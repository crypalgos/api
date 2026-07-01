import logging
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from app.advices.base_response_handler import BaseResponseHandler
from app.middlewares.auth_middleware import get_current_user
from app.modules.user_service.services.credential_service import credential_service, Exchange

logger = logging.getLogger(__name__)

credential_router = APIRouter(prefix="/credentials", tags=["Credentials & Preferences"])

class SaveBrokerCredentialSchema(BaseModel):
    exchange: Exchange = Field(..., description="Target exchange")
    account_label: str = Field(..., max_length=100, description="Friendly label for the account")
    api_key: str = Field(..., description="API key from exchange")
    api_secret: str = Field(..., description="API secret from exchange")
    passphrase: Optional[str] = Field(None, description="Optional passphrase")
    is_testnet: bool = Field(True, description="Sandbox / live environment switch")

class VerifyBrokerCredentialSchema(BaseModel):
    exchange: Exchange = Field(..., description="Target exchange")
    api_key: str = Field(..., description="API key")
    api_secret: str = Field(..., description="API secret")
    passphrase: Optional[str] = Field(None, description="Optional passphrase")
    is_testnet: bool = Field(True, description="Sandbox / live environment")

class SaveNotificationPreferenceSchema(BaseModel):
    telegram_chat_id: Optional[str] = Field(None, description="Telegram user chat ID")
    telegram_enabled: bool = Field(False, description="Master enable/disable switch")
    timezone: str = Field("UTC", description="User preferred timezone")
    paper_alerts: bool = Field(True, description="Notify on paper-trading fills")
    live_alerts: bool = Field(True, description="Notify on live-trading fills")
    stoploss_alerts: bool = Field(True, description="Notify on Stop Loss executions")
    tp_alerts: bool = Field(True, description="Notify on Take Profit executions")

@credential_router.post("/broker")
async def save_broker(
    payload: SaveBrokerCredentialSchema,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    user_id = current_user["user_id"]
    try:
        cred_id = await credential_service.save_broker_credential(
            user_id=user_id,
            exchange=payload.exchange,
            account_label=payload.account_label,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            passphrase=payload.passphrase,
            is_testnet=payload.is_testnet
        )
        return BaseResponseHandler.success_response(
            data={"credential_id": cred_id},
            message="Broker credentials saved successfully.",
            status_code=201
        )
    except Exception as e:
        logger.error(f"Error saving broker credentials: {e}")
        return BaseResponseHandler.error_response(
            message=str(e),
            status_code=400
        )

@credential_router.post("/broker/verify")
async def verify_broker(
    payload: VerifyBrokerCredentialSchema,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    res = await credential_service.verify_broker_credential(
        exchange=payload.exchange,
        api_key=payload.api_key,
        api_secret=payload.api_secret,
        passphrase=payload.passphrase,
        is_testnet=payload.is_testnet
    )
    return BaseResponseHandler.success_response(
        data={
            "success": res.success,
            "exchange": res.exchange.value,
            "account_name": res.account_name,
            "permissions": res.permissions,
            "is_testnet": res.is_testnet,
            "message": res.message
        },
        status_code=200
    )

@credential_router.get("/broker")
async def list_brokers(
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    user_id = current_user["user_id"]
    creds = await credential_service.list_user_credentials(user_id)
    return BaseResponseHandler.success_response(data=creds, status_code=200)

@credential_router.post("/preferences/notifications")
async def save_notification_pref(
    payload: SaveNotificationPreferenceSchema,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    user_id = current_user["user_id"]
    await credential_service.save_notification_preference(user_id, payload.model_dump())
    return BaseResponseHandler.success_response(
        message="Notification preferences updated successfully.",
        status_code=200
    )

@credential_router.get("/preferences/notifications")
async def get_notification_pref(
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    user_id = current_user["user_id"]
    prefs = await credential_service.get_notification_preference(user_id)
    return BaseResponseHandler.success_response(data=prefs, status_code=200)

class RotateBrokerCredentialSchema(BaseModel):
    api_key: str = Field(..., description="New API key")
    api_secret: str = Field(..., description="New API secret")
    passphrase: Optional[str] = Field(None, description="Optional new passphrase")

@credential_router.post("/broker/{credential_id}/rotate")
async def rotate_broker(
    credential_id: str,
    payload: RotateBrokerCredentialSchema,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    user_id = current_user["user_id"]
    try:
        success = await credential_service.rotate_broker_credential(
            credential_id=credential_id,
            user_id=user_id,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            passphrase=payload.passphrase
        )
        return BaseResponseHandler.success_response(
            message="Broker credentials rotated successfully.",
            status_code=200
        )
    except Exception as e:
        logger.error(f"Error rotating broker credentials: {e}")
        return BaseResponseHandler.error_response(
            message=str(e),
            status_code=400
        )
