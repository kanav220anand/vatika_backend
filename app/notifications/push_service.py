"""
Push Notification Service

This module handles sending push notifications to user devices via AWS SNS.
Supports both iOS (APNs) and Android (FCM) through SNS platform applications.

Key Features:
- Device token registration and management
- Push notification delivery via SNS
- Batched push for multiple devices
- Error handling and retry logic
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from bson import ObjectId

from app.core.database import Database
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class PushNotificationService:
    """
    Service for managing push notifications via AWS SNS.
    
    Handles device registration, token management, and push delivery.
    """
    
    @classmethod
    def _get_settings(cls):
        """Get application settings."""
        return get_settings()
    
    @classmethod
    def _get_devices_collection(cls):
        """Get device tokens MongoDB collection."""
        return Database.get_collection("device_tokens")
    
    @classmethod
    def _get_users_collection(cls):
        """Get users MongoDB collection."""
        return Database.get_collection("users")
    
    @classmethod
    def _get_sns_client(cls):
        """
        Get AWS SNS client.
        
        Returns:
            boto3 SNS client or None if not configured.
        """
        try:
            import boto3
            settings = cls._get_settings()
            
            return boto3.client(
                'sns',
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
        except Exception as e:
            logger.error(f"Failed to create SNS client: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Device Registration
    # -------------------------------------------------------------------------
    
    @classmethod
    async def register_device(
        cls,
        user_id: str,
        device_token: str,
        platform: str,  # "ios" or "android"
        device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Register a device for push notifications.
        
        Creates or updates device token in database and registers
        with AWS SNS platform application.
        
        Args:
            user_id: User's MongoDB ObjectId string.
            device_token: FCM or APNs device token.
            platform: "ios" or "android".
            device_id: Optional unique device identifier.
            
        Returns:
            Dict with registration result.
        """
        collection = cls._get_devices_collection()
        settings = cls._get_settings()
        now = datetime.utcnow()
        
        # Determine SNS platform application ARN
        if platform == "ios":
            platform_arn = settings.AWS_SNS_PLATFORM_ARN_IOS
        elif platform == "android":
            platform_arn = settings.AWS_SNS_PLATFORM_ARN_ANDROID
        else:
            return {"success": False, "error": f"Unknown platform: {platform}"}
        
        # Create SNS endpoint for this device
        endpoint_arn = None
        if platform_arn:
            endpoint_arn = await cls._create_platform_endpoint(
                platform_arn, 
                device_token,
                user_id
            )
        
        # Store/update device token in database
        filter_query = {
            "user_id": user_id,
            "device_token": device_token
        }
        
        update_doc = {
            "$set": {
                "user_id": user_id,
                "device_token": device_token,
                "platform": platform,
                "device_id": device_id,
                "endpoint_arn": endpoint_arn,
                "is_active": True,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            }
        }
        
        result = await collection.update_one(
            filter_query,
            update_doc,
            upsert=True
        )
        
        logger.info(f"Registered device for user {user_id}: {platform}")
        
        return {
            "success": True,
            "endpoint_arn": endpoint_arn,
            "is_new": result.upserted_id is not None
        }
    
    @classmethod
    async def _create_platform_endpoint(
        cls,
        platform_arn: str,
        device_token: str,
        user_id: str
    ) -> Optional[str]:
        """
        Create SNS platform endpoint for a device.
        
        Args:
            platform_arn: SNS Platform Application ARN.
            device_token: Device push token.
            user_id: User ID for custom data.
            
        Returns:
            Endpoint ARN or None if failed.
        """
        sns_client = cls._get_sns_client()
        if not sns_client:
            return None
        
        try:
            response = sns_client.create_platform_endpoint(
                PlatformApplicationArn=platform_arn,
                Token=device_token,
                CustomUserData=user_id
            )
            return response.get('EndpointArn')
        except Exception as e:
            # Handle already exists case
            if 'already exists' in str(e).lower():
                # Try to get existing endpoint
                return await cls._get_existing_endpoint(platform_arn, device_token)
            logger.error(f"Failed to create platform endpoint: {e}")
            return None
    
    @classmethod
    async def _get_existing_endpoint(
        cls,
        platform_arn: str,
        device_token: str
    ) -> Optional[str]:
        """Get existing endpoint ARN for a token."""
        # For now, return None - in production you'd query SNS
        return None
    
    @classmethod
    async def unregister_device(
        cls,
        user_id: str,
        device_token: str
    ) -> bool:
        """
        Unregister a device from push notifications.
        
        Args:
            user_id: User's MongoDB ObjectId string.
            device_token: Device token to unregister.
            
        Returns:
            True if device was unregistered, False otherwise.
        """
        collection = cls._get_devices_collection()
        
        # Mark device as inactive (soft delete)
        result = await collection.update_one(
            {"user_id": user_id, "device_token": device_token},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
        )
        
        if result.modified_count > 0:
            logger.info(f"Unregistered device for user {user_id}")
            return True
        
        return False
    
    @classmethod
    async def get_user_devices(cls, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all active devices for a user.
        
        Args:
            user_id: User's MongoDB ObjectId string.
            
        Returns:
            List of device documents.
        """
        collection = cls._get_devices_collection()
        
        cursor = collection.find({
            "user_id": user_id,
            "is_active": True
        })
        
        devices = []
        async for device in cursor:
            devices.append({
                "device_token": device.get("device_token"),
                "platform": device.get("platform"),
                "endpoint_arn": device.get("endpoint_arn"),
            })
        
        return devices
    
    # -------------------------------------------------------------------------
    # Push Notification Delivery
    # -------------------------------------------------------------------------
    
    @classmethod
    async def send_push(
        cls,
        user_id: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        badge: Optional[int] = None,
        silent: bool = False
    ) -> Dict[str, Any]:
        """
        Send push notification to all user's devices.
        
        Args:
            user_id: User's MongoDB ObjectId string.
            title: Notification title.
            body: Notification body text.
            data: Optional data payload.
            badge: Optional badge count for iOS.
            silent: If True, send silent notification.
            
        Returns:
            Dict with delivery results.
        """
        # Check user notification preferences
        users_collection = cls._get_users_collection()
        user = await users_collection.find_one(
            {"_id": ObjectId(user_id)},
            {"notifications_enabled": 1}
        )
        
        if user and user.get("notifications_enabled") is False:
            return {"success": False, "reason": "notifications_disabled"}
        
        # Get all active devices for user
        devices = await cls.get_user_devices(user_id)
        
        if not devices:
            logger.debug(f"No devices registered for user {user_id}")
            return {"success": False, "reason": "no_devices"}
        
        results = {
            "success": True,
            "sent": 0,
            "failed": 0,
            "devices": len(devices)
        }
        
        for device in devices:
            try:
                if device.get("endpoint_arn"):
                    await cls._send_to_endpoint(
                        endpoint_arn=device["endpoint_arn"],
                        platform=device.get("platform", "ios"),
                        title=title,
                        body=body,
                        data=data,
                        badge=badge,
                        silent=silent
                    )
                    results["sent"] += 1
                else:
                    # Fallback: Direct FCM/APNs (not implemented here)
                    results["failed"] += 1
            except Exception as e:
                logger.error(f"Failed to send push to device: {e}")
                results["failed"] += 1
        
        return results
    
    @classmethod
    async def _send_to_endpoint(
        cls,
        endpoint_arn: str,
        platform: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        badge: Optional[int] = None,
        silent: bool = False
    ) -> bool:
        """
        Send push notification to specific SNS endpoint.
        
        Args:
            endpoint_arn: SNS endpoint ARN.
            platform: "ios" or "android".
            title: Notification title.
            body: Notification body.
            data: Data payload.
            badge: iOS badge count.
            silent: Silent notification flag.
            
        Returns:
            True if sent successfully.
        """
        sns_client = cls._get_sns_client()
        if not sns_client:
            logger.warning("SNS client not available - push not sent")
            return False
        
        # Build platform-specific message
        message = cls._build_platform_message(
            platform=platform,
            title=title,
            body=body,
            data=data or {},
            badge=badge,
            silent=silent
        )
        
        try:
            sns_client.publish(
                TargetArn=endpoint_arn,
                Message=json.dumps(message),
                MessageStructure='json'
            )
            return True
        except Exception as e:
            error_msg = str(e)
            
            # Handle disabled endpoint
            if 'Endpoint is disabled' in error_msg:
                await cls._handle_disabled_endpoint(endpoint_arn)
            
            logger.error(f"Failed to publish to SNS: {e}")
            return False
    
    @classmethod
    def _build_platform_message(
        cls,
        platform: str,
        title: str,
        body: str,
        data: Dict[str, Any],
        badge: Optional[int] = None,
        silent: bool = False
    ) -> Dict[str, str]:
        """
        Build platform-specific push notification message.
        
        SNS requires different JSON structures for iOS and Android.
        
        Args:
            platform: "ios" or "android".
            title: Notification title.
            body: Notification body.
            data: Custom data payload.
            badge: iOS badge count.
            silent: Silent notification flag.
            
        Returns:
            Dict with platform-specific message JSONs.
        """
        if platform == "ios":
            # APNs payload
            apns_payload = {
                "aps": {
                    "alert": {
                        "title": title,
                        "body": body
                    },
                    "sound": "default" if not silent else None,
                    "content-available": 1 if silent else 0,
                }
            }
            
            if badge is not None:
                apns_payload["aps"]["badge"] = badge
            
            # Add custom data
            apns_payload.update(data)
            
            return {
                "APNS": json.dumps(apns_payload),
                "APNS_SANDBOX": json.dumps(apns_payload),  # For development
                "default": body
            }
        
        else:
            # FCM payload (Android)
            fcm_payload = {
                "notification": {
                    "title": title,
                    "body": body,
                },
                "data": {str(k): str(v) for k, v in data.items()},
            }
            
            if silent:
                # Remove notification for silent push
                del fcm_payload["notification"]
            
            return {
                "GCM": json.dumps(fcm_payload),
                "default": body
            }
    
    @classmethod
    async def _handle_disabled_endpoint(cls, endpoint_arn: str):
        """
        Handle a disabled SNS endpoint.
        
        Marks the device as inactive in our database.
        
        Args:
            endpoint_arn: The disabled endpoint ARN.
        """
        collection = cls._get_devices_collection()
        
        await collection.update_many(
            {"endpoint_arn": endpoint_arn},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
        )
        
        logger.info(f"Marked endpoint as inactive: {endpoint_arn}")
    
    # -------------------------------------------------------------------------
    # Batch Operations
    # -------------------------------------------------------------------------
    
    @classmethod
    async def send_push_to_users(
        cls,
        user_ids: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, int]:
        """
        Send push notification to multiple users.
        
        Args:
            user_ids: List of user MongoDB ObjectId strings.
            title: Notification title.
            body: Notification body.
            data: Optional data payload.
            
        Returns:
            Dict with batch send statistics.
        """
        stats = {
            "users": len(user_ids),
            "sent": 0,
            "failed": 0,
            "no_devices": 0
        }
        
        for user_id in user_ids:
            result = await cls.send_push(
                user_id=user_id,
                title=title,
                body=body,
                data=data
            )
            
            if result.get("success"):
                stats["sent"] += 1
            elif result.get("reason") == "no_devices":
                stats["no_devices"] += 1
            else:
                stats["failed"] += 1
        
        logger.info(f"Batch push complete: {stats}")
        return stats
