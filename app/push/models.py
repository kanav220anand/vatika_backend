"""Push notification models and schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PushPlatform(str, Enum):
    ios = "ios"
    android = "android"


class PushDeviceStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class PushDeviceMeta(BaseModel):
    device_model: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None


class PushDevicePermissions(BaseModel):
    push_enabled: bool = True
    consent_given: bool = False


class PushDeviceRegisterRequest(BaseModel):
    app_install_id: str = Field(..., min_length=4, max_length=128)
    platform: PushPlatform
    token: str = Field(..., min_length=8, max_length=4096)
    device_meta: PushDeviceMeta = Field(default_factory=PushDeviceMeta)
    permissions: PushDevicePermissions = Field(default_factory=PushDevicePermissions)


class PushDeviceRegisterResponse(BaseModel):
    device_id: str
    endpoint_arn: Optional[str] = None
    status: PushDeviceStatus
    updated_at: datetime


class PushDeviceUnbindRequest(BaseModel):
    app_install_id: str = Field(..., min_length=4, max_length=128)


class PushDeviceUnbindResponse(BaseModel):
    status: PushDeviceStatus
    updated_at: datetime


class ConsentState(str, Enum):
    accepted = "accepted"
    dismissed = "dismissed"


class PushPlantPreferences(BaseModel):
    reminders_enabled: Optional[bool] = None
    consent_state: Optional[ConsentState] = None


class PushPreferencesPatchRequest(BaseModel):
    global_enabled: Optional[bool] = None
    plants: Optional[Dict[str, PushPlantPreferences]] = None
    quiet_hours: Optional[Dict[str, Any]] = None


class PushPreferencesResponse(BaseModel):
    user_id: str
    global_enabled: bool
    plants: Dict[str, PushPlantPreferences] = Field(default_factory=dict)
    quiet_hours: Optional[Dict[str, Any]] = None
    updated_at: datetime


class PushTestRequest(BaseModel):
    title: str = Field(default="Test notification", min_length=1, max_length=120)
    body: str = Field(default="Hello from Vatisha 👋", min_length=1, max_length=1000)
    app_install_id: Optional[str] = Field(default=None, min_length=4, max_length=128)
    force: bool = Field(
        default=False,
        description="Send even if the user has global notifications disabled (debug-only endpoint).",
    )


class PushTestResult(BaseModel):
    device_id: str
    app_install_id: str
    endpoint_arn: str
    status: str
    message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class PushTestResponse(BaseModel):
    attempted: int
    sent: int
    failed: int
    skipped_reason: Optional[str] = None
    results: List[PushTestResult] = Field(default_factory=list)
