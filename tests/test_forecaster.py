"""Tests for the TimesFM forecaster."""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from src.forecasting.forecaster import TimesFMForecaster, get_model


class TestTimesFMForecaster:
    """Test cases for TimesFM forecaster."""

    @patch('src.forecasting.forecaster.timesfm')
    def test_forecaster_initialization(self, mock_timesfm):
        """Test forecaster initializes correctly."""
        # Mock the model
        mock_model = MagicMock()
        mock_timesfm.TimesFM_2p5_200M_torch.from_pretrained.return_value = mock_model
        
        forecaster = TimesFMForecaster(config={'max_context': 512})
        
        assert forecaster.config == {'max_context': 512, 'max_horizon': 256, 'normalize_inputs': True}
        
    @patch('src.forecasting.forecaster.timesfm')
    def test_forecast_success(self, mock_timesfm):
        """Test successful forecast."""
        # Mock model
        mock_model = MagicMock()
        mock_timesfm.TimesFM_2p5_200M_torch.from_pretrained.return_value = mock_model
        mock_model.forecast.return_value = (np.array([[1.0, 2.0, 3.0, 4.0, 5.0]]), None)
        
        forecaster = TimesFMForecaster()
        result = forecaster.forecast([1.0, 2.0, 3.0, 4.0, 5.0], horizon=5)
        
        assert result['has_nan'] is False
        assert len(result['point_forecast']) == 5
        assert result['error'] is None
        
    @patch('src.forecasting.forecaster.timesfm')
    def test_forecast_with_nan_retry(self, mock_timesfm):
        """Test that NaN triggers config retry."""
        # First call returns NaN
        mock_model = MagicMock()
        mock_timesfm.TimesFM_2p5_200M_torch.from_pretrained.return_value = mock_model
        
        # First call with NaN, second call succeeds
        mock_model.forecast.side_effect = [
            (np.array([[np.nan, np.nan]]), None),
            (np.array([[1.0, 2.0]]), None)
        ]
        
        forecaster = TimesFMForecaster()
        result = forecaster.forecast([1.0, 2.0], horizon=2)
        
        # Model should have been called twice
        assert mock_model.forecast.call_count == 2
        
    @patch('src.forecasting.forecaster.timesfm')
    def test_forecast_exception_handling(self, mock_timesfm):
        """Test exception handling in forecast."""
        mock_model = MagicMock()
        mock_timesfm.TimesFM_2p5_200M_torch.from_pretrained.return_value = mock_model
        mock_model.forecast.side_effect = RuntimeError("Model load failed")
        
        forecaster = TimesFMForecaster()
        result = forecaster.forecast([1.0, 2.0], horizon=2)
        
        assert result['has_nan'] is True
        assert result['point_forecast'] == []
        assert 'error' in result


class TestSingletonPattern:
    """Test singleton pattern for model caching."""
    
    @patch('src.forecasting.forecaster.timesfm')
    def test_get_model_reuses_instance(self, mock_timesfm):
        """Test that get_model returns cached instance."""
        mock_model = MagicMock()
        mock_timesfm.TimesFM_2p5_200M_torch.from_pretrained.return_value = mock_model
        
        # Reset module-level globals for testing
        import src.forecasting.forecaster as forecaster_module
        forecaster_module._model_instance = None
        forecaster_module._model_config = None
        
        # First call
        model1, config1 = get_model({'max_context': 512})
        
        # Second call with same config - should reuse
        model2, config2 = get_model({'max_context': 512})
        
        # Model should only be loaded once
        assert mock_timesfm.TimesFM_2p5_200M_torch.from_pretrained.call_count == 1
        assert model1 is model2
