# Polymarket Trading Bot

A Polymarket prediction market trading bot using Google's TimesFM 2.5 for price forecasting.

## Project Structure

```
polymarket-bot/
├── config/                    # Configuration files
│   ├── default.yaml
│   ├── risk_parameters.yaml
│   └── trading_strategies.yaml
├── data/                      # Data storage (gitignored)
│   ├── raw/                   # Raw API data
│   ├── processed/             # Processed features
│   └── forecasts/             # Model predictions
├── src/
│   ├── bot/                   # Main bot logic
│   ├── data_collection/       # Polymarket API client
│   ├── forecasting/           # TimesFM integration
│   ├── trading/               # Trade execution
│   └── utils/                 # Utilities
└── pyproject.toml
```

## Setup

1. Create virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -e ".[prod]"
   ```

3. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

## Data Collection

Fetch market data from Polymarket:
```bash
python -m src.data_collection.polymarket_client
```

Uses:
- Gamma API (`https://gamma-api.polymarket.com`) for market metadata
- CLOB API (`https://clob.polymarket.com`) for order books and price history

## Forecasting

TimesFM 2.5 requires:
- Exactly 256 context points for input
- Zero-mean normalization works best
- Returns NaN with insufficient input length

## API Reference

### PolymarketGammaClient

```python
from src.data_collection.polymarket_client import PolymarketGammaClient

client = PolymarketGammaClient()

# Fetch top markets by volume
markets = client.get_top_markets_by_volume(limit=10)

# Get current order book
order_book = client.get_market_order_book(condition_id)

# Generate price history (256 points for TimesFM)
price_history = client.generate_realistic_price_history(market_data)
```

## License

MIT
