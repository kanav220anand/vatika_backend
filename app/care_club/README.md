# Care Club - Q&A Community Feature

Care Club is a plant Q&A community where users can ask questions tied to their plants and get help from the community.

## Architecture Overview

### Data Model (MongoDB Collections)

```
care_club_posts (main collection)
├── _id: ObjectId
├── plant_id: string (required, must belong to author)
├── author_id: string
├── title: string (max 120)
├── details: string | null (max 1000)
├── tried: string | null (max 600) - "What have you tried?"
├── photo_urls: string[]
├── status: 'open' | 'resolved'
├── moderation_status: 'active' | 'hidden' | 'removed'
├── resolved_at: timestamp | null
├── resolved_note: string | null (required when resolved)
├── created_at: timestamp
├── updated_at: timestamp
├── last_activity_at: timestamp
└── aggregates:
    ├── comment_count: number
    └── latest_comment_at: timestamp | null

care_club_comments (separate collection)
├── _id: ObjectId
├── post_id: string
├── author_id: string
├── body: string (max 600)
├── photo_urls: string[]
├── created_at: timestamp
├── moderation_status: 'active' | 'hidden' | 'removed'
└── aggregates:
    └── helpful_count: number

care_club_helpful_votes (separate collection, unique index on comment_id + user_id)
├── _id: ObjectId
├── post_id: string
├── comment_id: string
├── user_id: string
└── created_at: timestamp

care_club_reports (moderation queue)
├── _id: ObjectId
├── reporter_user_id: string
├── target_type: 'post' | 'comment'
├── target_id: string
├── reason: 'spam' | 'abuse' | 'wrong_info' | 'other'
├── notes: string | null
├── status: 'open' | 'resolved'
├── snapshot: object (minimal target metadata for admins)
├── created_at: timestamp
├── resolved_at: timestamp | null
├── resolved_action: 'restore' | 'remove' | null
└── resolved_note: string | null

moderation_actions (audit trail, optional)
├── _id: ObjectId
├── admin_user_id: string
├── action: 'restore' | 'remove'
├── target_type: 'post' | 'comment'
├── target_id: string
├── report_id: string
├── note: string | null
└── created_at: timestamp
```

### Aggregate Maintenance Strategy

Aggregates are stored on parent documents and updated atomically:

1. **Comment Count**: When a comment is created/deleted, `care_club_posts.aggregates.comment_count` is incremented/decremented using `$inc`.

2. **Helpful Count**: When a helpful vote is toggled, `care_club_comments.aggregates.helpful_count` is updated using `$inc`.

3. **Timestamps**: `last_activity_at` is updated on the post whenever a comment is added.

All aggregate updates happen in the same operation as the main action (no separate triggers needed).

### Repository Pattern

The service layer follows a repository pattern for clean separation:

```python
CareClubRepository
├── list_posts(viewer_user_id, limit, cursor, status?)
├── get_post(post_id)
├── create_post(author_id, plant_id, title, details?, tried?, photo_urls?)
├── resolve_post(post_id, user_id, resolved_note)
└── delete_post(post_id, user_id)

CommentsRepository
├── list_comments(post_id, user_id, limit, cursor)
├── add_comment(post_id, author_id, body, photo_urls?)
├── delete_comment(comment_id, user_id)
└── toggle_helpful(post_id, comment_id, user_id)

EnrichmentService
├── get_authors_batch(author_ids[])
├── get_plants_batch(plant_ids[])
├── enrich_posts(posts[])
└── enrich_comments(comments[])
```

### API Endpoints

```
POST   /api/v1/vatisha/care-club/posts                    - Create post
GET    /api/v1/vatisha/care-club/posts                    - List posts (pagination)
GET    /api/v1/vatisha/care-club/posts/{id}               - Get post detail
POST   /api/v1/vatisha/care-club/posts/{id}/resolve       - Resolve post (owner only)
DELETE /api/v1/vatisha/care-club/posts/{id}               - Delete post (owner only)

GET    /api/v1/vatisha/care-club/posts/{id}/comments      - List comments
POST   /api/v1/vatisha/care-club/posts/{id}/comments      - Add comment
DELETE /api/v1/vatisha/care-club/posts/{id}/comments/{id} - Delete comment
POST   /api/v1/vatisha/care-club/posts/{id}/comments/{id}/helpful - Toggle helpful
POST   /api/v1/vatisha/care-club/report                   - Report post/comment (auto-hide)

# Admin (Postman-only; requires X-ADMIN-API-KEY)
GET    /api/v1/vatisha/admin/reports?status=open|resolved  - Reports queue
GET    /api/v1/vatisha/admin/reports/{id}                  - Report detail (includes snapshot)
POST   /api/v1/vatisha/admin/reports/{id}/resolve          - Resolve report (restore/remove)
```

### Pagination

Cursor-based pagination using `created_at` timestamps:
- Posts: newest first (descending)
- Comments: oldest first (ascending)

Response format:
```json
{
  "posts": [...],
  "total": 42,
  "has_more": true,
  "next_cursor": "2024-01-15T10:30:00.000Z"
}
```

### Permissions

| Action | Who Can Do It |
|--------|---------------|
| Read posts/comments | Any authenticated user |
| Create post | Public-profile users only (plant must belong to them) |
| Resolve post | Public-profile users only (and post author) |
| Delete post | Post author only |
| Create comment | Public-profile users only |
| Delete comment | Comment author only |
| Toggle helpful | Public-profile users only (1 vote per comment) |
| Report post/comment | Any authenticated user |

### Privacy (PRIV-001)

If `users.profile_visibility == "private"`:
- Reads still work (feed/posts/comments)
- All write actions are rejected with `403`:
  `"Your profile is private. Switch to Public to participate in Care Club."`
- In read responses, private authors are anonymized:
  - `author_id` becomes `null`
  - `author.name` becomes `"Anonymous"`

### Moderation (MOD-001)

Posts/comments have an additional field `moderation_status`:
- `active`: visible publicly
- `hidden`: hidden from public reads (auto-hidden immediately on report)
- `removed`: removed from public reads (admin action)

Public reads only return `active` content. Authors can still access their own hidden/removed post detail by ID.

### Rate limits (MOD-001)

Server-side limits over a rolling 24h window:
- Create post: `CARE_CLUB_POSTS_PER_24H` (default 3)
- Create comment: `CARE_CLUB_COMMENTS_PER_24H` (default 10)
- Helpful votes: `CARE_CLUB_HELPFUL_VOTES_PER_24H` (default 30, only when adding a vote)

When exceeded: `HTTP 429` with message:
`You’re doing that too often. Please try again later.`

### Postman ops (admin moderation)

Set `ADMIN_API_KEY` in backend env, then:

```bash
# List open reports
curl -s -H "X-ADMIN-API-KEY: $ADMIN_API_KEY" \
  "http://localhost:8000/api/v1/vatisha/admin/reports?status=open&limit=50" | jq

# Inspect a report
curl -s -H "X-ADMIN-API-KEY: $ADMIN_API_KEY" \
  "http://localhost:8000/api/v1/vatisha/admin/reports/<REPORT_ID>" | jq

# Restore
curl -s -H "X-ADMIN-API-KEY: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action":"restore","note":"false positive"}' \
  "http://localhost:8000/api/v1/vatisha/admin/reports/<REPORT_ID>/resolve" | jq

# Remove
curl -s -H "X-ADMIN-API-KEY: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action":"remove","note":"spam"}' \
  "http://localhost:8000/api/v1/vatisha/admin/reports/<REPORT_ID>/resolve" | jq
```

Quick sanity (requires valid JWT tokens):
```bash
# Private user should be blocked from creating a post
curl -i -H "Authorization: Bearer $PRIVATE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plant_id":"<PLANT_ID>","title":"Test","details":"x"}' \
  http://localhost:8000/api/v1/vatisha/care-club/posts

# Feed should show Anonymous for private authors
curl -s -H "Authorization: Bearer $PUBLIC_TOKEN" \
  "http://localhost:8000/api/v1/vatisha/care-club/posts?limit=5" | jq '.posts[].author'
```

### Photo Storage

Post/comment photos are stored in S3 under:
```
plants/{user_id}/{plant_id}/posts_images/{timestamp}_{uuid}_{filename}
```

If no photos are provided when creating a post, the plant's latest image is used as default.

### Database Indexes

```python
# Posts
care_club_posts.create_index([("created_at", -1)])  # For feed ordering
care_club_posts.create_index([("author_id", 1)])    # For user's posts
care_club_posts.create_index([("plant_id", 1)])     # For plant's posts
care_club_posts.create_index([("status", 1), ("created_at", -1)])  # Filtered feed
care_club_posts.create_index([("last_activity_at", -1)])  # Activity ranking
care_club_posts.create_index([("moderation_status", 1), ("created_at", -1)])  # Moderation filtering

# Comments
care_club_comments.create_index([("post_id", 1), ("created_at", 1)])  # Comments for post
care_club_comments.create_index([("post_id", 1), ("moderation_status", 1), ("created_at", 1)])  # Moderation filtering
care_club_comments.create_index([("author_id", 1)])  # User's comments

# Helpful votes (unique constraint for 1 vote per user per comment)
care_club_helpful_votes.create_index([("comment_id", 1), ("user_id", 1)], unique=True)
care_club_helpful_votes.create_index([("post_id", 1)])  # Cleanup when post deleted
care_club_helpful_votes.create_index([("user_id", 1), ("created_at", -1)])  # Rate limiting

# Reports (dedupe + queue)
care_club_reports.create_index([("status", 1), ("created_at", -1)])
care_club_reports.create_index([("target_type", 1), ("target_id", 1)])
care_club_reports.create_index([("reporter_user_id", 1), ("target_type", 1), ("target_id", 1)], unique=True)
```

## Frontend Screens

1. **CareClubHomeScreen** - Feed of posts with hero Ask CTA
2. **CareClubNewPostScreen** - Create post form with plant picker
3. **CareClubPostDetailScreen** - Post detail with comments
4. **ResolveBottomSheet** - Modal for marking post resolved

## Entry Points

1. Care Club tab in bottom navigation
2. "Ask" button on Plant Detail screen (preselects plant)
3. Hero CTA on Care Club Home

## Seed Script

Run the seed script to populate test data:
```bash
cd vatika_backend
python scripts/seed_care_club.py
```

Requires existing users and plants in the database.
