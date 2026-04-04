"""Market indicators for BTC trading.

Based on research from polymarket-assistant-tool/src/indicators.py

Implements:
- CVD (Cumulative Volume Delta): Net buy/sell volume over time windows
- OBI (Order Book Imbalance): Buy vs sell pressure from orderbook
- Trend Scorer: Aggregated trend signal
"""

import logging
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CVDCalculator:
    """Cumulative Volume Delta calculator.
    
    Tracks net buy/sell volume over multiple time windows.
    Positive CVD = buying pressure, Negative CVD = selling pressure.
    """
    
    def __init__(self):
        """Initialize CVD calculator."""
        # Store trades with timestamps
        self._trades: deque = deque(maxlen=5000)
        
        # Cached CVD values
        self._cvd_1m: float = 0.0
        self._cvd_3m: float = 0.0
        self._cvd_5m: float = 0.0
        self._last_update: float = 0.0
    
    def update(self, trade: Dict) -> None:
        """Update CVD with a new trade.
        
        Args:
            trade: Dict with keys:
                - timestamp: Unix timestamp (seconds)
                - price: Trade price
                - qty: Trade quantity
                - side: 'buy' or 'sell'
        """
        self._trades.append({
            't': trade.get('timestamp', time.time()),
            'price': float(trade['price']),
            'qty': float(trade['qty']),
            'is_buy': trade.get('side', 'buy') == 'buy',
        })
        self._last_update = time.time()
    
    def update_from_binance(self, trade_data: Dict) -> None:
        """Update from Binance trade message format.
        
        Args:
            trade_data: Binance trade dict with keys:
                - T: Trade time (milliseconds)
                - p: Price (string)
                - q: Quantity (string)
                - m: Is buyer maker (True = sell, False = buy)
        """
        self._trades.append({
            't': trade_data['T'] / 1000.0,
            'price': float(trade_data['p']),
            'qty': float(trade_data['q']),
            'is_buy': not trade_data.get('m', False),
        })
    
    def get_cvd(self, window_secs: float) -> float:
        """Calculate CVD for a specific time window.
        
        Args:
            window_secs: Time window in seconds
        
        Returns:
            Net volume delta (positive = buying, negative = selling)
        """
        cutoff = time.time() - window_secs
        return sum(
            t['qty'] * t['price'] * (1 if t['is_buy'] else -1)
            for t in self._trades
            if t['t'] >= cutoff
        )
    
    def get_all_cvd(self) -> Dict[str, float]:
        """Get CVD for all standard time windows.
        
        Returns:
            Dict with 'cvd_1m', 'cvd_3m', 'cvd_5m' keys
        """
        return {
            'cvd_1m': self.get_cvd(60),
            'cvd_3m': self.get_cvd(180),
            'cvd_5m': self.get_cvd(300),
        }
    
    def get_trend(self) -> str:
        """Get CVD trend direction.
        
        Returns:
            'bullish', 'bearish', or 'neutral'
        """
        cvd_1m = self.get_cvd(60)
        cvd_5m = self.get_cvd(300)
        
        if cvd_1m > 0 and cvd_5m > 0:
            return 'bullish'
        elif cvd_1m < 0 and cvd_5m < 0:
            return 'bearish'
        else:
            return 'neutral'


class OBICalculator:
    """Order Book Imbalance calculator.
    
    Measures buy vs sell pressure from orderbook depth.
    OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    Range: -1 (all sells) to +1 (all buys)
    """
    
    def __init__(self, levels: int = 5, band_pct: float = 1.0):
        """Initialize OBI calculator.
        
        Args:
            levels: Number of orderbook levels to consider
            band_pct: Percentage band around mid to include (default 1%)
        """
        self.levels = levels
        self.band_pct = band_pct
    
    def calculate(self, orderbook: Dict, mid: Optional[float] = None) -> float:
        """Calculate OBI from orderbook.
        
        Args:
            orderbook: Dict with 'bids' and 'asks' lists of (price, qty)
            mid: Optional mid price (calculated from orderbook if not provided)
        
        Returns:
            OBI value in range [-1, +1]
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return 0.0
        
        # Calculate mid price if not provided
        if mid is None:
            mid = (bids[0][0] + asks[0][0]) / 2
        
        # Calculate band
        band = mid * self.band_pct / 100
        
        # Sum volumes within band
        bid_vol = sum(
            q for p, q in bids[:self.levels]
            if p >= mid - band
        )
        ask_vol = sum(
            q for p, q in asks[:self.levels]
            if p <= mid + band
        )
        
        total = bid_vol + ask_vol
        return (bid_vol - ask_vol) / total if total > 0 else 0.0
    
    def get_trend(self, orderbook: Dict, mid: Optional[float] = None) -> str:
        """Get OBI trend direction.
        
        Returns:
            'bullish' if OBI > 0.1, 'bearish' if OBI < -0.1, else 'neutral'
        """
        obi = self.calculate(orderbook, mid)
        
        if obi > 0.1:
            return 'bullish'
        elif obi < -0.1:
            return 'bearish'
        else:
            return 'neutral'


class TrendScorer:
    """Aggregated trend score calculator.
    
    Combines CVD and OBI into a single trend signal.
    Based on bias_score from polymarket-assistant-tool.
    """
    
    # Weight configuration
    WEIGHTS = {
        'cvd_1m': 3,
        'cvd_5m': 7,
        'obi': 8,
    }
    
    def __init__(self):
        """Initialize trend scorer."""
        self.cvd = CVDCalculator()
        self.obi = OBICalculator()
        self._last_score: Dict = {}
    
    def update(self, trade: Dict, orderbook: Optional[Dict] = None) -> Dict:
        """Update with new trade and optionally orderbook.
        
        Args:
            trade: Trade dict with timestamp, price, qty, side
            orderbook: Optional orderbook dict with bids/asks
        
        Returns:
            Current score dict
        """
        self.cvd.update(trade)
        return self.get_score(orderbook)
    
    def get_score(self, orderbook: Optional[Dict] = None) -> Dict:
        """Calculate current trend score.
        
        Args:
            orderbook: Optional orderbook for OBI calculation
        
        Returns:
            Dict with:
                - cvd_1m, cvd_3m, cvd_5m: CVD values
                - obi: OBI value
                - trend: 'BULLISH', 'BEARISH', or 'NEUTRAL'
                - score: Aggregated score (-100 to +100)
        """
        W = self.WEIGHTS
        
        # Get CVD values
        cvd_vals = self.cvd.get_all_cvd()
        cvd_1m = cvd_vals['cvd_1m']
        cvd_5m = cvd_vals['cvd_5m']
        
        # Calculate score contribution
        total = 0.0
        
        # CVD 1m contribution
        if cvd_1m != 0:
            total += W['cvd_1m'] if cvd_1m > 0 else -W['cvd_1m']
        
        # CVD 5m contribution
        if cvd_5m != 0:
            total += W['cvd_5m'] if cvd_5m > 0 else -W['cvd_5m']
        
        # OBI contribution (if orderbook provided)
        obi_val = 0.0
        if orderbook:
            obi_val = self.obi.calculate(orderbook)
            total += obi_val * W['obi']
        
        # Normalize to [-100, +100]
        max_possible = sum(W.values())
        score = max(-100.0, min(100.0, (total / max_possible) * 100))
        
        # Determine trend
        if score >= 30:
            trend = 'BULLISH'
        elif score <= -30:
            trend = 'BEARISH'
        else:
            trend = 'NEUTRAL'
        
        self._last_score = {
            'cvd_1m': cvd_1m,
            'cvd_3m': cvd_vals['cvd_3m'],
            'cvd_5m': cvd_5m,
            'obi': obi_val,
            'trend': trend,
            'score': score,
        }
        
        return self._last_score
    
    def get_signal_strength(self) -> float:
        """Get signal strength (0-1) based on score magnitude.
        
        Returns:
            Signal strength where higher = more confident
        """
        if not self._last_score:
            return 0.0
        
        return abs(self._last_score.get('score', 0)) / 100.0


# Convenience function for quick analysis
def analyze_market(trades: List[Dict], orderbook: Dict) -> Dict:
    """Analyze market data and return indicators.
    
    Args:
        trades: List of trade dicts
        orderbook: Orderbook dict with bids/asks
    
    Returns:
        Dict with all indicator values
    """
    scorer = TrendScorer()
    
    for trade in trades:
        scorer.cvd.update(trade)
    
    return scorer.get_score(orderbook)


if __name__ == "__main__":
    import random
    
    logging.basicConfig(level=logging.INFO)
    
    # Test the indicators
    scorer = TrendScorer()
    
    # Simulate some trades
    for i in range(100):
        trade = {
            'timestamp': time.time() - (100 - i) * 0.5,
            'price': 85000 + random.uniform(-100, 100),
            'qty': random.uniform(0.001, 0.5),
            'side': 'buy' if random.random() > 0.4 else 'sell',
        }
        ob = {
            'bids': [(85000, random.uniform(0.1, 2.0))],
            'asks': [(85010, random.uniform(0.1, 1.5))],
        }
        scorer.update(trade, ob)
    
    result = scorer.get_score()
    print("Trend Score:", result)
    print("Signal Strength:", scorer.get_signal_strength())