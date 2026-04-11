"""pytest configuration and fixtures."""

import sys
import pytest
from pathlib import Path

# Add src to path
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))


@pytest.fixture
def sample_btc_prices():
    """Sample BTC price data for testing."""
    return [
        65000.0, 65200.0, 65100.0, 65300.0, 65500.0,
        65800.0, 65400.0, 65600.0, 65900.0, 66000.0,
        65700.0, 66100.0, 66300.0, 66000.0, 66400.0,
    ]


@pytest.fixture
def sample_forecast_result():
    """Sample TimesFM forecast result."""
    return {
        'point_forecast': [66200.0, 66500.0, 66800.0, 67000.0, 67200.0],
        'quantile_forecast': [],
        'has_nan': False,
        'error': None,
    }


@pytest.fixture
def sample_market_data():
    """Sample Polymarket market data."""
    return {
        'id': 'test-market-123',
        'question': 'Bitcoin Up or Down - Test Market',
        'slug': 'btc-updown-15m-1234567890',
        'outcomePrices': ['0.55', '0.45'],
        'clobTokenIds': ['token-up-123', 'token-down-456'],
        'active': True,
        'closed': False,
    }


@pytest.fixture
def test_config():
    """Test configuration."""
    return {
        'max_context': 512,
        'max_horizon': 128,
        'normalize_inputs': True,
    }
