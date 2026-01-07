"""Article models."""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


ArticleScope = Literal["universal", "family"]
ArticleIntent = Literal["explanatory", "expectation", "preventive"]


class ArticlePreview(BaseModel):
    """Preview returned in plant details."""

    id: str
    title: str
    read_time_minutes: int = Field(default=3, ge=1, le=60)
    intent: ArticleIntent


class ArticlesResponse(BaseModel):
    articles: List[ArticlePreview] = Field(default_factory=list)


class ArticleDetailResponse(BaseModel):
    id: str
    title: str
    description: str
    read_time_minutes: Optional[int] = None
    intent: Optional[ArticleIntent] = None

