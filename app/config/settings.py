import os
from typing import Final

from pydantic_settings import BaseSettings


def _resolve_env_file() -> str:
    """Return the env file to use based on environment variables.
    Priority:
      1. ENV_FILE - explicit override
      2. APP_ENV / ENV - production -> .env.prod, development -> .env.dev, test -> .env.test
      3. Fallback to .env.dev (for local dev)
    """
    # explicit override first
    env_file_override = os.environ.get("ENV_FILE")
    if env_file_override:
        return env_file_override

    # check common environment vars used to indicate the runtime environment
    app_env = (
        os.environ.get("APP_ENV") or os.environ.get("ENV") or os.environ.get("PY_ENV")
    )
    app_env = app_env.lower() if app_env else "development"

    if app_env in ("production", "prod", "staging"):
        return ".env.prod"
    if app_env in ("test", "testing", "ci", "pytest"):
        return ".env.test"
    if app_env in ("development", "dev"):
        return ".env.dev"

    # default fallback
    return ".env.dev"


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://username:password@localhost:5432/your_database"
    )
    env: str = "development"
    debug: bool = True
    refresh_token_secret_key: str = (
        "your-super-secret-refresh-key-change-this-in-production"
    )
    access_token_secret_key: str = (
        "your-super-secret-access-key-change-this-in-production"
    )
    jwt_algorithms: str = "HS256"
    refresh_token_expire_minutes: int = 10080  # 7 days
    access_token_expire_minutes: int = 30  # 30 minutes
    resend_api_token: str = ""
    resend_from_email: str = "noreply@crypalgos.com"
    resend_from_name: str = "CrypAlgos Platform"

    class Config:
        # computed once at import-time; can be overridden by setting ENV_FILE
        env_file: Final[str] = _resolve_env_file()
        env_file_encoding = "utf-8"


settings = Settings()
