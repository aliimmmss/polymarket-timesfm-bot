
import json, logging, threading, time, ssl
from collections import deque
from typing import Dict, List, Optional, Tuple

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False
    websocket = None

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s | %(levelname)s | %(message)s')

class BinanceBTCWebSocket:
    WS_URL = "wss://stream.binance.com:9443/ws"
    
    def __init__(self, symbol: str = "btcusdt"):
        if not HAS_WEBSOCKET:
            raise ImportError("websocket-client required")
        self.symbol = symbol.lower()
        self._lock = threading.Lock()
        self._price: Optional[float] = None
        self._trades: deque = deque(maxlen=1000)
        self._orderbook: Dict[str, List] = {'bids': [], 'asks': []}
        self._last_update: float = 0.0
        self._ws: Optional[websocket.WebSocketApp] = None
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._reconnect_delay: float = 1.0
        self._max_reconnect_delay: float = 30.0
        logger.info(f"Initialized for {symbol}")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("WebSocket thread started")

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("WebSocket stopped")

    def get_trades(self, seconds: float = 60.0) -> List[Dict]:
        cutoff = time.time() - seconds
        with self._lock:
            return [t for t in self._trades if t['timestamp'] >= cutoff]

    def get_current_price(self):
        with self._lock:
            return self._price

    def _run_loop(self):
        while self._running:
            try:
                self._connect()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            if self._running:
                logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    def _connect(self):
        streams = [f"{self.symbol}@trade", f"{self.symbol}@depth20@100ms"]
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

    def _on_open(self, ws):
        logger.info("WebSocket connected")
        self._reconnect_delay = 1.0

    def _on_message(self, ws, message: str):
        try:
            logger.debug(f"RAW MESSAGE: {message[:200]}")
            msg = json.loads(message)
            if 'stream' in msg and 'data' in msg:
                data = msg['data']
                logger.debug(f"Extracted data: {data.get('e', 'no-event-type')}")
            else:
                data = msg
                logger.debug("No stream envelope, using raw message")
            
            if 'e' in data:
                event_type = data['e']
                logger.info(f"Event: {event_type}")
                if event_type == 'trade':
                    self._handle_trade(data)
                elif event_type == 'depthUpdate':
                    self._handle_depth(data)
                elif 'lastUpdateId' in data:
                    self._handle_depth_snapshot(data)
            else:
                logger.warning(f"Message has no 'e' field: {list(data.keys())}")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    def _handle_trade(self, data: Dict) -> None:
        logger.info(f"TRADE: price={data.get('p')}, qty={data.get('q')}, maker={data.get('m')}")
        trade = {
            'timestamp': data['T'] / 1000.0,
            'price': float(data['p']),
            'qty': float(data['q']),
            'side': 'sell' if data['m'] else 'buy',
            'trade_id': data['t'],
        }
        with self._lock:
            self._trades.append(trade)
            self._price = trade['price']
            self._last_update = time.time()
        logger.info(f"Updated price to ${self._price:.2f}, trades in buffer: {len(self._trades)}")

    def _handle_depth(self, data: Dict) -> None:
        logger.info(f"DEPTH UPDATE: bids={len(data.get('b', []))}, asks={len(data.get('a', []))}")
        with self._lock:
            for bid in data.get('b', []):
                self._update_level('bids', float(bid[0]), float(bid[1]))
            for ask in data.get('a', []):
                self._update_level('asks', float(ask[0]), float(ask[1]))
            self._last_update = time.time()

    def _handle_depth_snapshot(self, data: Dict) -> None:
        logger.info(f"DEPTH SNAPSHOT: bids={len(data.get('bids', []))}, asks={len(data.get('asks', []))}")
        with self._lock:
            self._orderbook['bids'] = [(float(p), float(q)) for p, q in data.get('bids', [])]
            self._orderbook['asks'] = [(float(p), float(q)) for p, q in data.get('asks', [])]
            self._last_update = time.time()

    def _update_level(self, side: str, price: float, qty: float) -> None:
        book = self._orderbook[side]
        if qty == 0:
            self._orderbook[side] = [(p, q) for p, q in book if abs(p - price) > 1e-8]
        else:
            found = False
            for i, (p, q) in enumerate(book):
                if abs(p - price) < 1e-8:
                    book[i] = (price, qty)
                    found = True
                    break
            if not found:
                book.append((price, qty))
            reverse = (side == 'bids')
            self._orderbook[side].sort(key=lambda x: x[0], reverse=reverse)

    def _on_error(self, ws, error):
        logger.error(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self._ws = None

if __name__ == "__main__":
    ws = BinanceBTCWebSocket()
    ws.start()
    try:
        start = time.time()
        while time.time() - start < 20:
            price = ws.get_current_price()
            trades = ws.get_trades(60)
            ob = ws.get_orderbook()
            print(f"[{time.time()-start:.1f}s] Price: {price} | Trades: {len(trades)} | Bids: {len(ob['bids'])} | Asks: {len(ob['asks'])}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        ws.stop()
        print("Test complete")
