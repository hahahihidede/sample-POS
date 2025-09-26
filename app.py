import os
import uuid
import psycopg2
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv
from google.cloud import spanner
from google.api_core.exceptions import GoogleAPICallError

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# --- Spanner Configuration ---
SPANNER_PROJECT_ID = os.environ.get("SPANNER_PROJECT_ID")
SPANNER_INSTANCE_ID = os.environ.get("SPANNER_INSTANCE_ID")
SPANNER_DATABASE_ID = os.environ.get("SPANNER_DATABASE_ID")

# Initialize Spanner client
try:
    spanner_client = spanner.Client(project=SPANNER_PROJECT_ID)
    spanner_instance = spanner_client.instance(SPANNER_INSTANCE_ID)
    spanner_database = spanner_instance.database(SPANNER_DATABASE_ID)
except Exception as e:
    app.logger.error(f"Failed to initialize Spanner client: {e}")
    spanner_client = None
    spanner_database = None

# --- Cloud SQL (PostgreSQL) Configuration ---
def get_cloudsql_connection():
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

# --- Read Operations (from Cloud SQL) ---
@app.route('/')
def index():
    """Displays all sales data from Cloud SQL."""
    conn = get_cloudsql_connection()
    if not conn:
        return "Error: Database connection could not be established.", 500

    cur = conn.cursor()
    cur.execute("SELECT sale_id, product_name, quantity, price_per_item, quantity * price_per_item AS total_price FROM sales ORDER BY sale_date DESC;")
    sales = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', sales=sales)

# --- Create Operation (Dual Write) ---
@app.route('/add', methods=('GET', 'POST'))
def add():
    """Adds a new sale to both Cloud SQL and Cloud Spanner."""
    if request.method == 'POST':
        product_name = request.form['product_name']
        quantity = int(request.form['quantity'])
        price_per_item = float(request.form['price_per_item'])
        sale_id = str(uuid.uuid4())

        # Dual-write transaction
        conn_sql = get_cloudsql_connection()
        if not conn_sql:
            return "Error: Cloud SQL connection failed.", 500
        cur_sql = conn_sql.cursor()

        try:
            # 1. Write to Cloud SQL
            cur_sql.execute(
                "INSERT INTO sales (sale_id, product_name, quantity, price_per_item) VALUES (%s, %s, %s, %s)",
                (sale_id, product_name, quantity, price_per_item)
            )

            # 2. Write to Cloud Spanner
            if not spanner_database:
                raise Exception("Spanner database not configured.")

            def insert_spanner(transaction):
                transaction.execute_update(
                    "INSERT INTO sales (sale_id, product_name, quantity, price_per_item, sale_date) "
                    "VALUES (@sale_id, @product_name, @quantity, @price_per_item, PENDING_COMMIT_TIMESTAMP())",
                    params={
                        "sale_id": sale_id,
                        "product_name": product_name,
                        "quantity": quantity,
                        "price_per_item": price_per_item,
                    },
                    param_types={
                        "sale_id": spanner.param_types.STRING,
                        "product_name": spanner.param_types.STRING,
                        "quantity": spanner.param_types.INT64,
                        "price_per_item": spanner.param_types.FLOAT64,
                    },
                )
            spanner_database.run_in_transaction(insert_spanner)

            # 3. Commit Cloud SQL transaction if both writes are successful
            conn_sql.commit()
            return redirect(url_for('index'))

        except (GoogleAPICallError, psycopg2.Error, Exception) as e:
            app.logger.error(f"Dual-write failed: {e}")
            conn_sql.rollback()
            return f"An error occurred: {e}", 500
        finally:
            cur_sql.close()
            conn_sql.close()

    return render_template('add.html')

# --- Update Operation (Dual Write) ---
@app.route('/edit/<sale_id>', methods=('GET', 'POST'))
def edit(sale_id):
    """Edits an existing sale in both databases."""
    conn_sql = get_cloudsql_connection()
    if not conn_sql:
        return "Error: Database connection failed.", 500

    cur_sql = conn_sql.cursor()
    cur_sql.execute("SELECT sale_id, product_name, quantity, price_per_item FROM sales WHERE sale_id = %s", (sale_id,))
    sale = cur_sql.fetchone()

    if request.method == 'POST':
        product_name = request.form['product_name']
        quantity = int(request.form['quantity'])
        price_per_item = float(request.form['price_per_item'])

        try:
            # 1. Update Cloud SQL
            cur_sql.execute(
                "UPDATE sales SET product_name = %s, quantity = %s, price_per_item = %s WHERE sale_id = %s",
                (product_name, quantity, price_per_item, sale_id)
            )

            # 2. Update Cloud Spanner
            if not spanner_database:
                raise Exception("Spanner database not configured.")

            def update_spanner(transaction):
                transaction.execute_update(
                    "UPDATE sales SET product_name = @product_name, quantity = @quantity, price_per_item = @price_per_item "
                    "WHERE sale_id = @sale_id",
                    params={
                        "sale_id": sale_id,
                        "product_name": product_name,
                        "quantity": quantity,
                        "price_per_item": price_per_item,
                    },
                    param_types={
                        "sale_id": spanner.param_types.STRING,
                        "product_name": spanner.param_types.STRING,
                        "quantity": spanner.param_types.INT64,
                        "price_per_item": spanner.param_types.FLOAT64,
                    },
                )
            spanner_database.run_in_transaction(update_spanner)

            # 3. Commit Cloud SQL
            conn_sql.commit()
            return redirect(url_for('index'))

        except (GoogleAPICallError, psycopg2.Error, Exception) as e:
            app.logger.error(f"Dual-write update failed: {e}")
            conn_sql.rollback()
            return f"An error occurred during update: {e}", 500
        finally:
            cur_sql.close()
            conn_sql.close()
    
    # Close cursor and connection if it's a GET request
    cur_sql.close()
    conn_sql.close()
    return render_template('edit.html', sale=sale)

# --- Delete Operation (Dual Write) ---
@app.route('/delete/<sale_id>', methods=('POST',))
def delete(sale_id):
    """Deletes a sale from both databases."""
    conn_sql = get_cloudsql_connection()
    if not conn_sql:
        return "Error: Database connection failed.", 500
    cur_sql = conn_sql.cursor()

    try:
        # 1. Delete from Cloud SQL
        cur_sql.execute("DELETE FROM sales WHERE sale_id = %s", (sale_id,))

        # 2. Delete from Cloud Spanner
        if not spanner_database:
            raise Exception("Spanner database not configured.")

        def delete_spanner(transaction):
            transaction.execute_update(
                "DELETE FROM sales WHERE sale_id = @sale_id",
                params={"sale_id": sale_id},
                param_types={"sale_id": spanner.param_types.STRING},
            )
        spanner_database.run_in_transaction(delete_spanner)

        # 3. Commit Cloud SQL
        conn_sql.commit()
        return redirect(url_for('index'))

    except (GoogleAPICallError, psycopg2.Error, Exception) as e:
        app.logger.error(f"Dual-write delete failed: {e}")
        conn_sql.rollback()
        return f"An error occurred during deletion: {e}", 500
    finally:
        cur_sql.close()
        conn_sql.close()

# --- Reporting Page (from Cloud SQL) ---
@app.route('/report')
def report():
    """Displays a sales report from Cloud SQL."""
    conn = get_cloudsql_connection()
    if not conn:
        return "Error: Database connection could not be established.", 500

    cur = conn.cursor()
    cur.execute("""
        SELECT
            product_name,
            SUM(quantity) as total_quantity,
            SUM(quantity * price_per_item) as total_revenue
        FROM sales
        GROUP BY product_name
        ORDER BY total_revenue DESC;
    """)
    report_data = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('report.html', report_data=report_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=False)