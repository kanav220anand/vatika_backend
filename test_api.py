#!/usr/bin/env python3
"""
Comprehensive API test script for Plantsitter Backend.
Tests all endpoints in positive flow.
"""

import requests
import json
import base64
import sys
from typing import Optional

BASE_URL = "http://localhost:8000"
API_BASE = f"{BASE_URL}/api/v1"

# Test data
TEST_USER = {
    "email": "test@plantsitter.com",
    "password": "testpassword123",
    "name": "Test User",
    "city": "Bangalore",
    "balcony_orientation": "west"
}

# Note: Using a minimal test image. For real testing, use a proper plant photo.
# This small image may fail OpenAI analysis, which is expected.
# Small test image (1x1 red pixel PNG in base64)
TEST_IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_test(name: str):
    print(f"\n{Colors.BLUE}=== {name} ==={Colors.END}")

def print_success(msg: str):
    print(f"{Colors.GREEN}✓ {msg}{Colors.END}")

def print_error(msg: str):
    print(f"{Colors.RED}✗ {msg}{Colors.END}")

def print_info(msg: str):
    print(f"{Colors.YELLOW}ℹ {msg}{Colors.END}")

def test_health_checks():
    """Test health check endpoints."""
    print_test("Health Checks")
    
    # Root endpoint
    try:
        r = requests.get(f"{BASE_URL}/")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        print_success("GET / - Root health check")
    except Exception as e:
        print_error(f"GET / - {str(e)}")
        return False
    
    # Health endpoint
    try:
        r = requests.get(f"{BASE_URL}/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        print_success("GET /health - Detailed health check")
        print_info(f"Database: {data.get('database', 'unknown')}")
    except Exception as e:
        print_error(f"GET /health - {str(e)}")
        return False
    
    return True

def test_auth_flow() -> Optional[str]:
    """Test authentication flow. Returns access token on success."""
    print_test("Authentication Flow")
    
    token = None
    
    # Register
    try:
        r = requests.post(f"{API_BASE}/auth/register", json=TEST_USER)
        if r.status_code == 201 or r.status_code == 200:
            data = r.json()
            assert "access_token" in data
            token = data["access_token"]
            print_success("POST /auth/register - User registered")
        elif r.status_code == 400 and "already registered" in r.json().get("detail", "").lower():
            print_info("User already exists, trying login...")
            # Try login instead
            r = requests.post(f"{API_BASE}/auth/login", json={
                "email": TEST_USER["email"],
                "password": TEST_USER["password"]
            })
            if r.status_code == 200:
                data = r.json()
                token = data["access_token"]
                print_success("POST /auth/login - User logged in")
            else:
                print_error(f"POST /auth/login - {r.status_code}: {r.text}")
                return None
        else:
            print_error(f"POST /auth/register - {r.status_code}: {r.text}")
            return None
    except Exception as e:
        print_error(f"POST /auth/register - {str(e)}")
        return None
    
    if not token:
        return None
    
    # Get profile
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{API_BASE}/auth/me", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == TEST_USER["email"]
        print_success("GET /auth/me - Profile retrieved")
    except Exception as e:
        print_error(f"GET /auth/me - {str(e)}")
        return None
    
    # Update profile
    try:
        headers = {"Authorization": f"Bearer {token}"}
        update_data = {"name": "Updated Test User"}
        r = requests.patch(f"{API_BASE}/auth/me", json=update_data, headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Updated Test User"
        print_success("PATCH /auth/me - Profile updated")
    except Exception as e:
        print_error(f"PATCH /auth/me - {str(e)}")
        return None
    
    return token

def test_plants_flow(token: str) -> Optional[str]:
    """Test plant endpoints. Returns plant_id on success."""
    print_test("Plants Flow")
    
    plant_id = None
    
    # Analyze plant (optional auth)
    try:
        r = requests.post(
            f"{API_BASE}/plants/analyze",
            json={"image_base64": TEST_IMAGE_BASE64}
        )
        if r.status_code == 200:
            data = r.json()
            assert "plant_id" in data
            assert "scientific_name" in data
            assert "health" in data
            assert "care" in data
            plant_analysis = data
            print_success("POST /plants/analyze - Plant analyzed")
            print_info(f"Identified: {data.get('common_name', 'Unknown')} ({data.get('plant_id', 'N/A')})")
        else:
            error_detail = r.json().get("detail", r.text) if r.status_code != 500 else r.text
            if "cannot analyze" in error_detail.lower() or "can't analyze" in error_detail.lower():
                print_info(f"POST /plants/analyze - Image too small/invalid for analysis (expected with test image)")
            else:
                print_error(f"POST /plants/analyze - {r.status_code}: {error_detail[:100]}")
            # Continue with mock data for other tests
            plant_analysis = {
                "plant_id": "test_plant",
                "scientific_name": "Test Plant",
                "common_name": "Test Plant",
                "health_status": "healthy"
            }
            print_info("Using mock plant data for remaining tests")
    except Exception as e:
        print_error(f"POST /plants/analyze - {str(e)}")
        print_info("Using mock plant data for remaining tests")
        plant_analysis = {
            "plant_id": "test_plant",
            "scientific_name": "Test Plant",
            "common_name": "Test Plant",
            "health_status": "healthy"
        }
    
    # Save plant
    try:
        headers = {"Authorization": f"Bearer {token}"}
        plant_data = {
            "plant_id": plant_analysis.get("plant_id", "test_plant"),
            "scientific_name": plant_analysis.get("scientific_name", "Test Plant"),
            "common_name": plant_analysis.get("common_name", "Test Plant"),
            "health_status": "healthy"
        }
        r = requests.post(f"{API_BASE}/plants", json=plant_data, headers=headers)
        assert r.status_code == 201
        data = r.json()
        assert "id" in data
        plant_id = data["id"]
        print_success("POST /plants - Plant saved")
    except Exception as e:
        print_error(f"POST /plants - {str(e)}")
        return None
    
    # List plants
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{API_BASE}/plants", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0
        print_success(f"GET /plants - Found {len(data)} plant(s)")
    except Exception as e:
        print_error(f"GET /plants - {str(e)}")
        return None
    
    # Get specific plant
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{API_BASE}/plants/{plant_id}", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == plant_id
        print_success("GET /plants/{id} - Plant retrieved")
    except Exception as e:
        print_error(f"GET /plants/{{id}} - {str(e)}")
        return None
    
    # Update plant
    try:
        headers = {"Authorization": f"Bearer {token}"}
        update_data = {"notes": "Test note", "health_status": "stressed"}
        r = requests.patch(f"{API_BASE}/plants/{plant_id}", json=update_data, headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["notes"] == "Test note"
        print_success("PATCH /plants/{id} - Plant updated")
    except Exception as e:
        print_error(f"PATCH /plants/{{id}} - {str(e)}")
        return None
    
    # Mark as watered
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{API_BASE}/plants/{plant_id}/water", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "last_watered" in data
        print_success("POST /plants/{id}/water - Plant marked as watered")
    except Exception as e:
        print_error(f"POST /plants/{{id}}/water - {str(e)}")
        return None
    
    # Get care info
    try:
        plant_id_for_care = plant_analysis.get("plant_id", "monstera_deliciosa")
        r = requests.get(f"{API_BASE}/plants/care/{plant_id_for_care}")
        if r.status_code == 200:
            data = r.json()
            assert "water_frequency" in data
            print_success("GET /plants/care/{plant_id} - Care info retrieved")
        elif r.status_code == 404:
            print_info("GET /plants/care/{plant_id} - Not in knowledge base yet (expected for new plants)")
        else:
            print_error(f"GET /plants/care/{{plant_id}} - {r.status_code}: {r.text}")
    except Exception as e:
        print_error(f"GET /plants/care/{{plant_id}} - {str(e)}")
    
    # Search plants
    try:
        r = requests.get(f"{API_BASE}/plants/search?q=monstera")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print_success(f"GET /plants/search - Found {len(data)} result(s)")
    except Exception as e:
        print_error(f"GET /plants/search - {str(e)}")
    
    # Delete plant
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.delete(f"{API_BASE}/plants/{plant_id}", headers=headers)
        assert r.status_code == 204
        print_success("DELETE /plants/{id} - Plant deleted")
    except Exception as e:
        print_error(f"DELETE /plants/{{id}} - {str(e)}")
        return None
    
    return plant_id

def test_weather_flow(token: str):
    """Test weather endpoints."""
    print_test("Weather Flow")
    
    # Get alerts for specific city
    try:
        r = requests.get(f"{API_BASE}/weather/alerts/bangalore")
        assert r.status_code == 200
        data = r.json()
        assert "city" in data
        assert "current_weather" in data
        assert "alerts" in data
        print_success("GET /weather/alerts/{city} - Weather alerts retrieved")
        print_info(f"City: {data['city']}, Alerts: {len(data.get('alerts', []))}")
    except Exception as e:
        print_error(f"GET /weather/alerts/{{city}} - {str(e)}")
        return False
    
    # Get alerts for user's city
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{API_BASE}/weather/alerts", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "city" in data
        print_success("GET /weather/alerts - User city weather alerts retrieved")
    except Exception as e:
        print_error(f"GET /weather/alerts - {str(e)}")
        return False
    
    return True

def main():
    """Run all tests."""
    print(f"\n{Colors.BLUE}{'='*60}")
    print("Plantsitter API - Comprehensive Test Suite")
    print(f"{'='*60}{Colors.END}\n")
    
    print_info(f"Testing against: {BASE_URL}")
    print_info("Make sure the API is running before starting tests\n")
    
    # Test health checks
    if not test_health_checks():
        print_error("\nHealth checks failed. Is the API running?")
        sys.exit(1)
    
    # Test auth flow
    token = test_auth_flow()
    if not token:
        print_error("\nAuthentication flow failed. Cannot continue.")
        sys.exit(1)
    
    # Test plants flow
    plant_id = test_plants_flow(token)
    if not plant_id:
        print_error("\nPlants flow had errors (some may be expected).")
    
    # Test weather flow
    if not test_weather_flow(token):
        print_error("\nWeather flow had errors.")
    
    print(f"\n{Colors.GREEN}{'='*60}")
    print("All tests completed!")
    print(f"{'='*60}{Colors.END}\n")

if __name__ == "__main__":
    main()

