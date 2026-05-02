"""Trade journal for logging trades to YAML.

Integrates with Hermes trading skills for performance analysis.
"""

import os
import yaml
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class TradeJournal:
    """Append-only YAML trade journal.

    Matches the schema expected by Hermes /optimize-strategy skill.
    """

    def __init__(
        self,
        config_path: str = "~/trading/trading-config.yaml",
        log_path: Optional[str] = None,
    ):
        """Initialize trade journal.

        Args:
            config_path: Path to trading config YAML (contains capital, log path)
            log_path: Override log file path (default from config)
        """
        self.config_path = os.path.expanduser(config_path)
        self.log_path = os.path.expanduser(
            log_path or self._default_log_path()
        )
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self._capital = self._load_capital()

    def _default_log_path(self) -> str:
        """Determine log path from config or default."""
        if os.path.exists(self.config_path):
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
            return config.get("trading_log_path", "~/trading/trading-log.yaml")
        return "~/trading/trading-log.yaml"

    def _load_capital(self) -> float:
        """Load total capital from config for position sizing %."""
        if os.path.exists(self.config_path):
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
            return float(config.get("capital_usdc", 1000.0))
        return 1000.0

    def log_entry(self, trade: Dict[str, Any]) -> None:
        """Append a trade entry to the YAML journal.

        Args:
            trade: Dictionary with trade fields. Missing fields will be None.
        """
        entry = {
            "date": trade.get("date", datetime.now().isoformat()),
            "market": trade.get("market", "Unknown"),
            "position": trade.get("position", "YES"),
            "entry_price": trade.get("entry_price"),
            "exit_price": trade.get("exit_price"),
            "size_usdc": trade.get("size_usdc", 0.0),
            "size_pct": trade.get("size_pct"),
            "pnl_usdc": trade.get("pnl_usdc"),
            "pnl_pct": trade.get("pnl_pct"),
            "thesis": trade.get("thesis", ""),
            "time_horizon": trade.get("time_horizon", ""),
            "confidence": trade.get("confidence"),
            "strategy": trade.get("strategy", ""),
            "outcome": trade.get("outcome", "open"),
            "exit_date": trade.get("exit_date"),
            "lessons": trade.get("lessons", ""),
        }

        # Calculate size_pct if not provided and we know capital
        if entry["size_pct"] is None and entry["size_usdc"] and self._capital:
            entry["size_pct"] = round((entry["size_usdc"] / self._capital) * 100, 2)

        with open(self.log_path, 'a') as f:
            yaml.dump(entry, f, default_flow_style=False, sort_keys=False)
            f.write('\n---\n')

    def log_exit(
        self,
        order_id: Optional[str] = None,
        market: Optional[str] = None,
        exit_price: Optional[float] = None,
        pnl_usdc: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        exit_reason: str = "",
        lessons: str = "",
    ) -> bool:
        """Update an existing open trade with exit details.

        Reads the entire log, finds the matching open entry (by order_id if
        provided, else by market with no exit_price), updates exit fields,
        and rewrites the file.

        Returns True if an entry was found and updated, False otherwise.
        """
        if not os.path.exists(self.log_path):
            logger.warning(f"Trade log not found: {self.log_path}")
            return False

        # Read all entries (YAML documents separated by ---)
        with open(self.log_path, 'r') as f:
            content = f.read()

        # Split YAML documents
        docs = []
        for doc in content.split('\n---\n'):
            doc = doc.strip()
            if doc:
                try:
                    entry = yaml.safe_load(doc) or {}
                    docs.append(entry)
                except yaml.YAMLError:
                    continue

        # Find entry to update
        target_idx = None
        for i, entry in enumerate(docs):
            # Match by order_id if provided
            if order_id is not None:
                if entry.get('order_id') == order_id:
                    target_idx = i
                    break
            # Else match by market and missing exit_price (open position)
            elif market is not None and entry.get('exit_price') is None:
                if entry.get('market') == market:
                    target_idx = i
                    break

        if target_idx is None:
            logger.warning(f"No open trade found to update (order_id={order_id}, market={market})")
            return False

        # Update entry
        entry = docs[target_idx]
        if exit_price is not None:
            entry['exit_price'] = round(float(exit_price), 4)
        if pnl_usdc is not None:
            entry['pnl_usdc'] = round(float(pnl_usdc), 4)
        if pnl_pct is not None:
            entry['pnl_pct'] = round(float(pnl_pct), 4)
        if exit_reason:
            entry['exit_reason'] = exit_reason
        if lessons:
            entry['lessons'] = lessons
        # Set outcome based on P&L
        if pnl_usdc is not None:
            if pnl_usdc > 0:
                entry['outcome'] = 'win'
            elif pnl_usdc < 0:
                entry['outcome'] = 'loss'
            else:
                entry['outcome'] = 'scratch'
        else:
            entry['outcome'] = 'closed'
        entry['exit_date'] = datetime.now().isoformat()

        # Rewrite file
        with open(self.log_path, 'w') as f:
            for i, doc in enumerate(docs):
                yaml.dump(doc, f, default_flow_style=False, sort_keys=False)
                if i < len(docs) - 1:
                    f.write('\n---\n')

        logger.info(f"Trade exit logged: {market} @ {exit_price} (PNL: ${pnl_usdc or 0:.2f})")
        return True
