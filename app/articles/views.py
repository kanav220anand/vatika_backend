"""Articles API routes."""

from fastapi import APIRouter, Depends, Query
from bson import ObjectId

from app.core.dependencies import get_current_user
from app.core.exceptions import AppException, NotFoundException
from app.articles.models import ArticlesResponse, ArticlePreview, ArticleDetailResponse
from app.articles.service import ArticleSelectorService
from app.core.database import Database


router = APIRouter(prefix="/articles", tags=["Articles"])


@router.get("", response_model=ArticlesResponse)
async def get_articles_for_plant(
    plant_id: str = Query(..., description="Plant instance id"),
    current_user: dict = Depends(get_current_user),
):
    """Get contextual article previews for a plant (deterministic selection)."""
    try:
        docs = await ArticleSelectorService.select_for_plant(plant_id, current_user["id"])
        previews = [
            ArticlePreview(
                id=str(d["_id"]),
                title=d.get("title", ""),
                read_time_minutes=int(d.get("read_time_minutes") or 3),
                intent=d.get("intent", "explanatory"),
            )
            for d in docs
        ]
        return ArticlesResponse(articles=previews)
    except AppException as e:
        raise e
    except Exception as e:
        raise AppException(f"Failed to get articles: {str(e)}")


@router.get("/{article_id}", response_model=ArticleDetailResponse)
async def get_article_detail(
    article_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get full article body for rendering."""
    if not ObjectId.is_valid(article_id):
        raise NotFoundException("Article not found")

    doc = await Database.get_collection("articles").find_one({"_id": ObjectId(article_id), "is_active": True})
    if not doc:
        raise NotFoundException("Article not found")

    return ArticleDetailResponse(
        id=str(doc["_id"]),
        title=doc.get("title", ""),
        description=doc.get("description", "") or "",
        read_time_minutes=doc.get("read_time_minutes"),
        intent=doc.get("intent"),
    )

