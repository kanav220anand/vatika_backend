"""Mongo clients for jobs (async Motor for API; sync PyMongo for worker)."""

from __future__ import annotations

from functools import lru_cache
from typing import Tuple
from urllib.parse import urlparse

from pymongo import MongoClient

from app.core.config import get_settings
from app.core.database import Database


def _effective_mongo_uri_and_db() -> Tuple[str, str]:
    settings = get_settings()
    uri = (getattr(settings, "MONGODB_URI", "") or "").strip()
    if not uri:
        # Backward compatible: build from MONGO_URI + MONGO_DB_NAME.
        uri = (settings.MONGO_URI or "").strip()
        db = (settings.MONGO_DB_NAME or "").strip()
        return uri, db

    parsed = urlparse(uri)
    path = (parsed.path or "").lstrip("/")
    db = path.split("/")[0] if path else (settings.MONGO_DB_NAME or "plantsitter")
    return uri, db


async def get_motor_db():
    # Uses the shared Motor client already connected in app.core.database.Database.
    return Database.db


@lru_cache
def get_pymongo_db():
    uri, db_name = _effective_mongo_uri_and_db()
    client = MongoClient(uri)
    return client[db_name]

