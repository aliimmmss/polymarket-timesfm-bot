"""TimesFM 2.5 wrapper for BTC price forecasting.

FIXED: Model now loads ONCE and is reused (singleton pattern).
Bug 2a fix - TimesFM model reloads every instantiation.
"""

import logging
import numpy as np
import timesfm
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Module-level singleton for model caching
_model_instance = None
_model_config = None


def get_model(config: Optional[Dict] = None):
    """Get or create the singleton TimesFM model instance.
    
    This ensures the model loads ONCE and is reused across all
    TimesFMForecaster instantiations.
    
    Args:
        config: Optional config dict with keys:
            - max_context: Context length (default 1024)
            - max_horizon: Forecast horizon (default 256)
            - normalize_inputs: Whether to normalize (default True)
    
    Returns:
        Tuple of (model, compiled_config)
    """
    global _model_instance, _model_config
    
    config = config or {}
    new_config = {
        'max_context': config.get('max_context', 1024),
        'max_horizon': config.get('max_horizon', 256),
        'normalize_inputs': config.get('normalize_inputs', True),
    }
    
    # Check if we need to recompile (config changed)
    if _model_instance is None or _model_config != new_config:
        logger.info('Loading TimesFM 2.5 model...')
        
        _model_instance = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            'google/timesfm-2.5-200m-pytorch'
        )
        
        _model_instance.compile(timesfm.ForecastConfig(
            max_context=new_config['max_context'],
            max_horizon=new_config['max_horizon'],
            normalize_inputs=new_config['normalize_inputs'],
            use_continuous_quantile_head=True,
            force_flip_invariance=True,
            infer_is_positive=True,
            fix_quantile_crossing=True,
        ))
        
        _model_config = new_config
        logger.info('Model loaded and compiled.')
    
    return _model_instance, _model_config


class TimesFMForecaster:
    """Wrapper for Google TimesFM 2.5 time series forecasting model.
    
    Uses singleton pattern to ensure model loads only once.
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize forecaster with TimesFM 2.5 model.
        
        Model is loaded ONCE at module level and reused.
        
        Args:
            config: Dict with optional keys:
                - max_context: Context length (default 1024)
                - max_horizon: Forecast horizon (default 256)
                - normalize_inputs: Whether to normalize (default True)
        """
        self.model, self.config = get_model(config)
    
    def forecast(self, prices: List[float], horizon: int = 12) -> Dict:
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
                # Get model with different config
                self.model, _ = get_model({'normalize_inputs': False})
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
