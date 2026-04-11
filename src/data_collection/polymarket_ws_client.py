"""WebSocket client for real-time Polymarket data.

Uses Polymarket WSS endpoint for real-time market data:
wss://ws-clob.polymarket.com

Advantages over REST polling:
- Real-time orderbook updates
- Lower latency (20-50ms vs 1-5s polling)
- Reduced API rate limit usage

Based on:
- https://docs.polymarket.com/trading/orders
- https://github.com/Polymarket/py-clob-client
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WSOrderbookSnapshot:
    """Orderbook snapshot from WebSocket."""
    market_id: str
    timestamp: float
    bids: List[tuple]  # [(price, size), ...]
    asks: List[tuple]  # [(price, size), ...]


@dataclass
class WSTradeUpdate:
    """Trade update from WebSocket."""
    market_id: str
    timestamp: float
    side: str  # 'BUY' or 'SELL'
    price: float
    size: float
    trade_id: Optional[str] = None


@dataclass
class WSMarketUpdate:
    """Market price/ticker update."""
    market_id: str
    timestamp: float
    best_bid: float
    best_ask: float
    last_price: Optional[float] = None
    volume_24h: Optional[float] = None


class PolymarketWebSocketClient:
    """WebSocket client for real-time Polymarket data.
    
    Features:
    - Orderbook depth streaming
    - Trade feed updates
    - Market ticker updates
    - Automatic reconnection
    - Subscription management
    """
    
    WS_URL = "wss://ws-clob.polymarket.com"
    
    def __init__(
        self,
        api_creds: Optional[Dict] = None,
        reconnect_interval: float = 5.0,
        max_reconnect_attempts: int = 5,
    ):
        """Initialize WebSocket client.
        
        Args:
            api_creds: API credentials from ClobClient.create_or_derive_api_key()
            reconnect_interval: Seconds between reconnection attempts
            max_reconnect_attempts: Max reconnections before giving up
        """
        self.api_creds = api_creds
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        
        # Connection state
        self._ws = None
        self._connected = False
        self._reconnect_count = 0
        self._running = False
        
        # Subscriptions
        self._orderbook_callbacks: Dict[str, List[Callable]] = {}
        self._trade_callbacks: Dict[str, List[Callable]] = {}
        self._market_callbacks: Dict[str, List[Callable]] = {}
        self._global_callbacks: List[Callable] = []
        
        # Data cache
        self._orderbooks: Dict[str, WSOrderbookSnapshot] = {}
        
        logger.info("WebSocket client initialized")
    
    async def connect(self) -> bool:
        """Connect to Polymarket WebSocket.
        
        Returns:
            True if connected successfully
        """
        try:
            import websockets
            
            logger.info(f"Connecting to {self.WS_URL}...")
            
            # Build connection headers if API creds provided
            headers = {}
            if self.api_creds:
                # Add authentication headers
                headers['POLY_ADDRESS'] = self.api_creds.get('address', '')
                headers['POLY_SIGNATURE'] = self.api_creds.get('signature', '')
                headers['POLY_TIMESTAMP'] = str(self.api_creds.get('timestamp', ''))
            
            self._ws = await websockets.connect(
                self.WS_URL,
                extra_headers=headers,
                ping_interval=30,
                ping_timeout=10,
            )
            
            self._connected = True
            self._reconnect_count = 0
            logger.info("WebSocket connected")
            
            # Start message handler
            asyncio.create_task(self._message_handler())
            
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()
        self._connected = False
        logger.info("WebSocket disconnected")
    
    async def subscribe_orderbook(
        self,
        market_id: str,
        callback: Optional[Callable] = None,
        depth: int = 10,
    ):
        """Subscribe to orderbook updates for a market.
        
        Args:
            market_id: CLOB market ID
            callback: Function to call with orderbook updates
            depth: Number of price levels to track
        """
        if callback:
            if market_id not in self._orderbook_callbacks:
                self._orderbook_callbacks[market_id] = []
            self._orderbook_callbacks[market_id].append(callback)
        
        if self._connected:
            subscribe_msg = {
                "type": "SUBSCRIBE",
                "channel": "ORDERBOOK",
                "market": market_id,
                "depth": depth,
            }
            await self._ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to orderbook: {market_id}")
    
    async def subscribe_trades(
        self,
        market_id: str,
        callback: Optional[Callable] = None,
    ):
        """Subscribe to trade feed for a market."""
        if callback:
            if market_id not in self._trade_callbacks:
                self._trade_callbacks[market_id] = []
            self._trade_callbacks[market_id].append(callback)
        
        if self._connected:
            subscribe_msg = {
                "type": "SUBSCRIBE",
                "channel": "TRADES",
                "market": market_id,
            }
            await self._ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to trades: {market_id}")
    
    async def subscribe_market(self, market_id: str, callback: Optional[Callable] = None):
        """Subscribe to market ticker updates."""
        if callback:
            if market_id not in self._market_callbacks:
                self._market_callbacks[market_id] = []
            self._market_callbacks[market_id].append(callback)
        
        if self._connected:
            subscribe_msg = {
                "type": "SUBSCRIBE",
                "channel": "MARKET",
                "market": market_id,
            }
            await self._ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to market: {market_id}")
    
    async def unsubscribe_all(self):
        """Unsubscribe from all channels."""
        if self._connected:
            await self._ws.send(json.dumps({"type": "UNSUBSCRIBE_ALL"}))
            logger.info("Unsubscribed from all channels")
    
    async def _message_handler(self):
        """Handle incoming WebSocket messages."""
        self._running = True
        
        while self._running and self._connected:
            try:
                message = await self._ws.recv()
                data = json.loads(message)
                
                await self._process_message(data)
                
            except Exception as e:
                logger.error(f"Message handler error: {e}")
                self._connected = False
                break
        
        # Attempt reconnection
        if self._running and self._reconnect_count < self.max_reconnect_attempts:
            await self._attempt_reconnect()
    
    async def _process_message(self, data: Dict):
        """Process incoming message."""
        msg_type = data.get('type', '').upper()
        channel = data.get('channel', '').upper()
        market_id = data.get('market', '')
        
        # Log raw message at debug level
        logger.debug(f"WS message: {msg_type} {channel}")
        
        if channel == 'ORDERBOOK':
            await self._handle_orderbook_update(data)
        elif channel == 'TRADES':
            await self._handle_trade_update(data)
        elif channel == 'MARKET':
            await self._handle_market_update(data)
        elif msg_type == 'ERROR':
            logger.error(f"WS error: {data.get('message')}")
    
    async def _handle_orderbook_update(self, data: Dict):
        """Process orderbook update."""
        market_id = data.get('market', '')
        timestamp = data.get('timestamp', 0) / 1000  # Convert ms to seconds
        
        # Parse bids/asks
        bids = [(float(b['price']), float(b['size'])) for b in data.get('bids', [])]
        asks = [(float(a['price']), float(a['size'])) for a in data.get('asks', [])]
        
        snapshot = WSOrderbookSnapshot(
            market_id=market_id,
            timestamp=timestamp,
            bids=bids,
            asks=asks,
        )
        
        self._orderbooks[market_id] = snapshot
        
        # Trigger callbacks
        for callback in self._orderbook_callbacks.get(market_id, []):
            try:
                callback(snapshot)
            except Exception as e:
                logger.error(f"Orderbook callback error: {e}")
    
    async def _handle_trade_update(self, data: Dict):
        """Process trade update."""
        market_id = data.get('market', '')
        
        trade = WSTradeUpdate(
            market_id=market_id,
            timestamp=data.get('timestamp', 0) / 1000,
            side=data.get('side', ''),
            price=float(data.get('price', 0)),
            size=float(data.get('size', 0)),
            trade_id=data.get('tradeId'),
        )
        
        # Trigger callbacks
        for callback in self._trade_callbacks.get(market_id, []):
            try:
                callback(trade)
            except Exception as e:
                logger.error(f"Trade callback error: {e}")
    
    async def _handle_market_update(self, data: Dict):
        """Process market ticker update."""
        market_id = data.get('market', '')
        
        update = WSMarketUpdate(
            market_id=market_id,
            timestamp=data.get('timestamp', 0) / 1000,
            best_bid=float(data.get('bestBid', 0)),
            best_ask=float(data.get('bestAsk', 0)),
            last_price=float(data['lastPrice']) if 'lastPrice' in data else None,
            volume_24h=float(data['volume24h']) if 'volume24h' in data else None,
        )
        
        # Trigger callbacks
        for callback in self._market_callbacks.get(market_id, []):
            try:
                callback(update)
            except Exception as e:
                logger.error(f"Market callback error: {e}")
    
    async def _attempt_reconnect(self):
        """Attempt to reconnect."""
        self._reconnect_count += 1
        logger.warning(f"Reconnecting... (attempt {self._reconnect_count}/{self.max_reconnect_attempts})")
        
        await asyncio.sleep(self.reconnect_interval)
        
        if await self.connect():
            # Resubscribe to previous channels
            logger.info("Reconnected, resubscribing to channels...")
            for market_id in self._orderbook_callbacks.keys():
                await self.subscribe_orderbook(market_id)
            for market_id in self._trade_callbacks.keys():
                await self.subscribe_trades(market_id)
            for market_id in self._market_callbacks.keys():
                await self.subscribe_market(market_id)
    
    def get_orderbook(self, market_id: str) -> Optional[WSOrderbookSnapshot]:
        """Get current cached orderbook for market."""
        return self._orderbooks.get(market_id)
    
    def get_spread(self, market_id: str) -> Optional[float]:
        """Get current bid-ask spread."""
        ob = self._orderbooks.get(market_id)
        if ob and ob.bids and ob.asks:
            return ob.asks[0][0] - ob.bids[0][0]
        return None
    
    def get_mid_price(self, market_id: str) -> Optional[float]:
        """Get mid price (average of best bid/ask)."""
        ob = self._orderbooks.get(market_id)
        if ob and ob.bids and ob.asks:
            return (ob.bids[0][0] + ob.asks[0][0]) / 2
        return None


class WebSocketPriceFeed:
    """High-level WebSocket price feed for BTC markets.
    
    Simplified interface for the bot to get real-time prices
    without handling low-level WebSocket details.
    """
    
    def __init__(self, ws_client: PolymarketWebSocketClient):
        """Initialize with WebSocket client."""
        self.ws = ws_client
        self._latest_prices: Dict[str, float] = {}
        self._price_callbacks: List[Callable] = []
        
    async def start_btc_feed(self):
        """Start streaming BTC market prices."""
        # This would need actual BTC market IDs
        # For now, placeholder for implementation
        logger.info("BTC WebSocket price feed started")
    
    def on_price_update(self, callback: Callable):
        """Register callback for price updates."""
        self._price_callbacks.append(callback)
    
    def get_latest_price(self, market_id: str) -> Optional[float]:
        """Get latest mid price for market."""
        return self._latest_prices.get(market_id)
    
    def _handle_price_update(self, update: WSMarketUpdate):
        """Internal handler for price updates."""
        mid_price = (update.best_bid + update.best_ask) / 2
        self._latest_prices[update.market_id] = mid_price
        
        for callback in self._price_callbacks:
            try:
                callback(update.market_id, mid_price)
            except Exception as e:
                logger.error(f"Price callback error: {e}")


# Example usage
async def example():
    """Example usage of WebSocket client."""
    
    ws_client = PolymarketWebSocketClient()
    
    # Connect
    if await ws_client.connect():
        
        # Subscribe to a market
        market_id = "btc-updown-15m-12345"  # Example
        
        def on_orderbook(ob: WSOrderbookSnapshot):
            print(f"Orderbook update: {ob.bids[:3]} / {ob.asks[:3]}")
        
        def on_trade(trade: WSTradeUpdate):
            print(f"Trade: {trade.side} {trade.size} @ {trade.price}")
        
        await ws_client.subscribe_orderbook(market_id, on_orderbook)
        await ws_client.subscribe_trades(market_id, on_trade)
        
        # Keep running
        await asyncio.sleep(60)
        
        # Cleanup
        await ws_client.disconnect()


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example())
