"""
Feature engineering for Polymarket Trading Bot.

This module creates features from raw market data for TimesFM forecasting:
- Technical indicators (SMA, EMA, RSI, Bollinger Bands)
- Volume-based features
- Time-based features
- Market structure features
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
import talib

logger = logging.getLogger(__name__)


@dataclass
class FeatureSet:
    """Container for engineered features."""
    market_id: str
    timestamp: datetime
    yes_price: float
    no_price: float
    features: Dict[str, float]
    metadata: Dict[str, Any]


class FeatureEngineer:
    """Engineer features from market data for forecasting."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize feature engineer.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Default technical indicator parameters
        self.technical_params = {
            "sma_periods": [12, 24, 48, 168],  # 12h, 24h, 48h, 1 week
            "ema_periods": [6, 12, 24],
            "rsi_period": 14,
            "bb_period": 20,
            "bb_std": 2.0,
            "atr_period": 14
        }
        
        # Volume indicator parameters
        self.volume_params = {
            "volume_sma_periods": [24, 168],  # 1d, 1w
            "volume_ratio_periods": [1, 24]   # current vs 24h average
        }
        
        # Update with config if provided
        if "technical_indicators" in self.config:
            self.technical_params.update(self.config["technical_indicators"])
        if "volume_indicators" in self.config:
            self.volume_params.update(self.config["volume_indicators"])
    
    def create_features_from_prices(
        self, 
        market_id: str, 
        prices: List[Dict[str, Any]],
        current_timestamp: datetime
    ) -> Optional[FeatureSet]:
        """
        Create features from price history.
        
        Args:
            market_id: Market ID
            prices: List of price dictionaries with keys:
                - timestamp: datetime
                - yes_price: float
                - no_price: float
                - yes_volume: float
                - no_volume: float
                - total_volume: float
                - liquidity_usd: float
            current_timestamp: Current timestamp for feature calculation
            
        Returns:
            FeatureSet object or None if insufficient data
        """
        if len(prices) < max(self.technical_params["sma_periods"]):
            logger.warning(f"Insufficient data for market {market_id}: {len(prices)} points")
            return None
        
        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(prices)
        df = df.sort_values("timestamp")
        
        # Get latest price
        latest_price = df.iloc[-1]
        
        # Calculate features
        features = {}
        
        # 1. Price-based features
        features.update(self._calculate_price_features(df))
        
        # 2. Volume-based features
        features.update(self._calculate_volume_features(df))
        
        # 3. Time-based features
        features.update(self._calculate_time_features(df, current_timestamp))
        
        # 4. Market structure features
        features.update(self._calculate_market_structure_features(df))
        
        # 5. Derived probability features
        features.update(self._calculate_probability_features(df))
        
        # Create metadata
        metadata = {
            "num_data_points": len(df),
            "time_range_hours": (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 3600,
            "feature_generation_time": datetime.utcnow().isoformat()
        }
        
        return FeatureSet(
            market_id=market_id,
            timestamp=current_timestamp,
            yes_price=float(latest_price["yes_price"]),
            no_price=float(latest_price["no_price"]),
            features=features,
            metadata=metadata
        )
    
    def _calculate_price_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate price-based technical indicators."""
        features = {}
        
        # Extract price series
        yes_prices = df["yes_price"].values.astype(np.float64)
        no_prices = df["no_price"].values.astype(np.float64)
        mid_prices = (yes_prices + no_prices) / 2
        
        # Simple Moving Averages
        for period in self.technical_params["sma_periods"]:
            if len(yes_prices) >= period:
                sma_yes = talib.SMA(yes_prices, timeperiod=period)[-1]
                sma_no = talib.SMA(no_prices, timeperiod=period)[-1]
                sma_mid = talib.SMA(mid_prices, timeperiod=period)[-1]
                
                features[f"sma_yes_{period}"] = float(sma_yes)
                features[f"sma_no_{period}"] = float(sma_no)
                features[f"sma_mid_{period}"] = float(sma_mid)
                
                # Price deviation from SMA
                features[f"yes_dev_sma_{period}"] = float(yes_prices[-1] - sma_yes)
                features[f"no_dev_sma_{period}"] = float(no_prices[-1] - sma_no)
        
        # Exponential Moving Averages
        for period in self.technical_params["ema_periods"]:
            if len(yes_prices) >= period:
                ema_yes = talib.EMA(yes_prices, timeperiod=period)[-1]
                ema_no = talib.EMA(no_prices, timeperiod=period)[-1]
                
                features[f"ema_yes_{period}"] = float(ema_yes)
                features[f"ema_no_{period}"] = float(ema_no)
        
        # RSI (Relative Strength Index)
        if len(yes_prices) >= self.technical_params["rsi_period"] + 1:
            rsi_yes = talib.RSI(yes_prices, timeperiod=self.technical_params["rsi_period"])[-1]
            rsi_no = talib.RSI(no_prices, timeperiod=self.technical_params["rsi_period"])[-1]
            
            features[f"rsi_yes"] = float(rsi_yes)
            features[f"rsi_no"] = float(rsi_no)
        
        # Bollinger Bands
        if len(yes_prices) >= self.technical_params["bb_period"]:
            bb_upper, bb_middle, bb_lower = talib.BBANDS(
                yes_prices,
                timeperiod=self.technical_params["bb_period"],
                nbdevup=self.technical_params["bb_std"],
                nbdevdn=self.technical_params["bb_std"]
            )
            
            features[f"bb_yes_upper"] = float(bb_upper[-1])
            features[f"bb_yes_middle"] = float(bb_middle[-1])
            features[f"bb_yes_lower"] = float(bb_lower[-1])
            features[f"bb_yes_bandwidth"] = float((bb_upper[-1] - bb_lower[-1]) / bb_middle[-1])
        
        # Average True Range (volatility)
        if len(yes_prices) >= self.technical_params["atr_period"]:
            high = np.maximum(yes_prices, no_prices)
            low = np.minimum(yes_prices, no_prices)
            close = yes_prices  # Using YES price as close
            
            atr = talib.ATR(high, low, close, timeperiod=self.technical_params["atr_period"])[-1]
            features[f"atr"] = float(atr)
            features[f"atr_percent"] = float(atr / yes_prices[-1]) if yes_prices[-1] > 0 else 0.0
        
        # Price changes
        for lookback in [1, 6, 12, 24]:  # 1h, 6h, 12h, 24h changes
            if len(yes_prices) > lookback:
                yes_change = yes_prices[-1] - yes_prices[-lookback-1]
                no_change = no_prices[-1] - no_prices[-lookback-1]
                
                features[f"yes_change_{lookback}h"] = float(yes_change)
                features[f"no_change_{lookback}h"] = float(no_change)
                features[f"yes_return_{lookback}h"] = float(yes_change / yes_prices[-lookback-1]) if yes_prices[-lookback-1] > 0 else 0.0
                features[f"no_return_{lookback}h"] = float(no_change / no_prices[-lookback-1]) if no_prices[-lookback-1] > 0 else 0.0
        
        return features
    
    def _calculate_volume_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate volume-based features."""
        features = {}
        
        # Extract volume series
        yes_volumes = df["yes_volume"].values.astype(np.float64)
        no_volumes = df["no_volume"].values.astype(np.float64)
        total_volumes = df["total_volume"].values.astype(np.float64)
        liquidity = df["liquidity_usd"].values.astype(np.float64)
        
        # Volume SMAs
        for period in self.volume_params["volume_sma_periods"]:
            if len(total_volumes) >= period:
                volume_sma = talib.SMA(total_volumes, timeperiod=period)[-1]
                features[f"volume_sma_{period}"] = float(volume_sma)
                
                # Volume ratio (current vs SMA)
                if volume_sma > 0:
                    features[f"volume_ratio_{period}"] = float(total_volumes[-1] / volume_sma)
        
        # Volume ratios
        for lookback in self.volume_params["volume_ratio_periods"]:
            if len(total_volumes) > lookback:
                current_volume = total_volumes[-1]
                past_volume = total_volumes[-lookback-1] if lookback > 0 else total_volumes[-1]
                
                if past_volume > 0:
                    features[f"volume_ratio_{lookback}h"] = float(current_volume / past_volume)
        
        # YES/NO volume ratio
        if no_volumes[-1] > 0:
            features["yes_no_volume_ratio"] = float(yes_volumes[-1] / no_volumes[-1])
        
        # Volume concentration (current volume / average)
        if len(total_volumes) > 0 and np.mean(total_volumes) > 0:
            features["volume_concentration"] = float(total_volumes[-1] / np.mean(total_volumes))
        
        # Liquidity features
        if len(liquidity) > 0:
            features["current_liquidity"] = float(liquidity[-1])
            
            if len(liquidity) >= 24:  # 24-hour SMA
                liquidity_sma = np.mean(liquidity[-24:])
                features["liquidity_sma_24"] = float(liquidity_sma)
                
                if liquidity_sma > 0:
                    features["liquidity_ratio"] = float(liquidity[-1] / liquidity_sma)
        
        # Volume trend (linear regression slope)
        if len(total_volumes) >= 12:
            x = np.arange(len(total_volumes))
            slope = np.polyfit(x, total_volumes, 1)[0]
            features["volume_trend_slope"] = float(slope)
        
        return features
    
    def _calculate_time_features(self, df: pd.DataFrame, current_timestamp: datetime) -> Dict[str, float]:
        """Calculate time-based features."""
        features = {}
        
        # Time since market creation
        market_start = df["timestamp"].min()
        market_age_hours = (current_timestamp - market_start).total_seconds() / 3600
        features["market_age_hours"] = float(market_age_hours)
        
        # Time to resolution
        # Note: This would need market metadata - placeholder for now
        # features["hours_to_resolution"] = ...
        
        # Time of day and day of week effects
        features["hour_of_day"] = float(current_timestamp.hour)
        features["day_of_week"] = float(current_timestamp.weekday())  # Monday=0
        
        # Weekend flag
        features["is_weekend"] = float(1.0 if current_timestamp.weekday() >= 5 else 0.0)
        
        # Time since last price update
        if len(df) > 0:
            last_update = df["timestamp"].max()
            time_since_update = (current_timestamp - last_update).total_seconds() / 60  # minutes
            features["minutes_since_update"] = float(time_since_update)
        
        return features
    
    def _calculate_market_structure_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate market structure features."""
        features = {}
        
        # Price spread (YES - NO should be close to 1.0 theoretically)
        yes_prices = df["yes_price"].values.astype(np.float64)
        no_prices = df["no_price"].values.astype(np.float64)
        
        spreads = yes_prices + no_prices - 1.0  # Should be 0 in efficient market
        features["current_spread"] = float(spreads[-1])
        features["avg_spread_24h"] = float(np.mean(spreads[-24:])) if len(spreads) >= 24 else 0.0
        features["max_spread_24h"] = float(np.max(spreads[-24:])) if len(spreads) >= 24 else 0.0
        
        # Price correlation between YES and NO
        if len(yes_prices) >= 12:
            correlation = np.corrcoef(yes_prices[-12:], no_prices[-12:])[0, 1]
            features["yes_no_correlation_12h"] = float(correlation)
        
        # Price stability (variance)
        features["yes_price_variance_24h"] = float(np.var(yes_prices[-24:])) if len(yes_prices) >= 24 else 0.0
        features["no_price_variance_24h"] = float(np.var(no_prices[-24:])) if len(no_prices) >= 24 else 0.0
        
        # Mean reversion metrics
        if len(yes_prices) >= 48:
            # Hurst exponent approximation
            lags = range(2, 25)
            tau = [np.std(np.subtract(yes_prices[lag:], yes_prices[:-lag])) for lag in lags]
            poly = np.polyfit(np.log(lags), np.log(tau), 1)
            hurst = poly[0] * 2.0
            features["hurst_exponent"] = float(hurst)
        
        return features
    
    def _calculate_probability_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate derived probability features."""
        features = {}
        
        yes_prices = df["yes_price"].values.astype(np.float64)
        no_prices = df["no_price"].values.astype(np.float64)
        
        # Implied probability features
        features["current_yes_probability"] = float(yes_prices[-1])
        features["current_no_probability"] = float(no_prices[-1])
        
        # Probability changes
        for lookback in [1, 6, 12, 24]:
            if len(yes_prices) > lookback:
                prob_change = yes_prices[-1] - yes_prices[-lookback-1]
                features[f"prob_change_{lookback}h"] = float(prob_change)
                
                # Percentage change
                if yes_prices[-lookback-1] > 0:
                    features[f"prob_pct_change_{lookback}h"] = float(prob_change / yes_prices[-lookback-1])
        
        # Probability momentum
        if len(yes_prices) >= 12:
            # Simple momentum (current - average of last 12)
            momentum = yes_prices[-1] - np.mean(yes_prices[-12:])
            features["prob_momentum_12h"] = float(momentum)
        
        # Probability volatility
        if len(yes_prices) >= 24:
            prob_returns = np.diff(yes_prices[-24:]) / yes_prices[-25:-1]
            features["prob_volatility_24h"] = float(np.std(prob_returns)) if len(prob_returns) > 0 else 0.0
        
        # Fair value indicators (based on efficient market hypothesis)
        # Note: These are simplified - real implementation would be more sophisticated
        features["arbitrage_opportunity"] = float(abs(yes_prices[-1] + no_prices[-1] - 1.0))
        
        return features
    
    def prepare_timesfm_input(
        self, 
        feature_set: FeatureSet,
        history_hours: int = 168  # 1 week
    ) -> np.ndarray:
        """
        Prepare features for TimesFM input.
        
        Args:
            feature_set: FeatureSet object
            history_hours: Number of hours of history to include
            
        Returns:
            Numpy array suitable for TimesFM forecasting
        """
        # TimesFM expects a 1D array of values
        # We need to create a time series from our features
        
        # For now, we'll use the YES price as the primary series
        # In a real implementation, we would have historical features
        
        # Placeholder implementation
        logger.warning("Feature preparation for TimesFM is a placeholder")
        
        # Return a simple array (in real implementation, this would be
        # a properly formatted time series with engineered features)
        return np.array([feature_set.yes_price])
    
    def validate_features(self, features: Dict[str, float]) -> Tuple[bool, List[str]]:
        """
        Validate engineered features.
        
        Args:
            features: Dictionary of features
            
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        
        # Check for NaN or infinite values
        for key, value in features.items():
            if np.isnan(value) or np.isinf(value):
                issues.append(f"Invalid value for {key}: {value}")
        
        # Check for extreme values
        for key in features:
            if "probability" in key or "price" in key:
                if features[key] < 0 or features[key] > 1:
                    issues.append(f"Probability/price out of range for {key}: {features[key]}")
        
        # Check essential features
        essential_features = ["current_yes_probability", "current_no_probability"]
        for feat in essential_features:
            if feat not in features:
                issues.append(f"Missing essential feature: {feat}")
        
        is_valid = len(issues) == 0
        return is_valid, issues


if __name__ == "__main__":
    # Test feature engineering
    import pandas as pd
    from datetime import datetime, timedelta
    
    # Create synthetic price data
    np.random.seed(42)
    n_points = 200
    timestamps = [datetime.utcnow() - timedelta(hours=i) for i in range(n_points)]
    timestamps.reverse()  # Oldest to newest
    
    # Create YES prices with some trend and noise
    base_trend = np.linspace(0.4, 0.6, n_points)
    noise = 0.05 * np.random.randn(n_points)
    yes_prices = base_trend + noise
    yes_prices = np.clip(yes_prices, 0.01, 0.99)
    
    # NO prices should sum to approximately 1 with YES prices
    no_prices = 1.0 - yes_prices + 0.02 * np.random.randn(n_points)  # Add some spread
    no_prices = np.clip(no_prices, 0.01, 0.99)
    
    # Create synthetic data
    prices = []
    for i in range(n_points):
        prices.append({
            "timestamp": timestamps[i],
            "yes_price": float(yes_prices[i]),
            "no_price": float(no_prices[i]),
            "yes_volume": float(1000 + 500 * np.random.rand()),
            "no_volume": float(800 + 400 * np.random.rand()),
            "total_volume": float(1800 + 900 * np.random.rand()),
            "liquidity_usd": float(10000 + 5000 * np.random.rand())
        })
    
    # Test feature engineering
    engineer = FeatureEngineer()
    feature_set = engineer.create_features_from_prices(
        market_id="test_market_001",
        prices=prices,
        current_timestamp=datetime.utcnow()
    )
    
    if feature_set:
        print(f"Generated {len(feature_set.features)} features")
        print(f"YES price: {feature_set.yes_price:.4f}")
        print(f"NO price: {feature_set.no_price:.4f}")
        
        # Show some key features
        key_features = ["sma_yes_24", "rsi_yes", "bb_yes_bandwidth", "atr_percent", 
                       "prob_change_24h", "volume_ratio_24", "market_age_hours"]
        
        print("\nKey features:")
        for key in key_features:
            if key in feature_set.features:
                print(f"  {key}: {feature_set.features[key]:.6f}")
        
        # Validate features
        is_valid, issues = engineer.validate_features(feature_set.features)
        print(f"\nFeature validation: {'VALID' if is_valid else 'INVALID'}")
        if issues:
            print("Issues:")
            for issue in issues:
                print(f"  - {issue}")
    else:
        print("Failed to create features")