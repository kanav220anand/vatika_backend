"""Watering & care recommendation engine (v1).

This is a deterministic rules engine (no LLM calls) used for:
- UI guidance ("Check soil today" vs "Time to water")
- Reminder generation (NotificationService)

It intentionally handles unknown watering history without inventing fake dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.plants.service import PlantService
from app.plants.soil_logic import compute_soil_shift_days
from app.plants.models import SoilState


@dataclass(frozen=True)
class WateringRecommendation:
    guidance_type: str  # "check" | "water"
    urgency: str  # "upcoming" | "due_today" | "overdue"
    next_water_date: Optional[datetime]
    days_until_due: int
    recommended_action: str
    reason: str


def _utc_now(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.utcnow().replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _days_between(a: datetime, b: datetime) -> int:
    """Whole-day delta between two UTC datetimes (date-based)."""
    a_date = a.date()
    b_date = b.date()
    return (a_date - b_date).days


def compute_watering_recommendation(plant: dict, *, now: Optional[datetime] = None) -> WateringRecommendation:
    """
    Compute watering guidance for a plant.

    Rules:
    - If last_watered is None and last_watered_source is missing/unknown:
        - urgency = due_today
        - guidance_type = check
        - recommended_action = "Check soil today"
    - Otherwise (known last_watered):
        - use schedule-based next water date (from care_schedule) and derive urgency
        - guidance_type = water
    """
    now_utc = _utc_now(now)

    last_watered = plant.get("last_watered")
    last_watered_source = (plant.get("last_watered_source") or "").strip() or None

    soil_state: Optional[SoilState] = None
    raw_soil_state = plant.get("soil_state")
    if isinstance(raw_soil_state, SoilState):
        soil_state = raw_soil_state
    elif isinstance(raw_soil_state, dict):
        try:
            soil_state = SoilState(**raw_soil_state)
        except Exception:
            soil_state = None

    # Back-compat: no source + null last_watered => unknown.
    if last_watered is None and (last_watered_source in (None, "unknown")):
        # If we have a recent, confident soil_state, use it to nudge today’s guidance without inventing last_watered.
        try:
            shift = compute_soil_shift_days(soil_state, None, now_utc.replace(tzinfo=None))
        except Exception:
            shift = 0

        if shift >= 1:
            next_dt = now_utc + timedelta(days=shift)
            return WateringRecommendation(
                guidance_type="check",
                urgency="upcoming",
                next_water_date=next_dt,
                days_until_due=(next_dt.date() - now_utc.date()).days,
                recommended_action="Hold watering today; recheck tomorrow",
                reason="Last watering time is unknown (soil appears wet)",
            )
        if shift <= -1:
            return WateringRecommendation(
                guidance_type="water",
                urgency="due_today",
                next_water_date=now_utc,
                days_until_due=0,
                recommended_action="Water today (soil looks dry)",
                reason="Last watering time is unknown (soil appears dry)",
            )
        return WateringRecommendation(
            guidance_type="check",
            urgency="due_today",
            next_water_date=now_utc,
            days_until_due=0,
            recommended_action="Check soil today",
            reason="Last watering time is unknown",
        )

    next_water = PlantService.calculate_next_water_date(plant)
    if next_water is None:
        # If schedule is missing, fall back to "check" (safe and non-prescriptive).
        return WateringRecommendation(
            guidance_type="check",
            urgency="due_today",
            next_water_date=now_utc,
            days_until_due=0,
            recommended_action="Check soil today",
            reason="Watering schedule is unavailable",
        )

    base_next_utc = next_water if next_water.tzinfo else next_water.replace(tzinfo=timezone.utc)

    # ANALYSIS-002: apply soil day-shift modifier using latest cached soil_state.
    try:
        shift_days = compute_soil_shift_days(soil_state, last_watered, now_utc.replace(tzinfo=None))
    except Exception:
        shift_days = 0
    next_water_utc = base_next_utc + timedelta(days=shift_days)

    # Date-based computation keeps UX stable (no hour-level jitter).
    days_until_due = (next_water_utc.date() - now_utc.date()).days

    if days_until_due < 0:
        urgency = "overdue"
        recommended_action = "Water today"
        reason = f"Overdue by {abs(days_until_due)} day(s)"
    elif days_until_due == 0:
        urgency = "due_today"
        recommended_action = "Water today"
        reason = "Due today"
    else:
        urgency = "upcoming"
        recommended_action = f"Next watering in {days_until_due} day(s)"
        reason = "On schedule"

    if shift_days != 0:
        reason = f"{reason} (adjusted by soil)"

    return WateringRecommendation(
        guidance_type="water",
        urgency=urgency,
        next_water_date=next_water_utc,
        days_until_due=days_until_due,
        recommended_action=recommended_action,
        reason=reason,
    )
