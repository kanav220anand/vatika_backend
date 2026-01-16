"""Moderation service for Care Club (MOD-001)."""

from datetime import datetime
from typing import Any, Dict, Optional, Tuple, List

from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import BadRequestException, NotFoundException


class ModerationService:
    @staticmethod
    def _reports_collection():
        return Database.get_collection("care_club_reports")

    @staticmethod
    def _actions_collection():
        return Database.get_collection("moderation_actions")

    @staticmethod
    def _posts_collection():
        return Database.get_collection("care_club_posts")

    @staticmethod
    def _comments_collection():
        return Database.get_collection("care_club_comments")

    @staticmethod
    def _validate_object_id(id_str: str) -> ObjectId:
        if not ObjectId.is_valid(id_str):
            raise BadRequestException("Invalid ID")
        return ObjectId(id_str)

    @classmethod
    async def create_report(
        cls,
        reporter_user_id: str,
        target_type: str,
        target_id: str,
        reason: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.utcnow()

        # Ensure target exists and capture a small snapshot for admins.
        snapshot: Dict[str, Any] = {"target_type": target_type, "target_id": target_id}
        if target_type == "post":
            if not ObjectId.is_valid(target_id):
                raise NotFoundException("Post not found")
            post = await cls._posts_collection().find_one({"_id": ObjectId(target_id)})
            if not post:
                raise NotFoundException("Post not found")
            snapshot.update(
                {
                    "author_id": post.get("author_id"),
                    "plant_id": post.get("plant_id"),
                    "title": post.get("title"),
                    "created_at": post.get("created_at"),
                }
            )
        elif target_type == "comment":
            if not ObjectId.is_valid(target_id):
                raise NotFoundException("Comment not found")
            comment = await cls._comments_collection().find_one({"_id": ObjectId(target_id)})
            if not comment:
                raise NotFoundException("Comment not found")
            snapshot.update(
                {
                    "author_id": comment.get("author_id"),
                    "post_id": comment.get("post_id"),
                    "body": comment.get("body"),
                    "created_at": comment.get("created_at"),
                }
            )
        else:
            raise BadRequestException("Invalid target_type")

        # Dedupe: same reporter can't report same target twice.
        existing = await cls._reports_collection().find_one(
            {"reporter_user_id": reporter_user_id, "target_type": target_type, "target_id": target_id}
        )
        if existing:
            existing["id"] = str(existing.pop("_id"))
            return existing

        report_doc = {
            "reporter_user_id": reporter_user_id,
            "target_type": target_type,
            "target_id": target_id,
            "reason": reason,
            "notes": notes,
            "status": "open",
            "created_at": now,
            "resolved_at": None,
            "resolved_action": None,
            "resolved_note": None,
            "snapshot": snapshot,
        }

        # Insert report first (unique index enforces dedupe under race conditions).
        result = await cls._reports_collection().insert_one(report_doc)
        report_doc["_id"] = result.inserted_id

        # Auto-hide the target immediately.
        if target_type == "post":
            await cls._posts_collection().update_one({"_id": ObjectId(target_id)}, {"$set": {"moderation_status": "hidden"}})
        else:
            await cls._comments_collection().update_one({"_id": ObjectId(target_id)}, {"$set": {"moderation_status": "hidden"}})

        report_doc["id"] = str(report_doc.pop("_id"))
        return report_doc

    @classmethod
    async def list_reports(cls, status: str = "open", limit: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        collection = cls._reports_collection()
        query = {"status": status} if status else {}
        total = await collection.count_documents(query)
        cursor = collection.find(query).sort("created_at", -1).limit(limit)

        items: List[Dict[str, Any]] = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            items.append(doc)

        return items, total

    @classmethod
    async def get_report(cls, report_id: str) -> Dict[str, Any]:
        collection = cls._reports_collection()
        oid = cls._validate_object_id(report_id)
        doc = await collection.find_one({"_id": oid})
        if not doc:
            raise NotFoundException("Report not found")
        doc["id"] = str(doc.pop("_id"))
        return doc

    @classmethod
    async def resolve_report(
        cls,
        report_id: str,
        action: str,
        admin_user_id: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        action_norm = (action or "").strip().lower()
        if action_norm not in {"restore", "remove"}:
            raise BadRequestException("Invalid action")

        report = await cls.get_report(report_id)
        if report.get("status") != "open":
            return report

        target_type = report.get("target_type")
        target_id = report.get("target_id")
        now = datetime.utcnow()

        # Apply target status
        new_status = "active" if action_norm == "restore" else "removed"
        if target_type == "post" and ObjectId.is_valid(target_id):
            await cls._posts_collection().update_one({"_id": ObjectId(target_id)}, {"$set": {"moderation_status": new_status}})
        elif target_type == "comment" and ObjectId.is_valid(target_id):
            await cls._comments_collection().update_one({"_id": ObjectId(target_id)}, {"$set": {"moderation_status": new_status}})

        # Update report
        await cls._reports_collection().update_one(
            {"_id": ObjectId(report_id)},
            {
                "$set": {
                    "status": "resolved",
                    "resolved_at": now,
                    "resolved_action": action_norm,
                    "resolved_note": note,
                }
            },
        )

        # Audit trail (recommended)
        try:
            await cls._actions_collection().insert_one(
                {
                    "admin_user_id": admin_user_id,
                    "action": action_norm,
                    "target_type": target_type,
                    "target_id": target_id,
                    "report_id": report_id,
                    "note": note,
                    "created_at": now,
                }
            )
        except Exception:
            pass

        return await cls.get_report(report_id)

