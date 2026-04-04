"""Polymarket API client using real Gamma + CLOB APIs."""

import requests
import logging

logger = logging.getLogger(__name__)


class PolymarketClient:
    """Client for Polymarket Gamma and CLOB APIs."""
    
    GAMMA_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "PolymarketBot/2.0"
        })
    
    def get_active_markets(self, limit=50):
        """Fetch active markets from Gamma API sorted by volume."""
        try:
            resp = self.session.get(
                f"{self.GAMMA_URL}/markets",
                params={
                    'limit': limit,
                    'active': 'true',
                    'closed': 'false',
                    'order': 'volume24hr',
                    'ascending': 'false',
                },
                timeout=10
            )
            resp.raise_for_status()
            markets = resp.json()
            logger.info(f"Fetched {len(markets)} active markets")
            return markets
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []
    
    def get_price_history(self, token_id, interval='max', fidelity=60):
        """Fetch price history from CLOB API.
        
        Args:
            token_id: The CLOB token ID (from clobTokenIds field)
            interval: Time interval ('max', 'hour', 'day')
            fidelity: Data point frequency (1, 60, etc.)
        
        Returns:
            List of dicts with 'p' (price) and 't' (timestamp) keys
        """
        try:
            resp = self.session.get(
                f"{self.CLOB_URL}/prices-history",
                params={
                    'market': token_id,
                    'interval': interval,
                    'fidelity': fidelity,
                },
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            history = data.get('history', [])
            logger.info(f"Fetched {len(history)} price points for token {token_id[:16]}...")
            return history
        except Exception as e:
            logger.error(f"Failed to fetch price history for {token_id}: {e}")
            return []
    
    def get_order_book(self, condition_id):
        """Fetch current order book for a market."""
        try:
            resp = self.session.get(
                f"{self.CLOB_URL}/markets/{condition_id}/book",
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch order book for {condition_id}: {e}")
            return None
