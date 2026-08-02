import os
from typing import Final

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
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


# Load env variables into os.environ for external library compatibility
load_dotenv(_resolve_env_file())


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://username:password@localhost:5432/your_database"
    )
    env: str = "development"
    debug: bool = True
    waitlist: bool = True
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
    google_client_id: str = ""
    google_client_secret: str = ""
    admin_email: str = "ashishjangde54@gmail.com"  # override with ADMIN_EMAIL
    sandbox_enabled: bool = (
        False  # Set SANDBOX_ENABLED=true in .env.prod for Docker gVisor path
    )
    app_environment: str = Field(
        default_factory=lambda: (
            os.environ.get("APP_ENV") or os.environ.get("ENV") or os.environ.get("PY_ENV") or "development"
        ).lower()
    )
    encryption_key: str = Field(
        default="dGhpc19pc19hX2RlZmF1bHRfa2V5XzMyYnl0ZXNfISE=",  # default 32-byte urlsafe base64 key
        validation_alias=AliasChoices("encryption_key", "credential_encryption_key")
    )
    s3_bucket_name: str = ""
    # Gates split-artifact report delivery (report_split.py). Off -> task
    # completion writes the old monolithic report.msgpack.zstd blob (current
    # behavior). On -> new runs write per-tab sections instead, each proxied
    # through the same /artifacts/{type} endpoint as before (no direct S3
    # access from the browser). Flip off for an instant rollback with no
    # redeploy; reading old runs' reports always works regardless of this
    # flag (get_run_artifact falls back to report_s3_key).
    report_delivery_v2_enabled: bool = False
    # Durable per-session Testnet workspaces. They are intentionally separate
    # from the production ClickHouse market-data store.
    live_session_workspace_dir: str = "workspaces/live-sessions"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_default_region: str = "us-east-1"
    # Days an unpinned (is_favorite=False) Analyse-tab temporary run is kept
    # before the daily cleanup task deletes it. Pinned runs are never touched.
    temporary_run_retention_days: int = 30
    # The API/Celery processes consume the dedicated streamer-service; they
    # never open their own production exchange WebSocket.
    streamer_zmq_address: str = Field(
        default="tcp://127.0.0.1:5555",
        validation_alias=AliasChoices("streamer_zmq_address", "crypalgos_zmq_address"),
    )

    class Config:
        # computed once at import-time; can be overridden by setting ENV_FILE
        env_file: Final[str] = _resolve_env_file()
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
