"""Plant service - handles plant CRUD and knowledge base operations."""

import base64
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import uuid4
from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.config import get_settings
from app.core.s3_keys import normalize_s3_key
from app.plants.models import (
    PlantCreate,
    PlantResponse,
    PlantAnalysisResponse,
    CareSchedule,
    SoilAssessment,
)
from app.plants.care_utils import convert_care_schedule_to_stored
from app.plants.video_service import ImageService
from app.core.aws import S3Service
from app.ai.security import validate_user_owned_s3_key


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
    def get_season_for_date(dt: datetime) -> str:
        """
        Return season based on Indian climate for a given anchor date.

        Why this exists (GAME-001 fix):
        - We must anchor watering intervals to the month of the *anchor* (last_watered/created_at),
          not "now", otherwise due dates shift when seasons change.
        """
        month = (dt or datetime.utcnow()).month
        if month in [3, 4, 5]:  # Mar-May: Summer
            return "summer"
        if month in [6, 7, 8, 9]:  # Jun-Sept: Monsoon
            return "monsoon"
        return "winter"  # Oct-Feb: Winter

    @classmethod
    def get_current_season(cls) -> str:
        """Return current season (kept for backward compatibility)."""
        return cls.get_season_for_date(datetime.utcnow())
    
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
        
        created_at = plant_doc.get("created_at")

        # Anchor season to the baseline date so intervals remain stable across season changes.
        # Example:
        # - last_watered = May 30 (summer) and interval = 3 days -> next = Jun 2 (still uses summer interval)
        #   even if "now" is in monsoon months.
        anchor = last_watered or created_at or datetime.utcnow()
        season = cls.get_season_for_date(anchor)
        days = watering.get(season, 3)  # Default 3 days

        if last_watered:
            return last_watered + timedelta(days=days)
        # If never watered, default to created_at baseline (prevents immediate "overdue" on new plants).
        created_at = created_at or datetime.utcnow()
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

        # Store only S3 keys for user uploads. If a full S3 URL/presigned URL is sent,
        # normalize it back to a key so it can be re-signed at response time.
        normalized_image_value: Optional[str] = None
        if plant_data.image_url:
            settings = get_settings()
            maybe_key = normalize_s3_key(
                plant_data.image_url,
                bucket=settings.AWS_S3_BUCKET,
                region=settings.AWS_REGION,
            )
            if maybe_key:
                normalized_image_value = validate_user_owned_s3_key(user_id, maybe_key)
            else:
                # Allow external image URLs for non-uploaded images.
                normalized_image_value = plant_data.image_url.strip()

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
        
        last_watered_source = (plant_data.last_watered_source or "").strip() or None
        if plant_data.last_watered is None:
            last_watered_source = "unknown"
        elif last_watered_source is None:
            # Older clients may send a timestamp without a source; treat as exact.
            last_watered_source = "user_exact"
        else:
            allowed_sources = {"user_exact", "user_estimate", "unknown"}
            if last_watered_source not in allowed_sources:
                last_watered_source = "unknown" if plant_data.last_watered is None else "user_exact"

        plant_doc = {
            "user_id": user_id,
            "plant_id": plant_data.plant_id,
            "scientific_name": plant_data.scientific_name,
            "common_name": plant_data.common_name,
            "nickname": plant_data.nickname or plant_data.common_name,
            "image_url": normalized_image_value,
            "health_status": plant_data.health_status,
            "notes": plant_data.notes,
            "last_watered": plant_data.last_watered,
            "last_watered_source": last_watered_source,
            "watering_streak": 0,
            "created_at": datetime.utcnow(),
            # Care reminder fields
            "care_schedule": care_schedule_doc,
            "reminders_enabled": plant_data.reminders_enabled,
            "last_health_check": datetime.utcnow(),
        }

        # Persist latest analysis metadata if provided
        if plant_data.toxicity:
            plant_doc["toxicity"] = plant_data.toxicity.model_dump()
        if plant_data.placement:
            plant_doc["placement"] = plant_data.placement.model_dump()
        if (
            plant_data.health
            or plant_data.care
            or plant_data.confidence is not None
            or plant_data.plant_family
            or plant_data.toxicity
            or plant_data.placement
        ):
            plant_doc["last_analysis_at"] = plant_data.last_analysis_at or datetime.utcnow()

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

        # ANALYSIS-002: Create an initial snapshot for the plant's cover image (append-only timeline).
        if normalized_image_value and (normalized_image_value.startswith("plants/") or normalized_image_value.startswith("uploads/")):
            try:
                from app.plants.soil_logic import compute_soil_hint

                analysis_doc = {
                    "plant_id": plant_data.plant_id,
                    "scientific_name": plant_data.scientific_name,
                    "common_name": plant_data.common_name,
                    "plant_family": plant_data.plant_family,
                    "confidence": plant_data.confidence,
                    "health": plant_data.health.model_dump(exclude_none=True) if plant_data.health else None,
                    "care": plant_data.care.model_dump(exclude_none=True) if plant_data.care else None,
                    "toxicity": plant_data.toxicity.model_dump(exclude_none=True) if plant_data.toxicity else None,
                    "placement": plant_data.placement.model_dump(exclude_none=True) if plant_data.placement else None,
                }
                # Keep analysis payload compact and avoid storing nulls.
                analysis_doc = {k: v for k, v in analysis_doc.items() if v is not None}

                soil_hint = compute_soil_hint(plant_data.soil) if plant_data.soil else None

                snapshot = await cls.save_health_snapshot(
                    plant_id=str(result.inserted_id),
                    user_id=user_id,
                    health_status=(plant_data.health.status if plant_data.health else plant_doc.get("health_status", "unknown")),
                    confidence=(plant_data.health.confidence if plant_data.health else float(plant_doc.get("health_confidence") or 0.0)),
                    issues=(plant_data.health.issues if plant_data.health else plant_doc.get("health_issues") or []),
                    immediate_actions=(plant_data.health.immediate_actions if plant_data.health else plant_doc.get("health_immediate_actions") or []),
                    image_url=normalized_image_value,
                    snapshot_type="initial",
                    analysis=analysis_doc,
                    soil=plant_data.soil,
                    soil_hint=soil_hint.model_dump(exclude_none=True) if soil_hint else None,
                )

                # Keep a pointer to the initial snapshot for fast access.
                plant_doc["initial_snapshot_id"] = str(snapshot["_id"])
                await collection.update_one(
                    {"_id": result.inserted_id, "user_id": user_id},
                    {"$set": {"initial_snapshot_id": str(snapshot["_id"])}},
                )
            except Exception:
                # Never fail plant creation due to timeline snapshot issues.
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
        plants = await cls._attach_last_event_at(user_id, plants)
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
    async def _attach_last_event_at(cls, user_id: str, plant_docs: List[dict]) -> List[dict]:
        """
        Attach `last_event_at` onto each plant doc using a single aggregation over `events`.

        Falls back to plant.created_at if no events exist (e.g., older data).
        """
        if not plant_docs:
            return plant_docs

        plant_ids = [str(p.get("_id")) for p in plant_docs if p.get("_id")]
        if not plant_ids:
            return plant_docs

        events = Database.get_collection("events")
        pipeline = [
            {"$match": {"user_id": user_id, "plant_id": {"$in": plant_ids}}},
            {"$sort": {"created_at": -1}},
            {"$group": {"_id": "$plant_id", "created_at": {"$first": "$created_at"}}},
        ]

        last_event_by_plant = {}
        async for row in events.aggregate(pipeline):
            if row and row.get("_id") and row.get("created_at"):
                last_event_by_plant[str(row["_id"])] = row["created_at"]

        for p in plant_docs:
            pid = str(p.get("_id")) if p.get("_id") else None
            p["last_event_at"] = last_event_by_plant.get(pid) or p.get("created_at")

        return plant_docs
    
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
        try:
            prompt = await cls._build_progress_prompt(plant_id, user_id, plant)
            if prompt:
                plant["progress_prompt"] = prompt
        except Exception:
            # Best-effort: never fail plant fetch due to prompt logic.
            plant["progress_prompt"] = None
        return cls._doc_to_response(plant)
    
    @classmethod
    async def update_plant(cls, plant_id: str, user_id: str, updates: dict) -> PlantResponse:
        """Update a plant."""
        object_id = cls._validate_object_id(plant_id)
        collection = cls._get_plants_collection()
        
        # Remove None values
        updates = {k: v for k, v in updates.items() if v is not None}

        # Normalize S3 URLs/presigned URLs into keys for storage.
        if isinstance(updates.get("image_url"), str) and updates.get("image_url"):
            settings = get_settings()
            raw = updates["image_url"].strip()
            maybe_key = normalize_s3_key(raw, bucket=settings.AWS_S3_BUCKET, region=settings.AWS_REGION)
            if maybe_key:
                updates["image_url"] = validate_user_owned_s3_key(user_id, maybe_key)
            else:
                updates["image_url"] = raw
        
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
        """Mark a plant as watered, update schedule-aware streak, and log an enriched event."""
        object_id = cls._validate_object_id(plant_id)
        collection = cls._get_plants_collection()
        
        # Get current plant (owner-only)
        plant = await collection.find_one({"_id": object_id, "user_id": user_id})
        if not plant:
            raise NotFoundException("Plant not found")
        
        settings = get_settings()
        now = datetime.utcnow()

        streak_before = int(plant.get("watering_streak") or 0)

        # Capture schedule context BEFORE update (for event narrative).
        # IMPORTANT: If last_watered is missing, do not classify timing (baseline watering).
        had_history = bool(plant.get("last_watered"))
        next_before = cls.calculate_next_water_date(plant)
        recommended_at: Optional[datetime] = next_before if had_history else None

        timing: Optional[str] = None
        delta_days: Optional[int] = None

        if had_history and recommended_at:
            # Calendar-day delta avoids off-by-one due to floor(seconds/86400).
            # Example: recommended=Jan 10, now=Jan 20 => delta_days=10 (not 9/11 depending on time-of-day).
            delta_days = (now.date() - recommended_at.date()).days

            if delta_days < -int(settings.WATERING_GRACE_DAYS_EARLY):
                timing = "early"
            elif delta_days > int(settings.WATERING_GRACE_DAYS_LATE):
                timing = "late"
            else:
                timing = "on_time"

            # Apply safe streak rule (prevents overwatering to game streaks)
            if timing == "on_time":
                streak_after = streak_before + 1
            elif timing == "late":
                streak_after = 0
            else:
                streak_after = streak_before
        else:
            # Baseline watering: no reward/punish since we don't know prior schedule adherence.
            # Example: new plant (last_watered=None) -> timing=None, delta_days=None, streak unchanged.
            timing = None
            delta_days = None
            streak_after = streak_before
        
        update_fields = {"last_watered": now, "watering_streak": streak_after}
        if not plant.get("last_watered"):
            update_fields["last_watered_source"] = "user_exact"

        result = await collection.find_one_and_update(
            {"_id": object_id, "user_id": user_id},
            {"$set": update_fields},
            return_document=True
        )

        # Gamification: Add score for watering (2 pts, daily cap handled by frontend)
        if result:
            try:
                from app.auth.service import AuthService
                await AuthService.add_score(user_id, 2)
                
                # Weekly streak bonus (20 pts)
                if streak_after > 0 and streak_after % 7 == 0:
                   await AuthService.add_score(user_id, 20)
                # Monthly streak bonus (75 pts) 
                if streak_after > 0 and streak_after % 30 == 0:
                   await AuthService.add_score(user_id, 75)
            except Exception:
                pass
            
            # Stats: canonical watering counters for achievements integrity
            try:
                from app.achievements.service import AchievementService
                await AchievementService.increment_watering_stats(user_id, timing)
            except Exception:
                pass

            # Check and unlock any earned achievements
            try:
                from app.achievements.service import AchievementService
                await AchievementService.check_and_unlock_achievements(user_id)
            except Exception:
                pass  # Don't fail watering if achievement check fails

            try:
                from app.plants.events_service import EventService

                # Compute schedule context AFTER update.
                next_after = cls.calculate_next_water_date({**plant, "last_watered": now})
                await EventService.log_watering_event(
                    user_id=user_id,
                    plant_id=plant_id,
                    occurred_at=now,
                    recommended_at=recommended_at,
                    timing=timing,
                    delta_days=delta_days,
                    streak_before=streak_before,
                    streak_after=streak_after,
                    next_water_date_before=next_before,
                    next_water_date_after=next_after,
                    metadata={"source": "user"},
                )
            except Exception:
                pass

            # Update Today's plan (mark task completed) if it exists.
            try:
                from app.plants.today_service import TodayPlanService
                await TodayPlanService.mark_task_completed(user_id, plant_id, "water")
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
        image_url: str = None,  # backwards-compat (old field name)
        snapshot_type: str = "progress",
        analysis: Optional[dict] = None,
        soil: Optional[SoilAssessment] = None,
        soil_hint: Optional[dict] = None,
    ) -> dict:
        """Save a health snapshot for a plant."""
        collection = cls._get_health_snapshots_collection()

        created_at = datetime.utcnow()
        snapshot_type = (snapshot_type or "").strip().lower() or "progress"
        if snapshot_type not in {"initial", "progress"}:
            snapshot_type = "progress"

        # Enforce one initial snapshot per plant (code guard; avoids failures).
        if snapshot_type == "initial":
            try:
                existing = await collection.find_one(
                    {"plant_id": plant_id, "user_id": user_id, "snapshot_type": "initial"},
                    projection={"_id": 1},
                )
                if existing:
                    snapshot_type = "progress"
            except Exception:
                snapshot_type = "progress"

        # Normalize keys (older callers may pass full S3 URLs / presigned URLs).
        settings = get_settings()

        normalized_image_key = None
        if image_key or image_url:
            candidate = (image_key or image_url or "").strip()
            maybe_key = normalize_s3_key(candidate, bucket=settings.AWS_S3_BUCKET, region=settings.AWS_REGION)
            if maybe_key:
                normalized_image_key = validate_user_owned_s3_key(
                    user_id,
                    maybe_key,
                    allowed_prefixes=[f"plants/{user_id}/", f"uploads/{user_id}/"],
                )
            else:
                normalized_image_key = candidate or None

        normalized_thumbnail_key = None
        if thumbnail_key:
            candidate = str(thumbnail_key).strip()
            maybe_key = normalize_s3_key(candidate, bucket=settings.AWS_S3_BUCKET, region=settings.AWS_REGION)
            if maybe_key:
                normalized_thumbnail_key = validate_user_owned_s3_key(
                    user_id,
                    maybe_key,
                    allowed_prefixes=[f"plants/{user_id}/", f"uploads/{user_id}/"],
                )
            else:
                normalized_thumbnail_key = candidate or None

        snapshot = {
            "plant_id": plant_id,
            "user_id": user_id,
            "snapshot_type": snapshot_type,
            "health_status": health_status,
            "confidence": confidence,
            "issues": issues or [],
            "immediate_actions": immediate_actions or [],
            "image_key": normalized_image_key,
            "thumbnail_key": normalized_thumbnail_key,
            "created_at": created_at,
        }

        if isinstance(analysis, dict) and analysis:
            snapshot["analysis"] = analysis

        if soil is not None:
            try:
                soil_doc = soil.model_dump(exclude_none=True)
            except Exception:
                soil_doc = None
            if isinstance(soil_doc, dict):
                soil_doc["observed_at"] = created_at
                snapshot["soil"] = soil_doc

        if isinstance(soil_hint, dict) and soil_hint:
            snapshot["soil_hint"] = soil_hint

        result = await collection.insert_one(snapshot)
        snapshot["_id"] = result.inserted_id

        # Update lightweight latest soil_state cache on plant (best-effort).
        if "soil" in snapshot and isinstance(snapshot.get("soil"), dict):
            try:
                from app.core.config import get_settings

                threshold = float(getattr(get_settings(), "SOIL_CONFIDENCE_THRESHOLD", 0.6))
                soil_doc = snapshot["soil"]
                if bool(soil_doc.get("visible")) and float(soil_doc.get("confidence") or 0.0) >= threshold:
                    # Properly extract enum value (handle both enum objects and string representations)
                    dryness_raw = soil_doc.get("dryness") or "unknown"
                    if hasattr(dryness_raw, "value"):
                        dryness = dryness_raw.value
                    elif isinstance(dryness_raw, str) and "." in dryness_raw:
                        # Handle "SoilDryness.DRY" -> "dry"
                        dryness = dryness_raw.split(".")[-1].lower()
                    else:
                        dryness = str(dryness_raw)
                    soil_state_doc = {
                        "visible": True,
                        "confidence": float(soil_doc.get("confidence") or 0.0),
                        "dryness": dryness,
                        "observed_at": created_at,
                    }
                    if ObjectId.is_valid(plant_id):
                        await cls._get_plants_collection().update_one(
                            {"_id": ObjectId(plant_id), "user_id": user_id},
                            {"$set": {"soil_state": soil_state_doc}},
                        )
            except Exception:
                pass
        
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
        image_key: Optional[str] = None,
        city: Optional[str] = None,
        image_base64: Optional[str] = None,
        thumbnail_base64: Optional[str] = None,
        note: Optional[str] = None,
    ) -> dict:
        """
        Create a new health snapshot (weekly-gated) from an uploaded image key or base64 data.
        If image_base64 is provided, skips S3 download for faster processing.
        If thumbnail_base64 is provided, skips thumbnail generation.
        Runs thumbnail upload and OpenAI analysis in parallel for speed.
        Optionally saves a note alongside the snapshot as a journal entry.
        """
        import asyncio

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

        # Validate: need either image_key or image_base64
        if not image_base64 and (not image_key or not isinstance(image_key, str) or not image_key.strip()):
            raise BadRequestException("Either image_key or image_base64 is required")

        s3 = S3Service()

        # If base64 provided by client, use it directly (skip S3 download)
        if image_base64:
            # Client already prepared the analysis image
            analysis_base64 = image_base64
            # Use provided thumbnail or generate from analysis image
            if thumbnail_base64:
                thumb_base64 = thumbnail_base64
            else:
                thumb_base64 = ImageService.create_thumbnail(analysis_base64, max_size=(384, 384))
        else:
            # Legacy flow: download from S3
            try:
                base64_full = s3.download_file_as_base64(image_key)
            except Exception as e:
                raise BadRequestException(f"Failed to download uploaded image: {e}")

            # Generate thumbnail for UI
            thumb_base64 = ImageService.create_thumbnail(base64_full, max_size=(384, 384))

            # Use a larger but bounded image for analysis to reduce token/cost
            analysis_base64 = ImageService.create_thumbnail(base64_full, max_size=(1024, 1024))

        # Prepare thumbnail key
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        thumb_key = f"plants/{user_id}/{plant_id}/thumbs/{timestamp}_{ObjectId()}_thumb.jpg"

        # Run thumbnail upload and OpenAI analysis in parallel for speed
        from app.plants.openai_service import OpenAIService

        openai_service = OpenAIService()

        async def upload_thumbnail():
            """Upload thumbnail to S3 (run in executor since it's sync)."""
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: s3.upload_bytes(thumb_key, base64.b64decode(thumb_base64), content_type="image/jpeg")
            )

        async def analyze_health():
            """Run OpenAI health analysis."""
            return await openai_service.analyze_plant_thumbnail(
                thumbnail_base64=analysis_base64,
                city=city,
            )

        # Run both operations in parallel
        _, analysis = await asyncio.gather(
            upload_thumbnail(),
            analyze_health(),
        )

        health = analysis.health
        confidence_bucket = cls._confidence_bucket(analysis.confidence, health.confidence)

        # Save snapshot and update plant latest health fields
        from app.plants.soil_logic import compute_soil_hint

        analysis_doc = analysis.model_dump(exclude_none=True)
        analysis_doc.pop("soil", None)
        soil = analysis.soil
        soil_hint = compute_soil_hint(soil) if soil else None

        snapshot = await cls.save_health_snapshot(
            plant_id=plant_id,
            user_id=user_id,
            health_status=health.status,
            confidence=health.confidence,
            issues=health.issues,
            immediate_actions=health.immediate_actions,
            image_key=image_key,
            thumbnail_key=thumb_key,
            snapshot_type="progress",
            analysis=analysis_doc,
            soil=soil,
            soil_hint=soil_hint.model_dump(exclude_none=True) if soil_hint else None,
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

        # Create journal entry if note provided
        if note and note.strip():
            try:
                from app.plants.journal_service import JournalService
                from app.plants.models import JournalEntryCreate, JournalEntryType
                await JournalService.create_entry(
                    plant_id=plant_id,
                    user_id=user_id,
                    entry=JournalEntryCreate(
                        entry_type=JournalEntryType.NOTE,
                        content=note.strip(),
                        image_key=image_key,
                    ),
                )
            except Exception:
                pass  # Best effort

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
    async def _build_progress_prompt(cls, plant_id: str, user_id: str, plant_doc: dict) -> Optional[dict]:
        """Build the progress/check-in prompt for Plant Detail (backend-driven)."""
        now = datetime.utcnow()
        created_at = plant_doc.get("created_at") or now

        latest = await cls._get_latest_health_snapshot(plant_id, user_id)
        last_snapshot_at = latest.get("created_at") if latest else None

        min_days = cls._min_days_between_snapshots()
        base_threshold = max(min_days, 7)
        attention_threshold = max(min_days, 3)

        def build_prompt(title: str, subtitle: str) -> dict:
            return {
                "title": title,
                "subtitle": subtitle,
                "icon": "camera-outline",
                "cta_label": "Add photo",
                "cta_action": "add_progress_photo",
                "cta_enabled": True,
            }

        # No snapshot yet.
        if not last_snapshot_at:
            days_since_created = (now.date() - created_at.date()).days
            title = "Start your timeline" if days_since_created <= 7 else "Add your first photo"
            subtitle = "Add a progress photo to track changes."
            return build_prompt(title, subtitle)

        # Time since last snapshot.
        days_since_snapshot = (now.date() - last_snapshot_at.date()).days
        if days_since_snapshot < 0:
            return None

        health_status = (plant_doc.get("health_status") or "").lower()
        needs_attention = health_status in {"stressed", "needs_attention", "unhealthy", "critical"}

        if needs_attention and days_since_snapshot >= attention_threshold:
            return build_prompt("Check-in", "Add a photo to see if recovery is improving.")

        if days_since_snapshot >= base_threshold:
            return build_prompt("Weekly check-in", "Snap a progress photo to track growth.")

        return None
    
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
            last_watered_source=doc.get("last_watered_source") or ("unknown" if not doc.get("last_watered") else "user_exact"),
            watering_streak=doc.get("watering_streak", 0),
            created_at=doc["created_at"],
            care_schedule=care_schedule,
            reminders_enabled=doc.get("reminders_enabled", True),
            next_water_date=cls.calculate_next_water_date(doc),
            last_health_check=doc.get("last_health_check"),
            last_event_at=doc.get("last_event_at"),
            toxicity=doc.get("toxicity"),
            placement=doc.get("placement"),
            soil_state=cls._normalize_soil_state(doc.get("soil_state")),
            initial_snapshot_id=doc.get("initial_snapshot_id"),
            last_analysis_at=doc.get("last_analysis_at"),
            progress_prompt=doc.get("progress_prompt"),
        )

    @classmethod
    def _normalize_soil_state(cls, soil_state: Optional[dict]) -> Optional[dict]:
        """Normalize soil_state dict to ensure enum values are proper strings."""
        if not soil_state or not isinstance(soil_state, dict):
            return soil_state
        
        result = dict(soil_state)
        dryness = result.get("dryness")
        if dryness:
            # Handle enum objects
            if hasattr(dryness, "value"):
                result["dryness"] = dryness.value
            # Handle "SoilDryness.DRY" -> "dry"
            elif isinstance(dryness, str) and "." in dryness:
                result["dryness"] = dryness.split(".")[-1].lower()
        return result
