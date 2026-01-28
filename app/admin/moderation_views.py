"""Admin moderation endpoints for Care Club (Postman-only, MOD-001)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path
from pydantic import BaseModel, Field

from app.admin.dependencies import require_admin_api_key
from app.care_club.moderation_service import ModerationService
from app.care_club.models import (
    AdminReportsListResponse,
    AdminReportDetailResponse,
    ReportResponse,
    ResolveReportRequest,
)
from app.weather.service import WeatherService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin_api_key)],
)


# ==================== Weather Prefetch Admin Endpoints ====================


class WeatherPrefetchResponse(BaseModel):
    """Response for weather prefetch endpoint."""
    success: bool
    city: Optional[str] = None
    cities_processed: Optional[int] = None
    cities_failed: Optional[int] = None
    message: str


@router.post("/weather/prefetch", response_model=WeatherPrefetchResponse)
async def prefetch_weather_forecast(
    city: Optional[str] = Query(None, description="City to prefetch (omit for all active cities)"),
):
    """
    Trigger weather forecast prefetch for caching.
    
    - If `city` is provided, prefetch for that specific city.
    - If `city` is omitted, prefetch for all cities with active users.
    
    Protected by ADMIN_API_KEY header (X-ADMIN-API-KEY).
    
    Example:
        curl -X POST "https://api.vatisha.com/api/v1/vatisha/admin/weather/prefetch?city=mumbai" \\
             -H "X-ADMIN-API-KEY: your-admin-key"
    """
    service = WeatherService()
    
    if city:
        # Single city mode
        city_key = city.lower().strip()
        logger.info(f"Admin prefetch triggered for city: {city_key}")
        
        success = await service.prefetch_forecast_for_city(city_key)
        
        return WeatherPrefetchResponse(
            success=success,
            city=city_key,
            message=f"Prefetch {'succeeded' if success else 'failed'} for {city_key}",
        )
    
    else:
        # All cities mode
        logger.info("Admin prefetch triggered for all active cities")
        
        cities = await WeatherService.get_active_user_cities()
        
        if not cities:
            return WeatherPrefetchResponse(
                success=True,
                cities_processed=0,
                cities_failed=0,
                message="No active cities found in user profiles",
            )
        
        success_count = 0
        failure_count = 0
        
        for c in cities:
            if await service.prefetch_forecast_for_city(c):
                success_count += 1
            else:
                failure_count += 1
        
        return WeatherPrefetchResponse(
            success=failure_count == 0,
            cities_processed=success_count,
            cities_failed=failure_count,
            message=f"Prefetched {success_count} cities, {failure_count} failed",
        )


@router.get("/reports", response_model=AdminReportsListResponse)
async def list_reports(
    status: str = Query("open", description="open | resolved"),
    limit: int = Query(50, ge=1, le=200),
):
    reports, total = await ModerationService.list_reports(status=status, limit=limit)
    items = [
        ReportResponse(
            id=r["id"],
            reporter_user_id=r["reporter_user_id"],
            target_type=r["target_type"],
            target_id=r["target_id"],
            reason=r["reason"],
            notes=r.get("notes"),
            status=r.get("status", "open"),
            created_at=r["created_at"],
            resolved_at=r.get("resolved_at"),
            resolved_action=r.get("resolved_action"),
            resolved_note=r.get("resolved_note"),
        )
        for r in reports
    ]
    return AdminReportsListResponse(reports=items, total=total)


@router.get("/reports/{report_id}", response_model=AdminReportDetailResponse)
async def get_report(report_id: str = Path(..., description="Report ID")):
    r = await ModerationService.get_report(report_id)
    return AdminReportDetailResponse(
        id=r["id"],
        reporter_user_id=r["reporter_user_id"],
        target_type=r["target_type"],
        target_id=r["target_id"],
        reason=r["reason"],
        notes=r.get("notes"),
        status=r.get("status", "open"),
        created_at=r["created_at"],
        resolved_at=r.get("resolved_at"),
        resolved_action=r.get("resolved_action"),
        resolved_note=r.get("resolved_note"),
        snapshot=r.get("snapshot"),
    )


@router.post("/reports/{report_id}/resolve", response_model=AdminReportDetailResponse)
async def resolve_report(
    report_id: str = Path(..., description="Report ID"),
    request: ResolveReportRequest = ...,
):
    r = await ModerationService.resolve_report(
        report_id=report_id,
        action=request.action,
        admin_user_id="admin",
        note=request.note,
    )
    return AdminReportDetailResponse(
        id=r["id"],
        reporter_user_id=r["reporter_user_id"],
        target_type=r["target_type"],
        target_id=r["target_id"],
        reason=r["reason"],
        notes=r.get("notes"),
        status=r.get("status", "open"),
        created_at=r["created_at"],
        resolved_at=r.get("resolved_at"),
        resolved_action=r.get("resolved_action"),
        resolved_note=r.get("resolved_note"),
        snapshot=r.get("snapshot"),
    )

