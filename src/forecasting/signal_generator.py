"""Generate trading signals from TimesFM forecasts."""

import logging

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Generate BULLISH/BEARISH/HOLD signals from forecast results."""
    
    @staticmethod
    def generate(forecast_result, current_price):
        """Generate trading signal from forecast vs current price.
        
        Args:
            forecast_result: Dict from TimesFMForecaster.forecast()
            current_price: Current market price
        
        Returns:
            Dict with keys:
                - signal: 'BULLISH', 'BEARISH', or 'HOLD'
                - confidence: Float 0-1
                - pct_diff: Percentage difference from current price
                - reason: Explanation string
        """
        if forecast_result.get('has_nan') or not forecast_result.get('point_forecast'):
            return {
                'signal': 'HOLD',
                'confidence': 0,
                'pct_diff': 0,
                'reason': 'No valid forecast'
            }
        
        fc = forecast_result['point_forecast']
        avg = sum(fc) / len(fc)
        pct_diff = ((avg - current_price) / current_price) * 100 if current_price > 0 else 0
        
        if pct_diff > 2:
            signal = 'BULLISH'
        elif pct_diff < -2:
            signal = 'BEARISH'
        else:
            signal = 'HOLD'
        
        confidence = min(abs(pct_diff) / 10, 1.0)
        
        logger.info(f'Signal: {signal} ({pct_diff:+.2f}%, confidence={confidence:.2f})')
        
        return {
            'signal': signal,
            'confidence': round(confidence, 4),
            'pct_diff': round(pct_diff, 4),
            'reason': f'Forecast avg {avg:.4f} vs current {current_price:.4f}'
        }
