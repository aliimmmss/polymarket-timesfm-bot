"""Fetch BTC price history from CoinGecko."""

import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class BTCPriceFetcher:
    """Client for CoinGecko BTC price data."""
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def get_daily_prices(self, days=365):
        """Get daily BTC prices for the last N days.
        
        Args:
            days: Number of days of history (default 365)
        
        Returns:
            List of price values
        """
        resp = requests.get(
            f"{self.BASE_URL}/coins/bitcoin/market_chart",
            params={
                'vs_currency': 'usd',
                'days': days,
                'interval': 'daily',
            },
            timeout=30
        )
        resp.raise_for_status()
        prices = [p[1] for p in resp.json()['prices']]
        logger.info(f"Fetched {len(prices)} daily BTC prices")
        return prices
    
    def get_hourly_prices(self, days=30):
        """Get hourly BTC prices for the last N days.
        
        Args:
            days: Number of days of history (default 30)
        
        Returns:
            List of price values
        """
        resp = requests.get(
            f"{self.BASE_URL}/coins/bitcoin/market_chart",
            params={
                'vs_currency': 'usd',
                'days': days,
                'interval': 'hourly',
            },
            timeout=30
        )
        resp.raise_for_status()
        prices = [p[1] for p in resp.json()['prices']]
        logger.info(f"Fetched {len(prices)} hourly BTC prices")
        return prices
    
    def get_current_price(self):
        """Get current BTC price.
        
        Returns:
            Current price in USD
        """
        resp = requests.get(
            f"{self.BASE_URL}/simple/price",
            params={
                'ids': 'bitcoin',
                'vs_currencies': 'usd',
            },
            timeout=10
        )
        resp.raise_for_status()
        price = resp.json()['bitcoin']['usd']
        logger.info(f"Current BTC price: ${price:.2f}")
        return price
