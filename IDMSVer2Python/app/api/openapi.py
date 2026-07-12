"""OpenAPI / Swagger metadata for the API documentation UI."""

OPENAPI_TAGS = [
    {
        "name": "Documents",
        "description": (
            "Word document automation — merge sections, insert content, manage placeholders, "
            "and edit previously inserted text. All operations work on .docx files via their "
            "full UNC or local file paths. Processing uses pure OOXML (no Microsoft Word required)."
        ),
    },
    {
        "name": "Health",
        "description": "Service health and readiness checks.",
    },
]

SWAGGER_UI_PARAMETERS = {
    "docExpansion": "list",
    "defaultModelsExpandDepth": 2,
    "displayRequestDuration": True,
    "filter": True,
    "tryItOutEnabled": True,
}
