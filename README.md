# Tangle deployments for Google Cloud

Experimental solutions for deploying [Tangle](https://tangleml.com) to Google Cloud.

## Prerequisites

1.  Storage for artifacts and logs:
    *   Google Cloud Storage buckets:
        *   Artifacts: `gs://<bucket-artifacts>/artifacts`
        *   Logs: `gs://<bucket-logs>/logs`
2.  Cluster for running executions:
    *   A Google Kubernetes Engine Cluster
        *   Executions Namespace: A Kubernetes Namespace (or the "default" namespace)
        *   Executions Service Account: A Kubernetes Service Account (or the "default" service account). Must have write access to the artifacts bucket.
3.  Database:
    *   A Google Cloud SQL database.
    *   (A local Sqlite database like `sqlite:///db.sqlite` can be used for local testing.)
4.  Backend deployment:
    Backend can be deployed to Kubernetes or Google Cloud Run Service.
    For testing purposes, the backend can be executed locally.
5.  Permissions and access:
    *   The Backend Service Account needs write permissions to the artifact and log buckets
    *   The Executions Service Account must have write access to the artifacts bucket.
    *   The Backend Service Account must have permissions to create pods in the Kubernetes Engine Cluster in the Executions Namespace
    *   The Backend Service must have write access to the Database.
    *   The backend needs working kubernetes configuration such that `kubectl` commands work automatically. (The backend does not need the `kubectl` tool itself.)
        *   This may require installing `gcloud components install gke-gcloud-auth-plugin`
        *   Kubernetes config file may be created using `gcloud container clusters get-credentials CLUSTER_NAME --region us-central1 --project PROJECT_ID`
6.  Configuration:
    *   The admin deploying the Tangle service must modify the `start.py` script to specify the storage bucket URIs, database URI and Kubernetes configuration.
7.  Authentication:
    *   ! The backend API Server MUST be put behind auth proxy! The API Sever allows all users to access read-only API routes. So the API Server must not be open to public Internet.
    *   ! The admin deploying the Tangle service must modify the `get_user_details` function in the `start.py` script to properly extract the user auth from the HTTP requests (IAM/IAP). Documentation: <https://docs.cloud.google.com/run/docs/tutorials/identity-platform>, <https://docs.cloud.google.com/python/docs/getting-started/authenticate-users>

## Testing the configuration locally

```shell
git clone https://github.com/TangleML/tangle_deployment_gcp.git
cd tangle_deployment_gcp
git clone https://github.com/TangleML/tangle-ui.git ui_build --branch stable_local_build

# ! Edit start.py to configure the storage bucket URIs, database URI and Kubernetes configuration

uv run start.py
```
