"""OpenAI service for plant identification and health analysis."""

import re
from typing import Optional, List, Dict
from openai import AsyncOpenAI
from app.core.config import get_settings
from app.core.aws import S3Service
from app.plants.models import PlantAnalysisResponse, PlantHealth, CareSchedule


settings = get_settings()


class OpenAIService:
    """Handles OpenAI API interactions for plant analysis."""
    
    _instance: "OpenAIService" = None
    
    def __new__(cls):
        """Singleton pattern for OpenAI client."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            cls._instance.model = settings.OPENAI_MODEL
        return cls._instance
    
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

Analyze this plant photo and return a JSON object with the following structure:
{{
    "plant_id": "lowercase_underscore_name (e.g., monstera_deliciosa)",
    "scientific_name": "Scientific name",
    "common_name": "Common name used in India",
    "confidence": 0.0 to 1.0,
    "health": {{
        "status": "healthy" or "stressed" or "unhealthy",
        "confidence": 0.0 to 1.0,
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
    }}
}}

Consider Indian climate challenges: intense heat (40°C+), monsoons, humidity spikes, dust, pollution, and harsh afternoon sun.

Return ONLY the JSON object, no other text."""

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
            # If it looks like an S3 key (no protocol), generate presigned URL
            final_url = image_url
            if not image_url.startswith("http"):
                 try:
                     s3 = S3Service()
                     final_url = s3.generate_presigned_get_url(image_url)
                 except Exception:
                     pass # Fallback or keep properly formatted url
            
            image_content = {
                "type": "image_url",
                "image_url": {
                    "url": final_url,
                    "detail": "high"
                }
            }

        try:
            response = await self.client.chat.completions.create(
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
        
        # Build response model
        health = PlantHealth(
            status=data["health"]["status"],
            confidence=data["health"]["confidence"],
            issues=data["health"].get("issues", []),
            immediate_actions=data["health"].get("immediate_actions", []),
        )
        
        care = CareSchedule(
            water_frequency=data["care"]["water_frequency"],
            light_preference=data["care"]["light_preference"],
            humidity=data["care"]["humidity"],
            fertilizer_frequency=data["care"].get("fertilizer_frequency"),
            indian_climate_tips=data["care"].get("indian_climate_tips", []),
        )
        
        return PlantAnalysisResponse(
            plant_id=data["plant_id"],
            scientific_name=data["scientific_name"],
            common_name=data["common_name"],
            confidence=data["confidence"],
            health=health,
            care=care,
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

Count all visible individual plants. Return ONLY the JSON, no other text."""


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
            final_url = image_url
            if not image_url.startswith("http"):
                 try:
                     s3 = S3Service()
                     final_url = s3.generate_presigned_get_url(image_url)
                 except Exception:
                     pass
            
            image_content = {
                "type": "image_url",
                "image_url": {
                    "url": final_url,
                    "detail": "high"
                }
            }

        try:
            response = await self.client.chat.completions.create(
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

Analyze this plant image (cropped from a larger photo) and return a JSON object:
{{
    "plant_id": "lowercase_underscore_name (e.g., monstera_deliciosa)",
    "scientific_name": "Scientific name",
    "common_name": "Common name used in India",
    "confidence": 0.0 to 1.0,
    "health": {{
        "status": "healthy" or "stressed" or "unhealthy",
        "confidence": 0.0 to 1.0,
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
    }}
}}

Consider Indian climate challenges: intense heat (40°C+), monsoons, humidity, dust, and pollution.

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
            response = await self.client.chat.completions.create(
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

        
        # Build response model (same as analyze_plant)
        health = PlantHealth(
            status=data["health"]["status"],
            confidence=data["health"]["confidence"],
            issues=data["health"].get("issues", []),
            immediate_actions=data["health"].get("immediate_actions", []),
        )
        
        care = CareSchedule(
            water_frequency=data["care"]["water_frequency"],
            light_preference=data["care"]["light_preference"],
            humidity=data["care"]["humidity"],
            fertilizer_frequency=data["care"].get("fertilizer_frequency"),
            indian_climate_tips=data["care"].get("indian_climate_tips", []),
        )
        
        return PlantAnalysisResponse(
            plant_id=data["plant_id"],
            scientific_name=data["scientific_name"],
            common_name=data["common_name"],
            confidence=data["confidence"],
            health=health,
            care=care,
        )

