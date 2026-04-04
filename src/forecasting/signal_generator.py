"""Generate trading signals by comparing TimesFM BTC forecast to Polymarket odds."""

import logging

logger = logging.getLogger(__name__)


class BTCSignalGenerator:
    """Generate trading signals for BTC 15-min markets."""
    
    @staticmethod
    def generate(forecast_result, current_btc_price, polymarket_up_price):
        """Compare TimesFM BTC direction forecast to Polymarket's 'Up' probability.
        
        Args:
            forecast_result: Dict from TimesFMForecaster.forecast()
            current_btc_price: Current BTC price in USD
            polymarket_up_price: Polymarket's 'Up' token price (0-1)
        
        Returns:
            Dict with keys:
                - signal: 'BUY_UP', 'BUY_DOWN', or 'HOLD'
                - confidence: Float 0-1
                - timesfm_up_prob: TimesFM's predicted UP probability
                - polymarket_up_price: Polymarket's UP price
                - disagreement: Difference between the two
        """
        if forecast_result.get('has_nan') or not forecast_result.get('point_forecast'):
            return {
                'signal': 'HOLD',
                'confidence': 0,
                'reason': 'No valid forecast'
            }
        
        fc = forecast_result['point_forecast']
        up_count = sum(1 for v in fc if v > current_btc_price)
        total = len(fc)
        timesfm_up_prob = up_count / total
        poly_up_prob = float(polymarket_up_price)
        
        # Positive diff = TimesFM more bullish than market
        diff = timesfm_up_prob - poly_up_prob
        
        # Trading logic - only trade when disagreement is significant
        threshold = 0.15
        
        if diff > threshold:
            signal = 'BUY_UP'
            confidence = min(diff / 0.5, 1.0)
        elif diff < -threshold:
            signal = 'BUY_DOWN'
            confidence = min(abs(diff) / 0.5, 1.0)
        else:
            signal = 'HOLD'
            confidence = abs(diff) / threshold
        
        logger.info(
            f'TimesFM UP prob: {timesfm_up_prob:.2f}, '
            f'Polymarket UP price: {poly_up_prob:.2f}, '
            f'Diff: {diff:+.2f}, Signal: {signal}'
        )
        
        return {
            'signal': signal,
            'confidence': round(confidence, 4),
            'timesfm_up_prob': round(timesfm_up_prob, 4),
            'polymarket_up_price': round(poly_up_prob, 4),
            'disagreement': round(diff, 4),
            'up_count': up_count,
            'total_steps': total,
        }
