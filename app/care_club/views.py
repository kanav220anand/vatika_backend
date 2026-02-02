"""Care Club API routes.

Debug logging for image URLs:
Run with DEBUG=true and check logs for IMAGE_URL_DEBUG entries.
"""

from fastapi import APIRouter, Depends, Query, Path
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

from app.core.dependencies import get_current_user
from app.core.database import Database
from app.core.s3_urls import presign_user_uploads
from app.core.exceptions import NotFoundException
from app.care_club.models import (
    CreatePostRequest,
    UpdatePostRequest,
    ResolvePostRequest,
    CreateCommentRequest,
    PostResponse,
    PostsListResponse,
    PostListItem,
    CommentsListResponse,
    CommentResponse,
    HelpfulVoteResponse,
    PostAggregates,
    CommentAggregates,
    AuthorInfo,
    PlantInfo,
    CreateReportRequest,
    ReportResponse,
)
from app.care_club.service import (
    CareClubRepository,
    CommentsRepository,
    EnrichmentService,
)
from app.care_club.guards import require_public_profile, require_rate_limit
from app.care_club.moderation_service import ModerationService


router = APIRouter(prefix="/care-club", tags=["Care Club"])

def _to_read_urls(urls: List[str], expiration: int = 3600) -> List[str]:
    """
    Convert stored DB values into URLs that the app can actually load.

    Order of preference:
    - If value is a user-uploaded key (or a stored S3 URL), generate a fresh presigned GET URL.
    - Otherwise return the original value unchanged.
    
    DEBUG: Logs what URLs are being returned.
    """
    if not urls:
        return []

    out = presign_user_uploads(urls, expiration=expiration)
    for resolved in out:
        logger.info(f"[IMAGE_URL_DEBUG] CareClub: Resolved URL {str(resolved)[:80]}...")

    return out


# ============================================================================
# Posts
# ============================================================================

@router.get("/posts", response_model=PostsListResponse)
async def list_posts(
    limit: int = Query(20, ge=1, le=50, description="Number of posts to return"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    status: Optional[str] = Query(None, description="Filter by status: 'open' or 'resolved'"),
    current_user: dict = Depends(get_current_user),
):
    """
    List Care Club posts (newest first).
    
    Pagination is cursor-based using created_at timestamps.
    """
    posts, total, has_more, next_cursor = await CareClubRepository.list_posts(
        viewer_user_id=current_user["id"],
        limit=limit,
        cursor=cursor,
        status=status,
    )

    # Enrich with author and plant info
    posts = await EnrichmentService.enrich_posts(posts)

    # Convert to response models
    items = []
    for p in posts:
        items.append(PostListItem(
            id=p["id"],
            plant_id=p["plant_id"],
            author_id=p["author_id"],
            title=p["title"],
            photo_urls=_to_read_urls(p.get("photo_urls", [])),
            status=p["status"],
            moderation_status=p.get("moderation_status", "active"),
            created_at=p["created_at"],
            last_activity_at=p["last_activity_at"],
            aggregates=PostAggregates(**p.get("aggregates", {})),
            author=AuthorInfo(**p["author"]) if p.get("author") else None,
            plant=PlantInfo(**p["plant"]) if p.get("plant") else None,
        ))

    return PostsListResponse(
        posts=items,
        total=total,
        has_more=has_more,
        next_cursor=next_cursor,
    )


@router.get("/posts/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: str = Path(..., description="Post ID"),
    current_user: dict = Depends(get_current_user),
):
    """Get a single post by ID."""
    post = await CareClubRepository.get_post(post_id)

    if (post.get("moderation_status") or "active") != "active" and post.get("author_id") != current_user["id"]:
        raise NotFoundException("Post not found")

    # Enrich
    posts = await EnrichmentService.enrich_posts([post])
    post = posts[0]

    return PostResponse(
        id=post["id"],
        plant_id=post["plant_id"],
        author_id=post["author_id"],
        title=post["title"],
        details=post.get("details"),
        tried=post.get("tried"),
        photo_urls=_to_read_urls(post.get("photo_urls", [])),
        status=post["status"],
        moderation_status=post.get("moderation_status", "active"),
        resolved_at=post.get("resolved_at"),
        resolved_note=post.get("resolved_note"),
        created_at=post["created_at"],
        updated_at=post["updated_at"],
        last_activity_at=post["last_activity_at"],
        aggregates=PostAggregates(**post.get("aggregates", {})),
        author=AuthorInfo(**post["author"]) if post.get("author") else None,
        plant=PlantInfo(**post["plant"]) if post.get("plant") else None,
    )


@router.patch("/posts/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: str = Path(..., description="Post ID"),
    request: UpdatePostRequest = ...,
    current_user: dict = Depends(get_current_user),
):
    """
    Update a Care Club post (author only).
    """
    post = await CareClubRepository.update_post(
        post_id=post_id,
        user_id=current_user["id"],
        updates=request.model_dump(exclude_unset=True),
    )

    post = (await EnrichmentService.enrich_posts([post]))[0]

    return PostResponse(
        id=post["id"],
        plant_id=post["plant_id"],
        author_id=post["author_id"],
        title=post["title"],
        details=post.get("details"),
        tried=post.get("tried"),
        photo_urls=_to_read_urls(post.get("photo_urls", [])),
        status=post["status"],
        moderation_status=post.get("moderation_status", "active"),
        resolved_at=post.get("resolved_at"),
        resolved_note=post.get("resolved_note"),
        created_at=post["created_at"],
        updated_at=post["updated_at"],
        last_activity_at=post["last_activity_at"],
        aggregates=PostAggregates(**post.get("aggregates", {})),
        author=AuthorInfo(**post["author"]) if post.get("author") else None,
        plant=PlantInfo(**post["plant"]) if post.get("plant") else None,
    )


@router.post("/posts", response_model=PostResponse)
async def create_post(
    request: CreatePostRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new Care Club post.
    
    The plant_id must belong to the current user.
    If no photos are provided, the plant's image will be used as default.
    """
    await require_public_profile(current_user["id"])
    await require_rate_limit(current_user["id"], "post")
    post = await CareClubRepository.create_post(
        author_id=current_user["id"],
        plant_id=request.plant_id,
        title=request.title,
        details=request.details,
        tried=request.tried,
        photo_urls=request.photo_urls,
    )

    # Enrich
    posts = await EnrichmentService.enrich_posts([post])
    post = posts[0]

    return PostResponse(
        id=post["id"],
        plant_id=post["plant_id"],
        author_id=post["author_id"],
        title=post["title"],
        details=post.get("details"),
        tried=post.get("tried"),
        photo_urls=_to_read_urls(post.get("photo_urls", [])),
        status=post["status"],
        moderation_status=post.get("moderation_status", "active"),
        resolved_at=post.get("resolved_at"),
        resolved_note=post.get("resolved_note"),
        created_at=post["created_at"],
        updated_at=post["updated_at"],
        last_activity_at=post["last_activity_at"],
        aggregates=PostAggregates(**post.get("aggregates", {})),
        author=AuthorInfo(**post["author"]) if post.get("author") else None,
        plant=PlantInfo(**post["plant"]) if post.get("plant") else None,
    )


@router.post("/posts/{post_id}/resolve", response_model=PostResponse)
async def resolve_post(
    post_id: str = Path(..., description="Post ID"),
    request: ResolvePostRequest = ...,
    current_user: dict = Depends(get_current_user),
):
    """
    Mark a post as resolved.
    
    Only the post author can resolve. Must provide 'resolved_note' explaining what worked.
    """
    await require_public_profile(current_user["id"])
    post = await CareClubRepository.resolve_post(
        post_id=post_id,
        user_id=current_user["id"],
        resolved_note=request.resolved_note,
    )

    # Enrich
    posts = await EnrichmentService.enrich_posts([post])
    post = posts[0]

    return PostResponse(
        id=post["id"],
        plant_id=post["plant_id"],
        author_id=post["author_id"],
        title=post["title"],
        details=post.get("details"),
        tried=post.get("tried"),
        photo_urls=_to_read_urls(post.get("photo_urls", [])),
        status=post["status"],
        moderation_status=post.get("moderation_status", "active"),
        resolved_at=post.get("resolved_at"),
        resolved_note=post.get("resolved_note"),
        created_at=post["created_at"],
        updated_at=post["updated_at"],
        last_activity_at=post["last_activity_at"],
        aggregates=PostAggregates(**post.get("aggregates", {})),
        author=AuthorInfo(**post["author"]) if post.get("author") else None,
        plant=PlantInfo(**post["plant"]) if post.get("plant") else None,
    )


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str = Path(..., description="Post ID"),
    current_user: dict = Depends(get_current_user),
):
    """
    Delete a post.
    
    Only the post author can delete. This also deletes all comments and helpful votes.
    """
    await CareClubRepository.delete_post(post_id, current_user["id"])
    return {"message": "Post deleted successfully"}


# ============================================================================
# Comments
# ============================================================================

@router.get("/posts/{post_id}/comments", response_model=CommentsListResponse)
async def list_comments(
    post_id: str = Path(..., description="Post ID"),
    limit: int = Query(50, ge=1, le=100, description="Number of comments to return"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    current_user: dict = Depends(get_current_user),
):
    """
    List comments for a post (oldest first).
    
    Includes whether the current user has marked each comment as helpful.
    """
    comments, total, has_more, next_cursor = await CommentsRepository.list_comments(
        post_id=post_id,
        user_id=current_user["id"],
        limit=limit,
        cursor=cursor,
    )

    # Enrich with author info
    comments = await EnrichmentService.enrich_comments(comments)

    items = []
    for c in comments:
        items.append(CommentResponse(
            id=c["id"],
            post_id=c["post_id"],
            author_id=c["author_id"],
            body=c["body"],
            photo_urls=_to_read_urls(c.get("photo_urls", [])),
            created_at=c["created_at"],
            moderation_status=c.get("moderation_status", "active"),
            aggregates=CommentAggregates(**c.get("aggregates", {})),
            author=AuthorInfo(**c["author"]) if c.get("author") else None,
            user_voted_helpful=c.get("user_voted_helpful", False),
        ))

    return CommentsListResponse(
        comments=items,
        total=total,
        has_more=has_more,
        next_cursor=next_cursor,
    )


@router.post("/posts/{post_id}/comments", response_model=CommentResponse)
async def add_comment(
    post_id: str = Path(..., description="Post ID"),
    request: CreateCommentRequest = ...,
    current_user: dict = Depends(get_current_user),
):
    """Add a comment to a post."""
    await require_public_profile(current_user["id"])
    await require_rate_limit(current_user["id"], "comment")
    comment = await CommentsRepository.add_comment(
        post_id=post_id,
        author_id=current_user["id"],
        body=request.body,
        photo_urls=request.photo_urls,
    )

    # Enrich with author info
    comments = await EnrichmentService.enrich_comments([comment])
    comment = comments[0]

    return CommentResponse(
        id=comment["id"],
        post_id=comment["post_id"],
        author_id=comment["author_id"],
        body=comment["body"],
        photo_urls=_to_read_urls(comment.get("photo_urls", [])),
        created_at=comment["created_at"],
        moderation_status=comment.get("moderation_status", "active"),
        aggregates=CommentAggregates(**comment.get("aggregates", {})),
        author=AuthorInfo(**comment["author"]) if comment.get("author") else None,
        user_voted_helpful=comment.get("user_voted_helpful", False),
    )


@router.delete("/posts/{post_id}/comments/{comment_id}")
async def delete_comment(
    post_id: str = Path(..., description="Post ID"),
    comment_id: str = Path(..., description="Comment ID"),
    current_user: dict = Depends(get_current_user),
):
    """
    Delete a comment.
    
    Only the comment author can delete.
    """
    await CommentsRepository.delete_comment(comment_id, current_user["id"])
    return {"message": "Comment deleted successfully"}


# ============================================================================
# Helpful Votes
# ============================================================================

@router.post("/posts/{post_id}/comments/{comment_id}/helpful", response_model=HelpfulVoteResponse)
async def toggle_helpful(
    post_id: str = Path(..., description="Post ID"),
    comment_id: str = Path(..., description="Comment ID"),
    current_user: dict = Depends(get_current_user),
):
    """
    Toggle helpful vote on a comment.
    
    Each user can only vote once per comment. Calling again removes the vote.
    """
    await require_public_profile(current_user["id"])

    # Apply rate limit only when creating a new helpful vote (not when removing).
    existing_vote = await Database.get_collection("care_club_helpful_votes").find_one(
        {"comment_id": comment_id, "user_id": current_user["id"]},
        {"_id": 1},
    )
    if not existing_vote:
        await require_rate_limit(current_user["id"], "helpful_vote")

    voted, new_count = await CommentsRepository.toggle_helpful(
        post_id=post_id,
        comment_id=comment_id,
        user_id=current_user["id"],
    )

    return HelpfulVoteResponse(voted=voted, new_count=new_count)


# ============================================================================
# Reporting (MOD-001)
# ============================================================================

@router.post("/report", response_model=ReportResponse)
async def report_content(
    request: CreateReportRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Report a Care Club post/comment.

    We auto-hide the target immediately to stop harm fast.
    """
    report = await ModerationService.create_report(
        reporter_user_id=current_user["id"],
        target_type=request.target_type.value,
        target_id=request.target_id,
        reason=request.reason.value,
        notes=request.notes,
    )

    return ReportResponse(
        id=report["id"],
        reporter_user_id=report["reporter_user_id"],
        target_type=report["target_type"],
        target_id=report["target_id"],
        reason=report["reason"],
        notes=report.get("notes"),
        status=report.get("status", "open"),
        created_at=report["created_at"],
        resolved_at=report.get("resolved_at"),
        resolved_action=report.get("resolved_action"),
        resolved_note=report.get("resolved_note"),
    )
