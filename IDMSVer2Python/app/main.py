"""IDMS Document Processing API — Python implementation."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.openapi import OPENAPI_TAGS, SWAGGER_UI_PARAMETERS
from app.api.routes import documents
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description=settings.app_description,
    openapi_url="/openapi.json",
    docs_url="/swagger",
    redoc_url="/redoc",
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/api/v1")


@app.get("/health", tags=["Health"], summary="Health check")
async def health() -> dict:
    """Returns service status and version."""
    return {"status": "ok", "version": settings.app_version}
