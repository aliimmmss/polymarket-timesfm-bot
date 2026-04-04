"""Polymarket client for BTC 15-minute markets using Gamma + CLOB APIs."""

import requests
import time
import math
import json
import logging

logger = logging.getLogger(__name__)


class PolymarketBTCClient:
    """Client for Polymarket BTC 15-minute Up/Down markets."""
    
    GAMMA_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"
    
    def find_active_btc_markets(self, count=3):
        """Find current and upcoming BTC 15-min markets.
        
        Args:
            count: Number of markets to find (default 3)
        
        Returns:
            List of market dicts with question, outcomePrices, clobTokenIds, etc.
        """
        now = time.time()
        current_ts = math.floor(now / 900) * 900
        markets = []
        
        for i in range(count):
            ts = current_ts + (i * 900)
            slug = f"btc-updown-15m-{ts}"
            
            resp = requests.get(
                f"{self.GAMMA_URL}/markets",
                params={'slug': slug},
                timeout=10
            )
            
            if resp.status_code == 200 and resp.json():
                m = resp.json()[0]
                if m.get('active') and not m.get('closed'):
                    # Parse outcomePrices if needed
                    if isinstance(m.get('outcomePrices'), str):
                        m['outcomePrices'] = json.loads(m['outcomePrices'])
                    if isinstance(m.get('clobTokenIds'), str):
                        m['clobTokenIds'] = json.loads(m['clobTokenIds'])
                    markets.append(m)
                    logger.info(f"Found market: {m['question']} (Up: {m['outcomePrices'][0]})")
        
        return markets
    
    def get_market_orderbook(self, token_id):
        """Get full orderbook for a token.
        
        Args:
            token_id: CLOB token ID
        
        Returns:
            Dict with bids, asks, etc.
        """
        resp = requests.get(
            f"{self.CLOB_URL}/book",
            params={'token_id': token_id},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()
    
    def get_market_price(self, token_id):
        """Get midpoint price for a token.
        
        Args:
            token_id: CLOB token ID
        
        Returns:
            Midpoint price (0-1)
        """
        resp = requests.get(
            f"{self.CLOB_URL}/midpoint",
            params={'token_id': token_id},
            timeout=10
        )
        if resp.status_code == 200:
            return float(resp.json().get('mid', 0.5))
        return None
    
    def get_resolved_btc_markets(self, limit=20):
        """Get recently resolved BTC 15-min markets for backtesting.
        
        Args:
            limit: Max number of markets to return
        
        Returns:
            List of resolved market dicts
        """
        now = time.time()
        current_ts = math.floor(now / 900) * 900
        results = []
        
        # Look back at past windows
        for i in range(1, limit + 1):
            ts = current_ts - (i * 900)
            slug = f"btc-updown-15m-{ts}"
            
            resp = requests.get(
                f"{self.GAMMA_URL}/markets",
                params={'slug': slug},
                timeout=10
            )
            
            if resp.status_code == 200 and resp.json():
                m = resp.json()[0]
                if m.get('closed'):
                    if isinstance(m.get('outcomePrices'), str):
                        m['outcomePrices'] = json.loads(m['outcomePrices'])
                    if isinstance(m.get('clobTokenIds'), str):
                        m['clobTokenIds'] = json.loads(m['clobTokenIds'])
                    results.append(m)
        
        return results
