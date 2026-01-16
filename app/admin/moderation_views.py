"""Admin moderation endpoints for Care Club (Postman-only, MOD-001)."""

from fastapi import APIRouter, Depends, Query, Path

from app.admin.dependencies import require_admin_api_key
from app.care_club.moderation_service import ModerationService
from app.care_club.models import (
    AdminReportsListResponse,
    AdminReportDetailResponse,
    ReportResponse,
    ResolveReportRequest,
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin_api_key)],
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

