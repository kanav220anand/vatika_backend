"""Plant service - handles plant CRUD and knowledge base operations."""

import base64
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import uuid4
from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.config import get_settings
from app.plants.models import (
    PlantCreate,
    PlantResponse,
    PlantAnalysisResponse,
    CareSchedule,
)
from app.plants.care_utils import convert_care_schedule_to_stored
from app.plants.video_service import ImageService
from app.core.aws import S3Service


class PlantService:
    """Handles plant-related database operations."""
    
    @staticmethod
    def _get_plants_collection():
        return Database.get_collection("plants")
    
    @staticmethod
    def _get_knowledge_collection():
        return Database.get_collection("plant_knowledge")
    
    @staticmethod
    def _validate_object_id(id_str: str) -> ObjectId:
        """Validate and convert string to ObjectId."""
        if not ObjectId.is_valid(id_str):
            raise BadRequestException("Invalid plant ID")
        return ObjectId(id_str)
    
    @staticmethod
    def get_current_season() -> str:
        """Return current season based on Indian climate."""
        month = datetime.utcnow().month
        if month in [3, 4, 5]:      # Mar-May: Summer
            return "summer"
        elif month in [6, 7, 8, 9]: # Jun-Sept: Monsoon
            return "monsoon"
        else:                        # Oct-Feb: Winter
            return "winter"
    
    @classmethod
    def calculate_next_water_date(cls, plant_doc: dict) -> Optional[datetime]:
        """Calculate when plant needs water next based on care schedule."""
        last_watered = plant_doc.get("last_watered")
        care = plant_doc.get("care_schedule")
        
        if not care:
            return None
        
        watering = care.get("watering", {})
        if not watering:
            return None
        
        season = cls.get_current_season()
        days = watering.get(season, 3)  # Default 3 days
        
        if last_watered:
            return last_watered + timedelta(days=days)
        # If never watered, default to created_at baseline (prevents immediate "overdue" on new plants)
        created_at = plant_doc.get("created_at") or datetime.utcnow()
        return created_at + timedelta(days=days)

    @staticmethod
    def _normalize_action(action: str) -> str:
        return " ".join((action or "").strip().lower().split())

    @classmethod
    def _merge_immediate_fixes(cls, existing: List[dict], new_actions: List[str]) -> List[dict]:
        """
        Merge new immediate action strings into existing immediate_fixes.
        - Never removes older fixes.
        - Avoids duplicates (case/whitespace-insensitive).
        - Preserves is_done state.
        """
        existing = list(existing or [])
        seen = {cls._normalize_action((f or {}).get("action")) for f in existing if (f or {}).get("action")}

        for action in (new_actions or []):
            norm = cls._normalize_action(action)
            if not norm or norm in seen:
                continue
            existing.append(
                {
                    "id": str(uuid4()),
                    "action": action.strip(),
                    "is_done": False,
                    "created_at": datetime.utcnow(),
                    "completed_at": None,
                }
            )
            seen.add(norm)
        return existing

    @classmethod
    async def _ensure_immediate_fixes(cls, plant_doc: dict) -> dict:
        """
        Backfill immediate_fixes from legacy health_immediate_actions for older plants.
        Persists the migration once so IDs are stable for checklist toggles.
        """
        if not plant_doc or not isinstance(plant_doc, dict) or not plant_doc.get("_id"):
            return plant_doc

        if plant_doc.get("immediate_fixes"):
            return plant_doc

        legacy = plant_doc.get("health_immediate_actions") or []
        if not legacy:
            return plant_doc

        fixes = cls._merge_immediate_fixes([], legacy)
        plant_doc["immediate_fixes"] = fixes

        try:
            await cls._get_plants_collection().update_one({"_id": plant_doc["_id"]}, {"$set": {"immediate_fixes": fixes}})
        except Exception:
            pass

        return plant_doc

    @staticmethod
    def _compute_health_score(status: Optional[str], severity: Optional[str]) -> Optional[int]:
        """
        Store a user-facing health score (0–100) derived from status/severity.
        We keep it out of the UI for now, but store it for future use.
        """
        if not status:
            return None

        base_by_status = {
            "healthy": 90,
            "stressed": 65,
            "unhealthy": 40,
        }
        base = base_by_status.get(status)
        if base is None:
            return None

        severity_delta = {
            "low": 5,
            "medium": 0,
            "high": -10,
        }.get(severity or "medium", 0)

        return max(0, min(100, int(base + severity_delta)))
    
    # ==================== User Plants CRUD ====================
    
    @classmethod
    async def create_plant(cls, user_id: str, plant_data: PlantCreate) -> PlantResponse:
        """Save a plant to user's collection."""
        collection = cls._get_plants_collection()

        care_schedule_doc = None
        if plant_data.care_schedule:
            care_schedule_doc = plant_data.care_schedule.model_dump()
        else:
            care_source = None
            if plant_data.care:
                care_source = plant_data.care.model_dump()
            else:
                # Fallback: try the knowledge base (populated during /analyze)
                try:
                    knowledge = await cls._get_knowledge_collection().find_one({"plant_id": plant_data.plant_id})
                    if knowledge and knowledge.get("care"):
                        care_source = knowledge["care"]
                except Exception:
                    care_source = None

            if care_source:
                care_schedule_doc = convert_care_schedule_to_stored(care_source)
        
        plant_doc = {
            "user_id": user_id,
            "plant_id": plant_data.plant_id,
            "scientific_name": plant_data.scientific_name,
            "common_name": plant_data.common_name,
            "nickname": plant_data.nickname or plant_data.common_name,
            "image_url": plant_data.image_url,
            "health_status": plant_data.health_status,
            "notes": plant_data.notes,
            "last_watered": plant_data.last_watered,
            "watering_streak": 0,
            "created_at": datetime.utcnow(),
            # Care reminder fields
            "care_schedule": care_schedule_doc,
            "reminders_enabled": plant_data.reminders_enabled,
            "last_health_check": datetime.utcnow(),
        }

        # Persist latest health details if available (from /analyze)
        if plant_data.health:
            confidence_bucket = cls._confidence_bucket(plant_data.confidence, plant_data.health.confidence)
            immediate_fixes = cls._merge_immediate_fixes(
                plant_doc.get("immediate_fixes", []),
                plant_data.health.immediate_actions,
            )
            health_score = cls._compute_health_score(plant_data.health.status, plant_data.health.severity)
            plant_doc.update(
                {
                    "health_confidence": plant_data.health.confidence,
                    "health_primary_issue": plant_data.health.primary_issue,
                    "health_severity": plant_data.health.severity,
                    "confidence_bucket": confidence_bucket,
                    "plant_family": plant_data.plant_family,
                    "health_issues": plant_data.health.issues,
                    "health_immediate_actions": plant_data.health.immediate_actions,
                    "immediate_fixes": immediate_fixes,
                    "health_score": health_score,
                }
            )
        
        result = await collection.insert_one(plant_doc)
        plant_doc["_id"] = result.inserted_id

        # Save initial health snapshot for timeline/history
        if plant_data.health:
            try:
                await cls.save_health_snapshot(
                    plant_id=str(result.inserted_id),
                    user_id=user_id,
                    health_status=plant_data.health.status,
                    confidence=plant_data.health.confidence,
                    issues=plant_data.health.issues,
                    immediate_actions=plant_data.health.immediate_actions,
                    image_url=plant_data.image_url,
                )
            except Exception:
                pass
        
        # Generate health notification if plant is not healthy
        if plant_data.health_status != "healthy":
            try:
                from app.notifications.service import NotificationService
                await NotificationService.generate_health_notification(
                    user_id=user_id,
                    plant_id=str(result.inserted_id),
                    plant_name=plant_data.common_name,
                    health_status=plant_data.health_status
                )
            except Exception:
                pass  # Don't fail plant creation if notification fails
        
        # Gamification: Add score for adding a plant (10 pts per plant)
        try:
            from app.auth.service import AuthService
            await AuthService.add_score(user_id, 10)
        except Exception:
            pass
        
        # Check and unlock any earned achievements
        try:
            from app.achievements.service import AchievementService
            await AchievementService.check_and_unlock_achievements(user_id)
        except Exception:
            pass  # Don't fail plant creation if achievement check fails
        
        # Log event
        try:
            from app.plants.events_service import EventService, EventType
            await EventService.log_event(
                user_id=user_id,
                event_type=EventType.PLANT_ADDED,
                plant_id=str(result.inserted_id),
                metadata={"plant_name": plant_data.common_name}
            )
        except Exception:
            pass

        return cls._doc_to_response(plant_doc)

    @staticmethod
    def _confidence_bucket(plant_confidence: Optional[float], health_confidence: Optional[float]) -> str:
        """
        Bucket for downstream systems.
        Uses plant identification confidence when available; falls back to health confidence.
        """
        value = plant_confidence if isinstance(plant_confidence, (int, float)) else health_confidence
        if value is None:
            return "low"
        if value >= 0.85:
            return "high"
        if value >= 0.65:
            return "medium"
        return "low"

    
    @classmethod
    async def get_user_plants(cls, user_id: str, skip: int = 0, limit: int = 50) -> List[PlantResponse]:
        """Get plants for a user with pagination."""
        collection = cls._get_plants_collection()
        cursor = collection.find({"user_id": user_id}).sort("created_at", -1).skip(skip).limit(limit)
        plants = await cursor.to_list(length=limit)
        migrated = []
        for p in plants:
            migrated.append(await cls._ensure_immediate_fixes(p))
        return [cls._doc_to_response(p) for p in migrated]
    
    @classmethod
    async def get_plants_needing_water(cls, user_id: str) -> List[PlantResponse]:
        """Get plants that need watering (due today or overdue)."""
        collection = cls._get_plants_collection()
        now = datetime.utcnow()
        
        # Get all user's plants with reminders enabled
        cursor = collection.find({
            "user_id": user_id,
            "reminders_enabled": True,
            "care_schedule": {"$ne": None}
        })
        
        due_plants = []
        async for doc in cursor:
            next_water = cls.calculate_next_water_date(doc)
            if next_water and next_water <= now:
                due_plants.append(cls._doc_to_response(doc))
        
        return due_plants
    
    @classmethod
    async def get_plant_by_id(cls, plant_id: str, user_id: str) -> PlantResponse:
        """Get a specific plant by ID."""
        object_id = cls._validate_object_id(plant_id)
        collection = cls._get_plants_collection()
        
        plant = await collection.find_one({
            "_id": object_id,
            "user_id": user_id,
        })
        
        if not plant:
            raise NotFoundException("Plant not found")

        plant = await cls._ensure_immediate_fixes(plant)
        return cls._doc_to_response(plant)
    
    @classmethod
    async def update_plant(cls, plant_id: str, user_id: str, updates: dict) -> PlantResponse:
        """Update a plant."""
        object_id = cls._validate_object_id(plant_id)
        collection = cls._get_plants_collection()
        
        # Remove None values
        updates = {k: v for k, v in updates.items() if v is not None}
        
        if updates:
            result = await collection.find_one_and_update(
                {"_id": object_id, "user_id": user_id},
                {"$set": updates},
                return_document=True,
            )
        else:
            result = await collection.find_one({"_id": object_id, "user_id": user_id})
        
        if not result:
            raise NotFoundException("Plant not found")
        
        return cls._doc_to_response(result)

    @classmethod
    async def update_immediate_fix_status(
        cls, plant_id: str, user_id: str, fix_id: str, is_done: bool
    ) -> PlantResponse:
        """Toggle an immediate fix's done state (plant owner only)."""
        object_id = cls._validate_object_id(plant_id)
        collection = cls._get_plants_collection()

        plant = await collection.find_one({"_id": object_id, "user_id": user_id})
        if not plant:
            raise NotFoundException("Plant not found")

        fixes = plant.get("immediate_fixes") or []
        if not isinstance(fixes, list):
            raise NotFoundException("Immediate fix not found")

        found = False
        now = datetime.utcnow()
        for fix in fixes:
            if isinstance(fix, dict) and str(fix.get("id")) == str(fix_id):
                fix["is_done"] = bool(is_done)
                fix["completed_at"] = now if is_done else None
                found = True
                break

        if not found:
            raise NotFoundException("Immediate fix not found")

        await collection.update_one({"_id": object_id}, {"$set": {"immediate_fixes": fixes}})
        plant["immediate_fixes"] = fixes
        return cls._doc_to_response(plant)
    
    @classmethod
    async def delete_plant(cls, plant_id: str, user_id: str) -> bool:
        """Delete a plant."""
        object_id = cls._validate_object_id(plant_id)
        collection = cls._get_plants_collection()
        
        result = await collection.delete_one({
            "_id": object_id,
            "user_id": user_id,
        })
        
        if result.deleted_count == 0:
            raise NotFoundException("Plant not found")
        
        return True
    
    @classmethod
    async def mark_watered(cls, plant_id: str, user_id: str) -> PlantResponse:
        """Mark a plant as watered and update streak."""
        object_id = cls._validate_object_id(plant_id)
        collection = cls._get_plants_collection()
        
        # Get current plant to check streak
        plant = await collection.find_one({"_id": object_id, "user_id": user_id})
        if not plant:
            raise NotFoundException("Plant not found")
        
        now = datetime.utcnow()
        last_watered = plant.get("last_watered")
        current_streak = plant.get("watering_streak", 0)
        
        # Calculate new streak
        if last_watered:
            days_since = (now - last_watered).days
            if days_since <= 3:  # Watered within reasonable schedule
                new_streak = current_streak + 1
            elif days_since > 7:  # Too long, reset streak
                new_streak = 1
            else:
                new_streak = current_streak + 1  # Still counting
        else:
            new_streak = 1  # First watering
        
        result = await collection.find_one_and_update(
            {"_id": object_id, "user_id": user_id},
            {"$set": {"last_watered": now, "watering_streak": new_streak}},
            return_document=True
        )

        # Gamification: Add score for watering (2 pts, daily cap handled by frontend)
        if result:
            try:
                from app.auth.service import AuthService
                await AuthService.add_score(user_id, 2)
                
                # Weekly streak bonus (20 pts)
                if new_streak > 0 and new_streak % 7 == 0:
                   await AuthService.add_score(user_id, 20)
                # Monthly streak bonus (75 pts) 
                if new_streak > 0 and new_streak % 30 == 0:
                   await AuthService.add_score(user_id, 75)
            except Exception:
                pass
            
            # Check and unlock any earned achievements
            try:
                from app.achievements.service import AchievementService
                await AchievementService.check_and_unlock_achievements(user_id)
            except Exception:
                pass  # Don't fail watering if achievement check fails

            try:
                from app.plants.events_service import EventService, EventType
                await EventService.log_event(
                    user_id=user_id,
                    event_type=EventType.PLANT_WATERED,
                    plant_id=plant_id,
                    metadata={"last_watered": now},
                )
            except Exception:
                pass
        
        return cls._doc_to_response(result)
    
    # ==================== Plant Knowledge Base ====================
    
    @classmethod
    async def get_care_info(cls, plant_id: str) -> CareSchedule:
        """Get care info from knowledge base."""
        collection = cls._get_knowledge_collection()
        knowledge = await collection.find_one({"plant_id": plant_id})
        
        if not knowledge or "care" not in knowledge:
            raise NotFoundException(
                f"Care info for '{plant_id}' not found. "
                "Analyze a plant image first to add it to our knowledge base."
            )
        
        return CareSchedule(**knowledge["care"])
    
    @classmethod
    async def save_to_knowledge_base(cls, analysis: PlantAnalysisResponse, source: str = "openai"):
        """
        Save plant analysis to knowledge base for future use.
        This is the hybrid approach - we gradually build our own database.
        """
        collection = cls._get_knowledge_collection()
        
        # Check if already exists
        existing = await collection.find_one({"plant_id": analysis.plant_id})
        
        if existing:
            # Don't overwrite curated data with OpenAI data
            if existing.get("source") == "curated":
                return
        
        knowledge_doc = {
            "plant_id": analysis.plant_id,
            "scientific_name": analysis.scientific_name,
            "common_names": [analysis.common_name],
            "care": analysis.care.model_dump(),
            "created_at": datetime.utcnow(),
            "source": source,
        }
        
        await collection.update_one(
            {"plant_id": analysis.plant_id},
            {"$set": knowledge_doc},
            upsert=True,
        )
    
    @classmethod
    async def search_knowledge_base(cls, query: str) -> List[dict]:
        """Search plant knowledge base by name."""
        collection = cls._get_knowledge_collection()
        
        cursor = collection.find({
            "$or": [
                {"common_names": {"$regex": query, "$options": "i"}},
                {"scientific_name": {"$regex": query, "$options": "i"}},
                {"plant_id": {"$regex": query, "$options": "i"}},
            ]
        }).limit(10)
        
        results = await cursor.to_list(length=10)
        
        # Convert ObjectId to string
        for r in results:
            r["_id"] = str(r["_id"])
        
        return results
    
    # ==================== Health Timeline ====================
    
    @staticmethod
    def _get_health_snapshots_collection():
        return Database.get_collection("health_snapshots")
    
    @classmethod
    async def save_health_snapshot(
        cls,
        plant_id: str,
        user_id: str,
        health_status: str,
        confidence: float = 0.0,
        issues: list = None,
        immediate_actions: list = None,
        image_key: str = None,
        thumbnail_key: str = None,
        image_url: str = None  # backwards-compat (old field name)
    ) -> dict:
        """Save a health snapshot for a plant."""
        collection = cls._get_health_snapshots_collection()

        snapshot = {
            "plant_id": plant_id,
            "user_id": user_id,
            "health_status": health_status,
            "confidence": confidence,
            "issues": issues or [],
            "immediate_actions": immediate_actions or [],
            "image_key": image_key or image_url,
            "thumbnail_key": thumbnail_key,
            "created_at": datetime.utcnow()
        }

        result = await collection.insert_one(snapshot)
        snapshot["_id"] = result.inserted_id
        
        return snapshot
    
    @classmethod
    async def get_health_timeline(
        cls,
        plant_id: str,
        user_id: str,
        limit: int = 20
    ) -> tuple:
        """Get health timeline for a plant."""
        object_id = cls._validate_object_id(plant_id)
        collection = cls._get_health_snapshots_collection()
        
        # Verify plant belongs to user
        plants_collection = cls._get_plants_collection()
        plant = await plants_collection.find_one({"_id": object_id, "user_id": user_id})
        if not plant:
            raise NotFoundException("Plant not found")
        
        # Get snapshots
        cursor = collection.find({
            "plant_id": plant_id,
            "user_id": user_id
        }).sort("created_at", -1).limit(limit)
        
        snapshots = await cursor.to_list(length=limit)
        total = await collection.count_documents({"plant_id": plant_id, "user_id": user_id})

        return snapshots, total

    @classmethod
    async def _get_latest_health_snapshot(cls, plant_id: str, user_id: str) -> Optional[dict]:
        collection = cls._get_health_snapshots_collection()
        return await collection.find_one(
            {"plant_id": plant_id, "user_id": user_id},
            sort=[("created_at", -1)],
        )

    @classmethod
    def _min_days_between_snapshots(cls) -> int:
        settings = get_settings()
        try:
            return int(settings.PLANT_TIMELINE_MIN_DAYS_BETWEEN_SNAPSHOTS)
        except Exception:
            return 7

    @classmethod
    async def get_next_allowed_snapshot_at(cls, plant_id: str, user_id: str) -> Optional[datetime]:
        """Return when the user can add the next snapshot; None means allowed now."""
        min_days = cls._min_days_between_snapshots()
        if min_days <= 0:
            return None

        latest = await cls._get_latest_health_snapshot(plant_id, user_id)
        if not latest or not latest.get("created_at"):
            return None

        return latest["created_at"] + timedelta(days=min_days)

    @classmethod
    async def create_weekly_health_snapshot(
        cls,
        plant_id: str,
        user_id: str,
        image_key: str,
        city: Optional[str] = None,
    ) -> dict:
        """
        Create a new health snapshot (weekly-gated) from an uploaded image key.
        Also generates and uploads a thumbnail, and updates the plant's latest health fields.
        """
        object_id = cls._validate_object_id(plant_id)
        plants_collection = cls._get_plants_collection()
        plant = await plants_collection.find_one({"_id": object_id, "user_id": user_id})
        if not plant:
            raise NotFoundException("Plant not found")

        # Ensure legacy immediate actions are migrated before we append new ones.
        plant = await cls._ensure_immediate_fixes(plant)

        min_days = cls._min_days_between_snapshots()
        next_allowed_at = await cls.get_next_allowed_snapshot_at(plant_id, user_id)
        if min_days > 0 and next_allowed_at and datetime.utcnow() < next_allowed_at:
            raise BadRequestException("Snapshot already added recently. Please try again later.")

        if not image_key or not isinstance(image_key, str) or not image_key.strip():
            raise BadRequestException("image_key is required")

        s3 = S3Service()
        try:
            base64_full = s3.download_file_as_base64(image_key)
        except Exception as e:
            raise BadRequestException(f"Failed to download uploaded image: {e}")

        # Generate thumbnail for UI
        thumb_base64 = ImageService.create_thumbnail(base64_full, max_size=(384, 384))

        # Use a larger but bounded image for analysis to reduce token/cost
        analysis_base64 = ImageService.create_thumbnail(base64_full, max_size=(1024, 1024))

        # Upload thumbnail to S3
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        thumb_key = f"plants/{user_id}/{plant_id}/thumbs/{timestamp}_{ObjectId()}_thumb.jpg"
        s3.upload_bytes(thumb_key, base64.b64decode(thumb_base64), content_type="image/jpeg")

        # Analyze health (no user-facing analyze action; runs on weekly snapshot)
        from app.plants.openai_service import OpenAIService

        openai_service = OpenAIService()
        analysis = await openai_service.analyze_plant_thumbnail(
            thumbnail_base64=analysis_base64,
            city=city,
        )

        health = analysis.health
        confidence_bucket = cls._confidence_bucket(analysis.confidence, health.confidence)

        # Save snapshot and update plant latest health fields
        snapshot = await cls.save_health_snapshot(
            plant_id=plant_id,
            user_id=user_id,
            health_status=health.status,
            confidence=health.confidence,
            issues=health.issues,
            immediate_actions=health.immediate_actions,
            image_key=image_key,
            thumbnail_key=thumb_key,
        )

        await plants_collection.update_one(
            {"_id": object_id},
            {
                "$set": {
                    "health_status": health.status,
                    "health_confidence": health.confidence,
                    "health_primary_issue": health.primary_issue,
                    "health_severity": health.severity,
                    "confidence_bucket": confidence_bucket,
                    "plant_family": analysis.plant_family or plant.get("plant_family"),
                    "health_issues": health.issues,
                    "health_immediate_actions": health.immediate_actions,
                    "immediate_fixes": cls._merge_immediate_fixes(
                        plant.get("immediate_fixes", []),
                        health.immediate_actions,
                    ),
                    "health_score": cls._compute_health_score(health.status, health.severity),
                    "last_health_check": datetime.utcnow(),
                }
            },
        )

        try:
            from app.plants.events_service import EventService, EventType
            await EventService.log_event(
                user_id=user_id,
                event_type=EventType.PROGRESS_PHOTO,
                plant_id=plant_id,
                metadata={
                    "image_key": image_key,
                    "thumbnail_key": thumb_key,
                    "health_status": health.status,
                },
            )
        except Exception:
            pass

        try:
            from app.plants.events_service import EventService, EventType
            await EventService.log_event(
                user_id=user_id,
                event_type=EventType.HEALTH_CHECK,
                plant_id=plant_id,
                metadata={
                    "health_status": health.status,
                    "issues": health.issues,
                    "primary_issue": health.primary_issue,
                },
            )
        except Exception:
            pass

        snapshot["next_allowed_at"] = await cls.get_next_allowed_snapshot_at(plant_id, user_id)
        snapshot["min_days_between_snapshots"] = min_days
        return snapshot

    @classmethod
    async def delete_health_snapshot(cls, plant_id: str, user_id: str, snapshot_id: str) -> None:
        """Delete a snapshot (and its S3 objects) if it belongs to the user."""
        object_id = cls._validate_object_id(plant_id)
        plants_collection = cls._get_plants_collection()
        plant = await plants_collection.find_one({"_id": object_id, "user_id": user_id})
        if not plant:
            raise NotFoundException("Plant not found")

        if not ObjectId.is_valid(snapshot_id):
            raise BadRequestException("Invalid snapshot ID")

        collection = cls._get_health_snapshots_collection()
        snapshot = await collection.find_one({"_id": ObjectId(snapshot_id), "plant_id": plant_id, "user_id": user_id})
        if not snapshot:
            raise NotFoundException("Snapshot not found")

        # Delete DB record first (so UI stops showing it even if S3 delete fails)
        await collection.delete_one({"_id": snapshot["_id"]})

        # Best-effort S3 cleanup
        s3 = S3Service()
        for key in [snapshot.get("image_key") or snapshot.get("image_url"), snapshot.get("thumbnail_key")]:
            if key and isinstance(key, str) and (key.startswith("plants/") or key.startswith("uploads/")):
                try:
                    s3.delete_object(key)
                except Exception:
                    pass
    
    # ==================== Helpers ====================
    
    @classmethod
    def _doc_to_response(cls, doc: dict) -> PlantResponse:
        """Convert MongoDB document to PlantResponse."""
        # Import here to avoid circular import
        from app.plants.models import CareScheduleStored, WateringSchedule, ImmediateFixItem
        
        # Parse care_schedule if exists
        care_schedule = None
        if doc.get("care_schedule"):
            care_data = doc["care_schedule"]
            watering = care_data.get("watering", {})
            care_schedule = CareScheduleStored(
                watering=WateringSchedule(
                    summer=watering.get("summer", 3),
                    monsoon=watering.get("monsoon", 5),
                    winter=watering.get("winter", 7)
                ),
                light_preference=care_data.get("light_preference", "bright_indirect"),
                humidity=care_data.get("humidity", "medium"),
                fertilizer_frequency=care_data.get("fertilizer_frequency"),
                indian_climate_tips=care_data.get("indian_climate_tips", [])
            )
        
        immediate_fixes = []
        for fix in (doc.get("immediate_fixes") or []):
            if not isinstance(fix, dict):
                continue
            if not fix.get("id") or not fix.get("action") or not fix.get("created_at"):
                continue
            immediate_fixes.append(
                ImmediateFixItem(
                    id=str(fix["id"]),
                    action=str(fix["action"]),
                    is_done=bool(fix.get("is_done", False)),
                    created_at=fix["created_at"],
                    completed_at=fix.get("completed_at"),
                )
            )

        return PlantResponse(
            id=str(doc["_id"]),
            user_id=doc["user_id"],
            plant_id=doc["plant_id"],
            scientific_name=doc["scientific_name"],
            common_name=doc["common_name"],
            nickname=doc.get("nickname") or doc["common_name"],
            image_url=doc.get("image_url"),
            health_status=doc.get("health_status", "unknown"),
            health_confidence=doc.get("health_confidence"),
            health_primary_issue=doc.get("health_primary_issue"),
            health_severity=doc.get("health_severity"),
            confidence_bucket=doc.get("confidence_bucket"),
            plant_family=doc.get("plant_family"),
            health_score=doc.get("health_score"),
            health_issues=doc.get("health_issues", []),
            health_immediate_actions=doc.get("health_immediate_actions", []),
            immediate_fixes=immediate_fixes,
            notes=doc.get("notes"),
            last_watered=doc.get("last_watered"),
            watering_streak=doc.get("watering_streak", 0),
            created_at=doc["created_at"],
            care_schedule=care_schedule,
            reminders_enabled=doc.get("reminders_enabled", True),
            next_water_date=cls.calculate_next_water_date(doc),
            last_health_check=doc.get("last_health_check")
        )
