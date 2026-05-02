"""
Outcome Evaluator — resolves trades after market close and labels WIN/LOSS.

Queries Polymarket Gamma API for market resolution outcomes and matches
them against open trades in the journal / database.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import requests

from src.utils.db_persistence import TradingDatabase

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"


class OutcomeEvaluator:
    """Evaluates trade outcomes after market resolution."""

    def __init__(self, poll_interval: int = 30):
        """
        Args:
            poll_interval: How often (seconds) to check for resolved markets
        """
        self.poll_interval = poll_interval
        self.db = TradingDatabase()

    def fetch_resolved_markets(self, since: Optional[datetime] = None) -> list:
        """
        Fetch recently resolved markets from Polymarket.

        Args:
            since: Only fetch markets resolved after this timestamp

        Returns:
            List of resolved market dicts with outcome
        """
        markets = []
        try:
            # Gamma API: query markets with status "settled"
            params = {
                'status': 'settled',
                'limit': 100,
            }
            if since:
                params['endAfter'] = int(since.timestamp())

            resp = requests.get(
                f"{GAMMA_API}/v1/markets",
                params=params,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            # Gamma returns markets in 'markets' key or as list
            if isinstance(data, dict):
                markets = data.get('markets', [])
            elif isinstance(data, list):
                markets = data

            logger.info(f"Fetched {len(markets)} resolved markets from Gamma")
        except Exception as e:
            logger.error(f"Failed to fetch resolved markets: {e}")

        return markets

    def evaluate_trade_outcome(
        self,
        market_slug: str,
        signal: str,
        entry_price: float,
        outcome_price: float
    ) -> str:
        """
        Determine if a trade won or lost.

        Args:
            market_slug: Market identifier
            signal: 'BUY_UP' or 'BUY_DOWN'
            entry_price: Price at which we would have entered
            outcome_price: Final resolved price (0.0–1.0)

        Returns:
            'win', 'loss', or 'push'
        """
        # outcome_price is the final probability of the UP outcome
        # For a binary market:
        #  - outcome_price ≈ 1.0 means UP won (BTC went up)
        #  - outcome_price ≈ 0.0 means DOWN won (BTC went down)

        if signal == 'BUY_UP':
            if outcome_price >= 0.5:
                return 'win'
            elif outcome_price <= 0.5:
                return 'loss'
            else:
                return 'push'

        elif signal == 'BUY_DOWN':
            if outcome_price <= 0.5:
                return 'win'
            elif outcome_price >= 0.5:
                return 'loss'
            else:
                return 'push'

        return 'unknown'

    def update_trade_outcomes(self) -> int:
        """
        Check all open/unresolved trades and fill in outcomes.

        Returns:
            Number of trades updated
        """
        updated = 0

        # Get open trades from DB (outcome IS NULL)
        open_trades = self.db.get_open_trades()

        if not open_trades:
            logger.debug("No open trades to evaluate")
            return 0

        logger.info(f"Checking {len(open_trades)} open trades for resolution")

        for trade in open_trades:
            market_slug = trade.get('market_slug')
            signal = trade.get('signal')  # BUY_UP / BUY_DOWN

            # Fetch resolved markets; find if this slug settled
            resolved = self.fetch_resolved_markets()
            resolved_slugs = {m.get('slug'): m for m in resolved if m.get('slug')}

            if market_slug not in resolved_slugs:
                continue  # not settled yet

            market_data = resolved_slugs[market_slug]

            # Extract outcome: market_data['outcomePrices'] = ["0.85", "0.15"]
            # First value is UP token's final price
            outcome_str = market_data.get('outcomePrices', '[]')
            try:
                outcome_prices = json.loads(outcome_str) if isinstance(outcome_str, str) else outcome_str
                up_final = float(outcome_prices[0]) if outcome_prices else None
            except (json.JSONDecodeError, IndexError, ValueError, TypeError):
                logger.warning(f"Could not parse outcomePrices for {market_slug}: {outcome_str}")
                continue

            if up_final is None:
                continue

            # Determine outcome
            outcome = self.evaluate_trade_outcome(market_slug, signal, trade.get('entry_price', 0.0), up_final)

            # Update trade record in DB
            self.db.update_trade_outcome(trade['id'], outcome, up_final)
            updated += 1

            logger.info(f"Trade resolved: {market_slug} | {signal} → {outcome.upper()} (final UP={up_final:.2f})")

        return updated

    def poll_forever(self):
        """Continuously poll for resolved markets and update outcomes."""
        logger.info("OutcomeEvaluator starting — polling for resolved markets")
        last_check = datetime.now(timezone.utc)

        while True:
            try:
                n = self.update_trade_outcomes()
                if n > 0:
                    logger.info(f"Updated {n} trade outcomes")
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logger.info("OutcomeEvaluator stopped")
                break
            except Exception as e:
                logger.error(f"OutcomeEvaluator error: {e}")
                time.sleep(self.poll_interval)

__all__ = ['OutcomeEvaluator']
