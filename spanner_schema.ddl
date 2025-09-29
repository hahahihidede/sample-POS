-- Products Table
CREATE TABLE products (
    product_id   INT64 NOT NULL,
    name         STRING(100) NOT NULL,
    category     STRING(50) NOT NULL,
    price        FLOAT64 NOT NULL,
    description  STRING(MAX)
) PRIMARY KEY (product_id);

-- Employees Table
CREATE TABLE employees (
    employee_id  INT64 NOT NULL,
    first_name   STRING(50) NOT NULL,
    last_name    STRING(50) NOT NULL,
    position     STRING(50) NOT NULL,
    hire_date    DATE NOT NULL
) PRIMARY KEY (employee_id);

-- Customers Table
CREATE TABLE customers (
    customer_id  INT64 NOT NULL,
    first_name   STRING(50) NOT NULL,
    last_name    STRING(50) NOT NULL,
    email        STRING(100),
    join_date    DATE
) PRIMARY KEY (customer_id);

-- Sales Orders Table
CREATE TABLE sales_orders (
    order_id      INT64 NOT NULL,
    customer_id   INT64,
    employee_id   INT64 NOT NULL,
    product_id    INT64 NOT NULL,
    quantity      INT64 NOT NULL,
    total_price   FLOAT64 NOT NULL,
    order_date    TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (order_id);