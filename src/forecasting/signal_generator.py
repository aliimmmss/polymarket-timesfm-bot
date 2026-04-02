"""
Signal generation for Polymarket Trading Bot.

This module converts TimesFM forecasts into trading signals:
- Buy/Sell signals based on forecast vs market price discrepancies
- Position sizing based on forecast confidence
- Risk-adjusted signal scoring
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import numpy as np
import logging
from dataclasses import dataclass
from enum import Enum

from .timesfm_forecaster import ForecastResult

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Types of trading signals."""
    STRONG_BUY = "STRONG_BUY"
    MODERATE_BUY = "MODERATE_BUY"
    WEAK_BUY = "WEAK_BUY"
    NEUTRAL = "NEUTRAL"
    WEAK_SELL = "WEAK_SELL"
    MODERATE_SELL = "MODERATE_SELL"
    STRONG_SELL = "STRONG_SELL"
    
    @property
    def direction(self):
        """Get signal direction (-1 for sell, 0 for neutral, 1 for buy)."""
        if "BUY" in self.value:
            return 1
        elif "SELL" in self.value:
            return -1
        else:
            return 0
    
    @property
    def strength(self):
        """Get signal strength (0-1)."""
        if "STRONG" in self.value:
            return 0.9
        elif "MODERATE" in self.value:
            return 0.6
        elif "WEAK" in self.value:
            return 0.3
        else:
            return 0.0


@dataclass
class TradingSignal:
    """Container for a trading signal."""
    market_id: str
    signal_type: SignalType
    timestamp: datetime
    forecast_horizon: int  # Hours ahead
    current_price: float
    forecasted_price: float
    forecast_confidence: float  # 0-1, higher = more confident
    deviation_pct: float  # Percentage deviation from forecast
    confidence_width: float  # Width of prediction interval
    signal_score: float  # Composite score (0-1)
    position_size_pct: float  # Recommended position size (% of portfolio)
    entry_logic: str  # Description of why this signal was generated
    metadata: Dict[str, Any]
    
    def __post_init__(self):
        """Validate signal parameters."""
        if not 0 <= self.signal_score <= 1:
            raise ValueError(f"Signal score must be between 0 and 1, got {self.signal_score}")
        
        if not 0 <= self.position_size_pct <= 1:
            raise ValueError(f"Position size must be between 0 and 1, got {self.position_size_pct}")


class SignalGenerator:
    """Generate trading signals from TimesFM forecasts."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize signal generator.
        
        Args:
            config: Configuration dictionary with signal parameters
        """
        self.config = config or {}
        
        # Default signal parameters
        self.signal_params = {
            # Probability mispricing strategy
            "probability_mispricing": {
                "min_deviation": 0.02,  # Minimum 2% deviation from forecast
                "confidence_threshold": 0.8,  # Minimum forecast confidence
                "max_confidence_width": 0.05,  # Maximum width of 80% PI
                "horizon_preference": [6, 12, 24],  # Preferred forecast horizons
                "volume_ratio_min": 1.2,  # Minimum volume ratio (current/avg)
            },
            
            # Convergence trading strategy
            "convergence_trading": {
                "min_deviation": 0.03,  # Minimum 3% deviation
                "days_to_resolution_range": [7, 60],  # 1 week to 2 months
                "convergence_trend_required": True,
                "liquidity_score_min": 0.7,
            },
            
            # Signal scoring weights
            "scoring_weights": {
                "deviation_magnitude": 0.4,
                "forecast_confidence": 0.3,
                "market_liquidity": 0.15,
                "time_to_resolution": 0.15,
            },
            
            # Position sizing
            "position_sizing": {
                "base_size": 0.05,  # 5% base position
                "max_size": 0.10,  # 10% maximum
                "min_size": 0.01,  # 1% minimum
                "confidence_multiplier": 2.0,  # Double for high confidence
                "liquidity_discount": 0.5,  # Reduce for low liquidity
            },
        }
        
        # Update with config if provided
        if "strategies" in self.config:
            for strategy in self.signal_params.keys():
                if strategy in self.config["strategies"]:
                    self.signal_params[strategy].update(self.config["strategies"][strategy])
        
        logger.info(f"Initialized SignalGenerator with {len(self.signal_params)} strategies")
    
    def generate_signal(
        self,
        market_id: str,
        forecast_result: ForecastResult,
        current_price: float,
        market_features: Dict[str, float],
        strategy: str = "probability_mispricing"
    ) -> Optional[TradingSignal]:
        """
        Generate trading signal from forecast.
        
        Args:
            market_id: Market ID
            forecast_result: TimesFM forecast result
            current_price: Current YES price
            market_features: Dictionary of market features
            strategy: Trading strategy to use
            
        Returns:
            TradingSignal or None if no signal
        """
        if strategy not in self.signal_params:
            logger.error(f"Unknown strategy: {strategy}")
            return None
        
        # Get strategy parameters
        params = self.signal_params[strategy]
        
        # Calculate forecast deviation
        forecast_horizon = self._select_forecast_horizon(forecast_result, params)
        if forecast_horizon is None:
            return None
        
        forecasted_price = forecast_result.point_forecast[forecast_horizon]
        deviation_pct = (forecasted_price - current_price) / current_price
        
        # Calculate forecast confidence (inverse of confidence width)
        # Smaller width = higher confidence
        max_allowed_width = params.get("max_confidence_width", 0.05)
        if forecast_result.confidence_width > max_allowed_width:
            logger.debug(f"Forecast confidence too low: width={forecast_result.confidence_width:.4f} "
                        f"> {max_allowed_width}")
            return None
        
        forecast_confidence = max(0, 1 - (forecast_result.confidence_width / max_allowed_width))
        
        # Check minimum deviation requirement
        min_deviation = params.get("min_deviation", 0.02)
        if abs(deviation_pct) < min_deviation:
            logger.debug(f"Deviation too small: {deviation_pct:.4f} < {min_deviation}")
            return None
        
        # Check additional strategy-specific conditions
        if not self._check_strategy_conditions(strategy, market_features, params):
            logger.debug(f"Strategy conditions not met for {strategy}")
            return None
        
        # Generate signal type based on deviation
        signal_type = self._determine_signal_type(deviation_pct, forecast_confidence)
        
        # Calculate signal score
        signal_score = self._calculate_signal_score(
            deviation_pct=deviation_pct,
            forecast_confidence=forecast_confidence,
            market_features=market_features,
            strategy=strategy
        )
        
        # Calculate position size
        position_size = self._calculate_position_size(
            signal_score=signal_score,
            signal_type=signal_type,
            market_features=market_features
        )
        
        # Generate entry logic description
        entry_logic = self._generate_entry_logic(
            strategy=strategy,
            deviation_pct=deviation_pct,
            forecast_horizon=forecast_horizon,
            confidence_width=forecast_result.confidence_width
        )
        
        # Create metadata
        metadata = {
            "strategy": strategy,
            "forecast_horizon_index": forecast_horizon,
            "forecast_id": forecast_result.forecast_id,
            "market_features": market_features,
            "signal_generation_time": datetime.utcnow().isoformat()
        }
        
        signal = TradingSignal(
            market_id=market_id,
            signal_type=signal_type,
            timestamp=datetime.utcnow(),
            forecast_horizon=forecast_horizon + 1,  # Convert to 1-based
            current_price=current_price,
            forecasted_price=forecasted_price,
            forecast_confidence=forecast_confidence,
            deviation_pct=deviation_pct,
            confidence_width=forecast_result.confidence_width,
            signal_score=signal_score,
            position_size_pct=position_size,
            entry_logic=entry_logic,
            metadata=metadata
        )
        
        logger.info(f"Generated {signal_type.value} signal for {market_id}: "
                   f"score={signal_score:.2f}, size={position_size:.2%}")
        
        return signal
    
    def _select_forecast_horizon(
        self, 
        forecast_result: ForecastResult, 
        params: Dict[str, Any]
    ) -> Optional[int]:
        """
        Select the best forecast horizon to use.
        
        Args:
            forecast_result: Forecast result
            params: Strategy parameters
            
        Returns:
            Horizon index or None if no suitable horizon
        """
        preferred_horizons = params.get("horizon_preference", [6, 12, 24])
        
        # Convert preferred horizons to indices (0-based)
        available_horizons = list(range(len(forecast_result.point_forecast)))
        
        # Find the first preferred horizon that's available
        for preferred in preferred_horizons:
            # Convert hour to index (hour-1 because forecast_horizon is hours ahead)
            idx = preferred - 1
            if 0 <= idx < len(available_horizons):
                return idx
        
        # If no preferred horizon available, use the middle one
        if available_horizons:
            return len(available_horizons) // 2
        
        return None
    
    def _check_strategy_conditions(
        self, 
        strategy: str, 
        market_features: Dict[str, float], 
        params: Dict[str, Any]
    ) -> bool:
        """Check strategy-specific conditions."""
        if strategy == "probability_mispricing":
            # Check volume ratio
            volume_ratio_min = params.get("volume_ratio_min", 1.2)
            volume_ratio = market_features.get("volume_ratio_24", 1.0)
            
            if volume_ratio < volume_ratio_min:
                logger.debug(f"Volume ratio too low: {volume_ratio:.2f} < {volume_ratio_min}")
                return False
            
            # Check market age (minimum 24 hours)
            market_age = market_features.get("market_age_hours", 0)
            if market_age < 24:
                logger.debug(f"Market too new: {market_age:.1f}h < 24h")
                return False
            
        elif strategy == "convergence_trading":
            # Check days to resolution
            days_range = params.get("days_to_resolution_range", [7, 60])
            days_to_resolution = market_features.get("days_to_resolution", 365)  # Default if not available
            
            if not (days_range[0] <= days_to_resolution <= days_range[1]):
                logger.debug(f"Days to resolution out of range: {days_to_resolution}d")
                return False
            
            # Check convergence trend
            if params.get("convergence_trend_required", True):
                prob_change = market_features.get("prob_change_24h", 0)
                forecast_deviation = market_features.get("forecast_deviation", 0)
                
                # Check if price is moving toward forecast
                if prob_change * forecast_deviation < 0:  # Opposite signs
                    logger.debug("Price moving away from forecast")
                    return False
            
            # Check liquidity score
            liquidity_min = params.get("liquidity_score_min", 0.7)
            liquidity = market_features.get("liquidity_score", 0.5)
            
            if liquidity < liquidity_min:
                logger.debug(f"Liquidity too low: {liquidity:.2f} < {liquidity_min}")
                return False
        
        return True
    
    def _determine_signal_type(
        self, 
        deviation_pct: float, 
        forecast_confidence: float
    ) -> SignalType:
        """
        Determine signal type based on deviation and confidence.
        
        Args:
            deviation_pct: Percentage deviation from forecast
            forecast_confidence: Forecast confidence (0-1)
            
        Returns:
            SignalType
        """
        abs_deviation = abs(deviation_pct)
        
        if deviation_pct > 0:
            # Positive deviation = forecast > current price = BUY signal
            if abs_deviation > 0.05 and forecast_confidence > 0.9:
                return SignalType.STRONG_BUY
            elif abs_deviation > 0.03 and forecast_confidence > 0.7:
                return SignalType.MODERATE_BUY
            elif abs_deviation > 0.02:
                return SignalType.WEAK_BUY
            else:
                return SignalType.NEUTRAL
        else:
            # Negative deviation = forecast < current price = SELL signal
            if abs_deviation > 0.05 and forecast_confidence > 0.9:
                return SignalType.STRONG_SELL
            elif abs_deviation > 0.03 and forecast_confidence > 0.7:
                return SignalType.MODERATE_SELL
            elif abs_deviation > 0.02:
                return SignalType.WEAK_SELL
            else:
                return SignalType.NEUTRAL
    
    def _calculate_signal_score(
        self,
        deviation_pct: float,
        forecast_confidence: float,
        market_features: Dict[str, float],
        strategy: str
    ) -> float:
        """
        Calculate composite signal score (0-1).
        
        Args:
            deviation_pct: Percentage deviation
            forecast_confidence: Forecast confidence
            market_features: Market features
            strategy: Trading strategy
            
        Returns:
            Signal score between 0 and 1
        """
        weights = self.signal_params["scoring_weights"]
        
        # Component 1: Deviation magnitude score
        # Normalize deviation to 0-1 scale (0.02 deviation = 0.5, 0.05 deviation = 1.0)
        deviation_score = min(1.0, abs(deviation_pct) / 0.05)
        
        # Component 2: Forecast confidence score
        confidence_score = forecast_confidence
        
        # Component 3: Market liquidity score
        liquidity = market_features.get("liquidity_score", 0.5)
        liquidity_score = min(1.0, liquidity)  # Assuming liquidity_score is 0-1
        
        # Component 4: Time to resolution score
        # Prefer markets with 1-4 weeks to resolution
        days_to_resolution = market_features.get("days_to_resolution", 30)
        if 7 <= days_to_resolution <= 28:  # 1-4 weeks
            time_score = 1.0
        elif 1 <= days_to_resolution <= 60:  # 1 day - 2 months
            time_score = 0.7
        else:
            time_score = 0.3
        
        # Strategy-specific adjustments
        if strategy == "convergence_trading":
            # Weight time score more heavily for convergence trading
            adjusted_weights = weights.copy()
            adjusted_weights["time_to_resolution"] *= 1.5
            # Normalize weights
            total = sum(adjusted_weights.values())
            adjusted_weights = {k: v/total for k, v in adjusted_weights.items()}
            weights = adjusted_weights
        
        # Calculate weighted score
        score = (
            weights["deviation_magnitude"] * deviation_score +
            weights["forecast_confidence"] * confidence_score +
            weights["market_liquidity"] * liquidity_score +
            weights["time_to_resolution"] * time_score
        )
        
        # Ensure score is between 0 and 1
        return max(0.0, min(1.0, score))
    
    def _calculate_position_size(
        self,
        signal_score: float,
        signal_type: SignalType,
        market_features: Dict[str, float]
    ) -> float:
        """
        Calculate recommended position size (% of portfolio).
        
        Args:
            signal_score: Signal score (0-1)
            signal_type: Signal type
            market_features: Market features
            
        Returns:
            Position size as percentage of portfolio
        """
        params = self.signal_params["position_sizing"]
        
        # Base size
        base_size = params["base_size"]
        
        # Adjust by signal score
        score_adjusted = base_size * signal_score
        
        # Adjust by signal strength
        strength_adjusted = score_adjusted * signal_type.strength
        
        # Adjust by forecast confidence multiplier
        confidence = market_features.get("forecast_confidence", 0.5)
        confidence_multiplier = 1 + (params["confidence_multiplier"] - 1) * confidence
        confidence_adjusted = strength_adjusted * confidence_multiplier
        
        # Adjust by liquidity (discount for low liquidity)
        liquidity = market_features.get("liquidity_score", 0.5)
        liquidity_discount = 1 - params["liquidity_discount"] * (1 - liquidity)
        final_size = confidence_adjusted * liquidity_discount
        
        # Apply bounds
        final_size = max(params["min_size"], min(params["max_size"], final_size))
        
        return final_size
    
    def _generate_entry_logic(
        self,
        strategy: str,
        deviation_pct: float,
        forecast_horizon: int,
        confidence_width: float
    ) -> str:
        """Generate human-readable entry logic description."""
        if strategy == "probability_mispricing":
            direction = "above" if deviation_pct > 0 else "below"
            return (f"TimesFM forecast {direction} market price by {abs(deviation_pct):.1%} "
                   f"at {forecast_horizon+1}h horizon. Confidence width: {confidence_width:.3f}")
        
        elif strategy == "convergence_trading":
            direction = "above" if deviation_pct > 0 else "below"
            return (f"Market price {direction} forecast by {abs(deviation_pct):.1%}. "
                   f"Expected to converge over {forecast_horizon+1}h. "
                   f"Confidence: {1-confidence_width:.1%}")
        
        else:
            return f"{strategy}: Forecast deviation {deviation_pct:.1%} at {forecast_horizon+1}h"
    
    def generate_signals_batch(
        self,
        forecasts: Dict[str, ForecastResult],
        current_prices: Dict[str, float],
        market_features: Dict[str, Dict[str, float]],
        strategy: str = "probability_mispricing"
    ) -> Dict[str, TradingSignal]:
        """
        Generate signals for multiple markets in batch.
        
        Args:
            forecasts: Dict mapping market_id to ForecastResult
            current_prices: Dict mapping market_id to current price
            market_features: Dict mapping market_id to feature dict
            strategy: Trading strategy
            
        Returns:
            Dict mapping market_id to TradingSignal
        """
        signals = {}
        
        for market_id, forecast in forecasts.items():
            if market_id in current_prices and market_id in market_features:
                signal = self.generate_signal(
                    market_id=market_id,
                    forecast_result=forecast,
                    current_price=current_prices[market_id],
                    market_features=market_features[market_id],
                    strategy=strategy
                )
                
                if signal:
                    signals[market_id] = signal
        
        logger.info(f"Generated {len(signals)} signals from {len(forecasts)} forecasts")
        return signals
    
    def filter_signals(
        self,
        signals: Dict[str, TradingSignal],
        min_score: float = 0.5,
        max_positions: int = 10
    ) -> Dict[str, TradingSignal]:
        """
        Filter signals based on quality and portfolio constraints.
        
        Args:
            signals: Dictionary of signals
            min_score: Minimum signal score to include
            max_positions: Maximum number of positions to return
            
        Returns:
            Filtered dictionary of signals
        """
        # Filter by minimum score
        filtered = {
            market_id: signal for market_id, signal in signals.items()
            if signal.signal_score >= min_score
        }
        
        logger.info(f"Score filtering: {len(signals)} -> {len(filtered)} signals")
        
        # Sort by signal score (descending)
        sorted_signals = sorted(
            filtered.items(),
            key=lambda x: x[1].signal_score,
            reverse=True
        )
        
        # Take top N
        top_signals = dict(sorted_signals[:max_positions])
        
        logger.info(f"Top-N filtering: {len(filtered)} -> {len(top_signals)} signals")
        
        return top_signals


if __name__ == "__main__":
    # Test signal generation
    import numpy as np
    from datetime import datetime
    
    # Create a mock forecast result
    forecast_result = ForecastResult(
        market_id="test_market_001",
        forecast_timestamp=datetime.utcnow(),
        horizon_hours=24,
        point_forecast=np.array([0.65, 0.66, 0.67, 0.68, 0.69, 0.70] * 4),  # 24h forecast
        quantile_forecast=np.random.randn(24, 10) * 0.01 + 0.65,  # Mock quantiles
        confidence_width=0.03,
        input_features={},
        model_version="test"
    )
    
    # Create market features
    market_features = {
        "volume_ratio_24": 1.8,
        "market_age_hours": 48,
        "liquidity_score": 0.8,
        "days_to_resolution": 14,
        "prob_change_24h": 0.02,
        "forecast_deviation": 0.04
    }
    
    # Initialize signal generator
    generator = SignalGenerator()
    
    # Generate signal
    signal = generator.generate_signal(
        market_id="test_market_001",
        forecast_result=forecast_result,
        current_price=0.60,  # Market price below forecast
        market_features=market_features,
        strategy="probability_mispricing"
    )
    
    if signal:
        print(f"Signal generated: {signal.signal_type.value}")
        print(f"  Market: {signal.market_id}")
        print(f"  Current price: {signal.current_price:.4f}")
        print(f"  Forecasted price: {signal.forecasted_price:.4f}")
        print(f"  Deviation: {signal.deviation_pct:.2%}")
        print(f"  Signal score: {signal.signal_score:.2f}")
        print(f"  Position size: {signal.position_size_pct:.2%}")
        print(f"  Entry logic: {signal.entry_logic}")
    else:
        print("No signal generated")