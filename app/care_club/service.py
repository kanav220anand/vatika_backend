"""Care Club service layer - Repository pattern for scalable data access."""

from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any
from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import NotFoundException, ForbiddenException, AppException


class CareClubRepository:
    """Repository for Care Club posts."""

    @staticmethod
    def _posts_collection():
        return Database.get_collection("care_club_posts")

    @staticmethod
    def _comments_collection():
        return Database.get_collection("care_club_comments")

    @staticmethod
    def _helpful_votes_collection():
        return Database.get_collection("care_club_helpful_votes")

    @staticmethod
    def _plants_collection():
        return Database.get_collection("plants")

    @staticmethod
    def _users_collection():
        return Database.get_collection("users")

    # ========================================================================
    # Posts
    # ========================================================================

    @classmethod
    async def list_posts(
        cls,
        limit: int = 20,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Tuple[List[dict], int, bool, Optional[str]]:
        """
        List posts with pagination (newest first by created_at).
        
        Returns: (posts, total_count, has_more, next_cursor)
        """
        collection = cls._posts_collection()

        # Build filter
        filter_query: Dict[str, Any] = {}
        if status:
            filter_query["status"] = status

        # Cursor-based pagination using created_at
        if cursor:
            try:
                cursor_time = datetime.fromisoformat(cursor)
                filter_query["created_at"] = {"$lt": cursor_time}
            except ValueError:
                pass  # Invalid cursor, ignore

        # Get total count (without cursor filter for accurate total)
        base_filter = {"status": status} if status else {}
        total = await collection.count_documents(base_filter)

        # Fetch posts
        posts_cursor = collection.find(filter_query).sort("created_at", -1).limit(limit + 1)
        posts = await posts_cursor.to_list(length=limit + 1)

        # Check if there are more
        has_more = len(posts) > limit
        if has_more:
            posts = posts[:limit]

        # Next cursor
        next_cursor = None
        if has_more and posts:
            next_cursor = posts[-1]["created_at"].isoformat()

        # Convert ObjectId to string
        for post in posts:
            post["id"] = str(post.pop("_id"))

        return posts, total, has_more, next_cursor

    @classmethod
    async def get_post(cls, post_id: str) -> dict:
        """Get a single post by ID."""
        if not ObjectId.is_valid(post_id):
            raise NotFoundException("Post not found")

        collection = cls._posts_collection()
        post = await collection.find_one({"_id": ObjectId(post_id)})

        if not post:
            raise NotFoundException("Post not found")

        post["id"] = str(post.pop("_id"))
        return post

    @classmethod
    async def create_post(
        cls,
        author_id: str,
        plant_id: str,
        title: str,
        details: Optional[str] = None,
        tried: Optional[str] = None,
        photo_urls: Optional[List[str]] = None,
    ) -> dict:
        """Create a new post."""
        # Validate plant ownership
        if not ObjectId.is_valid(plant_id):
            raise NotFoundException("Plant not found")

        plant = await cls._plants_collection().find_one({
            "_id": ObjectId(plant_id),
            "user_id": author_id
        })
        if not plant:
            raise ForbiddenException("You can only create posts for your own plants")

        now = datetime.utcnow()
        
        # If no photos provided, use plant's image as default
        final_photo_urls = photo_urls or []
        if not final_photo_urls and plant.get("image_url"):
            # Store the raw key (not a presigned URL). We'll return presigned GET URLs at read-time.
            final_photo_urls = [plant["image_url"]]

        post_doc = {
            "plant_id": plant_id,
            "author_id": author_id,
            "title": title,
            "details": details,
            "tried": tried,
            "photo_urls": final_photo_urls,
            "status": "open",
            "resolved_at": None,
            "resolved_note": None,
            "created_at": now,
            "updated_at": now,
            "last_activity_at": now,
            "aggregates": {
                "comment_count": 0,
                "latest_comment_at": None,
            },
        }

        result = await cls._posts_collection().insert_one(post_doc)
        post_doc["id"] = str(result.inserted_id)
        post_doc.pop("_id", None)

        return post_doc

    @classmethod
    async def resolve_post(
        cls,
        post_id: str,
        user_id: str,
        resolved_note: str,
    ) -> dict:
        """Mark a post as resolved. Only post author can resolve."""
        if not ObjectId.is_valid(post_id):
            raise NotFoundException("Post not found")

        collection = cls._posts_collection()
        post = await collection.find_one({"_id": ObjectId(post_id)})

        if not post:
            raise NotFoundException("Post not found")

        if post["author_id"] != user_id:
            raise ForbiddenException("Only the post author can mark it as resolved")

        if post["status"] == "resolved":
            raise AppException("Post is already resolved")

        now = datetime.utcnow()
        update_result = await collection.update_one(
            {"_id": ObjectId(post_id)},
            {
                "$set": {
                    "status": "resolved",
                    "resolved_at": now,
                    "resolved_note": resolved_note,
                    "updated_at": now,
                    "last_activity_at": now,
                }
            }
        )

        if update_result.modified_count == 0:
            raise AppException("Failed to resolve post")

        # Return updated post
        return await cls.get_post(post_id)

    @classmethod
    async def delete_post(cls, post_id: str, user_id: str) -> bool:
        """Delete a post. Only post author can delete."""
        if not ObjectId.is_valid(post_id):
            raise NotFoundException("Post not found")

        collection = cls._posts_collection()
        post = await collection.find_one({"_id": ObjectId(post_id)})

        if not post:
            raise NotFoundException("Post not found")

        if post["author_id"] != user_id:
            raise ForbiddenException("Only the post author can delete it")

        # Delete all comments and helpful votes for this post
        await cls._comments_collection().delete_many({"post_id": post_id})
        await cls._helpful_votes_collection().delete_many({"post_id": post_id})

        # Delete the post
        await collection.delete_one({"_id": ObjectId(post_id)})

        return True


class CommentsRepository:
    """Repository for Care Club comments."""

    @staticmethod
    def _posts_collection():
        return Database.get_collection("care_club_posts")

    @staticmethod
    def _comments_collection():
        return Database.get_collection("care_club_comments")

    @staticmethod
    def _helpful_votes_collection():
        return Database.get_collection("care_club_helpful_votes")

    @classmethod
    async def list_comments(
        cls,
        post_id: str,
        user_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[dict], int, bool, Optional[str]]:
        """
        List comments for a post (oldest first).
        
        Returns: (comments, total_count, has_more, next_cursor)
        """
        if not ObjectId.is_valid(post_id):
            raise NotFoundException("Post not found")

        collection = cls._comments_collection()

        # Build filter
        filter_query: Dict[str, Any] = {"post_id": post_id}

        # Cursor-based pagination
        if cursor:
            try:
                cursor_time = datetime.fromisoformat(cursor)
                filter_query["created_at"] = {"$gt": cursor_time}
            except ValueError:
                pass

        # Get total count
        total = await collection.count_documents({"post_id": post_id})

        # Fetch comments (oldest first)
        comments_cursor = collection.find(filter_query).sort("created_at", 1).limit(limit + 1)
        comments = await comments_cursor.to_list(length=limit + 1)

        has_more = len(comments) > limit
        if has_more:
            comments = comments[:limit]

        next_cursor = None
        if has_more and comments:
            next_cursor = comments[-1]["created_at"].isoformat()

        # Get user's helpful votes for these comments
        comment_ids = [str(c["_id"]) for c in comments]
        user_votes = set()
        if comment_ids:
            votes_cursor = cls._helpful_votes_collection().find({
                "comment_id": {"$in": comment_ids},
                "user_id": user_id
            })
            async for vote in votes_cursor:
                user_votes.add(vote["comment_id"])

        # Format comments
        for comment in comments:
            comment["id"] = str(comment.pop("_id"))
            comment["user_voted_helpful"] = comment["id"] in user_votes

        return comments, total, has_more, next_cursor

    @classmethod
    async def add_comment(
        cls,
        post_id: str,
        author_id: str,
        body: str,
        photo_urls: Optional[List[str]] = None,
    ) -> dict:
        """Add a comment to a post."""
        if not ObjectId.is_valid(post_id):
            raise NotFoundException("Post not found")

        # Verify post exists
        post = await cls._posts_collection().find_one({"_id": ObjectId(post_id)})
        if not post:
            raise NotFoundException("Post not found")

        now = datetime.utcnow()

        comment_doc = {
            "post_id": post_id,
            "author_id": author_id,
            "body": body,
            "photo_urls": photo_urls or [],
            "created_at": now,
            "aggregates": {
                "helpful_count": 0,
            },
        }

        # Insert comment
        result = await cls._comments_collection().insert_one(comment_doc)
        comment_doc["id"] = str(result.inserted_id)
        comment_doc.pop("_id", None)

        # Update post aggregates atomically
        await cls._posts_collection().update_one(
            {"_id": ObjectId(post_id)},
            {
                "$inc": {"aggregates.comment_count": 1},
                "$set": {
                    "aggregates.latest_comment_at": now,
                    "last_activity_at": now,
                    "updated_at": now,
                },
            }
        )

        comment_doc["user_voted_helpful"] = False
        return comment_doc

    @classmethod
    async def delete_comment(cls, comment_id: str, user_id: str) -> bool:
        """Delete a comment. Only comment author can delete."""
        if not ObjectId.is_valid(comment_id):
            raise NotFoundException("Comment not found")

        collection = cls._comments_collection()
        comment = await collection.find_one({"_id": ObjectId(comment_id)})

        if not comment:
            raise NotFoundException("Comment not found")

        if comment["author_id"] != user_id:
            raise ForbiddenException("Only the comment author can delete it")

        post_id = comment["post_id"]

        # Delete helpful votes for this comment
        await cls._helpful_votes_collection().delete_many({"comment_id": comment_id})

        # Delete the comment
        await collection.delete_one({"_id": ObjectId(comment_id)})

        # Update post aggregates
        await cls._posts_collection().update_one(
            {"_id": ObjectId(post_id)},
            {
                "$inc": {"aggregates.comment_count": -1},
                "$set": {"updated_at": datetime.utcnow()},
            }
        )

        return True

    @classmethod
    async def toggle_helpful(
        cls,
        post_id: str,
        comment_id: str,
        user_id: str,
    ) -> Tuple[bool, int]:
        """
        Toggle helpful vote on a comment.
        
        Returns: (voted: bool, new_count: int)
        """
        if not ObjectId.is_valid(comment_id):
            raise NotFoundException("Comment not found")

        comments_collection = cls._comments_collection()
        votes_collection = cls._helpful_votes_collection()

        # Verify comment exists
        comment = await comments_collection.find_one({"_id": ObjectId(comment_id)})
        if not comment:
            raise NotFoundException("Comment not found")

        if comment["post_id"] != post_id:
            raise AppException("Comment does not belong to this post")

        # Check if user already voted
        existing_vote = await votes_collection.find_one({
            "comment_id": comment_id,
            "user_id": user_id,
        })

        if existing_vote:
            # Remove vote
            await votes_collection.delete_one({"_id": existing_vote["_id"]})
            await comments_collection.update_one(
                {"_id": ObjectId(comment_id)},
                {"$inc": {"aggregates.helpful_count": -1}}
            )
            voted = False
        else:
            # Add vote
            await votes_collection.insert_one({
                "post_id": post_id,
                "comment_id": comment_id,
                "user_id": user_id,
                "created_at": datetime.utcnow(),
            })
            await comments_collection.update_one(
                {"_id": ObjectId(comment_id)},
                {"$inc": {"aggregates.helpful_count": 1}}
            )
            voted = True

        # Get updated count
        updated_comment = await comments_collection.find_one({"_id": ObjectId(comment_id)})
        new_count = updated_comment.get("aggregates", {}).get("helpful_count", 0)

        return voted, new_count


class EnrichmentService:
    """Service to enrich posts/comments with author and plant info."""

    @staticmethod
    def _users_collection():
        return Database.get_collection("users")

    @staticmethod
    def _plants_collection():
        return Database.get_collection("plants")

    @staticmethod
    def _maybe_presign_asset(key: Optional[str], expiration: int = 3600) -> Optional[str]:
        """
        Convert stored S3 keys into a loadable URL for clients.
        If S3_BASE_URL is configured, use it; else generate a presigned GET URL.
        """
        if not key:
            return None
        value = str(key).strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value

        normalized = value.lstrip("/")

        # IMPORTANT: user uploads (plants/, uploads/) are typically stored in a private uploads bucket.
        # Do NOT use S3_BASE_URL here (often points to a separate public assets bucket).
        if normalized.startswith("plants/") or normalized.startswith("uploads/"):
            try:
                from app.core.aws import S3Service
                return S3Service().generate_presigned_get_url(normalized, expiration=expiration)
            except Exception:
                return normalized

        # For non-upload assets, fall back to S3_BASE_URL if configured.
        from app.core.config import get_settings
        settings = get_settings()
        base = (settings.S3_BASE_URL or "").strip()
        if base:
            if not base.endswith("/"):
                base = base + "/"
            return base + normalized

        return normalized

    @classmethod
    async def get_authors_batch(cls, author_ids: List[str]) -> Dict[str, dict]:
        """Batch fetch author info."""
        if not author_ids:
            return {}

        users_cursor = cls._users_collection().find(
            {"_id": {"$in": [ObjectId(uid) for uid in author_ids if ObjectId.is_valid(uid)]}},
            {"name": 1, "city": 1, "level": 1, "title": 1, "profile_visibility": 1},
        )
        
        authors = {}
        async for user in users_cursor:
            user_id = str(user["_id"])
            visibility = (user.get("profile_visibility") or "public").strip().lower()
            if visibility == "private":
                authors[user_id] = {
                    "id": None,
                    "name": "Anonymous",
                    "city": None,
                    "level": 1,
                    "title": None,
                    "_visibility": "private",
                }
            else:
                authors[user_id] = {
                    "id": user_id,
                    "name": user.get("name", "Unknown"),
                    "city": user.get("city"),
                    "level": user.get("level", 1),
                    "title": user.get("title"),
                    "_visibility": "public",
                }

        return authors

    @classmethod
    async def get_plants_batch(cls, plant_ids: List[str]) -> Dict[str, dict]:
        """Batch fetch plant info."""
        if not plant_ids:
            return {}

        plants_cursor = cls._plants_collection().find(
            {"_id": {"$in": [ObjectId(pid) for pid in plant_ids if ObjectId.is_valid(pid)]}}
        )

        plants = {}
        async for plant in plants_cursor:
            plant_id = str(plant["_id"])
            plants[plant_id] = {
                "id": plant_id,
                "common_name": plant.get("common_name", "Unknown Plant"),
                "scientific_name": plant.get("scientific_name"),
                "image_url": cls._maybe_presign_asset(plant.get("image_url")),
                "nickname": plant.get("nickname"),
            }

        return plants

    @classmethod
    async def enrich_posts(cls, posts: List[dict]) -> List[dict]:
        """Enrich posts with author and plant info."""
        if not posts:
            return posts

        # Collect unique IDs
        author_ids = list(set(p["author_id"] for p in posts))
        plant_ids = list(set(p["plant_id"] for p in posts))

        # Batch fetch
        authors = await cls.get_authors_batch(author_ids)
        plants = await cls.get_plants_batch(plant_ids)

        # Enrich
        for post in posts:
            author = authors.get(post["author_id"])
            post["author"] = {k: v for (k, v) in (author or {}).items() if not str(k).startswith("_")} if author else None

            # If author is private, do not leak raw author_id in public responses.
            if author and author.get("_visibility") == "private":
                post["author_id"] = None
                plant = plants.get(post["plant_id"])
                # Avoid leaking personal plant nicknames for private users.
                if plant and isinstance(plant, dict):
                    plant = dict(plant)
                    plant["nickname"] = None
                post["plant"] = plant
            else:
                post["plant"] = plants.get(post["plant_id"])

        return posts

    @classmethod
    async def enrich_comments(cls, comments: List[dict]) -> List[dict]:
        """Enrich comments with author info."""
        if not comments:
            return comments

        author_ids = list(set(c["author_id"] for c in comments))
        authors = await cls.get_authors_batch(author_ids)

        for comment in comments:
            author = authors.get(comment["author_id"])
            comment["author"] = {k: v for (k, v) in (author or {}).items() if not str(k).startswith("_")} if author else None
            if author and author.get("_visibility") == "private":
                comment["author_id"] = None

        return comments
