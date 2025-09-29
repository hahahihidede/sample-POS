import random
from locust import HttpUser, task, between

class WebAppUser(HttpUser):
    """
    Simulates a user browsing the POS application.
    This test is designed to be run against the application in 'stateless' mode.
    Usage: locust -f locustfile.py --host http://localhost:8080
    """
    wait_time = between(1, 5)  # Wait 1-5 seconds between tasks

    # --- Test Configuration ---
    # The database to target during the load test.
    # Can be 'postgres', 'spanner', or 'dual'.
    db_mode = "postgres"

    def on_start(self):
        """Called when a Locust user starts. We'll have them view the homepage."""
        self.client.get(f"/?db={self.db_mode}")

    @task(5)  # Viewing products is the most common action
    def view_products(self):
        self.client.get(f"/products?db={self.db_mode}", name="/products")

    @task(2)
    def view_employees(self):
        self.client.get(f"/employees?db={self.db_mode}", name="/employees")

    @task(2)
    def view_customers(self):
        self.client.get(f"/customers?db={self.db_mode}", name="/customers")

    @task(1)  # Writing data is less frequent but performance-critical
    def add_product(self):
        """
        Simulates a user adding a new product.
        This task gets the 'add' page and then POSTs the new product data.
        """
        # First, get the page (like a real user)
        self.client.get(f"/products/add?db={self.db_mode}", name="/products/add [GET]")

        # Then, create and post a new product
        random_id = random.randint(1000, 9999)
        product_name = f"Locust Test Product {random_id}"

        self.client.post(
            # The URL doesn't need the query param for POST, as it's in the form data
            "/products/add",
            {
                "name": product_name,
                "category": "Load Test",
                "price": 15.50,
                "description": "Product created by a Locust swarm.",
                "db": self.db_mode  # Pass 'db' in the form for stateless POST
            },
            name="/products/add [POST]" # Group POST requests in Locust UI
        )