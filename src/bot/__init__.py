"""
Bot module for Polymarket Trading Bot.

This module handles:
- Main bot orchestration
- Scheduling and task management
- Configuration management
- Logging setup
"""

from .main_bot import PolymarketBot
from .scheduler import BotScheduler
from .config_manager import ConfigManager

__all__ = ["PolymarketBot", "BotScheduler", "ConfigManager"]