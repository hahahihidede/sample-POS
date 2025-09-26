# Deployment Guide: Sales Application on GKE with Cloud SQL and Spanner

This guide provides comprehensive instructions for deploying the dual-database sales application to two Google Kubernetes Engine (GKE) clusters (one in the US, one in Asia), connected to both Cloud SQL for PostgreSQL and Cloud Spanner.

## 1. Prerequisites

Before you begin, ensure you have the following installed and configured:
- **Google Cloud SDK (`gcloud`)**: Authenticated with your GCP account (`gcloud auth login`, `gcloud config set project [YOUR_PROJECT_ID]`).
- **`kubectl`**: The Kubernetes command-line tool.
- **Docker**: For building and pushing container images.
- **A Google Cloud Platform project**: With billing enabled.

## 2. Infrastructure Setup

### 2.1. Create an Artifact Registry Repository
Create a repository to store your Docker images.
```bash
export REGION="us-central1" # Or any region of your choice
export REPO_NAME="sales-app-repo"
gcloud artifacts repositories create $REPO_NAME \
    --repository-format=docker \
    --location=$REGION \
    --description="Docker repository for the sales application"
```

### 2.2. Set Up Cloud SQL for PostgreSQL
Create two Cloud SQL instances, one for each region.

**For the US Cluster:**
```bash
export US_INSTANCE_NAME="sales-db-instance-us"
export US_REGION="us-central1"
export DB_USER="sales_user"
export DB_PASSWORD="your-strong-password" # Replace with a secure password

gcloud sql instances create $US_INSTANCE_NAME \
    --database-version=POSTGRES_14 \
    --region=$US_REGION \
    --cpu=2 \
    --memory=4GB

gcloud sql users create $DB_USER \
    --instance=$US_INSTANCE_NAME \
    --password=$DB_PASSWORD
```
**For the Asia Cluster:**
```bash
export ASIA_INSTANCE_NAME="sales-db-instance-asia"
export ASIA_REGION="asia-southeast1"

gcloud sql instances create $ASIA_INSTANCE_NAME \
    --database-version=POSTGRES_14 \
    --region=$ASIA_REGION \
    --cpu=2 \
    --memory=4GB

gcloud sql users create $DB_USER \
    --instance=$ASIA_INSTANCE_NAME \
    --password=$DB_PASSWORD
```

### 2.3. Set Up Cloud Spanner
Create two Cloud Spanner instances, one for each region.

**For the US Cluster:**
```bash
export US_SPANNER_INSTANCE_ID="sales-spanner-us"
export US_SPANNER_DATABASE_ID="sales-db-us"
gcloud spanner instances create $US_SPANNER_INSTANCE_ID --config=regional-us-central1 --description="US Spanner Instance" --nodes=1
gcloud spanner databases create $US_SPANNER_DATABASE_ID --instance=$US_SPANNER_INSTANCE_ID --ddl-file=spanner_schema.ddl
```
**For the Asia Cluster:**
```bash
export ASIA_SPANNER_INSTANCE_ID="sales-spanner-asia"
export ASIA_SPANNER_DATABASE_ID="sales-db-asia"
gcloud spanner instances create $ASIA_SPANNER_INSTANCE_ID --config=regional-asia-southeast1 --description="Asia Spanner Instance" --nodes=1
gcloud spanner databases create $ASIA_SPANNER_DATABASE_ID --instance=$ASIA_SPANNER_INSTANCE_ID --ddl-file=spanner_schema.ddl
```

### 2.4. Create GKE Clusters
Create two GKE clusters, one in the US and one in Asia.
```bash
# US Cluster
gcloud container clusters create-auto sales-cluster-us --region=us-central1

# Asia Cluster
gcloud container clusters create-auto sales-cluster-asia --region=asia-southeast1
```

## 3. Build and Push the Docker Image

1.  **Configure Docker**: Authenticate Docker with Artifact Registry.
    ```bash
    gcloud auth configure-docker $REGION-docker.pkg.dev
    ```
2.  **Build the Image**:
    ```bash
    export PROJECT_ID=$(gcloud config get-value project)
    export IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/sales-app:latest"
    docker build -t $IMAGE_TAG .
    ```
3.  **Push the Image**:
    ```bash
    docker push $IMAGE_TAG
    ```

## 4. Configure Kubernetes Manifests

You must replace the placeholder values in the Kubernetes configuration files before deploying.

1.  **Image Path**: In `kubernetes/base/deployment.yaml`, replace `gcr.io/your-gcp-project-id/sales-app:latest` with your image path (`$IMAGE_TAG`).

2.  **Base `kustomization.yaml`**: In `kubernetes/base/kustomization.yaml`:
    - Replace `your-gcp-project-id` with your actual GCP Project ID.
    - Replace `your-cloudsql-db-name` with the database name (e.g., `postgres`).
    - Replace `your-cloudsql-user` with the user you created (`sales_user`).
    - Replace `your-cloudsql-password` in the `secretGenerator` with your actual password.

3.  **US Overlay**: In `kubernetes/overlays/us/config.yaml`:
    - Set `CLOUDSQL_INSTANCE_CONNECTION_NAME` to the connection name of your US Cloud SQL instance (find it via `gcloud sql instances describe $US_INSTANCE_NAME`).
    - Set `SPANNER_INSTANCE_ID` to `$US_SPANNER_INSTANCE_ID`.

4.  **Asia Overlay**: In `kubernetes/overlays/asia/config.yaml`:
    - Set `CLOUDSQL_INSTANCE_CONNECTION_NAME` to the connection name of your Asia Cloud SQL instance.
    - Set `SPANNER_INSTANCE_ID` to `$ASIA_SPANNER_INSTANCE_ID`.


## 5. Deploy the Application

### 5.1. Deploy to the US Cluster
```bash
# Get credentials for the US cluster
gcloud container clusters get-credentials sales-cluster-us --region=us-central1

# Apply the US overlay
kubectl apply -k kubernetes/overlays/us
```

### 5.2. Deploy to the Asia Cluster
```bash
# Get credentials for the Asia cluster
gcloud container clusters get-credentials sales-cluster-asia --region=asia-southeast1

# Apply the Asia overlay
kubectl apply -k kubernetes/overlays/asia
```

## 6. Verify the Deployment

For each cluster, find the external IP address of the service and access the application in your browser.

```bash
# Wait for the service to get an external IP
kubectl get service sales-app-service --watch

# Once you see an IP, open it in your browser:
http://[EXTERNAL_IP]
```
You should now be able to access the sales application running in each respective region.