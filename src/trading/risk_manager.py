"""
Risk management module for Polymarket Trading Bot.

This module handles:
- Position sizing and risk allocation
- Stop loss and take profit calculation
- Portfolio risk monitoring
- Risk-adjusted performance metrics
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass
import math

from ..forecasting.signal_generator import TradingSignal
from .portfolio_manager import Position, PortfolioManager

logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    """Container for risk metrics."""
    timestamp: datetime
    portfolio_value: float
    var_95_1d: float  # Value at Risk (95% confidence, 1-day)
    cvar_95_1d: float  # Conditional VaR (95% confidence, 1-day)
    max_drawdown: float
    current_drawdown: float
    volatility_30d: float
    sharpe_ratio_30d: float
    sortino_ratio_30d: float
    beta_market: float  # Beta relative to market
    concentration_risk: float  # 0-1, higher = more concentrated
    liquidity_risk: float  # 0-1, higher = less liquid
    overall_risk_score: float  # 0-1 composite score
    risk_limit_breaches: List[str]
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class PositionRisk:
    """Container for position-level risk."""
    position_id: str
    market_id: str
    position_type: str
    quantity: float
    current_price: float
    position_value: float
    volatility: float
    beta: float
    var_contribution: float  # Contribution to portfolio VaR
    stop_loss_price: float
    take_profit_price: float
    risk_adjusted_return: float
    risk_score: float  # 0-1, higher = riskier
    metadata: Optional[Dict[str, Any]] = None


class RiskManager:
    """Manage trading risks."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize risk manager.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Default risk configuration
        self.risk_config = {
            # Portfolio risk limits
            "max_portfolio_var_95_1d": 0.05,  # 5% maximum 1-day VaR
            "max_drawdown_limit": 0.20,  # 20% maximum drawdown
            "max_concentration": 0.15,  # 15% max in single position
            "min_liquidity_score": 0.5,  # Minimum liquidity score
            
            # Position risk parameters
            "position_risk_multiplier": 1.0,
            "stop_loss_pct": 0.05,  # 5% stop loss
            "take_profit_pct": 0.10,  # 10% take profit
            "trailing_stop_pct": 0.03,  # 3% trailing stop
            
            # Risk calculation parameters
            "var_confidence_level": 0.95,
            "var_time_horizon_days": 1,
            "volatility_lookback_days": 30,
            "beta_calculation_days": 90,
            
            # Risk score weights
            "risk_score_weights": {
                "volatility": 0.25,
                "concentration": 0.20,
                "liquidity": 0.15,
                "drawdown": 0.20,
                "var": 0.20,
            },
        }
        
        # Update with config if provided
        if "risk" in self.config:
            self.risk_config.update(self.config["risk"])
        
        # Risk history
        self.risk_metrics_history: List[RiskMetrics] = []
        self.position_risk_history: Dict[str, List[PositionRisk]] = {}
        
        # Risk limit breaches
        self.risk_limit_breaches: List[Dict[str, Any]] = []
        
        logger.info(f"Initialized RiskManager with config: {self.risk_config}")
    
    def calculate_portfolio_risk(
        self,
        portfolio_manager: PortfolioManager,
        market_prices: Dict[str, Dict[str, float]],
        market_returns: Optional[pd.DataFrame] = None
    ) -> RiskMetrics:
        """
        Calculate comprehensive portfolio risk metrics.
        
        Args:
            portfolio_manager: PortfolioManager instance
            market_prices: Current market prices
            market_returns: Optional DataFrame of historical market returns
            
        Returns:
            RiskMetrics object
        """
        timestamp = datetime.utcnow()
        portfolio_value = portfolio_manager.get_portfolio_value(market_prices)
        
        # Calculate Value at Risk (VaR)
        var_95_1d, cvar_95_1d = self._calculate_var(
            portfolio_manager=portfolio_manager,
            market_prices=market_prices,
            market_returns=market_returns
        )
        
        # Calculate drawdown
        max_drawdown = self._calculate_max_drawdown(portfolio_manager)
        current_drawdown = portfolio_manager.snapshots[-1].drawdown if portfolio_manager.snapshots else 0.0
        
        # Calculate volatility
        volatility_30d = self._calculate_portfolio_volatility(portfolio_manager)
        
        # Calculate risk-adjusted returns
        sharpe_ratio_30d = portfolio_manager.snapshots[-1].sharpe_ratio_30d if portfolio_manager.snapshots else None
        sortino_ratio_30d = self._calculate_sortino_ratio(portfolio_manager)
        
        # Calculate beta (market correlation)
        beta_market = self._calculate_portfolio_beta(portfolio_manager, market_returns)
        
        # Calculate concentration risk
        concentration_risk = self._calculate_concentration_risk(portfolio_manager)
        
        # Calculate liquidity risk
        liquidity_risk = self._calculate_liquidity_risk(portfolio_manager, market_prices)
        
        # Calculate overall risk score
        overall_risk_score = self._calculate_overall_risk_score(
            var_95_1d=var_95_1d,
            max_drawdown=max_drawdown,
            volatility=volatility_30d,
            concentration=concentration_risk,
            liquidity=liquidity_risk
        )
        
        # Check for risk limit breaches
        risk_limit_breaches = self._check_risk_limits(
            var_95_1d=var_95_1d,
            max_drawdown=max_drawdown,
            concentration_risk=concentration_risk,
            liquidity_risk=liquidity_risk
        )
        
        # Create risk metrics
        risk_metrics = RiskMetrics(
            timestamp=timestamp,
            portfolio_value=portfolio_value,
            var_95_1d=var_95_1d,
            cvar_95_1d=cvar_95_1d,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            volatility_30d=volatility_30d,
            sharpe_ratio_30d=sharpe_ratio_30d or 0.0,
            sortino_ratio_30d=sortino_ratio_30d,
            beta_market=beta_market,
            concentration_risk=concentration_risk,
            liquidity_risk=liquidity_risk,
            overall_risk_score=overall_risk_score,
            risk_limit_breaches=risk_limit_breaches,
            metadata={
                "num_positions": len(portfolio_manager.positions),
                "portfolio_leverage": self._calculate_leverage(portfolio_manager),
                "risk_free_rate": 0.02,  # Assume 2% risk-free rate
            }
        )
        
        # Store in history
        self.risk_metrics_history.append(risk_metrics)
        
        # Limit history size
        if len(self.risk_metrics_history) > 1000:
            self.risk_metrics_history = self.risk_metrics_history[-1000:]
        
        logger.debug(f"Calculated portfolio risk: VaR={var_95_1d:.2%}, "
                    f"Score={overall_risk_score:.2f}, Breaches={len(risk_limit_breaches)}")
        
        return risk_metrics
    
    def calculate_position_risk(
        self,
        position: Position,
        market_data: Dict[str, Any],
        portfolio_value: float
    ) -> PositionRisk:
        """
        Calculate risk metrics for a single position.
        
        Args:
            position: Position object
            market_data: Dictionary with market data including volatility, beta, etc.
            portfolio_value: Total portfolio value
            
        Returns:
            PositionRisk object
        """
        position_value = position.quantity * position.current_price
        
        # Get market volatility
        volatility = market_data.get("volatility_30d", 0.1)  # Default 10%
        
        # Get market beta
        beta = market_data.get("beta", 1.0)  # Default beta = 1.0
        
        # Calculate VaR contribution (simplified)
        var_contribution = position_value * volatility * 2.33  # 99% confidence (2.33 std devs)
        
        # Calculate stop loss and take profit prices
        stop_loss_price, take_profit_price = self._calculate_stop_take_prices(
            position_type=position.position_type,
            average_price=position.average_price,
            current_price=position.current_price
        )
        
        # Calculate risk-adjusted return
        risk_adjusted_return = self._calculate_position_risk_adjusted_return(
            position=position,
            volatility=volatility,
            beta=beta
        )
        
        # Calculate position risk score
        risk_score = self._calculate_position_risk_score(
            position_value=position_value,
            portfolio_value=portfolio_value,
            volatility=volatility,
            beta=beta,
            concentration=position_value / portfolio_value if portfolio_value > 0 else 0.0
        )
        
        # Create position risk
        position_risk = PositionRisk(
            position_id=position.position_id,
            market_id=position.market_id,
            position_type=position.position_type,
            quantity=position.quantity,
            current_price=position.current_price,
            position_value=position_value,
            volatility=volatility,
            beta=beta,
            var_contribution=var_contribution,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            risk_adjusted_return=risk_adjusted_return,
            risk_score=risk_score,
            metadata={
                "average_price": position.average_price,
                "unrealized_pnl": position.unrealized_pnl,
                "realized_pnl": position.realized_pnl,
            }
        )
        
        # Store in history
        if position.position_id not in self.position_risk_history:
            self.position_risk_history[position.position_id] = []
        
        self.position_risk_history[position.position_id].append(position_risk)
        
        # Limit history size
        if len(self.position_risk_history[position.position_id]) > 100:
            self.position_risk_history[position.position_id] = \
                self.position_risk_history[position.position_id][-100:]
        
        return position_risk
    
    def _calculate_var(
        self,
        portfolio_manager: PortfolioManager,
        market_prices: Dict[str, Dict[str, float]],
        market_returns: Optional[pd.DataFrame] = None
    ) -> Tuple[float, float]:
        """
        Calculate Value at Risk (VaR) and Conditional VaR (CVaR).
        
        Args:
            portfolio_manager: PortfolioManager instance
            market_prices: Current market prices
            market_returns: Optional historical returns
            
        Returns:
            Tuple of (VaR, CVaR) as percentages of portfolio value
        """
        # Simplified VaR calculation using variance-covariance method
        
        # Get portfolio positions
        positions = portfolio_manager.positions.values()
        if not positions:
            return 0.0, 0.0
        
        # Calculate portfolio volatility
        portfolio_volatility = self._calculate_portfolio_volatility(portfolio_manager)
        
        # Get confidence level z-score
        confidence_level = self.risk_config["var_confidence_level"]
        
        if confidence_level == 0.95:
            z_score = 1.645  # 95% confidence
        elif confidence_level == 0.99:
            z_score = 2.326  # 99% confidence
        else:
            # Approximate using normal distribution
            z_score = abs(np.percentile(np.random.randn(10000), confidence_level * 100))
        
        # Calculate VaR
        portfolio_value = portfolio_manager.get_portfolio_value(market_prices)
        var_absolute = portfolio_value * portfolio_volatility * z_score
        
        # Calculate CVaR (expected loss given VaR breach)
        cvar_absolute = portfolio_value * portfolio_volatility * z_score * 1.5  # Approximation
        
        # Convert to percentages
        var_pct = var_absolute / portfolio_value if portfolio_value > 0 else 0.0
        cvar_pct = cvar_absolute / portfolio_value if portfolio_value > 0 else 0.0
        
        return var_pct, cvar_pct
    
    def _calculate_portfolio_volatility(self, portfolio_manager: PortfolioManager) -> float:
        """Calculate portfolio volatility."""
        if not portfolio_manager.snapshots or len(portfolio_manager.snapshots) < 2:
            return 0.1  # Default 10% volatility
        
        # Calculate daily returns from snapshots
        returns = []
        for i in range(1, len(portfolio_manager.snapshots)):
            prev_value = portfolio_manager.snapshots[i-1].total_value
            curr_value = portfolio_manager.snapshots[i].total_value
            
            if prev_value > 0:
                daily_return = (curr_value - prev_value) / prev_value
                returns.append(daily_return)
        
        if len(returns) < 5:
            return 0.1  # Default 10% volatility
        
        # Calculate annualized volatility
        daily_volatility = np.std(returns)
        annualized_volatility = daily_volatility * np.sqrt(365)
        
        return annualized_volatility
    
    def _calculate_max_drawdown(self, portfolio_manager: PortfolioManager) -> float:
        """Calculate maximum drawdown from portfolio history."""
        if not portfolio_manager.snapshots:
            return 0.0
        
        # Extract portfolio values
        values = [snapshot.total_value for snapshot in portfolio_manager.snapshots]
        
        # Calculate max drawdown
        peak = values[0]
        max_drawdown = 0.0
        
        for value in values:
            if value > peak:
                peak = value
            
            drawdown = (peak - value) / peak
            max_drawdown = max(max_drawdown, drawdown)
        
        return max_drawdown
    
    def _calculate_sortino_ratio(self, portfolio_manager: PortfolioManager) -> float:
        """Calculate Sortino ratio (risk-adjusted return using downside deviation)."""
        if not portfolio_manager.snapshots or len(portfolio_manager.snapshots) < 10:
            return 0.0
        
        # Calculate daily returns
        returns = []
        for i in range(1, len(portfolio_manager.snapshots)):
            prev_value = portfolio_manager.snapshots[i-1].total_value
            curr_value = portfolio_manager.snapshots[i].total_value
            
            if prev_value > 0:
                daily_return = (curr_value - prev_value) / prev_value
                returns.append(daily_return)
        
        if len(returns) < 5:
            return 0.0
        
        # Calculate downside deviation (only negative returns)
        target_return = 0.0  # Minimum acceptable return
        downside_returns = [r for r in returns if r < target_return]
        
        if len(downside_returns) < 2:
            downside_deviation = 0.0
        else:
            downside_deviation = np.std(downside_returns)
        
        # Calculate annualized mean return
        mean_return = np.mean(returns)
        annualized_return = mean_return * 365
        
        # Calculate Sortino ratio
        if downside_deviation > 0:
            sortino_ratio = annualized_return / downside_deviation
        else:
            sortino_ratio = float('inf') if annualized_return > 0 else 0.0
        
        return sortino_ratio
    
    def _calculate_portfolio_beta(
        self, 
        portfolio_manager: PortfolioManager, 
        market_returns: Optional[pd.DataFrame]
    ) -> float:
        """Calculate portfolio beta relative to market."""
        if not market_returns or not portfolio_manager.snapshots or len(portfolio_manager.snapshots) < 10:
            return 1.0  # Default beta
        
        # Align portfolio returns with market returns
        # This is simplified - in practice would need date alignment
        
        # For now, return default
        return 1.0
    
    def _calculate_concentration_risk(self, portfolio_manager: PortfolioManager) -> float:
        """Calculate concentration risk (0-1, higher = more concentrated)."""
        if not portfolio_manager.positions:
            return 0.0
        
        portfolio_value = portfolio_manager.get_portfolio_value()
        if portfolio_value <= 0:
            return 0.0
        
        # Calculate Herfindahl-Hirschman Index (HHI)
        position_values = []
        for position in portfolio_manager.positions.values():
            position_value = position.quantity * position.current_price
            position_values.append(position_value)
        
        # Calculate HHI
        hhi = sum((value / portfolio_value) ** 2 for value in position_values)
        
        # Normalize to 0-1 (0 = perfectly diversified, 1 = single position)
        normalized_hhi = min(1.0, hhi * len(position_values))
        
        return normalized_hhi
    
    def _calculate_liquidity_risk(
        self, 
        portfolio_manager: PortfolioManager,
        market_prices: Dict[str, Dict[str, float]]
    ) -> float:
        """Calculate liquidity risk (0-1, higher = less liquid)."""
        if not portfolio_manager.positions:
            return 0.0
        
        # Simplified liquidity risk calculation
        # In practice, would use bid-ask spreads, trading volumes, etc.
        
        portfolio_value = portfolio_manager.get_portfolio_value(market_prices)
        if portfolio_value <= 0:
            return 0.0
        
        # Calculate weighted liquidity score
        total_weight = 0.0
        weighted_liquidity = 0.0
        
        for position in portfolio_manager.positions.values():
            position_value = position.quantity * position.current_price
            weight = position_value / portfolio_value
            
            # Simplified: assume liquidity decreases with position size
            # In practice, would fetch actual liquidity metrics
            liquidity_score = max(0.1, 1.0 - (weight * 5))  # Decrease with concentration
            
            weighted_liquidity += weight * liquidity_score
            total_weight += weight
        
        if total_weight > 0:
            avg_liquidity = weighted_liquidity / total_weight
            liquidity_risk = 1.0 - avg_liquidity
        else:
            liquidity_risk = 0.0
        
        return liquidity_risk
    
    def _calculate_leverage(self, portfolio_manager: PortfolioManager) -> float:
        """Calculate portfolio leverage."""
        portfolio_value = portfolio_manager.get_portfolio_value()
        cash_balance = portfolio_manager.cash_balance
        
        if cash_balance <= 0:
            return float('inf')
        
        leverage = portfolio_value / cash_balance
        return leverage
    
    def _calculate_overall_risk_score(
        self,
        var_95_1d: float,
        max_drawdown: float,
        volatility: float,
        concentration: float,
        liquidity: float
    ) -> float:
        """Calculate overall risk score (0-1, higher = riskier)."""
        weights = self.risk_config["risk_score_weights"]
        
        # Normalize components to 0-1
        var_score = min(1.0, var_95_1d / self.risk_config["max_portfolio_var_95_1d"])
        drawdown_score = min(1.0, max_drawdown / self.risk_config["max_drawdown_limit"])
        volatility_score = min(1.0, volatility / 0.5)  # Cap at 50% volatility
        concentration_score = min(1.0, concentration / self.risk_config["max_concentration"])
        liquidity_score = max(0.0, (1 - self.risk_config["min_liquidity_score"]) - liquidity)
        liquidity_score = min(1.0, liquidity_score / (1 - self.risk_config["min_liquidity_score"]))
        
        # Calculate weighted score
        risk_score = (
            weights["var"] * var_score +
            weights["drawdown"] * drawdown_score +
            weights["volatility"] * volatility_score +
            weights["concentration"] * concentration_score +
            weights["liquidity"] * liquidity_score
        )
        
        return min(1.0, risk_score)
    
    def _check_risk_limits(
        self,
        var_95_1d: float,
        max_drawdown: float,
        concentration_risk: float,
        liquidity_risk: float
    ) -> List[str]:
        """Check for risk limit breaches."""
        breaches = []
        
        # Check VaR limit
        if var_95_1d > self.risk_config["max_portfolio_var_95_1d"]:
            breaches.append(f"VaR breach: {var_95_1d:.2%} > {self.risk_config['max_portfolio_var_95_1d']:.2%}")
        
        # Check drawdown limit
        if max_drawdown > self.risk_config["max_drawdown_limit"]:
            breaches.append(f"Drawdown breach: {max_drawdown:.2%} > {self.risk_config['max_drawdown_limit']:.2%}")
        
        # Check concentration limit
        if concentration_risk > self.risk_config["max_concentration"]:
            breaches.append(f"Concentration breach: {concentration_risk:.2%} > {self.risk_config['max_concentration']:.2%}")
        
        # Check liquidity limit
        min_liquidity = self.risk_config["min_liquidity_score"]
        if (1 - liquidity_risk) < min_liquidity:
            breaches.append(f"Liquidity breach: {1 - liquidity_risk:.2f} < {min_liquidity:.2f}")
        
        # Log breaches
        if breaches:
            for breach in breaches:
                logger.warning(f"Risk limit breach: {breach}")
                
                # Record breach
                self.risk_limit_breaches.append({
                    "timestamp": datetime.utcnow(),
                    "breach": breach,
                    "severity": "HIGH" if "VaR" in breach or "Drawdown" in breach else "MEDIUM"
                })
        
        return breaches
    
    def _calculate_stop_take_prices(
        self,
        position_type: str,
        average_price: float,
        current_price: float
    ) -> Tuple[float, float]:
        """
        Calculate stop loss and take profit prices.
        
        Args:
            position_type: "YES" or "NO"
            average_price: Average entry price
            current_price: Current market price
            
        Returns:
            Tuple of (stop_loss_price, take_profit_price)
        """
        stop_loss_pct = self.risk_config["stop_loss_pct"]
        take_profit_pct = self.risk_config["take_profit_pct"]
        
        if position_type == "YES":
            # YES position: profit if price goes up
            stop_loss_price = average_price * (1 - stop_loss_pct)
            take_profit_price = average_price * (1 + take_profit_pct)
        else:
            # NO position: profit if price goes down
            # Note: In Polymarket, NO price = 1 - YES price
            # For simplicity, we'll calculate similarly
            stop_loss_price = average_price * (1 + stop_loss_pct)  # Price increase = loss for NO
            take_profit_price = average_price * (1 - take_profit_pct)  # Price decrease = profit for NO
        
        # Clip to valid range
        stop_loss_price = max(0.01, min(0.99, stop_loss_price))
        take_profit_price = max(0.01, min(0.99, take_profit_price))
        
        return stop_loss_price, take_profit_price
    
    def _calculate_position_risk_adjusted_return(
        self,
        position: Position,
        volatility: float,
        beta: float
    ) -> float:
        """Calculate risk-adjusted return for a position."""
        # Calculate return since entry
        if position.average_price > 0:
            raw_return = (position.current_price - position.average_price) / position.average_price
        else:
            raw_return = 0.0
        
        # Adjust for risk (simplified Treynor ratio)
        if beta > 0:
            risk_adjusted_return = raw_return / beta
        else:
            risk_adjusted_return = raw_return
        
        # Adjust for volatility
        if volatility > 0:
            risk_adjusted_return = risk_adjusted_return / volatility
        
        return risk_adjusted_return
    
    def _calculate_position_risk_score(
        self,
        position_value: float,
        portfolio_value: float,
        volatility: float,
        beta: float,
        concentration: float
    ) -> float:
        """Calculate position risk score (0-1, higher = riskier)."""
        if portfolio_value <= 0:
            return 0.0
        
        # Component 1: Size relative to portfolio
        size_score = min(1.0, position_value / portfolio_value * 10)  # 10% = 1.0
        
        # Component 2: Volatility
        volatility_score = min(1.0, volatility * 2)  # 50% volatility = 1.0
        
        # Component 3: Beta (market correlation)
        beta_score = min(1.0, abs(beta - 1) * 0.5)  # Beta of 3 = 1.0
        
        # Component 4: Concentration
        concentration_score = min(1.0, concentration * 5)  # 20% concentration = 1.0
        
        # Weighted average
        risk_score = (
            size_score * 0.3 +
            volatility_score * 0.25 +
            beta_score * 0.25 +
            concentration_score * 0.2
        )
        
        return min(1.0, risk_score)
    
    def get_risk_adjusted_position_size(
        self,
        signal: TradingSignal,
        portfolio_value: float,
        current_price: float,
        volatility: float = 0.1
    ) -> float:
        """
        Calculate risk-adjusted position size for a signal.
        
        Args:
            signal: Trading signal
            portfolio_value: Total portfolio value
            current_price: Current market price
            volatility: Market volatility (default 10%)
            
        Returns:
            Position size as percentage of portfolio
        """
        # Base position size from signal
        base_size = signal.position_size_pct
        
        # Adjust for signal strength
        strength_multiplier = signal.signal_type.strength
        
        # Adjust for forecast confidence
        confidence_multiplier = signal.forecast_confidence
        
        # Adjust for volatility (reduce size for higher volatility)
        volatility_multiplier = max(0.1, 1 - (volatility * 2))  # 50% volatility = 0.0 multiplier
        
        # Adjust for portfolio risk
        # If overall risk is high, reduce position sizes
        risk_multiplier = 1.0
        if self.risk_metrics_history:
            latest_risk = self.risk_metrics_history[-1].overall_risk_score
            risk_multiplier = max(0.5, 1 - latest_risk)  # Reduce by up to 50% for high risk
        
        # Calculate final position size
        risk_adjusted_size = (
            base_size *
            strength_multiplier *
            confidence_multiplier *
            volatility_multiplier *
            risk_multiplier
        )
        
        # Apply position limits
        max_position_pct = self.risk_config.get("max_concentration", 0.15)
        risk_adjusted_size = min(max_position_pct, risk_adjusted_size)
        
        # Minimum position size
        min_position_pct = 0.01  # 1% minimum
        risk_adjusted_size = max(min_position_pct, risk_adjusted_size)
        
        logger.debug(f"Risk-adjusted position size: {base_size:.2%} -> {risk_adjusted_size:.2%}")
        
        return risk_adjusted_size
    
    def check_position_risk_limits(
        self,
        position_risk: PositionRisk,
        portfolio_risk: RiskMetrics
    ) -> Tuple[bool, List[str]]:
        """
        Check if a position violates risk limits.
        
        Args:
            position_risk: PositionRisk object
            portfolio_risk: Current portfolio risk metrics
            
        Returns:
            Tuple of (allowed, list_of_violations)
        """
        violations = []
        
        # Check stop loss
        if position_risk.current_price <= position_risk.stop_loss_price:
            violations.append(f"Stop loss triggered: {position_risk.current_price:.4f} <= {position_risk.stop_loss_price:.4f}")
        
        # Check concentration limit
        position_concentration = position_risk.position_value / portfolio_risk.portfolio_value
        max_concentration = self.risk_config["max_concentration"]
        
        if position_concentration > max_concentration:
            violations.append(f"Concentration limit: {position_concentration:.2%} > {max_concentration:.2%}")
        
        # Check position risk score
        max_position_risk_score = 0.8
        if position_risk.risk_score > max_position_risk_score:
            violations.append(f"Position risk score: {position_risk.risk_score:.2f} > {max_position_risk_score}")
        
        # Check portfolio risk impact
        # If portfolio risk is already high, additional positions may be restricted
        if portfolio_risk.overall_risk_score > 0.7:
            violations.append(f"Portfolio risk too high: {portfolio_risk.overall_risk_score:.2f} > 0.7")
        
        allowed = len(violations) == 0
        return allowed, violations


if __name__ == "__main__":
    # Test risk manager
    from ..trading.portfolio_manager import PortfolioManager, Position
    from datetime import datetime
    
    # Initialize risk manager
    risk_manager = RiskManager()
    
    # Create mock portfolio manager
    portfolio_manager = PortfolioManager()
    portfolio_manager.cash_balance = 8000.0
    
    # Create mock positions
    position1 = Position(
        market_id="market_001",
        position_type="YES",
        quantity=100.0,
        average_price=0.55,
        current_price=0.58,
        timestamp=datetime.utcnow()
    )
    
    position2 = Position(
        market_id="market_002",
        position_type="NO",
        quantity=50.0,
        average_price=0.45,
        current_price=0.42,
        timestamp=datetime.utcnow()
    )
    
    portfolio_manager.positions = {
        position1.position_id: position1,
        position2.position_id: position2
    }
    
    # Create mock snapshots
    for i in range(30):
        snapshot = type('Snapshot', (), {
            'timestamp': datetime.utcnow() - timedelta(days=30-i),
            'total_value': 10000.0 + np.random.randn() * 200,
            'drawdown': abs(np.random.randn() * 0.05)
        })
        portfolio_manager.snapshots.append(snapshot)
    
    # Mock market prices
    market_prices = {
        "market_001": {"YES": 0.58, "NO": 0.42},
        "market_002": {"YES": 0.60, "NO": 0.40},
    }
    
    # Calculate portfolio risk
    risk_metrics = risk_manager.calculate_portfolio_risk(
        portfolio_manager=portfolio_manager,
        market_prices=market_prices
    )
    
    print(f"Portfolio Risk Metrics:")
    print(f"  Portfolio Value: ${risk_metrics.portfolio_value:.2f}")
    print(f"  VaR (95%, 1-day): {risk_metrics.var_95_1d:.2%}")
    print(f"  Max Drawdown: {risk_metrics.max_drawdown:.2%}")
    print(f"  Volatility (30d): {risk_metrics.volatility_30d:.2%}")
    print(f"  Sharpe Ratio: {risk_metrics.sharpe_ratio_30d:.2f}")
    print(f"  Concentration Risk: {risk_metrics.concentration_risk:.2f}")
    print(f"  Overall Risk Score: {risk_metrics.overall_risk_score:.2f}")
    print(f"  Risk Limit Breaches: {risk_metrics.risk_limit_breaches}")
    
    # Calculate position risk
    market_data = {
        "volatility_30d": 0.15,
        "beta": 1.2,
    }
    
    position_risk = risk_manager.calculate_position_risk(
        position=position1,
        market_data=market_data,
        portfolio_value=risk_metrics.portfolio_value
    )
    
    print(f"\nPosition Risk Metrics for {position_risk.market_id}:")
    print(f"  Position Value: ${position_risk.position_value:.2f}")
    print(f"  Volatility: {position_risk.volatility:.2%}")
    print(f"  Beta: {position_risk.beta:.2f}")
    print(f"  Stop Loss: {position_risk.stop_loss_price:.4f}")
    print(f"  Take Profit: {position_risk.take_profit_price:.4f}")
    print(f"  Risk Score: {position_risk.risk_score:.2f}")
    
    # Check risk limits
    allowed, violations = risk_manager.check_position_risk_limits(
        position_risk=position_risk,
        portfolio_risk=risk_metrics
    )
    
    print(f"\nRisk Limit Check: {'ALLOWED' if allowed else 'BLOCKED'}")
    if violations:
        print("  Violations:")
        for violation in violations:
            print(f"    - {violation}")