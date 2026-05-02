# Polymarket BTC 15-Minute Market Bot

Trading Bitcoin "Up or Down" 15-minute markets on Polymarket using technical indicators.

## What It Does

1. Fetches BTC price history from CoinGecko (hourly, 30 days)
2. Computes technical indicators (TPD, CVD, OBI, time decay) and combines them into trading signals
3. Compares aggregated signal direction and strength to Polymarket odds
4. Generates BUY_UP / BUY_DOWN / HOLD signals based on aggregated confidence

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
```

## Usage

```bash
source .venv/bin/activate
python scripts/btc_15m_monitor_v2.py --duration 300 --interval 5 --dry-run
```

The bot logs observations to `data/observations/` (CSV) and records trades in the YAML trade journal.

## Trading Signal Logic

The bot computes four technical indicators:
- **TPD** (Token Price Disagreement): mispricing between BTC price and Polymarket's PTB
- **CVD** (Cumulative Volume Delta): Binance trade flow momentum
- **OBI** (Order Book Imbalance): real-time orderbook bid/ask pressure
- **Time Decay**: optimal trading window factor

These are combined with weights (TPD 0.35, CVD 0.30, OBI 0.20, time_decay 0.15) into a single confidence score (0–1).

Signal thresholds:
- If confidence ≥ 0.65 and ≥3 signals agree on UP → **BUY_UP**
- If confidence ≥ 0.65 and ≥3 signals agree on DOWN → **BUY_DOWN**
- Otherwise → **HOLD**

## Project Structure

```
src/
  data_collection/
    btc_price_fetcher.py    # CoinGecko BTC price history
    btc_websocket.py        # Binance BTC/USDT WebSocket (optional)
  analysis/
    indicators.py           # TPD, CVD, OBI calculations
    signal_aggregator.py   # Signal combination and decision logic
  trading/
    order_executor.py       # CLOB V2 order execution
    trade_journal.py       # YAML journaling
    stop_loss.py           # Stop-loss management
  utils/
    db_persistence.py      # SQLite database layer
    monitoring.py          # Prometheus metrics
    logger.py             # Logging configuration
scripts/
  btc_15m_monitor_v2.py    # Main bot (monitor + signal)
  dashboard/
    app_v2.py               # Enhanced Flask metrics dashboard
tests/
  test_btc_fetcher.py
  test_order_executor.py
docs/
```

## Example Output

```
BTC 15min Signal(s) [UP]: gap=$+42.50, CVD1m=+1,245, OBI=+0.32, Confidence=0.82
Signal: BUY_UP | Confidence: 0.82 | Market: btc-updown-15m-XXXXX
Trade recorded to journal (dry-run)
```

## License

MIT
