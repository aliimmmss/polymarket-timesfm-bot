"""Order execution for Polymarket using py-clob-client V2.

Based on official Polymarket documentation:
- https://docs.polymarket.com/trading/quickstart
- https://github.com/Polymarket/py-clob-client-v2

Uses correct V2 SDK pattern:
1. ClobClient(host, chainId, signer) for temp L1 client
2. create_or_derive_api_key() to get L2 credentials
3. ClobClient(host, chainId, signer, creds, signature_type, funder) for trading
4. create_and_post_order(OrderArgs, PartialCreateOrderOptions, OrderType)

SAFETY: DRY_RUN mode enforced by default.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import requests

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
    """Execute trades on Polymarket using py-clob-client V2.
    
    SAFETY FEATURES:
    - DRY_RUN mode by default (logs orders without executing)
    - Maximum order size limits
    - Daily loss limits
    - Proper API credential derivation (L1 → L2)
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
            signature_type: 0=EOA (wallet pays gas), 1=Proxy eoasigner, 2=Proxy eosigner
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
        """Initialize py-clob-client V2 with proper credential derivation.
        
        V2 SDK Pattern (2-level auth):
        1. Create temp ClobClient with signer (L1: wallet signature)
        2. Derive API credentials via create_or_derive_api_key() (L2: HMAC)
        3. Create trading ClobClient with L2 credentials
        """
        if not self.private_key:
            raise ValueError("PRIVATE_KEY required for live trading")
        
        try:
            # V2 imports - separate package
            from py_clob_client_v2 import ClobClient, ApiCreds, OrderArgs, Side, OrderType, PartialCreateOrderOptions
            from py_clob_client_v2.order_utils import SignatureTypeV2, generate_order_salt
            from py_clob_client_v2.order_utils.model.side import Side as SideEnum
            
            # Store imported types for later use
            self._Side = SideEnum
            self._OrderType = OrderType
            
            # Create signer from private key
            from py_clob_client_v2.order_utils import Signer
            signer = Signer(private_key=self.private_key)
            
            # STEP 1: Create temp client (L1 auth only - wallet signature)
            temp_client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                signer=signer,
            )
            
            # STEP 2: Derive L2 API credentials (HMAC key/secret)
            # This creates/retrieves API credentials tied to the wallet
            self._api_creds: ApiCreds = temp_client.create_or_derive_api_key()
            logger.info("API credentials derived successfully (L2 auth ready)")
            
            # STEP 3: Create trading client with both L1+L2 auth
            # Funder: for proxy wallets, this is the proxy; for EOA, it's the wallet itself
            funder = self.funder_address or signer.address()
            
            # Use appropriate signature type constant from V2
            sig_type_map = {
                0: SignatureTypeV2.EOA,        # EOA wallet
                1: SignatureTypeV2.POLY_PROXY, # Polymarket proxy with eoasigner
                2: SignatureTypeV2.POLY_GNOSIS_SAFE,  # Gnosis Safe
            }
            sig_type = sig_type_map.get(self.signature_type, SignatureTypeV2.EOA)
            
            self._client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                signer=signer,
                creds=self._api_creds,
                signature_type=sig_type,
                funder=funder,
            )
            
            logger.info(f"ClobClient V2 initialized (sig_type={self.signature_type}, funder={funder})")
            
        except ImportError as e:
            raise ImportError(
                "py-clob-client-v2 required for CLOB V2 trading. "
                "Install: pip install py-clob-client-v2. "
                f"Original error: {e}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize ClobClient V2: {e}")
            raise
    
    def _get_market_config(self, token_id: str) -> Tuple[str, bool]:
        """Get tickSize and negRisk for a market.

        Required for order creation in V2.
        Tries SDK methods first, falls back to direct REST API.

        Args:
            token_id: CLOB token ID

        Returns:
            (tick_size, neg_risk) tuple - tick_size as string, neg_risk as bool
        """
        if self.dry_run:
            return ("0.01", False)

        tick_size = "0.01"  # Default 1¢
        neg_risk = False     # Default for binary markets

        try:
            # Try V2 SDK methods if available
            if hasattr(self._client, 'get_market'):
                market = self._client.get_market(token_id)
                if market:
                    ts = market.get('tick_size') or market.get('tickSize')
                    if ts:
                        tick_size = str(ts)
                    nr = market.get('neg_risk')
                    if nr is not None:
                        neg_risk = bool(nr)
                        return (tick_size, neg_risk)

            # Try dedicated methods
            if hasattr(self._client, 'get_tick_size'):
                ts = self._client.get_tick_size(token_id)
                if ts:
                    tick_size = str(ts)
            if hasattr(self._client, 'get_neg_risk'):
                nr = self._client.get_neg_risk(token_id)
                if nr is not None:
                    neg_risk = bool(nr)
                    return (tick_size, neg_risk)

        except Exception as e:
            logger.warning(f"SDK methods failed: {e}, trying direct REST...")

        # FALLBACK: Direct REST call to CLOB exchange endpoint (public, no auth)
        try:
            resp = requests.get(
                f"https://clob.polymarket.com/exchange/v2/market/{token_id}",
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                # Parse response — structure may vary, check common keys
                ts = data.get('tick_size') or data.get('tickSize')
                if ts:
                    tick_size = str(ts)
                nr = data.get('neg_risk')
                if nr is not None:
                    neg_risk = bool(nr)
                logger.info(f"Market config from REST: tick_size={tick_size}, neg_risk={neg_risk}")
                return (tick_size, neg_risk)
        except Exception as e:
            logger.warning(f"REST fallback failed: {e}")

        # All methods failed — use safe defaults
        logger.warning("All market config methods failed, using defaults (tick_size=0.01, neg_risk=False)")
        return ("0.01", False)

    def _call_with_retry(
        self,
        func,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        *args,
        **kwargs
    ) -> any:
        """Call a function with exponential backoff retry on transient errors.

        Retries on: Timeout, ConnectionError, 5xx HTTP, 429 Too Many Requests.
        Does NOT retry on business logic errors (invalid order, insufficient balance).

        Args:
            func: Callable to execute
            max_attempts: Maximum retry attempts (default 3)
            base_delay: Base delay in seconds, doubles each retry (1 → 2 → 4)
            *args, **kwargs: Arguments to pass to func

        Returns:
            Result from func on success

        Raises:
            Last exception if all attempts fail
        """
        last_exception = None
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exception = e
                if attempt < max_attempts - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Network error: {e}. Retrying in {delay:.1f}s... (attempt {attempt + 1}/{max_attempts})")
                    time.sleep(delay)
                else:
                    logger.error(f"Network error after {max_attempts} attempts: {e}")
            except Exception as e:
                # Check if it's an HTTP error with status code
                if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                    status = e.response.status_code
                    if status in [429, 500, 502, 503, 504]:
                        last_exception = e
                        if attempt < max_attempts - 1:
                            delay = base_delay * (2 ** attempt)
                            logger.warning(f"HTTP {status} error. Retrying in {delay:.1f}s... (attempt {attempt + 1}/{max_attempts})")
                            time.sleep(delay)
                            continue
                        else:
                            logger.error(f"HTTP {status} error after {max_attempts} attempts")
                    else:
                        # Non-retryable HTTP error (4xx other than 429)
                        raise
                else:
                    # Non-retryable exception
                    raise
        # If we get here, all retries failed
        if last_exception:
            raise last_exception
        return None  # Shouldn't reach
    
    def buy_token(
        self,
        token_id: str,
        price: float,
        size_usdc: float,
        order_type: str = "GTC",  # GTC, FOK, IOC, FAK
    ) -> Dict:
        """Place a BUY order for a token (V2).
        
        Args:
            token_id: CLOB token ID for "Up" or "Down"
            price: Limit price (0.01 to 0.99 probability)
            size_usdc: Amount in USDC to spend
            order_type: Order type - GTC (Good-till-cancel), FOK, IOC, FAK
            
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
        """Place a SELL order for a token (V2).
        
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
        """Create and post order using V2 SDK pattern."""
        
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
        """Place actual order using V2 SDK.
        
        V2 Pattern:
        1. PartialCreateOrderOptions(tick_size, neg_risk)
        2. OrderArgsV2(token_id, price, size, side=Side enum, expiration, builder_code, metadata)
        3. create_and_post_order(order_args=..., options=..., order_type=...)
        """
        
        try:
            from py_clob_client_v2 import OrderArgs, Side, OrderType, PartialCreateOrderOptions
            
            # Get market config (tick_size, neg_risk)
            tick_size, neg_risk = self._get_market_config(token_id)
            
            # Calculate size in tokens
            # V2 OrderArgs 'size' is always token amount (not USDC)
            if is_sell:
                size_tokens = size  # SELL: size already in tokens
            else:
                size_tokens = size / price  # BUY: convert USDC → token amount
            
            # Build order args (V2 uses Side enum, not string constants)
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size_tokens,
                side=Side.BUY if side == 'BUY' else Side.SELL,
                # Optional fields defaulted:
                expiration=0,  # No expiration
                builder_code="0x" + "0"*64,  # BYTES32_ZERO - no builder fee
                metadata="0x" + "0"*64,     # BYTES32_ZERO - no metadata
            )
            
            # Build order options
            options = PartialCreateOrderOptions(
                tick_size=tick_size,
                neg_risk=neg_risk,
            )
            
            # Map order type string to V2 OrderType enum
            order_type_map = {
                'GTC': OrderType.GTC,
                'FOK': OrderType.FOK,
                'IOC': OrderType.IOC,
                'FAK': OrderType.FAK,
            }
            sdk_order_type = order_type_map.get(order_type.upper(), OrderType.GTC)

            # STEP: Create and post order (with retry on transient failures)
            response = self._call_with_retry(
                self._client.create_and_post_order,
                max_attempts=3,
                base_delay=1.0,
                order_args=order_args,
                options=options,
                order_type=sdk_order_type,
            )
            
            # Extract order ID - V2 response structure may vary
            order_id = response.get('orderID') or response.get('id') or response.get('order_id')
            status = response.get('status', 'UNKNOWN')
            
            logger.info(f"Order placed: {order_id} (status: {status})")
            
            # Track order
            order = Order(
                order_id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size_usdc=size if not is_sell else size_tokens * price,
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
                'size_usdc': size if not is_sell else size_tokens * price,
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
                'filled': order.get('status') == 'FILLED',
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
            return orders if isinstance(orders, list) else []
        except Exception as e:
            logger.error(f"Get open orders failed: {e}")
            return []
    
    def get_fills(self) -> List[Dict]:
        """Get filled orders (trade history).
        
        V2: get_fills() returns executed trades.
        Returns list of fill objects with size_matched, price, etc.
        """
        if self.dry_run:
            return []
        
        try:
            fills = self._client.get_fills()
            return fills if isinstance(fills, list) else []
        except Exception as e:
            logger.error(f"Get fills failed: {e}")
            return []
    
    def get_balances(self) -> Dict:
        """Get wallet balances."""
        if self.dry_run:
            # Compute paper balance from trades DB: initial_capital + realized_pnl - locked_capital
            try:
                import yaml
                import sqlite3
                # Locate config and DB
                home = os.path.expanduser('~')
                config_path = os.path.join(home, 'polymarket-timesfm-bot', 'data', 'pilot_config.yaml')
                db_path = os.path.join(home, 'polymarket-timesfm-bot', 'data', 'trading.db')
                initial_capital = 1000.0
                if os.path.exists(config_path):
                    with open(config_path) as fh:
                        cfg = yaml.safe_load(fh) or {}
                    initial_capital = float(cfg.get('initial_capital', 1000.0))
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    # Realized P&L sum
                    cur.execute("SELECT SUM(pnl) FROM trades WHERE pnl IS NOT NULL")
                    realized = cur.fetchone()[0] or 0.0
                    # Open positions capital (size_usdc)
                    cur.execute("SELECT SUM(size_usdc) FROM trades WHERE pnl IS NULL")
                    locked = cur.fetchone()[0] or 0.0
                    conn.close()
                    available = initial_capital + realized - locked
                    return {'USDC': round(available, 2), 'positions': {}}
            except Exception as e:
                logger.debug(f"Dry-run balance compute failed: {e}")
            return {'USDC': 1000.0, 'positions': {}}
        
        try:
            balances = self._client.get_balances()
            # V2 balances format: may return Balances object or dict
            if hasattr(balances, '__dict__'):
                balances = balances.__dict__
            return {
                'USDC': float(balances.get('USDC', 0)),
                'positions': {
                    str(b.get('asset', '')): float(b.get('balance', 0))
                    for b in balances.get('positions', [])
                    if float(b.get('balance', 0)) > 0
                },
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
    
    def get_orders(self) -> List[Dict]:
        """Get all orders (open + history)."""
        if self.dry_run:
            return []
        try:
            orders = self._client.get_orders()
            return orders if isinstance(orders, list) else []
        except Exception as e:
            logger.error(f"Get orders failed: {e}")
            return []


def test_order_executor() -> None:
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
