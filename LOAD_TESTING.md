# Load Testing with Locust

This document provides instructions for running load tests against the POS application using [Locust](https://locust.io/). It also explains the two different operating modes of the application: `stateful` and `stateless`.

## Application Modes: Stateful vs. Stateless

To allow for flexible deployment and testing, the application can run in one of two modes, configured via the `APP_MODE` environment variable.

### 1. Stateful Mode (Default)
-   **Configuration:** `APP_MODE=stateful` (or unset)
-   **Behavior:** The application uses a server-side Flask session to keep track of the user's selected database (`PostgreSQL`, `Spanner`, or `Dual Write`). The database choice is stored in a cookie on the user's browser.
-   **Pros:** Simpler URLs (no query parameters needed for state).
-   **Cons:** Requires a "sticky session" mechanism on a load balancer if deployed across multiple pods/instances to ensure a user is always sent to the same server where their session lives. This can make horizontal scaling more complex.

### 2. Stateless Mode
-   **Configuration:** `APP_MODE=stateless`
-   **Behavior:** The application does not use sessions to store the database choice. Instead, the database selection is passed explicitly with every request as a URL query parameter (e.g., `/products?db=spanner`).
-   **Pros:** Greatly simplifies scaling. Any server can handle any request because all the necessary information is contained within the request itself. This is ideal for cloud-native environments and load balancing.
-   **Cons:** URLs are more verbose. Every link and form on the frontend must be aware of and include the `db` parameter.

## Running the Load Test

The included `locustfile.py` is designed to test the application in **stateless mode**, as this is the most common scenario for performance testing a scalable web service.

### Step 1: Install Locust
If you don't have Locust installed, you can add it to your `requirements.txt` or install it directly:
```bash
pip install locust
```

### Step 2: Run the Application
Start the Flask application. Make sure to set the mode to `stateless`.
```bash
# Make sure your database environment variables are set in a .env file
APP_MODE=stateless python app.py
```
The application will start on `http://localhost:8080`.

### Step 3: Start Locust
In a new terminal, navigate to the project's root directory and run Locust:
```bash
locust -f locustfile.py --host http://localhost:8080
```

### Step 4: Run the Test from the Web UI
1.  Open your web browser and go to `http://localhost:8089` (the default Locust web UI).
2.  Enter the number of users you want to simulate (e.g., `100`).
3.  Enter the spawn rate (how many users to start per second, e.g., `10`).
4.  Click **"Start swarming"**.

You will now see real-time statistics for the application's performance under load, including requests per second, response times, and any failures. You can modify the `db_mode` variable inside `locustfile.py` to test the performance of `postgres`, `spanner`, or `dual` write modes.