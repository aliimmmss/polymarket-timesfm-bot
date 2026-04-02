"""
Data collection module for Polymarket Trading Bot.

This module handles:
- Fetching data from Polymarket API
- Storing data in PostgreSQL database
- Feature engineering for forecasting
- Real-time data streaming
"""

from .polymarket_client import PolymarketClient
from .data_fetcher import DataFetcher
from .data_store import DataStore
from .feature_engineering import FeatureEngineer

__all__ = ["PolymarketClient", "DataFetcher", "DataStore", "FeatureEngineer"]