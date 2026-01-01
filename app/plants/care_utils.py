"""Care schedule utilities for parsing and converting care data."""

import re
from typing import Dict, Optional


def parse_frequency_to_days(frequency_str: str) -> int:
    """
    Parse a frequency string like "every 2 days" or "twice a week" to integer days.
    
    Examples:
        "every 2 days" -> 2
        "every 3-4 days" -> 3 (use lower bound)
        "twice a week" -> 3
        "once a week" -> 7
        "weekly" -> 7
        "daily" -> 1
        "every other day" -> 2
    """
    if not frequency_str:
        return 3  # Default
    
    freq = frequency_str.lower().strip()
    
    # Direct matches
    if freq in ["daily", "every day"]:
        return 1
    if freq in ["every other day", "alternate days"]:
        return 2
    if freq in ["weekly", "once a week", "once weekly"]:
        return 7
    if freq in ["twice a week", "2x per week"]:
        return 3
    if freq in ["three times a week", "3x per week"]:
        return 2
    
    # Pattern: "every X days" or "every X-Y days"
    match = re.search(r"every\s+(\d+)(?:\s*-\s*\d+)?\s*days?", freq)
    if match:
        return int(match.group(1))
    
    # Pattern: "X days" at start
    match = re.search(r"^(\d+)\s*days?", freq)
    if match:
        return int(match.group(1))
    
    # Pattern: just a number
    match = re.search(r"(\d+)", freq)
    if match:
        return int(match.group(1))
    
    # Default fallback
    return 3


def convert_care_schedule_to_stored(care_schedule: Dict) -> Dict:
    """
    Convert OpenAI's CareSchedule (with string frequencies) to CareScheduleStored (with int days).
    
    Input: {"water_frequency": {"summer": "every 2 days", ...}, "light_preference": "bright_indirect", ...}
    Output: {"watering": {"summer": 2, ...}, "light_preference": "bright_indirect", ...}
    """
    if not care_schedule:
        return None
    
    water_freq = care_schedule.get("water_frequency", {})
    
    watering = {
        "summer": parse_frequency_to_days(water_freq.get("summer", "every 3 days")),
        "monsoon": parse_frequency_to_days(water_freq.get("monsoon", "every 5 days")),
        "winter": parse_frequency_to_days(water_freq.get("winter", "every 7 days")),
    }
    
    return {
        "watering": watering,
        "light_preference": care_schedule.get("light_preference", "bright_indirect"),
        "humidity": care_schedule.get("humidity", "medium"),
        "indian_climate_tips": care_schedule.get("indian_climate_tips", []),
    }
