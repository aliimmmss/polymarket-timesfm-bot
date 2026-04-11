"""Order execution for Polymarket using py-clob-client (Official SDK Pattern).

Based on official Polymarket documentation:
- https://docs.polymarket.com/trading/quickstart
- https://github.com/Polymarket/py-clob-client

Uses correct SDK pattern:
1. ClobClient(host, chainId, signer) for temp client
2. create_or_derive_api_key() to get credentials
3. ClobClient(host, chainId, signer, creds, signature_type, funder) for trading
4. create_and_post_order(OrderArgs, OrderBookConfig, OrderType) for orders

SAFETY: DRY_RUN mode enforced by default.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from decimal import Decimal

logger = logging.getLogger(__name__)

# Global safety settings
DRY_RUN = True  # MUST default to True
MAX_ORDER_SIZE_USDC = 10.0
DAILY_LOSS_LIMIT_USDC = 20.0

# Host constants
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet


@dataclass
class Order:
    """Represents a trade order."""
    order_id: str
    token_id: str
    side: str  # 'BUY' or 'SELL'
    price: float  # Probability 0-1
    size_usdc: float  # USDC amount
    status: str
    timestamp: float
    dry_run: bool = False
    maker: bool = False  # True if limit order on book


class OrderExecutor:
    """Execute trades on Polymarket using official py-clob-client SDK.
    
    SAFETY FEATURES:
    - DRY_RUN mode by default (logs orders without executing)
    - Maximum order size limits
    - Daily loss limits
    - Proper API credential derivation
    - Signature type handling (EOA vs Proxy)
    """
    
    def __init__(
        self,
        private_key: Optional[str] = None,
        dry_run: bool = True,
        max_order_size: float = 10.0,
        daily_loss_limit: float = 20.0,
        signature_type: int = 0,  # 0=EOA, 1=Polymarket proxy w/ eoasigner, 2=Polymarket proxy w/ eosigner
    ):
        """Initialize order executor.
        
        Args:
            private_key: Wallet private key (required for real trading)
            dry_run: If True, only log orders without executing
            max_order_size: Maximum order size in USDC
            daily_loss_limit: Maximum daily loss in USDC
            signature_type: 0=EOA (wallet pays gas), 1/2=Proxy wallet (gasless)
        """
        self.dry_run = dry_run or DRY_RUN
        self.max_order_size = min(max_order_size, MAX_ORDER_SIZE_USDC)
        self.daily_loss_limit = min(daily_loss_limit, DAILY_LOSS_LIMIT_USDC)
        self.signature_type = signature_type
        
        # Read from environment if not provided
        self.private_key = private_key or os.getenv('PRIVATE_KEY')
        self.funder_address = os.getenv('FUNDER_ADDRESS')
        
        # Trading state
        self._daily_pnl: float = 0.0
        self._orders: List[Order] = []
        self._client = None
        self._api_creds = None
        
        # Initialize client if not dry run
        if not self.dry_run:
            self._init_client()
        else:
            logger.info("[DRY_RUN] Order executor initialized - no real orders")
    
    def _init_client(self) -> None:
        """Initialize py-clob-client with proper API credential derivation.
        
        Official SDK Pattern:
        1. Create temp ClobClient with signer
        2. Derive API credentials via create_or_derive_api_key()
        3. Create trading ClobClient with credentials
        """
        if not self.private_key:
            raise ValueError("PRIVATE_KEY required for live trading")
        
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.signer import Signer
            
            # Create signer from private key
            signer = Signer(private_key=self.private_key)
            
            # STEP 1: Create temp client to derive credentials
            temp_client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                signer=signer,
            )
            
            # STEP 2: Derive API credentials (cached on backend)
            self._api_creds = temp_client.create_or_derive_api_key()
            logger.info("API credentials derived successfully")
            
            # STEP 3: Create trading client with credentials
            # EOA (type 0): funder is wallet address
            # Proxy (type 1/2): funder is proxy wallet address (check polymarket.com/settings)
            funder = self.funder_address or signer.address
            
            self._client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                signer=signer,
                creds=self._api_creds,
                signature_type=self.signature_type,
                funder=funder,
            )
            
            logger.info(f"py-clob-client initialized (signature_type={self.signature_type}, funder={funder})")
            
        except ImportError as e:
            raise ImportError(f"py-clob-client required: pip install py-clob-client. Error: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize ClobClient: {e}")
            raise
    
    def _get_market_config(self, token_id: str) -> Tuple[str, bool]:
        """Get tickSize and negRisk for a market.
        
        Required for order creation.
        
        Args:
            token_id: CLOB token ID
            
        Returns:
            (tickSize, negRisk) tuple
        """
        if self.dry_run:
            return ("0.01", False)
        
        try:
            # Get market info from client
            # Note: py-clob-client may have different method names
            # Using defaults if methods unavailable
            tick_size = "0.01"  # Default, should query from market
            neg_risk = False     # Default for binary markets
            
            # Try to get from market data if available
            if hasattr(self._client, 'get_tick_size'):
                tick_size = self._client.get_tick_size(token_id)
            if hasattr(self._client, 'get_neg_risk'):
                neg_risk = self._client.get_neg_risk(token_id)
                
            return (tick_size, neg_risk)
        except Exception as e:
            logger.warning(f"Could not fetch market config: {e}, using defaults")
            return ("0.01", False)
    
    def buy_token(
        self,
        token_id: str,
        price: float,
        size_usdc: float,
        order_type: str = "GTC",  # GTC, FOK, IOC
    ) -> Dict:
        """Place a BUY order for a token.
        
        Args:
            token_id: CLOB token ID for "Up" or "Down"
            price: Limit price (0.01 to 0.99 probability)
            size_usdc: Amount in USDC to spend
            order_type: Order type - GTC (Good-till-cancel), FOK (Fill-or-kill), IOC (Immediate-or-cancel)
            
        Returns:
            Dict with order details or error
        """
        return self._create_order(token_id, "BUY", price, size_usdc, order_type)
    
    def sell_token(
        self,
        token_id: str,
        price: float,
        size_tokens: float,
        order_type: str = "GTC",
    ) -> Dict:
        """Place a SELL order for a token.
        
        Args:
            token_id: CLOB token ID
            price: Limit price (0.01 to 0.99)
            size_tokens: Number of tokens to sell
            order_type: Order type
            
        Returns:
            Dict with order details or error
        """
        return self._create_order(token_id, "SELL", price, size_tokens, order_type, is_sell=True)
    
    def _create_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "GTC",
        is_sell: bool = False,
    ) -> Dict:
        """Create and post order using official SDK pattern."""
        
        # Safety checks
        if not is_sell and size > self.max_order_size:
            logger.warning(f"Order size ${size:.2f} exceeds max ${self.max_order_size:.2f}")
            size = self.max_order_size
        
        if self._daily_pnl < -self.daily_loss_limit:
            return {
                'success': False,
                'error': f"Daily loss limit reached: ${self._daily_pnl:.2f}",
            }
        
        # Validate price bounds
        price = max(0.01, min(0.99, price))
        
        # DRY_RUN mode
        if self.dry_run:
            return self._dry_run_order(side, token_id, price, size)
        
        # Live trading
        return self._place_live_order(token_id, side, price, size, order_type, is_sell)
    
    def _place_live_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str,
        is_sell: bool,
    ) -> Dict:
        """Place actual order using official SDK pattern.
        
        Official Pattern:
        1. OrderArgs(token_id, price, size, side)
        2. OrderBookConfig(tickSize, negRisk)
        3. create_and_post_order(OrderArgs, OrderBookConfig, OrderType)
        """
        try:
            from py_clob_client.clob_types import OrderArgs, OrderBookConfig
            from py_clob_client.order_builder.constants import BUY, SELL, OrderType
            
            # Get market configuration
            tick_size, neg_risk = self._get_market_config(token_id)
            
            # STEP 1: Create OrderArgs
            # For BUY: size is USDC, need token count = USDC / price
            # For SELL: size is token count directly
            if is_sell:
                size_tokens = size
            else:
                size_tokens = size / price  # Convert USDC to token count
            
            order_args = OrderArgs(
                price=price,
                size=size_tokens,
                side=SELL if side == 'SELL' else BUY,
                token_id=token_id,
            )
            
            # STEP 2: Create OrderBookConfig
            order_book_config = OrderBookConfig(
                tick_size=tick_size,
                neg_risk=neg_risk,
            )
            
            # STEP 3: Map order type string to SDK constant
            order_type_map = {
                'GTC': OrderType.GTC,
                'FOK': OrderType.FOK,
                'IOC': OrderType.IOC,
            }
            sdk_order_type = order_type_map.get(order_type, OrderType.GTC)
            
            # STEP 4: Create and post order
            response = self._client.create_and_post_order(
                order_args=order_args,
                orderbook_config=order_book_config,
                order_type=sdk_order_type,
            )
            
            order_id = response.get('orderID') or response.get('id')
            status = response.get('status', 'UNKNOWN')
            
            logger.info(f"Order placed: {order_id} (status: {status})")
            
            # Track order
            order = Order(
                order_id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size_usdc=size if not is_sell else size * price,
                status=status,
                timestamp=time.time(),
                maker=(status == 'LIVE'),  # LIVE means resting on book
            )
            self._orders.append(order)
            
            return {
                'success': True,
                'order_id': order_id,
                'side': side,
                'price': price,
                'size_usdc': size if not is_sell else size * price,
                'size_tokens': size_tokens,
                'status': status,
                'tick_size': tick_size,
                'neg_risk': neg_risk,
            }
            
        except Exception as e:
            logger.error(f"Order failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'side': side,
                'price': price,
            }
    
    def _dry_run_order(
        self,
        side: str,
        token_id: str,
        price: float,
        size_usdc: float,
    ) -> Dict:
        """Log order without executing (DRY_RUN mode)."""
        order_id = f"DRY_RUN_{int(time.time() * 1000)}"
        
        logger.info(f"[DRY_RUN] {side} order:")
        logger.info(f"  Token: {token_id[:30]}...")
        logger.info(f"  Price: {price:.4f} (prob)")
        logger.info(f"  Size: ${size_usdc:.2f} USDC")
        logger.info(f"  Est. tokens: {size_usdc / price:.2f}")
        
        order = Order(
            order_id=order_id,
            token_id=token_id,
            side=side,
            price=price,
            size_usdc=size_usdc,
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
            'size_usdc': size_usdc,
            'size_tokens': size_usdc / price,
            'dry_run': True,
        }
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if self.dry_run:
            logger.info(f"[DRY_RUN] Would cancel order: {order_id}")
            return True
        
        try:
            self._client.cancel_order(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Dict:
        """Check order status."""
        if order_id.startswith('DRY_RUN'):
            return {'status': 'DRY_RUN', 'filled': False, 'dry_run': True}
        
        try:
            order = self._client.get_order(order_id)
            return {
                'status': order.get('status'),
                'filled': order.get('status') == 'LIVE',
                'size_matched': float(order.get('size_matched', 0)),
                'price_avg': float(order.get('price_avg', 0)),
            }
        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return {'status': 'UNKNOWN', 'error': str(e)}
    
    def get_open_orders(self) -> List[Dict]:
        """Get all open orders."""
        if self.dry_run:
            return [o.__dict__ for o in self._orders if o.status == 'DRY_RUN']
        
        try:
            orders = self._client.get_open_orders()
            return orders
        except Exception as e:
            logger.error(f"Get open orders failed: {e}")
            return []
    
    def get_trades(self) -> List[Dict]:
        """Get trade history."""
        if self.dry_run:
            return []
        
        try:
            trades = self._client.get_trades()
            return trades
        except Exception as e:
            logger.error(f"Get trades failed: {e}")
            return []
    
    def get_balances(self) -> Dict:
        """Get wallet balances."""
        if self.dry_run:
            return {'USDC': 1000.0, 'positions': {}}
        
        try:
            balances = self._client.get_balances()
            return {
                'USDC': float(balances.get('USDC', 0)),
                'positions': {
                    b['asset']: float(b['balance']) 
                    for b in balances 
                    if float(b.get('balance', 0)) > 0 and b['asset'] != 'USDC'
                }
            }
        except Exception as e:
            logger.error(f"Get balances failed: {e}")
            return {'USDC': 0.0, 'positions': {}}
    
    def update_pnl(self, pnl: float) -> None:
        """Update daily P&L tracking."""
        self._daily_pnl += pnl
        logger.info(f"Daily P&L: ${self._daily_pnl:.2f}")
    
    def reset_daily_limits(self) -> None:
        """Reset daily limits."""
        self._daily_pnl = 0.0
        logger.info("Daily limits reset")


def test_order_executor():
    """Test order executor in dry run mode."""
    logging.basicConfig(level=logging.INFO)
    
    executor = OrderExecutor(dry_run=True, signature_type=0)
    
    # Test buy (BTC UP token)
    result = executor.buy_token(
        token_id="0x1234567890abcdef1234567890abcdef12345678",  # Fake token ID
        price=0.55,
        size_usdc=5.0,
    )
    print(f"Buy result: {result}")
    
    # Test sell
    result = executor.sell_token(
        token_id="0x1234567890abcdef1234567890abcdef12345678",
        price=0.95,
        size_tokens=5.0 / 0.55,  # Tokens from earlier buy
    )
    print(f"Sell result: {result}")
    
    return executor


if __name__ == "__main__":
    test_order_executor()
