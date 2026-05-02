"""Trade journal for logging trades to YAML.

Integrates with Hermes trading skills for performance analysis.
"""

import os
import yaml
from datetime import datetime
from typing import Dict, Any, Optional


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
        market: str,
        exit_price: float,
        pnl_usdc: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        lessons: str = "",
    ) -> None:
        """Append an exit entry for a position.

        In current implementation, we simply append a closing record.
        Sophisticated matching of open positions can be added later.
        """
        entry = {
            "date": datetime.now().isoformat(),
            "market": market,
            "position": "CLOSE",
            "exit_price": exit_price,
            "pnl_usdc": pnl_usdc,
            "pnl_pct": pnl_pct,
            "outcome": "closed",
            "lessons": lessons,
        }
        with open(self.log_path, 'a') as f:
            yaml.dump(entry, f, default_flow_style=False, sort_keys=False)
            f.write('\n---\n')
