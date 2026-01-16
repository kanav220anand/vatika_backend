"""Care Club Pydantic models and schemas."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Embedded / Nested Schemas
# ============================================================================

class PostAggregates(BaseModel):
    """Aggregate counts stored on post document."""
    comment_count: int = 0
    latest_comment_at: Optional[datetime] = None


class CommentAggregates(BaseModel):
    """Aggregate counts stored on comment document."""
    helpful_count: int = 0


# ============================================================================
# Request Schemas
# ============================================================================

class CreatePostRequest(BaseModel):
    """Request to create a new Care Club post."""
    plant_id: str = Field(..., description="User's plant ID (required)")
    title: str = Field(..., min_length=1, max_length=120)
    details: Optional[str] = Field(None, max_length=1000)
    tried: Optional[str] = Field(None, max_length=600, description="What have you tried?")
    photo_urls: Optional[List[str]] = Field(default_factory=list, max_length=3)

    @field_validator('photo_urls')
    @classmethod
    def validate_photo_urls(cls, v):
        if v and len(v) > 3:
            raise ValueError('Maximum 3 photos allowed')
        return v or []


class ResolvePostRequest(BaseModel):
    """Request to resolve a post."""
    resolved_note: str = Field(..., min_length=1, max_length=600, description="What worked")


class CreateCommentRequest(BaseModel):
    """Request to create a comment."""
    body: str = Field(..., min_length=1, max_length=600)
    photo_urls: Optional[List[str]] = Field(default_factory=list, max_length=3)

    @field_validator('photo_urls')
    @classmethod
    def validate_photo_urls(cls, v):
        if v and len(v) > 3:
            raise ValueError('Maximum 3 photos allowed')
        return v or []


# ============================================================================
# Response Schemas - Author/Plant Info (fetched separately)
# ============================================================================

class AuthorInfo(BaseModel):
    """Author information for display."""
    id: Optional[str] = None
    name: str
    city: Optional[str] = None
    level: int = 1
    title: Optional[str] = None


class PlantInfo(BaseModel):
    """Plant information for display."""
    id: str
    common_name: str
    scientific_name: Optional[str] = None
    image_url: Optional[str] = None
    nickname: Optional[str] = None


# ============================================================================
# Response Schemas - Posts
# ============================================================================

class PostResponse(BaseModel):
    """Full post response for detail view."""
    id: str
    plant_id: str
    author_id: Optional[str] = None
    title: str
    details: Optional[str] = None
    tried: Optional[str] = None
    photo_urls: List[str] = []
    status: str = "open"  # 'open' | 'resolved'
    resolved_at: Optional[datetime] = None
    resolved_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    aggregates: PostAggregates
    
    # Enriched data (fetched separately)
    author: Optional[AuthorInfo] = None
    plant: Optional[PlantInfo] = None


class PostListItem(BaseModel):
    """Post item for list/feed view."""
    id: str
    plant_id: str
    author_id: Optional[str] = None
    title: str
    photo_urls: List[str] = []
    status: str
    created_at: datetime
    last_activity_at: datetime
    aggregates: PostAggregates
    
    # Enriched data
    author: Optional[AuthorInfo] = None
    plant: Optional[PlantInfo] = None


class PostsListResponse(BaseModel):
    """Paginated posts list response."""
    posts: List[PostListItem]
    total: int
    has_more: bool
    next_cursor: Optional[str] = None


# ============================================================================
# Response Schemas - Comments
# ============================================================================

class CommentResponse(BaseModel):
    """Comment response."""
    id: str
    post_id: str
    author_id: Optional[str] = None
    body: str
    photo_urls: List[str] = []
    created_at: datetime
    aggregates: CommentAggregates
    
    # Enriched data
    author: Optional[AuthorInfo] = None
    
    # User-specific
    user_voted_helpful: bool = False


class CommentsListResponse(BaseModel):
    """Paginated comments list response."""
    comments: List[CommentResponse]
    total: int
    has_more: bool
    next_cursor: Optional[str] = None


# ============================================================================
# Response Schemas - Helpful Vote
# ============================================================================

class HelpfulVoteResponse(BaseModel):
    """Response after toggling helpful vote."""
    voted: bool
    new_count: int
