CREATE TABLE sales (
    sale_id      STRING(36) NOT NULL,
    product_name STRING(100) NOT NULL,
    quantity     INT64 NOT NULL,
    price_per_item FLOAT64 NOT NULL,
    sale_date    TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true)
) PRIMARY KEY (sale_id);