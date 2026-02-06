"""
Notification Content Templates

This module contains all notification message templates for the Vatisha app.
Centralizing content here allows easy modification of notification copy
without changing business logic.

All templates use f-string formatting with named placeholders.
"""

from typing import Optional


class WaterReminderContent:
    """
    Water reminder notification content templates.
    
    Message escalation follows this pattern:
    - Day 1: Gentle, benefit-focused
    - Day 2: Friendly persistence
    - Day 3: Slight urgency
    - Day 4: More direct
    - Day 5: Final gentle check-in (last push)
    - Day 6+: In-app only, no push
    """
    
    # -------------------------------------------------------------------------
    # Titles
    # -------------------------------------------------------------------------
    
    TITLE_DEFAULT = "💧 Gentle reminder"
    TITLE_FINAL = "💧 Final check-in"
    
    # -------------------------------------------------------------------------
    # Single Plant Messages (by day)
    # -------------------------------------------------------------------------
    
    @staticmethod
    def single_plant_day_1(plant_name: str) -> str:
        """Day 1: Gentle, benefit-focused message."""
        return f"Your {plant_name} would benefit from watering today."
    
    @staticmethod
    def single_plant_day_2(plant_name: str) -> str:
        """Day 2: Friendly persistence."""
        return f"Your {plant_name} is still waiting for some water."
    
    @staticmethod
    def single_plant_day_3(plant_name: str) -> str:
        """Day 3: Slight urgency."""
        return f"Your {plant_name} could really use some water today."
    
    @staticmethod
    def single_plant_day_4(plant_name: str) -> str:
        """Day 4: More direct."""
        return f"Your {plant_name} needs watering — it's been a few days."
    
    @staticmethod
    def single_plant_day_5(plant_name: str) -> str:
        """Day 5: Final gentle check-in (last push notification)."""
        return f"Watering still pending for {plant_name}."
    
    @staticmethod
    def single_plant_message(plant_name: str, reminder_day: int) -> str:
        """
        Get the appropriate message for a single plant based on reminder day.
        
        Args:
            plant_name: Name of the plant to include in message.
            reminder_day: Which day of the reminder sequence (1-5).
            
        Returns:
            Formatted message string.
        """
        messages = {
            1: WaterReminderContent.single_plant_day_1,
            2: WaterReminderContent.single_plant_day_2,
            3: WaterReminderContent.single_plant_day_3,
            4: WaterReminderContent.single_plant_day_4,
            5: WaterReminderContent.single_plant_day_5,
        }
        # Default to day 5 message for any day beyond 5
        message_func = messages.get(reminder_day, WaterReminderContent.single_plant_day_5)
        return message_func(plant_name)
    
    # -------------------------------------------------------------------------
    # Multiple Plants (Batched) Messages
    # -------------------------------------------------------------------------
    
    @staticmethod
    def multiple_plants_day_1(primary_plant: str, other_count: int, capped: bool = False) -> str:
        """Day 1: Gentle batched message."""
        suffix = "+" if capped else ""
        return f"Your {primary_plant} and {other_count}{suffix} other plants would benefit from watering today."
    
    @staticmethod
    def multiple_plants_day_2(primary_plant: str, other_count: int, capped: bool = False) -> str:
        """Day 2: Friendly persistence batched."""
        suffix = "+" if capped else ""
        return f"Your {primary_plant} and {other_count}{suffix} other plants are still waiting for water."
    
    @staticmethod
    def multiple_plants_day_3(primary_plant: str, other_count: int, capped: bool = False) -> str:
        """Day 3: Slight urgency batched."""
        suffix = "+" if capped else ""
        return f"Your {primary_plant} and {other_count}{suffix} other plants could really use some water."
    
    @staticmethod
    def multiple_plants_day_4(primary_plant: str, other_count: int, capped: bool = False) -> str:
        """Day 4: More direct batched."""
        suffix = "+" if capped else ""
        return f"Your {primary_plant} and {other_count}{suffix} other plants need watering."
    
    @staticmethod
    def multiple_plants_day_5(primary_plant: str, other_count: int, capped: bool = False) -> str:
        """Day 5: Final check-in batched."""
        suffix = "+" if capped else ""
        return f"Watering still pending for {primary_plant} and {other_count}{suffix} other plants."
    
    @staticmethod
    def multiple_plants_message(
        primary_plant: str, 
        other_count: int, 
        reminder_day: int,
        capped: bool = False
    ) -> str:
        """
        Get the appropriate message for multiple plants based on reminder day.
        
        Args:
            primary_plant: Name of the most overdue plant (shown first).
            other_count: Number of additional plants needing water.
            reminder_day: Which day of the reminder sequence (1-5).
            capped: Whether the count was capped (shows "5+" instead of actual number).
            
        Returns:
            Formatted message string.
        """
        messages = {
            1: WaterReminderContent.multiple_plants_day_1,
            2: WaterReminderContent.multiple_plants_day_2,
            3: WaterReminderContent.multiple_plants_day_3,
            4: WaterReminderContent.multiple_plants_day_4,
            5: WaterReminderContent.multiple_plants_day_5,
        }
        message_func = messages.get(reminder_day, WaterReminderContent.multiple_plants_day_5)
        return message_func(primary_plant, other_count, capped)
    
    @staticmethod
    def get_title(reminder_day: int) -> str:
        """
        Get notification title based on reminder day.
        
        Args:
            reminder_day: Which day of the reminder sequence (1-5).
            
        Returns:
            Title string with emoji.
        """
        if reminder_day >= 5:
            return WaterReminderContent.TITLE_FINAL
        return WaterReminderContent.TITLE_DEFAULT
    
    # -------------------------------------------------------------------------
    # Post-Action Feedback (shown after user marks plant as watered)
    # -------------------------------------------------------------------------
    
    @staticmethod
    def action_confirmed(plant_name: str) -> str:
        """Message shown after user taps 'Watered' button."""
        return f"{plant_name} care logged."
    
    @staticmethod
    def action_confirmed_all() -> str:
        """Message shown after user taps 'Mark all watered'."""
        return "All plants marked as watered."
    
    # -------------------------------------------------------------------------
    # Snooze Options
    # -------------------------------------------------------------------------
    
    SNOOZE_OPTION_4_HOURS = "In 4 hours"
    SNOOZE_OPTION_TOMORROW = "Tomorrow morning"
    
    @staticmethod
    def get_snooze_options():
        """
        Get available snooze options.
        
        Returns:
            List of snooze option dictionaries with id, label, and optional hours.
        """
        return [
            {"id": "4h", "label": WaterReminderContent.SNOOZE_OPTION_4_HOURS, "hours": 4},
            {"id": "tomorrow", "label": WaterReminderContent.SNOOZE_OPTION_TOMORROW, "hours": None},
        ]
    
    # -------------------------------------------------------------------------
    # Button Labels
    # -------------------------------------------------------------------------
    
    BUTTON_WATER = "Water"
    BUTTON_WATERED = "Watered"
    BUTTON_LATER = "Later"
    BUTTON_VIEW_PLANTS = "View plants"
    BUTTON_MARK_ALL_WATERED = "Mark all as watered"


class HealthAlertContent:
    """
    Health alert notification content templates.
    
    Used when plant health analysis detects issues.
    """
    
    TITLE_STRESSED = "🌿 Plant needs attention"
    TITLE_UNHEALTHY = "⚠️ Plant health alert"
    
    @staticmethod
    def stressed_message(plant_name: str) -> str:
        """Message for stressed plant detection."""
        return f"Your {plant_name} is showing signs of stress. Tap to see what's happening."
    
    @staticmethod
    def unhealthy_message(plant_name: str) -> str:
        """Message for unhealthy plant detection."""
        return f"Your {plant_name} needs some care. We've identified a few things to check."


class AchievementContent:
    """
    Achievement and milestone notification content templates.
    """
    
    TITLE_STREAK = "🔥 Streak milestone!"
    TITLE_ACHIEVEMENT = "🏆 Achievement unlocked!"
    
    @staticmethod
    def streak_message(days: int) -> str:
        """Message for watering streak milestone."""
        return f"Amazing! You've maintained a {days}-day watering streak."
    
    @staticmethod
    def achievement_message(achievement_name: str) -> str:
        """Message for unlocked achievement."""
        return f"You've earned the '{achievement_name}' badge!"


class WeatherAlertContent:
    """
    Weather-based notification content templates.
    """
    
    TITLE_HEAT = "☀️ Heat wave incoming"
    TITLE_COLD = "❄️ Cold weather alert"
    TITLE_RAIN = "🌧️ Rainy days ahead"
    
    @staticmethod
    def heat_message(plant_count: int) -> str:
        """Message for heat wave alert."""
        if plant_count == 1:
            return "High temperatures expected. Your plant may need extra water."
        return f"High temperatures expected. Your {plant_count} plants may need extra water."
    
    @staticmethod
    def cold_message() -> str:
        """Message for cold weather alert."""
        return "Cold weather ahead. Consider moving sensitive plants indoors."
    
    @staticmethod
    def rain_message() -> str:
        """Message for rainy weather alert."""
        return "Rain expected this week. You may be able to skip watering outdoor plants."
