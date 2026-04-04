"""Stop-loss management for BTC 15-minute trading.

Based on research from:
- polymarket-bot/polymarket_auto_trade.py (Chinese bot)

Implements probability-based stop-loss:
- Triggers when token price drops X% from entry
- Monitors positions continuously
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open position."""
    token_id: str
    side: str  # 'up' or 'down'
    buy_price: float  # Entry probability (0-1)
    buy_time: float  # Timestamp of entry
    size: float  # Position size in USDC
    stop_loss_price: float  # Stop-loss trigger price
    take_profit_price: Optional[float] = None  # Take-profit price
    highest_price: float = 0.0  # Track highest price for trailing stop
    closed: bool = False


class StopLossManager:
    """Manages stop-loss monitoring for open positions.
    
    Configurable parameters:
    - stop_loss_prob_pct: Price drop percentage to trigger stop (default 15%)
    - check_interval: How often to check positions (default 5s)
    - min_hold_time: Minimum time before allowing stop-loss (default 30s)
    """
    
    def __init__(
        self,
        stop_loss_prob_pct: float = 0.15,
        check_interval: float = 5.0,
        min_hold_time: float = 30.0,
        use_trailing_stop: bool = False,
        trailing_stop_pct: float = 0.10,
    ):
        """Initialize stop-loss manager.
        
        Args:
            stop_loss_prob_pct: Stop loss as % of entry price (default 0.15 = 15%)
            check_interval: Seconds between checks
            min_hold_time: Minimum hold time before stop-loss triggers
            use_trailing_stop: Whether to use trailing stop
            trailing_stop_pct: Trailing stop percentage
        """
        self.stop_loss_prob_pct = stop_loss_prob_pct
        self.check_interval = check_interval
        self.min_hold_time = min_hold_time
        self.use_trailing_stop = use_trailing_stop
        self.trailing_stop_pct = trailing_stop_pct
        
        self._positions: Dict[str, Position] = {}
        self._last_check: float = 0.0
    
    def add_position(
        self,
        token_id: str,
        buy_price: float,
        buy_time: float,
        side: str,
        size: float = 0.0,
        take_profit_pct: Optional[float] = None,
    ) -> Position:
        """Add a position for monitoring.
        
        Args:
            token_id: CLOB token ID
            buy_price: Entry price (probability 0-1)
            buy_time: Timestamp of entry
            side: 'up' or 'down'
            size: Position size in USDC
            take_profit_pct: Optional take-profit percentage
        
        Returns:
            Created Position object
        """
        # Calculate stop-loss price
        stop_loss_price = buy_price * (1.0 - self.stop_loss_prob_pct)
        
        # Calculate take-profit price if specified
        take_profit_price = None
        if take_profit_pct:
            take_profit_price = buy_price * (1.0 + take_profit_pct)
            take_profit_price = min(take_profit_price, 0.99)  # Cap at 99%
        
        position = Position(
            token_id=token_id,
            side=side,
            buy_price=buy_price,
            buy_time=buy_time,
            size=size,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            highest_price=buy_price,
        )
        
        self._positions[token_id] = position
        logger.info(
            f"Position added: {side.upper()} @ {buy_price:.4f}, "
            f"SL={stop_loss_price:.4f}, TP={take_profit_price}"
        )
        
        return position
    
    def check(
        self,
        current_prices: Dict[str, float],
        current_time: Optional[float] = None,
    ) -> List[Dict]:
        """Check all tracked positions for stop-loss or take-profit triggers.
        
        Args:
            current_prices: Dict mapping token_id to current price
            current_time: Current timestamp (uses time.time() if not provided)
        
        Returns:
            List of action dicts with keys:
                - token_id: Token to act on
                - action: 'SELL' or 'HOLD'
                - reason: Explanation for the action
        """
        if current_time is None:
            current_time = time.time()
        
        actions = []
        
        for token_id, position in self._positions.items():
            if position.closed:
                continue
            
            current_price = current_prices.get(token_id)
            if current_price is None:
                continue
            
            # Update highest price for trailing stop
            if self.use_trailing_stop and current_price > position.highest_price:
                position.highest_price = current_price
                # Update trailing stop
                position.stop_loss_price = position.highest_price * (
                    1.0 - self.trailing_stop_pct
                )
            
            # Check hold time
            time_held = current_time - position.buy_time
            if time_held < self.min_hold_time:
                actions.append({
                    'token_id': token_id,
                    'action': 'HOLD',
                    'reason': f"Min hold time not reached ({time_held:.1f}s < {self.min_hold_time}s)",
                    'current_price': current_price,
                    'stop_loss_price': position.stop_loss_price,
                })
                continue
            
            # Check take-profit
            if position.take_profit_price and current_price >= position.take_profit_price:
                actions.append({
                    'token_id': token_id,
                    'action': 'SELL',
                    'reason': f"Take-profit triggered: {current_price:.4f} >= {position.take_profit_price:.4f}",
                    'position': position,
                    'trigger': 'TAKE_PROFIT',
                })
                position.closed = True
                continue
            
            # Check stop-loss
            if current_price <= position.stop_loss_price:
                actions.append({
                    'token_id': token_id,
                    'action': 'SELL',
                    'reason': f"Stop-loss triggered: {current_price:.4f} <= {position.stop_loss_price:.4f}",
                    'position': position,
                    'trigger': 'STOP_LOSS',
                })
                position.closed = True
                continue
            
            # No trigger
            actions.append({
                'token_id': token_id,
                'action': 'HOLD',
                'reason': f"Price {current_price:.4f} within range "
                         f"[SL: {position.stop_loss_price:.4f}, TP: {position.take_profit_price}]",
                'current_price': current_price,
                'stop_loss_price': position.stop_loss_price,
            })
        
        self._last_check = current_time
        return actions
    
    def check_by_gap(
        self,
        gap: float,
        gap_threshold: float = 10.0,
        original_gap: Optional[float] = None,
    ) -> List[Dict]:
        """Check positions based on BTC-PTB gap.
        
        Alternative stop-loss method: trigger when gap shrinks too much.
        
        Args:
            gap: Current BTC-PTB gap
            gap_threshold: Minimum gap to maintain (default $10)
            original_gap: Gap at position entry (optional)
        
        Returns:
            List of action dicts
        """
        actions = []
        
        if gap < gap_threshold:
            # Gap has shrunk below threshold - signal to close positions
            for token_id, position in self._positions.items():
                if not position.closed:
                    actions.append({
                        'token_id': token_id,
                        'action': 'SELL',
                        'reason': f"Gap shrunk to ${gap:.2f} < ${gap_threshold:.2f}",
                        'position': position,
                        'trigger': 'GAP_SHRINK',
                    })
                    position.closed = True
        
        return actions
    
    def remove_position(self, token_id: str) -> Optional[Position]:
        """Remove a position (after sell or expiration).
        
        Args:
            token_id: Token ID to remove
        
        Returns:
            Removed Position or None if not found
        """
        return self._positions.pop(token_id, None)
    
    def get_position(self, token_id: str) -> Optional[Position]:
        """Get a specific position.
        
        Args:
            token_id: Token ID
        
        Returns:
            Position or None
        """
        return self._positions.get(token_id)
    
    def get_all_positions(self) -> List[Position]:
        """Get all tracked positions.
        
        Returns:
            List of Position objects
        """
        return list(self._positions.values())
    
    def get_active_positions(self) -> List[Position]:
        """Get all active (not closed) positions.
        
        Returns:
            List of active Position objects
        """
        return [p for p in self._positions.values() if not p.closed]
    
    def clear_closed_positions(self) -> int:
        """Remove all closed positions.
        
        Returns:
            Number of positions removed
        """
        closed = [tid for tid, pos in self._positions.items() if pos.closed]
        for tid in closed:
            del self._positions[tid]
        return len(closed)


# Test function
def test_stop_loss():
    """Test stop-loss manager."""
    manager = StopLossManager(
        stop_loss_prob_pct=0.15,  # 15% drop triggers stop
        min_hold_time=5.0,  # 5 seconds for testing
    )
    
    # Add a position
    pos = manager.add_position(
        token_id="test_up_token",
        buy_price=0.80,
        buy_time=time.time(),
        side="up",
        size=5.0,
        take_profit_pct=0.10,  # 10% profit target
    )
    
    print(f"Position added: SL={pos.stop_loss_price:.4f}, TP={pos.take_profit_price:.4f}")
    
    # Wait for min hold time
    time.sleep(6)
    
    # Check with current price
    actions = manager.check({
        "test_up_token": 0.75,  # 6.25% drop, not enough for 15% stop
    })
    print("Actions (price 0.75):", actions)
    
    # Check with stop-loss triggering price
    actions = manager.check({
        "test_up_token": 0.65,  # 18.75% drop, triggers stop
    })
    print("Actions (price 0.65):", actions)
    
    return manager


if __name__ == "__main__":
    import time as time_module
    logging.basicConfig(level=logging.INFO)
    test_stop_loss()
