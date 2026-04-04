"""TimesFM 2.5 wrapper for BTC price forecasting."""

import logging
import numpy as np
import timesfm

logger = logging.getLogger(__name__)


class TimesFMForecaster:
    """Wrapper for Google TimesFM 2.5 time series forecasting model."""
    
    def __init__(self, config=None):
        """Initialize and load TimesFM 2.5 model.
        
        Args:
            config: Dict with optional keys:
                - max_context: Context length (default 1024)
                - max_horizon: Forecast horizon (default 256)
                - normalize_inputs: Whether to normalize (default True)
        """
        config = config or {}
        
        logger.info('Loading TimesFM 2.5 model...')
        self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            'google/timesfm-2.5-200m-pytorch'
        )
        
        self.model.compile(timesfm.ForecastConfig(
            max_context=config.get('max_context', 1024),
            max_horizon=config.get('max_horizon', 256),
            normalize_inputs=config.get('normalize_inputs', True),
            use_continuous_quantile_head=True,
            force_flip_invariance=True,
            infer_is_positive=True,
            fix_quantile_crossing=True,
        ))
        logger.info('Model loaded and compiled.')
    
    def forecast(self, prices, horizon=12):
        """Run forecast on a price series.
        
        Args:
            prices: List or array of price values
            horizon: Number of steps to forecast (default 12)
        
        Returns:
            Dict with keys:
                - point_forecast: List of forecasted values
                - quantile_forecast: Quantile predictions
                - has_nan: Boolean indicating if NaN was detected
                - error: Error message if forecast failed
        """
        prices = [float(p) for p in prices]
        logger.info(f'Forecasting {len(prices)} points, horizon={horizon}')
        
        try:
            point, quantile = self.model.forecast(
                horizon=horizon,
                inputs=[prices]
            )
            
            has_nan = np.isnan(point).any()
            
            if has_nan:
                logger.warning('NaN detected, retrying with normalize_inputs=False')
                self.model.compile(timesfm.ForecastConfig(
                    max_context=1024,
                    max_horizon=256,
                    normalize_inputs=False,
                    use_continuous_quantile_head=True,
                    force_flip_invariance=True,
                ))
                point, quantile = self.model.forecast(
                    horizon=horizon,
                    inputs=[prices]
                )
                has_nan = np.isnan(point).any()
            
            vals = point[0].tolist() if len(point.shape) > 1 else point.tolist()
            
            return {
                'point_forecast': vals,
                'quantile_forecast': quantile.tolist() if quantile is not None else [],
                'has_nan': bool(has_nan)
            }
            
        except Exception as e:
            logger.error(f'Forecast failed: {e}')
            return {
                'point_forecast': [],
                'quantile_forecast': [],
                'has_nan': True,
                'error': str(e)
            }
