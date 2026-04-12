"""Tests for Polymarket client.

Covers:
- Market data fetching
- CLOB API interactions
- Error handling
"""

import pytest
from unittest.mock import patch, MagicMock, Mock
import json


class TestPolymarketClient:
    """Test cases for Polymarket API client."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.sample_market = {
            'id': 'test-market-123',
            'question': 'Bitcoin Up or Down - Test Market',
            'slug': 'btc-updown-15m-1234567890',
            'outcomePrices': ['0.55', '0.45'],
            'clobTokenIds': ['token-up-123', 'token-down-456'],
            'active': True,
            'closed': False,
            'marketId': 12345,
        }
    
    @patch('src.data_collection.polymarket_client.requests.get')
    def test_fetch_markets_success(self, mock_get):
        """Test successful market fetch."""
        from src.data_collection.polymarket_client import PolymarketClient
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': [self.sample_market],
            'pagination': {'total': 1}
        }
        mock_get.return_value = mock_response
        
        client = PolymarketClient()
        markets = client.get_markets(limit=1)
        
        assert len(markets) == 1
        assert markets[0]['id'] == 'test-market-123'
        mock_get.assert_called_once()
    
    @patch('src.data_collection.polymarket_client.requests.get')
    def test_fetch_markets_failure(self, mock_get):
        """Test market fetch failure handling."""
        from src.data_collection.polymarket_client import PolymarketClient
        
        # Mock failure
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'
        mock_get.return_value = mock_response
        
        client = PolymarketClient()
        markets = client.get_markets(limit=1)
        
        # Should return empty list on failure
        assert markets == []
    
    @patch('src.data_collection.polymarket_client.requests.get')
    def test_fetch_market_by_slug(self, mock_get):
        """Test fetching specific market by slug."""
        from src.data_collection.polymarket_client import PolymarketClient
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self.sample_market
        mock_get.return_value = mock_response
        
        client = PolymarketClient()
        market = client.get_market_by_slug('btc-updown-15m-1234567890')
        
        assert market['id'] == 'test-market-123'
        assert market['outcomePrices'] == ['0.55', '0.45']
    
    @patch('src.data_collection.polymarket_client.requests.get')
    def test_fetch_orderbook(self, mock_get):
        """Test fetching orderbook data."""
        from src.data_collection.polymarket_client import PolymarketClient
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'bids': [{'price': 0.53, 'size': 100}],
            'asks': [{'price': 0.57, 'size': 80}],
        }
        mock_get.return_value = mock_response
        
        client = PolymarketClient()
        orderbook = client.get_orderbook('token-up-123')
        
        assert 'bids' in orderbook
        assert 'asks' in orderbook
        assert orderbook['bids'][0]['price'] == 0.53
    
    def test_parse_market_data(self):
        """Test market data parsing."""
        from src.data_collection.polymarket_client import PolymarketClient
        
        client = PolymarketClient()
        parsed = client.parse_market(self.sample_market)
        
        assert parsed['market_id'] == 'test-market-123'
        assert parsed['up_price'] == 0.55
        assert parsed['down_price'] == 0.45
        assert parsed['up_token_id'] == 'token-up-123'
        assert parsed['down_token_id'] == 'token-down-456'
    
    @patch('src.data_collection.polymarket_client.requests.get')
    def test_rate_limit_handling(self, mock_get):
        """Test rate limit response handling."""
        from src.data_collection.polymarket_client import PolymarketClient
        
        # Mock rate limit
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {'Retry-After': '5'}
        mock_get.return_value = mock_response
        
        client = PolymarketClient()
        result = client.get_markets()
        
        # Should handle gracefully
        assert isinstance(result, list)
    
    @patch('src.data_collection.polymarket_client.requests.get')
    def test_network_timeout(self, mock_get):
        """Test network timeout handling."""
        from src.data_collection.polymarket_client import PolymarketClient
        import requests
        
        mock_get.side_effect = requests.exceptions.Timeout()
        
        client = PolymarketClient(timeout=5)
        markets = client.get_markets()
        
        assert markets == []
    
    @patch('src.data_collection.polymarket_client.requests.get')
    def test_malformed_response(self, mock_get):
        """Test handling malformed JSON response."""
        from src.data_collection.polymarket_client import PolymarketClient
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError('test', 'bad json', 0)
        mock_get.return_value = mock_response
        
        client = PolymarketClient()
        markets = client.get_markets()
        
        assert markets == []


class TestPolymarketClientLive:
    """Live integration tests (optional)."""
    
    @pytest.mark.skipif(
        not os.getenv('RUN_LIVE_TESTS'),
        reason="Set RUN_LIVE_TESTS to run live tests"
    )
    def test_live_market_fetch(self):
        """Test against real Polymarket API."""
        import os
        from src.data_collection.polymarket_client import PolymarketClient
        
        client = PolymarketClient()
        markets = client.get_active_markets(category='crypto')
        
        # There should be at least some crypto markets
        assert isinstance(markets, list)
        if len(markets) > 0:
            assert 'id' in markets[0]
            assert 'outcomePrices' in markets[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
