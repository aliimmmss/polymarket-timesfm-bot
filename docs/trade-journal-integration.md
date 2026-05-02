# Trade Journal Integration with Hermes Skills

This bot now automatically logs every trade decision to your **Hermes trading journal** (`~/trading/trading-log.yaml`), enabling systematic performance review via `/optimize-strategy`.

## What Gets Logged

For each trade (or attempted trade) the bot records:

| Field | Source | Description |
|-------|--------|-------------|
| `date` | Timestamp | When the trade was executed |
| `market` | Polymarket API | Market question text |
| `position` | Strategy | "YES" (UP) currently |
| `entry_price` | CLOB midpoint | Probability at entry |
| `size_usdc` | Config `MAX_ORDER_SIZE` | Dollar amount risked |
| `size_pct` | Calculated | Position size as % of total capital (from `~/trading/trading-config.yaml`) |
| `thesis` | Signal logic | Human-readable reasoning (e.g., "Signal A: gap=$X, CVD=Y") |
| `strategy` | Signal type | e.g., `btc_15min_a+b` |
| `confidence` | Heuristic | 0.7 default; can be derived from gap magnitude |
| `time_horizon` | Fixed | "15 minutes" for BTC 15-min markets |
| `outcome` | Execution result | `filled` / `skipped` (exit P&L to be added later) |

## How It Works

- **btc_15m_monitor_v2.py**: After a signal triggers and order is placed, a YAML document is appended to `~/trading/trading-log.yaml`.
- **run_paper_trading.py**: Paper trades are logged identically (dry-run safe).
- **TradeJournal class** (`src/trading/trade_journal.py`): Handles all file I/O, reading config for capital, computing `size_pct`.

## Prerequisites

1. Hermes trading setup must be complete:
   ```bash
   /trading-setup
   ```
   This creates `~/trading/trading-config.yaml` and the empty `trading-log.yaml`.

2. Bot config `MAX_ORDER_SIZE` (in script or environment) determines position sizing.
   The journal auto-calculates percentage based on your declared capital.

## Reviewing Performance

Once you have a few journal entries, run:

```
/optimize-strategy
```

Hermes will:
- Read your `trading-log.yaml`
- Compute win rates, P&L by strategy
- Identify which signals (A, B, C) are working
- Recommend adjustments (position sizing, stop using certain conditions)

## Future Enhancements

- **Exit logging**: When stop-loss or take-profit triggers, update the existing journal entry with `exit_price`, `pnl_usdc`, `pnl_pct`, and `lessons`.
- **Confidence calibration**: Map signal strength (gap, CVD) to a numeric confidence instead of fixed 0.7.
- **Multi-asset extension**: Journal already generic; can log politics, sports, etc. by adding new monitor scripts.

## Troubleshooting

**"Trade journal unavailable" warning**: Means `src/trading/trade_journal.py` not found or config missing. Ensure file exists and `~/trading/trading-config.yaml` is present.

**Log file not updating**: Check permissions on `~/trading/` directory. Bot will log errors to its own logs.

---

*Part of the Polymarket TimesFM Bot — now powered by Hermes disciplined trading skills.*
