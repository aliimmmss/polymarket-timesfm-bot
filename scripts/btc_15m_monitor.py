#!/usr/bin/env python3
"""BTC 15-minute market monitor - Phase 1 (Fixed)

Monitors Polymarket BTC 15-minute Up/Down markets and flags trading opportunities.
Tracks BTC price, PTB (Price To Beat), and token prices every 30 seconds.

Strategies:
- Strategy 1: BTC > PTB by $20+ AND "Up" token < $0.55 AND >5min remaining
- Strategy 3: BTC > PTB by $50+ AND "Up" token < $0.95 AND <3min remaining

FIXES:
- Proper time remaining tracking based on window_start + 900s
- PTB source tracking (CoinGecko vs Chainlink)
- Outcome tracking after market resolution
"""

import sys
import os
import time
import json
import csv
import math
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any, List

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Constants
WINDOW_DURATION_SEC = 900  # 15 minutes
STRATEGY_1_MIN_TIME = 300   # 5 minutes
STRATEGY_3_MAX_TIME = 180   # 3 minutes


@dataclass
class Observation:
    """Single observation data point."""
    timestamp: str
    btc_price: float
    ptb: float
    ptb_source: str  # 'coingecko' or 'chainlink'
    gap: float
    up_token_price: float
    down_token_price: float
    time_remaining_sec: float
    time_remaining_human: str
    window_start_ts: int
    window_end_ts: int
    strategy_1_flag: bool
    strategy_3_flag: bool
    market_slug: str
    market_question: str


@dataclass
class ResolvedMarket:
    """Resolved market outcome for tracking."""
    window_start_ts: int
    window_end_ts: int
    ptb: float
    end_btc_price: float
    actual_outcome: str  # 'Up' or 'Down'
    price_change: float  # end_btc - ptb
    signals_triggered: List[str] = field(default_factory=list)


class BTCPriceSource:
    """Fetch BTC price from multiple sources with fallback."""
    
    COINGECKO_URL = "https://api.coingecko.com/api/v3"
    BINANCE_URL = "https://api.binance.com/api/v3/ticker/price"
    
    def __init__(self, primary: str = "coingecko"):
        self.primary = primary
        self.last_price = None
        self.source_name = primary
    
    def get_price(self) -> Optional[float]:
        """Get current BTC price, trying multiple sources."""
        price = self._fetch_coingecko() if self.primary == "coingecko" else self._fetch_binance()
        
        if price is None:
            price = self._fetch_binance() if self.primary == "coingecko" else self._fetch_coingecko()
        
        if price:
            self.last_price = price
        
        return price or self.last_price
    
    def get_price_at_timestamp(self, timestamp: int) -> tuple[Optional[float], str]:
        """Get BTC price at a specific Unix timestamp.
        
        Returns:
            Tuple of (price, source_name)
        """
        try:
            resp = requests.get(
                f"{self.COINGECKO_URL}/coins/bitcoin/market_chart/range",
                params={
                    'vs_currency': 'usd',
                    'from': timestamp - 60,
                    'to': timestamp + 60,
                },
                timeout=15
            )
            if resp.status_code == 200:
                prices = resp.json().get('prices', [])
                if prices:
                    closest = min(prices, key=lambda p: abs(p[0]/1000 - timestamp))
                    return closest[1], 'coingecko'
        except Exception as e:
            logger.debug(f"Historical price error: {e}")
        
        # Fallback to current price
        price = self.get_price()
        return price, 'coingecko_current' if price else 'unavailable'
    
    def _fetch_coingecko(self) -> Optional[float]:
        """Fetch from CoinGecko."""
        try:
            resp = requests.get(
                f"{self.COINGECKO_URL}/simple/price",
                params={'ids': 'bitcoin', 'vs_currencies': 'usd'},
                timeout=10
            )
            if resp.status_code == 200:
                return float(resp.json()['bitcoin']['usd'])
        except Exception as e:
            logger.debug(f"CoinGecko error: {e}")
        return None
    
    def _fetch_binance(self) -> Optional[float]:
        """Fetch from Binance."""
        try:
            resp = requests.get(
                f"{self.BINANCE_URL}?symbol=BTCUSDT",
                timeout=10
            )
            if resp.status_code == 200:
                return float(resp.json()['price'])
        except Exception as e:
            logger.debug(f"Binance error: {e}")
        return None


def format_time_remaining(seconds: float) -> str:
    """Convert seconds to human-readable format: ' Xm Ys remaining'."""
    if seconds <= 0:
        return "0s (ENDED)"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if mins > 0:
        return f"{mins}m {secs}s remaining"
    return f"{secs}s remaining"


class PolymarketMonitor:
    """Monitor Polymarket BTC 15-minute markets."""
    
    GAMMA_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"
    
    def __init__(self):
        self.current_market: Optional[Dict[str, Any]] = None
        self.up_token_id: Optional[str] = None
        self.down_token_id: Optional[str] = None
        self.window_start_ts: Optional[int] = None
        self.window_end_ts: Optional[int] = None
        self._ptb: Optional[float] = None
        self._ptb_source: str = 'unknown'
        self.resolved_markets: List[ResolvedMarket] = []
    
    def find_current_market(self) -> Optional[Dict[str, Any]]:
        """Find the current active BTC 15-minute market."""
        now = time.time()
        # Current 15-min window start
        current_ts = math.floor(now / WINDOW_DURATION_SEC) * WINDOW_DURATION_SEC
        slug = f"btc-updown-15m-{current_ts}"
        
        try:
            resp = requests.get(
                f"{self.GAMMA_URL}/markets",
                params={'slug': slug},
                timeout=10
            )
            
            if resp.status_code == 200 and resp.json():
                market = resp.json()[0]
                if market.get('active') and not market.get('closed'):
                    # Parse JSON fields if needed
                    if isinstance(market.get('outcomePrices'), str):
                        market['outcomePrices'] = json.loads(market['outcomePrices'])
                    if isinstance(market.get('clobTokenIds'), str):
                        market['clobTokenIds'] = json.loads(market['clobTokenIds'])
                    
                    self.current_market = market
                    self.up_token_id = market['clobTokenIds'][0]
                    self.down_token_id = market['clobTokenIds'][1]
                    self.window_start_ts = current_ts
                    self.window_end_ts = current_ts + WINDOW_DURATION_SEC
                    self._ptb = None  # Reset PTB for new market
                    
                    logger.info(f"Found market: {market['question'][:50]}...")
                    logger.info(f"Window: {datetime.fromtimestamp(current_ts, tz=timezone.utc)} - {datetime.fromtimestamp(self.window_end_ts, tz=timezone.utc)}")
                    return market
        except Exception as e:
            logger.error(f"Error finding market: {e}")
        
        return None
    
    def get_ptb(self) -> tuple[Optional[float], str]:
        """Get Price To Beat (BTC price at window start).
        
        Returns:
            Tuple of (ptb_price, source_name)
        """
        if not self.window_start_ts:
            return None, 'unknown'
        
        # Cache PTB - it doesn't change during the window
        if self._ptb:
            return self._ptb, self._ptb_source
        
        # Fetch BTC price at window start timestamp
        btc_source = BTCPriceSource()
        ptb, source = btc_source.get_price_at_timestamp(self.window_start_ts)
        
        if ptb:
            self._ptb = ptb
            self._ptb_source = source
            logger.info(f"PTB (BTC at window start): ${ptb:,.2f} (source: {source})")
            return self._ptb, self._ptb_source
        
        # Fallback: use current price
        logger.warning("Could not fetch historical PTB, using current price")
        price = btc_source.get_price()
        return price, 'coingecko_current' if price else 'unavailable'
    
    def get_time_remaining(self) -> float:
        """Get seconds remaining until window ends.
        
        Uses window_start_ts + 900s for accurate calculation.
        """
        if not self.window_end_ts:
            return 0
        
        now = time.time()
        remaining = self.window_end_ts - now
        return max(0, remaining)
    
    def get_token_prices(self) -> tuple[Optional[float], Optional[float]]:
        """Get current Up and Down token prices from CLOB."""
        if not self.up_token_id or not self.down_token_id:
            return None, None
        
        up_price = None
        down_price = None
        
        try:
            resp_up = requests.get(
                f"{self.CLOB_URL}/midpoint",
                params={'token_id': self.up_token_id},
                timeout=10
            )
            if resp_up.status_code == 200:
                up_price = float(resp_up.json().get('mid', 0))
        except Exception as e:
            logger.debug(f"Up token price error: {e}")
        
        try:
            resp_down = requests.get(
                f"{self.CLOB_URL}/midpoint",
                params={'token_id': self.down_token_id},
                timeout=10
            )
            if resp_down.status_code == 200:
                down_price = float(resp_down.json().get('mid', 0))
        except Exception as e:
            logger.debug(f"Down token price error: {e}")
        
        return up_price, down_price
    
    def check_resolved_market(self, window_ts: int) -> Optional[Dict[str, Any]]:
        """Check if a previous market has resolved.
        
        Args:
            window_ts: Window start timestamp
            
        Returns:
            Resolved market data or None
        """
        slug = f"btc-updown-15m-{window_ts}"
        
        try:
            resp = requests.get(
                f"{self.GAMMA_URL}/markets",
                params={'slug': slug},
                timeout=10
            )
            
            if resp.status_code == 200 and resp.json():
                market = resp.json()[0]
                if market.get('closed'):
                    # Parse fields
                    if isinstance(market.get('outcomePrices'), str):
                        market['outcomePrices'] = json.loads(market['outcomePrices'])
                    
                    # Determine winner
                    # outcomePrices[0] = Up price, [1] = Down price
                    # If Up wins, outcomePrices[0] should be close to 1.0
                    up_price = float(market['outcomePrices'][0])
                    winner = 'Up' if up_price > 0.5 else 'Down'
                    
                    market['winner'] = winner
                    return market
        except Exception as e:
            logger.debug(f"Error checking resolved market: {e}")
        
        return None


class ObservationLogger:
    """Log observations to CSV for backtesting."""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        today = datetime.now().strftime('%Y%m%d')
        self.csv_path = self.output_dir / f"observations_{today}.csv"
        self.csv_file = None
        self.writer = None
        self._init_csv()
    
    def _init_csv(self):
        """Initialize CSV file with headers."""
        file_exists = self.csv_path.exists()
        self.csv_file = open(self.csv_path, 'a', newline='')
        self.writer = csv.DictWriter(self.csv_file, fieldnames=[
            'timestamp', 'btc_price', 'ptb', 'ptb_source', 'gap',
            'up_token_price', 'down_token_price', 
            'time_remaining_sec', 'time_remaining_human',
            'window_start_ts', 'window_end_ts',
            'strategy_1_flag', 'strategy_3_flag',
            'market_slug', 'market_question'
        ])
        if not file_exists:
            self.writer.writeheader()
            self.csv_file.flush()
    
    def log(self, obs: Observation):
        """Write observation to CSV."""
        self.writer.writerow(asdict(obs))
        self.csv_file.flush()
    
    def close(self):
        """Close CSV file."""
        if self.csv_file:
            self.csv_file.close()


class OutcomeLogger:
    """Log resolved market outcomes for analysis."""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        today = datetime.now().strftime('%Y%m%d')
        self.csv_path = self.output_dir / f"outcomes_{today}.csv"
        self._init_csv()
    
    def _init_csv(self):
        """Initialize CSV file with headers."""
        file_exists = self.csv_path.exists()
        self.file = open(self.csv_path, 'a', newline='')
        self.writer = csv.DictWriter(self.file, fieldnames=[
            'timestamp', 'window_start_ts', 'window_end_ts',
            'ptb', 'end_btc_price', 'price_change',
            'actual_outcome', 'signals_triggered'
        ])
        if not file_exists:
            self.writer.writeheader()
            self.file.flush()
    
    def log(self, resolved: ResolvedMarket):
        """Write resolved market to CSV."""
        self.writer.writerow({
            'timestamp': datetime.now().isoformat(),
            'window_start_ts': resolved.window_start_ts,
            'window_end_ts': resolved.window_end_ts,
            'ptb': resolved.ptb,
            'end_btc_price': resolved.end_btc_price,
            'price_change': resolved.price_change,
            'actual_outcome': resolved.actual_outcome,
            'signals_triggered': ','.join(resolved.signals_triggered)
        })
        self.file.flush()
    
    def close(self):
        if self.file:
            self.file.close()


class Dashboard:
    """Simple terminal dashboard."""
    
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    
    @classmethod
    def clear(cls):
        """Clear terminal."""
        os.system('clear' if os.name == 'posix' else 'cls')
    
    @classmethod
    def render(cls, obs: Observation, source: str, total_obs: int, signals: dict):
        """Render dashboard."""
        print(f"\n{cls.BOLD}{'='*70}{cls.RESET}")
        print(f"{cls.BOLD}   BTC 15-MIN MARKET MONITOR - Phase 1{cls.RESET}")
        print(f"{cls.BOLD}{'='*70}{cls.RESET}\n")
        
        # Market info
        print(f"  Market: {obs.market_question[:60]}...")
        print(f"  Window: {obs.market_slug}")
        
        # Time remaining with color - CRITICAL FIX
        time_sec = obs.time_remaining_sec
        time_human = obs.time_remaining_human
        if time_sec > STRATEGY_1_MIN_TIME:
            time_color = cls.GREEN
        elif time_sec > STRATEGY_3_MAX_TIME:
            time_color = cls.YELLOW
        else:
            time_color = cls.RED
        print(f"  Time: {time_color}{time_human}{cls.RESET}\n")
        
        # Price section
        print(f"{cls.CYAN}{'─'*70}{cls.RESET}")
        print(f"  BTC Price (live):    ${obs.btc_price:,.2f} ({source})")
        print(f"  PTB (window start):  ${obs.ptb:,.2f} ({obs.ptb_source})")
        
        # Gap with color
        gap = obs.gap
        if gap >= 50:
            gap_color = cls.GREEN
        elif gap >= 20:
            gap_color = cls.YELLOW
        elif gap >= 0:
            gap_color = cls.CYAN
        else:
            gap_color = cls.RED
        print(f"  Gap (BTC-PTB):       {gap_color}${gap:+,.2f}{cls.RESET}\n")
        
        # Token prices
        print(f"{cls.CYAN}{'─'*70}{cls.RESET}")
        print(f"  UP Token:   ${obs.up_token_price:.3f} (YES)")
        print(f"  DOWN Token: ${obs.down_token_price:.3f} (NO)\n")
        
        # Strategy signals - NOW WITH TIME CONTEXT
        print(f"{cls.CYAN}{'─'*70}{cls.RESET}")
        print(f"  Strategy Signals:")
        
        # Strategy 1: requires >5min remaining
        s1_status = f"{cls.GREEN}ACTIVE{cls.RESET}" if obs.strategy_1_flag else "inactive"
        print(f"    Strategy 1 (>5min, gap>$20, up<$0.55): [{s1_status}]")
        print(f"      {signals.get('s1_reason', '')}")
        
        # Strategy 3: requires <3min remaining
        s3_status = f"{cls.GREEN}ACTIVE{cls.RESET}" if obs.strategy_3_flag else "inactive"
        print(f"    Strategy 3 (<3min, gap>$50, up<$0.95): [{s3_status}]")
        print(f"      {signals.get('s3_reason', '')}")
        
        # Stats
        print(f"\n{cls.CYAN}{'─'*70}{cls.RESET}")
        print(f"  Observations: {total_obs}  |  Last update: {obs.timestamp}")
        print(f"{cls.BOLD}{'='*70}{cls.RESET}")
        
        # Alert box if signal active
        if obs.strategy_1_flag or obs.strategy_3_flag:
            print(f"\n{cls.BOLD}{cls.GREEN}{'!'*70}{cls.RESET}")
            print(f"{cls.BOLD}{cls.GREEN}   SIGNAL DETECTED - CHECK MARKET!{cls.RESET}")
            print(f"{cls.BOLD}{cls.GREEN}{'!'*70}{cls.RESET}\n")


def evaluate_strategies(obs: Observation) -> dict:
    """Evaluate strategy conditions and return flags with reasons.
    
    CRITICAL: Time remaining is now properly checked.
    """
    signals = {'s1_reason': '', 's3_reason': ''}
    
    time_sec = obs.time_remaining_sec
    time_min = time_sec / 60
    
    # Strategy 1: BTC > PTB by $20+ AND Up token < $0.55 AND >5min remaining
    if obs.gap >= 20 and obs.up_token_price < 0.55 and time_sec > STRATEGY_1_MIN_TIME:
        obs.strategy_1_flag = True
        signals['s1_reason'] = f"✓ gap=${obs.gap:+.0f}>=$20 | ✓ up=${obs.up_token_price:.3f}<$0.55 | ✓ time={time_min:.1f}min>5min"
    else:
        obs.strategy_1_flag = False
        reasons = []
        if obs.gap < 20:
            reasons.append(f"gap=${obs.gap:+.0f}<$20")
        if obs.up_token_price >= 0.55:
            reasons.append(f"up=${obs.up_token_price:.3f}>=$0.55")
        if time_sec <= STRATEGY_1_MIN_TIME:
            reasons.append(f"time={time_min:.1f}min<=5min (FAILS TIME CHECK)")
        signals['s1_reason'] = " | ".join(reasons) if reasons else "conditions met"
    
    # Strategy 3: BTC > PTB by $50+ AND Up token < $0.95 AND <3min remaining
    if obs.gap >= 50 and obs.up_token_price < 0.95 and time_sec < STRATEGY_3_MAX_TIME:
        obs.strategy_3_flag = True
        signals['s3_reason'] = f"✓ gap=${obs.gap:+.0f}>=$50 | ✓ up=${obs.up_token_price:.3f}<$0.95 | ✓ time={time_min:.1f}min<3min"
    else:
        obs.strategy_3_flag = False
        reasons = []
        if obs.gap < 50:
            reasons.append(f"gap=${obs.gap:+.0f}<$50")
        if obs.up_token_price >= 0.95:
            reasons.append(f"up=${obs.up_token_price:.3f}>=$0.95")
        if time_sec >= STRATEGY_3_MAX_TIME:
            reasons.append(f"time={time_min:.1f}min>=3min (FAILS TIME CHECK)")
        signals['s3_reason'] = " | ".join(reasons) if reasons else "conditions met"
    
    return signals


def run_monitor(interval: int = 30, output_dir: str = None):
    """Run the monitor loop."""
    
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "data" / "observations"
    
    btc_source = BTCPriceSource(primary="coingecko")
    polymarket = PolymarketMonitor()
    obs_logger = ObservationLogger(output_dir)
    outcome_logger = OutcomeLogger(output_dir)
    
    total_observations = 0
    last_market_check = 0
    signals_triggered = []  # Track signals for current window
    pending_resolutions = []  # Windows that need resolution checks
    
    logger.info(f"Starting BTC 15-minute market monitor (FIXED VERSION)")
    logger.info(f"Interval: {interval}s | Output: {output_dir}")
    logger.info(f"Strategy 1: gap>=$20, up<$0.55, time>{STRATEGY_1_MIN_TIME}s")
    logger.info(f"Strategy 3: gap>=$50, up<$0.95, time<{STRATEGY_3_MAX_TIME}s")
    logger.info("Press Ctrl+C to stop\n")
    
    try:
        while True:
            now = time.time()
            
            # Check pending resolutions
            resolved_windows = []
            for pending in pending_resolutions:
                window_ts, window_end, ptb, signals = pending
                if now > window_end + 60:  # Wait 1 min after window ends
                    logger.info(f"Re-checking resolution for window {window_ts}...")
                    resolved = polymarket.check_resolved_market(window_ts)
                    if resolved:
                        end_price = btc_source.get_price() or 0
                        price_change = end_price - ptb
                        
                        outcome = ResolvedMarket(
                            window_start_ts=window_ts,
                            window_end_ts=window_end,
                            ptb=ptb,
                            end_btc_price=end_price,
                            actual_outcome=resolved.get('winner', 'Unknown'),
                            price_change=price_change,
                            signals_triggered=signals
                        )
                        outcome_logger.log(outcome)
                        logger.info(f"Window resolved: {outcome.actual_outcome} (price change: ${price_change:+,.2f})")
                        logger.info(f"Signals triggered: {signals}")
                        resolved_windows.append(pending)
            
            # Remove resolved from pending
            for r in resolved_windows:
                pending_resolutions.remove(r)
            
            # Check for new market every 60 seconds
            if now - last_market_check > 60:
                # Check if current window is ending
                if polymarket.window_start_ts and now > polymarket.window_end_ts:
                    # Add to pending resolutions
                    pending_resolutions.append((
                        polymarket.window_start_ts,
                        polymarket.window_end_ts,
                        polymarket._ptb or 0,
                        signals_triggered.copy()
                    ))
                    logger.info(f"Window {polymarket.window_start_ts} ended, added to pending resolutions")
                    
                    # Reset signals for new window
                    signals_triggered = []
                
                # Find new market
                market = polymarket.find_current_market()
                if market:
                    ptb, ptb_source = polymarket.get_ptb()
                    if ptb:
                        logger.info(f"PTB: ${ptb:,.2f} (source: {ptb_source})")
                last_market_check = now
            
            # Skip if no market
            if not polymarket.current_market:
                logger.warning("No active market found, waiting...")
                time.sleep(30)
                continue
            
            # Get BTC price
            btc_price = btc_source.get_price()
            if not btc_price:
                logger.warning("Could not fetch BTC price")
                time.sleep(5)
                continue
            
            # Get PTB
            ptb, ptb_source = polymarket.get_ptb()
            if not ptb:
                logger.warning("Could not get PTB")
                ptb = 0
                ptb_source = 'unavailable'
            
            # Get token prices
            up_price, down_price = polymarket.get_token_prices()
            if up_price is None:
                logger.warning("Could not fetch token prices")
                time.sleep(5)
                continue
            
            # Get time remaining - NOW BASED ON WINDOW CALCULATION
            time_remaining = polymarket.get_time_remaining()
            time_human = format_time_remaining(time_remaining)
            
            # Create observation
            obs = Observation(
                timestamp=datetime.now().isoformat(),
                btc_price=btc_price,
                ptb=ptb,
                ptb_source=ptb_source,
                gap=btc_price - ptb,
                up_token_price=up_price,
                down_token_price=down_price,
                time_remaining_sec=time_remaining,
                time_remaining_human=time_human,
                window_start_ts=polymarket.window_start_ts,
                window_end_ts=polymarket.window_end_ts,
                strategy_1_flag=False,
                strategy_3_flag=False,
                market_slug=polymarket.current_market.get('slug', ''),
                market_question=polymarket.current_market.get('question', '')
            )
            
            # Evaluate strategies
            signals = evaluate_strategies(obs)
            
            # Track signals for this window
            if obs.strategy_1_flag and 'strategy_1' not in signals_triggered:
                signals_triggered.append('strategy_1')
                logger.info(f"STRATEGY 1 TRIGGERED: Gap=${obs.gap:+.0f} | Up=${obs.up_token_price:.3f} | Time={time_human}")
            if obs.strategy_3_flag and 'strategy_3' not in signals_triggered:
                signals_triggered.append('strategy_3')
                logger.info(f"STRATEGY 3 TRIGGERED: Gap=${obs.gap:+.0f} | Up=${obs.up_token_price:.3f} | Time={time_human}")
            
            # Log to CSV
            obs_logger.log(obs)
            total_observations += 1
            
            # Render dashboard
            Dashboard.clear()
            Dashboard.render(obs, btc_source.source_name, total_observations, signals)
            
            # Wait for next interval
            time.sleep(interval)
    
    except KeyboardInterrupt:
        logger.info("\nStopping monitor...")
    finally:
        obs_logger.close()
        outcome_logger.close()
        logger.info(f"Total observations: {total_observations}")
        logger.info(f"Data saved to: {obs_logger.csv_path}")


def main():
    parser = argparse.ArgumentParser(description='BTC 15-minute market monitor (FIXED)')
    parser.add_argument('--interval', '-i', type=int, default=30,
                        help='Polling interval in seconds (default: 30)')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Output directory for observations')
    
    args = parser.parse_args()
    run_monitor(interval=args.interval, output_dir=args.output)


if __name__ == '__main__':
    main()
