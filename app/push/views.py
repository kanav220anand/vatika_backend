"""Push notifications API routes (device registration + preferences)."""

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.exceptions import ForbiddenException
from app.push.models import (
    PushDeviceRegisterRequest,
    PushDeviceRegisterResponse,
    PushDeviceUnbindRequest,
    PushDeviceUnbindResponse,
    PushPreferencesPatchRequest,
    PushPreferencesResponse,
    PushTestRequest,
    PushTestResponse,
)
from app.push.service import PushService

router = APIRouter(prefix="/push", tags=["Push Notifications"])
settings = get_settings()


@router.post("/devices", response_model=PushDeviceRegisterResponse)
async def register_device(
    req: PushDeviceRegisterRequest,
    current_user: dict = Depends(get_current_user),
):
    return await PushService.register_device(user_id=current_user["id"], req=req)


@router.post("/devices/unbind", response_model=PushDeviceUnbindResponse)
async def unbind_device(
    req: PushDeviceUnbindRequest,
    current_user: dict = Depends(get_current_user),
):
    return await PushService.unbind_device(user_id=current_user["id"], app_install_id=req.app_install_id)


@router.get("/preferences", response_model=PushPreferencesResponse)
async def get_preferences(current_user: dict = Depends(get_current_user)):
    return await PushService.get_preferences(user_id=current_user["id"])


@router.patch("/preferences", response_model=PushPreferencesResponse)
async def patch_preferences(
    req: PushPreferencesPatchRequest,
    current_user: dict = Depends(get_current_user),
):
    return await PushService.patch_preferences(user_id=current_user["id"], req=req)


@router.post("/test", response_model=PushTestResponse)
async def test_push(
    req: PushTestRequest,
    current_user: dict = Depends(get_current_user),
):
    if not bool(settings.DEBUG):
        raise ForbiddenException("Test push endpoint is not available in production.")
    return await PushService.send_test_push(user_id=current_user["id"], req=req)
