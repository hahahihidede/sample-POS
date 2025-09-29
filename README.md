# Sales Data Management Application

This is a Flask web application designed to manage sales data. It serves as a practical example of a dual-write architecture, where data is written to two separate database systems simultaneously:

1.  **Cloud SQL for PostgreSQL:** A fully-managed relational database service.
2.  **Google Cloud Spanner:** A globally-distributed, horizontally-scalable database service.

The primary purpose of this application is to demonstrate how to maintain data consistency across two different types of databases in a cloud environment.

## Architecture

The application follows a dual-write pattern for all create, update, and delete operations. Here's how it works:

1.  **User Initiates a Write Operation:** A user adds, edits, or deletes a sale through the web interface.
2.  **Flask Backend Receives Request:** The Flask application receives the request and starts a transaction.
3.  **Dual Write:**
    *   The application first attempts to write the data to Cloud SQL.
    *   It then attempts to write the same data to Cloud Spanner.
4.  **Transaction Management:**
    *   If both writes are successful, the Cloud SQL transaction is committed.
    *   If either write fails, the Cloud SQL transaction is rolled back to prevent data inconsistency.

Read operations, such as displaying the list of sales and generating reports, are performed against the Cloud SQL database.

## Prerequisites

Before you can run this application, you need to have the following installed:

*   Python 3.x
*   `pip` for installing Python packages

You will also need access to a Google Cloud Platform (GCP) project with the following APIs enabled:

*   Cloud SQL Admin API
*   Cloud Spanner API

## Configuration

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up databases:**
    *   **Cloud SQL (PostgreSQL):**
        *   Create a new Cloud SQL for PostgreSQL instance.
        *   Create a database within the instance.
        *   Create a user and set a password.
        *   Use the `init.sql` file in this repository to create the `sales` table:
            ```sql
            CREATE TABLE sales (
                sale_id VARCHAR(255) PRIMARY KEY,
                product_name VARCHAR(255),
                quantity INTEGER,
                price_per_item NUMERIC(10, 2),
                sale_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            ```
    *   **Cloud Spanner:**
        *   Create a new Cloud Spanner instance.
        *   Create a database within the instance.
        *   Use the `spanner_schema.ddl` file to define the schema for the `sales` table:
            ```
            gcloud spanner database ddl update <your-database-id> --instance=<your-instance-id> --ddl-file=spanner_schema.ddl
            ```

4.  **Set up environment variables:**
    Create a `.env` file in the root of the project and add the following variables:

    ```
    # Cloud SQL Configuration
    DB_HOST=<your-cloud-sql-instance-ip>
    DB_NAME=<your-cloud-sql-database-name>
    DB_USER=<your-cloud-sql-user>
    DB_PASSWORD=<your-cloud-sql-password>

    # Spanner Configuration
    SPANNER_PROJECT_ID=<your-gcp-project-id>
    SPANNER_INSTANCE_ID=<your-spanner-instance-id>
    SPANNER_DATABASE_ID=<your-spanner-database-id>
    ```

## Running the Application

Once you have completed the configuration steps, you can run the application with the following command:

```bash
python app.py
```

The application will be available at `http://localhost:8080`.
