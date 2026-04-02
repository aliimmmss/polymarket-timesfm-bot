"""
TimesFM Forecaster for Polymarket Trading Bot.

This module integrates Google's TimesFM model for probabilistic forecasting
of Polymarket prices.
"""

import torch
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import logging
import json
from dataclasses import dataclass
import hashlib
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class ForecastResult:
    """Container for TimesFM forecast results."""
    market_id: str
    forecast_timestamp: datetime
    horizon_hours: int
    point_forecast: np.ndarray  # Median forecast for each horizon point
    quantile_forecast: np.ndarray  # Quantile forecasts shape (horizon, 10)
    confidence_width: float  # Width between 10th and 90th percentiles
    input_features: Dict[str, Any]
    model_version: str
    forecast_id: Optional[str] = None
    
    def __post_init__(self):
        """Generate forecast ID if not provided."""
        if self.forecast_id is None:
            # Create deterministic ID from market_id and timestamp
            base_str = f"{self.market_id}_{self.forecast_timestamp.isoformat()}_{self.horizon_hours}"
            self.forecast_id = hashlib.md5(base_str.encode()).hexdigest()[:16]


class TimesFMForecaster:
    """TimesFM forecasting wrapper for Polymarket prices."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize TimesFM forecaster.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self.model = None
        self.model_loaded = False
        self.model_version = "google/timesfm-2.5-200m-pytorch"
        
        # Forecast configuration
        self.forecast_config = {
            "max_context": 1024,
            "max_horizon": 256,
            "normalize_inputs": True,
            "use_continuous_quantile_head": True,
            "force_flip_invariance": True,
            "infer_is_positive": False,  # Allow negative values for probabilities
            "fix_quantile_crossing": True,
            "per_core_batch_size": 32
        }
        
        # Update with config if provided
        if "forecasting" in self.config:
            self.forecast_config.update(self.config["forecasting"])
        
        # Cache for recent forecasts
        self.forecast_cache: Dict[str, Tuple[datetime, ForecastResult]] = {}
        self.cache_ttl = timedelta(minutes=5)  # 5 minute cache TTL
        
        logger.info(f"Initialized TimesFMForecaster with config: {self.forecast_config}")
    
    def load_model(self):
        """Load TimesFM model from HuggingFace."""
        if self.model_loaded:
            return True
            
        try:
            import timesfm
            
            # Set PyTorch settings
            torch.set_float32_matmul_precision("high")
            
            # Load model
            logger.info(f"Loading TimesFM model: {self.model_version}")
            self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(self.model_version)
            
            # Compile model with forecast config
            logger.info("Compiling TimesFM model...")
            self.model.compile(
                timesfm.ForecastConfig(**self.forecast_config)
            )
            
            self.model_loaded = True
            logger.info("TimesFM model loaded and compiled successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load TimesFM model: {e}")
            self.model_loaded = False
            return False
    
    def prepare_input_data(
        self, 
        price_history: np.ndarray,
        features: Optional[Dict[str, float]] = None
    ) -> np.ndarray:
        """
        Prepare input data for TimesFM forecasting.
        
        TimesFM expects a 1D array of values. We can optionally
        incorporate features through preprocessing.
        
        Args:
            price_history: 1D array of YES prices
            features: Optional dictionary of engineered features
            
        Returns:
            Prepared input array for TimesFM
        """
        # Ensure price history is valid
        if len(price_history) < 32:
            raise ValueError(f"Insufficient data points: {len(price_history)} < 32")
        
        # Clean data (remove NaN, infinite values)
        price_history = np.nan_to_num(price_history, nan=0.5, posinf=0.5, neginf=0.5)
        
        # Clip to valid probability range
        price_history = np.clip(price_history, 0.01, 0.99)
        
        # Optional: Incorporate features through scaling or transformation
        # For now, we just use the raw price history
        # Future: Create multivariate series with engineered features
        
        return price_history.astype(np.float32)
    
    def forecast(
        self,
        market_id: str,
        price_history: np.ndarray,
        horizon_hours: int,
        features: Optional[Dict[str, float]] = None,
        use_cache: bool = True
    ) -> Optional[ForecastResult]:
        """
        Generate forecast using TimesFM.
        
        Args:
            market_id: Market ID
            price_history: Array of historical YES prices
            horizon_hours: Forecast horizon in hours
            features: Optional engineered features
            use_cache: Whether to use cached forecasts
            
        Returns:
            ForecastResult or None if error
        """
        # Check cache
        if use_cache:
            cache_key = self._create_cache_key(market_id, price_history, horizon_hours)
            cached = self.forecast_cache.get(cache_key)
            if cached:
                cached_time, cached_forecast = cached
                if datetime.utcnow() - cached_time < self.cache_ttl:
                    logger.debug(f"Using cached forecast for {market_id}")
                    return cached_forecast
        
        # Ensure model is loaded
        if not self.load_model():
            logger.error("Cannot forecast: TimesFM model not loaded")
            return None
        
        try:
            # Prepare input data
            prepared_input = self.prepare_input_data(price_history, features)
            
            # Generate forecast
            logger.debug(f"Generating forecast for {market_id}, horizon: {horizon_hours}h")
            
            point_forecast, quantile_forecast = self.model.forecast(
                horizon=horizon_hours,
                inputs=[prepared_input]
            )
            
            # Convert to numpy arrays
            point_forecast = point_forecast[0].numpy()  # Shape: (horizon,)
            quantile_forecast = quantile_forecast[0].numpy()  # Shape: (horizon, 10)
            
            # Calculate confidence width (90th - 10th percentile)
            confidence_width = np.mean(quantile_forecast[:, 9] - quantile_forecast[:, 1])
            
            # Create forecast result
            result = ForecastResult(
                market_id=market_id,
                forecast_timestamp=datetime.utcnow(),
                horizon_hours=horizon_hours,
                point_forecast=point_forecast,
                quantile_forecast=quantile_forecast,
                confidence_width=float(confidence_width),
                input_features=features or {},
                model_version=self.model_version
            )
            
            # Cache the result
            if use_cache:
                cache_key = self._create_cache_key(market_id, price_history, horizon_hours)
                self.forecast_cache[cache_key] = (datetime.utcnow(), result)
                # Clean old cache entries
                self._clean_cache()
            
            logger.info(f"Generated forecast for {market_id}: {len(point_forecast)} points, "
                       f"confidence width: {confidence_width:.4f}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error forecasting for market {market_id}: {e}")
            return None
    
    def forecast_multiple(
        self,
        market_histories: Dict[str, np.ndarray],
        horizon_hours: int,
        batch_size: int = 32
    ) -> Dict[str, ForecastResult]:
        """
        Forecast multiple markets in batch.
        
        Args:
            market_histories: Dict mapping market_id to price history
            horizon_hours: Forecast horizon in hours
            batch_size: Batch size for TimesFM
            
        Returns:
            Dict mapping market_id to ForecastResult
        """
        results = {}
        
        # Process in batches
        market_ids = list(market_histories.keys())
        for i in range(0, len(market_ids), batch_size):
            batch_market_ids = market_ids[i:i+batch_size]
            batch_histories = [market_histories[mid] for mid in batch_market_ids]
            
            # Ensure model is loaded
            if not self.load_model():
                logger.error("Cannot forecast: TimesFM model not loaded")
                break
            
            try:
                # Prepare batch inputs
                batch_inputs = []
                for history in batch_histories:
                    prepared = self.prepare_input_data(history)
                    batch_inputs.append(prepared)
                
                # Batch forecast
                point_forecasts, quantile_forecasts = self.model.forecast(
                    horizon=horizon_hours,
                    inputs=batch_inputs
                )
                
                # Process results
                for j, market_id in enumerate(batch_market_ids):
                    if j < len(point_forecasts):
                        point_fc = point_forecasts[j].numpy()
                        quantile_fc = quantile_forecasts[j].numpy()
                        
                        confidence_width = np.mean(quantile_fc[:, 9] - quantile_fc[:, 1])
                        
                        result = ForecastResult(
                            market_id=market_id,
                            forecast_timestamp=datetime.utcnow(),
                            horizon_hours=horizon_hours,
                            point_forecast=point_fc,
                            quantile_forecast=quantile_fc,
                            confidence_width=float(confidence_width),
                            input_features={},
                            model_version=self.model_version
                        )
                        
                        results[market_id] = result
                
                logger.info(f"Batch forecast completed: {len(batch_market_ids)} markets")
                
            except Exception as e:
                logger.error(f"Error in batch forecasting: {e}")
                # Try individual forecasts for failed batch
                for market_id in batch_market_ids:
                    try:
                        result = self.forecast(
                            market_id=market_id,
                            price_history=market_histories[market_id],
                            horizon_hours=horizon_hours,
                            use_cache=False
                        )
                        if result:
                            results[market_id] = result
                    except Exception as e2:
                        logger.error(f"Failed individual forecast for {market_id}: {e2}")
        
        return results
    
    def get_forecast_at_horizon(
        self,
        forecast_result: ForecastResult,
        horizon_index: int
    ) -> Tuple[float, float, float]:
        """
        Get forecast values at specific horizon index.
        
        Args:
            forecast_result: ForecastResult object
            horizon_index: Index in forecast horizon (0-based)
            
        Returns:
            Tuple of (median, lower_80, upper_80) forecasts
        """
        if horizon_index >= len(forecast_result.point_forecast):
            raise ValueError(f"Horizon index {horizon_index} out of range "
                           f"(max {len(forecast_result.point_forecast)-1})")
        
        median = float(forecast_result.point_forecast[horizon_index])
        lower_80 = float(forecast_result.quantile_forecast[horizon_index, 1])  # 10th percentile
        upper_80 = float(forecast_result.quantile_forecast[horizon_index, 9])  # 90th percentile
        
        return median, lower_80, upper_80
    
    def evaluate_forecast(
        self,
        forecast_result: ForecastResult,
        actual_prices: np.ndarray
    ) -> Dict[str, float]:
        """
        Evaluate forecast accuracy against actual prices.
        
        Args:
            forecast_result: ForecastResult object
            actual_prices: Array of actual prices corresponding to forecast horizon
            
        Returns:
            Dictionary of evaluation metrics
        """
        if len(actual_prices) != len(forecast_result.point_forecast):
            raise ValueError(f"Actual prices length {len(actual_prices)} doesn't match "
                           f"forecast length {len(forecast_result.point_forecast)}")
        
        forecast = forecast_result.point_forecast
        quantiles = forecast_result.quantile_forecast
        
        # Calculate metrics
        errors = actual_prices - forecast
        abs_errors = np.abs(errors)
        
        metrics = {
            "mae": float(np.mean(abs_errors)),  # Mean Absolute Error
            "rmse": float(np.sqrt(np.mean(errors ** 2))),  # Root Mean Square Error
            "mape": float(np.mean(abs_errors / np.maximum(actual_prices, 0.01)) * 100),  # Mean Absolute Percentage Error
            "bias": float(np.mean(errors)),  # Forecast bias
        }
        
        # Probability interval coverage
        lower_80 = quantiles[:, 1]  # 10th percentile
        upper_80 = quantiles[:, 9]  # 90th percentile
        
        within_80 = np.logical_and(actual_prices >= lower_80, actual_prices <= upper_80)
        metrics["coverage_80"] = float(np.mean(within_80) * 100)  # Percentage within 80% PI
        
        # Sharpness (width of prediction intervals)
        metrics["sharpness_80"] = float(np.mean(upper_80 - lower_80))
        
        # Calibration score (closer to 0.8 is better for 80% PI)
        metrics["calibration_score"] = float(abs(metrics["coverage_80"] / 100 - 0.8))
        
        logger.debug(f"Forecast evaluation for {forecast_result.market_id}: "
                    f"MAE={metrics['mae']:.4f}, Coverage={metrics['coverage_80']:.1f}%")
        
        return metrics
    
    def _create_cache_key(
        self, 
        market_id: str, 
        price_history: np.ndarray, 
        horizon_hours: int
    ) -> str:
        """Create cache key for forecast."""
        # Use hash of recent price history
        recent_prices = price_history[-100:] if len(price_history) >= 100 else price_history
        price_hash = hashlib.md5(recent_prices.tobytes()).hexdigest()[:8]
        
        return f"{market_id}_{price_hash}_{horizon_hours}"
    
    def _clean_cache(self):
        """Remove expired cache entries."""
        now = datetime.utcnow()
        expired_keys = [
            key for key, (timestamp, _) in self.forecast_cache.items()
            if now - timestamp > self.cache_ttl
        ]
        
        for key in expired_keys:
            del self.forecast_cache[key]
        
        if expired_keys:
            logger.debug(f"Cleaned {len(expired_keys)} expired cache entries")
    
    def save_forecast(self, forecast_result: ForecastResult, filepath: str):
        """Save forecast result to JSON file."""
        data = {
            "market_id": forecast_result.market_id,
            "forecast_id": forecast_result.forecast_id,
            "forecast_timestamp": forecast_result.forecast_timestamp.isoformat(),
            "horizon_hours": forecast_result.horizon_hours,
            "point_forecast": forecast_result.point_forecast.tolist(),
            "quantile_forecast": forecast_result.quantile_forecast.tolist(),
            "confidence_width": forecast_result.confidence_width,
            "model_version": forecast_result.model_version,
            "input_features": forecast_result.input_features
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.debug(f"Saved forecast to {filepath}")
    
    @staticmethod
    def load_forecast(filepath: str) -> Optional[ForecastResult]:
        """Load forecast result from JSON file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            return ForecastResult(
                market_id=data["market_id"],
                forecast_timestamp=datetime.fromisoformat(data["forecast_timestamp"]),
                horizon_hours=data["horizon_hours"],
                point_forecast=np.array(data["point_forecast"]),
                quantile_forecast=np.array(data["quantile_forecast"]),
                confidence_width=data["confidence_width"],
                input_features=data["input_features"],
                model_version=data["model_version"],
                forecast_id=data.get("forecast_id")
            )
        except Exception as e:
            logger.error(f"Error loading forecast from {filepath}: {e}")
            return None


if __name__ == "__main__":
    # Test the forecaster
    import numpy as np
    from datetime import datetime
    
    # Create synthetic price data
    np.random.seed(42)
    n_points = 200
    
    # Create YES prices with trend and seasonality
    t = np.linspace(0, 10, n_points)
    trend = 0.002 * t
    seasonality = 0.1 * np.sin(2 * np.pi * t / 5)
    noise = 0.05 * np.random.randn(n_points)
    
    yes_prices = 0.5 + trend + seasonality + noise
    yes_prices = np.clip(yes_prices, 0.01, 0.99)
    
    # Initialize forecaster
    forecaster = TimesFMForecaster()
    
    # Generate forecast
    forecast = forecaster.forecast(
        market_id="test_market_001",
        price_history=yes_prices,
        horizon_hours=24,
        features={"volume_ratio": 1.5, "rsi": 45.0}
    )
    
    if forecast:
        print(f"Forecast generated for {forecast.market_id}")
        print(f"Horizon: {forecast.horizon_hours} hours")
        print(f"Point forecast shape: {forecast.point_forecast.shape}")
        print(f"Quantile forecast shape: {forecast.quantile_forecast.shape}")
        print(f"Confidence width: {forecast.confidence_width:.4f}")
        
        # Get forecast at specific horizons
        horizons = [0, 5, 11, 23]  # 1h, 6h, 12h, 24h
        print("\nForecast at specific horizons:")
        for h in horizons:
            if h < len(forecast.point_forecast):
                median, lower, upper = forecaster.get_forecast_at_horizon(forecast, h)
                print(f"  Hour {h+1}: Median={median:.4f}, 80% PI=[{lower:.4f}, {upper:.4f}]")
        
        # Save forecast
        forecaster.save_forecast(forecast, "test_forecast.json")
        
        # Load forecast
        loaded = TimesFMForecaster.load_forecast("test_forecast.json")
        if loaded:
            print(f"\nLoaded forecast ID: {loaded.forecast_id}")
    else:
        print("Failed to generate forecast")