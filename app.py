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
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-default-secret-key")

# --- Application Mode Configuration ---
APP_MODE = os.environ.get("APP_MODE", "stateful").lower()

def get_db_choice():
    """Determines the database choice based on the application mode."""
    if APP_MODE == 'stateless':
        # In stateless mode, check query params (for GET) or form data (for POST)
        if request.method == 'POST':
            return request.form.get('db', get_db_choice.last_get)
        # Persist the db choice for the duration of the request
        get_db_choice.last_get = request.args.get('db', 'postgres')
        return get_db_choice.last_get
    else:
        # In stateful mode, we use the session.
        return session.get('db', 'postgres')
get_db_choice.last_get = 'postgres'

@app.context_processor
def inject_shared_vars():
    """Injects variables needed in all templates."""
    return dict(APP_MODE=APP_MODE, db=get_db_choice())

# --- Database Selection (Stateful Mode Only) ---
@app.route('/select_db', methods=['POST'])
def select_db():
    if APP_MODE != 'stateful':
        return jsonify(success=False, message="Endpoint only available in stateful mode."), 400
    data = request.get_json()
    db_choice = data.get('db')
    if db_choice in ['postgres', 'spanner', 'dual']:
        session['db'] = db_choice
        return jsonify(success=True, message=f"Database switched to {db_choice}")
    return jsonify(success=False, message="Invalid database choice"), 400

# --- Database Initialization ---
SPANNER_PROJECT_ID = os.environ.get("SPANNER_PROJECT_ID")
SPANNER_INSTANCE_ID = os.environ.get("SPANNER_INSTANCE_ID")
SPANNER_DATABASE_ID = os.environ.get("SPANNER_DATABASE_ID")

spanner_client, spanner_database = None, None
try:
    spanner_client = spanner.Client(project=SPANNER_PROJECT_ID)
    spanner_instance = spanner_client.instance(SPANNER_INSTANCE_ID)
    spanner_database = spanner_instance.database(SPANNER_DATABASE_ID)
except Exception as e:
    app.logger.error(f"Failed to initialize Spanner client: {e}")

def get_postgres_connection():
    try:
        return psycopg2.connect(
            host=os.environ.get("DB_HOST"), database=os.environ.get("DB_NAME"),
            user=os.environ.get("DB_USER"), password=os.environ.get("DB_PASSWORD")
        )
    except psycopg2.OperationalError as e:
        app.logger.error(f"Could not connect to Cloud SQL: {e}")
        return None

# --- Data Access Layer ---
def get_db_for_read():
    db_choice = get_db_choice()
    if db_choice == 'spanner':
        if not spanner_database: raise Exception("Spanner DB not configured.")
        return spanner_database
    else:
        return get_postgres_connection()

def get_all(table_name):
    db_conn = get_db_for_read()
    if get_db_choice() == 'spanner':
        with db_conn.snapshot() as snapshot:
            return [list(row) for row in snapshot.execute_sql(f"SELECT * FROM {table_name}")]
    else:
        with db_conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_name} ORDER BY 1;")
            items = cur.fetchall()
        db_conn.close()
        return items

def get_one(table_name, id_column, item_id):
    db_conn = get_db_for_read()
    if get_db_choice() == 'spanner':
        with db_conn.snapshot() as snapshot:
            cols = {
                'products': ['product_id', 'name', 'category', 'price', 'description'],
                'employees': ['employee_id', 'first_name', 'last_name', 'position', 'hire_date'],
                'customers': ['customer_id', 'first_name', 'last_name', 'email', 'join_date']
            }.get(table_name, [])

            key_set = spanner.KeySet(keys=[[item_id]])
            results = snapshot.read(table=table_name, columns=cols, keyset=key_set)
            try:
                return list(next(results))
            except StopIteration:
                return None
    else:
        with db_conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_name} WHERE {id_column} = %s", (item_id,))
            item = cur.fetchone()
        db_conn.close()
        return item

# --- Main Route ---
@app.route('/')
def index():
    query = "SELECT so.order_id, p.name, e.first_name, c.first_name, so.quantity, so.total_price, so.order_date FROM sales_orders so JOIN products p ON so.product_id = p.product_id JOIN employees e ON so.employee_id = e.employee_id LEFT JOIN customers c ON so.customer_id = c.customer_id ORDER BY so.order_date DESC"
    db_conn = get_db_for_read()
    if get_db_choice() == 'spanner':
        with db_conn.snapshot() as snapshot:
            orders = [list(row) for row in snapshot.execute_sql(query)]
    else:
        with db_conn.cursor() as cur:
            cur.execute(query)
            orders = cur.fetchall()
        db_conn.close()
    return render_template('index.html', sales_orders=orders)

# --- Product Routes ---
@app.route('/products')
def list_products():
    return render_template('products.html', products=get_all('products'))

@app.route('/products/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        db_mode = get_db_choice()
        name, category, price, desc = request.form['name'], request.form['category'], float(request.form['price']), request.form['description']

        if db_mode == 'postgres':
            conn = get_postgres_connection()
            with conn.cursor() as cur: cur.execute("INSERT INTO products (name, category, price, description) VALUES (%s, %s, %s, %s)", (name, category, price, desc))
            conn.commit()
            conn.close()
        elif db_mode == 'spanner':
            def _insert(t):
                res = t.execute_sql("SELECT MAX(product_id) FROM products")
                new_id = (list(res)[0][0] or 0) + 1
                t.execute_update("INSERT INTO products (product_id, name, category, price, description) VALUES (@id, @name, @cat, @price, @desc)", params={"id": new_id, "name": name, "cat": category, "price": price, "desc": desc}, param_types={"id": spanner.param_types.INT64, "name": spanner.param_types.STRING, "cat": spanner.param_types.STRING, "price": spanner.param_types.FLOAT64, "desc": spanner.param_types.STRING})
            spanner_database.run_in_transaction(_insert)
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                with pg_conn.cursor() as cur:
                    cur.execute("INSERT INTO products (name, category, price, description) VALUES (%s, %s, %s, %s) RETURNING product_id", (name, category, price, desc))
                    new_id = cur.fetchone()[0]
                def _dual_insert(t): t.execute_update("INSERT INTO products (product_id, name, category, price, description) VALUES (@id, @name, @cat, @price, @desc)", params={"id": new_id, "name": name, "cat": category, "price": price, "desc": desc}, param_types={"id": spanner.param_types.INT64, "name": spanner.param_types.STRING, "cat": spanner.param_types.STRING, "price": spanner.param_types.FLOAT64, "desc": spanner.param_types.STRING})
                spanner_database.run_in_transaction(_dual_insert)
                pg_conn.commit()
            except Exception as e: pg_conn.rollback(); raise e
            finally: pg_conn.close()

        return redirect(url_for('list_products', db=db_mode))
    return render_template('add_product.html')

@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if request.method == 'POST':
        db_mode = get_db_choice()
        name, category, price, desc = request.form['name'], request.form['category'], float(request.form['price']), request.form['description']

        def update_pg():
            conn = get_postgres_connection()
            with conn.cursor() as cur: cur.execute("UPDATE products SET name=%s, category=%s, price=%s, description=%s WHERE product_id=%s", (name, category, price, desc, product_id))
            conn.commit()
            conn.close()
        def update_spanner():
            def _update(t): t.execute_update("UPDATE products SET name=@name, category=@cat, price=@price, description=@desc WHERE product_id=@id", params={"id": product_id, "name": name, "cat": category, "price": price, "desc": desc}, param_types={"id": spanner.param_types.INT64, "name": spanner.param_types.STRING, "cat": spanner.param_types.STRING, "price": spanner.param_types.FLOAT64, "desc": spanner.param_types.STRING})
            spanner_database.run_in_transaction(_update)

        if db_mode == 'postgres': update_pg()
        elif db_mode == 'spanner': update_spanner()
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                with pg_conn.cursor() as cur: cur.execute("UPDATE products SET name=%s, category=%s, price=%s, description=%s WHERE product_id=%s", (name, category, price, desc, product_id))
                update_spanner()
                pg_conn.commit()
            except Exception as e: pg_conn.rollback(); raise e
            finally: pg_conn.close()
        return redirect(url_for('list_products', db=db_mode))

    product = get_one('products', 'product_id', product_id)
    if product is None: return "Product not found", 404
    return render_template('edit_product.html', product=product)

@app.route('/products/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    db_mode = get_db_choice()
    def del_pg():
        conn = get_postgres_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sales_orders WHERE product_id = %s", (product_id,))
            cur.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
        conn.commit()
        conn.close()
    def del_spanner():
        def _delete(t):
            t.execute_update("DELETE FROM sales_orders WHERE product_id = @id", params={"id": product_id}, param_types={"id": spanner.param_types.INT64})
            t.execute_update("DELETE FROM products WHERE product_id = @id", params={"id": product_id}, param_types={"id": spanner.param_types.INT64})
        spanner_database.run_in_transaction(_delete)

    if db_mode == 'postgres': del_pg()
    elif db_mode == 'spanner': del_spanner()
    elif db_mode == 'dual':
        pg_conn = get_postgres_connection()
        try:
            with pg_conn.cursor() as cur:
                cur.execute("DELETE FROM sales_orders WHERE product_id = %s", (product_id,))
                cur.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
            del_spanner()
            pg_conn.commit()
        except Exception as e: pg_conn.rollback(); raise e
        finally: pg_conn.close()
    return redirect(url_for('list_products', db=db_mode))

# --- Employee Routes ---
@app.route('/employees')
def list_employees():
    return render_template('employees.html', employees=get_all('employees'))

@app.route('/employees/add', methods=['GET', 'POST'])
def add_employee():
    if request.method == 'POST':
        db_mode = get_db_choice()
        first, last, pos, hire_str = request.form['first_name'], request.form['last_name'], request.form['position'], request.form['hire_date']
        hire_date = date.fromisoformat(hire_str)

        if db_mode == 'postgres':
            conn = get_postgres_connection()
            with conn.cursor() as cur: cur.execute("INSERT INTO employees (first_name, last_name, position, hire_date) VALUES (%s, %s, %s, %s)", (first, last, pos, hire_date))
            conn.commit()
            conn.close()
        elif db_mode == 'spanner':
            def _insert(t):
                res = t.execute_sql("SELECT MAX(employee_id) FROM employees")
                new_id = (list(res)[0][0] or 0) + 1
                t.execute_update("INSERT INTO employees (employee_id, first_name, last_name, position, hire_date) VALUES (@id, @first, @last, @pos, @hire)", params={"id": new_id, "first": first, "last": last, "pos": pos, "hire": hire_str}, param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING, "pos": spanner.param_types.STRING, "hire": spanner.param_types.DATE})
            spanner_database.run_in_transaction(_insert)
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                with pg_conn.cursor() as cur:
                    cur.execute("INSERT INTO employees (first_name, last_name, position, hire_date) VALUES (%s, %s, %s, %s) RETURNING employee_id", (first, last, pos, hire_date))
                    new_id = cur.fetchone()[0]
                def _dual_insert(t): t.execute_update("INSERT INTO employees (employee_id, first_name, last_name, position, hire_date) VALUES (@id, @first, @last, @pos, @hire)", params={"id": new_id, "first": first, "last": last, "pos": pos, "hire": hire_str}, param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING, "pos": spanner.param_types.STRING, "hire": spanner.param_types.DATE})
                spanner_database.run_in_transaction(_dual_insert)
                pg_conn.commit()
            except Exception as e: pg_conn.rollback(); raise e
            finally: pg_conn.close()
        return redirect(url_for('list_employees', db=db_mode))
    return render_template('add_employee.html')

@app.route('/employees/edit/<int:employee_id>', methods=['GET', 'POST'])
def edit_employee(employee_id):
    if request.method == 'POST':
        db_mode = get_db_choice()
        first, last, pos, hire_str = request.form['first_name'], request.form['last_name'], request.form['position'], request.form['hire_date']
        hire_date = date.fromisoformat(hire_str)

        def update_pg():
            conn = get_postgres_connection()
            with conn.cursor() as cur: cur.execute("UPDATE employees SET first_name=%s, last_name=%s, position=%s, hire_date=%s WHERE employee_id=%s", (first, last, pos, hire_date, employee_id))
            conn.commit()
            conn.close()
        def update_spanner():
            def _update(t): t.execute_update("UPDATE employees SET first_name=@first, last_name=@last, position=@pos, hire_date=@hire WHERE employee_id=@id", params={"id": employee_id, "first": first, "last": last, "pos": pos, "hire": hire_str}, param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING, "pos": spanner.param_types.STRING, "hire": spanner.param_types.DATE})
            spanner_database.run_in_transaction(_update)

        if db_mode == 'postgres': update_pg()
        elif db_mode == 'spanner': update_spanner()
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                with pg_conn.cursor() as cur: cur.execute("UPDATE employees SET first_name=%s, last_name=%s, position=%s, hire_date=%s WHERE employee_id=%s", (first, last, pos, hire_date, employee_id))
                update_spanner()
                pg_conn.commit()
            except Exception as e: pg_conn.rollback(); raise e
            finally: pg_conn.close()
        return redirect(url_for('list_employees', db=db_mode))

    employee = get_one('employees', 'employee_id', employee_id)
    return render_template('edit_employee.html', employee=employee)

@app.route('/employees/delete/<int:employee_id>', methods=['POST'])
def delete_employee(employee_id):
    db_mode = get_db_choice()
    def del_pg():
        conn = get_postgres_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sales_orders WHERE employee_id = %s", (employee_id,))
            cur.execute("DELETE FROM employees WHERE employee_id = %s", (employee_id,))
        conn.commit()
        conn.close()
    def del_spanner():
        def _delete(t):
            t.execute_update("DELETE FROM sales_orders WHERE employee_id = @id", params={"id": employee_id}, param_types={"id": spanner.param_types.INT64})
            t.execute_update("DELETE FROM employees WHERE employee_id = @id", params={"id": employee_id}, param_types={"id": spanner.param_types.INT64})
        spanner_database.run_in_transaction(_delete)

    if db_mode == 'postgres': del_pg()
    elif db_mode == 'spanner': del_spanner()
    elif db_mode == 'dual':
        pg_conn = get_postgres_connection()
        try:
            with pg_conn.cursor() as cur:
                cur.execute("DELETE FROM sales_orders WHERE employee_id = %s", (employee_id,))
                cur.execute("DELETE FROM employees WHERE employee_id = %s", (employee_id,))
            del_spanner()
            pg_conn.commit()
        except Exception as e: pg_conn.rollback(); raise e
        finally: pg_conn.close()
    return redirect(url_for('list_employees', db=db_mode))

# --- Customer Routes ---
@app.route('/customers')
def list_customers():
    return render_template('customers.html', customers=get_all('customers'))

@app.route('/customers/add', methods=['GET', 'POST'])
def add_customer():
    if request.method == 'POST':
        db_mode = get_db_choice()
        first, last, email, join_str = request.form['first_name'], request.form['last_name'], request.form['email'], request.form['join_date']
        join_date = date.fromisoformat(join_str)

        if db_mode == 'postgres':
            conn = get_postgres_connection()
            with conn.cursor() as cur: cur.execute("INSERT INTO customers (first_name, last_name, email, join_date) VALUES (%s, %s, %s, %s)", (first, last, email, join_date))
            conn.commit()
            conn.close()
        elif db_mode == 'spanner':
            def _insert(t):
                res = t.execute_sql("SELECT MAX(customer_id) FROM customers")
                new_id = (list(res)[0][0] or 0) + 1
                t.execute_update("INSERT INTO customers (customer_id, first_name, last_name, email, join_date) VALUES (@id, @first, @last, @email, @join)", params={"id": new_id, "first": first, "last": last, "email": email, "join": join_str}, param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING, "email": spanner.param_types.STRING, "join": spanner.param_types.DATE})
            spanner_database.run_in_transaction(_insert)
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                with pg_conn.cursor() as cur:
                    cur.execute("INSERT INTO customers (first_name, last_name, email, join_date) VALUES (%s, %s, %s, %s) RETURNING customer_id", (first, last, email, join_date))
                    new_id = cur.fetchone()[0]
                def _dual_insert(t): t.execute_update("INSERT INTO customers (customer_id, first_name, last_name, email, join_date) VALUES (@id, @first, @last, @email, @join)", params={"id": new_id, "first": first, "last": last, "email": email, "join": join_str}, param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING, "email": spanner.param_types.STRING, "join": spanner.param_types.DATE})
                spanner_database.run_in_transaction(_dual_insert)
                pg_conn.commit()
            except Exception as e: pg_conn.rollback(); raise e
            finally: pg_conn.close()
        return redirect(url_for('list_customers', db=db_mode))
    return render_template('add_customer.html')

@app.route('/customers/edit/<int:customer_id>', methods=['GET', 'POST'])
def edit_customer(customer_id):
    if request.method == 'POST':
        db_mode = get_db_choice()
        first, last, email, join_str = request.form['first_name'], request.form['last_name'], request.form['email'], request.form['join_date']
        join_date = date.fromisoformat(join_str)

        def update_pg():
            conn = get_postgres_connection()
            with conn.cursor() as cur: cur.execute("UPDATE customers SET first_name=%s, last_name=%s, email=%s, join_date=%s WHERE customer_id=%s", (first, last, email, join_date, customer_id))
            conn.commit()
            conn.close()
        def update_spanner():
            def _update(t): t.execute_update("UPDATE customers SET first_name=@first, last_name=@last, email=@email, join_date=@join WHERE customer_id=@id", params={"id": customer_id, "first": first, "last": last, "email": email, "join": join_str}, param_types={"id": spanner.param_types.INT64, "first": spanner.param_types.STRING, "last": spanner.param_types.STRING, "email": spanner.param_types.STRING, "join": spanner.param_types.DATE})
            spanner_database.run_in_transaction(_update)

        if db_mode == 'postgres': update_pg()
        elif db_mode == 'spanner': update_spanner()
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                with pg_conn.cursor() as cur: cur.execute("UPDATE customers SET first_name=%s, last_name=%s, email=%s, join_date=%s WHERE customer_id=%s", (first, last, email, join_date, customer_id))
                update_spanner()
                pg_conn.commit()
            except Exception as e: pg_conn.rollback(); raise e
            finally: pg_conn.close()
        return redirect(url_for('list_customers', db=db_mode))
    customer = get_one('customers', 'customer_id', customer_id)
    return render_template('edit_customer.html', customer=customer)

@app.route('/customers/delete/<int:customer_id>', methods=['POST'])
def delete_customer(customer_id):
    db_mode = get_db_choice()
    def del_pg():
        conn = get_postgres_connection()
        with conn.cursor() as cur:
            cur.execute("UPDATE sales_orders SET customer_id = NULL WHERE customer_id = %s", (customer_id,))
            cur.execute("DELETE FROM customers WHERE customer_id = %s", (customer_id,))
        conn.commit()
        conn.close()
    def del_spanner():
        def _delete(t):
            orders_to_update = t.execute_sql("SELECT order_id FROM sales_orders WHERE customer_id = @id", params={"id": customer_id}, param_types={"id": spanner.param_types.INT64})
            for order in orders_to_update:
                t.execute_update("UPDATE sales_orders SET customer_id = NULL WHERE order_id = @order_id", params={"order_id": order[0]}, param_types={"order_id": spanner.param_types.INT64})
            t.execute_update("DELETE FROM customers WHERE customer_id = @id", params={"id": customer_id}, param_types={"id": spanner.param_types.INT64})
        spanner_database.run_in_transaction(_delete)

    if db_mode == 'postgres': del_pg()
    elif db_mode == 'spanner': del_spanner()
    elif db_mode == 'dual':
        pg_conn = get_postgres_connection()
        try:
            with pg_conn.cursor() as cur:
                cur.execute("UPDATE sales_orders SET customer_id = NULL WHERE customer_id = %s", (customer_id,))
                cur.execute("DELETE FROM customers WHERE customer_id = %s", (customer_id,))
            del_spanner()
            pg_conn.commit()
        except Exception as e: pg_conn.rollback(); raise e
        finally: pg_conn.close()
    return redirect(url_for('list_customers', db=db_mode))

# --- Sales Order Routes ---
@app.route('/sales/add', methods=['GET', 'POST'])
def add_sale():
    if request.method == 'POST':
        db_mode = get_db_choice()
        product_id, qty, emp_id = int(request.form['product_id']), int(request.form['quantity']), int(request.form['employee_id'])
        cust_id = int(request.form['customer_id']) if request.form.get('customer_id') else None
        total = float(request.form['total_price'])

        if db_mode == 'postgres':
            conn = get_postgres_connection()
            with conn.cursor() as cur: cur.execute("INSERT INTO sales_orders (product_id, quantity, employee_id, customer_id, total_price) VALUES (%s, %s, %s, %s, %s)", (product_id, qty, emp_id, cust_id, total))
            conn.commit()
            conn.close()
        elif db_mode == 'spanner':
            def _insert(t):
                res = t.execute_sql("SELECT MAX(order_id) FROM sales_orders")
                new_id = (list(res)[0][0] or 0) + 1
                t.execute_update("INSERT INTO sales_orders (order_id, product_id, quantity, employee_id, customer_id, total_price, order_date) VALUES (@oid, @pid, @qty, @eid, @cid, @price, PENDING_COMMIT_TIMESTAMP())", params={"oid": new_id, "pid": product_id, "qty": qty, "eid": emp_id, "cid": cust_id, "price": total}, param_types={"oid": spanner.param_types.INT64, "pid": spanner.param_types.INT64, "qty": spanner.param_types.INT64, "eid": spanner.param_types.INT64, "cid": spanner.param_types.INT64, "price": spanner.param_types.FLOAT64})
            spanner_database.run_in_transaction(_insert)
        elif db_mode == 'dual':
            pg_conn = get_postgres_connection()
            try:
                with pg_conn.cursor() as cur:
                    cur.execute("INSERT INTO sales_orders (product_id, quantity, employee_id, customer_id, total_price) VALUES (%s, %s, %s, %s, %s) RETURNING order_id", (product_id, qty, emp_id, cust_id, total))
                    new_id = cur.fetchone()[0]
                def _dual_insert(t): t.execute_update("INSERT INTO sales_orders (order_id, product_id, quantity, employee_id, customer_id, total_price, order_date) VALUES (@oid, @pid, @qty, @eid, @cid, @price, PENDING_COMMIT_TIMESTAMP())", params={"oid": new_id, "pid": product_id, "qty": qty, "eid": emp_id, "cid": cust_id, "price": total}, param_types={"oid": spanner.param_types.INT64, "pid": spanner.param_types.INT64, "qty": spanner.param_types.INT64, "eid": spanner.param_types.INT64, "cid": spanner.param_types.INT64, "price": spanner.param_types.FLOAT64})
                spanner_database.run_in_transaction(_dual_insert)
                pg_conn.commit()
            except Exception as e: pg_conn.rollback(); raise e
            finally: pg_conn.close()

        return redirect(url_for('index', db=db_mode))

    return render_template('add_sale.html', products=get_all('products'), employees=get_all('employees'), customers=get_all('customers'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=False)