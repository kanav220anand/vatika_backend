"""Push notification service (devices + preferences)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from bson import ObjectId
from pymongo import ReturnDocument

from app.core.config import get_settings
from app.core.database import Database
from app.core.exceptions import BadRequestException, NotFoundException
from app.push.models import (
    PushDevicePermissions,
    PushDeviceRegisterRequest,
    PushDeviceRegisterResponse,
    PushDeviceStatus,
    PushDeviceUnbindResponse,
    PushPreferencesPatchRequest,
    PushPreferencesResponse,
    PushPlantPreferences,
    PushTestRequest,
    PushTestResponse,
    PushTestResult,
)

settings = get_settings()


class PushService:
    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _devices():
        return Database.get_collection("push_devices")

    @staticmethod
    def _prefs():
        return Database.get_collection("push_preferences")

    @staticmethod
    def _sns_client():
        if not (settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY):
            return None
        return boto3.client(
            "sns",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )

    @staticmethod
    def _sns_platform_application_arn(platform: str) -> Optional[str]:
        if platform == "ios":
            # In development, APNS tokens are typically sandbox; SNS requires using the APNS_SANDBOX platform app.
            if bool(getattr(settings, "DEBUG", False)):
                sandbox = (getattr(settings, "AWS_SNS_PLATFORM_APPLICATION_ARN_IOS_SANDBOX", "") or "").strip()
                if sandbox:
                    return sandbox
            return (getattr(settings, "AWS_SNS_PLATFORM_APPLICATION_ARN_IOS", "") or "").strip() or None
        if platform == "android":
            return (getattr(settings, "AWS_SNS_PLATFORM_APPLICATION_ARN_ANDROID", "") or "").strip() or None
        return None

    @classmethod
    def _device_status(cls, permissions: PushDevicePermissions) -> PushDeviceStatus:
        if not permissions.push_enabled:
            return PushDeviceStatus.inactive
        if not permissions.consent_given:
            return PushDeviceStatus.inactive
        return PushDeviceStatus.active

    @classmethod
    def _extract_existing_endpoint_arn(cls, error_message: str) -> Optional[str]:
        """
        SNS sometimes returns an error like:
          'Invalid parameter: Token Reason: Endpoint arn:aws:sns:... already exists with the same Token'
        """
        if not error_message:
            return None
        match = re.search(r"(arn:aws:sns:[^\\s]+:endpoint/[^\\s]+)", error_message)
        return match.group(1) if match else None

    @classmethod
    def _sns_create_or_reuse_endpoint(
        cls,
        *,
        platform: str,
        token: str,
        custom_user_data: str,
    ) -> Optional[str]:
        client = cls._sns_client()
        if not client:
            return None
        app_arn = cls._sns_platform_application_arn(platform)
        if not app_arn:
            return None

        try:
            resp = client.create_platform_endpoint(
                PlatformApplicationArn=app_arn,
                Token=token,
                CustomUserData=custom_user_data,
            )
            return resp.get("EndpointArn")
        except ClientError as e:
            # If the endpoint already exists for this token, reuse it.
            message = str(getattr(e, "response", {}).get("Error", {}).get("Message", "") or "")
            existing = cls._extract_existing_endpoint_arn(message)
            if existing:
                return existing
            raise

    @classmethod
    def _sns_set_endpoint_enabled(cls, endpoint_arn: str, *, enabled: bool) -> None:
        client = cls._sns_client()
        if not client:
            return
        if not endpoint_arn:
            return
        try:
            client.set_endpoint_attributes(
                EndpointArn=endpoint_arn,
                Attributes={"Enabled": "true" if enabled else "false"},
            )
        except ClientError:
            # Best-effort; endpoint may not exist / perms missing.
            return

    @classmethod
    def _build_sns_message_json(cls, *, title: str, body: str) -> str:
        """
        Build an SNS platform message with APNS + FCM variants.

        Note: Platform application type determines the delivery channel; including both is safe.
        """
        apns_payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}}
        fcm_payload = {"notification": {"title": title, "body": body}}
        envelope = {
            "default": body,
            "APNS": json.dumps(apns_payload, separators=(",", ":")),
            "APNS_SANDBOX": json.dumps(apns_payload, separators=(",", ":")),
            "GCM": json.dumps(fcm_payload, separators=(",", ":")),
        }
        return json.dumps(envelope, separators=(",", ":"))

    @classmethod
    def _sns_publish(cls, *, endpoint_arn: str, title: str, body: str) -> str:
        client = cls._sns_client()
        if not client:
            raise ValueError("SNS client is not configured.")
        message = cls._build_sns_message_json(title=title, body=body)
        resp = client.publish(TargetArn=endpoint_arn, MessageStructure="json", Message=message)
        return str(resp.get("MessageId") or "")

    @classmethod
    def _sns_error_details(cls, e: Exception) -> Tuple[Optional[str], str]:
        if isinstance(e, ClientError):
            err = (e.response or {}).get("Error") or {}
            code = (err.get("Code") or "").strip() or None
            message = (err.get("Message") or "").strip() or str(e)
            return code, message
        return None, str(e)

    @classmethod
    def _is_endpoint_invalid(cls, *, error_code: Optional[str], error_message: str) -> bool:
        code = (error_code or "").strip()
        msg = (error_message or "").lower()
        if code == "EndpointDisabled":
            return True
        if code in {"NotFound", "InvalidParameter"} and ("endpoint" in msg or "token" in msg):
            return True
        return False

    @classmethod
    async def _mark_device_inactive(cls, *, device_id: ObjectId, error_code: Optional[str], error_message: str) -> None:
        now = cls._now()
        await cls._devices().update_one(
            {"_id": device_id},
            {
                "$set": {
                    "status": PushDeviceStatus.inactive.value,
                    "updated_at": now,
                    "last_error": {"code": error_code, "message": error_message},
                    "last_error_at": now,
                }
            },
        )

    @classmethod
    async def send_test_push(cls, *, user_id: str, req: PushTestRequest) -> PushTestResponse:
        # Respect global setting unless explicitly forced.
        prefs = await cls.get_preferences(user_id=user_id)
        if not req.force and not prefs.global_enabled:
            return PushTestResponse(attempted=0, sent=0, failed=0, skipped_reason="global_disabled", results=[])

        query: Dict[str, Any] = {"user_id": user_id, "status": PushDeviceStatus.active.value}
        if req.app_install_id:
            query["app_install_id"] = req.app_install_id
        query["endpoint_arn"] = {"$exists": True, "$ne": None, "$ne": ""}

        cursor = cls._devices().find(query)
        results: list[PushTestResult] = []
        attempted = sent = failed = 0

        async for device in cursor:
            attempted += 1
            device_id = device.get("_id")
            endpoint_arn = (device.get("endpoint_arn") or "").strip()
            app_install_id = str(device.get("app_install_id") or "")
            try:
                message_id = cls._sns_publish(endpoint_arn=endpoint_arn, title=req.title, body=req.body)
                sent += 1
                await cls._devices().update_one(
                    {"_id": device_id},
                    {"$set": {"last_sent_at": cls._now(), "last_error": None, "last_error_at": None}},
                )
                await Database.get_collection("push_log").insert_one(
                    {
                        "user_id": user_id,
                        "device_id": str(device_id),
                        "endpoint_arn": endpoint_arn,
                        "type": "test",
                        "payload": {"title": req.title, "body": req.body},
                        "status": "sent",
                        "message_id": message_id,
                        "created_at": cls._now(),
                    }
                )
                results.append(
                    PushTestResult(
                        device_id=str(device_id),
                        app_install_id=app_install_id,
                        endpoint_arn=endpoint_arn,
                        status="sent",
                        message_id=message_id or None,
                    )
                )
            except Exception as e:
                failed += 1
                error_code, error_message = cls._sns_error_details(e)
                if isinstance(device_id, ObjectId) and cls._is_endpoint_invalid(
                    error_code=error_code, error_message=error_message
                ):
                    try:
                        await cls._mark_device_inactive(
                            device_id=device_id,
                            error_code=error_code,
                            error_message=error_message,
                        )
                    except Exception:
                        pass
                try:
                    await Database.get_collection("push_log").insert_one(
                        {
                            "user_id": user_id,
                            "device_id": str(device_id),
                            "endpoint_arn": endpoint_arn,
                            "type": "test",
                            "payload": {"title": req.title, "body": req.body},
                            "status": "failed",
                            "error": {"code": error_code, "message": error_message},
                            "created_at": cls._now(),
                        }
                    )
                except Exception:
                    pass
                results.append(
                    PushTestResult(
                        device_id=str(device_id),
                        app_install_id=app_install_id,
                        endpoint_arn=endpoint_arn,
                        status="failed",
                        error_code=error_code,
                        error_message=error_message,
                    )
                )

        return PushTestResponse(
            attempted=attempted,
            sent=sent,
            failed=failed,
            skipped_reason=None,
            results=results,
        )

    @classmethod
    async def register_device(cls, *, user_id: str, req: PushDeviceRegisterRequest) -> PushDeviceRegisterResponse:
        # GDPR: explicit opt-in required before token registration.
        if not req.permissions.consent_given:
            raise BadRequestException("Push consent is required before registering this device.")

        now = cls._now()
        status = cls._device_status(req.permissions)

        # Create/update SNS endpoint (best-effort).
        endpoint_arn = None
        try:
            endpoint_arn = cls._sns_create_or_reuse_endpoint(
                platform=req.platform.value,
                token=req.token,
                custom_user_data=f"user_id={user_id};app_install_id={req.app_install_id}",
            )
            if endpoint_arn:
                cls._sns_set_endpoint_enabled(endpoint_arn, enabled=(status == PushDeviceStatus.active))
        except Exception:
            # Allow registration to succeed even if SNS isn't configured yet.
            endpoint_arn = None

        update_doc: Dict[str, Any] = {
            "user_id": user_id,
            "platform": req.platform.value,
            "token": req.token,
            "status": status.value,
            "device_meta": req.device_meta.model_dump(exclude_none=True),
            "permissions": {
                "push_enabled": bool(req.permissions.push_enabled),
                "consent_given": bool(req.permissions.consent_given),
                "consent_updated_at": now,
            },
            "last_seen_at": now,
            "updated_at": now,
        }
        # Only overwrite endpoint_arn when we successfully computed one (avoid clobbering a previously stored ARN).
        if endpoint_arn:
            update_doc["endpoint_arn"] = endpoint_arn

        doc = await cls._devices().find_one_and_update(
            {"app_install_id": req.app_install_id},
            {
                "$set": update_doc,
                "$setOnInsert": {"app_install_id": req.app_install_id, "created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        return PushDeviceRegisterResponse(
            device_id=str(doc["_id"]),
            endpoint_arn=doc.get("endpoint_arn"),
            status=PushDeviceStatus(doc.get("status") or PushDeviceStatus.inactive.value),
            updated_at=doc.get("updated_at") or now,
        )

    @classmethod
    async def unbind_device(cls, *, user_id: str, app_install_id: str) -> PushDeviceUnbindResponse:
        now = cls._now()
        doc = await cls._devices().find_one_and_update(
            {"app_install_id": app_install_id, "user_id": user_id},
            {
                "$set": {
                    "user_id": None,
                    "status": PushDeviceStatus.inactive.value,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            raise NotFoundException("Device not found for current user.")

        # Best-effort: disable endpoint.
        try:
            endpoint_arn = (doc.get("endpoint_arn") or "").strip()
            if endpoint_arn:
                cls._sns_set_endpoint_enabled(endpoint_arn, enabled=False)
        except Exception:
            pass

        return PushDeviceUnbindResponse(status=PushDeviceStatus.inactive, updated_at=doc.get("updated_at") or now)

    @classmethod
    async def get_preferences(cls, *, user_id: str) -> PushPreferencesResponse:
        doc = await cls._prefs().find_one({"user_id": user_id})
        if not doc:
            # Default behavior matches the existing user-level toggle in `users.notifications_enabled`.
            user = None
            try:
                if ObjectId.is_valid(user_id):
                    user = await Database.get_collection("users").find_one(
                        {"_id": ObjectId(user_id)},
                        {"notifications_enabled": 1},
                    )
            except Exception:
                user = None
            global_enabled = bool((user or {}).get("notifications_enabled", True))
            now = cls._now()
            return PushPreferencesResponse(
                user_id=user_id,
                global_enabled=global_enabled,
                plants={},
                quiet_hours=None,
                updated_at=now,
            )

        plants_raw = doc.get("plants") or {}
        plants: Dict[str, PushPlantPreferences] = {}
        if isinstance(plants_raw, dict):
            for plant_id, prefs in plants_raw.items():
                if isinstance(prefs, dict):
                    plants[str(plant_id)] = PushPlantPreferences(**prefs)

        return PushPreferencesResponse(
            user_id=user_id,
            global_enabled=bool(doc.get("global_enabled", True)),
            plants=plants,
            quiet_hours=doc.get("quiet_hours"),
            updated_at=doc.get("updated_at") or cls._now(),
        )

    @classmethod
    async def patch_preferences(cls, *, user_id: str, req: PushPreferencesPatchRequest) -> PushPreferencesResponse:
        now = cls._now()
        update: Dict[str, Any] = {"updated_at": now}
        if req.global_enabled is not None:
            update["global_enabled"] = bool(req.global_enabled)
            # Keep the existing `users.notifications_enabled` flag in sync for backward compatibility.
            try:
                if ObjectId.is_valid(user_id):
                    await Database.get_collection("users").update_one(
                        {"_id": ObjectId(user_id)},
                        {"$set": {"notifications_enabled": bool(req.global_enabled)}},
                    )
            except Exception:
                pass
        if req.quiet_hours is not None:
            update["quiet_hours"] = req.quiet_hours
        if req.plants is not None:
            update["plants"] = {
                plant_id: prefs.model_dump(exclude_none=True) for plant_id, prefs in req.plants.items()
            }

        doc = await cls._prefs().find_one_and_update(
            {"user_id": user_id},
            {"$set": update, "$setOnInsert": {"user_id": user_id, "created_at": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        plants_raw = doc.get("plants") or {}
        plants: Dict[str, PushPlantPreferences] = {}
        if isinstance(plants_raw, dict):
            for plant_id, prefs in plants_raw.items():
                if isinstance(prefs, dict):
                    plants[str(plant_id)] = PushPlantPreferences(**prefs)

        return PushPreferencesResponse(
            user_id=user_id,
            global_enabled=bool(doc.get("global_enabled", True)),
            plants=plants,
            quiet_hours=doc.get("quiet_hours"),
            updated_at=doc.get("updated_at") or now,
        )
