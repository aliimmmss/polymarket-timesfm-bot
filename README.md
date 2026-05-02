# Polymarket BTC 15-Minute Market Bot

Forecasting Bitcoin "Up or Down" 15-minute markets on Polymarket using Google technical indicators.

## What It Does

1. Fetches BTC price history from CoinGecko (hourly, 30 days)
2. Runs technical indicators time series forecasting (200M parameter model)
3. Compares technical indicator-based direction prediction to Polymarket odds
4. Generates BUY_UP / BUY_DOWN / HOLD signals based on disagreement

## How BTC 15-Min Markets Work

Polymarket has Bitcoin "Up or Down" 15-minute markets:
- Markets resolve based on whether BTC/USD price went UP or DOWN in the 15-min window
- Slug pattern: `btc-updown-15m-{UNIX_TIMESTAMP}`
- Timestamps aligned to 900-second boundaries (every 15 min)
- Two outcomes: "Up" and "Down" with token IDs in clobTokenIds
- outcomePrices: ["0.53", "0.47"] - first is Up, second is Down

Example active market:
```
Question: Bitcoin Up or Down - April 3, 10:45PM-11:00PM ET
UP price: 0.155 (15.5% chance market assigns to UP)
DOWN price: 0.845 (84.5% chance market assigns to DOWN)
```

## Setup

```bash
git clone https://github.com/aliimmmss/polymarket-trading-bot.git
cd polymarket-trading-bot
python3 -m venv .venv --python 3.11
source .venv/bin/activate
pip install -r requirements.txt

# technical indicator-based must be installed from source (not on PyPI)
```

## Usage

```bash
source .venv/bin/activate
python scripts/btc_15m_monitor_v2.py --markets 3 --horizon 15
```

Results are saved to `data/logs/` as JSON files.

## Trading Signal Logic

The bot compares:
- **technical indicator-based UP probability**: % of forecasted steps above current price
- **Polymarket UP price**: Market's implied probability

Signal thresholds:
- If technical indicator-based UP prob > Polymarket UP price + 0.15 → **BUY_UP**
- If technical indicator-based UP prob < Polymarket UP price - 0.15 → **BUY_DOWN**
- Otherwise → **HOLD**

## Project Structure

```
src/
  data_collection/
    btc_price_fetcher.py    # CoinGecko BTC price history
    polymarket_client.py    # Polymarket Gamma + CLOB APIs
    btc_websocket.py        # Binance BTC/USDT WebSocket (optional)
  analysis/
    indicators.py           # TPD, CVD, OBI calculations
    signal_aggregator.py   # Signal combination and decision logic
  trading/
    order_executor.py       # CLOB V2 order execution
    enhanced_executor.py   # With circuit breaker + DB persistence
    trade_journal.py       # YAML journaling
    stop_loss.py           # Stop-loss management
    kelly_sizer.py         # Position sizing
  utils/
    db_persistence.py      # SQLite database layer
    monitoring.py          # Prometheus metrics
    circuit_breaker.py    # Trading halt logic
    logger.py             # Logging configuration
scripts/
  btc_15m_monitor_v2.py    # Main bot (monitor + signal)
  btc_15m_monitor.py       # Original monitor (legacy)
  dashboard/
    app.py                 # Flask metrics dashboard
    app_v2.py               # Enhanced dashboard
tests/
  test_btc_fetcher.py
  test_order_executor.py
  test_polymarket_client.py
  test_signal_aggregator.py
docs/
```

## Example Output

```
TRADING SIGNAL:
  technical indicator-based UP probability: 93.3% (14/15 steps)
  Polymarket UP price: 15.5%
  Disagreement: +0.78
  SIGNAL: BUY_UP (confidence: 1.00)
  Action: Market UNDERPRICES upside - consider buying UP token
```

## License

MIT
