# AI / OpenAI Endpoints (COST-001)

This backend calls OpenAI only from the Plants domain.

## Endpoints that trigger OpenAI

- `POST /api/v1/vatisha/plants/analyze`
  - Plant identification + health + care from an uploaded image.
- `POST /api/v1/vatisha/plants/analyze/detect`
  - Multi-plant detection (returns crop boxes + thumbnails).
- `POST /api/v1/vatisha/plants/analyze/thumbnail`
  - Thumbnail + context analysis (health + care).
- `POST /api/v1/vatisha/plants/{plant_id}/health-snapshots`
  - Weekly snapshot upload + analysis (runs OpenAI automatically).

## Protections applied

- Auth required (JWT) on all AI endpoints.
- Max request body size via `MaxBodySizeMiddleware` → `413 Payload too large`.
- Rate limiting + quotas (Mongo):
  - Per-IP coarse limit: `AI_RATE_PER_IP_PER_MINUTE`
  - Per-user per-minute: `AI_RATE_ANALYZE_PER_MINUTE` / `AI_RATE_GENERIC_PER_MINUTE`
  - Per-user daily: `AI_DAILY_REQUESTS`
  - Per-user daily snapshots: `AI_DAILY_SNAPSHOTS`
- S3 key ownership validation (SEC-002): only keys under `plants/{user_id}/...` or `uploads/{user_id}/...`.
- OpenAI concurrency + timeout in `app/plants/openai_service.py`:
  - `AI_MAX_CONCURRENT`
  - `AI_OPENAI_TIMEOUT_SECONDS`
- Usage logging to Mongo `ai_usage` (success + fail; no prompts/images stored).

## Environment variables

All are optional (defaults are in `app/core/config.py`):

- `MAX_REQUEST_BODY_BYTES` (default `2000000`)
- `AI_MAX_CONCURRENT` (default `10`)
- `AI_OPENAI_TIMEOUT_SECONDS` (default `45`)
- `AI_MAX_S3_IMAGE_BYTES` (default `8000000`)
- `AI_MAX_BASE64_CHARS` (default `120000`)
- `AI_RATE_PER_IP_PER_MINUTE` (default `60`)
- `AI_RATE_ANALYZE_PER_MINUTE` (default `10`)
- `AI_RATE_GENERIC_PER_MINUTE` (default `30`)
- `AI_DAILY_REQUESTS` (default `50`)
- `AI_DAILY_SNAPSHOTS` (default `10`)

## Example 429 response

When rate-limited:

```json
{ "detail": "Rate limit exceeded. Try again in 60 seconds." }
```

When daily-limited:

```json
{ "detail": "Daily limit reached. Try again tomorrow." }
```
