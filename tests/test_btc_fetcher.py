"""Tests for BTC price fetcher.

Covers:
- Price fetching from CoinGecko
- Data transformation
- Error handling
- Caching
"""

import pytest
from unittest.mock import patch, MagicMock
import numpy as np
from datetime import datetime, timedelta


class TestBTCPriceFetcher:
    """Test cases for BTC price fetcher."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.sample_prices = {
            'prices': [
                [int(datetime.now().timestamp() * 1000) - 1000000], 65000.0,
                [int(datetime.now().timestamp() * 1000)], 65200.0,
                [int(datetime.now().timestamp() * 1000) + 1000000], 65100.0,
            ],
            'market_caps': [],
            'total_volumes': [],
        }
    
    @patch('src.data_collection.btc_price_fetcher.requests.get')
    def test_fetch_btc_prices_success(self, mock_get):
        """Test successful BTC price fetch."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'prices': [
                [1234567890000, 65000.0],
                [1234567890100, 65200.0],
                [1234567890200, 65100.0],
            ],
            'market_caps': [],
            'total_volumes': [],
        }
        mock_get.return_value = mock_response
        
        fetcher = BTCPriceFetcher()
        prices = fetcher.get_historical_prices(days=30)
        
        assert len(prices) == 3
        assert prices[0] == 65000.0
        assert prices[1] == 65200.0
    
    @patch('src.data_collection.btc_price_fetcher.requests.get')
    def test_fetch_btc_current_price(self, mock_get):
        """Test fetching current BTC price."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'bitcoin': {'usd': 65000.0}
        }
        mock_get.return_value = mock_response
        
        fetcher = BTCPriceFetcher()
        current_price = fetcher.get_current_price()
        
        assert current_price == 65000.0
    
    @patch('src.data_collection.btc_price_fetcher.requests.get')
    def test_fetch_failure_handling(self, mock_get):
        """Test fetch failure handling."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        # Mock failure
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'
        mock_get.return_value = mock_response
        
        fetcher = BTCPriceFetcher()
        prices = fetcher.get_historical_prices(days=30)
        
        # Should return empty list or cached data
        assert isinstance(prices, (list, type(None)))
    
    @patch('src.data_collection.btc_price_fetcher.requests.get')
    def test_api_rate_limit(self, mock_get):
        """Test rate limit response."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response
        
        fetcher = BTCPriceFetcher()
        prices = fetcher.get_historical_prices(days=30)
        
        # Should handle gracefully
        assert isinstance(prices, (list, type(None)))
    
    @patch('src.data_collection.btc_price_fetcher.requests.get')
    def test_network_timeout(self, mock_get):
        """Test network timeout handling."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        import requests
        
        mock_get.side_effect = requests.exceptions.Timeout()
        
        fetcher = BTCPriceFetcher(timeout=5)
        prices = fetcher.get_historical_prices(days=30)
        
        assert prices == [] or prices is None
    
    def test_price_normalization(self):
        """Test price data normalization."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        fetcher = BTCPriceFetcher()
        
        # Raw API data format: [timestamp, price]
        raw_data = [
            [1234567890000, 65000.0],
            [1234567893600, 65200.0],  # +1 hour
            [1234567897200, 65100.0],  # +2 hours
        ]
        
        normalized = fetcher.normalize_prices(raw_data)
        
        assert len(normalized) == 3
        assert all(isinstance(p, (int, float)) for p in normalized)
    
    def test_cache_mechanism(self):
        """Test caching behavior."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        fetcher = BTCPriceFetcher(cache_duration=300)  # 5 min cache
        
        # First call
        with patch('src.data_collection.btc_price_fetcher.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'prices': [[1234567890000, 65000.0]],
                'market_caps': [],
                'total_volumes': [],
            }
            mock_get.return_value = mock_response
            
            prices1 = fetcher.get_historical_prices(days=1)
            assert mock_get.called
            
            # Second call within cache window
            prices2 = fetcher.get_historical_prices(days=1)
            # Should not call API again
            assert mock_get.call_count == 1
            assert prices1 == prices2
    
    def test_data_formatting(self):
        """Test price data formatting for TimesFM."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        fetcher = BTCPriceFetcher()
        
        raw_prices = [65000.0, 65200.0, 65100.0, 65300.0, 65500.0]
        formatted = fetcher.format_for_model(raw_prices, normalize=True)
        
        # Should return numpy array or list
        assert isinstance(formatted, (np.ndarray, list))
        
        # If normalized, first value should be ~0
        if isinstance(formatted, np.ndarray) and len(formatted) > 0:
            assert abs(formatted[0]) < 0.01
    
    @patch('src.data_collection.btc_price_fetcher.requests.get')
    def test_empty_response_handling(self, mock_get):
        """Test handling empty API response."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'prices': []}
        mock_get.return_value = mock_response
        
        fetcher = BTCPriceFetcher()
        prices = fetcher.get_historical_prices(days=1)
        
        assert prices == []
    
    @patch('src.data_collection.btc_price_fetcher.requests.get')
    def test_malformed_response(self, mock_get):
        """Test handling malformed JSON."""
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        import json
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError('test', 'bad', 0)
        mock_get.return_value = mock_response
        
        fetcher = BTCPriceFetcher()
        prices = fetcher.get_historical_prices(days=1)
        
        assert prices == []


class TestBTCPriceFetcherLive:
    """Live integration tests (optional)."""
    
    @pytest.mark.skipif(
        not os.getenv('RUN_LIVE_TESTS'),
        reason="Set RUN_LIVE_TESTS to run live tests"
    )
    def test_live_btc_fetch(self):
        """Test against real CoinGecko API."""
        import os
        from src.data_collection.btc_price_fetcher import BTCPriceFetcher
        
        fetcher = BTCPriceFetcher()
        current_price = fetcher.get_current_price()
        
        # Current BTC price should be reasonable
        assert current_price > 10000  # Sanity check
        assert current_price < 1000000
        
        historical = fetcher.get_historical_prices(days=7)
        assert len(historical) > 100  # Should have many data points
        assert all(p > 0 for p in historical)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
