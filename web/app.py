from fastapi import FastAPI

from .dependencies import DemoConfig, build_demo_state
from .routes import APP_DESCRIPTION, APP_NAME, APP_VERSION, router


def create_app(config: DemoConfig | None = None) -> FastAPI:
    """Create an isolated FastAPI application and its in-memory demo state."""
    application = FastAPI(
        title=APP_NAME,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.state.demo_state = build_demo_state(config)
    application.include_router(router)
    return application


app = create_app()
