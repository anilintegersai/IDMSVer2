"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the document processing API."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    base_path: str = r"C:\Work\YokogawaSharedFolder\ProjectDocs"
    template_source_base_path: str = r"C:\Work\YokogawaSharedFolder\SourceTemplates"
    template_destination_base_path: str = r"C:\Work\YokogawaSharedFolder\Templates"
    merged_base_path: str = r"C:\Work\YokogawaSharedFolder\MergedTemplates"
    shade_fill: str = "E2EAF4"
    insert_marker_text: bool = True
    jwt_secret: str = "change-me-in-production"
    jwt_enabled: bool = False
    audit_enabled: bool = False
    payload_logging_enabled: bool = False
    # Placeholder default — set the real connection string via the DATABASE_URL
    # environment variable (or a local, git-ignored .env). Only used when
    # audit/payload logging is enabled.
    database_url: str = (
        "mssql+pyodbc://sa:CHANGE_ME@localhost,1433/Document_Automation"
        "?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
    )
    host: str = "0.0.0.0"
    port: int = 8000
    app_title: str = "IDMS Document Processing API"
    app_version: str = "1.0.0"
    app_description: str = (
        "Python document automation API for Word (.docx) processing. "
        "Supports TOC extraction, section merge with destination formatting preserved, "
        "paragraph/image insertion, placeholder discovery, and inserted-text editing. "
        "All operations use pure OOXML manipulation — no Microsoft Word installation required."
    )

    # CORS configuration — set explicit origins in production
    cors_allowed_origins: list[str] = ["http://localhost:3000"]
    cors_allow_credentials: bool = False
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    # Debugging/dev flags
    debug: bool = False

    # Upload & rate limiting
    max_upload_size_bytes: int = 10 * 1024 * 1024  # 10 MB by default
    rate_limit_enabled: bool = False
    rate_limit_per_min: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
