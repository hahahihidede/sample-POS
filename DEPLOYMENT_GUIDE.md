# Deployment Guide: Coffee Shop POS on GKE

This guide provides instructions for deploying the Coffee Shop POS application to a single, budget-friendly Google Kubernetes Engine (GKE) cluster, connected to both a Cloud SQL for PostgreSQL 17 instance and a Cloud Spanner instance.

## 1. Prerequisites

Before you begin, ensure you have the following installed and configured:
- **Google Cloud SDK (`gcloud`)**: Authenticated with your GCP account (`gcloud auth login`, `gcloud config set project [YOUR_PROJECT_ID]`).
- **`kubectl`**: The Kubernetes command-line tool.
- **Docker**: For building and pushing container images.
- **A Google Cloud Platform project**: With billing enabled.

## 2. Infrastructure Setup (Single Region)

All resources will be provisioned in a single region to be cost-effective. We'll use `us-central1` as an example.

### 2.1. Create an Artifact Registry Repository
Create a repository to store your Docker images.
```bash
export REGION="us-central1"
export REPO_NAME="pos-app-repo"
gcloud artifacts repositories create $REPO_NAME \
    --repository-format=docker \
    --location=$REGION \
    --description="Docker repository for the POS application"
```

### 2.2. Set Up Cloud SQL for PostgreSQL 17
Create a budget-friendly Cloud SQL instance.
```bash
export INSTANCE_NAME="pos-db-postgres"
export DB_USER="pos_user"
export DB_PASSWORD="your-strong-password" # Replace with a secure password
export DB_NAME="pos_database"

# Create a budget-friendly instance with PostgreSQL 17
gcloud sql instances create $INSTANCE_NAME \
    --database-version=POSTGRES_17 \
    --region=$REGION \
    --tier=db-g1-small # A cost-effective machine type

# Create a user for the database
gcloud sql users create $DB_USER \
    --instance=$INSTANCE_NAME \
    --password=$DB_PASSWORD

# Create the database itself
gcloud sql databases create $DB_NAME --instance=$INSTANCE_NAME
```
**Note:** After creation, run the contents of `init.sql` against this database to create the tables and add sample data.

### 2.3. Set Up Cloud Spanner
Create a small, single-node Cloud Spanner instance.
```bash
export SPANNER_INSTANCE_ID="pos-spanner-instance"
export SPANNER_DATABASE_ID="pos-spanner-db"

# Create a cost-effective 1-node instance
gcloud spanner instances create $SPANNER_INSTANCE_ID \
    --config=regional-us-central1 \
    --description="POS Spanner Instance" \
    --nodes=1

# Create the Spanner database and apply the schema
gcloud spanner databases create $SPANNER_DATABASE_ID \
    --instance=$SPANNER_INSTANCE_ID \
    --ddl-file=spanner_schema.ddl
```

### 2.4. Create a GKE Cluster
Create a GKE cluster using the cost-optimized Autopilot mode.
```bash
gcloud container clusters create-auto pos-cluster --region=$REGION
```

## 3. Build and Push the Docker Image

1.  **Configure Docker**: Authenticate Docker with Artifact Registry.
    ```bash
    gcloud auth configure-docker $REGION-docker.pkg.dev
    ```
2.  **Build the Image**:
    ```bash
    export PROJECT_ID=$(gcloud config get-value project)
    export IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/pos-app:latest"
    docker build -t $IMAGE_TAG .
    ```
3.  **Push the Image**:
    ```bash
    docker push $IMAGE_TAG
    ```

## 4. Configure Kubernetes Manifests

You will need to update the placeholder values in the `kubernetes/` directory. **Note:** The current manifest files are structured for a multi-cluster setup. You will need to simplify them for this single-cluster deployment, likely by only using and modifying the `kubernetes/base` files and removing the `overlays`.

A simplified `deployment.yaml` should have its image path updated and environment variables configured via a `ConfigMap` and `Secret` to pass the database credentials to the application.

## 5. Deploy the Application

1.  **Get Cluster Credentials**:
    ```bash
    gcloud container clusters get-credentials pos-cluster --region=$REGION
    ```
2.  **Apply Manifests**:
    After configuring your Kubernetes YAML files (deployment, service, secrets), apply them:
    ```bash
    kubectl apply -f your-configured-manifest.yaml
    ```

## 6. Verify the Deployment

Find the external IP address of the service and access the application in your browser.
```bash
# Wait for the service to get an external IP
kubectl get service --watch

# Once you see an IP for your service, open it in your browser:
# http://[EXTERNAL_IP]
```
You should now be able to access the POS application. You can switch between PostgreSQL and Spanner using the dropdown in the navigation bar.