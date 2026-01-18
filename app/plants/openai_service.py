"""OpenAI service for plant identification and health analysis."""

import re
import json
import asyncio
from typing import Optional, List, Dict
from openai import AsyncOpenAI
from app.core.config import get_settings
from app.core.aws import S3Service
from app.plants.models import PlantAnalysisResponse, PlantHealth, CareSchedule, PlantToxicity, PlantPlacement

import logging
import traceback

settings = get_settings()
logger = logging.getLogger(__name__)


class OpenAIService:
    """Handles OpenAI API interactions for plant analysis."""
    
    _instance: "OpenAIService" = None
    _semaphore: Optional[asyncio.Semaphore] = None
    
    def __new__(cls):
        """Singleton pattern for OpenAI client."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # COST-001: disable client retries to avoid multiplying spend on transient failures.
            cls._instance.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=0)
            cls._instance.model = settings.OPENAI_MODEL
            cls._semaphore = asyncio.Semaphore(int(getattr(settings, "AI_MAX_CONCURRENT", 10)))
        return cls._instance

    async def _chat_completion(self, **kwargs):
        """
        Centralized OpenAI call wrapper (COST-001):
        - limits concurrency
        - enforces a hard timeout
        """
        timeout_s = int(getattr(settings, "AI_OPENAI_TIMEOUT_SECONDS", 45))
        sem = self.__class__._semaphore
        if sem is None:
            return await asyncio.wait_for(self.client.chat.completions.create(**kwargs), timeout=timeout_s)
        async with sem:
            return await asyncio.wait_for(self.client.chat.completions.create(**kwargs), timeout=timeout_s)

    @staticmethod
    def _coerce_choice(value: Optional[str], allowed: set, default: str = "unknown") -> str:
        raw = (value or "").strip().lower()
        raw = re.sub(r"\s+", "_", raw)
        return raw if raw in allowed else default

    @staticmethod
    def _clamp_confidence(value: object) -> float:
        try:
            f = float(value)  # type: ignore[arg-type]
        except Exception:
            return 0.0
        return max(0.0, min(1.0, f))

    @classmethod
    def _parse_toxicity(cls, data: dict) -> Optional[PlantToxicity]:
        """
        Parse optional toxicity block.

        If plant identification confidence is low (< 0.6), force unknown (per ANALYSIS-001).
        Never hard-fail if missing/invalid.
        """
        plant_conf = cls._clamp_confidence(data.get("confidence"))

        if plant_conf < 0.6:
            return PlantToxicity(
                cats="unknown",
                dogs="unknown",
                humans="unknown",
                severity="unknown",
                summary="Not sure yet — scan again with clearer leaves and pot label if available.",
                symptoms=[],
                confidence=0.0,
            )

        tox = data.get("toxicity")
        if not isinstance(tox, dict):
            return None

        cats = cls._coerce_choice(tox.get("cats"), {"safe", "mildly_toxic", "toxic", "unknown"})
        dogs = cls._coerce_choice(tox.get("dogs"), {"safe", "mildly_toxic", "toxic", "unknown"})
        humans = cls._coerce_choice(tox.get("humans"), {"safe", "irritant", "toxic", "unknown"})
        severity = cls._coerce_choice(tox.get("severity"), {"low", "medium", "high", "unknown"})

        summary = tox.get("summary")
        if isinstance(summary, str):
            summary = " ".join(summary.strip().split())
            if len(summary) > 220:
                summary = summary[:220].rstrip() + "…"
        else:
            summary = None

        symptoms = tox.get("symptoms")
        if not isinstance(symptoms, list):
            symptoms = []
        symptoms_out: List[str] = []
        for s in symptoms:
            if isinstance(s, str):
                item = " ".join(s.strip().split())
                if item:
                    symptoms_out.append(item)
            if len(symptoms_out) >= 8:
                break

        confidence = cls._clamp_confidence(tox.get("confidence"))

        return PlantToxicity(
            cats=cats,
            dogs=dogs,
            humans=humans,
            severity=severity,
            summary=summary,
            symptoms=symptoms_out,
            confidence=confidence,
        )

    @classmethod
    def _parse_placement(cls, data: dict) -> Optional[PlantPlacement]:
        placement = data.get("placement")
        if not isinstance(placement, dict):
            return None

        env_allowed = {"indoor", "outdoor", "both", "unknown"}
        typical = cls._coerce_choice(placement.get("typical_environment"), env_allowed)
        recommended = cls._coerce_choice(placement.get("recommended_environment"), env_allowed)

        reason = placement.get("reason")
        if isinstance(reason, str):
            reason = " ".join(reason.strip().split())
            if len(reason) > 220:
                reason = reason[:220].rstrip() + "…"
        else:
            reason = None

        def clean_list(value: object, max_items: int) -> List[str]:
            if not isinstance(value, list):
                return []
            out: List[str] = []
            for v in value:
                if isinstance(v, str):
                    item = " ".join(v.strip().split())
                    if item:
                        out.append(item)
                if len(out) >= max_items:
                    break
            return out

        indoor_tips = clean_list(placement.get("indoor_tips"), 6)
        outdoor_tips = clean_list(placement.get("outdoor_tips"), 6)
        confidence = cls._clamp_confidence(placement.get("confidence"))

        return PlantPlacement(
            typical_environment=typical,
            recommended_environment=recommended,
            reason=reason,
            indoor_tips=indoor_tips,
            outdoor_tips=outdoor_tips,
            confidence=confidence,
        )

    @staticmethod
    def _normalize_primary_issue(
        primary_issue: Optional[str],
        *,
        issues: Optional[List[str]],
        health_status: Optional[str],
        health_confidence: Optional[float],
        allowed_primary_issues: set,
    ) -> str:
        """
        Ensure `primary_issue` is one of the allowed enum values.

        LLM occasionally returns placeholders like "none" — we map those into safe, broad categories
        so the analysis doesn't hard-fail for users.
        """
        raw = (primary_issue or "").strip().lower()
        raw = re.sub(r"\s+", "_", raw)
        if raw in allowed_primary_issues:
            return raw

        issue_text = " ".join([str(x).lower() for x in (issues or [])])

        # Symptom keyword fallbacks (deterministic)
        if any(k in issue_text for k in ["curl", "curling"]):
            return "leaf_curling"
        if any(k in issue_text for k in ["droop", "drooping", "wilting"]):
            return "leaf_drooping"
        if "yellow" in issue_text:
            return "yellow_leaves"
        if any(k in issue_text for k in ["spot", "spots"]):
            return "leaf_spots"
        if any(k in issue_text for k in ["wrinkl", "wrinkle"]):
            return "leaf_wrinkling"
        if any(k in issue_text for k in ["soft", "mushy"]):
            return "leaf_softness"
        if any(k in issue_text for k in ["crisp", "crispy", "dry_tip", "dry tips", "brown edge", "brown edges"]):
            return "leaf_crisping"
        if any(k in issue_text for k in ["shed", "shedding", "dropping leaves"]):
            return "leaf_shedding"
        if any(k in issue_text for k in ["sun", "burn", "scorch"]):
            return "sun_stress"

        # If confidence is low or the model returned a placeholder, pick a broad v1-safe issue.
        conf = float(health_confidence) if isinstance(health_confidence, (int, float)) else 0.0
        status = (health_status or "").strip().lower()
        if conf < 0.65:
            return "environmental_change" if status in {"stressed", "unhealthy"} else "water_imbalance"

        # Default broad category that won't break downstream selector logic.
        return "water_imbalance"
    
    async def analyze_plant(
        self, 
        image_base64: Optional[str] = None, 
        image_url: Optional[str] = None,
        city: Optional[str] = None
    ) -> PlantAnalysisResponse:
        """
        Analyze a plant image using GPT-4o Vision.
        Accepts either base64 string or S3 key (image_url).
        """
        if not image_base64 and not image_url:
            raise ValueError("Either image_base64 or image_url must be provided")

        city_context = f" The user is in {city}, India." if city else " The user is in India."
        
        prompt = f"""You are an expert botanist specializing in Indian urban balcony plants.{city_context}

PlantFamily =
- succulent_dry
- tropical_foliage
- flowering
- herbs_edibles
- woody_trees
- ferns_moisture

Analyze this plant photo and return a JSON object with the following structure:
{{
    "plant_id": "lowercase_underscore_name (e.g., monstera_deliciosa)",
    "scientific_name": "Scientific name",
    "common_name": "Common name used in India",
    "plant_family": "one of the PlantFamily enum values",
    "confidence": 0.0 to 1.0,
    "health": {{
        "status": "healthy" or "stressed" or "unhealthy",
        "confidence": 0.0 to 1.0,
        "primary_issue": "exactly one from allowed list",
        "severity": "low" or "medium" or "high",
        "issues": ["list of visible issues if any"],
        "immediate_actions": ["list of actions to take now"]
    }},
    "care": {{
        "water_frequency": {{
            "summer": "daily/twice_weekly/weekly/biweekly",
            "monsoon": "frequency",
            "winter": "frequency"
        }},
        "light_preference": "full_sun/bright_indirect/partial_shade/shade",
        "humidity": "low/medium/high",
        "fertilizer_frequency": "weekly/biweekly/monthly/none",
        "indian_climate_tips": ["specific tips for Indian balcony conditions"]
    }},
    "toxicity": {{
        "cats": "safe|mildly_toxic|toxic|unknown",
        "dogs": "safe|mildly_toxic|toxic|unknown",
        "humans": "safe|irritant|toxic|unknown",
        "severity": "low|medium|high|unknown",
        "summary": "1–2 lines max, calm tone",
        "symptoms": ["optional short list"],
        "confidence": 0.0
    }},
    "placement": {{
        "typical_environment": "indoor|outdoor|both|unknown",
        "recommended_environment": "indoor|outdoor|both|unknown",
        "reason": "short reason",
        "indoor_tips": ["2–4 bullets"],
        "outdoor_tips": ["2–4 bullets"],
        "confidence": 0.0
    }}
}}

Choose plant_family based on care behavior, not botanical taxonomy.
If unsure, select the closest match based on watering, light, and growth patterns.
Always choose one family from the provided enum.

Allowed primary_issue values (choose exactly one; must match articles.issue_tags):
overwatering, underwatering, root_rot, root_stress, poor_drainage, dry_soil, water_imbalance,
low_light, light_excess, direct_sunlight, sun_stress, light_instability,
yellow_leaves, leaf_drooping, leaf_curling, leaf_spots, leaf_shedding, leaf_softness, leaf_crisping, leaf_wrinkling,
heat_stress, cold_stress, low_humidity, high_humidity, airflow_issues, environmental_change, relocation_stress, air_pollution,
bud_drop, early_flower_drop, no_blooming, flowering_cycle_disruption,
leggy_growth, bolting, loss_of_flavor, slow_edible_growth,
slow_growth, establishment_stress, fragile_recovery

Choose exactly one primary_issue from the allowed list.
Prefer the underlying cause over visible symptoms.
If uncertain, choose a broader category rather than a specific one (e.g., water_imbalance, environmental_change).

Consider Indian climate challenges: intense heat (40°C+), monsoons, humidity spikes, dust, pollution, and harsh afternoon sun.

Critical rules for toxicity:
- If plant identification confidence < 0.6 OR you are unsure, set cats/dogs/humans/severity to "unknown" and confidence to 0.0.
- Never guess toxicity when uncertain.
- Keep summary calm; no medical advice.

Return ONLY the JSON object, no other text.

IMPORTANT: If the image does NOT contain a real plant (e.g., it's a coffee mug, animal, person, or artificial object), return a JSON with a field "is_plant": false.
Example: {{"is_plant": false, "reason": "Image contains a coffee mug, not a plant"}}"""

        # Prepare image content
        image_content = {}
        if image_base64:
            image_content = {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}",
                    "detail": "high"
                }
            }
        elif image_url:
            # Hybrid Approach: Download from S3 to base64 (in-memory)
            # OpenAI has trouble with S3 presigned URLs (redirects/headers), so we proxy it.
            final_base64 = None
            if not image_url.startswith("http"):
                 try:
                     s3 = S3Service()
                     final_base64 = s3.download_file_as_base64(image_url)
                 except Exception as e:
                     print(f"DEBUG S3 DOWNLOAD ERROR: {e}")
                     pass 
            
            if final_base64:
                image_content = {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{final_base64}",
                        "detail": "high"
                    }
                }
            else:
                # Fallback to original URL if not S3 key or download failed
                image_content = {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url,
                        "detail": "high"
                    }
                }

        try:
            response = await self._chat_completion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            image_content
                        ]
                    }
                ],
                max_tokens=1000,
                temperature=0.3,
            )
        except Exception as e:
            error_msg = str(e)
            if "api key" in error_msg.lower() or "authentication" in error_msg.lower():
                raise ValueError("OpenAI API key is missing or invalid. Please set OPENAI_API_KEY in your environment.")
            raise ValueError(f"OpenAI API error: {error_msg}")
        
        # Parse the response
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("OpenAI returned an empty response")
        
        content = response.choices[0].message.content.strip()
        
        # Check if OpenAI declined to analyze the image
        if "can't analyze" in content.lower() or "cannot analyze" in content.lower() or "unable to analyze" in content.lower():
            raise ValueError(f"OpenAI cannot analyze this image. The image may be too small, invalid, or unclear. Response: {content}")
        
        # Extract JSON from response (handle potential markdown code blocks)
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            content = json_match.group(1).strip()
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse OpenAI response as JSON: {e}. Response: {content[:200]}")
        
        # Check if it's not a plant
        if data.get("is_plant") is False:
             raise ValueError(f"This doesn't look like a plant. {data.get('reason', 'Please upload a clear photo of a plant.')}")
        
        # Validate required fields are present
        required_fields = ["plant_id", "scientific_name", "common_name", "plant_family", "confidence", "health", "care"]
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise ValueError(f"Incomplete plant analysis - missing fields: {', '.join(missing_fields)}. Try taking a clearer photo of the plant.")
        
        # Validate health object
        if not isinstance(data.get("health"), dict):
            raise ValueError("Invalid health data in analysis. Please try again with a clearer photo.")
        
        allowed_plant_families = {
            "succulent_dry",
            "tropical_foliage",
            "flowering",
            "herbs_edibles",
            "woody_trees",
            "ferns_moisture",
        }
        plant_family = data.get("plant_family")
        if not plant_family:
            raise ValueError("Missing plant_family in analysis. Try again with a clearer photo.")
        if plant_family not in allowed_plant_families:
            raise ValueError(f"Invalid plant_family '{plant_family}'. Please try again with a clearer photo.")

        health_required = ["status", "confidence", "primary_issue", "severity"]
        health_missing = [field for field in health_required if field not in data["health"]]
        if health_missing:
            raise ValueError(f"Incomplete health analysis - missing: {', '.join(health_missing)}. Try a clearer photo.")

        allowed_primary_issues = {
            # 🌱 Water & Roots
            "overwatering",
            "underwatering",
            "root_rot",
            "root_stress",
            "poor_drainage",
            "dry_soil",
            "water_imbalance",
            # ☀️ Light
            "low_light",
            "light_excess",
            "direct_sunlight",
            "sun_stress",
            "light_instability",
            # 🌿 Leaves & Growth Symptoms
            "yellow_leaves",
            "leaf_drooping",
            "leaf_curling",
            "leaf_spots",
            "leaf_shedding",
            "leaf_softness",
            "leaf_crisping",
            "leaf_wrinkling",
            # 🌡 Environment & Stress
            "heat_stress",
            "cold_stress",
            "low_humidity",
            "high_humidity",
            "airflow_issues",
            "environmental_change",
            "relocation_stress",
            "air_pollution",
            # 🌸 Flowering-specific
            "bud_drop",
            "early_flower_drop",
            "no_blooming",
            "flowering_cycle_disruption",
            # 🌿 Herbs & Edibles
            "leggy_growth",
            "bolting",
            "loss_of_flavor",
            "slow_edible_growth",
            # 🌴 Trees, Woody & Ferns
            "slow_growth",
            "establishment_stress",
            "fragile_recovery",
        }
        data["health"]["primary_issue"] = self._normalize_primary_issue(
            data["health"].get("primary_issue"),
            issues=data["health"].get("issues", []),
            health_status=data["health"].get("status"),
            health_confidence=data["health"].get("confidence"),
            allowed_primary_issues=allowed_primary_issues,
        )

        allowed_health_status = {"healthy", "stressed", "unhealthy"}
        if data["health"].get("status") not in allowed_health_status:
            raise ValueError("Invalid health.status in analysis. Please try again.")
        allowed_severity = {"low", "medium", "high"}
        if data["health"].get("severity") not in allowed_severity:
            raise ValueError("Invalid health.severity in analysis. Please try again.")
        
        # Validate care object
        if not isinstance(data.get("care"), dict):
            raise ValueError("Invalid care data in analysis. Please try again.")
        
        # Build response model
        health = PlantHealth(
            status=data["health"]["status"],
            confidence=data["health"]["confidence"],
            primary_issue=data["health"]["primary_issue"],
            severity=data["health"]["severity"],
            issues=data["health"].get("issues", []),
            immediate_actions=data["health"].get("immediate_actions", []),
        )
        
        care = CareSchedule(
            water_frequency=data["care"].get("water_frequency", {}),
            light_preference=data["care"].get("light_preference", "bright_indirect"),
            humidity=data["care"].get("humidity", "medium"),
            fertilizer_frequency=data["care"].get("fertilizer_frequency"),
            indian_climate_tips=data["care"].get("indian_climate_tips", []),
        )

        toxicity = self._parse_toxicity(data)
        placement = self._parse_placement(data)
        
        return PlantAnalysisResponse(
            plant_id=data["plant_id"],
            scientific_name=data["scientific_name"],
            common_name=data["common_name"],
            plant_family=data["plant_family"],
            confidence=data["confidence"],
            health=health,
            care=care,
            toxicity=toxicity,
            placement=placement,
        )

    async def detect_multiple_plants(
        self, 
        image_base64: Optional[str] = None,
        image_url: Optional[str] = None,
        city: Optional[str] = None
    ) -> List[Dict]:
        """
        Detect all plants in an image and return their bounding boxes.
        
        Returns a list of plant detections with bounding boxes and preliminary IDs.
        """
        city_context = f" The user is in {city}, India." if city else " The user is in India."
        
        prompt = f"""You are an expert botanist specializing in plant detection.{city_context}

TASK: Identify each INDIVIDUAL potted plant in this image and provide TIGHT bounding boxes.

CRITICAL RULES FOR BOUNDING BOXES:
1. Each box should contain ONLY ONE plant/pot combination
2. Draw boxes TIGHTLY around each plant - minimize empty space
3. Include the pot/container as part of the bounding box
4. Do NOT group multiple plants together
5. For plants in a long planter box with multiple plants, draw SEPARATE boxes for each distinct plant
6. Coordinates are normalized 0-1 where (0,0) is top-left

Return JSON:
{{
    "plants": [
        {{
            "index": 0,
            "bbox": {{"x": 0.1, "y": 0.2, "width": 0.15, "height": 0.25}},
            "preliminary_name": "Snake Plant"
        }}
    ]
}}

BBOX FORMAT:
- x, y = top-left corner (normalized 0-1)
- width, height = size of box (normalized 0-1)
- A typical single potted plant might have width: 0.1-0.25 and height: 0.2-0.4

IDENTIFICATION:
- For preliminary_name, use common names (e.g., "Snake Plant", "Money Plant", "Rubber Plant")
- If unsure, use general name like "Succulent" or "Fern"

Count all visible individual plants. Return ONLY the JSON, no other text.

IMPORTANT: If the image does NOT contain any real plants (e.g., it's a coffee mug, animal, or random object), return {{"plants": []}}."""





        # Prepare image content
        image_content = {}
        if image_base64:
            image_content = {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}",
                    "detail": "high"
                }
            }
        elif image_url:
            final_base64 = None
            if not image_url.startswith("http"):
                 logger.error(f"DEBUG: Downloading S3 key: {image_url}")
                 try:
                     s3 = S3Service()
                     final_base64 = s3.download_file_as_base64(image_url)
                     logger.error(f"DEBUG: Download successful. Base64 len: {len(final_base64) if final_base64 else 0}")
                 except Exception as e:
                     logger.error(f"DEBUG S3 DOWNLOAD ERROR: {e}")
                     pass
            
            if final_base64:
                logger.error("DEBUG: Using Base64 content for OpenAI")
                image_content = {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{final_base64}",
                        "detail": "high"
                    }
                }
            else:
                logger.error(f"DEBUG: Using raw URL: {image_url}")
                image_content = {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url,
                        "detail": "high"
                    }
                }

        try:
            response = await self._chat_completion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            image_content
                        ]
                    }
                ],
                max_tokens=1000,
                temperature=0.3,
            )
        except Exception as e:
            error_msg = str(e)
            if "api key" in error_msg.lower() or "authentication" in error_msg.lower():
                raise ValueError("OpenAI API key is missing or invalid.")
            raise ValueError(f"OpenAI API error: {error_msg}")
        
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("OpenAI returned an empty response")
        
        content = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            content = json_match.group(1).strip()
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse OpenAI response as JSON: {e}")
        
        return data.get("plants", [])

    async def analyze_plant_thumbnail(
        self, 
        thumbnail_base64: str, 
        city: Optional[str] = None,
        context_image_base64: Optional[str] = None,
        context_image_url: Optional[str] = None
    ) -> PlantAnalysisResponse:
        """
        Analyze a cropped plant thumbnail with full health and care analysis.
        
        Similar to analyze_plant but optimized for cropped images.
        """
        city_context = f" The user is in {city}, India." if city else " The user is in India."
        
        prompt = f"""You are an expert botanist specializing in Indian urban balcony plants.{city_context}

PlantFamily =
- succulent_dry
- tropical_foliage
- flowering
- herbs_edibles
- woody_trees
- ferns_moisture

Analyze this plant image (cropped from a larger photo) and return a JSON object:
{{
    "plant_id": "lowercase_underscore_name (e.g., monstera_deliciosa)",
    "scientific_name": "Scientific name",
    "common_name": "Common name used in India",
    "plant_family": "one of the PlantFamily enum values",
    "confidence": 0.0 to 1.0,
    "health": {{
        "status": "healthy" or "stressed" or "unhealthy",
        "confidence": 0.0 to 1.0,
        "primary_issue": "exactly one from allowed list",
        "severity": "low" or "medium" or "high",
        "issues": ["list of visible issues if any"],
        "immediate_actions": ["list of actions to take now"]
    }},
    "care": {{
        "water_frequency": {{
            "summer": "daily/twice_weekly/weekly/biweekly",
            "monsoon": "frequency",
            "winter": "frequency"
        }},
        "light_preference": "full_sun/bright_indirect/partial_shade/shade",
        "humidity": "low/medium/high",
        "fertilizer_frequency": "weekly/biweekly/monthly/none",
        "indian_climate_tips": ["specific tips for Indian balcony conditions"]
    }},
    "toxicity": {{
        "cats": "safe|mildly_toxic|toxic|unknown",
        "dogs": "safe|mildly_toxic|toxic|unknown",
        "humans": "safe|irritant|toxic|unknown",
        "severity": "low|medium|high|unknown",
        "summary": "1–2 lines max, calm tone",
        "symptoms": ["optional short list"],
        "confidence": 0.0
    }},
    "placement": {{
        "typical_environment": "indoor|outdoor|both|unknown",
        "recommended_environment": "indoor|outdoor|both|unknown",
        "reason": "short reason",
        "indoor_tips": ["2–4 bullets"],
        "outdoor_tips": ["2–4 bullets"],
        "confidence": 0.0
    }}
}}

Choose plant_family based on care behavior, not botanical taxonomy.
If unsure, select the closest match based on watering, light, and growth patterns.
Always choose one family from the provided enum.

Allowed primary_issue values (choose exactly one; must match articles.issue_tags):
overwatering, underwatering, root_rot, root_stress, poor_drainage, dry_soil, water_imbalance,
low_light, light_excess, direct_sunlight, sun_stress, light_instability,
yellow_leaves, leaf_drooping, leaf_curling, leaf_spots, leaf_shedding, leaf_softness, leaf_crisping, leaf_wrinkling,
heat_stress, cold_stress, low_humidity, high_humidity, airflow_issues, environmental_change, relocation_stress, air_pollution,
bud_drop, early_flower_drop, no_blooming, flowering_cycle_disruption,
leggy_growth, bolting, loss_of_flavor, slow_edible_growth,
slow_growth, establishment_stress, fragile_recovery

Choose exactly one primary_issue from the allowed list.
Prefer the underlying cause over visible symptoms.
If uncertain, choose a broader category rather than a specific one (e.g., water_imbalance, environmental_change).

Consider Indian climate challenges: intense heat (40°C+), monsoons, humidity, dust, and pollution.

Critical rules for toxicity:
- If plant identification confidence < 0.6 OR you are unsure, set cats/dogs/humans/severity to "unknown" and confidence to 0.0.
- Never guess toxicity when uncertain.
- Keep summary calm; no medical advice.

Return ONLY the JSON object, no other text."""

        messages_content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{thumbnail_base64}",
                    "detail": "high"
                }
            }
        ]
        
        # Add context image if provided (helps with harder identifications)
        if context_image_base64:
            messages_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{context_image_base64}",
                    "detail": "low"  # Lower detail for context
                }
            })
        elif context_image_url:
            final_ctx_url = context_image_url
            if not context_image_url.startswith("http"):
                 try:
                     s3 = S3Service()
                     final_ctx_url = s3.generate_presigned_get_url(context_image_url)
                 except Exception:
                     pass
            
            messages_content.append({
                "type": "image_url",
                "image_url": {
                    "url": final_ctx_url,
                    "detail": "low"
                }
            })

        try:
            response = await self._chat_completion(
                model=self.model,
                messages=[{"role": "user", "content": messages_content}],
                max_tokens=1000,
                temperature=0.3,
            )
        except Exception as e:
            error_msg = str(e)
            if "api key" in error_msg.lower() or "authentication" in error_msg.lower():
                raise ValueError("OpenAI API key is missing or invalid.")
            raise ValueError(f"OpenAI API error: {error_msg}")
        
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("OpenAI returned an empty response")
        
        content = response.choices[0].message.content.strip()
        
        # Check for analysis failures - OpenAI sometimes returns text instead of JSON
        refusal_patterns = [
            "can't analyze", "cannot analyze", "unable to analyze",
            "unable to identify", "can't identify", "cannot identify",
            "i'm unable", "i am unable", "not able to",
            "i cannot", "i can't", "sorry",
        ]
        content_lower = content.lower()
        if any(pattern in content_lower for pattern in refusal_patterns) and not content.strip().startswith("{"):
            raise ValueError(f"Could not identify plant - the image may be unclear or too small. Try a closer photo.")
        
        # Extract JSON from markdown code blocks if present
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            content = json_match.group(1).strip()
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            # If JSON parsing fails, provide a helpful error
            if len(content) < 100 and not content.startswith("{"):
                raise ValueError(f"Could not identify plant - the image may be unclear. Try a different photo.")
            raise ValueError(f"Failed to parse plant analysis. Please try again.")

        
        # Validate required fields are present
        required_fields = ["plant_id", "scientific_name", "common_name", "plant_family", "confidence", "health", "care"]
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise ValueError(f"Incomplete plant analysis - missing fields: {', '.join(missing_fields)}. Try taking a clearer photo of the plant.")
        
        # Validate health object
        if not isinstance(data.get("health"), dict):
            raise ValueError("Invalid health data in analysis. Please try again with a clearer photo.")

        allowed_plant_families = {
            "succulent_dry",
            "tropical_foliage",
            "flowering",
            "herbs_edibles",
            "woody_trees",
            "ferns_moisture",
        }
        plant_family = data.get("plant_family")
        if not plant_family:
            raise ValueError("Missing plant_family in analysis. Try again with a clearer photo.")
        if plant_family not in allowed_plant_families:
            raise ValueError(f"Invalid plant_family '{plant_family}'. Please try again with a clearer photo.")

        health_required = ["status", "confidence", "primary_issue", "severity"]
        health_missing = [field for field in health_required if field not in data["health"]]
        if health_missing:
            raise ValueError(f"Incomplete health analysis - missing: {', '.join(health_missing)}. Try a clearer photo.")

        allowed_primary_issues = {
            # 🌱 Water & Roots
            "overwatering",
            "underwatering",
            "root_rot",
            "root_stress",
            "poor_drainage",
            "dry_soil",
            "water_imbalance",
            # ☀️ Light
            "low_light",
            "light_excess",
            "direct_sunlight",
            "sun_stress",
            "light_instability",
            # 🌿 Leaves & Growth Symptoms
            "yellow_leaves",
            "leaf_drooping",
            "leaf_curling",
            "leaf_spots",
            "leaf_shedding",
            "leaf_softness",
            "leaf_crisping",
            "leaf_wrinkling",
            # 🌡 Environment & Stress
            "heat_stress",
            "cold_stress",
            "low_humidity",
            "high_humidity",
            "airflow_issues",
            "environmental_change",
            "relocation_stress",
            "air_pollution",
            # 🌸 Flowering-specific
            "bud_drop",
            "early_flower_drop",
            "no_blooming",
            "flowering_cycle_disruption",
            # 🌿 Herbs & Edibles
            "leggy_growth",
            "bolting",
            "loss_of_flavor",
            "slow_edible_growth",
            # 🌴 Trees, Woody & Ferns
            "slow_growth",
            "establishment_stress",
            "fragile_recovery",
        }
        data["health"]["primary_issue"] = self._normalize_primary_issue(
            data["health"].get("primary_issue"),
            issues=data["health"].get("issues", []),
            health_status=data["health"].get("status"),
            health_confidence=data["health"].get("confidence"),
            allowed_primary_issues=allowed_primary_issues,
        )

        allowed_health_status = {"healthy", "stressed", "unhealthy"}
        if data["health"].get("status") not in allowed_health_status:
            raise ValueError("Invalid health.status in analysis. Please try again.")
        allowed_severity = {"low", "medium", "high"}
        if data["health"].get("severity") not in allowed_severity:
            raise ValueError("Invalid health.severity in analysis. Please try again.")
        
        # Validate care object
        if not isinstance(data.get("care"), dict):
            raise ValueError("Invalid care data in analysis. Please try again.")
        
        # Build response model (same as analyze_plant)
        health = PlantHealth(
            status=data["health"]["status"],
            confidence=data["health"]["confidence"],
            primary_issue=data["health"]["primary_issue"],
            severity=data["health"]["severity"],
            issues=data["health"].get("issues", []),
            immediate_actions=data["health"].get("immediate_actions", []),
        )
        
        care = CareSchedule(
            water_frequency=data["care"].get("water_frequency", {}),
            light_preference=data["care"].get("light_preference", "bright_indirect"),
            humidity=data["care"].get("humidity", "medium"),
            fertilizer_frequency=data["care"].get("fertilizer_frequency"),
            indian_climate_tips=data["care"].get("indian_climate_tips", []),
        )

        toxicity = self._parse_toxicity(data)
        placement = self._parse_placement(data)
        
        return PlantAnalysisResponse(
            plant_id=data["plant_id"],
            scientific_name=data["scientific_name"],
            common_name=data["common_name"],
            plant_family=data["plant_family"],
            confidence=data["confidence"],
            health=health,
            care=care,
            toxicity=toxicity,
            placement=placement,
        )
