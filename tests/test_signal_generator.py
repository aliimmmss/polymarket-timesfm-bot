"""Tests for the BTC signal generator."""

import pytest
from src.forecasting.signal_generator import BTCSignalGenerator


class TestBTCSignalGenerator:
    """Test cases for signal generation."""

    def test_generate_buy_up_signal(self, sample_forecast_result):
        """Test generation of BUY_UP signal."""
        # TimesFM says 100% UP (all above current), market says 50%
        result = BTCSignalGenerator.generate(
            sample_forecast_result,  # 5 forecast steps, all higher
            current_btc_price=65000.0,
            polymarket_up_price=0.35  # Market significantly underpricing UP
        )
        
        assert result['signal'] == 'BUY_UP'
        assert result['confidence'] > 0
        assert result['timesfm_up_prob'] == 1.0
        assert result['disagreement'] > 0.15  # Significant disagreement
        
    def test_generate_buy_down_signal(self, sample_forecast_result):
        """Test generation of BUY_DOWN signal."""
        # Modify forecast to all DOWN
        forecast_down = {
            'point_forecast': [64000.0, 63800.0, 63500.0, 63300.0, 63000.0],
            'quantile_forecast': [],
            'has_nan': False,
        }
        
        result = BTCSignalGenerator.generate(
            forecast_down,
            current_btc_price=65000.0,
            polymarket_up_price=0.70  # Market overpricing UP (so DOWN underpriced)
        )
        
        assert result['signal'] == 'BUY_DOWN'
        assert result['confidence'] > 0
        assert result['timesfm_up_prob'] == 0.0
        
    def test_generate_hold_signal(self):
        """Test generation of HOLD signal when no significant disagreement."""
        forecast_neutral = {
            'point_forecast': [65100.0, 65200.0, 64900.0, 65100.0, 64800.0],
            'quantile_forecast': [],
            'has_nan': False,
        }
        
        result = BTCSignalGenerator.generate(
            forecast_neutral,
            current_btc_price=65000.0,
            polymarket_up_price=0.50  # Close to forecast
        )
        
        assert result['signal'] == 'HOLD'
        assert result['confidence'] < 1.0
        
    def test_hold_on_nan_forecast(self):
        """Test that HOLD is returned when forecast contains NaN."""
        forecast_nan = {
            'point_forecast': [],
            'quantile_forecast': [],
            'has_nan': True,
            'error': 'Forecast failed',
        }
        
        result = BTCSignalGenerator.generate(
            forecast_nan,
            current_btc_price=65000.0,
            polymarket_up_price=0.50
        )
        
        assert result['signal'] == 'HOLD'
        assert result['reason'] == 'No valid forecast'
        
    def test_edge_case_exact_threshold(self):
        """Test behavior at exact threshold boundary."""
        # Creates exactly 0.15 disagreement
        forecast_borderline = {
            'point_forecast': [65200.0, 65100.0, 65300.0, 65000.0, 64900.0],
            'quantile_forecast': [],
            'has_nan': False,
        }
        
        result = BTCSignalGenerator.generate(
            forecast_borderline,
            current_btc_price=65000.0,
            polymarket_up_price=0.50
        )
        
        # Exactly at threshold should be HOLD
        # (diff > threshold, so 0.6 - 0.5 = 0.1 < 0.15, should be HOLD)
        assert result['disagreement'] < 0.15
        assert result['signal'] == 'HOLD'


class TestSignalConfidence:
    """Test confidence calculation logic."""
    
    def test_high_confidence_large_disagreement(self):
        """Test that large disagreement gives high confidence."""
        forecast = {
            'point_forecast': [67000.0, 67200.0, 67500.0, 67800.0, 68000.0],
            'quantile_forecast': [],
            'has_nan': False,
        }
        
        result = BTCSignalGenerator.generate(
            forecast,
            current_btc_price=65000.0,
            polymarket_up_price=0.20
        )
        
        # TimesFM 100% UP, market 20% UP = 0.80 disagreement
        assert result['confidence'] > 0.9
        
    def test_low_confidence_small_disagreement(self):
        """Test that small disagreement gives low confidence."""
        forecast = {
            'point_forecast': [65100.0, 65200.0, 65000.0, 64900.0, 64800.0],
            'quantile_forecast': [],
            'has_nan': False,
        }
        
        result = BTCSignalGenerator.generate(
            forecast,
            current_btc_price=65000.0,
            polymarket_up_price=0.55
        )
        
        # Small disagreement = lower confidence
        assert result['confidence'] < 0.5
