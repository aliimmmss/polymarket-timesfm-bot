# Polymarket BTC 15-Minute Market Bot

Forecasting Bitcoin "Up or Down" 15-minute markets on Polymarket using Google TimesFM 2.5.

## What It Does

1. Fetches BTC price history from CoinGecko (hourly, 30 days)
2. Runs TimesFM 2.5 time series forecasting (200M parameter model)
3. Compares TimesFM direction prediction to Polymarket odds
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
git clone https://github.com/aliimmmss/polymarket-timesfm-bot.git
cd polymarket-timesfm-bot
python3 -m venv .venv --python 3.11
source .venv/bin/activate
pip install -r requirements.txt

# TimesFM must be installed from source (not on PyPI)
git clone https://github.com/google-research/timesfm.git /tmp/timesfm-install
pip install -e /tmp/timesfm-install.[torch]
```

## Usage

```bash
source .venv/bin/activate
python scripts/run_btc_forecast.py --markets 3 --horizon 15
```

Results are saved to `data/forecasts/` as JSON files.

## Trading Signal Logic

The bot compares:
- **TimesFM UP probability**: % of forecasted steps above current price
- **Polymarket UP price**: Market's implied probability

Signal thresholds:
- If TimesFM UP prob > Polymarket UP price + 0.15 → **BUY_UP**
- If TimesFM UP prob < Polymarket UP price - 0.15 → **BUY_DOWN**
- Otherwise → **HOLD**

## Project Structure

```
src/
  data_collection/
    btc_price_fetcher.py    # CoinGecko BTC price history
    polymarket_client.py    # Polymarket Gamma + CLOB APIs
  forecasting/
    forecaster.py           # TimesFM 2.5 wrapper
    signal_generator.py     # Compare TimesFM vs Polymarket odds
scripts/
  run_btc_forecast.py       # Main entry point
data/
  forecasts/                # Saved forecast results
  logs/                     # Run logs
```

## Example Output

```
TRADING SIGNAL:
  TimesFM UP probability: 93.3% (14/15 steps)
  Polymarket UP price: 15.5%
  Disagreement: +0.78
  SIGNAL: BUY_UP (confidence: 1.00)
  Action: Market UNDERPRICES upside - consider buying UP token
```

## License

MIT
