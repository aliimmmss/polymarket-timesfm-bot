"""
Outcome Evaluator — resolves trades after market close and labels WIN/LOSS.

Queries Polymarket market resolution outcomes from Falcon API (primary)
with Gamma API fallback, and matches them against open trades in the journal / database.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

import requests
from dotenv import load_dotenv

from src.utils.db_persistence import TradingDatabase

# Load .env into os.environ (FALCON_API_KEY, etc.)
load_dotenv()

logger = logging.getLogger(__name__)

# Primary: Falcon API (unified prediction market data)
FALCON_API = "https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized"
FALCON_AGENT_ID = 574  # Polymarket market data agent

# Fallback: Polymarket Gamma API
GAMMA_API = "https://gamma-api.polymarket.com"


class OutcomeEvaluator:
    """Evaluates trade outcomes after market resolution.

    Resolution workflow (dry-run safe):
      1. Query Falcon API for recently closed markets (closed=true)
      2. Fallback to Gamma API if Falcon fails or returns empty
      3. Match closed markets to open trades by market_slug
      4. Determine WIN/LOSS using the resolved final UP price
    """

    def __init__(self, poll_interval: int = 30, use_falcon: bool = True):
        """
        Args:
            poll_interval: How often (seconds) to check for resolved markets
            use_falcon: If True, prefer Falcon API; fall back to Gamma when unavailable
        """
        self.poll_interval = poll_interval
        self.use_falcon = use_falcon
        self.db = TradingDatabase()

    # ─────────────────────────────────────────────
    # Falcon integration
    # ─────────────────────────────────────────────
    def _fetch_falcon_markets(
        self,
        closed: bool = True,
        since: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Fetch resolved markets from Falcon API.

        Returns a list of market dicts with a unified schema:
          {
            'slug': <market_slug>,
            'outcomePrices': [up_price_str, down_price_str],
            'condition_id': <condition_id>,
            'closed': <bool>,
          }
        """
        api_key = os.getenv('FALCON_API_KEY')
        if not api_key:
            logger.warning("Falcon fetch skipped — FALCON_API_KEY not set")
            return []

        # If since is not provided, look back 2 days to keep result set bounded
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(days=2)

        unified: List[Dict[str, Any]] = []
        offset = 0
        page_limit = min(limit, 100)  # Falcon max per page appears to be 100

        while True:
            payload: Dict[str, Any] = {
                "agent_id": FALCON_AGENT_ID,
                "params": {
                    "closed": "True" if closed else "False",
                    "market_slug": "btc-updown-15m-",
                    "end_date_min": str(int(since.timestamp())),
                },
                "pagination": {"limit": page_limit, "offset": offset},
                "formatter_config": {"format_type": "raw"},
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            try:
                resp = requests.post(FALCON_API, json=payload, headers=headers, timeout=10)
                if resp.status_code != 200:
                    logger.warning(f"Falcon API returned {resp.status_code}: {resp.text[:200]}")
                    break
                data = resp.json()
                page_results = data.get("data", {}).get("results", [])
                pagination = data.get("pagination", {})
                has_more = data.get("data", {}).get("has_more", pagination.get("has_more", False))

                for m in page_results:
                    winning = m.get("winning_outcome", "")
                    side_a = m.get("side_a_outcome", "")
                    up_final = 1.0 if winning == side_a else 0.0
                    unified.append({
                        "slug": m.get("slug", ""),
                        "outcomePrices": [str(up_final), str(1.0 - up_final)],
                        "condition_id": m.get("condition_id", ""),
                        "closed": m.get("closed", True),
                    })

                logger.info(f"Falcon fetched page offset={offset} count={len(page_results)} has_more={has_more}")

                if not has_more:
                    break
                # Safety: if we already have >= requested limit items, stop
                if len(unified) >= limit:
                    break
                offset += page_limit

            except requests.RequestException as e:
                logger.error(f"Falcon fetch error (network): {e}")
                break
            except json.JSONDecodeError as e:
                logger.error(f"Falcon fetch error (invalid JSON): {e}")
                break
            except Exception as e:
                logger.error(f"Falcon fetch error: {e}")
                break

        logger.info(f"Falcon total fetched: {len(unified)} markets")
        return unified


    def _fetch_gamma_markets(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch recently resolved markets from Polymarket Gamma API."""
        markets: List[Dict[str, Any]] = []
        try:
            params = {'limit': limit, 'closed': 'true'}
            if since:
                params['endAfter'] = int(since.timestamp())
            resp = requests.get(
                f"{GAMMA_API}/markets",
                params=params,
                headers={'Accept': 'application/json'},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"OutcomeEvaluator: Gamma API returned {resp.status_code}"
                )
                return []
            data = resp.json()
            # Gamma returns a list directly or nested under 'markets'
            markets = data if isinstance(data, list) else data.get('markets', [])
            logger.info(f"Fetched {len(markets)} resolved markets from Gamma")
        except Exception as e:
            logger.error(f"Failed to fetch resolved markets from Gamma: {e}")
        return markets

    def fetch_resolved_markets(
        self, since: Optional[datetime] = None, *, prefer_falcon: bool = True
    ) -> List[Dict[str, Any]]:
        """Fetch recently resolved markets.

        Resolution source priority:
          1. Falcon API (primary, if enabled) — more reliable, explicit winning_outcome
          2. Gamma API (fallback) — legacy endpoint

        Args:
            since: Only return markets resolved after this timestamp
            prefer_falcon: If True, try Falcon first

        Returns:
            List of market dicts containing at minimum:
              - 'slug': market identifier (str)
              - 'outcomePrices': list [up_price, down_price] as strings
        """
        if prefer_falcon and self.use_falcon:
            falcon_markets = self._fetch_falcon_markets(since=since)
            if falcon_markets:
                return falcon_markets
            logger.debug("Falcon returned no results; falling back to Gamma")

        # Fallback path (Gamma)
        return self._fetch_gamma_markets(since=since)

    # ─────────────────────────────────────────────
    # Outcome determination
    # ─────────────────────────────────────────────
    def evaluate_trade_outcome(
        self,
        market_slug: str,
        signal: str,
        entry_price: float,
        outcome_price: float,
    ) -> str:
        """
        Determine if a trade won or lost.

        Args:
            market_slug: Market identifier
            signal: 'BUY_UP' or 'BUY_DOWN'
            entry_price: Price at which we would have entered
            outcome_price: Final resolved price for UP side (0.0–1.0)

        Returns:
            'win', 'loss', or 'push'
        """
        # outcome_price is the final probability of the UP outcome
        # Binary market: outcome_price near 1.0 means UP won; near 0.0 means DOWN won.
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

    # ─────────────────────────────────────────────
    # Main update loop
    # ─────────────────────────────────────────────
    def update_trade_outcomes(self) -> int:
        """
        Check all open/unresolved trades and fill in outcomes.

        Returns:
            Number of trades updated
        """
        updated = 0
        open_trades = self.db.get_open_trades()
        if not open_trades:
            logger.debug("No open trades to evaluate")
            return 0

        logger.info(f"Checking {len(open_trades)} open trades for resolution")
        resolved_markets = self.fetch_resolved_markets()
        if not resolved_markets:
            logger.debug("No resolved markets returned this cycle")
            return 0

        # Build slug → market_data lookup
        resolved_slugs = {
            m.get('slug'): m
            for m in resolved_markets
            if m.get('slug')
        }

        for trade in open_trades:
            market_slug = trade.get('market_slug')
            signal = trade.get('signal')  # BUY_UP / BUY_DOWN
            if market_slug not in resolved_slugs:
                continue  # not settled yet

            market_data = resolved_slugs[market_slug]

            # Extract UP token's final price from outcomePrices
            outcome_prices = market_data.get('outcomePrices', [])
            try:
                up_final = float(outcome_prices[0]) if outcome_prices else None
            except (IndexError, ValueError, TypeError):
                logger.warning(
                    f"Could not parse outcomePrices for {market_slug}: {outcome_prices}"
                )
                continue

            if up_final is None:
                continue

            outcome = self.evaluate_trade_outcome(
                market_slug, signal, trade.get('entry_price', 0.0), up_final
            )
            self.db.update_trade_outcome(trade['id'], outcome, up_final)
            updated += 1
            logger.info(
                f"Trade resolved: {market_slug} | {signal} → {outcome.upper()} "
                f"(final UP={up_final:.2f})"
            )

        return updated

    # ─────────────────────────────────────────────
    # Polling loop
    # ─────────────────────────────────────────────
    def poll_forever(self) -> None:
        """Continuously poll for resolved markets and update outcomes."""
        logger.info(
            "OutcomeEvaluator starting — polling for resolved markets "
            f"(source={'Falcon' if self.use_falcon else 'Gamma'})"
        )
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
