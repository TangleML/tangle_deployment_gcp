import contextlib
import threading
import traceback
import logging
import os
import pathlib

import fastapi
import fastapi
from fastapi import staticfiles
import sqlalchemy
from sqlalchemy import orm

from cloud_pipelines.orchestration.storage_providers import (
    interfaces as storage_interfaces,
)

from cloud_pipelines_backend import api_router
from cloud_pipelines_backend import database_ops
from cloud_pipelines_backend import orchestrator_sql

# region: Configuration
# database_uri = f"mysql://..."
database_uri = f"sqlite:///db.sqlite"
artifacts_root_uri = "gs://<bucket-artifacts>/artifacts"
logs_root_uri = "gs://<bucket-logs>/logs"
# Kubernetes configuration
kubernetes_namespace = "default"
kubernetes_service_account_name: str | None = None

kubeconfig_path: str | None = None  # e.g., "~/.kube/config"
# Kubeconfig context. Example: "gke_project-id_us-central1_cluster-1"
kubeconfig_context: str | None = None

# API Server configuration
host = "0.0.0.0"
port = 8000

authentication_type = (
    "dummy_admin"  # No auth. Only use for local development and testing.
)

## Orchestrator configuration
sleep_seconds_between_queue_sweeps: float = 1.0

# endregion


# region: Logging configuration
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "standard": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "default": {
            "level": "INFO",
            "formatter": "standard",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        # root logger
        "": {
            "level": "INFO",
            "handlers": ["default"],
            "propagate": False,
        },
        __name__: {
            "level": "DEBUG",
            "handlers": ["default"],
            "propagate": False,
        },
        "cloud_pipelines_backend.orchestrator_sql": {
            "level": "DEBUG",
            "handlers": ["default"],
            "propagate": False,
        },
        "cloud_pipelines.orchestration.launchers.kubernetes_launchers": {
            "level": "DEBUG",
            "handlers": ["default"],
            "propagate": False,
        },
        "uvicorn.error": {
            "level": "DEBUG",
            "handlers": ["default"],
            # Fix triplicated log messages
            "propagate": False,
        },
        "uvicorn.access": {
            # "level": "DEBUG",
            "level": "INFO",  # Skip successful GET requests. Does not work...
            "handlers": ["default"],
        },
        "watchfiles.main": {
            "level": "WARNING",
            "handlers": ["default"],
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)

logger = logging.getLogger(__name__)
# endregion


# region: Storage configuration
from cloud_pipelines.orchestration.storage_providers import google_cloud_storage

storage_provider = google_cloud_storage.GoogleCloudStorageProvider()
# endregion

# region: Launcher configuration
from kubernetes import client as k8s_client_lib
from kubernetes import config as k8s_config_lib

try:
    k8s_config_lib.load_incluster_config()
except:
    k8s_config_lib.load_kube_config(
        config_file=kubeconfig_path,
        context=kubeconfig_context,
    )
k8s_client = k8s_client_lib.ApiClient()

# Testing the client
k8s_client_lib.VersionApi(k8s_client).get_code(_request_timeout=5)

from cloud_pipelines_backend.launchers import kubernetes_launchers


launcher = kubernetes_launchers.GoogleKubernetesEngineLauncher(
    api_client=k8s_client,
    namespace=kubernetes_namespace,
    service_account_name=kubernetes_service_account_name,
)
# endregion


# region: Authentication configuration

if authentication_type == "dummy_admin":
    ADMIN_USER_NAME = "admin"
    default_component_library_owner_username = ADMIN_USER_NAME

    # ! This function is just a placeholder for user authentication and authorization so that every request has a user name and permissions.
    # ! This placeholder function authenticates the user as user with name "admin" and read/write/admin permissions.
    # ! In a real multi-user deployment, the `get_user_details` function MUST be replaced with real authentication/authorization based on OAuth or another auth system.
    def get_user_details(request: fastapi.Request):
        return api_router.UserDetails(
            name=ADMIN_USER_NAME,
            permissions=api_router.Permissions(
                read=True,
                write=True,
                admin=True,
            ),
        )

elif authentication_type == "google_cloud_iap":
    raise NotImplementedError("Google Cloud IAP authentication is not implemented yet.")
else:
    raise ValueError(f"Unknown authentication type: {authentication_type}")
# endregion


# region: Database engine initialization
from cloud_pipelines_backend import database_ops

db_engine = database_ops.create_db_engine_and_migrate_db(
    database_uri=database_uri,
)
# endregion


# region: Orchestrator initialization
def run_orchestrator(
    db_engine: sqlalchemy.Engine,
    storage_provider: storage_interfaces.StorageProvider,
    data_root_uri: str,
    logs_root_uri: str,
    sleep_seconds_between_queue_sweeps: float = 1.0,
):
    logger.info("Starting the orchestrator")

    session_factory = orm.sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine
    )

    orchestrator = orchestrator_sql.OrchestratorService_Sql(
        session_factory=session_factory,
        launcher=launcher,
        storage_provider=storage_provider,
        data_root_uri=data_root_uri,
        logs_root_uri=logs_root_uri,
        # default_task_annotations={},
        sleep_seconds_between_queue_sweeps=sleep_seconds_between_queue_sweeps,
    )
    orchestrator.run_loop()


run_configured_orchestrator = lambda: run_orchestrator(
    db_engine=db_engine,
    storage_provider=storage_provider,
    data_root_uri=artifacts_root_uri,
    logs_root_uri=logs_root_uri,
    sleep_seconds_between_queue_sweeps=sleep_seconds_between_queue_sweeps,
)
# endregion


# region: API Server initialization
@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    threading.Thread(
        target=run_configured_orchestrator,
        daemon=True,
    ).start()
    if os.environ.get("GOOGLE_CLOUD_SHELL") == "true":
        # TODO: Find a way to get fastapi/starlette/uvicorn port
        global port
        port = port or 8000
        logger.info(
            f"View app at: https://shell.cloud.google.com/devshell/proxy?port={port}"
        )
    yield


app = fastapi.FastAPI(
    title="Tangle API",
    version="0.0.1",
    separate_input_output_schemas=False,
    lifespan=lifespan,
)


@app.exception_handler(Exception)
def handle_error(request: fastapi.Request, exc: BaseException):
    exception_str = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return fastapi.responses.JSONResponse(
        status_code=503,
        content={"exception": exception_str},
    )


api_router.setup_routes(
    app=app,
    db_engine=db_engine,
    user_details_getter=get_user_details,
    container_launcher_for_log_streaming=launcher,
    default_component_library_owner_username=default_component_library_owner_username,
)


# Health check needed by the Web app
@app.get("/services/ping")
def health_check():
    return {}


# Mounting the web app if the files exist
this_dir = pathlib.Path(__file__).parent
web_app_search_dirs = [
    this_dir / ".." / "pipeline-studio-app" / "build",
    this_dir / ".." / "frontend" / "build",
    this_dir / ".." / "frontend_build",
    this_dir / ".." / "tangle-ui" / "dist",
    this_dir / ".." / "ui_build",
    this_dir / "pipeline-studio-app" / "build",
    this_dir / "ui_build",
]
found_frontend_build_files = False
for web_app_dir in web_app_search_dirs:
    if web_app_dir.exists():
        found_frontend_build_files = True
        logger.info(
            f"Found the Web app static files at {str(web_app_dir)}. Mounting them."
        )
        # The Web app base URL is currently static and hardcoded.
        # TODO: Remove this mount once the base URL becomes relative.
        app.mount(
            "/tangle-ui/",
            staticfiles.StaticFiles(directory=web_app_dir, html=True),
            name="static",
        )
        app.mount(
            "/pipeline-studio-app/",
            staticfiles.StaticFiles(directory=web_app_dir, html=True),
            name="static",
        )
        app.mount(
            "/",
            staticfiles.StaticFiles(directory=web_app_dir, html=True),
            name="static",
        )
if not found_frontend_build_files:
    logger.warning("The Web app files were not found. Skipping.")
# endregion


if __name__ == "__main__":
    import uvicorn

    # ! Need to navigate to http://127.0.0.1:8000 not http://0.0.0.0:8000 to avoid CORS issues.
    logger.info(f"Starting the app on http://127.0.0.1:{port}")
    uvicorn.run(app, host=host, port=port)
