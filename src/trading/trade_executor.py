"""
Trade execution module for Polymarket Trading Bot.

This module handles:
- Order placement and execution on Polymarket
- Trade confirmation and slippage management
- Paper trading vs live trading modes
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import logging
from dataclasses import dataclass
import json
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """Container for trade order."""
    market_id: str
    order_type: str  # "BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"
    quantity: float  # Number of shares
    price: float  # Limit price (if None, market order)
    timestamp: datetime
    paper_trade: bool = True
    order_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, EXECUTED, CANCELLED, REJECTED
    executed_price: Optional[float] = None
    executed_quantity: Optional[float] = None
    executed_timestamp: Optional[datetime] = None
    fee_usd: float = 0.0
    slippage: float = 0.0
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Generate order ID if not provided."""
        if self.order_id is None:
            # Create deterministic ID from market_id and timestamp
            base_str = f"{self.market_id}_{self.order_type}_{self.timestamp.isoformat()}"
            self.order_id = hashlib.md5(base_str.encode()).hexdigest()[:16]
    
    @property
    def total_usd(self) -> float:
        """Calculate total USD value of order."""
        if self.executed_price and self.executed_quantity:
            return self.executed_price * self.executed_quantity
        return self.price * self.quantity if self.price else 0.0
    
    def mark_executed(
        self, 
        executed_price: float, 
        executed_quantity: float,
        fee_usd: float = 0.0,
        slippage: float = 0.0
    ):
        """Mark order as executed."""
        self.status = "EXECUTED"
        self.executed_price = executed_price
        self.executed_quantity = executed_quantity
        self.executed_timestamp = datetime.utcnow()
        self.fee_usd = fee_usd
        self.slippage = slippage
    
    def mark_cancelled(self):
        """Mark order as cancelled."""
        self.status = "CANCELLED"
    
    def mark_rejected(self, reason: str = ""):
        """Mark order as rejected."""
        self.status = "REJECTED"
        if self.metadata is None:
            self.metadata = {}
        self.metadata["rejection_reason"] = reason


class TradeExecutor:
    """Execute trades on Polymarket."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize trade executor.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Default configuration
        self.execution_config = {
            "paper_trading": True,
            "max_position_size_usd": 1000.0,
            "default_slippage": 0.001,  # 0.1% default slippage
            "max_slippage": 0.01,  # 1% maximum slippage
            "fee_percentage": 0.01,  # 1% trading fee
            "min_fee_usd": 0.10,
            "order_timeout_seconds": 30,
            "retry_attempts": 3,
            "retry_delay_seconds": 5,
            "mock_execution": True,  # Simulate execution for testing
        }
        
        # Update with config if provided
        if "execution" in self.config:
            self.execution_config.update(self.config["execution"])
        
        # State tracking
        self.open_orders: Dict[str, Order] = {}
        self.executed_orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []
        
        # Initialize Polymarket client if available
        self.polymarket_client = None
        
        logger.info(f"Initialized TradeExecutor (paper_trading={self.execution_config['paper_trading']})")
    
    def set_polymarket_client(self, client):
        """Set Polymarket client for order execution."""
        self.polymarket_client = client
    
    async def execute_order(
        self,
        market_id: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        paper_trade: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Order:
        """
        Execute a trade order.
        
        Args:
            market_id: Market ID
            order_type: "BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"
            quantity: Number of shares
            price: Limit price (if None, market order)
            paper_trade: Whether this is a paper trade
            metadata: Additional metadata
            
        Returns:
            Order object with execution results
        """
        # Determine if paper trading
        if paper_trade is None:
            paper_trade = self.execution_config["paper_trading"]
        
        # Create order
        order = Order(
            market_id=market_id,
            order_type=order_type,
            quantity=quantity,
            price=price if price else self._get_market_price(order_type),
            timestamp=datetime.utcnow(),
            paper_trade=paper_trade,
            metadata=metadata or {}
        )
        
        # Store as open order
        self.open_orders[order.order_id] = order
        
        logger.info(f"Executing order {order.order_id}: {order.order_type} "
                   f"{quantity} shares @ {order.price:.4f} for market {market_id}")
        
        try:
            # Execute based on mode
            if paper_trade or self.execution_config["mock_execution"]:
                # Paper trade or mock execution
                executed_order = await self._execute_paper_trade(order)
            else:
                # Live trade
                executed_order = await self._execute_live_trade(order)
            
            # Update order history
            self.order_history.append(executed_order)
            
            logger.info(f"Order {executed_order.order_id} executed: "
                       f"{executed_order.status} @ {executed_order.executed_price:.4f}")
            
            return executed_order
            
        except Exception as e:
            logger.error(f"Error executing order {order.order_id}: {e}")
            order.mark_rejected(str(e))
            self.order_history.append(order)
            return order
    
    async def _execute_paper_trade(self, order: Order) -> Order:
        """
        Execute a paper trade (simulated execution).
        
        Args:
            order: Order to execute
            
        Returns:
            Executed order
        """
        try:
            # Simulate execution delay
            await asyncio.sleep(0.5)
            
            # Get current market price for slippage calculation
            current_price = self._get_market_price(order.order_type)
            
            # Calculate slippage
            slippage = self._calculate_slippage(
                order_type=order.order_type,
                quantity=order.quantity,
                price=order.price,
                current_price=current_price
            )
            
            # Calculate execution price with slippage
            if order.order_type in ["BUY_YES", "BUY_NO"]:
                # Buying: price increases with slippage
                executed_price = order.price * (1 + slippage)
            else:
                # Selling: price decreases with slippage
                executed_price = order.price * (1 - slippage)
            
            # Clip to valid range
            executed_price = max(0.01, min(0.99, executed_price))
            
            # Calculate fee
            fee_usd = self._calculate_fee(executed_price * order.quantity)
            
            # Mark order as executed
            order.mark_executed(
                executed_price=executed_price,
                executed_quantity=order.quantity,
                fee_usd=fee_usd,
                slippage=slippage
            )
            
            # Update order tracking
            self.executed_orders[order.order_id] = order
            del self.open_orders[order.order_id]
            
            return order
            
        except Exception as e:
            logger.error(f"Error in paper trade execution: {e}")
            order.mark_rejected(f"Paper trade error: {e}")
            return order
    
    async def _execute_live_trade(self, order: Order) -> Order:
        """
        Execute a live trade on Polymarket.
        
        Note: This is a placeholder - actual implementation would require
        Polymarket API integration with wallet connectivity.
        
        Args:
            order: Order to execute
            
        Returns:
            Executed order
        """
        logger.warning("Live trading not implemented - using paper trade simulation")
        
        # For now, fall back to paper trading
        return await self._execute_paper_trade(order)
    
    def _get_market_price(self, order_type: str) -> float:
        """
        Get current market price for order type.
        
        Args:
            order_type: Order type ("BUY_YES", etc.)
            
        Returns:
            Current market price
        """
        # Placeholder - in real implementation, this would fetch from Polymarket API
        # For now, return a mock price
        if "YES" in order_type:
            return 0.55  # Mock YES price
        else:
            return 0.45  # Mock NO price
    
    def _calculate_slippage(
        self,
        order_type: str,
        quantity: float,
        price: float,
        current_price: float
    ) -> float:
        """
        Calculate expected slippage for an order.
        
        Args:
            order_type: Order type
            quantity: Order quantity
            price: Order price
            current_price: Current market price
            
        Returns:
            Slippage as decimal (e.g., 0.001 for 0.1%)
        """
        # Base slippage
        base_slippage = self.execution_config["default_slippage"]
        
        # Adjust for order size (larger orders = more slippage)
        size_multiplier = min(2.0, quantity / 100)  # Cap at 2x
        
        # Adjust for price difference
        price_diff = abs(price - current_price) / current_price
        price_multiplier = 1 + price_diff * 10
        
        # Calculate total slippage
        slippage = base_slippage * size_multiplier * price_multiplier
        
        # Cap at maximum
        slippage = min(slippage, self.execution_config["max_slippage"])
        
        return slippage
    
    def _calculate_fee(self, trade_value_usd: float) -> float:
        """
        Calculate trading fee.
        
        Args:
            trade_value_usd: Trade value in USD
            
        Returns:
            Fee in USD
        """
        fee_percentage = self.execution_config["fee_percentage"]
        min_fee = self.execution_config["min_fee_usd"]
        
        fee = trade_value_usd * fee_percentage
        return max(fee, min_fee)
    
    async def execute_signal(
        self,
        market_id: str,
        signal_type: str,
        position_size_pct: float,
        current_price: float,
        portfolio_value: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Order]:
        """
        Execute a trading signal.
        
        Args:
            market_id: Market ID
            signal_type: Signal type (e.g., "STRONG_BUY")
            position_size_pct: Position size as percentage of portfolio
            current_price: Current market price
            portfolio_value: Total portfolio value
            metadata: Additional metadata
            
        Returns:
            Executed order or None if no trade
        """
        # Convert signal type to order type
        order_type = self._signal_to_order_type(signal_type, market_id)
        if not order_type:
            logger.warning(f"Cannot convert signal {signal_type} to order type")
            return None
        
        # Calculate position size
        position_size_usd = portfolio_value * position_size_pct
        quantity = position_size_usd / current_price
        
        # Check minimum size
        min_trade_usd = 10.0  # Minimum $10 trade
        if position_size_usd < min_trade_usd:
            logger.debug(f"Position size too small: ${position_size_usd:.2f} < ${min_trade_usd}")
            return None
        
        # Check maximum position size
        max_position = self.execution_config["max_position_size_usd"]
        if position_size_usd > max_position:
            logger.info(f"Capping position size: ${position_size_usd:.2f} > ${max_position}")
            position_size_usd = max_position
            quantity = position_size_usd / current_price
        
        # Prepare metadata
        exec_metadata = metadata or {}
        exec_metadata.update({
            "signal_type": signal_type,
            "position_size_pct": position_size_pct,
            "portfolio_value": portfolio_value,
            "position_size_usd": position_size_usd,
        })
        
        # Execute order
        order = await self.execute_order(
            market_id=market_id,
            order_type=order_type,
            quantity=quantity,
            price=current_price,  # Market order at current price
            metadata=exec_metadata
        )
        
        return order
    
    def _signal_to_order_type(self, signal_type: str, market_id: str) -> Optional[str]:
        """
        Convert signal type to Polymarket order type.
        
        Args:
            signal_type: Signal type (e.g., "STRONG_BUY")
            market_id: Market ID (used to determine YES/NO side)
            
        Returns:
            Order type or None if invalid
        """
        # In a real implementation, we would need to know which side
        # the forecast is for. For simplicity, we'll assume:
        # - BUY signals = BUY_YES
        # - SELL signals = SELL_YES
        
        if "BUY" in signal_type:
            return "BUY_YES"
        elif "SELL" in signal_type:
            return "SELL_YES"
        else:
            return None
    
    def get_open_orders(self) -> List[Order]:
        """Get list of open orders."""
        return list(self.open_orders.values())
    
    def get_executed_orders(
        self,
        market_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Order]:
        """Get filtered list of executed orders."""
        orders = list(self.executed_orders.values())
        
        if market_id:
            orders = [o for o in orders if o.market_id == market_id]
        
        if start_date:
            orders = [o for o in orders if o.timestamp >= start_date]
        
        if end_date:
            orders = [o for o in orders if o.timestamp <= end_date]
        
        return orders
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        if order_id in self.open_orders:
            return self.open_orders[order_id]
        elif order_id in self.executed_orders:
            return self.executed_orders[order_id]
        else:
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if cancelled, False otherwise
        """
        if order_id in self.open_orders:
            order = self.open_orders[order_id]
            order.mark_cancelled()
            
            # Move to executed orders (cancelled)
            self.executed_orders[order_id] = order
            del self.open_orders[order_id]
            
            logger.info(f"Cancelled order {order_id}")
            return True
        
        logger.warning(f"Cannot cancel order {order_id}: not found or not open")
        return False
    
    def get_trading_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get trading performance summary.
        
        Args:
            start_date: Start date filter
            end_date: End date filter
            
        Returns:
            Dictionary with trading summary
        """
        # Filter orders
        orders = self.get_executed_orders(start_date=start_date, end_date=end_date)
        
        if not orders:
            return {"error": "No executed orders in period"}
        
        # Calculate metrics
        total_trades = len(orders)
        winning_trades = 0
        losing_trades = 0
        
        total_pnl = 0.0
        total_fees = 0.0
        total_volume = 0.0
        
        for order in orders:
            if order.status == "EXECUTED" and order.executed_price and order.price:
                # Calculate P&L (simplified)
                price_diff = order.executed_price - order.price
                if order.order_type in ["BUY_YES", "BUY_NO"]:
                    # Buying: profit if price goes up
                    pnl = price_diff * order.quantity
                else:
                    # Selling: profit if price goes down
                    pnl = -price_diff * order.quantity
                
                total_pnl += pnl
                
                if pnl > 0:
                    winning_trades += 1
                elif pnl < 0:
                    losing_trades += 1
                
                total_fees += order.fee_usd
                total_volume += order.total_usd
        
        # Calculate derived metrics
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        # Gross profit/loss
        gross_profit = max(total_pnl, 0)
        gross_loss = abs(min(total_pnl, 0))
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Average trade metrics
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0
        avg_volume = total_volume / total_trades if total_trades > 0 else 0.0
        
        # Create summary
        summary = {
            "period": {
                "start": start_date.isoformat() if start_date else "N/A",
                "end": end_date.isoformat() if end_date else "N/A",
            },
            "trading_stats": {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate": win_rate,
            },
            "financials": {
                "total_pnl": total_pnl,
                "net_pnl": total_pnl - total_fees,
                "total_fees": total_fees,
                "total_volume": total_volume,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "profit_factor": profit_factor,
            },
            "averages": {
                "avg_pnl_per_trade": avg_pnl,
                "avg_volume_per_trade": avg_volume,
                "avg_fee_per_trade": total_fees / total_trades if total_trades > 0 else 0.0,
            }
        }
        
        return summary
    
    def save_orders(self, filepath: str):
        """Save order history to JSON file."""
        orders_data = []
        
        # Include all orders (open and executed)
        all_orders = list(self.open_orders.values()) + list(self.executed_orders.values())
        
        for order in all_orders:
            order_dict = {
                "order_id": order.order_id,
                "market_id": order.market_id,
                "order_type": order.order_type,
                "quantity": order.quantity,
                "price": order.price,
                "timestamp": order.timestamp.isoformat(),
                "paper_trade": order.paper_trade,
                "status": order.status,
                "executed_price": order.executed_price,
                "executed_quantity": order.executed_quantity,
                "executed_timestamp": order.executed_timestamp.isoformat() if order.executed_timestamp else None,
                "fee_usd": order.fee_usd,
                "slippage": order.slippage,
                "metadata": order.metadata,
            }
            orders_data.append(order_dict)
        
        with open(filepath, 'w') as f:
            json.dump(orders_data, f, indent=2)
        
        logger.info(f"Saved {len(orders_data)} orders to {filepath}")
    
    def load_orders(self, filepath: str):
        """Load order history from JSON file."""
        try:
            with open(filepath, 'r') as f:
                orders_data = json.load(f)
            
            for order_dict in orders_data:
                try:
                    order = Order(
                        market_id=order_dict["market_id"],
                        order_type=order_dict["order_type"],
                        quantity=order_dict["quantity"],
                        price=order_dict["price"],
                        timestamp=datetime.fromisoformat(order_dict["timestamp"]),
                        paper_trade=order_dict["paper_trade"],
                        order_id=order_dict["order_id"],
                        metadata=order_dict.get("metadata")
                    )
                    
                    # Set status and execution details
                    order.status = order_dict["status"]
                    
                    if order_dict.get("executed_price"):
                        order.executed_price = order_dict["executed_price"]
                        order.executed_quantity = order_dict["executed_quantity"]
                        if order_dict.get("executed_timestamp"):
                            order.executed_timestamp = datetime.fromisoformat(order_dict["executed_timestamp"])
                        order.fee_usd = order_dict.get("fee_usd", 0.0)
                        order.slippage = order_dict.get("slippage", 0.0)
                    
                    # Store in appropriate dict
                    if order.status == "EXECUTED":
                        self.executed_orders[order.order_id] = order
                    elif order.status == "PENDING":
                        self.open_orders[order.order_id] = order
                    else:
                        self.executed_orders[order.order_id] = order
                    
                except Exception as e:
                    logger.error(f"Error parsing order: {e}")
                    continue
            
            logger.info(f"Loaded {len(orders_data)} orders from {filepath}")
            
        except Exception as e:
            logger.error(f"Error loading orders from {filepath}: {e}")


if __name__ == "__main__":
    # Test trade executor
    import asyncio
    
    async def test():
        # Initialize executor
        executor = TradeExecutor()
        
        # Execute a paper trade
        order = await executor.execute_order(
            market_id="test_market_001",
            order_type="BUY_YES",
            quantity=100.0,
            price=0.55
        )
        
        print(f"Order executed: {order.status}")
        print(f"Order ID: {order.order_id}")
        print(f"Executed price: {order.executed_price}")
        print(f"Slippage: {order.slippage:.2%}")
        print(f"Fee: ${order.fee_usd:.2f}")
        print(f"Total: ${order.total_usd:.2f}")
        
        # Execute a signal
        signal_order = await executor.execute_signal(
            market_id="test_market_002",
            signal_type="STRONG_BUY",
            position_size_pct=0.05,  # 5% of portfolio
            current_price=0.60,
            portfolio_value=10000.0
        )
        
        if signal_order:
            print(f"\nSignal order executed: {signal_order.order_type}")
            print(f"Quantity: {signal_order.quantity:.2f}")
            print(f"Value: ${signal_order.total_usd:.2f}")
        
        # Get trading summary
        summary = executor.get_trading_summary()
        print(f"\nTrading summary: {summary.get('trading_stats', {}).get('total_trades', 0)} trades")
    
    asyncio.run(test())