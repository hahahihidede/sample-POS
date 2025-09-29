-- Drop existing tables if they exist to ensure a clean slate.
DROP TABLE IF EXISTS sales_orders;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products;

-- Create Products Table (Coffee & Pastries)
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL, -- e.g., 'Coffee', 'Pastry', 'Merchandise'
    price NUMERIC(10, 2) NOT NULL,
    description TEXT
);

-- Create Employees Table
CREATE TABLE employees (
    employee_id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    position VARCHAR(50) NOT NULL, -- e.g., 'Barista', 'Manager'
    hire_date DATE NOT NULL
);

-- Create Customers Table
CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE,
    join_date DATE DEFAULT CURRENT_DATE
);

-- Create Sales Orders Table
CREATE TABLE sales_orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INT,
    employee_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    total_price NUMERIC(10, 2) NOT NULL,
    order_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

-- --- Sample Data ---

-- Populate Products
INSERT INTO products (name, category, price, description) VALUES
('Espresso', 'Coffee', 2.50, 'A strong, concentrated coffee shot.'),
('Latte', 'Coffee', 4.00, 'Espresso with steamed milk and a layer of foam.'),
('Cappuccino', 'Coffee', 3.75, 'Espresso with equal parts steamed milk and foam.'),
('Americano', 'Coffee', 3.00, 'Espresso diluted with hot water.'),
('Cold Brew', 'Coffee', 4.50, 'Coffee steeped in cold water for a smooth, low-acid flavor.'),
('Croissant', 'Pastry', 2.75, 'A buttery, flaky pastry.'),
('Muffin', 'Pastry', 2.50, 'A sweet, single-serving quick bread.'),
('Coffee Beans (12oz)', 'Merchandise', 15.00, 'Our signature house blend coffee beans.');

-- Populate Employees
INSERT INTO employees (first_name, last_name, position, hire_date) VALUES
('John', 'Doe', 'Manager', '2022-01-15'),
('Jane', 'Smith', 'Barista', '2022-03-01'),
('Peter', 'Jones', 'Barista', '2023-05-20');

-- Populate Customers
INSERT INTO customers (first_name, last_name, email) VALUES
('Alice', 'Williams', 'alice.w@example.com'),
('Bob', 'Brown', 'bob.b@example.com'),
('Charlie', 'Davis', 'charlie.d@example.com');

-- Populate Sample Sales Orders
-- Order 1: Alice buys a Latte from Jane
INSERT INTO sales_orders (customer_id, employee_id, product_id, quantity, total_price)
VALUES (1, 2, 2, 1, 4.00);

-- Order 2: Bob buys an Espresso and a Croissant from Peter
INSERT INTO sales_orders (customer_id, employee_id, product_id, quantity, total_price)
VALUES (2, 3, 1, 1, 2.50);
INSERT INTO sales_orders (customer_id, employee_id, product_id, quantity, total_price)
VALUES (2, 3, 6, 1, 2.75);

-- Order 3: A guest (no customer_id) buys an Americano from Jane
INSERT INTO sales_orders (customer_id, employee_id, product_id, quantity, total_price)
VALUES (NULL, 2, 4, 1, 3.00);