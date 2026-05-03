"""Database persistence layer for trading data.

Stores trade history, positions, and performance metrics.
Supports SQLite (default) and PostgreSQL (production).

Required tables:
- trades: Executed trades
- signals: Generated trading signals
- positions: Current token holdings
- orders: Order history
- performance: Daily P&L tracking
- signals: Generated trading signals
"""

import logging
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Record of a trade."""
    id: Optional[int]
    timestamp: datetime
    market_id: str
    market_slug: str
    token_id: str
    side: str  # 'BUY' or 'SELL'
    price: float  # Entry price
    size_usdc: float
    size_tokens: float
    signal: str  # 'BUY_UP', 'BUY_DOWN', 'HOLD'
    confidence: float
    signal_strength: float
    polymarket_up_price: float
    pnl: Optional[float]
    status: str  # 'PENDING', 'FILLED', 'PARTIAL', 'FAILED'
    order_id: Optional[str]
    dry_run: bool
    outcome: Optional[str] = None  # 'win', 'loss', 'push', or None if pending
    resolved_at: Optional[datetime] = None
    final_up_price: Optional[float] = None


@dataclass
class PositionRecord:
    """Record of current position."""
    id: Optional[int]
    timestamp: datetime
    token_id: str
    market_slug: str
    market_id: str
    balance: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    side: str  # 'LONG' or 'SHORT'


class TradingDatabase:
    """Database for trading data persistence.
    
    Uses SQLite for development, supports PostgreSQL for production.
    """
    
    def __init__(self, db_path: str = "data/trading.db"):
        """Initialize database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_db()
        logger.info(f"Database initialized: {db_path}")
    
    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            # Trades table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,              -- Buy / Sell / Redeem / Deposit
                    market_slug TEXT,
                    market_name TEXT,
                    token_id TEXT,
                    token_name TEXT,                   -- Up / Down / USDC
                    side TEXT,                         -- BUY / SELL (for Buy/Sell rows)
                    price REAL,                        -- price per token (probability)
                    size_usdc REAL,
                    size_tokens REAL,
                    order_id TEXT,                     -- Polymarket order ID
                    tx_hash TEXT,                      -- transaction hash
                    signal TEXT,                       -- Signal A/B/C (for Buy rows)
                    confidence REAL,
                    pnl REAL,                          -- realized P&L (Sell/Redeem)
                    outcome TEXT,                      -- win/loss/scratch
                    final_up_price REAL,               -- 1.0 or 0.0 at settlement
                    resolved_at TEXT
                )
            """)
            
            # Positions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    token_id TEXT UNIQUE NOT NULL,
                    market_slug TEXT,
                    market_id TEXT,
                    balance REAL NOT NULL DEFAULT 0,
                    avg_entry_price REAL DEFAULT 0,
                    current_price REAL DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    side TEXT
                )
            """)
            
            # Performance table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE NOT NULL,
                    daily_pnl REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    win_count INTEGER DEFAULT 0,
                    loss_count INTEGER DEFAULT 0,
                    starting_balance REAL,
                    ending_balance REAL
                )
            """)
            
            # Signals table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    market_id TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    confidence REAL,
                    signal_strength REAL,
                    polymarket_up_price REAL,                    executed BOOLEAN DEFAULT FALSE
                )
            """)
            
            conn.commit()
    
    def _get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def save_trade(self, trade: TradeRecord) -> int:
        """Save trade to database.
        
        Returns:
            Trade ID
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO trades (
                    timestamp, market_id, market_slug, token_id, side,
                    price, size_usdc, size_tokens, signal, confidence,
                    signal_strength, polymarket_up_price, pnl, status,
                    order_id, dry_run
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.timestamp.isoformat(),
                trade.market_id,
                trade.market_slug,
                trade.token_id,
                trade.side,
                trade.price,
                trade.size_usdc,
                trade.size_tokens,
                trade.signal,
                trade.confidence,
                trade.signal_strength,
                trade.polymarket_up_price,
                trade.pnl,
                trade.status,
                trade.order_id,
                trade.dry_run,
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update_trade_status(self, trade_id: int, status: str, pnl: Optional[float] = None):
        """Update trade status and P&L."""
        with self._get_connection() as conn:
            if pnl is not None:
                conn.execute(
                    "UPDATE trades SET status = ?, pnl = ? WHERE id = ?",
                    (status, pnl, trade_id)
                )
            else:
                conn.execute(
                    "UPDATE trades SET status = ? WHERE id = ?",
                    (status, trade_id)
                )
            conn.commit()
    def save_position(self, position: PositionRecord):
        """Save or update position."""
        with self._get_connection() as conn:
            # Upsert pattern
            conn.execute("""
                INSERT INTO positions (timestamp, token_id, market_slug, market_id, balance,
                                     avg_entry_price, current_price, unrealized_pnl, side)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    balance = excluded.balance,
                    avg_entry_price = excluded.avg_entry_price,
                    current_price = excluded.current_price,
                    unrealized_pnl = excluded.unrealized_pnl
            """, (
                position.timestamp.isoformat(),
                position.token_id,
                position.market_slug,
                position.market_id,
                position.balance,
                position.avg_entry_price,
                position.current_price,
                position.unrealized_pnl,
                position.side,
            ))
            conn.commit()
    
    def get_position(self, token_id: str) -> Optional[PositionRecord]:
        """Get position by token ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE token_id = ?",
                (token_id,)
            ).fetchone()
            
            if row:
                return PositionRecord(
                    id=row['id'],
                    timestamp=datetime.fromisoformat(row['timestamp']),
                    token_id=row['token_id'],
                    market_slug=row['market_slug'],
                    market_id=row['market_id'],
                    balance=row['balance'],
                    avg_entry_price=row['avg_entry_price'],
                    current_price=row['current_price'],
                    unrealized_pnl=row['unrealized_pnl'],
                    side=row['side'],
                )
            return None
    
    def get_all_positions(self) -> List[PositionRecord]:
        """Get all positions."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE balance > 0"
            ).fetchall()
            
            return [
                PositionRecord(
                    id=row['id'],
                    timestamp=datetime.fromisoformat(row['timestamp']),
                    token_id=row['token_id'],
                    market_slug=row['market_slug'],
                    market_id=row['market_id'],
                    balance=row['balance'],
                    avg_entry_price=row['avg_entry_price'],
                    current_price=row['current_price'],
                    unrealized_pnl=row['unrealized_pnl'],
                    side=row['side'],
                )
                for row in rows
            ]
    
    def get_trades(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get recent trades."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM trades
                   ORDER BY timestamp DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset)
            ).fetchall()
            return [dict(row) for row in rows]
    
    def get_daily_stats(self, date: Optional[str] = None) -> Dict:
        """Get daily statistics."""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        with self._get_connection() as conn:
            # Get P&L
            pnls = conn.execute(
                """SELECT COALESCE(SUM(pnl), 0) as daily_pnl,
                          COUNT(*) as trade_count
                   FROM trades
                   WHERE date(timestamp) = ? AND status = 'FILLED'""",
                (date,)
            ).fetchone()
            
            # Get win/loss
            wins = conn.execute(
                """SELECT COUNT(*) FROM trades
                   WHERE date(timestamp) = ? AND pnl > 0""",
                (date,)
            ).fetchone()[0]
            
            losses = conn.execute(
                """SELECT COUNT(*) FROM trades
                   WHERE date(timestamp) = ? AND pnl < 0""",
                (date,)
            ).fetchone()[0]
            
            return {
                'date': date,
                'daily_pnl': pnls['daily_pnl'] or 0,
                'trade_count': pnls['trade_count'],
                'wins': wins,
                'losses': losses,
                'win_rate': wins / (wins + losses) if (wins + losses) > 0 else 0,
            }
    
    def get_performance_summary(self, days: int = 30) -> Dict:
        """Get performance summary for last N days."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT date(timestamp) as date,
                          COALESCE(SUM(pnl), 0) as pnl
                   FROM trades
                   WHERE status = 'FILLED'
                     AND timestamp >= date('now', '-{} days')
                   GROUP BY date(timestamp)
                   ORDER BY date""".format(days)
            ).fetchall()
            
            daily_pnl = {row['date']: row['pnl'] for row in rows}
            cumulative_pnl = 0
            cumulative = {}
            
            for date, pnl in daily_pnl.items():
                cumulative_pnl += pnl
                cumulative[date] = cumulative_pnl
            
            total_trades = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status = 'FILLED'"
            ).fetchone()[0]
            
            total_pnl = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM trades"
            ).fetchone()[0]
            
            return {
                'total_trades': total_trades,
                'total_pnl': total_pnl,
                'daily_pnl': daily_pnl,
                'cumulative_pnl': cumulative,
                'period_days': days,
            }
    
    def save_signal(self, market_id: str, signal: str, confidence: float,
                   signal_strength: float, polymarket_up_price: float,
                   disagreement: float) -> int:
        """Save generated signal."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO signals (timestamp, market_id, signal, confidence,
                                     signal_strength, polymarket_up_price)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.now().isoformat(), market_id, signal, confidence,
                 signal_strength, polymarket_up_price)
            )
            conn.commit()
            return cursor.lastrowid


    def update_trade_outcome(self, trade_id: int, outcome: str, final_up_price: float) -> bool:
        """Update a trade with its resolution outcome and compute P&L.

        Args:
            trade_id: Trade record ID
            outcome: 'win', 'loss', or 'push'
            final_up_price: Final resolved price of UP token (0.0–1.0)

        Returns:
            True if updated successfully
        """
        try:
            with self._get_connection() as conn:
                # Fetch entry price and token size to compute P&L
                row = conn.execute(
                    "SELECT price, size_tokens, side FROM trades WHERE id = ?",
                    (trade_id,)
                ).fetchone()
                pnl = None
                if row:
                    entry_price, size_tokens, side = row
                    # Currently only BUY_UP side is supported by the bot
                    # P&L = (final_up_price - entry_price) * size_tokens
                    if side == 'BUY':
                        pnl = (final_up_price - entry_price) * size_tokens
                    # Future: handle BUY (down) side if needed

                conn.execute("""
                    UPDATE trades
                    SET outcome = ?, resolved_at = ?, final_up_price = ?, pnl = ?
                    WHERE id = ?
                """, (
                    outcome,
                    datetime.now().isoformat(),
                    final_up_price,
                    pnl,
                    trade_id
                ))
                conn.commit()
                logger.debug(
                    f"Updated trade {trade_id}: outcome={outcome}, "
                    f"final_up={final_up_price:.3f}, pnl={pnl:.4f if pnl is not None else 'N/A'}"
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update trade outcome {trade_id}: {e}")
            return False

    def get_open_trades(self) -> List[Dict]:
        """Get all trades that have not yet been resolved (outcome IS NULL).

        Returns:
            List of trade dicts
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT id, market_slug, signal, price AS entry_price, confidence
                    FROM trades
                    WHERE outcome IS NULL
                      AND status IN ('FILLED', 'PARTIAL')
                      AND dry_run = TRUE
                """)
                rows = cursor.fetchall()
                trades = []
                for row in rows:
                    trades.append({
                        'id': row[0],
                        'market_slug': row[1],
                        'signal': row[2],
                        'entry_price': row[3],
                        'confidence': row[4],
                    })
                return trades
        except Exception as e:
            logger.error(f"Failed to fetch open trades: {e}")
            return []


# Example usage
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Test database
    db = TradingDatabase("data/test.db")
    
    # Save sample trade
    trade = TradeRecord(
        id=None,
        timestamp=datetime.now(),
        market_id="btc-market-123",
        market_slug="btc-updown-15m",
        token_id="token-up-456",
        side="BUY",
        price=0.55,
        size_usdc=5.0,
        size_tokens=9.09,
        signal="BUY_UP",
        confidence=0.8,
        signal_strength=0.75,
        polymarket_up_price=0.55,
        pnl=0.5,
        status="FILLED",
        order_id="order-789",
        dry_run=False,
    )
    
    trade_id = db.save_trade(trade)
    print(f"Saved trade: {trade_id}")
    
    # Query
    stats = db.get_daily_stats()
    print(f"Daily stats: {stats}")
