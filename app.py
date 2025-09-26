import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv

load_dotenv() # Muat variabel dari file .env

app = Flask(__name__)

# --- Konfigurasi Koneksi Database ---
def get_db_connection():
    """Membuat koneksi ke database Cloud SQL."""
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD")
    )
    return conn

# --- Halaman Utama (Read) ---
@app.route('/')
def index():
    """Menampilkan semua data penjualan."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT sale_id, product_name, quantity, price_per_item, quantity * price_per_item AS total_price FROM sales ORDER BY sale_date DESC;")
    sales = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', sales=sales)

# --- Halaman Tambah Data (Create) ---
@app.route('/add', methods=('GET', 'POST'))
def add():
    """Menambah data penjualan baru."""
    if request.method == 'POST':
        product_name = request.form['product_name']
        quantity = request.form['quantity']
        price_per_item = request.form['price_per_item']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO sales (product_name, quantity, price_per_item) VALUES (%s, %s, %s)",
                    (product_name, quantity, price_per_item))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    return render_template('add.html')

# --- Halaman Edit Data (Update) ---
@app.route('/edit/<int:sale_id>', methods=('GET', 'POST'))
def edit(sale_id):
    """Mengedit data penjualan yang sudah ada."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sales WHERE sale_id = %s", (sale_id,))
    sale = cur.fetchone()

    if request.method == 'POST':
        product_name = request.form['product_name']
        quantity = request.form['quantity']
        price_per_item = request.form['price_per_item']

        cur.execute("UPDATE sales SET product_name = %s, quantity = %s, price_per_item = %s WHERE sale_id = %s",
                    (product_name, quantity, price_per_item, sale_id))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('index'))
    
    cur.close()
    conn.close()
    return render_template('edit.html', sale=sale)

# --- Fungsi Hapus Data (Delete) ---
@app.route('/delete/<int:sale_id>', methods=('POST',))
def delete(sale_id):
    """Menghapus data penjualan."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM sales WHERE sale_id = %s", (sale_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

# --- Halaman Laporan Penjualan (Reporting) ---
@app.route('/report')
def report():
    """Menampilkan laporan total penjualan per produk."""
    conn = get_db_connection()
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
    app.run(host='0.0.0.0', port=8080, debug=True)
