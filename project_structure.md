# Polymarket TimesFM Trading Bot Project Structure

## Directory Layout
```
polymarket-bot/
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example
│
├── src/
│   ├── __init__.py
│   ├── data_collection/
│   │   ├── __init__.py
│   │   ├── polymarket_client.py
│   │   ├── data_fetcher.py
│   │   ├── data_store.py
│   │   └── feature_engineering.py
│   │
│   ├── forecasting/
│   │   ├── __init__.py
│   │   ├── timesfm_forecaster.py
│   │   ├── signal_generator.py
│   │   └── forecast_evaluator.py
│   │
│   ├── trading/
│   │   ├── __init__.py
│   │   ├── portfolio_manager.py
│   │   ├── order_executor.py
│   │   └── risk_manager.py
│   │
│   ├── backtesting/
│   │   ├── __init__.py
│   │   ├── backtester.py
│   │   ├── performance_metrics.py
│   │   └── visualization.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── config.py
│       ├── logger.py
│       └── helpers.py
│
├── scripts/
│   ├── setup_db.py
│   ├── collect_historical_data.py
│   ├── run_backtest.py
│   └── run_paper_trading.py
│
├── config/
│   ├── default.yaml
│   ├── trading_strategies.yaml
│   └── risk_parameters.yaml
│
├── tests/
│   ├── test_data_collection.py
│   ├── test_forecasting.py
│   └── test_trading.py
│
├── notebooks/
│   ├── data_exploration.ipynb
│   ├── timesfm_testing.ipynb
│   └── strategy_development.ipynb
│
└── docker/
    ├── Dockerfile
    ├── docker-compose.yml
    └── nginx.conf
```

## Initial Setup Steps

### 1. Create Virtual Environment
```bash
cd polymarket-bot
uv venv
source .venv/bin/activate
```

### 2. Install Core Dependencies
```bash
uv pip install timesfm[torch] torch --index-url https://download.pytorch.org/whl/cpu
uv pip install pandas numpy matplotlib seaborn scikit-learn
uv pip install httpx websockets python-dotenv yaml
uv pip install sqlalchemy psycopg2-binary asyncpg
uv pip install pytest pytest-asyncio
```

### 3. Set Up PostgreSQL Database
```bash
# Install PostgreSQL (if not already installed)
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql -c "CREATE DATABASE polymarket_bot;"
sudo -u postgres psql -c "CREATE USER bot_user WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE polymarket_bot TO bot_user;"
```

### 4. Create .env File
```bash
cp .env.example .env
# Edit .env with your configurations
```

## Development Priorities (Week 1)

### Day 1-2: Data Collection Infrastructure
- Implement `polymarket_client.py` with GraphQL API integration
- Create `data_store.py` with PostgreSQL schema
- Set up real-time data streaming
- Implement historical data backfill

### Day 3-4: Forecasting Module
- Create `timesfm_forecaster.py` wrapper
- Implement feature engineering pipeline
- Set up caching for TimesFM forecasts
- Create basic signal generation logic

### Day 5-7: Backtesting Framework
- Implement `backtester.py` with historical data
- Create performance metrics calculation
- Build visualization tools
- Test basic trading strategies

## Configuration Files

### config/default.yaml
```yaml
database:
  host: localhost
  port: 5432
  name: polymarket_bot
  user: bot_user
  password: ${DB_PASSWORD}

polymarket:
  api_url: https://gamma-api.polymarket.com/
  graphql_endpoint: https://api.polymarket.com/graphql
  refresh_interval: 60  # seconds

forecasting:
  timesfm_model: "google/timesfm-2.5-200m-pytorch"
  max_context: 1024
  max_horizon: 256
  forecast_horizons: [1, 6, 12, 24]  # hours
  
trading:
  paper_mode: true
  initial_capital: 1000.0
  max_position_size: 0.10  # 10% of portfolio
  slippage_tolerance: 0.005  # 0.5%
```

### .env.example
```env
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=polymarket_bot
DB_USER=bot_user
DB_PASSWORD=your_secure_password

# Polymarket
POLYMARKET_API_KEY=your_api_key
POLYMARKET_WALLET_PRIVATE_KEY=your_wallet_private_key

# TimesFM
HF_TOKEN=your_huggingface_token

# External APIs
NEWS_API_KEY=your_newsapi_key
TWITTER_BEARER_TOKEN=your_twitter_token

# Risk Management
MAX_DAILY_LOSS=0.05
MAX_POSITION_CORRELATION=0.7
```

## Next Steps After Setup
1. Run database migrations
2. Collect historical market data
3. Test TimesFM integration
4. Develop first trading strategy
5. Begin paper trading