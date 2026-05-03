"""Binance WebSocket client for real-time BTC price data.

Based on research from:
- polymarket-assistant-tool/src/feeds.py
- polymarket-bot/polymarket_auto_trade.py

Provides thread-safe access to:
- Current BTC price
- Trade history
- Order book snapshot
"""

import json
import logging
import threading
import time
import ssl
from collections import deque
from typing import Dict, List, Optional, Tuple

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False
    websocket = None

logger = logging.getLogger(__name__)


class BinanceBTCWebSocket:
    """Binance WebSocket client with automatic reconnection.
    
    Streams live trades and orderbook data from Binance.
    Thread-safe access to latest data.
    """
    
    WS_URL = "wss://stream.binance.com:9443/ws"
    
    def __init__(self, symbol: str = "btcusdt"):
        """Initialize WebSocket client.
        
        Args:
            symbol: Trading pair symbol (default: btcusdt)
        """
        if not HAS_WEBSOCKET:
            raise ImportError("websocket-client required: pip install websocket-client")
        
        self.symbol = symbol.lower()
        
        # Current state (protected by lock)
        self._lock = threading.Lock()
        self._price: Optional[float] = None
        self._trades: deque = deque(maxlen=1000)  # Last 1000 trades
        self._orderbook: Dict[str, List] = {'bids': [], 'asks': []}
        self._last_update: float = 0.0
        
        # WebSocket state
        self._ws: Optional[websocket.WebSocketApp] = None
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._reconnect_delay: float = 1.0
        self._max_reconnect_delay: float = 30.0
        
        logger.info(f"BinanceBTCWebSocket initialized for {symbol}")
    
    def start(self) -> None:
        """Start WebSocket in background thread."""
        if self._running:
            logger.warning("WebSocket already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("WebSocket thread started")
    
    def stop(self) -> None:
        """Stop WebSocket gracefully."""
        self._running = False
        if self._ws:
            self._ws.close()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("WebSocket stopped")
    
    def get_current_price(self) -> Optional[float]:
        """Get current BTC price (thread-safe).
        
        Returns:
            Current price or None if not available
        """
        with self._lock:
            return self._price
    
    def get_trades(self, seconds: float = 60.0) -> List[Dict]:
        """Get trades from the last N seconds (thread-safe).
        
        Args:
            seconds: Time window in seconds
        
        Returns:
            List of trade dicts with keys: timestamp, price, qty, side
        """
        cutoff = time.time() - seconds
        with self._lock:
            return [t for t in self._trades if t['timestamp'] >= cutoff]
    
    def get_orderbook(self) -> Dict[str, List[Tuple[float, float]]]:
        """Get current orderbook snapshot (thread-safe).
        
        Returns:
            Dict with 'bids' and 'asks' lists of (price, qty) tuples
        """
        with self._lock:
            return {
                'bids': list(self._orderbook['bids']),
                'asks': list(self._orderbook['asks'])
            }
    
    def get_mid_price(self) -> Optional[float]:
        """Get mid price from orderbook (thread-safe).
        
        Returns:
            Mid price or None if orderbook empty
        """
        with self._lock:
            if self._orderbook['bids'] and self._orderbook['asks']:
                best_bid = self._orderbook['bids'][0][0]
                best_ask = self._orderbook['asks'][0][0]
                return (best_bid + best_ask) / 2
            return None
    
    def _run_loop(self) -> None:
        """Main WebSocket loop with reconnection."""
        while self._running:
            try:
                self._connect()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            
            if self._running:
                # Exponential backoff for reconnection
                logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay
                )
    
    def _connect(self) -> None:
        """Establish WebSocket connection."""
        # Subscribe to trade and depth streams
        streams = [
            f"{self.symbol}@trade",
            f"{self.symbol}@depth20@100ms",
        ]
        url = f"wss://stream.binance.com:9443/stream?streams={self.symbol}@trade/{self.symbol}@depth20@100ms"
        
        logger.info(f"Connecting to {url}")
        
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        
        self._ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
    
    def _on_open(self, ws) -> None:
        """Called when connection opens."""
        logger.info("WebSocket connected")
        self._reconnect_delay = 1.0  # Reset backoff on successful connection
    
    def _on_message(self, ws, message: str) -> None:
        """Process incoming WebSocket message."""
        try:
            msg = json.loads(message)
            # Handle combined stream format: {"stream": "...", "data": {...}}
            if 'stream' in msg and 'data' in msg:
                data = msg['data']
            else:
                data = msg
            
            # Handle trade message
            if 'e' in data and data['e'] == 'trade':
                self._handle_trade(data)
            # Handle depth update
            elif 'e' in data and data['e'] == 'depthUpdate':
                self._handle_depth(data)
            # Handle full depth snapshot
            elif 'lastUpdateId' in data:
                self._handle_depth_snapshot(data)
        
        except json.JSONDecodeError:
            logger.warning("Failed to parse message")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    def _handle_trade(self, data: Dict) -> None:
        """Handle trade message."""
        trade = {
            'timestamp': data['T'] / 1000.0,  # Trade time in seconds
            'price': float(data['p']),
            'qty': float(data['q']),
            'side': 'sell' if data['m'] else 'buy',  # m=True = seller is maker
            'trade_id': data['t'],
        }
        
        with self._lock:
            self._trades.append(trade)
            self._price = trade['price']
            self._last_update = time.time()
    
    def _handle_depth(self, data: Dict) -> None:
        """Handle depth update message."""
        with self._lock:
            # Update bids
            for bid in data.get('b', []):
                self._update_level('bids', float(bid[0]), float(bid[1]))
            
            # Update asks
            for ask in data.get('a', []):
                self._update_level('asks', float(ask[0]), float(ask[1]))
            
            self._last_update = time.time()
    
    def _handle_depth_snapshot(self, data: Dict) -> None:
        """Handle full depth snapshot."""
        with self._lock:
            self._orderbook['bids'] = [
                (float(p), float(q)) for p, q in data.get('bids', [])
            ]
            self._orderbook['asks'] = [
                (float(p), float(q)) for p, q in data.get('asks', [])
            ]
            self._last_update = time.time()
    
    def _update_level(self, side: str, price: float, qty: float) -> None:
        """Update a single orderbook level."""
        book = self._orderbook[side]
        
        if qty == 0:
            # Remove level
            self._orderbook[side] = [
                (p, q) for p, q in book if abs(p - price) > 1e-8
            ]
        else:
            # Update or add level
            found = False
            for i, (p, q) in enumerate(book):
                if abs(p - price) < 1e-8:
                    book[i] = (price, qty)
                    found = True
                    break
            
            if not found:
                book.append((price, qty))
            
            # Sort: bids descending, asks ascending
            reverse = (side == 'bids')
            self._orderbook[side].sort(key=lambda x: x[0], reverse=reverse)
    
    def _on_error(self, ws, error) -> None:
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg) -> None:
        """Handle WebSocket close."""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self._ws = None


# Test function
if __name__ == "__main__":
    import time
    
    logging.basicConfig(level=logging.INFO)
    
    ws = BinanceBTCWebSocket()
    ws.start()
    
    try:
        for i in range(10):
            time.sleep(1)
            price = ws.get_current_price()
            trades = ws.get_trades(60)
            ob = ws.get_orderbook()
            
            print(f"[{i}] Price: ${price:.2f} | Trades: {len(trades)} | Bids: {len(ob['bids'])} | Asks: {len(ob['asks'])}")
    
    finally:
        ws.stop()
        print("Test complete")
