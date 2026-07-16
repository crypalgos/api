from typing import Any, Optional

from fastapi import Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from app.config.settings import settings
from app.exceptions.exceptions import UnauthorizedAccessException
from app.modules.user_service.utils.auth_utils import JWTUtils


class CurrentUser(BaseModel):
    """Typed authenticated principal — routes never touch raw token dicts."""

    user_id: str
    email: Optional[str] = None


# Dependency for request-scoped authentication
async def get_current_user(request: Request) -> CurrentUser:
    """
    FastAPI dependency for authenticating users.
    Extracts and validates JWT token, returns user information.
    """
    try:
        # Priority 1: Get token from cookies (access_token)
        token = request.cookies.get("access_token")

        # Priority 2: Fallback to Authorization header (Bearer token)
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            raise UnauthorizedAccessException("Authorization token missing")

        payload = JWTUtils.decode_access_token(token)

        if not payload:
            raise UnauthorizedAccessException("Invalid or expired token")

        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedAccessException("Invalid token payload")

        return CurrentUser(user_id=user_id, email=payload.get("email"))

    except UnauthorizedAccessException:
        raise
    except Exception:
        raise UnauthorizedAccessException("Authentication failed")


# Alternative dependency using HTTPBearer for routes that need explicit token validation
security = HTTPBearer()


from fastapi import Depends


async def get_admin_user(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency gating admin-only routes (settings.admin_email)."""
    if current_user.email != settings.admin_email:
        raise UnauthorizedAccessException("Access denied. Admin only.")
    return current_user
