# Polymarket Bot Repository Research Report

**Date:** 2026-04-04  
**Purpose:** Research-only analysis of 3 GitHub repositories for strategy integration into polymarket-timesfm-bot  
**Status:** RESEARCH ONLY - No code modifications made

---

## Executive Summary

This report analyzes three GitHub repositories to extract techniques for improving our BTC 15-minute prediction market trading bot:

1. **bs-p (polymarket-kernel)** - Academic Rust/C kernel for prediction market microstructure
2. **polymarket-assistant-tool** - Real-time dashboard combining Binance + Polymarket data  
3. **polymarket-bot (Chinese)** - Complete auto-trading implementation

**Key Findings:**
- The Chinese bot (sdohuajia) is the most directly useful - it's a working auto-trader for BTC 15-min markets
- The assistant-tool provides excellent WebSocket implementations for real-time data
- The bs-p kernel provides sophisticated academic frameworks (Kelly sizing, logit-space math) but requires significant adaptation

---

## Section 1: Repository Summaries

### 1.1 REPO: holypolyfoundation/bs-p (polymarket-kernel)

**URL:** https://github.com/holypolyfoundation/bs-p  
**Language:** Rust + C with AVX-512 SIMD optimization  
**Focus:** Ultra-low latency market-making kernel for prediction markets

**What It Does:**
- Implements Avellaneda-Stoikov quoting in LOGIT SPACE (probabilities → log-odds)
- Provides implied belief volatility calibration from bid/ask spreads
- Offers Kelly criterion position sizing for maker/taker clips
- Computes order book microstructure metrics (OBI, VWM, pressure)
- Aggregates cross-market portfolio Greeks

**Key Files:**
- `c_src/kernel.c` - Core sigmoid/logit transformations and quote calculation
- `c_src/analytics.c` - Implied volatility, Kelly sizing, OBI/VWM calculations
- `src/lib.rs` - Rust FFI bindings
- `src/analytics.rs` - High-level analytics API
- `src/ring_buffer.rs` - Lock-free SPSC ring buffer for market data

**Code Quality Assessment:**
- **Excellent** - Production-grade, numerically stable, zero hot-path allocations
- Well-documented with academic paper reference
- Benchmark: 6.71 ns/market for quote calculation
- Uses proper numerical clamping to avoid logit singularities

**What We Can Use:**
- The mathematical formulas (logit/sigmoid transformations)
- Kelly sizing formula
- OBI and VWM calculations
- Greeks (delta, gamma) in logit space

**What Needs Adaptation:**
- Cannot use Rust/C directly - must translate to Python
- Market-making focus differs from our directional trading
- Over-engineered for single-market 15-min trading

---

### 1.2 REPO: FiatFiorino/polymarket-assistant-tool

**URL:** https://github.com/FiatFiorino/polymarket-assistant-tool  
**Language:** Python 3.10+  
**Focus:** Real-time terminal dashboard for BTC/ETH/SOL/XRP prediction markets

**What It Does:**
- Streams live trades and orderbook from Binance via WebSocket
- Fetches Up/Down token prices from Polymarket via WebSocket
- Calculates 11 indicators: OBI, CVD (1m/3m/5m), Delta, Volume Profile, RSI, MACD, VWAP, EMA cross, Heikin Ashi
- Aggregates into BULLISH/BEARISH/NEUTRAL trend score
- Sends Telegram notifications for trend changes

**Key Files:**
- `main.py` - Entry point, dashboard loop, trend detection
- `src/feeds.py` - Binance WebSocket, Polymarket WebSocket, market discovery
- `src/indicators.py` - All 11 indicator calculations
- `src/dashboard.py` - Rich terminal rendering
- `src/config.py` - Market slug patterns, API URLs

**Code Quality Assessment:**
- **Good** - Clean async code, proper WebSocket handling with reconnect
- Well-structured with separate concerns
- Uses `rich` library for excellent terminal output
- Some hardcoded values but acceptable for a tool

**What We Can Use:**
- Binance WebSocket implementation (directly reusable)
- Polymarket WebSocket for token prices
- CVD calculation (exact formula)
- OBI calculation
- Trend score aggregation logic
- Market slug generation pattern

**What Needs Adaptation:**
- Add support for 15-minute specific timeframe
- Integrate with our TimesFM momentum scoring
- Remove multi-coin complexity (we only need BTC)

---

### 1.3 REPO: sdohuajia/polymarket-bot (Chinese)

**URL:** https://github.com/sdohuajia/polymarket-bot  
**Language:** Python (Chinese comments)  
**Focus:** Complete BTC 15-minute auto-trading bot

**What It Does:**
- **EXACTLY WHAT WE'RE BUILDING** - A working auto-trader for BTC 15-min markets
- Monitors BTC price via Chainlink WebSocket + Binance fallback
- Gets PTB (Price To Beat) from Polymarket crypto-price API
- Gets Up/Down token prices via WebSocket
- Auto-trades when conditions met (configurable triggers)
- Implements stop-loss and take-profit
- Auto-redeems winning tokens via Polymarket Builder API
- Web dashboard at localhost:5080

**Key Files:**
- `polymarket_auto_trade.py` - 2437 lines, complete trading system
- `config.env` - Configuration template
- `static/dashboard.html` - Web UI

**Code Quality Assessment:**
- **Functional but messy** - Single 2400+ line file
- Chinese comments require translation
- Has some bugs (mentions issues with PTB caching)
- Good error handling and reconnection logic
- Comprehensive but needs refactoring

**What We Can Use:**
- **EVERYTHING** - This is a complete implementation of our target
- py-clob-client order placement code
- Stop-loss execution logic
- Auto-redeem implementation
- WebSocket data handling
- Web dashboard structure
- Configuration file format

**What Needs Adaptation:**
- Split into modules
- Fix PTB caching bug
- Integrate our TimesFM scoring
- Add our Strategy 1/3 conditions

---

## Section 2: Key Techniques Extracted

### 2.1 Logit-Space Price Transformation (from bs-p)

**Source:** `c_src/kernel.c` lines 31-62

**How It Works:**
Prediction market prices are probabilities p ∈ (0,1). Direct diffusion is inconvenient due to boundary constraints. Transform to log-odds (logit):

```
x = log(p / (1-p))      # logit transformation
p = 1 / (1 + exp(-x))   # sigmoid transformation
```

This maps probabilities to the full real line x ∈ (-∞, +∞), enabling standard stochastic calculus.

**Python Implementation:**

```python
import numpy as np

def sigmoid(x: float) -> float:
    """Transform logit to probability."""
    x = np.clip(x, -700, 700)  # Prevent overflow
    return 1.0 / (1.0 + np.exp(-x))

def logit(p: float) -> float:
    """Transform probability to logit."""
    p = np.clip(p, 1e-12, 1.0 - 1e-12)  # Avoid log(0)
    return np.log(p / (1.0 - p))

def batch_sigmoid(x_arr: np.ndarray) -> np.ndarray:
    """Vectorized sigmoid."""
    return 1.0 / (1.0 + np.exp(-np.clip(x_arr, -700, 700)))

def batch_logit(p_arr: np.ndarray) -> np.ndarray:
    """Vectorized logit."""
    p_clipped = np.clip(p_arr, 1e-12, 1.0 - 1e-12)
    return np.log(p_clipped / (1.0 - p_clipped))
```

**Application to Our Strategy:**
- Transform token prices (0-1) to logit space for more stable comparisons
- Greeks (delta, gamma) in logit space show sensitivity better than probability space
- **Rating: 6/10** - Useful for advanced analytics but not critical for basic trading

---

### 2.2 Implied Belief Volatility (from bs-p)

**Source:** `c_src/analytics.c` lines 58-101

**How It Works:**
Given observed market spread, calibrate the implied "belief volatility" σ_b that would produce that spread under the quoting model:

```
Δ_x^mkt = logit(ask) - logit(bid)  # Observed spread in logit space
Δ_x^model(σ_b) = γ·τ·σ_b² + (2/k)·ln(1 + γ/k)  # Model spread

Solve: f(σ_b) = Δ_x^model - Δ_x^mkt = 0
Using Newton-Raphson: σ_{n+1} = max(0, σ_n - f(σ_n)/f'(σ_n))
where f'(σ) = 2·γ·τ·σ
```

**Python Implementation:**

```python
def implied_belief_volatility(bid_p: float, ask_p: float, 
                               gamma: float = 0.08, 
                               tau: float = 0.5, 
                               k: float = 1.4,
                               max_iters: int = 4) -> float:
    """
    Calibrate implied belief volatility from bid/ask spread.
    
    Args:
        bid_p: Bid probability (0-1)
        ask_p: Ask probability (0-1)
        gamma: Risk aversion parameter
        tau: Time to resolution (fraction of interval)
        k: Order arrival rate parameter
    
    Returns:
        Implied belief volatility σ_b
    """
    if ask_p <= bid_p or gamma <= 1e-9 or tau <= 1e-9:
        return 0.0
    
    target_spread = logit(ask_p) - logit(bid_p)
    two_non_linear = 2.0 * np.log1p(gamma / k) / k
    gamma_tau = max(1e-9, gamma * tau)
    
    # Initial guess
    sigma = np.sqrt(max(0.0, (target_spread - two_non_linear) / gamma_tau))
    
    # Newton-Raphson iteration
    for _ in range(max_iters):
        f = gamma_tau * sigma * sigma + two_non_linear - target_spread
        fp = max(1e-9, 2.0 * gamma_tau * sigma)
        sigma = max(0.0, sigma - f / fp)
    
    return sigma
```

**Application to Our Strategy:**
- Measure market uncertainty from spread width
- Wide spread = high uncertainty = avoid trade
- Narrow spread = confident market = safer entry
- **Rating: 7/10** - Good risk filter before entering trades

---

### 2.3 Avellaneda-Stoikov Quoting in Logit Space (from bs-p)

**Source:** `c_src/kernel.c` lines 110-144

**How It Works:**
For market-making, calculate optimal bid/ask quotes accounting for inventory:

```
# Reservation quote (inventory-adjusted fair value)
r_x = x_t - q_t · γ · σ_b² · τ

# Half-spread
δ_x = 0.5 · γ · σ_b² · τ + (1/k) · ln(1 + γ/k)

# Quotes in logit space
bid_x = r_x - δ_x
ask_x = r_x + δ_x

# Convert back to probability
bid_p = sigmoid(bid_x)
ask_p = sigmoid(ask_x)
```

**Python Implementation:**

```python
def calculate_quotes_logit(x_t: float, q_t: float, sigma_b: float,
                          gamma: float = 0.08, tau: float = 0.5,
                          k: float = 1.4) -> tuple[float, float]:
    """
    Calculate market-making quotes in logit space.
    
    Args:
        x_t: Current logit mid
        q_t: Current inventory (positive = long)
        sigma_b: Belief volatility
        gamma: Risk aversion
        tau: Time to resolution
        k: Order arrival rate
    
    Returns:
        (bid_p, ask_p) in probability space
    """
    gamma = max(0.0, gamma)
    tau = max(0.0, tau)
    k = max(1e-12, k)
    
    sigma2 = sigma_b * sigma_b
    risk_term = gamma * sigma2 * tau
    
    # Reservation quote (inventory shifts fair value)
    r_x = x_t - q_t * risk_term
    
    # Half-spread (risk compensation + adverse selection)
    delta_x = 0.5 * risk_term + np.log1p(gamma / k) / k
    
    bid_x = r_x - delta_x
    ask_x = r_x + delta_x
    
    return sigmoid(bid_x), sigmoid(ask_x)
```

**Application to Our Strategy:**
- Less relevant for directional trading
- Could inform position sizing based on inventory risk
- **Rating: 4/10** - Over-engineered for our use case

---

### 2.4 Kelly Criterion Position Sizing (from bs-p)

**Source:** `c_src/analytics.c` lines 421-463

**How It Works:**
Kelly sizing determines optimal bet size based on edge and variance:

```
# Edge vs market
e = p_user - p_market

# Variance of binary outcome
v = p_market · (1 - p_market)

# Kelly fraction
f* = e / v

# Apply risk limits and inventory scaling
inventory_scale = 1 / (1 + γ·|q_t|)
taker_clip = clamp(f* · risk_limit · inventory_scale, -max_clip, +max_clip)
maker_clip = clamp(0.5 · taker_clip, short_limit, long_limit)
```

**Python Implementation:**

```python
def kelly_sizing(belief_p: float, market_p: float, 
                 current_position: float = 0.0,
                 gamma: float = 0.08,
                 risk_limit: float = 100.0,
                 max_clip: float = 50.0) -> tuple[float, float]:
    """
    Calculate Kelly-optimal position sizing.
    
    Args:
        belief_p: Your estimated probability (0-1)
        market_p: Current market price (0-1)
        current_position: Current position size (USDC)
        gamma: Risk aversion parameter
        risk_limit: Maximum risk per position
        max_clip: Maximum clip size
    
    Returns:
        (maker_clip, taker_clip) in USDC
    """
    belief_p = np.clip(belief_p, 1e-12, 1.0 - 1e-12)
    market_p = np.clip(market_p, 1e-12, 1.0 - 1e-12)
    
    # Edge and variance
    edge = belief_p - market_p
    variance = market_p * (1.0 - market_p)
    
    # Kelly fraction
    kelly_frac = edge / max(variance, 1e-12)
    
    # Inventory scaling (reduce size when already positioned)
    inventory_scale = 1.0 / (1.0 + gamma * abs(current_position))
    
    # Raw taker size
    taker = kelly_frac * risk_limit * inventory_scale
    taker = np.clip(taker, -max_clip, max_clip)
    
    # Position limits
    long_limit = risk_limit - current_position
    short_limit = -risk_limit - current_position
    
    taker = np.clip(taker, short_limit, long_limit)
    maker = np.clip(0.5 * taker, short_limit, long_limit)
    
    return maker, taker
```

**Application to Our Strategy:**
- **HIGHLY USEFUL** - Direct application to position sizing
- When we have high conviction (large edge), bet bigger
- When already positioned, reduce new bets
- **Rating: 9/10** - Should implement immediately

---

### 2.5 OBI - Order Book Imbalance (from assistant-tool)

**Source:** `src/indicators.py` lines 5-10

**How It Works:**
Calculate buying vs selling pressure from order book:

```python
def obi(bids, asks, mid, band_pct=1.0):
    """
    Order Book Imbalance - measures buy/sell pressure.
    
    Args:
        bids: List of (price, volume) for bids
        asks: List of (price, volume) for asks
        mid: Current mid price
        band_pct: Percentage band around mid to consider
    
    Returns:
        OBI value in range [-1, +1]
    """
    band = mid * band_pct / 100
    bid_vol = sum(q for p, q in bids if p >= mid - band)
    ask_vol = sum(q for p, q in asks if p <= mid + band)
    total = bid_vol + ask_vol
    return (bid_vol - ask_vol) / total if total else 0.0
```

**Application to Our Strategy:**
- Positive OBI = buying pressure, supports UP
- Negative OBI = selling pressure, supports DOWN
- Use as confirmation signal for our token price disagreement
- **Rating: 8/10** - Very useful for entry timing

---

### 2.6 CVD - Cumulative Volume Delta (from assistant-tool)

**Source:** `src/indicators.py` lines 36-42

**How It Works:**
Track net buying vs selling volume over time windows:

```python
def cvd(trades, window_secs):
    """
    Cumulative Volume Delta - net buy/sell volume.
    
    Args:
        trades: List of trade dicts with 't', 'price', 'qty', 'is_buy'
        window_secs: Time window in seconds
    
    Returns:
        Net volume in quote currency (positive = buying)
    """
    cutoff = time.time() - window_secs
    return sum(
        t['qty'] * t['price'] * (1 if t['is_buy'] else -1)
        for t in trades
        if t['t'] >= cutoff
    )
```

**Application to Our Strategy:**
- **Critical for timing** - shows actual buying/selling pressure
- CVD 1m for short-term momentum
- CVD 5m for trend confirmation
- Positive CVD + BTC > PTB = strong UP signal
- **Rating: 9/10** - Essential for entry timing

---

### 2.7 Trend Score Aggregation (from assistant-tool)

**Source:** `src/dashboard.py` lines 39-87 and `src/indicators.py` lines 132-207

**How It Works:**
Weighted combination of all indicators into single score:

```python
# Weights from config.py
BIAS_WEIGHTS = {
    'ema': 10,    # EMA5/EMA20 cross - strongest trend proxy
    'obi': 8,     # Order Book Imbalance
    'macd': 8,    # MACD histogram sign
    'cvd': 7,     # CVD 5m sign
    'ha': 6,      # Heikin-Ashi streak (up to 3 candles)
    'vwap': 5,    # Price vs VWAP
    'rsi': 5,     # RSI overbought/oversold
    'poc': 3,     # Price vs POC
    'walls': 4,   # bid walls - ask walls
}

def bias_score(bids, asks, mid, trades, klines) -> float:
    """
    Calculate weighted bias score.
    
    Returns:
        Score in [-100, +100], positive = bullish
    """
    W = BIAS_WEIGHTS
    total = 0.0
    
    # EMA cross
    es, el = emas(klines)
    if es and el:
        total += W['ema'] if es > el else -W['ema']
    
    # OBI
    if mid:
        obi_v = obi(bids, asks, mid)
        total += obi_v * W['obi']
    
    # MACD histogram
    _, _, hv = macd(klines)
    if hv is not None:
        total += W['macd'] if hv > 0 else -W['macd']
    
    # CVD 5m
    cvd5 = cvd(trades, 300)
    if cvd5 != 0:
        total += W['cvd'] if cvd5 > 0 else -W['cvd']
    
    # ... more indicators ...
    
    max_possible = sum(W.values())  # 56
    return np.clip((total / max_possible) * 100, -100, 100)
```

**Application to Our Strategy:**
- Combine multiple signals into one actionable score
- Use as confidence multiplier for Kelly sizing
- **Rating: 8/10** - Good framework for signal integration

---

### 2.8 Binance WebSocket Implementation (from assistant-tool + polymarket-bot)

**Source:** `src/feeds.py` lines 47-102 and `polymarket_auto_trade.py`

**How It Works:**

```python
import asyncio
import json
import websockets

BINANCE_WS = "wss://stream.binance.com/stream"

async def binance_feed(symbol: str, state):
    """
    Stream live trades and klines from Binance.
    
    Args:
        symbol: e.g., "BTCUSDT"
        state: Shared state object to update
    """
    sym = symbol.lower()
    streams = "/".join([
        f"{sym}@trade",
        f"{sym}@kline_1m",
    ])
    url = f"{BINANCE_WS}?streams={streams}"
    
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=60,
                close_timeout=10
            ) as ws:
                print(f"[Binance WS] connected - {symbol}")
                
                while True:
                    data = json.loads(await ws.recv())
                    stream = data.get("stream", "")
                    payload = data["data"]
                    
                    if "@trade" in stream:
                        state.trades.append({
                            "t": payload["T"] / 1000.0,
                            "price": float(payload["p"]),
                            "qty": float(payload["q"]),
                            "is_buy": not payload["m"],  # m=True = seller is maker
                        })
                        # Trim old trades
                        if len(state.trades) > 5000:
                            cutoff = time.time() - 600
                            state.trades = [t for t in state.trades if t["t"] >= cutoff]
                    
                    elif "@kline" in stream:
                        k = payload["k"]
                        candle = {
                            "t": k["t"] / 1000.0,
                            "o": float(k["o"]),
                            "h": float(k["h"]),
                            "l": float(k["l"]),
                            "c": float(k["c"]),
                            "v": float(k["v"]),
                        }
                        state.cur_kline = candle
                        if k["x"]:  # Candle closed
                            state.klines.append(candle)
                            state.klines = state.klines[-150:]
        
        except websockets.exceptions.ConnectionClosed:
            print("[Binance WS] connection closed, reconnecting...")
        except Exception as e:
            print(f"[Binance WS] error: {e}, reconnecting in 5s...")
            await asyncio.sleep(5)
```

**Application to Our Strategy:**
- **Replace our REST polling with WebSocket**
- Much lower latency, better for timing
- Already working code we can adapt
- **Rating: 10/10** - Essential upgrade

---

### 2.9 Trigger Condition System (from polymarket-bot)

**Source:** `polymarket_auto_trade.py` lines 2014-2053

**How It Works:**
Configurable conditions with time remaining and price gap thresholds:

```python
# From config.env
C1_TIME = 120      # Condition 1: remaining <= 120 seconds
C1_DIFF = 30       # Gap >= $30
C1_MIN_PROB = 0.80 # UP probability 80%-92%
C1_MAX_PROB = 0.92

C3_TIME = 60       # Condition 3: remaining <= 60 seconds
C3_DIFF = 50       # Gap >= $50
C3_MIN_PROB = 0.80
C3_MAX_PROB = 0.92

# Evaluation logic
def check_conditions(remaining, diff, up_price, down_price):
    """
    Check if any trading condition is met.
    
    Returns:
        (triggered, side, condition_name) or (False, None, None)
    """
    # Condition 1: Strong UP signal with time
    if remaining <= C1_TIME and diff >= C1_DIFF:
        if C1_MIN_PROB <= up_price <= C1_MAX_PROB:
            return True, "UP", f"Condition 1: {remaining}s left, gap=${diff}, UP={up_price:.1%}"
    
    # Condition 3: Very strong UP signal, little time
    if remaining <= C3_TIME and diff >= C3_DIFF:
        if C3_MIN_PROB <= up_price <= C3_MAX_PROB:
            return True, "UP", f"Condition 3: {remaining}s left, gap=${diff}, UP={up_price:.1%}"
    
    # Similar for DOWN conditions...
    
    return False, None, None
```

**Application to Our Strategy:**
- Already similar to our Strategy 1/3
- Can add more conditions based on CVD/OBI
- **Rating: 8/10** - Good foundation

---

### 2.10 Stop-Loss Execution (from polymarket-bot)

**Source:** `polymarket_auto_trade.py` lines 2390-2426

**How It Works:**

```python
# Stop loss triggered when probability drops 15% from entry
STOP_LOSS_PROB_PCT = 0.15

def check_stop_loss(position, current_prob):
    """
    Check if stop-loss should be triggered.
    
    Args:
        position: dict with 'entry_price' (probability)
        current_prob: Current token price
    
    Returns:
        True if stop-loss should trigger
    """
    entry_prob = position['entry_price']
    stop_prob = entry_prob * (1.0 - STOP_LOSS_PROB_PCT)
    
    return current_prob <= stop_prob

def execute_stop_loss(trader, position, market, current_prob):
    """Execute stop-loss sell."""
    side = position['side']
    
    # Use bid price for immediate execution
    sell_price = market['up_bid'] if side == "UP" else market['down_bid']
    sell_token = market['up_token'] if side == "UP" else market['down_token']
    size = position['size']
    
    # Cancel any existing take-profit orders
    if position.get('take_profit_order'):
        trader.cancel_order(position['take_profit_order'])
    
    # Execute market sell
    order_id = trader.place_order(sell_token, "SELL", sell_price, size)
    
    return order_id
```

**Application to Our Strategy:**
- **Essential for risk management**
- Probability-based stop loss makes sense for binary markets
- **Rating: 9/10** - Must implement

---

### 2.11 Auto-Redeem Winning Tokens (from polymarket-bot)

**Source:** `polymarket_auto_trade.py` lines 1537-1710

**How It Works:**

```python
from py_builder_relayer_client.client import RelayClient

class AutoRedeemer:
    """Automatically redeem winning prediction market tokens."""
    
    def __init__(self, private_key, funder_address):
        self.relayer_client = RelayClient(
            "https://relayer-v2.polymarket.com",
            137,  # Polygon chain ID
            private_key,
            builder_config
        )
    
    def _redeem_condition(self, condition_id: str):
        """
        Redeem winning tokens for a resolved condition.
        
        Args:
            condition_id: The condition ID (bytes32)
        """
        ctf_addr = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
        usdc_addr = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
        
        # Encode the redeem call
        contract = w3.eth.contract(
            address=ctf_addr,
            abi=[{
                "name": "redeemPositions",
                "type": "function",
                "inputs": [
                    {"name": "collateralToken", "type": "address"},
                    {"name": "parentCollectionId", "type": "bytes32"},
                    {"name": "conditionId", "type": "bytes32"},
                    {"name": "indexSets", "type": "uint256[]"},
                ],
            }]
        )
        
        cond_bytes = bytes.fromhex(condition_id[2:])
        data = contract.encode_abi(
            abi_element_identifier="redeemPositions",
            args=[usdc_addr, b"\x00" * 32, cond_bytes, [1, 2]]
        )
        
        tx = SafeTransaction(to=str(ctf_addr), data=str(data), value="0")
        resp = self.relayer_client.execute([tx], f"Redeem {condition_id}")
        result = resp.wait()
        
        return result
```

**Application to Our Strategy:**
- **Important for full automation**
- Winning tokens must be claimed manually otherwise
- Requires Polymarket Builder API keys
- **Rating: 8/10** - Implement after basic trading works

---

### 2.12 Web Dashboard (from polymarket-bot)

**Source:** `static/dashboard.html` + Flask routes in main script

**How It Works:**

```python
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

@app.route("/")
def dashboard_index():
    return send_from_directory("static", "dashboard.html")

@app.route("/api/status")
def dashboard_status():
    return jsonify({
        "market": {...},
        "prices": {...},
        "position": {...},
        "trade_history": [...],
    })

@app.route("/api/stream")
def dashboard_stream():
    """Server-sent events for real-time updates."""
    def generate():
        while True:
            with dashboard_cond:
                dashboard_cond.wait(timeout=15)
                yield f"event: status\ndata: {json.dumps(dashboard_state)}\n\n"
    
    return Response(generate(), mimetype="text/event-stream")

# Start web server
def start_web_server():
    app.run(host="0.0.0.0", port=5080, threaded=True)
```

**Application to Our Strategy:**
- **Very useful for monitoring**
- Clean UI for manual trading
- Real-time updates via SSE
- **Rating: 7/10** - Nice to have, not critical

---

## Section 3: Enhanced Strategy Proposal

### 3.1 Entry Conditions

Combine multiple signals into confident entries:

```
IF ALL of these are true:
  1. BTC_price > PTB + $20 (price gap signal)
  2. UP_token_price < 0.55 (market undervaluing UP)
  3. time_remaining > 5min (sufficient time)
  4. CVD_5m > threshold (buy pressure confirmed)
  5. OBI > 0.1 (order book confirms)
  6. TimesFM_momentum_score > 0.6
  7. implied_volatility < threshold (market not too uncertain)
  
THEN:
  - Signal strength = weighted average of all factors
  - Position size = Kelly_sizing(signal_strength, current_position)
  - Entry type: limit order at current ask price
```

### 3.2 Exit Conditions

Multi-tier exit strategy:

```
Take-Profit:
  - If probability reaches 95%+ with time remaining
  - Use limit sell at bid price

Stop-Loss:
  - If probability drops 15% from entry
  - Market sell at bid price

Time-Based Exit:
  - If <30 seconds remaining and position exists
  - Close position at market price

Signal Reversal:
  - If CVD flips opposite direction
  - If OBI flips opposite direction
  - Consider early exit
```

### 3.3 Position Sizing

Kelly criterion with safety limits:

```python
def calculate_position_size(edge: float, volatility: float, 
                           capital: float = 1000.0,
                           max_position: float = 100.0,
                           current_position: float = 0.0) -> float:
    """
    Kelly sizing with practical limits.
    
    Args:
        edge: Expected edge (e.g., 0.05 for 5% edge)
        volatility: Implied belief volatility
        capital: Total trading capital
        max_position: Maximum single position
        current_position: Current position (positive or negative)
    
    Returns:
        Position size in USDC
    """
    # Kelly fraction
    variance = edge * (1 - edge)  # Binary variance approximation
    kelly = edge / variance if variance > 0 else 0
    
    # Half-Kelly for safety
    half_kelly = kelly / 2
    
    # Scale by remaining risk budget
    risk_budget = capital - abs(current_position)
    
    # Apply limits
    size = min(half_kelly * risk_budget, max_position)
    size = max(0, size)  # No negative sizes for directional trades
    
    return size
```

### 3.4 Risk Management

Daily and per-window limits:

```
- Max daily loss: 5% of capital
- Max per-window loss: 2% of capital
- Max consecutive losses: 3 (then pause 1 hour)
- Max position age: 14 minutes (must exit before window closes)
- Min time between trades: 30 seconds (avoid over-trading)
```

### 3.5 Data Feeds Required

```
Primary:
1. Binance WebSocket - BTC trades + orderbook (real-time)
2. Polymarket WebSocket - UP/DOWN token prices (real-time)
3. Polymarket Gamma API - market metadata (on startup, then cache)

Secondary:
4. CoinGecko API - PTB historical price (once per window)
5. Polymarket CLOB API - token IDs, orderbook depth (on startup)

Optional:
6. Chainlink price feed - settlement price reference
```

### 3.6 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    POLYMARKET-TIMESFM-BOT                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │   Binance   │    │ Polymarket  │    │   CoinGecko │         │
│  │  WebSocket  │    │  WebSocket  │    │     API     │         │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘         │
│         │                  │                   │                 │
│         ▼                  ▼                   ▼                 │
│  ┌─────────────────────────────────────────────────────┐       │
│  │                    DATA LAYER                        │       │
│  │  - BTC trades (real-time)                           │       │
│  │  - BTC orderbook (real-time)                        │       │
│  │  - UP/DOWN prices (real-time)                       │       │
│  │  - PTB (cached per window)                          │       │
│  └─────────────────────────────────────────────────────┘       │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐       │
│  │                 INDICATOR LAYER                      │       │
│  │  - CVD (1m, 3m, 5m)                                 │       │
│  │  - OBI                                              │       │
│  │  - TimesFM momentum/volatility                      │       │
│  │  - Implied belief volatility                        │       │
│  │  - Price gap (BTC - PTB)                            │       │
│  └─────────────────────────────────────────────────────┘       │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐       │
│  │                 SIGNAL LAYER                         │       │
│  │  - Strategy 1 check (gap>$20, up<$0.55, time>5min)  │       │
│  │  - Strategy 3 check (gap>$50, up<$0.95, time<3min)  │       │
│  │  - CVD/OBI confirmation                             │       │
│  │  - Signal aggregation + confidence                  │       │
│  └─────────────────────────────────────────────────────┘       │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐       │
│  │               POSITION SIZING                        │       │
│  │  - Kelly criterion                                  │       │
│  │  - Risk limits (daily, per-window)                  │       │
│  │  - Inventory adjustment                             │       │
│  └─────────────────────────────────────────────────────┘       │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐       │
│  │               TRADE EXECUTION                        │       │
│  │  - py-clob-client order placement                   │       │
│  │  - Order monitoring                                 │       │
│  │  - Stop-loss execution                              │       │
│  │  - Auto-redeem                                      │       │
│  └─────────────────────────────────────────────────────┘       │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐       │
│  │                 LOGGING                              │       │
│  │  - CSV observations                                 │       │
│  │  - Trade history                                    │       │
│  │  - Performance tracking                             │       │
│  └─────────────────────────────────────────────────────┘       │
│                                                                  │
│  ┌─────────────────────────────────────────────────────┐       │
│  │              WEB DASHBOARD (Optional)               │       │
│  │  - Flask server on port 5080                        │       │
│  │  - Real-time SSE updates                            │       │
│  │  - Manual trading interface                         │       │
│  └─────────────────────────────────────────────────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Section 4: Integration Priority Matrix

| Rank | Technique | Effort | Value | Dependencies | Recommended Order |
|------|-----------|--------|-------|--------------|-------------------|
| 1 | Binance WebSocket | Medium | High | None | **Phase 2** (immediate) |
| 2 | CVD Calculation | Easy | High | Binance WS | **Phase 2** |
| 3 | OBI Calculation | Easy | High | Binance WS | **Phase 2** |
| 4 | Stop-Loss Execution | Medium | High | py-clob-client | **Phase 2** |
| 5 | Kelly Position Sizing | Easy | High | None | **Phase 2** |
| 6 | Trend Score Aggregation | Medium | Medium | CVD, OBI | **Phase 3** |
| 7 | Polymarket WebSocket | Medium | Medium | None | **Phase 2** |
| 8 | py-clob-client Integration | Medium | High | None | **Phase 2** |
| 9 | Implied Belief Volatility | Easy | Medium | Logit transform | **Phase 3** |
| 10 | Auto-Redeem | Medium | Medium | py-clob-client, Builder API | **Phase 4** |
| 11 | Logit/Sigmoid Transform | Easy | Low | None | **Phase 3** |
| 12 | Web Dashboard | Hard | Low | Everything else | **Phase 4** |
| 13 | Avellaneda-Stoikov | Hard | Low | Logit, Kelly | **Skip** |

---

## Section 5: Code Snippets to Reuse

### 5.1 Binance WebSocket with Reconnect

```python
import asyncio
import json
import websockets
from datetime import datetime

class BinanceWebSocket:
    """Binance WebSocket client with automatic reconnection."""
    
    WS_URL = "wss://stream.binance.com/stream"
    
    def __init__(self, symbol: str = "btcusdt"):
        self.symbol = symbol.lower()
        self.trades = []
        self.orderbook = {"bids": [], "asks": []}
        self.running = False
        
    async def connect(self):
        """Connect and maintain WebSocket connection."""
        streams = "/".join([
            f"{self.symbol}@trade",
            f"{self.symbol}@depth@100ms",
        ])
        url = f"{self.WS_URL}?streams={streams}"
        
        self.running = True
        while self.running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=60,
                ) as ws:
                    print(f"[Binance] Connected to {self.symbol}")
                    
                    async for message in ws:
                        await self._handle_message(json.loads(message))
                        
            except websockets.exceptions.ConnectionClosed:
                print("[Binance] Reconnecting...")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[Binance] Error: {e}")
                await asyncio.sleep(5)
    
    async def _handle_message(self, data: dict):
        """Process incoming WebSocket message."""
        stream = data.get("stream", "")
        payload = data.get("data", {})
        
        if "@trade" in stream:
            self.trades.append({
                "timestamp": payload["T"] / 1000,
                "price": float(payload["p"]),
                "quantity": float(payload["q"]),
                "is_buyer_maker": payload["m"],  # True = sell
            })
            # Keep last 1000 trades
            self.trades = self.trades[-1000:]
            
        elif "@depth" in stream:
            # Delta orderbook update
            for bid in payload.get("b", []):
                self._update_level("bids", bid)
            for ask in payload.get("a", []):
                self._update_level("asks", ask)
    
    def _update_level(self, side: str, level: list):
        """Update orderbook level."""
        price, qty = float(level[0]), float(level[1])
        book = self.orderbook[side]
        
        if qty == 0:
            # Remove level
            self.orderbook[side] = [l for l in book if l[0] != price]
        else:
            # Update or add level
            found = False
            for i, (p, q) in enumerate(book):
                if p == price:
                    book[i] = (price, qty)
                    found = True
                    break
            if not found:
                book.append((price, qty))
                book.sort(reverse=(side == "bids"))
    
    def get_cvd(self, window_secs: int) -> float:
        """Calculate CVD for time window."""
        cutoff = datetime.now().timestamp() - window_secs
        return sum(
            t["quantity"] * t["price"] * (-1 if t["is_buyer_maker"] else 1)
            for t in self.trades
            if t["timestamp"] >= cutoff
        )
    
    def get_obi(self, band_pct: float = 1.0) -> float:
        """Calculate Order Book Imbalance."""
        if not self.orderbook["bids"] or not self.orderbook["asks"]:
            return 0.0
        
        best_bid = self.orderbook["bids"][0][0]
        best_ask = self.orderbook["asks"][0][0]
        mid = (best_bid + best_ask) / 2
        band = mid * band_pct / 100
        
        bid_vol = sum(q for p, q in self.orderbook["bids"] if p >= mid - band)
        ask_vol = sum(q for p, q in self.orderbook["asks"] if p <= mid + band)
        total = bid_vol + ask_vol
        
        return (bid_vol - ask_vol) / total if total else 0.0
    
    def stop(self):
        """Stop the WebSocket connection."""
        self.running = False
```

### 5.2 Polymarket WebSocket for Token Prices

```python
import asyncio
import json
import websockets

class PolymarketWebSocket:
    """Polymarket WebSocket for real-time token prices."""
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(self, up_token: str, down_token: str):
        self.up_token = up_token
        self.down_token = down_token
        self.up_price = None
        self.down_price = None
        self.running = False
        
    async def connect(self):
        """Connect and subscribe to token updates."""
        self.running = True
        
        while self.running:
            try:
                async with websockets.connect(
                    self.WS_URL,
                    ping_interval=20,
                    ping_timeout=60,
                ) as ws:
                    # Subscribe to tokens
                    await ws.send(json.dumps({
                        "assets_ids": [self.up_token, self.down_token],
                        "type": "market"
                    }))
                    
                    print("[Polymarket] Connected")
                    
                    async for message in ws:
                        await self._handle_message(json.loads(message))
                        
            except websockets.exceptions.ConnectionClosed:
                print("[Polymarket] Reconnecting...")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[Polymarket] Error: {e}")
                await asyncio.sleep(5)
    
    async def _handle_message(self, data):
        """Process price updates."""
        # Handle initial snapshot
        if isinstance(data, list):
            for entry in data:
                self._update_price(entry.get("asset_id"), entry.get("asks", []))
        
        # Handle streaming updates
        elif data.get("event_type") == "price_change":
            for change in data.get("price_changes", []):
                if change.get("best_ask"):
                    self._update_price(change["asset_id"], float(change["best_ask"]))
    
    def _update_price(self, asset_id: str, price_data):
        """Update token price."""
        if asset_id == self.up_token:
            if isinstance(price_data, list) and price_data:
                self.up_price = min(float(a["price"]) for a in price_data)
            else:
                self.up_price = price_data
        elif asset_id == self.down_token:
            if isinstance(price_data, list) and price_data:
                self.down_price = min(float(a["price"]) for a in price_data)
            else:
                self.down_price = price_data
    
    def stop(self):
        self.running = False
```

### 5.3 py-clob-client Order Placement

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

class PolymarketTrader:
    """Execute trades on Polymarket using py-clob-client."""
    
    def __init__(self, host: str = "https://clob.polymarket.com", chain_id: int = 137):
        self.client = ClobClient(host, chain_id)
        self.host = host
        
    def place_order(self, token_id: str, side: str, price: float, 
                    size: float) -> str:
        """
        Place a limit order.
        
        Args:
            token_id: CLOB token ID
            side: "BUY" or "SELL"
            price: Limit price (0-1 probability)
            size: Position size in tokens
        
        Returns:
            Order ID
        """
        order_args = OrderArgs(
            price=price,
            size=size,
            side=side,
            token_id=token_id,
        )
        
        try:
            resp = self.client.create_order(order_args)
            order_id = resp.get("orderID") or resp.get("id")
            print(f"[Trade] {side} {size} @ {price:.4f} - Order: {order_id}")
            return order_id
        except Exception as e:
            print(f"[Trade Error] {e}")
            return None
    
    def get_order_status(self, order_id: str) -> dict:
        """Check order status."""
        try:
            order = self.client.get_order(order_id)
            return {
                "status": order.get("status"),
                "filled": order.get("status") == "LIVE",
                "size_matched": float(order.get("size_matched", 0)),
                "price": float(order.get("original_price", 0)),
            }
        except Exception as e:
            print(f"[Order Status Error] {e}")
            return {}
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            self.client.cancel_order(order_id)
            return True
        except Exception as e:
            print(f"[Cancel Error] {e}")
            return False
```

### 5.4 Kelly Sizing Formula

```python
import numpy as np

def kelly_position_size(edge: float, probability: float, 
                        capital: float = 1000.0,
                        max_fraction: float = 0.25,
                        current_position: float = 0.0) -> float:
    """
    Calculate Kelly-optimal position size.
    
    Args:
        edge: Expected edge (your probability - market probability)
        probability: Market probability (0-1)
        capital: Total trading capital
        max_fraction: Maximum fraction of capital to risk (default 25%)
        current_position: Current position size
    
    Returns:
        Position size in base currency
    """
    # Clamp inputs
    probability = np.clip(probability, 0.01, 0.99)
    
    # Variance of binary outcome
    variance = probability * (1 - probability)
    
    # Kelly fraction: f* = edge / variance
    if variance < 1e-9:
        return 0.0
    
    kelly = edge / variance
    
    # Half-Kelly for safety (reduces variance dramatically)
    half_kelly = kelly / 2
    
    # Apply max fraction cap
    fraction = np.clip(half_kelly, 0, max_fraction)
    
    # Calculate position size
    available = capital - abs(current_position)
    position_size = fraction * available
    
    # Minimum position size (avoid dust)
    if position_size < 1.0:
        return 0.0
    
    return position_size


def calculate_stop_loss(entry_price: float, stop_loss_pct: float = 0.15) -> float:
    """
    Calculate stop-loss price level.
    
    Args:
        entry_price: Entry probability (0-1)
        stop_loss_pct: Stop loss percentage (default 15%)
    
    Returns:
        Stop-loss probability level
    """
    return entry_price * (1.0 - stop_loss_pct)


def calculate_take_profit(entry_price: float, stop_loss_pct: float = 0.15,
                         risk_reward: float = 1.0,
                         max_price: float = 0.99) -> float:
    """
    Calculate take-profit price level.
    
    Args:
        entry_price: Entry probability
        stop_loss_pct: Stop loss percentage
        risk_reward: Desired risk/reward ratio
        max_price: Maximum probability cap
    
    Returns:
        Take-profit probability level
    """
    risk = entry_price * stop_loss_pct
    reward = risk * risk_reward
    tp_price = entry_price + reward
    return min(tp_price, max_price)
```

### 5.5 Logit/Sigmoid Transformations

```python
import numpy as np

def sigmoid(x: np.ndarray) -> np.ndarray:
    """
    Transform logit to probability.
    
    Args:
        x: Logit values (any real number)
    
    Returns:
        Probabilities in (0, 1)
    """
    x = np.clip(x, -700, 700)  # Prevent overflow
    return 1.0 / (1.0 + np.exp(-x))


def logit(p: np.ndarray) -> np.ndarray:
    """
    Transform probability to logit.
    
    Args:
        p: Probabilities in (0, 1)
    
    Returns:
        Logit values (any real number)
    """
    p = np.clip(p, 1e-12, 1.0 - 1e-12)
    return np.log(p / (1.0 - p))


def logit_delta(p: np.ndarray) -> np.ndarray:
    """
    Delta (first derivative of sigmoid) in logit space.
    
    Measures how sensitive probability is to changes in logit.
    
    Args:
        p: Probabilities in (0, 1)
    
    Returns:
        Delta values (maximum at p=0.5)
    """
    return p * (1.0 - p)


def logit_gamma(p: np.ndarray) -> np.ndarray:
    """
    Gamma (second derivative of sigmoid) in logit space.
    
    Measures curvature/concavity.
    
    Args:
        p: Probabilities in (0, 1)
    
    Returns:
        Gamma values
    """
    delta = logit_delta(p)
    return delta * (1.0 - 2.0 * p)
```

---

## Section 6: What to Avoid / What Doesn't Work

### 6.1 Over-Engineered Techniques

**Avellaneda-Stoikov Market Making:**
- Designed for market makers, not directional traders
- Requires continuous quoting, not applicable to 15-min windows
- **Skip unless we pivot to market-making**

**AVX-512 SIMD Optimization:**
- bs-p uses C with AVX-512 for 6.71ns/market
- Python can't achieve this performance
- Overkill for 30-second polling
- **Skip - not needed for our use case**

**Cross-Market Portfolio Greeks:**
- Only useful when trading multiple markets simultaneously
- We focus on single BTC 15-min market
- **Skip for now, consider later if scaling**

### 6.2 Code Quality Issues Found

**Chinese Bot (sdohuajia):**
- Single 2400+ line file - needs refactoring
- PTB caching bug (caches to 0.0 on failure)
- Hardcoded values should be configurable
- Chinese comments require translation
- ANSI codes break in non-terminal environments

**Assistant Tool:**
- Some hardcoded thresholds (threshold=3 for trend)
- Limited to specific timeframes
- No auto-trading capability

**bs-p:**
- Rust/C stack not usable directly
- Requires translation to Python

### 6.3 Conflicting Strategies

**Market Making vs Directional Trading:**
- bs-p is market-making focused
- Our strategy is directional
- Some techniques (Kelly sizing) work for both
- Others (spread optimization) don't apply

**Multi-Asset vs Single-Asset:**
- Assistant-tool supports BTC/ETH/SOL/XRP
- We only need BTC
- Simplify by removing multi-asset code

### 6.4 Missing Features We Still Need

1. **PTB API Integration:**
   - Chinese bot uses `polymarket.com/api/crypto/crypto-price`
   - We currently use CoinGecko historical
   - Should switch to official API

2. **WebSocket for Token Prices:**
   - Both repos have this
   - We still use REST polling
   - Priority upgrade needed

3. **TimesFM Integration:**
   - Neither repo has ML-based forecasting
   - Our unique advantage
   - Need to combine with CVD/OBI

4. **Backtesting Framework:**
   - Neither repo has proper backtesting
   - We need to build this ourselves

5. **Paper Trading Mode:**
   - Critical for testing before real money
   - Not present in any repo

---

## Conclusion

The three repositories provide complementary value:

1. **bs-p** provides mathematical foundations (Kelly, logit-space, Greeks)
2. **polymarket-assistant-tool** provides real-time data infrastructure
3. **polymarket-bot (Chinese)** provides a complete trading implementation

**Recommended Next Steps:**

1. **Phase 2 (Immediate):**
   - Replace REST polling with Binance WebSocket
   - Add CVD and OBI indicators
   - Integrate py-clob-client for order execution
   - Implement stop-loss logic

2. **Phase 3 (Short-term):**
   - Add Kelly position sizing
   - Implement signal aggregation
   - Add implied volatility filter

3. **Phase 4 (Medium-term):**
   - Build web dashboard
   - Implement auto-redeem
   - Add paper trading mode

**Critical Insight:** The Chinese bot proves that BTC 15-minute trading is viable. Our differentiator is TimesFM momentum scoring combined with better signal aggregation from CVD/OBI data.

---

*End of Report*
