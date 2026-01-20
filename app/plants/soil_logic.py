"""Soil logic (ANALYSIS-002).

- Derives a lightweight hint from a soil assessment.
- Computes a day-shift modifier for watering schedules using latest cached soil_state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.core.config import get_settings
from app.plants.models import SoilAssessment, SoilHint, SoilState

settings = get_settings()


def compute_soil_hint(soil: Optional[SoilAssessment]) -> Optional[SoilHint]:
    """
    Derive a user-friendly hint from soil signals.

    Returns None when soil isn't visible or confidence is below the configured threshold.
    """
    if soil is None:
        return None
    if not soil.visible:
        return None
    if float(soil.confidence or 0.0) < float(getattr(settings, "SOIL_CONFIDENCE_THRESHOLD", 0.6)):
        return None

    dryness = (soil.dryness or "unknown").value if hasattr(soil.dryness, "value") else str(soil.dryness or "unknown")
    mold = (soil.surface_signals.mold_or_algae or "unknown").value if hasattr(soil.surface_signals.mold_or_algae, "value") else str(soil.surface_signals.mold_or_algae or "unknown")
    salt = (soil.surface_signals.salt_crust or "unknown").value if hasattr(soil.surface_signals.salt_crust, "value") else str(soil.surface_signals.salt_crust or "unknown")

    if dryness == "waterlogged":
        return SoilHint(
            status="action",
            headline="Soil looks waterlogged",
            action="Hold watering and improve drainage; recheck tomorrow",
            confidence=soil.confidence,
            relevant_factors=["dryness:waterlogged"],
        )
    if dryness == "wet":
        return SoilHint(
            status="action",
            headline="Soil looks wet",
            action="Hold watering 1–2 days; recheck top 2cm",
            confidence=soil.confidence,
            relevant_factors=["dryness:wet"],
        )
    if dryness == "very_dry":
        return SoilHint(
            status="action",
            headline="Soil looks very dry",
            action="Check top 2cm; water if dry",
            confidence=soil.confidence,
            relevant_factors=["dryness:very_dry"],
        )
    if mold == "likely":
        return SoilHint(
            status="watch",
            headline="Possible surface mold",
            action="Increase airflow; avoid keeping topsoil wet",
            confidence=soil.confidence,
            relevant_factors=["mold_or_algae:likely"],
        )
    if salt == "likely":
        return SoilHint(
            status="watch",
            headline="Possible mineral buildup",
            action="Top up soil or flush lightly next watering",
            confidence=soil.confidence,
            relevant_factors=["salt_crust:likely"],
        )
    return None


def compute_soil_shift_days(
    soil_state: Optional[SoilState],
    last_watered_at: Optional[datetime],
    now: datetime,
) -> int:
    """
    Compute a day-shift modifier for schedule-based next watering.

    Positive shift delays watering; negative shift pulls it earlier.

    Safety check:
    - If user watered recently and then uploaded a photo, wet soil is expected and should not delay.
    """
    if soil_state is None:
        return 0
    if not soil_state.visible:
        return 0

    threshold = float(getattr(settings, "SOIL_CONFIDENCE_THRESHOLD", 0.6))
    if float(soil_state.confidence or 0.0) < threshold:
        return 0

    observed_at = soil_state.observed_at
    if not isinstance(observed_at, datetime):
        return 0

    max_age_days = int(getattr(settings, "SOIL_MAX_AGE_DAYS", 3))
    if observed_at < (now - timedelta(days=max_age_days)):
        return 0

    dryness = soil_state.dryness.value if hasattr(soil_state.dryness, "value") else str(soil_state.dryness)
    mapping = {
        "very_dry": -1,
        "dry": -1,
        "moist": 0,
        "wet": 1,
        "waterlogged": 2,
        "unknown": 0,
    }
    shift = int(mapping.get(dryness, 0))

    # CRITICAL SAFETY CHECK (watered today + photo today)
    if dryness in {"wet", "waterlogged"} and isinstance(last_watered_at, datetime):
        ignore_hours = int(getattr(settings, "SOIL_RECENT_WATERING_IGNORE_HOURS", 24))
        if last_watered_at.date() == observed_at.date():
            return 0
        if observed_at - last_watered_at <= timedelta(hours=ignore_hours):
            return 0

    max_shift = int(getattr(settings, "SOIL_SHIFT_MAX_DAYS", 2))
    if shift > max_shift:
        shift = max_shift
    if shift < -max_shift:
        shift = -max_shift
    return shift

