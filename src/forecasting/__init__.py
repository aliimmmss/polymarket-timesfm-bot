"""
Forecasting module for Polymarket Trading Bot.

This module handles:
- TimesFM model integration and forecasting
- Signal generation from forecasts
- Forecast evaluation and validation
"""

from .timesfm_forecaster import TimesFMForecaster
from .signal_generator import SignalGenerator
from .forecast_evaluator import ForecastEvaluator

__all__ = ["TimesFMForecaster", "SignalGenerator", "ForecastEvaluator"]