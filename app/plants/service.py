"""Plant service - handles plant CRUD and knowledge base operations."""

from datetime import datetime, timedelta
from typing import Optional, List
from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import NotFoundException, BadRequestException
from app.plants.models import (
    PlantCreate,
    PlantResponse,
    PlantAnalysisResponse,
    CareSchedule,
)


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
        else:
            # If never watered, due now
            return datetime.utcnow()
    
    # ==================== User Plants CRUD ====================
    
    @classmethod
    async def create_plant(cls, user_id: str, plant_data: PlantCreate) -> PlantResponse:
        """Save a plant to user's collection."""
        collection = cls._get_plants_collection()
        
        plant_doc = {
            "user_id": user_id,
            "plant_id": plant_data.plant_id,
            "scientific_name": plant_data.scientific_name,
            "common_name": plant_data.common_name,
            "nickname": plant_data.nickname or plant_data.common_name,
            "image_url": plant_data.image_url,
            "health_status": plant_data.health_status,
            "notes": plant_data.notes,
            "last_watered": None,
            "watering_streak": 0,
            "created_at": datetime.utcnow(),
            # Care reminder fields
            "care_schedule": plant_data.care_schedule.dict() if plant_data.care_schedule else None,
            "reminders_enabled": plant_data.reminders_enabled,
            "last_health_check": datetime.utcnow(),
        }
        
        result = await collection.insert_one(plant_doc)
        plant_doc["_id"] = result.inserted_id
        
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

    
    @classmethod
    async def get_user_plants(cls, user_id: str, skip: int = 0, limit: int = 50) -> List[PlantResponse]:
        """Get plants for a user with pagination."""
        collection = cls._get_plants_collection()
        cursor = collection.find({"user_id": user_id}).sort("created_at", -1).skip(skip).limit(limit)
        plants = await cursor.to_list(length=limit)
        return [cls._doc_to_response(p) for p in plants]
    
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
        image_url: str = None
    ) -> dict:
        """Save a health snapshot for a plant."""
        collection = cls._get_health_snapshots_collection()
        
        snapshot = {
            "plant_id": plant_id,
            "user_id": user_id,
            "health_status": health_status,
            "confidence": confidence,
            "issues": issues or [],
            "image_url": image_url,
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
    
    # ==================== Helpers ====================
    
    @classmethod
    def _doc_to_response(cls, doc: dict) -> PlantResponse:
        """Convert MongoDB document to PlantResponse."""
        # Import here to avoid circular import
        from app.plants.models import CareScheduleStored, WateringSchedule
        
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
                indian_climate_tips=care_data.get("indian_climate_tips", [])
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
            notes=doc.get("notes"),
            last_watered=doc.get("last_watered"),
            watering_streak=doc.get("watering_streak", 0),
            created_at=doc["created_at"],
            care_schedule=care_schedule,
            reminders_enabled=doc.get("reminders_enabled", True),
            next_water_date=cls.calculate_next_water_date(doc),
            last_health_check=doc.get("last_health_check")
        )

