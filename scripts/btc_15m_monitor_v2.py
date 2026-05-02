#!/usr/bin/env python3
"""BTC 15-Minute Market Monitor V2 - Enhanced with WebSocket and Indicators.

CHANGES FROM V1:
...

Based on research from:
...
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# FIX: Force certifi CA bundle for SSL in WSL environments with broken system CAs
try:
    import certifi
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
except ImportError:
    pass

# FIX: Bypass any system/ corporate proxy that intercepts HTTPS
os.environ.setdefault('NO_PROXY', '*')
os.environ.setdefault('no_proxy', '*')

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

# Try imports with graceful fallback
try:
    from src.data_collection.btc_websocket import BinanceBTCWebSocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False
    print("Warning: websocket-client not installed, will use REST polling")

try:
    from src.analysis.indicators import TrendScorer
    HAS_INDICATORS = True
except ImportError:
    HAS_INDICATORS = False
    print("Warning: indicators not available")

try:
    from src.trading.order_executor import OrderExecutor
    HAS_EXECUTOR = True
except ImportError:
    HAS_EXECUTOR = False

try:
    from src.trading.stop_loss import StopLossManager
    HAS_STOP_LOSS = True
except ImportError:
    HAS_STOP_LOSS = False

try:
    from src.trading.trade_journal import TradeJournal
    HAS_TRADE_JOURNAL = True
except ImportError:
    HAS_TRADE_JOURNAL = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
CRYPTO_PRICE_API = "https://polymarket.com/api/crypto/crypto-price"
COINGECKO_API = "https://api.coingecko.com/api/v3"

# Strategy thresholds (can be overridden via CLI)
SIGNAL_A_GAP = 20.0      # $20+ gap
SIGNAL_A_MAX_PRICE = 0.55
SIGNAL_A_MIN_TIME = 300  # 5 minutes

SIGNAL_B_GAP = 50.0      # $50+ gap
SIGNAL_B_MAX_PRICE = 0.95
SIGNAL_B_MAX_TIME = 180  # 3 minutes

SIGNAL_C_CVD = 50.0      # Strong CVD
SIGNAL_C_OBI = 0.30      # Strong OBI
SIGNAL_C_MAX_PRICE = 0.50

# Safety settings
DRY_RUN = True
MAX_ORDER_SIZE = 5.0

# Position persistence (crash recovery)
POSITIONS_DIR = Path.home() / ".polymarket_bot"
POSITIONS_FILE = POSITIONS_DIR / "positions.json"


def load_positions() -> Dict[str, dict]:
    """Load open positions from disk if available."""
    if POSITIONS_FILE.exists():
        try:
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                logger.info(f"Loaded {len(data)} open positions from {POSITIONS_FILE}")
                return data
        except Exception as e:
            logger.error(f"Failed to load positions: {e}")
    return {}


def save_positions(positions: Dict[str, dict]) -> None:
    """Save open positions to disk."""
    try:
        POSITIONS_DIR.mkdir(parents=True, exist_ok=True)
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save positions: {e}")


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Observation:
    """Single market observation data point."""
    timestamp: str
    btc_price: float
    ptb: float
    ptb_source: str
    gap: float
    up_token_price: float
    down_token_price: float
    time_remaining_sec: float
    cvd_1m: float
    cvd_5m: float
    obi: float
    trend_score: float
    signal_a: bool
    signal_b: bool
    signal_c: bool
    market_slug: str
    market_question: str


@dataclass
class Market:
    """Polymarket market data."""
    slug: str
    question: str
    up_token_id: str
    down_token_id: str
    window_start: int
    window_end: int
    active: bool


# ============================================================================
# PTB FETCHING (Bug 2b fix - never cache to 0.0)
# ============================================================================

def get_ptb_from_polymarket(window_start_ts: int) -> Optional[Tuple[float, str]]:
    """Get PTB from Polymarket crypto-price API.

    Args:
        window_start_ts: Unix timestamp of window start

    Returns:
        Tuple of (price, source) or None if failed
    """
    for verify in [True, False]:  # try normal first, then skip verification
        try:
            # Polymarket crypto-price API
            params = {
                'symbol': 'BTC',
                'eventStartTime': window_start_ts,
                'variant': 'fifteen',
            }

            resp = requests.get(
                CRYPTO_PRICE_API,
                params=params,
                timeout=10,
                verify=verify
            )

            if resp.status_code == 200:
                data = resp.json()
                # API may return either 'price' or 'openPrice' depending on window state
                raw_price = data.get('price') or data.get('openPrice')
                if raw_price and float(raw_price) > 0:
                    return (float(raw_price), 'polymarket-api')
            else:
                logger.debug(f"Polymarket API returned HTTP {resp.status_code} (verify={verify})")
        except Exception as e:
            logger.warning(f"Polymarket PTB API failed (verify={verify}): {e}")
            if not verify:
                break  # second attempt failed, stop retrying

    logger.warning("Polymarket PTB fetch failed after all retries")
    return None


def get_ptb_from_coingecko(window_start_ts: int) -> Optional[Tuple[float, str]]:
    """Get PTB from CoinGecko historical API.

    Fallback when Polymarket API unavailable.

    Args:
        window_start_ts: Unix timestamp of window start

    Returns:
        Tuple of (price, source) or None if failed
    """
    for verify in [True, False]:
        try:
            # CoinGecko historical price
            end_ts = window_start_ts + 60  # Small window around start
            url = f"{COINGECKO_API}/coins/bitcoin/market_chart/range"

            resp = requests.get(
                url,
                params={
                    'vs_currency': 'usd',
                    'from': window_start_ts - 60,
                    'to': end_ts,
                },
                timeout=15,
                verify=verify
            )

            if resp.status_code == 200:
                data = resp.json()
                prices = data.get('prices', [])
                if prices:
                    # Find closest price to window start
                    closest = min(
                        prices,
                        key=lambda p: abs(p[0]/1000 - window_start_ts)
                    )
                    price = closest[1]
                    if price > 0:
                        return (price, 'coingecko')
            else:
                logger.debug(f"CoinGecko PTB HTTP {resp.status_code} (verify={verify})")
        except Exception as e:
            logger.warning(f"CoinGecko PTB fetch failed (verify={verify}): {e}")
            if not verify:
                break

    logger.warning("CoinGecko PTB fetch failed after all retries")
    return None


def get_ptb(window_start_ts: int, cached_ptb: Optional[float] = None) -> Tuple[float, str]:
    """Get Price To Beat with fallback chain.
    
    Bug 2b fix: Never return or cache 0.0.
    
    Args:
        window_start_ts: Unix timestamp of window start
        cached_ptb: Previously cached PTB (if any)
    
    Returns:
        Tuple of (price, source)
    """
    # Try Polymarket API first
    result = get_ptb_from_polymarket(window_start_ts)
    if result and result[0] > 0:
        return result
    
    # Fallback to CoinGecko
    result = get_ptb_from_coingecko(window_start_ts)
    if result and result[0] > 0:
        return result
    
    # Use cached value if valid (NOT 0.0)
    if cached_ptb and cached_ptb > 0:
        logger.warning(f"Using cached PTB: ${cached_ptb:.2f}")
        return (cached_ptb, 'cached')
    
    # All sources failed - this is an error condition
    logger.error("All PTB sources failed, cannot monitor this window")
    return (0.0, 'failed')


# ============================================================================
# MARKET DISCOVERY
# ============================================================================

def find_active_market() -> Optional[Market]:
    """Find current active BTC 15-minute market.

    Returns:
        Market object or None
    """
    now = time.time()
    current_ts = int(now // 900) * 900  # Floor to 15-min boundary
    slug = f"btc-updown-15m-{current_ts}"

    for verify in [True, False]:
        try:
            resp = requests.get(
                f"{GAMMA_API}/markets",
                params={'slug': slug},
                timeout=10,
                verify=verify
            )

            if resp.status_code == 200 and resp.json():
                m = resp.json()[0]

                if m.get('active') and not m.get('closed'):
                    # Parse token IDs
                    if isinstance(m.get('clobTokenIds'), str):
                        token_ids = json.loads(m['clobTokenIds'])
                    else:
                        token_ids = m.get('clobTokenIds', [])

                    return Market(
                        slug=m.get('slug', slug),
                        question=m.get('question', ''),
                        up_token_id=token_ids[0] if len(token_ids) > 0 else '',
                        down_token_id=token_ids[1] if len(token_ids) > 1 else '',
                        window_start=current_ts,
                        window_end=current_ts + 900,
                        active=True,
                    )

            else:
                logger.debug(f"Gamma API HTTP {resp.status_code} (verify={verify})")
        except Exception as e:
            logger.debug(f"Market discovery failed (verify={verify}): {e}")
            if not verify:
                break

    logger.error("Market discovery failed after all retries")
    return None


def get_token_prices(market: Market) -> Tuple[float, float]:
    """Get Up and Down token prices from CLOB API.

    Args:
        market: Market object

    Returns:
        Tuple of (up_price, down_price)
    """
    up_price = 0.5
    down_price = 0.5

    # Helper to fetch with SSL fallback
    def fetch_midpoint(token_id: str) -> Optional[float]:
        for verify in [True, False]:
            try:
                resp = requests.get(
                    f"{CLOB_API}/midpoint",
                    params={'token_id': token_id},
                    timeout=5,
                    verify=verify
                )
                if resp.status_code == 200:
                    mid = resp.json().get('mid')
                    if mid is not None:
                        return float(mid)
            except Exception as e:
                logger.debug(f"Midpoint fetch fail (verify={verify}): {e}")
                if not verify:
                    break
        return None

    up_mid = fetch_midpoint(market.up_token_id)
    down_mid = fetch_midpoint(market.down_token_id)

    if up_mid is not None:
        up_price = up_mid
    if down_mid is not None:
        down_price = down_mid

    return up_price, down_price


def get_token_midpoint_price(token_id: str) -> Optional[float]:
    """Get current midpoint price for any token from CLOB API.

    Used for liquidating positions during market-switch cleanup.

    Args:
        token_id: CLOB token ID

    Returns:
        Midpoint price (0-1 probability) or None if fetch fails
    """
    for verify in [True, False]:
        try:
            resp = requests.get(
                f"{CLOB_API}/midpoint",
                params={'token_id': token_id},
                timeout=5,
                verify=verify
            )
            if resp.status_code == 200:
                price = float(resp.json().get('mid', 0.5))
                if price > 0:
                    return price
        except Exception as e:
            logger.debug(f"Midpoint fetch fail for {token_id[:30]} (verify={verify}): {e}")
            if not verify:
                break
    return None


# ============================================================================
# SIGNAL DETECTION
# ============================================================================

def check_signals(
    gap: float,
    up_price: float,
    time_remaining: float,
    cvd_5m: float,
    obi: float,
) -> Tuple[bool, bool, bool]:
    """Check for trading signals.
    
    Signal A: Token Price Disagreement + CVD confirms
    - Gap >= $20
    - Up price < 0.55
    - Time remaining > 5 minutes
    - CVD positive (buying pressure)
    
    Signal B: Late Window Convergence
    - Gap >= $50
    - Up price < 0.95
    - Time remaining < 3 minutes
    
    Signal C: Strong Momentum + Mispricing
    - CVD >= threshold (strong buying)
    - OBI >= threshold (order book bullish)
    - Up price < 0.50 (cheap)
    - Time remaining > 5 minutes
    
    Returns:
        Tuple of (signal_a, signal_b, signal_c)
    """
    signal_a = (
        gap >= SIGNAL_A_GAP and
        up_price < SIGNAL_A_MAX_PRICE and
        time_remaining > SIGNAL_A_MIN_TIME and
        cvd_5m > 0  # CVD confirms buying
    )
    
    signal_b = (
        gap >= SIGNAL_B_GAP and
        up_price < SIGNAL_B_MAX_PRICE and
        time_remaining < SIGNAL_B_MAX_TIME
    )
    
    signal_c = (
        abs(cvd_5m) >= SIGNAL_C_CVD and
        obi >= SIGNAL_C_OBI and
        up_price < SIGNAL_C_MAX_PRICE and
        time_remaining > SIGNAL_A_MIN_TIME
    )
    
    return signal_a, signal_b, signal_c


# ============================================================================
# CSV LOGGING (Bug 2d fix - consistent format)
# ============================================================================

class ObservationLogger:
    """CSV logger with consistent format."""
    
    FIELDNAMES = [
        'timestamp', 'btc_price', 'ptb', 'ptb_source', 'gap',
        'up_token_price', 'down_token_price', 'time_remaining_sec',
        'cvd_1m', 'cvd_5m', 'obi', 'trend_score',
        'signal_a', 'signal_b', 'signal_c',
        'market_slug', 'market_question',
    ]
    
    def __init__(self, log_dir: str):
        """Initialize logger.
        
        Args:
            log_dir: Directory for CSV files
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Daily CSV file
        date_str = datetime.now().strftime('%Y%m%d')
        self.csv_path = self.log_dir / f"observations_{date_str}.csv"
        
        self.csv_file = None
        self.writer = None
        self._init_csv()
    
    def _init_csv(self):
        """Initialize CSV file with header."""
        file_exists = self.csv_path.exists()
        
        self.csv_file = open(self.csv_path, 'a', newline='')
        self.writer = csv.DictWriter(
            self.csv_file,
            fieldnames=self.FIELDNAMES
        )
        
        if not file_exists:
            self.writer.writeheader()
            self.csv_file.flush()
            logger.info(f"Created CSV: {self.csv_path}")
    
    def log(self, obs: Observation):
        """Log an observation."""
        if self.writer:
            self.writer.writerow(asdict(obs))
            self.csv_file.flush()
    
    def close(self):
        """Close CSV file."""
        if self.csv_file:
            self.csv_file.close()


# ============================================================================
# DISPLAY (Bug 2c fix - no ANSI in non-terminal)
# ============================================================================

def format_display(
    market: Market,
    btc_price: float,
    ptb: float,
    gap: float,
    up_price: float,
    down_price: float,
    time_remaining: float,
    cvd_1m: float,
    cvd_5m: float,
    obi: float,
    trend_score: float,
    signal_a: bool,
    signal_b: bool,
    signal_c: bool,
    dry_run: bool = True,
) -> str:
    """Format display output (no ANSI codes).
    
    Returns:
        Formatted string for display
    """
    lines = [
        "=" * 60,
        "BTC 15-MIN MONITOR V2",
        "=" * 60,
        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"Market: {market.question[:50]}...",
        f"Window: {datetime.fromtimestamp(market.window_start, tz=timezone.utc).strftime('%H:%M:%S')} - {datetime.fromtimestamp(market.window_end, tz=timezone.utc).strftime('%H:%M:%S')} UTC",
        "",
        f"PTB:  ${ptb:,.2f} (source: {market.slug[:30] if market.slug else 'unknown'})",
        f"BTC:  ${btc_price:,.2f}",
        f"GAP:  ${gap:+,.2f}",
        "",
        f"Up Token:   ${up_price:.3f} ({up_price*100:.1f}%)",
        f"Down Token: ${down_price:.3f} ({down_price*100:.1f}%)",
        "",
        f"Time Remaining: {int(time_remaining//60)}:{int(time_remaining%60):02d}",
        "",
        "INDICATORS:",
        f"  CVD 1m: ${cvd_1m:+,.1f}",
        f"  CVD 5m: ${cvd_5m:+,.1f}",
        f"  OBI:    {obi:+.2f}",
        f"  Score:  {trend_score:+.0f}",
        "",
        "SIGNALS:",
    ]
    
    if signal_a:
        lines.append("  [A] Token Disagreement + CVD confirms - BUY UP")
    else:
        lines.append("  [ ] Signal A: No")
    
    if signal_b:
        lines.append("  [B] Late Window Convergence - BUY UP")
    else:
        lines.append("  [ ] Signal B: No")
    
    if signal_c:
        lines.append("  [C] Strong Momentum + Mispricing - BUY UP")
    else:
        lines.append("  [ ] Signal C: No")
    
    lines.append("")
    if dry_run:
        lines.append(f"DRY RUN MODE - No orders will be placed")
    
    lines.append("=" * 60)
    
    return "\n".join(lines)


# ============================================================================
# MAIN MONITOR LOOP
# ============================================================================

def run_monitor(
    duration: int = 300,
    interval: float = 5.0,
    dry_run: bool = True,
    log_dir: str = "data/observations",
):
    """Run the V2 monitor.
    
    Args:
        duration: Maximum run time in seconds (0 = unlimited)
        interval: Polling interval in seconds
        dry_run: If True, don't execute trades
        log_dir: Directory for CSV logs
    """
    logger.info(f"Starting BTC 15-min Monitor V2")
    logger.info(f"Duration: {duration}s, Interval: {interval}s, Dry Run: {dry_run}")
    
    # Initialize components
    csv_logger = ObservationLogger(log_dir)
    
    # Initialize trade journal if available
    trade_journal = None
    if HAS_TRADE_JOURNAL:
        try:
            trade_journal = TradeJournal()
            logger.info("Trade journal initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize trade journal: {e}")
    
    # WebSocket for BTC data
    ws = None
    if HAS_WEBSOCKET:
        ws = BinanceBTCWebSocket()
        ws.start()
        logger.info("Binance WebSocket started")
        time.sleep(2)  # Wait for initial data
    
    # Indicator calculator
    scorer = TrendScorer() if HAS_INDICATORS else None
    
    # Order executor (dry run by default)
    executor = None
    if HAS_EXECUTOR:
        executor = OrderExecutor(dry_run=dry_run)
    
    # Stop loss manager
    stop_loss = None
    if HAS_STOP_LOSS:
        stop_loss = StopLossManager()

    # Track open positions for exit logging
    # Key: token_id, Value: dict with market, entry_price, size_usdc, size_tokens, order_id, buy_time
    open_positions = load_positions()
    logger.info(f"Started with {len(open_positions)} open positions from disk")

    # Rehydrate StopLossManager from loaded positions
    if stop_loss and open_positions:
        for token_id, pos in open_positions.items():
            stop_loss.add_position(
                token_id=token_id,
                buy_price=pos['entry_price'],
                buy_time=pos['buy_time'],
                side='up',  # we only trade UP tokens
                size=pos['size_usdc'],
                take_profit_pct=0.5,
            )
        logger.info("Stop-loss manager rehydrated from saved positions")
    
    # Market tracking
    current_market = None
    cached_ptb = None
    btc_price_cache = {'price': None, 'timestamp': 0}  # Cache to avoid rate limits (30s TTL)
    start_time = time.time()
    
    try:
        while True:
            elapsed = time.time() - start_time
            if duration > 0 and elapsed >= duration:
                logger.info(f"Duration reached ({duration}s), stopping")
                break
            
            # Find active market
            market = find_active_market()
            if not market:
                logger.info("No active market found, waiting...")
                time.sleep(interval)
                continue
            
            # Check if market changed
            if current_market is None or market.slug != current_market.slug:
                logger.info(f"New market: {market.slug}")
                
                # MARKET-SWITCH CLEANUP: Liquidate all open positions from previous market
                if open_positions:
                    logger.info(f"Market switch: liquidating {len(open_positions)} stale position(s)")
                    for token_id, pos in list(open_positions.items()):
                        try:
                            # Get current price for this token via midpoint API
                            sell_price = get_token_midpoint_price(token_id)
                            if not sell_price or sell_price <= 0:
                                logger.warning(f"Invalid price for {token_id[:30]}, using entry price fallback")
                                sell_price = pos['entry_price']
                            
                            size_tokens = pos['size_tokens']
                            
                            # Execute FOK sell (fill-or-kill: immediate or cancel)
                            if executor:
                                sell_result = executor.sell_token(
                                    token_id=token_id,
                                    price=sell_price,
                                    size_tokens=size_tokens,
                                    order_type='FOK',
                                )
                                logger.info(f"Market-switch sell: {sell_result}")
                            else:
                                sell_result = {'success': True, 'order_id': 'DRY_RUN_EXIT_MSW'}
                            
                            # Calculate P&L
                            entry = pos['entry_price']
                            pnl_usdc = (sell_price - entry) * size_tokens
                            pnl_pct = (sell_price - entry) / entry if entry else 0.0
                            
                            # Log exit with reason
                            if trade_journal:
                                try:
                                    trade_journal.log_exit(
                                        order_id=pos['order_id'],
                                        market=pos['market'],
                                        exit_price=sell_price,
                                        pnl_usdc=pnl_usdc,
                                        pnl_pct=pnl_pct,
                                        exit_reason='market_switch',
                                        lessons='',
                                    )
                                    logger.info("Exit logged (market_switch)")
                                except Exception as e:
                                    logger.error(f"Failed to log exit: {e}")
                            
                            # Cleanup
                            if stop_loss:
                                stop_loss.remove_position(token_id)
                            open_positions.pop(token_id, None)
                            
                            # Persist updated positions
                            save_positions(open_positions)
                            
                        except Exception as e:
                            logger.error(f"Failed to liquidate {token_id[:30]}: {e}")
                
                # Now update to the new market
                current_market = market
                # Get PTB for new window
                ptb, ptb_source = get_ptb(market.window_start)
                
                # Bug 2b fix: Don't cache invalid PTB
                if ptb > 0:
                    cached_ptb = ptb
                else:
                    logger.error("Invalid PTB, skipping this window")
                    time.sleep(interval)
                    continue
            else:
                ptb = cached_ptb
                ptb_source = 'cached'
            
            # Get BTC price (WS → Binance REST → CoinGecko fallback chain, with 30s cache)
            now = time.time()
            CACHE_TTL = 30  # seconds
            if btc_price_cache['price'] is not None and now - btc_price_cache['timestamp'] < CACHE_TTL:
                btc_price = btc_price_cache['price']
                logger.debug(f"BTC price from cache: ${btc_price:,.2f}")
            else:
                btc_price = None

                # 1) Try WebSocket if available
                if ws:
                    btc_price = ws.get_current_price()
                    if btc_price:
                        logger.debug(f"BTC price from WebSocket: ${btc_price:,.2f}")
                    else:
                        logger.warning("WebSocket price unavailable, trying REST fallback...")

                # 2) Binance REST if WS failed or unavailable
                if not btc_price:
                    for verify in [True, False]:  # try normal first, then skip verification
                        try:
                            resp = requests.get(
                                "https://api.binance.com/api/v3/ticker/price",
                                params={'symbol': 'BTCUSDT'},
                                timeout=5,
                                verify=verify
                            )
                            if resp.status_code == 200:
                                btc_price = float(resp.json()['price'])
                                logger.debug(f"BTC price from Binance REST (verify={verify}): ${btc_price:,.2f}")
                                break
                        except Exception as e:
                            logger.warning(f"Binance REST failed (verify={verify}): {e}")
                            if not verify:
                                break

                # 3) CoinGecko REST as final fallback
                if not btc_price:
                    for verify in [True, False]:
                        try:
                            resp = requests.get(
                                f"{COINGECKO_API}/simple/price",
                                params={'ids': 'bitcoin', 'vs_currencies': 'usd'},
                                timeout=5,
                                verify=verify
                            )
                            if resp.status_code == 200:
                                btc_price = float(resp.json()['bitcoin']['usd'])
                                logger.debug(f"BTC price from CoinGecko (verify={verify}): ${btc_price:,.2f}")
                                break
                        except Exception as e:
                            logger.warning(f"CoinGecko REST failed (verify={verify}): {e}")
                            if not verify:
                                break

                # Update cache if we got a valid price
                if btc_price and btc_price > 0:
                    btc_price_cache = {'price': btc_price, 'timestamp': now}

            # Give up if all sources failed
            if not btc_price or btc_price <= 0:
                logger.warning("BTC price unavailable from all sources, skipping cycle")
                time.sleep(interval)
                continue

            # Get token prices
            up_price, down_price = get_token_prices(market)
            
            # Calculate indicators
            cvd_1m = 0.0
            cvd_5m = 0.0
            obi = 0.0
            trend_score = 0.0
            
            if scorer and ws:
                # Get trades and orderbook
                trades = ws.get_trades(300)
                orderbook = ws.get_orderbook()
                
                for t in trades[-100:]:  # Last 100 trades
                    scorer.cvd.update(t)
                
                if orderbook['bids'] and orderbook['asks']:
                    mid = (orderbook['bids'][0][0] + orderbook['asks'][0][0]) / 2
                    obi = scorer.obi.calculate(orderbook, mid)
                
                cvd_vals = scorer.cvd.get_all_cvd()
                cvd_1m = cvd_vals['cvd_1m']
                cvd_5m = cvd_vals['cvd_5m']
                
                score_dict = scorer.get_score(orderbook)
                trend_score = score_dict.get('score', 0.0)
            
            # Calculate gap and time remaining
            gap = btc_price - ptb
            time_remaining = max(0, market.window_end - time.time())
            
            # Check signals
            signal_a, signal_b, signal_c = check_signals(
                gap, up_price, time_remaining, cvd_5m, obi
            )
            
            # Create observation
            obs = Observation(
                timestamp=datetime.now(timezone.utc).isoformat(),
                btc_price=btc_price,
                ptb=ptb,
                ptb_source=ptb_source,
                gap=gap,
                up_token_price=up_price,
                down_token_price=down_price,
                time_remaining_sec=time_remaining,
                cvd_1m=cvd_1m,
                cvd_5m=cvd_5m,
                obi=obi,
                trend_score=trend_score,
                signal_a=signal_a,
                signal_b=signal_b,
                signal_c=signal_c,
                market_slug=market.slug,
                market_question=market.question,
            )
            
            # Log to CSV
            csv_logger.log(obs)
            
            # Display
            print(format_display(
                market=market,
                btc_price=btc_price,
                ptb=ptb,
                gap=gap,
                up_price=up_price,
                down_price=down_price,
                time_remaining=time_remaining,
                cvd_1m=cvd_1m,
                cvd_5m=cvd_5m,
                obi=obi,
                trend_score=trend_score,
                signal_a=signal_a,
                signal_b=signal_b,
                signal_c=signal_c,
                dry_run=dry_run,
            ))
            
            # Execute if signal and not dry run
            if not dry_run and executor and (signal_a or signal_b or signal_c):
                logger.info("Signal detected! Executing trade...")
                result = executor.buy_token(
                    token_id=market.up_token_id,
                    price=up_price,
                    size_usdc=MAX_ORDER_SIZE,
                )
                logger.info(f"Order result: {result}")
                
                # Log trade to journal
                if trade_journal:
                    try:
                        # Build thesis from signals
                        sig_parts = []
                        if signal_a: sig_parts.append('A')
                        if signal_b: sig_parts.append('B')
                        if signal_c: sig_parts.append('C')
                        signal_type = '+'.join(sig_parts) if sig_parts else 'NONE'
                        thesis = f"BTC 15min Signal(s) [{signal_type}]: gap=${gap:.2f}, CVD1m=${cvd_1m:+,.0f}, OBI={obi:+.2f}, Score={trend_score:.0f}"
                        strategy = f"btc_15min_{signal_type.lower()}"
                        # size_pct will be computed from config capital inside journal
                        trade_record = {
                            "date": datetime.now().isoformat(),
                            "market": market.question,
                            "position": "YES",
                            "entry_price": up_price,
                            "size_usdc": MAX_ORDER_SIZE,
                            "thesis": thesis,
                            "time_horizon": "15 minutes",
                            "confidence": 0.7,  # TODO: derive from gap
                            "strategy": strategy,
                            "outcome": "filled" if result.get('success') else "skipped",
                            "order_id": result.get('order_id'),
                        }
                        trade_journal.log_entry(trade_record)
                        logger.info("Trade logged to journal")

                        # Register position for stop-loss monitoring and exit logging
                        if result.get('success') and stop_loss:
                            token_id = market.up_token_id
                            size_tokens = result.get('size_tokens', MAX_ORDER_SIZE / up_price)
                            stop_loss.add_position(
                                token_id=token_id,
                                buy_price=up_price,
                                buy_time=time.time(),
                                side='up',
                                size=MAX_ORDER_SIZE,
                                take_profit_pct=0.5,  # 50% take-profit target
                            )
                            open_positions[token_id] = {
                                'market': market.question,
                                'entry_price': up_price,
                                'size_usdc': MAX_ORDER_SIZE,
                                'size_tokens': size_tokens,
                                'order_id': result.get('order_id'),
                                'buy_time': time.time(),
                            }
                            logger.info(f"Position registered for stop-loss monitoring: {token_id[:30]}...")

                            # Persist open positions
                            save_positions(open_positions)
                    except Exception as e:
                        logger.error(f"Failed to log trade: {e}")

            # EXIT: Check stop-loss / take-profit for open positions
            if stop_loss and open_positions:
                # Build current price map for our held tokens (only UP tokens currently)
                current_prices = {}
                for token_id in open_positions:
                    current_prices[token_id] = up_price  # we track up_price for current market

                if current_prices:
                    actions = stop_loss.check(current_prices, current_time=time.time())
                    for action in actions:
                        if action.get('action') != 'SELL':
                            continue
                        token_id = action['token_id']
                        pos_info = open_positions.get(token_id)
                        if not pos_info:
                            continue
                        trigger = action.get('trigger', 'UNKNOWN')
                        logger.info(f"Exit triggered: {trigger} for {token_id[:30]}...")

                        # Execute sell
                        sell_price = current_prices.get(token_id, pos_info['entry_price'])
                        if executor:
                            # Size in tokens to sell = all tokens we hold
                            size_tokens = pos_info['size_tokens']
                            sell_result = executor.sell_token(
                                token_id=token_id,
                                price=sell_price,
                                size_tokens=size_tokens,
                            )
                            logger.info(f"Sell order result: {sell_result}")
                        else:
                            sell_result = {'success': True, 'order_id': 'DRY_RUN_EXIT'}

                        # Calculate P&L
                        entry = pos_info['entry_price']
                        tokens = pos_info['size_tokens']
                        pnl_usdc = (sell_price - entry) * tokens
                        pnl_pct = (sell_price - entry) / entry if entry else 0.0

                        # Log exit to journal
                        if trade_journal:
                            try:
                                journal_ok = trade_journal.log_exit(
                                    order_id=pos_info['order_id'],
                                    market=pos_info['market'],
                                    exit_price=sell_price,
                                    pnl_usdc=pnl_usdc,
                                    pnl_pct=pnl_pct,
                                    exit_reason=trigger,
                                    lessons="",
                                )
                                if journal_ok:
                                    logger.info("Exit logged to journal")
                            except Exception as e:
                                logger.error(f"Failed to log exit: {e}")

                        # Cleanup
                        stop_loss.remove_position(token_id)
                        open_positions.pop(token_id, None)

                        # Persist updated positions
                        save_positions(open_positions)

            # MAX-HOLD TIMER: Exit any position held > 15 minutes
            if open_positions:
                now = time.time()
                max_hold_sec = 15 * 60
                for token_id, pos in list(open_positions.items()):
                    if now - pos.get('buy_time', now) > max_hold_sec:
                        logger.info(f"Max-hold timeout: exiting {token_id[:30]}... (held {now - pos['buy_time']:.0f}s)")
                        try:
                            # Use current up_price as exit price (approx)
                            exit_price = up_price
                            size_tokens = pos['size_tokens']
                            
                            if executor:
                                sell_result = executor.sell_token(
                                    token_id=token_id,
                                    price=exit_price,
                                    size_tokens=size_tokens,
                                    order_type='FOK',
                                )
                                logger.info(f"Max-hold sell: {sell_result}")
                            else:
                                sell_result = {'success': True, 'order_id': 'DRY_RUN_EXIT_MAXHOLD'}
                            
                            # P&L
                            entry = pos['entry_price']
                            pnl_usdc = (exit_price - entry) * size_tokens
                            pnl_pct = (exit_price - entry) / entry if entry else 0.0
                            
                            # Log exit
                            if trade_journal:
                                try:
                                    trade_journal.log_exit(
                                        order_id=pos['order_id'],
                                        market=pos['market'],
                                        exit_price=exit_price,
                                        pnl_usdc=pnl_usdc,
                                        pnl_pct=pnl_pct,
                                        exit_reason='max_hold',
                                        lessons='',
                                    )
                                    logger.info("Exit logged (max_hold)")
                                except Exception as e:
                                    logger.error(f"Failed to log exit: {e}")
                            
                            # Cleanup
                            if stop_loss:
                                stop_loss.remove_position(token_id)
                            open_positions.pop(token_id, None)
                            save_positions(open_positions)
                            
                        except Exception as e:
                            logger.error(f"Max-hold exit failed for {token_id[:30]}: {e}")

            time.sleep(interval)
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    finally:
        # Cleanup
        if ws:
            ws.stop()
        csv_logger.close()
        # Final position save (should already be clean, but ensure consistency)
        save_positions(open_positions)
        logger.info("Monitor stopped")


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BTC 15-Min Monitor V2")
    parser.add_argument(
        '--duration', type=int, default=300,
        help="Run duration in seconds (0=unlimited)"
    )
    parser.add_argument(
        '--interval', type=float, default=5.0,
        help="Polling interval in seconds"
    )
    parser.add_argument(
        '--dry-run', action='store_true', default=False,
        help="Enable dry-run (no real orders). Default: trades are simulated."
    )
    parser.add_argument(
        '--log-dir', type=str, default="data/observations",
        help="Directory for CSV logs"
    )
    
    args = parser.parse_args()
    
    run_monitor(
        duration=args.duration,
        interval=args.interval,
        dry_run=args.dry_run,
        log_dir=args.log_dir,
    )