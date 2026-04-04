# BTC 15-Minute Market Monitor (Phase 1)

Real-time monitor for Polymarket BTC 15-minute Up/Down markets.

## Features

- **Market Detection**: Automatically finds the current active BTC 15-minute market
- **BTC Price Tracking**: Fetches BTC price every 30 seconds from CoinGecko (with Binance fallback)
- **PTB Calculation**: Fetches BTC price at window start (Price To Beat) using historical data
- **Token Prices**: Real-time UP and DOWN token prices from Polymarket CLOB
- **Strategy Signals**: Flags trading opportunities based on configurable strategies
- **CSV Logging**: All observations saved for backtesting

## Strategies

### Strategy 1 (Early Window)
- BTC > PTB by $20+ AND
- "Up" token price < $0.55 AND
- >5 minutes remaining

### Strategy 3 (Late Window)
- BTC > PTB by $50+ AND
- "Up" token price < $0.95 AND
- <3 minutes remaining

## Usage

```bash
# Activate virtual environment
cd ~/polymarket-bot
source .venv/bin/activate

# Run monitor (30-second interval default)
python scripts/btc_15m_monitor.py

# Custom interval (e.g., 20 seconds)
python scripts/btc_15m_monitor.py --interval 20

# Custom output directory
python scripts/btc_15m_monitor.py --output ~/custom/path
```

## Output

- **Terminal Dashboard**: Real-time display with color-coded signals
- **CSV Files**: Daily observations saved to `data/observations/observations_YYYYMMDD.csv`

### CSV Columns

| Column | Description |
|--------|-------------|
| timestamp | ISO timestamp of observation |
| btc_price | Current BTC price in USD |
| ptb | Price To Beat (BTC at window start) |
| gap | BTC_price - PTB (positive = BTC above PTB) |
| up_token_price | Polymarket "Up" token price (0-1) |
| down_token_price | Polymarket "Down" token price (0-1) |
| time_remaining_sec | Seconds until market resolution |
| strategy_1_flag | True if Strategy 1 conditions met |
| strategy_3_flag | True if Strategy 3 conditions met |
| market_slug | Market identifier |
| market_question | Full market question text |

## Data Sources

- **Polymarket Gamma API**: Market metadata (`https://gamma-api.polymarket.com`)
- **Polymarket CLOB API**: Token prices (`https://clob.polymarket.com`)
- **CoinGecko API**: BTC current and historical prices
- **Binance API**: Fallback BTC prices

## Next Steps (Phase 2)

- [ ] Automated trade execution
- [ ] Multiple market tracking
- [ ] TimesFM forecasting integration
- [ ] Risk management integration
- [ ] Performance analytics
