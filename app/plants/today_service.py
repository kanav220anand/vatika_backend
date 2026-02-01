"""Daily Today plan service (backend-driven UI payload)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from zoneinfo import ZoneInfo

from app.auth.service import AuthService
from app.cities.service import CitiesService
from app.core.database import Database
from app.plants.service import PlantService

try:
    from timezonefinder import TimezoneFinder  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    TimezoneFinder = None


class TodayPlanService:
    """Builds and persists the daily Today plan for a user."""

    @staticmethod
    def _get_collection():
        return Database.get_collection("today_plans")

    @staticmethod
    def _get_tzinfo(tz_name: Optional[str]):
        if not tz_name:
            return timezone.utc
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return timezone.utc

    @classmethod
    async def _resolve_timezone_name(cls, user_id: str) -> Optional[str]:
        city = await AuthService.get_user_city(user_id)
        if not city:
            return None
        city_doc = await CitiesService.get_by_name(city)
        if not city_doc:
            return None

        lat = city_doc.get("lat")
        lng = city_doc.get("lng")
        if lat is not None and lng is not None and TimezoneFinder:
            try:
                tz_name = TimezoneFinder().timezone_at(lat=lat, lng=lng)
                if tz_name:
                    return tz_name
            except Exception:
                pass

        # Fallback: India is single-timezone; use it when city is present but lookup fails.
        return "Asia/Kolkata"

    @classmethod
    def _local_date_str(cls, tz_name: Optional[str]) -> str:
        tz = cls._get_tzinfo(tz_name)
        return datetime.now(tz).date().isoformat()

    @classmethod
    def _local_date(cls, tz_name: Optional[str]) -> datetime.date:
        tz = cls._get_tzinfo(tz_name)
        return datetime.now(tz).date()

    @classmethod
    def _to_local_date(cls, dt: datetime, tz_name: Optional[str]) -> datetime.date:
        tz = cls._get_tzinfo(tz_name)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).date()

    @staticmethod
    def _plural(value: int, unit: str) -> str:
        return f"{value} {unit}" + ("s" if value != 1 else "")

    @classmethod
    def _format_overdue_label(cls, days: int) -> str:
        return f"Overdue by {cls._plural(days, 'day')}"

    @classmethod
    def _format_next_up(cls, days: Optional[int]) -> str:
        if days is None:
            return "No upcoming care tasks"
        if days == 0:
            return "Next up today"
        if days == 1:
            return "Next up tomorrow"
        return f"Next up in {cls._plural(days, 'day')}"

    @classmethod
    async def _fetch_user_plants(cls, user_id: str) -> List[dict]:
        collection = PlantService._get_plants_collection()
        fields = {
            "_id": 1,
            "nickname": 1,
            "common_name": 1,
            "reminders_enabled": 1,
            "care_schedule": 1,
            "created_at": 1,
            "last_watered": 1,
        }
        plants = await collection.find({"user_id": user_id}, fields).to_list(length=None)
        return await PlantService._attach_last_event_at(user_id, plants)

    @classmethod
    def _build_due_tasks(
        cls, plants: List[dict], local_date: datetime.date, tz_name: Optional[str]
    ) -> List[dict]:
        tasks: List[Tuple[Tuple[int, int], dict]] = []
        for plant in plants:
            if plant.get("reminders_enabled") is False:
                continue
            if not plant.get("care_schedule"):
                continue
            next_water = PlantService.calculate_next_water_date(plant)
            if not next_water:
                continue

            next_local = cls._to_local_date(next_water, tz_name)
            diff_days = (next_local - local_date).days
            if diff_days > 0:
                continue

            status = "overdue" if diff_days < 0 else "due"
            label = "Due today" if diff_days == 0 else cls._format_overdue_label(abs(diff_days))

            plant_id = str(plant.get("_id"))
            plant_name = plant.get("nickname") or plant.get("common_name") or "Your plant"

            task = {
                "id": f"water:{plant_id}:{local_date.isoformat()}",
                "type": "water",
                "plant_id": plant_id,
                "plant_name": plant_name,
                "status": status,
                "primary_label": label,
                "cta_label": "Mark watered",
                "icon": "water-outline",
                "completed": False,
                "completed_at": None,
                "action": {
                    "type": "mark_watered",
                    "label": "Mark watered",
                    "plant_id": plant_id,
                    "plant_name": plant_name,
                    "icon": "water-outline",
                },
            }

            # Sort: overdue first, then due today. Larger overdue first.
            sort_key = (0 if status == "overdue" else 1, diff_days)
            tasks.append((sort_key, task))

        tasks.sort(key=lambda item: item[0])
        return [task for _, task in tasks]

    @classmethod
    def _format_subtitle(cls, tasks: List[dict]) -> str:
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("completed"))
        if total == 0:
            return ""
        if completed > 0:
            return f"{completed} of {total} completed"
        return f"{total} task" + ("s" if total != 1 else "")

    @classmethod
    def _pick_focus_plant(cls, plants: List[dict]) -> Optional[dict]:
        if not plants:
            return None
        # Prefer least-recent activity for a gentle check-in.
        def key(p: dict):
            return p.get("last_event_at") or p.get("created_at") or datetime.utcnow()

        return sorted(plants, key=key)[0]

    @classmethod
    def _compute_next_due_days(
        cls, plants: List[dict], local_date: datetime.date, tz_name: Optional[str]
    ) -> Optional[int]:
        next_days: Optional[int] = None
        for plant in plants:
            if plant.get("reminders_enabled") is False or not plant.get("care_schedule"):
                continue
            next_water = PlantService.calculate_next_water_date(plant)
            if not next_water:
                continue
            next_local = cls._to_local_date(next_water, tz_name)
            diff_days = (next_local - local_date).days
            if diff_days <= 0:
                continue
            if next_days is None or diff_days < next_days:
                next_days = diff_days
        return next_days

    @classmethod
    def _empty_state_no_plants(cls) -> dict:
        return {
            "title": "Start your garden",
            "subtitle": "Add your first plant to unlock daily care tasks.",
            "actions": [
                {"type": "open_scan", "label": "Scan a plant", "icon": "scan-outline"},
                {
                    "type": "open_browse",
                    "label": "Browse beginner plants",
                    "icon": "leaf-outline",
                    "payload": {"beginnerOnly": True},
                },
            ],
        }

    @classmethod
    def _empty_state_caught_up(
        cls, plants: List[dict], local_date: datetime.date, tz_name: Optional[str]
    ) -> dict:
        focus = cls._pick_focus_plant(plants)
        next_days = cls._compute_next_due_days(plants, local_date, tz_name)

        actions = []
        if focus:
            actions = [
                {
                    "type": "open_plant",
                    "label": "Quick check-in",
                    "icon": "leaf-outline",
                    "plant_id": str(focus.get("_id")),
                },
                {
                    "type": "open_log",
                    "label": "Add progress photo",
                    "icon": "camera-outline",
                    "plant_id": str(focus.get("_id")),
                    "payload": {"initialAction": "log"},
                },
            ]

        return {
            "title": "All caught up",
            "subtitle": cls._format_next_up(next_days),
            "actions": actions,
        }

    @classmethod
    async def _build_plan_doc(cls, user_id: str, local_date: str, tz_name: Optional[str]) -> dict:
        now = datetime.utcnow()
        plants = await cls._fetch_user_plants(user_id)
        local_day = datetime.fromisoformat(local_date).date()

        if not plants:
            return {
                "user_id": user_id,
                "local_date": local_date,
                "timezone": tz_name,
                "created_at": now,
                "updated_at": now,
                "state": "no_plants",
                "title": "Today",
                "subtitle": "",
                "tasks": [],
                "empty_state": cls._empty_state_no_plants(),
            }

        tasks = cls._build_due_tasks(plants, local_day, tz_name)
        if tasks:
            return {
                "user_id": user_id,
                "local_date": local_date,
                "timezone": tz_name,
                "created_at": now,
                "updated_at": now,
                "state": "tasks",
                "title": "Today",
                "subtitle": cls._format_subtitle(tasks),
                "tasks": tasks,
                "empty_state": None,
            }

        empty_state = cls._empty_state_caught_up(plants, local_day, tz_name)
        return {
            "user_id": user_id,
            "local_date": local_date,
            "timezone": tz_name,
            "created_at": now,
            "updated_at": now,
            "state": "empty",
            "title": "Today",
            "subtitle": empty_state.get("subtitle") or "",
            "tasks": [],
            "empty_state": empty_state,
        }

    @classmethod
    async def _sync_plan(
        cls, plan: dict, user_id: str, local_date: str, tz_name: Optional[str]
    ) -> dict:
        plants = await cls._fetch_user_plants(user_id)
        plant_ids = {str(p.get("_id")) for p in plants}

        tasks = list(plan.get("tasks") or [])
        filtered_tasks = [
            t for t in tasks if not t.get("plant_id") or t.get("plant_id") in plant_ids
        ]
        existing_keys = {(t.get("type"), t.get("plant_id")) for t in filtered_tasks}

        local_day = datetime.fromisoformat(local_date).date()
        due_tasks = cls._build_due_tasks(plants, local_day, tz_name)
        new_tasks = [
            t for t in due_tasks if (t.get("type"), t.get("plant_id")) not in existing_keys
        ]
        if new_tasks:
            filtered_tasks.extend(new_tasks)

        updated = False
        next_state = plan.get("state") or "empty"
        next_empty_state = plan.get("empty_state")
        next_subtitle = plan.get("subtitle") or ""

        if filtered_tasks:
            next_state = "tasks"
            next_empty_state = None
            next_subtitle = cls._format_subtitle(filtered_tasks)
        else:
            if not plants:
                next_state = "no_plants"
                next_empty_state = cls._empty_state_no_plants()
                next_subtitle = ""
            else:
                next_state = "empty"
                next_empty_state = cls._empty_state_caught_up(plants, local_day, tz_name)
                next_subtitle = next_empty_state.get("subtitle") or ""

        if filtered_tasks != tasks or next_state != plan.get("state"):
            updated = True
        if next_empty_state != plan.get("empty_state"):
            updated = True
        if next_subtitle != plan.get("subtitle"):
            updated = True

        if updated:
            plan["tasks"] = filtered_tasks
            plan["state"] = next_state
            plan["empty_state"] = next_empty_state
            plan["subtitle"] = next_subtitle
            plan["updated_at"] = datetime.utcnow()
            await cls._get_collection().update_one(
                {"_id": plan["_id"]},
                {
                    "$set": {
                        "tasks": plan["tasks"],
                        "state": plan["state"],
                        "empty_state": plan["empty_state"],
                        "subtitle": plan["subtitle"],
                        "updated_at": plan["updated_at"],
                    }
                },
            )

        return plan

    @classmethod
    def _to_response(cls, plan: dict) -> dict:
        payload = {k: v for k, v in plan.items() if k not in {"_id", "user_id", "created_at", "updated_at"}}
        return {"today": payload}

    # Public API -----------------------------------------------------

    @classmethod
    async def get_today_plan(cls, user_id: str) -> dict:
        tz_name = await cls._resolve_timezone_name(user_id)
        local_date = cls._local_date_str(tz_name)
        collection = cls._get_collection()

        plan = await collection.find_one({"user_id": user_id, "local_date": local_date})
        if not plan:
            plan = await cls._build_plan_doc(user_id, local_date, tz_name)
            await collection.insert_one(plan)
            return cls._to_response(plan)

        plan = await cls._sync_plan(plan, user_id, local_date, tz_name)
        return cls._to_response(plan)

    @classmethod
    async def mark_task_completed(cls, user_id: str, plant_id: str, task_type: str = "water") -> None:
        tz_name = await cls._resolve_timezone_name(user_id)
        local_date = cls._local_date_str(tz_name)
        collection = cls._get_collection()
        plan = await collection.find_one({"user_id": user_id, "local_date": local_date})
        if not plan:
            return

        tasks = list(plan.get("tasks") or [])
        updated = False
        now = datetime.utcnow()

        for task in tasks:
            if task.get("type") == task_type and task.get("plant_id") == plant_id:
                if not task.get("completed"):
                    task["completed"] = True
                    task["completed_at"] = now
                    updated = True

        if not updated:
            return

        subtitle = cls._format_subtitle(tasks)
        await collection.update_one(
            {"_id": plan["_id"]},
            {"$set": {"tasks": tasks, "subtitle": subtitle, "updated_at": now}},
        )
