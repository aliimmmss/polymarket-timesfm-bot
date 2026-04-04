"""Order execution for Polymarket using py-clob-client.

Based on research from:
- polymarket-bot/polymarket_auto_trade.py (Chinese bot)

IMPORTANT: DRY_RUN mode is enforced by default.
Real orders require explicit configuration.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Global safety settings
DRY_RUN = True  # MUST default to True
MAX_ORDER_SIZE_USDC = 10.0
DAILY_LOSS_LIMIT_USDC = 20.0


@dataclass
class Order:
    """Represents a trade order."""
    order_id: str
    token_id: str
    side: str  # 'BUY' or 'SELL'
    price: float
    size: float
    status: str
    timestamp: float
    dry_run: bool = False


class OrderExecutor:
    """Execute trades on Polymarket using py-clob-client.
    
    SAFETY FEATURES:
    - DRY_RUN mode by default (logs orders without executing)
    - Maximum order size limits
    - Daily loss limits
    """
    
    CLOB_API = "https://clob.polymarket.com"
    CHAIN_ID = 137  # Polygon
    
    def __init__(
        self,
        private_key: Optional[str] = None,
        dry_run: bool = True,
        max_order_size: float = 10.0,
        daily_loss_limit: float = 20.0,
    ):
        """Initialize order executor.
        
        Args:
            private_key: Wallet private key (required for real trading)
            dry_run: If True, only log orders without executing
            max_order_size: Maximum order size in USDC
            daily_loss_limit: Maximum daily loss in USDC
        """
        self.dry_run = dry_run or DRY_RUN
        self.max_order_size = min(max_order_size, MAX_ORDER_SIZE_USDC)
        self.daily_loss_limit = min(daily_loss_limit, DAILY_LOSS_LIMIT_USDC)
        
        # Read from environment if not provided
        self.private_key = private_key or os.getenv('PRIVATE_KEY')
        self.funder_address = os.getenv('FUNDER_ADDRESS')
        self.signature_type = int(os.getenv('SIGNATURE_TYPE', '2'))
        
        # Trading state
        self._daily_pnl: float = 0.0
        self._orders: List[Order] = []
        self._client = None
        
        # Initialize client if not dry run
        if not self.dry_run:
            self._init_client()
        else:
            logger.info("Order executor initialized in DRY_RUN mode")
    
    def _init_client(self) -> None:
        """Initialize py-clob-client."""
        if not self.private_key:
            raise ValueError("PRIVATE_KEY required for live trading")
        
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            
            self._client = ClobClient(self.CLOB_API, self.CHAIN_ID)
            
            # Derive API credentials
            creds = self._client.derive_api_creds(
                self.private_key,
                self.signature_type,
            )
            self._client.set_api_creds(creds)
            
            logger.info("py-clob-client initialized")
            
        except ImportError:
            raise ImportError("py-clob-client required: pip install py-clob-client")
    
    def buy_token(
        self,
        token_id: str,
        price: float,
        size_usdc: float,
    ) -> Dict:
        """Place a BUY limit order for a token.
        
        Args:
            token_id: CLOB token ID for "Up" or "Down"
            price: Limit price (0.01 to 0.99 probability)
            size_usdc: Amount in USDC to spend
        
        Returns:
            Dict with order details or error
        """
        # Safety checks
        if size_usdc > self.max_order_size:
            logger.warning(f"Order size {size_usdc} exceeds max {self.max_order_size}")
            size_usdc = self.max_order_size
        
        if self._daily_pnl < -self.daily_loss_limit:
            logger.error(f"Daily loss limit reached: ${self._daily_pnl:.2f}")
            return {
                'success': False,
                'error': 'Daily loss limit reached',
            }
        
        # Validate price
        price = max(0.01, min(0.99, price))
        
        if self.dry_run:
            return self._dry_run_order('BUY', token_id, price, size_usdc)
        
        return self._place_order(token_id, 'BUY', price, size_usdc)
    
    def sell_token(
        self,
        token_id: str,
        price: float,
        size_tokens: float,
    ) -> Dict:
        """Place a SELL limit order for a token.
        
        Args:
            token_id: CLOB token ID
            price: Limit price (0.01 to 0.99)
            size_tokens: Number of tokens to sell
        
        Returns:
            Dict with order details or error
        """
        # Validate price
        price = max(0.01, min(0.99, price))
        
        if self.dry_run:
            return self._dry_run_order('SELL', token_id, price, size_tokens)
        
        return self._place_order(token_id, 'SELL', price, size_tokens, is_sell=True)
    
    def _dry_run_order(
        self,
        side: str,
        token_id: str,
        price: float,
        size: float,
    ) -> Dict:
        """Log order without executing (DRY_RUN mode)."""
        order_id = f"DRY_RUN_{int(time.time() * 1000)}"
        
        logger.info(f"[DRY RUN] {side} order:")
        logger.info(f"  Token: {token_id[:20]}...")
        logger.info(f"  Price: ${price:.4f}")
        logger.info(f"  Size: ${size:.2f} USDC")
        
        order = Order(
            order_id=order_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            status='DRY_RUN',
            timestamp=time.time(),
            dry_run=True,
        )
        self._orders.append(order)
        
        return {
            'success': True,
            'order_id': order_id,
            'side': side,
            'price': price,
            'size': size,
            'dry_run': True,
        }
    
    def _place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        is_sell: bool = False,
    ) -> Dict:
        """Place actual order on Polymarket."""
        try:
            from py_clob_client.clob_types import OrderArgs
            from py_clob_client.order_builder.constants import BUY, SELL
            
            # Calculate size in tokens for buy, or use provided size for sell
            if not is_sell:
                # Buy: size is USDC, convert to tokens
                size_tokens = size / price
            else:
                size_tokens = size
            
            order_args = OrderArgs(
                price=price,
                size=size_tokens,
                side=BUY if side == 'BUY' else SELL,
                token_id=token_id,
            )
            
            resp = self._client.create_order(order_args)
            order_id = resp.get('orderID') or resp.get('id')
            
            logger.info(f"Order placed: {order_id}")
            
            order = Order(
                order_id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                status='PENDING',
                timestamp=time.time(),
            )
            self._orders.append(order)
            
            return {
                'success': True,
                'order_id': order_id,
                'side': side,
                'price': price,
                'size': size,
            }
            
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return {
                'success': False,
                'error': str(e),
            }
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            True if cancelled successfully
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel order: {order_id}")
            return True
        
        try:
            self._client.cancel_order(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Dict:
        """Check order status.
        
        Args:
            order_id: Order ID to check
        
        Returns:
            Dict with status information
        """
        if order_id.startswith('DRY_RUN'):
            return {
                'status': 'DRY_RUN',
                'filled': False,
            }
        
        try:
            order = self._client.get_order(order_id)
            return {
                'status': order.get('status'),
                'filled': order.get('status') == 'LIVE',
                'size_matched': float(order.get('size_matched', 0)),
            }
        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return {'status': 'UNKNOWN', 'error': str(e)}
    
    def get_positions(self) -> List[Dict]:
        """Get current open positions.
        
        Returns:
            List of position dicts
        """
        if self.dry_run:
            return []
        
        try:
            balances = self._client.get_balances()
            return [
                {
                    'token': b['asset'],
                    'balance': float(b['balance']),
                }
                for b in balances
                if float(b.get('balance', 0)) > 0
            ]
        except Exception as e:
            logger.error(f"Get positions failed: {e}")
            return []
    
    def update_pnl(self, pnl: float) -> None:
        """Update daily P&L tracking.
        
        Args:
            pnl: Profit/loss amount in USDC
        """
        self._daily_pnl += pnl
        logger.info(f"Daily P&L updated: ${self._daily_pnl:.2f}")
    
    def reset_daily_limits(self) -> None:
        """Reset daily limits (call at market open)."""
        self._daily_pnl = 0.0
        logger.info("Daily limits reset")


# Convenience function for testing
def test_order_executor():
    """Test order executor in dry run mode."""
    executor = OrderExecutor(dry_run=True)
    
    # Test buy
    result = executor.buy_token(
        token_id="test_token_id",
        price=0.55,
        size_usdc=5.0,
    )
    print("Buy result:", result)
    
    # Test sell
    result = executor.sell_token(
        token_id="test_token_id",
        price=0.95,
        size_tokens=5.0,
    )
    print("Sell result:", result)
    
    return executor


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_order_executor()
