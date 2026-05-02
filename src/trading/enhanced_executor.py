"""Enhanced Order Executor with Circuit Breaker and Database Persistence.

Wraps OrderExecutor with:
- Circuit breaker integration (emergency halt)
- Database persistence (SQLite/PostgreSQL)
- Signal tracking and reporting
- Enhanced error handling
"""

import logging
import os
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Import circuit breaker
from utils.circuit_breaker import (
    check_trading_allowed,
    on_trade_success,
    on_trade_failure,
    on_model_failure,
    get_circuit_status,
    CircuitBreaker
)

# Import database
from utils.db_persistence import (
    TradingDatabase,
    TradeRecord,
    PositionRecord
)

# Import base executor
from trading.order_executor import OrderExecutor, Order


class EnhancedOrderExecutor:
    """Order Executor with Circuit Breaker and Database Persistence.
    
    Wraps OrderExecutor and adds:
    - Safety checks before every trade
    - Persistent trade logging
    - Position tracking
    - Circuit breaker integration
    """
    
    def __init__(
        self,
        private_key: Optional[str] = None,
        dry_run: bool = True,
        max_order_size: float = 10.0,
        daily_loss_limit: float = 20.0,
        db_path: str = "data/trading.db",
    ):
        """Initialize enhanced executor.
        
        Args:
            private_key: Wallet private key
            dry_run: If True, only log orders
            max_order_size: Max order size in USDC
            daily_loss_limit: Max daily loss
            db_path: Database file path
        """
        # Base executor
        self.executor = OrderExecutor(
            private_key=private_key,
            dry_run=dry_run,
            max_order_size=max_order_size,
            daily_loss_limit=daily_loss_limit,
        )
        
        # Database
        self.db = TradingDatabase(db_path)
        
        # Configuration
        self.dry_run = dry_run
        self.max_order_size = max_order_size
        self.daily_loss_limit = daily_loss_limit
        
        logger.info(f"EnhancedOrderExecutor initialized (dry_run={dry_run}, db={db_path})")
    
    def execute_signal(
        self,
        token_id: str,
        side: str,  # 'BUY' or 'SELL'
        price: float,
        size_usdc: float,
        signal: str,
        confidence: float,
        signal_strength: float,
        polymarket_up_price: float,
        market_slug: str = "",
        market_id: str = "",
    ) -> Dict:
        """Execute trading signal with safety checks and persistence.
        
        Args:
            token_id: CLOB token ID
            side: 'BUY' or 'SELL'
            price: Limit price (0.01-0.99)
            size_usdc: USDC amount
            signal: Signal type ('BUY_UP', 'BUY_DOWN', etc.)
            confidence: Signal confidence (0-1)
            signal_strength: Signal strength probability
            polymarket_up_price: Current market price
            market_slug: Market slug for logging
            market_id: Market ID for logging
            
        Returns:
            Execution result with order ID and status
        """
        # Step 1: Circuit breaker check
        if not check_trading_allowed():
            status = get_circuit_status()
            logger.error(f"Trading blocked: {status.get('halt_reason')}")
            return {
                'success': False,
                'error': f"Circuit breaker: {status.get('halt_reason')}",
                'blocked': True
            }
        
        # Step 2: Save signal to database
        self.db.save_signal(
            market_id=market_id or market_slug,
            signal=signal,
            confidence=confidence,
            signal_strength=signal_strength,
            polymarket_up_price=polymarket_up_price,
        )
        
        # Step 3: Execute order
        try:
            if side == 'BUY':
                result = self.executor.buy_token(
                    token_id=token_id,
                    price=price,
                    size_usdc=size_usdc,
                )
            else:  # SELL
                result = self.executor.sell_token(
                    token_id=token_id,
                    price=price,
                    size_tokens=size_usdc,  # Note: different unit
                )
            
            # Step 4: Record result
            if result.get('success') or self.dry_run:
                # Calculate P&L (placeholder for dry run)
                pnl = 0.0
                if 'pnl' in result:
                    pnl = result['pnl']
                
                # Record trade
                trade = self._create_trade_record(
                    result=result,
                    token_id=token_id,
                    side=side,
                    price=price,
                    size_usdc=size_usdc,
                    signal=signal,
                    confidence=confidence,
                    signal_strength=signal_strength,
                    polymarket_up_price=polymarket_up_price,
                    market_slug=market_slug,
                    market_id=market_id,
                    pnl=pnl,
                )
                trade_id = self.db.save_trade(trade)
                
                # Update circuit breaker
                on_trade_success(pnl=pnl)
                
                # Update positions
                self._update_position(
                    token_id=token_id,
                    market_slug=market_slug,
                    market_id=market_id,
                    side=side,
                    price=price,
                    size_usdc=size_usdc,
                )
                
                logger.info(f"Trade executed: {signal} {side} @ {price:.3f} (ID: {trade_id})")
                result['trade_id'] = trade_id
                result['db_saved'] = True
            else:
                # Record failure
                on_trade_failure(error=result.get('error', 'Unknown'), pnl=0.0)
                logger.error(f"Trade failed: {result.get('error')}")
            
            return result
            
        except Exception as e:
            logger.exception("Trade execution error")
            on_trade_failure(error=str(e), pnl=0.0)
            return {
                'success': False,
                'error': str(e),
                'exception': True
            }
    
    def _create_trade_record(
        self,
        result: Dict,
        token_id: str,
        side: str,
        price: float,
        size_usdc: float,
        signal: str,
        confidence: float,
        signal_strength: float,
        polymarket_up_price: float,
        market_slug: str,
        market_id: str,
        pnl: float,
    ) -> TradeRecord:
        """Create TradeRecord from execution result."""
        size_tokens = size_usdc / price if price > 0 else 0.0
        
        return TradeRecord(
            id=None,
            timestamp=datetime.now(),
            market_id=market_id or market_slug,
            market_slug=market_slug,
            token_id=token_id,
            side=side,
            price=price,
            size_usdc=size_usdc,
            size_tokens=size_tokens,
            signal=signal,
            confidence=confidence,
            signal_strength=signal_strength,
            polymarket_up_price=polymarket_up_price,
            pnl=pnl,
            status='FILLED' if not self.dry_run else 'DRY_RUN',
            order_id=result.get('order_id'),
            dry_run=self.dry_run,
        )
    
    def _update_position(
        self,
        token_id: str,
        market_slug: str,
        market_id: str,
        side: str,
        price: float,
        size_usdc: float,
    ):
        """Update position tracking."""
        existing = self.db.get_position(token_id)
        
        if side == 'BUY':
            if existing and existing.balance > 0:
                # Update existing position (cost averaging)
                new_balance = existing.balance + size_usdc / price
                new_avg = (existing.avg_entry_price * existing.balance + price * size_usdc / price) / new_balance
                unrealized_pnl = (price - new_avg) * new_balance
                
                position = PositionRecord(
                    id=existing.id,
                    timestamp=datetime.now(),
                    token_id=token_id,
                    market_slug=market_slug,
                    market_id=market_id,
                    balance=new_balance,
                    avg_entry_price=new_avg,
                    current_price=price,
                    unrealized_pnl=unrealized_pnl,
                    side='LONG',
                )
            else:
                # New position
                size_tokens = size_usdc / price
                position = PositionRecord(
                    id=None,
                    timestamp=datetime.now(),
                    token_id=token_id,
                    market_slug=market_slug,
                    market_id=market_id,
                    balance=size_tokens,
                    avg_entry_price=price,
                    current_price=price,
                    unrealized_pnl=0.0,
                    side='LONG',
                )
        else:  # SELL
            if existing:
                size_tokens = size_usdc
                new_balance = max(0, existing.balance - size_tokens)
                realized_pnl = (price - existing.avg_entry_price) * size_tokens
                
                if new_balance > 0:
                    position = PositionRecord(
                        id=existing.id,
                        timestamp=datetime.now(),
                        token_id=token_id,
                        market_slug=market_slug,
                        market_id=market_id,
                        balance=new_balance,
                        avg_entry_price=existing.avg_entry_price,
                        current_price=price,
                        unrealized_pnl=(price - existing.avg_entry_price) * new_balance,
                        side='LONG',
                    )
                else:
                    # Position closed
                    self.db._get_connection().execute(
                        "DELETE FROM positions WHERE token_id = ?",
                        (token_id,)
                    )
                    logger.info(f"Position closed for {token_id}: PnL ${realized_pnl:.2f}")
                    return
            else:
                logger.warning(f"Sell attempt with no position: {token_id}")
                return
        
        self.db.save_position(position)
    
    def get_status(self) -> Dict:
        """Get complete system status."""
        circuit_status = get_circuit_status()
        daily_stats = self.db.get_daily_stats()
        
        return {
            'circuit_breaker': circuit_status,
            'daily_trading_stats': daily_stats,
            'dry_run': self.dry_run,
            'positions_count': len(self.db.get_all_positions()),
        }
    
    def emergency_stop(self, reason: str):
        """Trigger emergency stop."""
        from utils.circuit_breaker import trigger_emergency_stop
        trigger_emergency_stop(reason)
        logger.critical(f"EMERGENCY STOP TRIGGERED: {reason}")
    
    def resume_trading(self):
        """Resume trading after halt."""
        from utils.circuit_breaker import clear_emergency_stop
        clear_emergency_stop()
        logger.info("Trading resumed")
    
    def get_circuit_breaker_status(self) -> Dict:
        """Get circuit breaker status."""
        return get_circuit_status()


# Convenience function for quick execution
def execute_trade_with_safety(
    token_id: str,
    signal: str,
    side: str,
    price: float,
    size_usdc: float,
    confidence: float,
    signal_strength: float,
    polymarket_up_price: float,
    **kwargs
) -> Dict:
    """Quick execution function with safety wrappers.
    
    Creates a new EnhancedOrderExecutor each call (for simple scripts).
    For production, create and reuse EnhancedOrderExecutor instance.
    """
    executor = EnhancedOrderExecutor(
        dry_run=os.getenv('DRY_RUN', 'true').lower() == 'true',
        db_path=os.getenv('DB_PATH', 'data/trading.db'),
    )
    
    return executor.execute_signal(
        token_id=token_id,
        side=side,
        price=price,
        size_usdc=size_usdc,
        signal=signal,
        confidence=confidence,
        signal_strength=signal_strength,
        polymarket_up_price=polymarket_up_price,
        **kwargs
    )


if __name__ == "__main__":
    # Test the enhanced executor
    logging.basicConfig(level=logging.INFO)
    
    print("Testing EnhancedOrderExecutor...")
    
    # Create test instance (dry run)
    executor = EnhancedOrderExecutor(dry_run=True, db_path="data/test.db")
    
    # Test circuit breaker
    print(f"Circuit status: {executor.get_circuit_breaker_status()}")
    
    # Test trade (dry run)
    result = executor.execute_signal(
        token_id="test-token-123",
        side="BUY",
        price=0.55,
        size_usdc=5.0,
        signal="BUY_UP",
        confidence=0.8,
        signal_strength=0.75,
        polymarket_up_price=0.55,
        market_slug="btc-updown-15m-test",
    )
    
    print(f"Trade result: {result}")
    print(f"System status: {executor.get_status()}")
