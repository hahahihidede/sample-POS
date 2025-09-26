# Sales Application

This is a simple Flask web application for tracking sales. It has been refactored to support a multi-region deployment on Google Kubernetes Engine (GKE), connecting to both Cloud SQL for PostgreSQL and Cloud Spanner.

## Overview

- **Frontend**: Simple HTML with CSS.
- **Backend**: Flask (Python).
- **Databases**:
    - Cloud SQL for PostgreSQL (for read operations).
    - Cloud Spanner (for write operations, synchronized with Cloud SQL).
- **Deployment**: Configured for GKE using Kubernetes and Kustomize.

## Deployment

For detailed, step-by-step instructions on how to set up the cloud infrastructure and deploy this application to GKE, please see the [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md).