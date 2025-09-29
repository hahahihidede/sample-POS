import os
import psycopg2
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
from google.cloud import spanner
from google.api_core.exceptions import GoogleAPICallError

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# A secret key is required for using sessions
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-default-secret-key")

# --- Database Selection ---
@app.before_request
def before_request():
    """Set default database in session if not already set."""
    if 'db' not in session:
        session['db'] = 'postgres' # Default to PostgreSQL

@app.route('/select_db', methods=['POST'])
def select_db():
    """Endpoint to switch the active database."""
    data = request.get_json()
    db_choice = data.get('db')
    if db_choice in ['postgres', 'spanner', 'dual']:
        session['db'] = db_choice
        return jsonify(success=True, message=f"Database switched to {db_choice}")
    return jsonify(success=False, message="Invalid database choice"), 400

# --- Spanner Configuration ---
SPANNER_PROJECT_ID = os.environ.get("SPANNER_PROJECT_ID")
SPANNER_INSTANCE_ID = os.environ.get("SPANNER_INSTANCE_ID")
SPANNER_DATABASE_ID = os.environ.get("SPANNER_DATABASE_ID")

spanner_client = None
spanner_database = None
try:
    spanner_client = spanner.Client(project=SPANNER_PROJECT_ID)
    spanner_instance = spanner_client.instance(SPANNER_INSTANCE_ID)
    spanner_database = spanner_instance.database(SPANNER_DATABASE_ID)
except Exception as e:
    app.logger.error(f"Failed to initialize Spanner client: {e}")

# --- Cloud SQL (PostgreSQL) Configuration ---
def get_postgres_connection():
    """Establishes a connection to the Cloud SQL for PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST"),
            database=os.environ.get("DB_NAME"),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD")
        )
        return conn
    except psycopg2.OperationalError as e:
        app.logger.error(f"Could not connect to Cloud SQL: {e}")
        return None

# --- Data Access Layer ---
def get_db_for_read():
    """Returns the appropriate database connection/client for read operations."""
    # For 'postgres' or 'dual' mode, we read from PostgreSQL.
    if session.get('db') == 'spanner':
        if not spanner_database:
            raise Exception("Spanner database is not configured or available.")
        return spanner_database
    else:
        return get_postgres_connection()

# --- Generic Read Operations ---
def get_all(table_name):
    """Fetches all records from a given table based on the selected DB for reads."""
    db_conn = get_db_for_read()
    if session.get('db') == 'spanner':
        with db_conn.snapshot() as snapshot:
            results = snapshot.execute_sql(f"SELECT * FROM {table_name}")
            # Spanner returns an iterator; convert it to a list for consistent output.
            return [list(row) for row in results]
    else: # postgres or dual
        cur = db_conn.cursor()
        cur.execute(f"SELECT * FROM {table_name} ORDER BY 1;")
        items = cur.fetchall()
        cur.close()
        db_conn.close()
        return items

# --- Sales Orders Logic ---
def get_sales_orders():
    """Fetches all sales orders with details from the selected database."""
    db_conn = get_db_for_read()
    # This query is compatible with both PostgreSQL and Spanner.
    query = """
        SELECT so.order_id, p.name as product_name, e.first_name as employee_name,
               c.first_name as customer_name, so.quantity, so.total_price, so.order_date
        FROM sales_orders so
        JOIN products p ON so.product_id = p.product_id
        JOIN employees e ON so.employee_id = e.employee_id
        LEFT JOIN customers c ON so.customer_id = c.customer_id
        ORDER BY so.order_date DESC
    """
    if session.get('db') == 'spanner':
        with db_conn.snapshot() as snapshot:
            return [list(row) for row in snapshot.execute_sql(query)]
    else: # postgres or dual
        cur = db_conn.cursor()
        cur.execute(query)
        orders = cur.fetchall()
        cur.close()
        db_conn.close()
        return orders

# --- Main Route ---
@app.route('/')
def index():
    """Displays the main page with sales orders."""
    try:
        orders = get_sales_orders()
        return render_template('index.html', sales_orders=orders, db=session.get('db'))
    except Exception as e:
        app.logger.error(f"Failed to fetch data for index page: {e}")
        return f"An error occurred: {e}", 500

# --- Products Management ---
@app.route('/products')
def list_products():
    products = get_all('products')
    return render_template('products.html', products=products, db=session.get('db'))

# --- Generic Single-Item Read Operation ---
def get_one(table_name, id_column, item_id):
    """Fetches a single record from a table by its ID."""
    db_conn = get_db_for_read()
    if session.get('db') == 'spanner':
        with db_conn.snapshot() as snapshot:
            key_set = spanner.KeySet(keys=[[item_id]])
            results = snapshot.read(table=table_name, columns=(id_column, 'name', 'category', 'price', 'description'), keyset=key_set)
            # Read returns an iterator, get the first result
            try:
                return list(next(results))
            except StopIteration:
                return None
    else: # postgres or dual
        cur = db_conn.cursor()
        cur.execute(f"SELECT * FROM {table_name} WHERE {id_column} = %s", (item_id,))
        item = cur.fetchone()
        cur.close()
        db_conn.close()
        return item

@app.route('/products/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        try:
            name = request.form['name']
            category = request.form['category']
            price = float(request.form['price'])
            description = request.form['description']
            db_mode = session.get('db')

            # --- PostgreSQL Only ---
            if db_mode == 'postgres':
                conn = get_postgres_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO products (name, category, price, description) VALUES (%s, %s, %s, %s)",
                            (name, category, price, description))
                conn.commit()
                cur.close()
                conn.close()

            # --- Spanner Only ---
            elif db_mode == 'spanner':
                def insert_spanner(transaction):
                    res = transaction.execute_sql("SELECT MAX(product_id) FROM products")
                    max_id = list(res)[0][0] or 0
                    new_id = max_id + 1
                    transaction.execute_update(
                        "INSERT INTO products (product_id, name, category, price, description) VALUES (@id, @name, @cat, @price, @desc)",
                        params={"id": new_id, "name": name, "cat": category, "price": price, "desc": description},
                        param_types={"id": spanner.param_types.INT64, "name": spanner.param_types.STRING, "cat": spanner.param_types.STRING,
                                     "price": spanner.param_types.FLOAT64, "desc": spanner.param_types.STRING}
                    )
                spanner_database.run_in_transaction(insert_spanner)

            # --- Dual Write ---
            elif db_mode == 'dual':
                pg_conn = get_postgres_connection()
                try:
                    # 1. Insert into PostgreSQL and get the new ID
                    cur = pg_conn.cursor()
                    cur.execute("INSERT INTO products (name, category, price, description) VALUES (%s, %s, %s, %s) RETURNING product_id",
                                (name, category, price, description))
                    new_id = cur.fetchone()[0]
                    cur.close()

                    # 2. Insert into Spanner with the same ID
                    def dual_insert_spanner(transaction):
                        transaction.execute_update(
                            "INSERT INTO products (product_id, name, category, price, description) VALUES (@id, @name, @cat, @price, @desc)",
                            params={"id": new_id, "name": name, "cat": category, "price": price, "desc": description},
                            param_types={"id": spanner.param_types.INT64, "name": spanner.param_types.STRING, "cat": spanner.param_types.STRING,
                                         "price": spanner.param_types.FLOAT64, "desc": spanner.param_types.STRING}
                        )
                    spanner_database.run_in_transaction(dual_insert_spanner)

                    # 3. If both succeed, commit the PostgreSQL transaction
                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    raise e # Re-raise the exception to be caught below
                finally:
                    pg_conn.close()

            return redirect(url_for('list_products'))
        except Exception as e:
            app.logger.error(f"Error adding product in '{session.get('db')}' mode: {e}")
            return f"An error occurred: {e}", 500

    return render_template('add_product.html', db=session.get('db'))

@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    """Edits an existing product."""
    if request.method == 'POST':
        try:
            name = request.form['name']
            category = request.form['category']
            price = float(request.form['price'])
            description = request.form['description']
            db_mode = session.get('db')

            def update_postgres():
                conn = get_postgres_connection()
                cur = conn.cursor()
                cur.execute("UPDATE products SET name=%s, category=%s, price=%s, description=%s WHERE product_id=%s",
                            (name, category, price, description, product_id))
                conn.commit()
                cur.close()
                conn.close()

            def update_spanner():
                def _update(transaction):
                    transaction.execute_update(
                        "UPDATE products SET name=@name, category=@cat, price=@price, description=@desc WHERE product_id=@id",
                        params={"id": product_id, "name": name, "cat": category, "price": price, "desc": description},
                        param_types={"id": spanner.param_types.INT64, "name": spanner.param_types.STRING, "cat": spanner.param_types.STRING,
                                     "price": spanner.param_types.FLOAT64, "desc": spanner.param_types.STRING}
                    )
                spanner_database.run_in_transaction(_update)

            if db_mode == 'postgres':
                update_postgres()
            elif db_mode == 'spanner':
                update_spanner()
            elif db_mode == 'dual':
                pg_conn = get_postgres_connection()
                try:
                    cur = pg_conn.cursor()
                    cur.execute("UPDATE products SET name=%s, category=%s, price=%s, description=%s WHERE product_id=%s",
                                (name, category, price, description, product_id))
                    update_spanner()
                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    raise e
                finally:
                    pg_conn.close()

            return redirect(url_for('list_products'))
        except Exception as e:
            app.logger.error(f"Error editing product {product_id}: {e}")
            return f"An error occurred: {e}", 500

    product = get_one('products', 'product_id', product_id)
    if product is None:
        return "Product not found", 404
    return render_template('edit_product.html', product=product, db=session.get('db'))

@app.route('/products/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    """Deletes a product."""
    try:
        db_mode = session.get('db')

        def delete_postgres():
            conn = get_postgres_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
            conn.commit()
            cur.close()
            conn.close()

        def delete_spanner():
            def _delete(transaction):
                transaction.execute_update("DELETE FROM products WHERE product_id = @id",
                                           params={"id": product_id},
                                           param_types={"id": spanner.param_types.INT64})
            spanner_database.run_in_transaction(_delete)

        if db_mode == 'postgres':
            delete_postgres()
        elif db_mode == 'spanner':
            delete_spanner()
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                cur = pg_conn.cursor()
                # Must delete from sales_orders first due to foreign key constraints in PostgreSQL
                cur.execute("DELETE FROM sales_orders WHERE product_id = %s", (product_id,))
                cur.execute("DELETE FROM products WHERE product_id = %s", (product_id,))

                # In Spanner, we need to handle this transactionally as well.
                # Note: Spanner doesn't enforce foreign keys, but for consistency, we delete from both.
                def dual_delete_spanner(transaction):
                    transaction.execute_update("DELETE FROM sales_orders WHERE product_id = @id",
                                               params={"id": product_id}, param_types={"id": spanner.param_types.INT64})
                    transaction.execute_update("DELETE FROM products WHERE product_id = @id",
                                               params={"id": product_id}, param_types={"id": spanner.param_types.INT64})
                spanner_database.run_in_transaction(dual_delete_spanner)

                pg_conn.commit()
            except Exception as e:
                pg_conn.rollback()
                raise e
            finally:
                pg_conn.close()

        return redirect(url_for('list_products'))
    except Exception as e:
        app.logger.error(f"Error deleting product {product_id}: {e}")
        return f"An error occurred: {e}", 500

# --- Employees Management ---
@app.route('/employees')
def list_employees():
    employees = get_all('employees')
    return render_template('employees.html', employees=employees, db=session.get('db'))

@app.route('/employees/add', methods=['GET', 'POST'])
def add_employee():
    if request.method == 'POST':
        try:
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            position = request.form['position']
            hire_date_str = request.form['hire_date']
            hire_date = date.fromisoformat(hire_date_str)
            db_mode = session.get('db')

            # --- PostgreSQL Only ---
            if db_mode == 'postgres':
                conn = get_postgres_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO employees (first_name, last_name, position, hire_date) VALUES (%s, %s, %s, %s)",
                            (first_name, last_name, position, hire_date))
                conn.commit()
                cur.close()
                conn.close()

            # --- Spanner Only ---
            elif db_mode == 'spanner':
                def insert_spanner(transaction):
                    res = transaction.execute_sql("SELECT MAX(employee_id) FROM employees")
                    max_id = list(res)[0][0] or 0
                    new_id = max_id + 1
                    transaction.execute_update(
                        "INSERT INTO employees (employee_id, first_name, last_name, position, hire_date) VALUES (@id, @first, @last, @pos, @hire)",
                        params={"id": new_id, "first": first_name, "last": last_name, "pos": position, "hire": hire_date_str},
                        param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING,
                                     "pos": spanner.param_types.STRING, "hire": spanner.param_types.DATE}
                    )
                spanner_database.run_in_transaction(insert_spanner)

            # --- Dual Write ---
            elif db_mode == 'dual':
                pg_conn = get_postgres_connection()
                try:
                    cur = pg_conn.cursor()
                    cur.execute("INSERT INTO employees (first_name, last_name, position, hire_date) VALUES (%s, %s, %s, %s) RETURNING employee_id",
                                (first_name, last_name, position, hire_date))
                    new_id = cur.fetchone()[0]
                    cur.close()

                    def dual_insert_spanner(transaction):
                        transaction.execute_update(
                            "INSERT INTO employees (employee_id, first_name, last_name, position, hire_date) VALUES (@id, @first, @last, @pos, @hire)",
                            params={"id": new_id, "first": first_name, "last": last_name, "pos": position, "hire": hire_date_str},
                            param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING,
                                         "pos": spanner.param_types.STRING, "hire": spanner.param_types.DATE}
                        )
                    spanner_database.run_in_transaction(dual_insert_spanner)
                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    raise e
                finally:
                    pg_conn.close()

            return redirect(url_for('list_employees'))
        except Exception as e:
            app.logger.error(f"Error adding employee in '{session.get('db')}' mode: {e}")
            return f"An error occurred: {e}", 500

    return render_template('add_employee.html', db=session.get('db'))

@app.route('/employees/edit/<int:employee_id>', methods=['GET', 'POST'])
def edit_employee(employee_id):
    """Edits an existing employee."""
    if request.method == 'POST':
        try:
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            position = request.form['position']
            hire_date_str = request.form['hire_date']
            hire_date = date.fromisoformat(hire_date_str)
            db_mode = session.get('db')

            def update_postgres():
                conn = get_postgres_connection()
                cur = conn.cursor()
                cur.execute("UPDATE employees SET first_name=%s, last_name=%s, position=%s, hire_date=%s WHERE employee_id=%s",
                            (first_name, last_name, position, hire_date, employee_id))
                conn.commit()
                cur.close()
                conn.close()

            def update_spanner():
                def _update(transaction):
                    transaction.execute_update(
                        "UPDATE employees SET first_name=@first, last_name=@last, position=@pos, hire_date=@hire WHERE employee_id=@id",
                        params={"id": employee_id, "first": first_name, "last": last_name, "pos": position, "hire": hire_date_str},
                        param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING,
                                     "pos": spanner.param_types.STRING, "hire": spanner.param_types.DATE}
                    )
                spanner_database.run_in_transaction(_update)

            if db_mode == 'postgres':
                update_postgres()
            elif db_mode == 'spanner':
                update_spanner()
            elif db_mode == 'dual':
                pg_conn = get_postgres_connection()
                try:
                    cur = pg_conn.cursor()
                    cur.execute("UPDATE employees SET first_name=%s, last_name=%s, position=%s, hire_date=%s WHERE employee_id=%s",
                                (first_name, last_name, position, hire_date, employee_id))
                    update_spanner()
                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    raise e
                finally:
                    pg_conn.close()

            return redirect(url_for('list_employees'))
        except Exception as e:
            app.logger.error(f"Error editing employee {employee_id}: {e}")
            return f"An error occurred: {e}", 500

    # For GET request, fetch employee data and render the edit form
    employee = get_one('employees', 'employee_id', employee_id)
    if employee is None:
        return "Employee not found", 404
    return render_template('edit_employee.html', employee=employee, db=session.get('db'))

@app.route('/employees/delete/<int:employee_id>', methods=['POST'])
def delete_employee(employee_id):
    """Deletes an employee."""
    try:
        db_mode = session.get('db')

        def delete_postgres():
            conn = get_postgres_connection()
            cur = conn.cursor()
            # Must delete from sales_orders first
            cur.execute("DELETE FROM sales_orders WHERE employee_id = %s", (employee_id,))
            cur.execute("DELETE FROM employees WHERE employee_id = %s", (employee_id,))
            conn.commit()
            cur.close()
            conn.close()

        def delete_spanner():
            def _delete(transaction):
                transaction.execute_update("DELETE FROM sales_orders WHERE employee_id = @id",
                                           params={"id": employee_id}, param_types={"id": spanner.param_types.INT64})
                transaction.execute_update("DELETE FROM employees WHERE employee_id = @id",
                                           params={"id": employee_id}, param_types={"id": spanner.param_types.INT64})
            spanner_database.run_in_transaction(_delete)

        if db_mode == 'postgres':
            delete_postgres()
        elif db_mode == 'spanner':
            delete_spanner()
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                cur = pg_conn.cursor()
                cur.execute("DELETE FROM sales_orders WHERE employee_id = %s", (employee_id,))
                cur.execute("DELETE FROM employees WHERE employee_id = %s", (employee_id,))
                delete_spanner() # Spanner delete function already handles both tables
                pg_conn.commit()
            except Exception as e:
                pg_conn.rollback()
                raise e
            finally:
                pg_conn.close()

        return redirect(url_for('list_employees'))
    except Exception as e:
        app.logger.error(f"Error deleting employee {employee_id}: {e}")
        return f"An error occurred: {e}", 500

# --- Customers Management ---
@app.route('/customers')
def list_customers():
    customers = get_all('customers')
    return render_template('customers.html', customers=customers, db=session.get('db'))

@app.route('/customers/add', methods=['GET', 'POST'])
def add_customer():
    if request.method == 'POST':
        try:
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            email = request.form['email']
            join_date_str = request.form['join_date']
            join_date = date.fromisoformat(join_date_str)
            db_mode = session.get('db')

            # --- PostgreSQL Only ---
            if db_mode == 'postgres':
                conn = get_postgres_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO customers (first_name, last_name, email, join_date) VALUES (%s, %s, %s, %s)",
                            (first_name, last_name, email, join_date))
                conn.commit()
                cur.close()
                conn.close()

            # --- Spanner Only ---
            elif db_mode == 'spanner':
                def insert_spanner(transaction):
                    res = transaction.execute_sql("SELECT MAX(customer_id) FROM customers")
                    max_id = list(res)[0][0] or 0
                    new_id = max_id + 1
                    transaction.execute_update(
                        "INSERT INTO customers (customer_id, first_name, last_name, email, join_date) VALUES (@id, @first, @last, @email, @join)",
                        params={"id": new_id, "first": first_name, "last": last_name, "email": email, "join": join_date_str},
                        param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING,
                                     "email": spanner.param_types.STRING, "join": spanner.param_types.DATE}
                    )
                spanner_database.run_in_transaction(insert_spanner)

            # --- Dual Write ---
            elif db_mode == 'dual':
                pg_conn = get_postgres_connection()
                try:
                    cur = pg_conn.cursor()
                    cur.execute("INSERT INTO customers (first_name, last_name, email, join_date) VALUES (%s, %s, %s, %s) RETURNING customer_id",
                                (first_name, last_name, email, join_date))
                    new_id = cur.fetchone()[0]
                    cur.close()

                    def dual_insert_spanner(transaction):
                        transaction.execute_update(
                            "INSERT INTO customers (customer_id, first_name, last_name, email, join_date) VALUES (@id, @first, @last, @email, @join)",
                            params={"id": new_id, "first": first_name, "last": last_name, "email": email, "join": join_date_str},
                            param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING,
                                         "email": spanner.param_types.STRING, "join": spanner.param_types.DATE}
                        )
                    spanner_database.run_in_transaction(dual_insert_spanner)
                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    raise e
                finally:
                    pg_conn.close()

            return redirect(url_for('list_customers'))
        except Exception as e:
            app.logger.error(f"Error adding customer in '{session.get('db')}' mode: {e}")
            return f"An error occurred: {e}", 500

    return render_template('add_customer.html', db=session.get('db'))

@app.route('/customers/edit/<int:customer_id>', methods=['GET', 'POST'])
def edit_customer(customer_id):
    """Edits an existing customer."""
    if request.method == 'POST':
        try:
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            email = request.form['email']
            join_date_str = request.form['join_date']
            join_date = date.fromisoformat(join_date_str)
            db_mode = session.get('db')

            def update_postgres():
                conn = get_postgres_connection()
                cur = conn.cursor()
                cur.execute("UPDATE customers SET first_name=%s, last_name=%s, email=%s, join_date=%s WHERE customer_id=%s",
                            (first_name, last_name, email, join_date, customer_id))
                conn.commit()
                cur.close()
                conn.close()

            def update_spanner():
                def _update(transaction):
                    transaction.execute_update(
                        "UPDATE customers SET first_name=@first, last_name=@last, email=@email, join_date=@join WHERE customer_id=@id",
                        params={"id": customer_id, "first": first_name, "last": last_name, "email": email, "join": join_date_str},
                        param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING,
                                     "email": spanner.param_types.STRING, "join": spanner.param_types.DATE}
                    )
                spanner_database.run_in_transaction(_update)

            if db_mode == 'postgres':
                update_postgres()
            elif db_mode == 'spanner':
                update_spanner()
            elif db_mode == 'dual':
                pg_conn = get_postgres_connection()
                try:
                    cur = pg_conn.cursor()
                    cur.execute("UPDATE customers SET first_name=%s, last_name=%s, email=%s, join_date=%s WHERE customer_id=%s",
                                (first_name, last_name, email, join_date, customer_id))
                    update_spanner()
                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    raise e
                finally:
                    pg_conn.close()

            return redirect(url_for('list_customers'))
        except Exception as e:
            app.logger.error(f"Error editing customer {customer_id}: {e}")
            return f"An error occurred: {e}", 500

    customer = get_one('customers', 'customer_id', customer_id)
    if customer is None:
        return "Customer not found", 404
    return render_template('edit_customer.html', customer=customer, db=session.get('db'))

@app.route('/customers/delete/<int:customer_id>', methods=['POST'])
def delete_customer(customer_id):
    """Deletes a customer."""
    try:
        db_mode = session.get('db')

        def delete_postgres():
            conn = get_postgres_connection()
            cur = conn.cursor()
            # Update sales_orders to set customer_id to NULL
            cur.execute("UPDATE sales_orders SET customer_id = NULL WHERE customer_id = %s", (customer_id,))
            cur.execute("DELETE FROM customers WHERE customer_id = %s", (customer_id,))
            conn.commit()
            cur.close()
            conn.close()

        def delete_spanner():
            def _delete(transaction):
                # Spanner doesn't have cascading updates, so we find referencing orders and update them
                orders_to_update = transaction.execute_sql(
                    "SELECT order_id FROM sales_orders WHERE customer_id = @id",
                    params={"id": customer_id}, param_types={"id": spanner.param_types.INT64}
                )
                for order in orders_to_update:
                    transaction.execute_update(
                        "UPDATE sales_orders SET customer_id = NULL WHERE order_id = @order_id",
                        params={"order_id": order[0]}, param_types={"order_id": spanner.param_types.INT64}
                    )
                transaction.execute_update("DELETE FROM customers WHERE customer_id = @id",
                                           params={"id": customer_id}, param_types={"id": spanner.param_types.INT64})
            spanner_database.run_in_transaction(_delete)

        if db_mode == 'postgres':
            delete_postgres()
        elif db_mode == 'spanner':
            delete_spanner()
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                cur = pg_conn.cursor()
                cur.execute("UPDATE sales_orders SET customer_id = NULL WHERE customer_id = %s", (customer_id,))
                cur.execute("DELETE FROM customers WHERE customer_id = %s", (customer_id,))
                delete_spanner()
                pg_conn.commit()
            except Exception as e:
                pg_conn.rollback()
                raise e
            finally:
                pg_conn.close()

        return redirect(url_for('list_customers'))
    except Exception as e:
        app.logger.error(f"Error deleting customer {customer_id}: {e}")
        return f"An error occurred: {e}", 500

# --- Sales Order Management ---
@app.route('/sales/add', methods=['GET', 'POST'])
def add_sale():
    """Creates a new sales order."""
    if request.method == 'POST':
        try:
            product_id = int(request.form['product_id'])
            quantity = int(request.form['quantity'])
            employee_id = int(request.form['employee_id'])
            # Customer ID can be None if it's a guest
            customer_id = int(request.form['customer_id']) if request.form.get('customer_id') else None
            total_price = float(request.form['total_price'])
            db_mode = session.get('db')

            def insert_postgres():
                conn = get_postgres_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO sales_orders (product_id, quantity, employee_id, customer_id, total_price) VALUES (%s, %s, %s, %s, %s)",
                            (product_id, quantity, employee_id, customer_id, total_price))
                conn.commit()
                cur.close()
                conn.close()

            def insert_spanner(new_id=None):
                def _insert(transaction):
                    # If not in dual-write mode, generate a new ID for Spanner
                    if new_id is None:
                        res = transaction.execute_sql("SELECT MAX(order_id) FROM sales_orders")
                        max_id = list(res)[0][0] or 0
                        spanner_id = max_id + 1
                    else:
                        spanner_id = new_id

                    transaction.execute_update(
                        "INSERT INTO sales_orders (order_id, product_id, quantity, employee_id, customer_id, total_price, order_date) "
                        "VALUES (@oid, @pid, @qty, @eid, @cid, @price, PENDING_COMMIT_TIMESTAMP())",
                        params={"oid": spanner_id, "pid": product_id, "qty": quantity, "eid": employee_id, "cid": customer_id, "price": total_price},
                        param_types={"oid": spanner.param_types.INT64, "pid": spanner.param_types.INT64, "qty": spanner.param_types.INT64,
                                     "eid": spanner.param_types.INT64, "cid": spanner.param_types.INT64, "price": spanner.param_types.FLOAT64}
                    )
                spanner_database.run_in_transaction(_insert)

            if db_mode == 'postgres':
                insert_postgres()
            elif db_mode == 'spanner':
                insert_spanner()
            elif db_mode == 'dual':
                pg_conn = get_postgres_connection()
                try:
                    cur = pg_conn.cursor()
                    cur.execute("INSERT INTO sales_orders (product_id, quantity, employee_id, customer_id, total_price) VALUES (%s, %s, %s, %s, %s) RETURNING order_id",
                                (product_id, quantity, employee_id, customer_id, total_price))
                    new_order_id = cur.fetchone()[0]
                    cur.close()

                    insert_spanner(new_id=new_order_id)

                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    raise e
                finally:
                    pg_conn.close()

            return redirect(url_for('index'))
        except Exception as e:
            app.logger.error(f"Error adding sale in '{session.get('db')}' mode: {e}")
            return f"An error occurred: {e}", 500

    # For GET request, fetch data needed for the form dropdowns
    products = get_all('products')
    employees = get_all('employees')
    customers = get_all('customers')
    return render_template('add_sale.html', products=products, employees=employees, customers=customers, db=session.get('db'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=False)