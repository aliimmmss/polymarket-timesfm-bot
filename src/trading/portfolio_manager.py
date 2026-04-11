"""
Portfolio management module for Polymarket Trading Bot.

This module handles:
- Portfolio tracking and valuation
- Position management
- Cash management and allocation
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass
import json
from pathlib import Path

from ..trading.order_executor import Order

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Container for a market position."""
    market_id: str
    position_type: str  # "YES" or "NO"
    quantity: float
    average_price: float
    current_price: float
    timestamp: datetime
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_invested: float = 0.0
    position_id: Optional[str] = None
    
    def __post_init__(self):
        """Calculate derived values."""
        self.total_invested = self.quantity * self.average_price
        self.update_unrealized_pnl(self.current_price)
        
        # Generate position ID
        if self.position_id is None:
            self.position_id = f"{self.market_id}_{self.position_type}_{int(self.timestamp.timestamp())}"
    
    def update_unrealized_pnl(self, current_price: float):
        """Update unrealized P&L based on current price."""
        self.current_price = current_price
        
        if self.position_type == "YES":
            # YES position: profit if price goes up
            self.unrealized_pnl = self.quantity * (current_price - self.average_price)
        else:
            # NO position: profit if price goes down
            # Note: NO price = 1 - YES price, but we track NO positions separately
            # For simplicity, we'll assume direct NO price tracking
            self.unrealized_pnl = self.quantity * (current_price - self.average_price)
    
    def add_to_position(self, quantity: float, price: float):
        """Add to existing position."""
        # Update average price
        total_cost = self.total_invested + (quantity * price)
        total_quantity = self.quantity + quantity
        
        if total_quantity > 0:
            self.average_price = total_cost / total_quantity
        
        # Update quantities
        self.quantity = total_quantity
        self.total_invested = total_cost
    
    def reduce_position(self, quantity: float, price: float) -> float:
        """
        Reduce position by quantity.
        
        Args:
            quantity: Quantity to reduce
            price: Price at reduction
            
        Returns:
            Realized P&L from reduction
        """
        if quantity > self.quantity:
            raise ValueError(f"Cannot reduce {quantity} from position with {self.quantity}")
        
        # Calculate P&L for reduced portion
        if self.position_type == "YES":
            pnl = quantity * (price - self.average_price)
        else:
            pnl = quantity * (price - self.average_price)
        
        # Update position
        self.quantity -= quantity
        self.total_invested = self.quantity * self.average_price
        self.realized_pnl += pnl
        
        return pnl
    
    def close_position(self, price: float) -> float:
        """
        Close entire position.
        
        Args:
            price: Closing price
            
        Returns:
            Total realized P&L
        """
        pnl = self.reduce_position(self.quantity, price)
        return pnl


@dataclass
class PortfolioSnapshot:
    """Container for portfolio snapshot."""
    timestamp: datetime
    total_value: float
    cash_balance: float
    invested_amount: float
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: float
    daily_return: float
    drawdown: float
    sharpe_ratio_30d: Optional[float] = None
    max_position_size: float = 0.0
    active_positions: int = 0
    risk_score: float = 0.0
    metadata: Optional[Dict[str, Any]] = None


class PortfolioManager:
    """Manage trading portfolio."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize portfolio manager.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Default configuration
        self.portfolio_config = {
            "initial_capital": 10000.0,
            "max_position_size_pct": 0.10,  # 10% max per position
            "max_portfolio_risk": 0.20,  # 20% max portfolio risk
            "target_daily_return": 0.01,  # 1% target daily return
            "stop_loss_pct": 0.05,  # 5% stop loss
            "take_profit_pct": 0.10,  # 10% take profit
            "rebalance_threshold": 0.02,  # 2% rebalancing threshold
            "snapshot_interval_minutes": 60,
            "performance_window_days": 30,
        }
        
        # Update with config if provided
        if "portfolio" in self.config:
            self.portfolio_config.update(self.config["portfolio"])
        
        # Portfolio state
        self.cash_balance = self.portfolio_config["initial_capital"]
        self.positions: Dict[str, Position] = {}  # key: position_id
        self.snapshots: List[PortfolioSnapshot] = []
        self.trade_history: List[Order] = []
        
        # Performance tracking
        self.daily_pnl_history: List[Dict[str, float]] = []
        self.returns_history: List[float] = []
        
        logger.info(f"Initialized PortfolioManager with ${self.cash_balance:.2f} initial capital")
    
    def update_position_from_order(self, order: Order):
        """
        Update portfolio positions based on executed order.
        
        Args:
            order: Executed order
        """
        if order.status != "EXECUTED" or not order.executed_price or not order.executed_quantity:
            logger.warning(f"Cannot update position from non-executed order: {order.order_id}")
            return
        
        # Determine position type from order type
        if order.order_type in ["BUY_YES", "SELL_YES"]:
            position_type = "YES"
        elif order.order_type in ["BUY_NO", "SELL_NO"]:
            position_type = "NO"
        else:
            logger.error(f"Unknown order type: {order.order_type}")
            return
        
        position_key = f"{order.market_id}_{position_type}"
        
        # Update cash balance
        trade_value = order.executed_price * order.executed_quantity
        
        if order.order_type in ["BUY_YES", "BUY_NO"]:
            # Buying: reduce cash
            self.cash_balance -= trade_value + order.fee_usd
        else:
            # Selling: increase cash
            self.cash_balance += trade_value - order.fee_usd
        
        # Update or create position
        if order.order_type in ["BUY_YES", "BUY_NO"]:
            # Opening or adding to long position
            if position_key in self.positions:
                # Add to existing position
                self.positions[position_key].add_to_position(
                    quantity=order.executed_quantity,
                    price=order.executed_price
                )
            else:
                # Create new position
                position = Position(
                    market_id=order.market_id,
                    position_type=position_type,
                    quantity=order.executed_quantity,
                    average_price=order.executed_price,
                    current_price=order.executed_price,
                    timestamp=datetime.utcnow()
                )
                self.positions[position_key] = position
                
        else:  # SELL_YES or SELL_NO
            # Closing or reducing position
            if position_key in self.positions:
                position = self.positions[position_key]
                
                if order.executed_quantity <= position.quantity:
                    # Reduce position
                    realized_pnl = position.reduce_position(
                        quantity=order.executed_quantity,
                        price=order.executed_price
                    )
                    
                    # Remove position if quantity is zero
                    if position.quantity <= 0.001:  # Small epsilon
                        del self.positions[position_key]
                        logger.info(f"Closed position {position_key}")
                    
                else:
                    logger.warning(f"Trying to sell {order.executed_quantity} but only have "
                                 f"{position.quantity} in position {position_key}")
            else:
                logger.warning(f"Trying to sell {order.executed_quantity} shares of "
                             f"{position_key} but no position found")
        
        # Add to trade history
        self.trade_history.append(order)
        
        logger.debug(f"Updated portfolio from order {order.order_id}. "
                    f"Cash: ${self.cash_balance:.2f}, Positions: {len(self.positions)}")
    
    def update_position_prices(self, market_prices: Dict[str, Dict[str, float]]):
        """
        Update position prices from market data.
        
        Args:
            market_prices: Dict mapping market_id to {"YES": price, "NO": price}
        """
        for position_key, position in self.positions.items():
            market_id = position.market_id
            position_type = position.position_type
            
            if market_id in market_prices:
                price_data = market_prices[market_id]
                
                if position_type in price_data:
                    current_price = price_data[position_type]
                    position.update_unrealized_pnl(current_price)
                else:
                    logger.warning(f"No price data for {position_type} in market {market_id}")
            else:
                logger.warning(f"No price data for market {market_id}")
    
    def get_portfolio_value(self, market_prices: Optional[Dict[str, Dict[str, float]]] = None) -> float:
        """
        Calculate total portfolio value.
        
        Args:
            market_prices: Optional current market prices
            
        Returns:
            Total portfolio value in USD
        """
        # Update position prices if provided
        if market_prices:
            self.update_position_prices(market_prices)
        
        # Calculate position values
        position_value = 0.0
        for position in self.positions.values():
            position_value += position.quantity * position.current_price
        
        # Total portfolio value = cash + position value
        total_value = self.cash_balance + position_value
        
        return total_value
    
    def create_snapshot(self, market_prices: Optional[Dict[str, Dict[str, float]]] = None):
        """
        Create a portfolio snapshot.
        
        Args:
            market_prices: Optional current market prices
        """
        # Calculate portfolio metrics
        total_value = self.get_portfolio_value(market_prices)
        
        # Calculate position values
        position_value = total_value - self.cash_balance
        
        # Calculate unrealized P&L
        unrealized_pnl = sum(p.unrealized_pnl for p in self.positions.values())
        
        # Calculate realized P&L from trade history
        realized_pnl = sum(p.realized_pnl for p in self.positions.values())
        
        # Calculate daily P&L
        daily_pnl = 0.0
        if self.snapshots:
            last_snapshot = self.snapshots[-1]
            time_diff = datetime.utcnow() - last_snapshot.timestamp
            
            if time_diff.total_seconds() >= 23 * 3600:  # Approximately daily
                daily_pnl = total_value - last_snapshot.total_value
                self.daily_pnl_history.append({
                    "timestamp": datetime.utcnow(),
                    "pnl": daily_pnl,
                    "return": daily_pnl / last_snapshot.total_value if last_snapshot.total_value > 0 else 0.0
                })
        
        # Calculate daily return
        daily_return = daily_pnl / total_value if total_value > 0 else 0.0
        
        # Calculate drawdown
        drawdown = self._calculate_drawdown(total_value)
        
        # Calculate Sharpe ratio (30-day)
        sharpe_ratio = self._calculate_sharpe_ratio()
        
        # Calculate max position size
        max_position_size = 0.0
        if self.positions:
            position_values = [p.quantity * p.current_price for p in self.positions.values()]
            max_position_size = max(position_values) if position_values else 0.0
        
        # Calculate risk score
        risk_score = self._calculate_risk_score()
        
        # Create snapshot
        snapshot = PortfolioSnapshot(
            timestamp=datetime.utcnow(),
            total_value=total_value,
            cash_balance=self.cash_balance,
            invested_amount=position_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            daily_pnl=daily_pnl,
            daily_return=daily_return,
            drawdown=drawdown,
            sharpe_ratio_30d=sharpe_ratio,
            max_position_size=max_position_size,
            active_positions=len(self.positions),
            risk_score=risk_score,
            metadata={
                "position_details": {
                    position_key: {
                        "quantity": p.quantity,
                        "avg_price": p.average_price,
                        "current_price": p.current_price,
                        "unrealized_pnl": p.unrealized_pnl
                    }
                    for position_key, p in self.positions.items()
                }
            }
        )
        
        self.snapshots.append(snapshot)
        
        logger.debug(f"Created portfolio snapshot: ${total_value:.2f}, "
                    f"Cash: ${self.cash_balance:.2f}, Positions: {len(self.positions)}")
    
    def _calculate_drawdown(self, current_value: float) -> float:
        """
        Calculate current drawdown from peak.
        
        Args:
            current_value: Current portfolio value
            
        Returns:
            Drawdown as percentage (0-1)
        """
        if not self.snapshots:
            return 0.0
        
        # Find peak value
        peak_value = max(snapshot.total_value for snapshot in self.snapshots)
        
        if peak_value > 0:
            drawdown = (peak_value - current_value) / peak_value
            return max(0.0, drawdown)
        
        return 0.0
    
    def _calculate_sharpe_ratio(self, days: int = 30) -> Optional[float]:
        """
        Calculate Sharpe ratio over specified period.
        
        Args:
            days: Number of days to calculate over
            
        Returns:
            Sharpe ratio or None if insufficient data
        """
        if len(self.daily_pnl_history) < days:
            return None
        
        # Get recent daily returns
        recent_returns = [
            entry["return"] for entry in self.daily_pnl_history[-days:]
        ]
        
        if len(recent_returns) < 2:
            return None
        
        # Calculate annualized Sharpe ratio
        mean_return = np.mean(recent_returns)
        std_return = np.std(recent_returns)
        
        if std_return > 0:
            # Annualize: multiply by sqrt(365) for daily returns
            sharpe_ratio = mean_return / std_return * np.sqrt(365)
            return sharpe_ratio
        
        return None
    
    def _calculate_risk_score(self) -> float:
        """
        Calculate portfolio risk score (0-1).
        
        Returns:
            Risk score (higher = riskier)
        """
        score = 0.0
        
        # Component 1: Concentration risk
        if self.positions:
            total_value = self.get_portfolio_value()
            position_values = [p.quantity * p.current_price for p in self.positions.values()]
            
            if total_value > 0:
                concentration = sum(position_values) / total_value
                score += concentration * 0.4  # Weight: 40%
        
        # Component 2: Drawdown risk
        score += min(1.0, self._calculate_drawdown(self.get_portfolio_value()) * 10) * 0.3  # Weight: 30%
        
        # Component 3: Volatility risk
        if len(self.returns_history) >= 5:
            volatility = np.std(self.returns_history[-20:]) if len(self.returns_history) >= 20 else np.std(self.returns_history)
            score += min(1.0, volatility * 20) * 0.3  # Weight: 30%
        
        return min(1.0, score)
    
    def get_position_limits(
        self,
        market_id: str,
        position_type: str,
        current_price: float
    ) -> Dict[str, float]:
        """
        Get position limits for a market.
        
        Args:
            market_id: Market ID
            position_type: "YES" or "NO"
            current_price: Current market price
            
        Returns:
            Dictionary with position limits
        """
        total_value = self.get_portfolio_value()
        
        # Maximum position size by percentage
        max_position_pct = self.portfolio_config["max_position_size_pct"]
        max_position_value = total_value * max_position_pct
        
        # Convert to quantity
        max_position_quantity = max_position_value / current_price if current_price > 0 else 0
        
        # Existing position
        position_key = f"{market_id}_{position_type}"
        existing_position = self.positions.get(position_key)
        
        if existing_position:
            existing_quantity = existing_position.quantity
            existing_value = existing_position.quantity * existing_position.current_price
        else:
            existing_quantity = 0
            existing_value = 0
        
        # Available to add
        available_value = max(0, max_position_value - existing_value)
        available_quantity = available_value / current_price if current_price > 0 else 0
        
        return {
            "max_position_value": max_position_value,
            "max_position_quantity": max_position_quantity,
            "existing_quantity": existing_quantity,
            "existing_value": existing_value,
            "available_value": available_value,
            "available_quantity": available_quantity,
        }
    
    def check_trade_allowed(
        self,
        market_id: str,
        position_type: str,
        quantity: float,
        price: float,
        trade_value: float
    ) -> Tuple[bool, str]:
        """
        Check if a trade is allowed based on portfolio constraints.
        
        Args:
            market_id: Market ID
            position_type: "YES" or "NO"
            quantity: Trade quantity
            price: Trade price
            trade_value: Trade value in USD
            
        Returns:
            Tuple of (allowed, reason)
        """
        # Check cash availability for buys
        if position_type in ["YES", "NO"] and quantity > 0:  # Buying
            if trade_value > self.cash_balance:
                return False, f"Insufficient cash: ${trade_value:.2f} > ${self.cash_balance:.2f}"
        
        # Check position limits
        position_key = f"{market_id}_{position_type}"
        existing_position = self.positions.get(position_key)
        
        if existing_position and quantity > 0:  # Adding to position
            position_limits = self.get_position_limits(market_id, position_type, price)
            
            new_position_value = (existing_position.quantity + quantity) * price
            max_allowed_value = position_limits["max_position_value"]
            
            if new_position_value > max_allowed_value * 1.01:  # 1% buffer
                return False, f"Position limit exceeded: ${new_position_value:.2f} > ${max_allowed_value:.2f}"
        
        # Check portfolio risk
        risk_score = self._calculate_risk_score()
        max_risk = self.portfolio_config["max_portfolio_risk"]
        
        if risk_score > max_risk:
            return False, f"Portfolio risk too high: {risk_score:.2f} > {max_risk:.2f}"
        
        # Check minimum trade size
        min_trade_usd = 10.0
        if trade_value < min_trade_usd:
            return False, f"Trade too small: ${trade_value:.2f} < ${min_trade_usd}"
        
        return True, "Trade allowed"
    
    def get_performance_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Generate portfolio performance report.
        
        Args:
            start_date: Start date filter
            end_date: End date filter
            
        Returns:
            Dictionary with performance metrics
        """
        # Filter snapshots
        if start_date:
            snapshots = [s for s in self.snapshots if s.timestamp >= start_date]
        else:
            snapshots = self.snapshots
        
        if end_date:
            snapshots = [s for s in snapshots if s.timestamp <= end_date]
        
        if not snapshots:
            return {"error": "No snapshots in period"}
        
        # Calculate metrics
        initial_value = snapshots[0].total_value
        final_value = snapshots[-1].total_value
        total_return = final_value - initial_value
        total_return_pct = total_return / initial_value * 100 if initial_value > 0 else 0.0
        
        # Calculate daily metrics
        daily_returns = []
        for i in range(1, len(snapshots)):
            daily_return = (snapshots[i].total_value - snapshots[i-1].total_value) / snapshots[i-1].total_value
            daily_returns.append(daily_return)
        
        # Calculate risk metrics
        volatility = np.std(daily_returns) * np.sqrt(365) if daily_returns else 0.0
        sharpe_ratio = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(365) if daily_returns and np.std(daily_returns) > 0 else 0.0
        
        # Calculate max drawdown
        peak = initial_value
        max_drawdown = 0.0
        for snapshot in snapshots:
            if snapshot.total_value > peak:
                peak = snapshot.total_value
            else:
                drawdown = (peak - snapshot.total_value) / peak
                max_drawdown = max(max_drawdown, drawdown)
        
        # Create report
        report = {
            "period": {
                "start": snapshots[0].timestamp.isoformat(),
                "end": snapshots[-1].timestamp.isoformat(),
                "days": (snapshots[-1].timestamp - snapshots[0].timestamp).days
            },
            "performance": {
                "initial_value": initial_value,
                "final_value": final_value,
                "total_return": total_return,
                "total_return_pct": total_return_pct,
                "annualized_return": total_return_pct * 365 / max(1, (snapshots[-1].timestamp - snapshots[0].timestamp).days),
            },
            "risk_metrics": {
                "volatility": volatility,
                "sharpe_ratio": sharpe_ratio,
                "max_drawdown": max_drawdown,
                "avg_drawdown": np.mean([s.drawdown for s in snapshots]),
            },
            "trading_stats": {
                "total_trades": len(self.trade_history),
                "active_positions": len(self.positions),
                "win_rate": self._calculate_win_rate(),
                "profit_factor": self._calculate_profit_factor(),
            }
        }
        
        return report
    
    def _calculate_win_rate(self) -> float:
        """Calculate win rate from trade history."""
        if not self.trade_history:
            return 0.0
        
        winning_trades = 0
        for order in self.trade_history:
            if order.status == "EXECUTED" and order.executed_price and order.price:
                # Simplified win/loss calculation
                if order.order_type in ["BUY_YES", "BUY_NO"]:
                    # Buying: win if executed price <= order price (got better price)
                    if order.executed_price <= order.price:
                        winning_trades += 1
                else:
                    # Selling: win if executed price >= order price
                    if order.executed_price >= order.price:
                        winning_trades += 1
        
        return winning_trades / len(self.trade_history)
    
    def _calculate_profit_factor(self) -> float:
        """Calculate profit factor from trade history."""
        if not self.trade_history:
            return 0.0
        
        gross_profit = 0.0
        gross_loss = 0.0
        
        for order in self.trade_history:
            if order.status == "EXECUTED" and order.executed_price and order.price:
                # Calculate P&L for this trade
                if order.order_type in ["BUY_YES", "BUY_NO"]:
                    pnl = (order.executed_price - order.price) * order.quantity
                else:
                    pnl = (order.price - order.executed_price) * order.quantity
                
                if pnl > 0:
                    gross_profit += pnl
                else:
                    gross_loss += abs(pnl)
        
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        
        return gross_profit / gross_loss
    
    def save_portfolio(self, filepath: str):
        """Save portfolio state to JSON file."""
        portfolio_data = {
            "cash_balance": self.cash_balance,
            "positions": [],
            "snapshots": [],
            "trade_history": []
        }
        
        # Save positions
        for position in self.positions.values():
            position_data = {
                "market_id": position.market_id,
                "position_type": position.position_type,
                "quantity": position.quantity,
                "average_price": position.average_price,
                "current_price": position.current_price,
                "timestamp": position.timestamp.isoformat(),
                "unrealized_pnl": position.unrealized_pnl,
                "realized_pnl": position.realized_pnl,
                "total_invested": position.total_invested,
                "position_id": position.position_id
            }
            portfolio_data["positions"].append(position_data)
        
        # Save snapshots
        for snapshot in self.snapshots:
            snapshot_data = {
                "timestamp": snapshot.timestamp.isoformat(),
                "total_value": snapshot.total_value,
                "cash_balance": snapshot.cash_balance,
                "invested_amount": snapshot.invested_amount,
                "unrealized_pnl": snapshot.unrealized_pnl,
                "realized_pnl": snapshot.realized_pnl,
                "daily_pnl": snapshot.daily_pnl,
                "daily_return": snapshot.daily_return,
                "drawdown": snapshot.drawdown,
                "sharpe_ratio_30d": snapshot.sharpe_ratio_30d,
                "max_position_size": snapshot.max_position_size,
                "active_positions": snapshot.active_positions,
                "risk_score": snapshot.risk_score,
                "metadata": snapshot.metadata
            }
            portfolio_data["snapshots"].append(snapshot_data)
        
        # Save trade history
        for order in self.trade_history:
            order_data = {
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
            portfolio_data["trade_history"].append(order_data)
        
        # Save to file
        with open(filepath, 'w') as f:
            json.dump(portfolio_data, f, indent=2)
        
        logger.info(f"Saved portfolio to {filepath}")
    
    def load_portfolio(self, filepath: str):
        """Load portfolio state from JSON file."""
        try:
            with open(filepath, 'r') as f:
                portfolio_data = json.load(f)
            
            # Load cash balance
            self.cash_balance = portfolio_data.get("cash_balance", self.portfolio_config["initial_capital"])
            
            # Load positions
            self.positions.clear()
            for position_data in portfolio_data.get("positions", []):
                try:
                    position = Position(
                        market_id=position_data["market_id"],
                        position_type=position_data["position_type"],
                        quantity=position_data["quantity"],
                        average_price=position_data["average_price"],
                        current_price=position_data["current_price"],
                        timestamp=datetime.fromisoformat(position_data["timestamp"]),
                        position_id=position_data.get("position_id")
                    )
                    position.unrealized_pnl = position_data.get("unrealized_pnl", 0.0)
                    position.realized_pnl = position_data.get("realized_pnl", 0.0)
                    position.total_invested = position_data.get("total_invested", 0.0)
                    
                    self.positions[position.position_id] = position
                except Exception as e:
                    logger.error(f"Error loading position: {e}")
                    continue
            
            # Load snapshots
            self.snapshots.clear()
            for snapshot_data in portfolio_data.get("snapshots", []):
                try:
                    snapshot = PortfolioSnapshot(
                        timestamp=datetime.fromisoformat(snapshot_data["timestamp"]),
                        total_value=snapshot_data["total_value"],
                        cash_balance=snapshot_data["cash_balance"],
                        invested_amount=snapshot_data["invested_amount"],
                        unrealized_pnl=snapshot_data["unrealized_pnl"],
                        realized_pnl=snapshot_data["realized_pnl"],
                        daily_pnl=snapshot_data["daily_pnl"],
                        daily_return=snapshot_data["daily_return"],
                        drawdown=snapshot_data["drawdown"],
                        sharpe_ratio_30d=snapshot_data.get("sharpe_ratio_30d"),
                        max_position_size=snapshot_data.get("max_position_size", 0.0),
                        active_positions=snapshot_data.get("active_positions", 0),
                        risk_score=snapshot_data.get("risk_score", 0.0),
                        metadata=snapshot_data.get("metadata")
                    )
                    self.snapshots.append(snapshot)
                except Exception as e:
                    logger.error(f"Error loading snapshot: {e}")
                    continue
            
            # Load trade history
            self.trade_history.clear()
            for order_data in portfolio_data.get("trade_history", []):
                try:
                    order = Order(
                        market_id=order_data["market_id"],
                        order_type=order_data["order_type"],
                        quantity=order_data["quantity"],
                        price=order_data["price"],
                        timestamp=datetime.fromisoformat(order_data["timestamp"]),
                        paper_trade=order_data["paper_trade"],
                        order_id=order_data["order_id"],
                        metadata=order_data.get("metadata")
                    )
                    
                    order.status = order_data["status"]
                    
                    if order_data.get("executed_price"):
                        order.executed_price = order_data["executed_price"]
                        order.executed_quantity = order_data["executed_quantity"]
                        if order_data.get("executed_timestamp"):
                            order.executed_timestamp = datetime.fromisoformat(order_data["executed_timestamp"])
                        order.fee_usd = order_data.get("fee_usd", 0.0)
                        order.slippage = order_data.get("slippage", 0.0)
                    
                    self.trade_history.append(order)
                except Exception as e:
                    logger.error(f"Error loading trade: {e}")
                    continue
            
            logger.info(f"Loaded portfolio from {filepath}")
            
        except Exception as e:
            logger.error(f"Error loading portfolio from {filepath}: {e}")


if __name__ == "__main__":
    # Test portfolio manager
    from ..trading.trade_executor import Order
    
    # Initialize portfolio manager
    manager = PortfolioManager()
    
    # Create mock orders
    order1 = Order(
        market_id="market_001",
        order_type="BUY_YES",
        quantity=100.0,
        price=0.55,
        timestamp=datetime.utcnow(),
        paper_trade=True
    )
    order1.mark_executed(executed_price=0.56, executed_quantity=100.0, fee_usd=0.56, slippage=0.001)
    
    order2 = Order(
        market_id="market_002",
        order_type="BUY_NO",
        quantity=50.0,
        price=0.45,
        timestamp=datetime.utcnow(),
        paper_trade=True
    )
    order2.mark_executed(executed_price=0.46, executed_quantity=50.0, fee_usd=0.23, slippage=0.001)
    
    # Update portfolio
    manager.update_position_from_order(order1)
    manager.update_position_from_order(order2)
    
    # Update market prices
    market_prices = {
        "market_001": {"YES": 0.58, "NO": 0.42},
        "market_002": {"YES": 0.60, "NO": 0.40},
    }
    
    manager.update_position_prices(market_prices)
    
    # Create snapshot
    manager.create_snapshot(market_prices)
    
    # Get portfolio value
    total_value = manager.get_portfolio_value()
    print(f"Portfolio value: ${total_value:.2f}")
    print(f"Cash balance: ${manager.cash_balance:.2f}")
    print(f"Active positions: {len(manager.positions)}")
    
    # Get position limits
    limits = manager.get_position_limits("market_001", "YES", 0.58)
    print(f"\nPosition limits for market_001 YES:")
    for key, value in limits.items():
        print(f"  {key}: {value:.2f}")
    
    # Get performance report
    report = manager.get_performance_report()
    print(f"\nPerformance report:")
    print(f"  Total return: ${report['performance']['total_return']:.2f}")
    print(f"  Total return %: {report['performance']['total_return_pct']:.2f}%")
    print(f"  Sharpe ratio: {report['risk_metrics']['sharpe_ratio']:.2f}")
    
    # Save portfolio
    manager.save_portfolio("test_portfolio.json")