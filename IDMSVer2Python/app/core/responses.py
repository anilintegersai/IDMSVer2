"""Standard API response wrappers."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Uniform success/failure envelope returned by all endpoints."""

    success: bool = Field(description="Whether the operation completed successfully.")
    message: str = Field(description="Human-readable outcome message.")
    message_code: str = Field(description="Machine-readable code for client-side handling.")
    data: T | None = Field(default=None, description="Payload returned on success; shape depends on endpoint.")
