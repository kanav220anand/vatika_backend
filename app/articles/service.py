"""Article selector service (deterministic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set

from bson import ObjectId

from app.core.database import Database
from app.core.exceptions import NotFoundException


@dataclass(frozen=True)
class NormalizedPlantAnalysis:
    plant_family: str
    confidence_bucket: str
    health_status: str
    primary_issue: str
    severity: str


class ArticleSelectorService:
    """Selects up to the allowed number of contextual articles for a plant."""

    @staticmethod
    def _articles_collection():
        return Database.get_collection("articles")

    @staticmethod
    def _plants_collection():
        return Database.get_collection("plants")

    @staticmethod
    def _overlaps(tags: List[str], used: Set[str]) -> bool:
        return any(t in used for t in (tags or []))

    @classmethod
    async def _pick_first(cls, query: Dict, used_tags: Set[str]) -> Optional[dict]:
        """Pick highest priority doc matching query with no issue_tag overlap."""
        cursor = cls._articles_collection().find(query).sort("priority", -1)
        async for doc in cursor:
            tags = doc.get("issue_tags") or []
            if cls._overlaps(tags, used_tags):
                continue
            return doc
        return None

    @staticmethod
    def _step4_allowed_tags() -> List[str]:
        # Must be deterministic and concrete, not abstract theme tags.
        return [
            # light
            "low_light",
            "light_excess",
            "direct_sunlight",
            "sun_stress",
            "light_instability",
            # growth
            "slow_growth",
            "recovery_time",
            "new_growth",
            "stalled_growth",
            # environment
            "low_humidity",
            "high_humidity",
            "heat_stress",
            "airflow_issues",
            "environmental_change",
        ]

    @classmethod
    async def _load_normalized_analysis(cls, plant_id: str, user_id: str) -> NormalizedPlantAnalysis:
        if not ObjectId.is_valid(plant_id):
            raise NotFoundException("Plant not found")

        plant = await cls._plants_collection().find_one({"_id": ObjectId(plant_id), "user_id": user_id})
        if not plant:
            raise NotFoundException("Plant not found")

        plant_family = plant.get("plant_family")
        confidence_bucket = plant.get("confidence_bucket")
        health_status = plant.get("health_status")
        primary_issue = plant.get("health_primary_issue")
        severity = plant.get("health_severity")

        if not (plant_family and confidence_bucket and health_status and primary_issue and severity):
            # If analysis isn't present yet, we return empty selection upstream.
            return NormalizedPlantAnalysis(
                plant_family=plant_family or "",
                confidence_bucket=confidence_bucket or "",
                health_status=health_status or "",
                primary_issue=primary_issue or "",
                severity=severity or "",
            )

        return NormalizedPlantAnalysis(
            plant_family=plant_family,
            confidence_bucket=confidence_bucket,
            health_status=health_status,
            primary_issue=primary_issue,
            severity=severity,
        )

    @classmethod
    async def select_for_plant(cls, plant_id: str, user_id: str) -> List[dict]:
        """
        Deterministic selector.

        - Healthy: exactly 1 article (family overlay).
        - Stressed/Unhealthy: up to 3 (v1 UI rule is 2–3; Step 4 only fills gaps).
        - Severity high caps at 3 and forbids Step 4 (fewer articles).
        - No overlapping issue_tags between selected articles.
        """
        analysis = await cls._load_normalized_analysis(plant_id, user_id)

        # If we don't have enough analysis to select deterministically, show nothing.
        if not (analysis.plant_family and analysis.health_status):
            return []
        if analysis.health_status != "healthy" and not (
            analysis.confidence_bucket and analysis.primary_issue and analysis.severity
        ):
            return []

        used_tags: Set[str] = set()
        selected: List[dict] = []

        # Healthy rule: show only the family overlay.
        if analysis.health_status == "healthy":
            family = await cls._pick_first(
                {
                    "scope": "family",
                    "plant_family": analysis.plant_family,
                    "is_active": True,
                    "plant": None,
                },
                used_tags,
            )
            if family:
                used_tags.update(family.get("issue_tags") or [])
                selected.append(family)
            return selected[:1]

        # Caps
        max_articles = 3

        # STEP 1 — Primary Universal Explainer (ALWAYS)
        if analysis.primary_issue:
            explainer = await cls._pick_first(
                {
                    "scope": "universal",
                    "issue_tags": analysis.primary_issue,
                    "is_active": True,
                    "plant": None,
                },
                used_tags,
            )
            if explainer:
                used_tags.update(explainer.get("issue_tags") or [])
                selected.append(explainer)

        # STEP 2 — Family Overlay (ALWAYS)
        family = await cls._pick_first(
            {
                "scope": "family",
                "plant_family": analysis.plant_family,
                "is_active": True,
                "plant": None,
            },
            used_tags,
        )
        if family and len(selected) < max_articles:
            used_tags.update(family.get("issue_tags") or [])
            selected.append(family)

        # STEP 3 — Recovery / Expectation Article
        allowed_intents = ["expectation"] if analysis.severity == "high" else ["expectation", "preventive"]
        expectation = await cls._pick_first(
            {
                "scope": "universal",
                "intent": {"$in": allowed_intents},
                "is_active": True,
                "plant": None,
            },
            used_tags,
        )
        if expectation and len(selected) < max_articles:
            used_tags.update(expectation.get("issue_tags") or [])
            selected.append(expectation)

        # STEP 4 — Optional Education (ONLY if allowed)
        if analysis.confidence_bucket == "high" and analysis.severity != "high" and len(selected) < max_articles:
            education = await cls._pick_first(
                {
                    "scope": "universal",
                    "issue_tags": {"$in": cls._step4_allowed_tags()},
                    "is_active": True,
                    "plant": None,
                },
                used_tags,
            )
            if education and len(selected) < max_articles:
                used_tags.update(education.get("issue_tags") or [])
                selected.append(education)

        return selected[:max_articles]
