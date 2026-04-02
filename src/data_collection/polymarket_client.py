"""
Polymarket API Client for fetching market data.

This client interacts with Polymarket's GraphQL API to fetch:
- Market information and metadata
- Historical price data
- Real-time order book data
- Trading volumes and liquidity metrics
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import httpx
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Market:
    """Represents a Polymarket market."""
    id: str
    slug: str
    question: str
    description: str
    category: str
    subcategory: str
    resolution_source: str
    resolution_date: datetime
    created_at: datetime
    liquidity_usd: float
    volume_24h_usd: float
    active: bool
    
    
@dataclass
class MarketPrice:
    """Represents market price at a specific time."""
    timestamp: datetime
    market_id: str
    yes_price: float
    no_price: float
    yes_volume: float
    no_volume: float
    total_volume: float
    liquidity_usd: float
    
    
@dataclass
class OrderBook:
    """Represents market order book."""
    market_id: str
    timestamp: datetime
    yes_bids: List[Dict[str, float]]  # [{price: float, size: float}]
    yes_asks: List[Dict[str, float]]
    no_bids: List[Dict[str, float]]
    no_asks: List[Dict[str, float]]


class PolymarketClient:
    """Client for interacting with Polymarket API."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.polymarket.com"):
        """
        Initialize Polymarket client.
        
        Args:
            api_key: Optional API key for authenticated requests
            base_url: Base URL for Polymarket API
        """
        self.api_key = api_key
        self.base_url = base_url
        self.graphql_endpoint = f"{base_url}/graphql"
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers=self._get_headers()
        )
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Polymarket-Trading-Bot/0.1.0"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    async def fetch_active_markets(self, limit: int = 100, offset: int = 0) -> List[Market]:
        """
        Fetch active markets from Polymarket.
        
        Args:
            limit: Maximum number of markets to fetch
            offset: Pagination offset
            
        Returns:
            List of Market objects
        """
        query = """
        query GetActiveMarkets($limit: Int!, $offset: Int!) {
          markets(limit: $limit, offset: $offset, where: {active: {_eq: true}}) {
            id
            slug
            question
            description
            category
            subcategory
            resolutionSource
            resolutionDate
            createdAt
            liquidityUsd
            volume24hUsd
            active
          }
        }
        """
        
        variables = {"limit": limit, "offset": offset}
        
        try:
            response = await self.client.post(
                self.graphql_endpoint,
                json={"query": query, "variables": variables}
            )
            response.raise_for_status()
            data = response.json()
            
            markets = []
            for market_data in data.get("data", {}).get("markets", []):
                try:
                    market = Market(
                        id=market_data["id"],
                        slug=market_data["slug"],
                        question=market_data["question"],
                        description=market_data.get("description", ""),
                        category=market_data["category"],
                        subcategory=market_data.get("subcategory", ""),
                        resolution_source=market_data["resolutionSource"],
                        resolution_date=datetime.fromisoformat(market_data["resolutionDate"].replace("Z", "+00:00")),
                        created_at=datetime.fromisoformat(market_data["createdAt"].replace("Z", "+00:00")),
                        liquidity_usd=float(market_data.get("liquidityUsd", 0)),
                        volume_24h_usd=float(market_data.get("volume24hUsd", 0)),
                        active=market_data["active"]
                    )
                    markets.append(market)
                except (KeyError, ValueError) as e:
                    logger.warning(f"Error parsing market data: {e}")
                    continue
                    
            logger.info(f"Fetched {len(markets)} active markets")
            return markets
            
        except Exception as e:
            logger.error(f"Error fetching active markets: {e}")
            return []
    
    async def fetch_market_prices(
        self, 
        market_id: str, 
        start_time: datetime, 
        end_time: datetime,
        interval_minutes: int = 5
    ) -> List[MarketPrice]:
        """
        Fetch historical prices for a specific market.
        
        Args:
            market_id: Market ID
            start_time: Start time for historical data
            end_time: End time for historical data
            interval_minutes: Time interval between data points
            
        Returns:
            List of MarketPrice objects
        """
        # Note: Polymarket doesn't have a direct historical price endpoint
        # This would need to use their WebSocket feed or aggregate from trades
        # For now, we'll implement a placeholder that needs to be filled
        # with actual data fetching logic
        
        logger.warning("Historical price fetching not fully implemented - needs WebSocket integration")
        return []
    
    async def fetch_current_prices(self, market_ids: List[str]) -> Dict[str, MarketPrice]:
        """
        Fetch current prices for multiple markets.
        
        Args:
            market_ids: List of market IDs
            
        Returns:
            Dictionary mapping market_id to MarketPrice
        """
        query = """
        query GetMarketPrices($marketIds: [String!]!) {
          markets(where: {id: {_in: $marketIds}}) {
            id
            yesPrice
            noPrice
            yesVolume24h
            noVolume24h
            totalVolume24h
            liquidityUsd
          }
        }
        """
        
        variables = {"marketIds": market_ids}
        
        try:
            response = await self.client.post(
                self.graphql_endpoint,
                json={"query": query, "variables": variables}
            )
            response.raise_for_status()
            data = response.json()
            
            prices = {}
            timestamp = datetime.utcnow()
            
            for market_data in data.get("data", {}).get("markets", []):
                market_id = market_data["id"]
                prices[market_id] = MarketPrice(
                    timestamp=timestamp,
                    market_id=market_id,
                    yes_price=float(market_data.get("yesPrice", 0)),
                    no_price=float(market_data.get("noPrice", 0)),
                    yes_volume=float(market_data.get("yesVolume24h", 0)),
                    no_volume=float(market_data.get("noVolume24h", 0)),
                    total_volume=float(market_data.get("totalVolume24h", 0)),
                    liquidity_usd=float(market_data.get("liquidityUsd", 0))
                )
            
            logger.info(f"Fetched current prices for {len(prices)} markets")
            return prices
            
        except Exception as e:
            logger.error(f"Error fetching current prices: {e}")
            return {}
    
    async def fetch_order_book(self, market_id: str) -> Optional[OrderBook]:
        """
        Fetch order book for a specific market.
        
        Args:
            market_id: Market ID
            
        Returns:
            OrderBook object or None if error
        """
        query = """
        query GetOrderBook($marketId: String!) {
          market(id: $marketId) {
            id
            yesBids {
              price
              size
            }
            yesAsks {
              price
              size
            }
            noBids {
              price
              size
            }
            noAsks {
              price
              size
            }
          }
        }
        """
        
        variables = {"marketId": market_id}
        
        try:
            response = await self.client.post(
                self.graphql_endpoint,
                json={"query": query, "variables": variables}
            )
            response.raise_for_status()
            data = response.json()
            
            market_data = data.get("data", {}).get("market", {})
            if not market_data:
                return None
            
            return OrderBook(
                market_id=market_id,
                timestamp=datetime.utcnow(),
                yes_bids=market_data.get("yesBids", []),
                yes_asks=market_data.get("yesAsks", []),
                no_bids=market_data.get("noBids", []),
                no_asks=market_data.get("noAsks", [])
            )
            
        except Exception as e:
            logger.error(f"Error fetching order book for market {market_id}: {e}")
            return None
    
    async def fetch_market_trades(
        self, 
        market_id: str, 
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent trades for a market.
        
        Args:
            market_id: Market ID
            limit: Maximum number of trades to fetch
            
        Returns:
            List of trade dictionaries
        """
        query = """
        query GetMarketTrades($marketId: String!, $limit: Int!) {
          trades(
            where: {marketId: {_eq: $marketId}}
            order_by: {timestamp: desc}
            limit: $limit
          ) {
            id
            timestamp
            side
            price
            amount
            taker
            maker
          }
        }
        """
        
        variables = {"marketId": market_id, "limit": limit}
        
        try:
            response = await self.client.post(
                self.graphql_endpoint,
                json={"query": query, "variables": variables}
            )
            response.raise_for_status()
            data = response.json()
            
            return data.get("data", {}).get("trades", [])
            
        except Exception as e:
            logger.error(f"Error fetching trades for market {market_id}: {e}")
            return []
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Synchronous wrapper for convenience
class SyncPolymarketClient:
    """Synchronous wrapper for PolymarketClient."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.polymarket.com"):
        self.api_key = api_key
        self.base_url = base_url
        
    def fetch_active_markets(self, limit: int = 100, offset: int = 0) -> List[Market]:
        """Synchronous version of fetch_active_markets."""
        async def _fetch():
            async with PolymarketClient(self.api_key, self.base_url) as client:
                return await client.fetch_active_markets(limit, offset)
        
        return asyncio.run(_fetch())
    
    def fetch_current_prices(self, market_ids: List[str]) -> Dict[str, MarketPrice]:
        """Synchronous version of fetch_current_prices."""
        async def _fetch():
            async with PolymarketClient(self.api_key, self.base_url) as client:
                return await client.fetch_current_prices(market_ids)
        
        return asyncio.run(_fetch())


if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def example():
        client = PolymarketClient()
        
        # Fetch active markets
        markets = await client.fetch_active_markets(limit=10)
        print(f"Fetched {len(markets)} markets")
        
        if markets:
            # Fetch prices for first 3 markets
            market_ids = [m.id for m in markets[:3]]
            prices = await client.fetch_current_prices(market_ids)
            print(f"Fetched prices for {len(prices)} markets")
            
            # Fetch order book for first market
            order_book = await client.fetch_order_book(markets[0].id)
            if order_book:
                print(f"Order book has {len(order_book.yes_bids)} YES bids")
        
        await client.close()
    
    asyncio.run(example())