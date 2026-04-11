"""Order execution for Polymarket using official py-clob-client SDK v2.

Uses correct SDK pattern per docs.polymarket.com:
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

logger = logging.getLogger(__name__)

# Global safety settings
DRY_RUN = True
MAX_ORDER_SIZE_USDC = 10.0
DAILY_LOSS_LIMIT_USDC = 20.0

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


@dataclass
class Order:
    """Represents a trade order."""
    order_id: str
    token_id: str
    side: str
    price: float
    size_usdc: float
    status: str
    timestamp: float
    dry_run: bool = False


class OrderExecutorV2:
    """Execute trades using official py-clob-client SDK pattern."""
    
    def __init__(
        self,
        private_key: Optional[str] = None,
        dry_run: bool = True,
        max_order_size: float = 10.0,
        daily_loss_limit: float = 20.0,
        signature_type: int = 0,  # 0=EOA, 1=Proxy w/ eosigner, 2=Proxy w/ eoasigner
    ):
        """Initialize executor."""
        self.dry_run = dry_run or DRY_RUN
        self.max_order_size = min(max_order_size, MAX_ORDER_SIZE_USDC)
        self.daily_loss_limit = min(daily_loss_limit, DAILY_LOSS_LIMIT_USDC)
        self.signature_type = signature_type
        
        self.private_key = private_key or os.getenv('PRIVATE_KEY')
        self.funder_address = os.getenv('FUNDER_ADDRESS')
        
        self._daily_pnl = 0.0
        self._orders: List[Order] = []
        self._client = None
        self._api_creds = None
        
        if not self.dry_run:
            self._init_client()
        else:
            logger.info("[DRY_RUN] V2 executor initialized")
    
    def _init_client(self) -> None:
        """Initialize ClobClient with proper credential derivation per docs."""
        if not self.private_key:
            raise ValueError("PRIVATE_KEY required for live trading")
        
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.signer import Signer
            
            # Step 1: Create signer
            signer = Signer(private_key=self.private_key)
            
            # Step 2: Create temp client
            temp_client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                signer=signer,
            )
            
            # Step 3: Derive API credentials
            self._api_creds = temp_client.create_or_derive_api_key()
            logger.info("API credentials derived")
            
            # Step 4: Create trading client
            funder = self.funder_address or signer.address
            self._client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                signer=signer,
                creds=self._api_creds,
                signature_type=self.signature_type,
                funder=funder,
            )
            
            logger.info(f"ClobClient V2 ready (sig_type={self.signature_type})")
            
        except ImportError:
            raise ImportError("py-clob-client required: pip install py-clob-client")
    
    def _get_market_config(self, token_id: str) -> Tuple[str, bool]:
        """Get tickSize and negRisk for market."""
        if self.dry_run:
            return ("0.01", False)
        
        try:
            # Try SDK methods
            tick_size = "0.01"
            neg_risk = False
            
            if hasattr(self._client, 'get_tick_size'):
                tick_size = self._client.get_tick_size(token_id)
            if hasattr(self._client, 'get_neg_risk'):
                neg_risk = self._client.get_neg_risk(token_id)
                
            return (tick_size, neg_risk)
        except Exception as e:
            logger.warning(f"Using default market config: {e}")
            return ("0.01", False)
    
    def buy_token(self, token_id: str, price: float, size_usdc: float) -> Dict:
        """Place BUY order."""
        return self._create_order(token_id, "BUY", price, size_usdc)
    
    def sell_token(self, token_id: str, price: float, size_tokens: float) -> Dict:
        """Place SELL order."""
        return self._create_order(token_id, "SELL", price, size_tokens, is_sell=True)
    
    def _create_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        is_sell: bool = False,
    ) -> Dict:
        """Create order with official SDK pattern."""
        
        # Safety checks
        if not is_sell and size > self.max_order_size:
            size = self.max_order_size
        
        if self._daily_pnl < -self.daily_loss_limit:
            return {'success': False, 'error': 'Daily loss limit reached'}
        
        price = max(0.01, min(0.99, price))
        
        if self.dry_run:
            return self._dry_run_order(side, token_id, price, size)
        
        return self._place_live_order(token_id, side, price, size, is_sell)
    
    def _place_live_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        is_sell: bool,
    ) -> Dict:
        """Place live order with official SDK."""
        try:
            from py_clob_client.clob_types import OrderArgs, OrderBookConfig
            from py_clob_client.order_builder.constants import BUY, SELL, OrderType
            
            # Get config
            tick_size, neg_risk = self._get_market_config(token_id)
            
            # Calculate size
            if is_sell:
                size_tokens = size
            else:
                size_tokens = size / price
            
            # Create OrderArgs
            order_args = OrderArgs(
                price=price,
                size=size_tokens,
                side=SELL if side == 'SELL' else BUY,
                token_id=token_id,
            )
            
            # Create OrderBookConfig
            order_book_config = OrderBookConfig(
                tick_size=tick_size,
                neg_risk=neg_risk,
            )
            
            # Place order
            response = self._client.create_and_post_order(
                order_args=order_args,
                orderbook_config=order_book_config,
                order_type=OrderType.GTC,
            )
            
            order_id = response.get('orderID') or response.get('id')
            
            order = Order(
                order_id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size_usdc=size if not is_sell else size * price,
                status=response.get('status', 'PENDING'),
                timestamp=time.time(),
            )
            self._orders.append(order)
            
            return {
                'success': True,
                'order_id': order_id,
                'side': side,
                'price': price,
                'status': response.get('status'),
            }
            
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def _dry_run_order(self, side, token_id, price, size) -> Dict:
        """Dry run - log only."""
        order_id = f"DRY_RUN_{int(time.time() * 1000)}"
        
        logger.info(f"[DRY_RUN_V2] {side}:")
        logger.info(f"  Token: {token_id[:30]}...")
        logger.info(f"  Price: {price:.4f}")
        logger.info(f"  Size: ${size:.2f} USDC")
        
        order = Order(
            order_id=order_id,
            token_id=token_id,
            side=side,
            price=price,
            size_usdc=size,
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
            'size_usdc': size,
            'dry_run': True,
        }
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        if self.dry_run:
            return True
        try:
            self._client.cancel_order(order_id)
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False
    
    def get_balances(self) -> Dict:
        """Get balances."""
        if self.dry_run:
            return {'USDC': 1000.0}
        try:
            return self._client.get_balances()
        except Exception as e:
            logger.error(f"Get balances failed: {e}")
            return {}
    
    def update_pnl(self, pnl: float) -> None:
        self._daily_pnl += pnl
