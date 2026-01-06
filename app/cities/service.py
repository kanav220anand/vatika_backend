"""Service layer for cities directory."""

import re
from typing import List
from app.core.database import Database


class CitiesService:
    """Service for city search/typeahead."""

    @staticmethod
    def get_collection():
        return Database.get_collection("cities")

    @classmethod
    async def search(cls, query: str = "", limit: int = 10) -> List[dict]:
        """
        Case- and whitespace-insensitive search across city and state.

        Matches prefix of name/state using a safe regex. Results sorted by rank
        (seed order) to prioritize bigger/more common cities.
        """
        collection = cls.get_collection()
        q = (query or "").strip()

        filter_query = {}
        if q:
            safe = re.escape(q)
            filter_query = {
                "$or": [
                    {"name_lower": {"$regex": f"^{safe}", "$options": "i"}},
                    {"state_lower": {"$regex": f"^{safe}", "$options": "i"}},
                ]
            }

        cursor = (
            collection.find(filter_query, {"_id": 0})
            .sort("rank", 1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)
