# 🌱 Plantsitter API

**Urban Gardening Assistant for Indian Balconies**

An intelligent plant care backend that helps urban Indians keep their balcony plants alive. Uses AI for plant identification and health assessment, combined with real-time weather data for personalized care recommendations.

## Features

- 🔍 **Plant Analysis** - Upload a photo to identify plants and assess their health using GPT-4o Vision
- 📅 **Care Schedules** - Get personalized watering and care routines based on plant type and season
- 🌤️ **Weather Alerts** - Receive alerts for extreme weather conditions (heatwaves, heavy rain, cold snaps)
- 🏠 **Plant Collection** - Manage your personal plant collection with tracking
- 🇮🇳 **India-First** - Optimized for Indian climate conditions (heat, monsoon, dust, pollution)

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI (Python) |
| Database | MongoDB |
| Auth | JWT (PyJWT + bcrypt) |
| AI | OpenAI GPT-4o Vision |
| Weather | OpenWeatherMap API |
| Container | Docker + Docker Compose |

## Project Structure

```
app/
├── __init__.py
├── main.py                 # FastAPI app entry point
│
├── core/                   # Shared utilities
│   ├── __init__.py
│   ├── config.py           # Settings (env variables)
│   ├── database.py         # MongoDB connection
│   ├── dependencies.py     # Auth dependencies (get_current_user)
│   └── exceptions.py       # Custom exceptions
│
├── auth/                   # Authentication module
│   ├── __init__.py
│   ├── models.py           # User schemas
│   ├── service.py          # JWT, password, user operations
│   └── views.py            # /auth endpoints
│
├── plants/                 # Plants module
│   ├── __init__.py
│   ├── models.py           # Plant schemas
│   ├── openai_service.py   # GPT-4o Vision integration
│   ├── service.py          # Plant CRUD, knowledge base
│   └── views.py            # /plants endpoints
│
└── weather/                # Weather module
    ├── __init__.py
    ├── models.py           # Weather schemas
    ├── service.py          # OpenWeatherMap integration
    └── views.py            # /weather endpoints
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- OpenAI API key ([Get one here](https://platform.openai.com/api-keys))
- OpenWeatherMap API key ([Get one here](https://openweathermap.org/api))

### 1. Clone and Setup

```bash
cd vatika_backend

# Copy environment file and add your API keys
cp env.example .env
```

Edit `.env` and add your API keys:
```env
OPENAI_API_KEY=sk-your-actual-key
OPENWEATHER_API_KEY=your-actual-key
JWT_SECRET_KEY=generate-a-secure-random-key
```

### 2. Start with Docker

```bash
# Start API + MongoDB
docker-compose up --build

# Or run in background
docker-compose up -d --build
```

The API will be available at: **http://localhost:8000**

### 3. View API Documentation

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Optional: MongoDB Admin UI

```bash
# Start with Mongo Express UI
docker-compose --profile tools up
```

Access Mongo Express at: http://localhost:8081

## Local Development (Without Docker)

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

### 2. Start MongoDB

Make sure MongoDB is running locally on port 27017.

```bash
# Using Docker for just MongoDB
docker run -d -p 27017:27017 --name plantsitter-mongo mongo:7

# Or install MongoDB locally
```

### 3. Run the Server

```bash
# Development with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

### Authentication (`/api/v1/auth`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/register` | Register new user |
| POST | `/login` | Login and get token |
| GET | `/me` | Get current user profile |
| PATCH | `/me` | Update profile |

### Plants (`/api/v1/plants`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/analyze` | Analyze plant image (AI) |
| POST | `/` | Save plant to collection |
| GET | `/` | List user's plants |
| GET | `/{id}` | Get specific plant |
| PATCH | `/{id}` | Update plant |
| DELETE | `/{id}` | Delete plant |
| POST | `/{id}/water` | Mark plant as watered |
| GET | `/care/{plant_id}` | Get care info |
| GET | `/search?q=` | Search knowledge base |

### Weather (`/api/v1/weather`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/alerts/{city}` | Get weather alerts for city |
| GET | `/alerts` | Get alerts for user's city |

## Usage Examples

### Register a User

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "securepassword",
    "name": "Plant Lover",
    "city": "Mumbai",
    "balcony_orientation": "west"
  }'
```

### Analyze a Plant Image

```bash
# First, convert your image to base64
BASE64_IMAGE=$(base64 -i plant.jpg)

curl -X POST http://localhost:8000/api/v1/plants/analyze \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d "{\"image_base64\": \"$BASE64_IMAGE\"}"
```

### Get Weather Alerts

```bash
curl http://localhost:8000/api/v1/weather/alerts/bangalore
```

## Module Architecture

Each feature module follows the same pattern:

```
module/
├── __init__.py      # Exports the router
├── models.py        # Pydantic schemas (request/response)
├── service.py       # Business logic (database, external APIs)
└── views.py         # FastAPI routes
```

This structure:
- Keeps related code together (easy to find)
- Avoids circular imports
- Makes testing easier
- Follows Flask blueprint-like patterns

## Supported Indian Cities

Weather alerts are optimized for major Indian cities:
- Mumbai, Delhi, Bangalore, Chennai, Kolkata
- Hyderabad, Pune, Ahmedabad, Jaipur
- Lucknow, Chandigarh, Kochi, Goa
- Noida, Gurgaon, and more

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - feel free to use this for your own projects!

---

Made with 🌿 for urban plant parents in India
