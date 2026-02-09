from typing import Any
from fastapi import Request
from fastapi.security import HTTPBearer

from app.exceptions.exceptions import UnauthorizedAccessException
from app.modules.user_service.utils.auth_utils import JWTUtils


# Dependency for request-scoped authentication
async def get_current_user(request: Request) -> dict[str, Any]:
    """
    FastAPI dependency for authenticating users.
    Extracts and validates JWT token, returns user information.
    """
    try:
        # Try to get token from cookies first (for frontend)
        token = request.cookies.get("access_token")

        # Fallback to Authorization header (for Postman/API testing)
        if not token:
            authorization = request.headers.get("Authorization")
            if authorization and authorization.startswith("Bearer "):
                token = authorization[7:]  # Remove "Bearer " prefix

        if not token:
            raise UnauthorizedAccessException("Authorization token missing")

        payload = JWTUtils.decode_access_token(token)

        if not payload:
            raise UnauthorizedAccessException("Invalid or expired token")

        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedAccessException("Invalid token payload")

        return {
            "user_id": user_id,
            "email": payload.get("email"),
        }

    except UnauthorizedAccessException:
        raise
    except Exception:
        raise UnauthorizedAccessException("Authentication failed")





# Alternative dependency using HTTPBearer for routes that need explicit token validation
security = HTTPBearer()
