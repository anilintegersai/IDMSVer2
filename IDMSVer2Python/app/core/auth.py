"""JWT authentication stub — full validation deferred to Phase 2."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> dict | None:
    """
    When JWT is disabled, all requests pass through.
    When enabled, a Bearer token must be present (validation stub only for now).
    """
    if not settings.jwt_enabled:
        return None
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization required")
    return {"user_id": 0, "token": credentials.credentials}
