# Testing Guide

## Prerequisites

1. **Docker and Docker Compose** must be installed and running
2. **Environment variables** set in `.env` file:
   - `OPENAI_API_KEY` - Your OpenAI API key
   - `OPENWEATHER_API_KEY` - Your OpenWeatherMap API key
   - `JWT_SECRET_KEY` - Generated secure key (already generated)

## Quick Start

### 1. Start the Application

```bash
# Make sure Docker is running
docker ps

# Start all services
docker-compose up --build

# Or run in background
docker-compose up -d --build
```

The API will be available at: **http://localhost:8000**

### 2. Run Tests

Once the API is running, execute the test script:

```bash
# Install requests if needed
pip install requests

# Run the test script
python3 test_api.py
```

The test script will:
- Test health check endpoints
- Test authentication flow (register, login, profile)
- Test all plant endpoints (analyze, CRUD, care, search)
- Test weather alert endpoints

## Manual Testing

### Using Swagger UI

1. Open http://localhost:8000/docs
2. Use the interactive API documentation to test endpoints

## Jobs / Celery (INFRA-001 + JOBS-001)

Local dev requirement: **use real AWS SQS** (no LocalStack).

### 1) Create SQS queue (one-time)

```bash
aws sqs create-queue --queue-name vatika-default --region ap-south-1
```

### 2) Get queue URL

```bash
aws sqs get-queue-url --queue-name vatika-default --region ap-south-1
```

Copy the returned URL into `.env` as:

`SQS_DEFAULT_QUEUE_URL=...`

### 3) Minimal IAM permissions

The AWS identity used by the API and worker must have:
- `sqs:SendMessage`
- `sqs:ReceiveMessage`
- `sqs:DeleteMessage`
- `sqs:GetQueueAttributes`
- `sqs:GetQueueUrl`
- `sqs:ChangeMessageVisibility` (recommended; visibility extensions/retries)

Important: `CELERY_VISIBILITY_TIMEOUT` must exceed your longest task runtime or SQS may redeliver messages.

### 4) Run API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5) Run worker (separate terminal)

```bash
celery -A app.worker.celery_app.celery_app worker --loglevel=INFO
```

### 6) Smoke test (requires auth token)

Create a `ping` job:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type":"ping","input":{}}' \
  http://localhost:8000/api/v1/vatisha/jobs | jq
```

Poll until succeeded:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/vatisha/jobs/<JOB_ID> | jq
```

### Using curl

See examples in the main README.md file.

## Test Results

The test script provides color-coded output:
- ✓ Green - Test passed
- ✗ Red - Test failed
- ℹ Yellow - Informational message

## Troubleshooting

### Port 8000 already in use

```bash
# Find and kill the process
lsof -ti:8000 | xargs kill -9

# Or use a different port in docker-compose.yml
```

### MongoDB connection errors

```bash
# Check if MongoDB container is running
docker ps | grep mongo

# Check MongoDB logs
docker logs plantsitter-mongo
```

### API not starting

```bash
# Check API logs
docker logs plantsitter-api

# Rebuild containers
docker-compose down
docker-compose up --build
```

## Expected Test Flow

1. **Health Checks** ✓
   - GET / → 200 OK
   - GET /health → 200 OK with DB status

2. **Authentication** ✓
   - POST /api/v1/auth/register → 201 Created (or 400 if exists)
   - POST /api/v1/auth/login → 200 OK with token
   - GET /api/v1/auth/me → 200 OK with user data
   - PATCH /api/v1/auth/me → 200 OK with updated data

3. **Plants** ✓
   - POST /api/v1/plants/analyze → 200 OK (may fail if OpenAI key invalid)
   - POST /api/v1/plants → 201 Created
   - GET /api/v1/plants → 200 OK with list
   - GET /api/v1/plants/{id} → 200 OK
   - PATCH /api/v1/plants/{id} → 200 OK
   - POST /api/v1/plants/{id}/water → 200 OK
   - GET /api/v1/plants/care/{plant_id} → 200 OK or 404
   - GET /api/v1/plants/search?q=... → 200 OK
   - DELETE /api/v1/plants/{id} → 204 No Content

4. **Weather** ✓
   - GET /api/v1/weather/alerts/{city} → 200 OK
   - GET /api/v1/weather/alerts → 200 OK (requires auth)
