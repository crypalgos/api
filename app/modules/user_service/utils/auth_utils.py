import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config.settings import settings


class PasswordUtils:
    @staticmethod
    def generate_password_hash(password: str) -> str:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode(), salt)
        return hashed.decode(encoding="utf-8")

    @staticmethod
    def check_password_hash(password_hash: str, password: str) -> bool:
        return bcrypt.checkpw(password.encode(), password_hash.encode())


class JWTUtils:
    REFRESH_TOKEN_SECRET_KEY = settings.refresh_token_secret_key
    ACCESS_TOKEN_SECRET_KEY = settings.access_token_secret_key
    ALGORITHM = settings.jwt_algorithms
    REFRESH_TOKEN_EXPIRE_MINUTES = settings.refresh_token_expire_minutes
    ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

    @staticmethod
    def create_access_token(data: dict[str, str] = None) -> str:
        to_encode = data.copy() if data else {}
        expire = datetime.now(UTC) + timedelta(
            minutes=JWTUtils.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        to_encode.update({"exp": expire})
        return jwt.encode(
            to_encode, JWTUtils.ACCESS_TOKEN_SECRET_KEY, algorithm=JWTUtils.ALGORITHM
        )

    @staticmethod
    def decode_access_token(token: str) -> dict[str, str] | None:
        try:
            payload = jwt.decode(
                token, JWTUtils.ACCESS_TOKEN_SECRET_KEY, algorithms=[JWTUtils.ALGORITHM]
            )
            return payload
        except JWTError:
            return None

    @staticmethod
    def verify_access_token(token: str) -> bool:
        try:
            jwt.decode(
                token, JWTUtils.ACCESS_TOKEN_SECRET_KEY, algorithms=[JWTUtils.ALGORITHM]
            )
            return True
        except JWTError:
            return False

    @staticmethod
    def create_refresh_token(user_id: str) -> str:
        """Create a secure refresh token"""
        payload = {
            "sub": user_id,
            "jti": str(uuid.uuid4()),  # JWT ID for tracking
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC)
            + timedelta(minutes=JWTUtils.REFRESH_TOKEN_EXPIRE_MINUTES),
        }
        return jwt.encode(
            payload, JWTUtils.REFRESH_TOKEN_SECRET_KEY, algorithm=JWTUtils.ALGORITHM
        )

    @staticmethod
    def decode_refresh_token(token: str) -> dict[str, str] | None:
        try:
            payload = jwt.decode(
                token,
                JWTUtils.REFRESH_TOKEN_SECRET_KEY,
                algorithms=[JWTUtils.ALGORITHM],
            )
            return payload
        except JWTError:
            return None

    @staticmethod
    def verify_refresh_token(token: str) -> bool:
        try:
            jwt.decode(
                token,
                JWTUtils.REFRESH_TOKEN_SECRET_KEY,
                algorithms=[JWTUtils.ALGORITHM],
            )
            return True
        except JWTError:
            return False

    @staticmethod
    def get_token_expiry_time() -> datetime:
        """Get the expiry time for access tokens"""
        return datetime.now(UTC) + timedelta(
            minutes=JWTUtils.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    @staticmethod
    def get_refresh_token_expiry_time() -> datetime:
        """Get the expiry time for refresh tokens"""
        return datetime.now(UTC) + timedelta(
            minutes=JWTUtils.REFRESH_TOKEN_EXPIRE_MINUTES
        )


class VerificationCodeUtils:
    @staticmethod
    def generate_verification_code() -> str:
        """Generate a random 6-digit verification code."""
        import random

        return str(random.randint(100000, 999999))

    @staticmethod
    def verification_code_expiry() -> datetime:
        """Get expiry time for verification codes (15 minutes from now)"""
        return datetime.now(UTC) + timedelta(minutes=15)

    @staticmethod
    def is_verification_code_expired(expiry_time: datetime) -> bool:
        """Check if verification code has expired"""
        return datetime.now(UTC) > expiry_time
