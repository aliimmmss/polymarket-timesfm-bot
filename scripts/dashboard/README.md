# Polymarket Bot Dashboard

Web dashboard for monitoring the Polymarket TimesFM trading bot.

## Quick Start

```bash
# Run dashboard
./scripts/dashboard/run_dashboard.sh

# Or manually
source .venv/bin/activate
python scripts/dashboard/app.py
```

Then open http://localhost:5000

## Pages

- `/` - Overview with portfolio stats
- `/trades` - Trade history
- `/signals` - Signal history
- `/positions` - Open positions
- `/status` - Circuit breaker & config

## API

- `GET /api/status` - Full status
- `GET /api/portfolio` - Portfolio stats
- `GET /api/trades` - Trades
- `GET /api/signals` - Signals
- `GET /api/circuit` - Circuit status
- `GET /api/config` - Configuration

Auto-refreshes every 5-10 seconds.
