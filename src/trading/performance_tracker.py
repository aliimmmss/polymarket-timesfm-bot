"""
Performance tracking module for Polymarket Trading Bot.

This module handles:
- Performance metrics calculation and reporting
- Benchmark comparison
- Performance attribution analysis
- Report generation
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass
import json
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns

from ..forecasting.signal_generator import TradingSignal
from ..forecasting.forecast_evaluator import ForecastEvaluation
from .portfolio_manager import PortfolioSnapshot
from .trade_executor import Order

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Container for comprehensive performance metrics."""
    timestamp: datetime
    period_days: int
    
    # Return metrics
    total_return: float
    total_return_pct: float
    annualized_return: float
    daily_return_mean: float
    daily_return_std: float
    
    # Risk metrics
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    volatility_annualized: float
    var_95_1d: float
    cvar_95_1d: float
    
    # Trading metrics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    avg_trade: float
    best_trade: float
    worst_trade: float
    
    # Signal metrics
    total_signals: int
    signal_accuracy: float
    avg_signal_score: float
    forecast_mae: float
    forecast_coverage: float
    
    # Portfolio metrics
    avg_position_size: float
    max_position_size: float
    avg_leverage: float
    turnover_ratio: float
    concentration_hhi: float
    
    # Benchmark comparison
    alpha: Optional[float] = None
    beta: Optional[float] = None
    tracking_error: Optional[float] = None
    information_ratio: Optional[float] = None
    
    metadata: Optional[Dict[str, Any]] = None


class PerformanceTracker:
    """Track and analyze trading performance."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize performance tracker.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Default configuration
        self.tracker_config = {
            "performance_window_days": 30,
            "benchmark_returns": None,  # Optional benchmark returns series
            "risk_free_rate": 0.02,  # 2% annual risk-free rate
            "reporting_frequency": "daily",  # daily, weekly, monthly
            "save_reports": True,
            "reports_dir": "performance_reports",
            "generate_charts": True,
            "charts_dir": "performance_charts",
        }
        
        # Update with config if provided
        if "tracking" in self.config:
            self.tracker_config.update(self.config["tracking"])
        
        # Performance data storage
        self.portfolio_snapshots: List[PortfolioSnapshot] = []
        self.trade_history: List[Order] = []
        self.trading_signals: List[TradingSignal] = []
        self.forecast_evaluations: List[ForecastEvaluation] = []
        
        # Performance metrics history
        self.performance_metrics_history: List[PerformanceMetrics] = []
        
        # Create directories if needed
        if self.tracker_config["save_reports"]:
            reports_dir = Path(self.tracker_config["reports_dir"])
            reports_dir.mkdir(parents=True, exist_ok=True)
        
        if self.tracker_config["generate_charts"]:
            charts_dir = Path(self.tracker_config["charts_dir"])
            charts_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized PerformanceTracker with config: {self.tracker_config}")
    
    def add_portfolio_snapshot(self, snapshot: PortfolioSnapshot):
        """Add portfolio snapshot to tracker."""
        self.portfolio_snapshots.append(snapshot)
        
        # Limit history size
        if len(self.portfolio_snapshots) > 10000:
            self.portfolio_snapshots = self.portfolio_snapshots[-10000:]
    
    def add_trade(self, trade: Order):
        """Add trade to tracker."""
        self.trade_history.append(trade)
        
        # Limit history size
        if len(self.trade_history) > 10000:
            self.trade_history = self.trade_history[-10000:]
    
    def add_signal(self, signal: TradingSignal):
        """Add trading signal to tracker."""
        self.trading_signals.append(signal)
        
        # Limit history size
        if len(self.trading_signals) > 10000:
            self.trading_signals = self.trading_signals[-10000:]
    
    def add_forecast_evaluation(self, evaluation: ForecastEvaluation):
        """Add forecast evaluation to tracker."""
        self.forecast_evaluations.append(evaluation)
        
        # Limit history size
        if len(self.forecast_evaluations) > 10000:
            self.forecast_evaluations = self.forecast_evaluations[-10000:]
    
    def calculate_performance_metrics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        benchmark_returns: Optional[pd.Series] = None
    ) -> PerformanceMetrics:
        """
        Calculate comprehensive performance metrics.
        
        Args:
            start_date: Start date for analysis
            end_date: End date for analysis
            benchmark_returns: Optional benchmark returns series
            
        Returns:
            PerformanceMetrics object
        """
        timestamp = datetime.utcnow()
        
        # Filter data by date range
        portfolio_snapshots = self._filter_by_date(self.portfolio_snapshots, start_date, end_date)
        trades = self._filter_by_date(self.trade_history, start_date, end_date)
        signals = self._filter_by_date(self.trading_signals, start_date, end_date)
        evaluations = self._filter_by_date(self.forecast_evaluations, start_date, end_date)
        
        # Calculate period length
        if portfolio_snapshots:
            period_days = (portfolio_snapshots[-1].timestamp - portfolio_snapshots[0].timestamp).days
            if period_days == 0:
                period_days = 1
        else:
            period_days = 1
        
        # Calculate return metrics
        return_metrics = self._calculate_return_metrics(portfolio_snapshots, period_days)
        
        # Calculate risk metrics
        risk_metrics = self._calculate_risk_metrics(portfolio_snapshots)
        
        # Calculate trading metrics
        trading_metrics = self._calculate_trading_metrics(trades)
        
        # Calculate signal metrics
        signal_metrics = self._calculate_signal_metrics(signals, evaluations)
        
        # Calculate portfolio metrics
        portfolio_metrics = self._calculate_portfolio_metrics(portfolio_snapshots, trades)
        
        # Calculate benchmark comparison
        benchmark_metrics = self._calculate_benchmark_metrics(
            portfolio_snapshots, 
            benchmark_returns or self.tracker_config.get("benchmark_returns")
        )
        
        # Create metadata
        metadata = {
            "data_points": {
                "portfolio_snapshots": len(portfolio_snapshots),
                "trades": len(trades),
                "signals": len(signals),
                "evaluations": len(evaluations),
            },
            "period": {
                "start": portfolio_snapshots[0].timestamp.isoformat() if portfolio_snapshots else None,
                "end": portfolio_snapshots[-1].timestamp.isoformat() if portfolio_snapshots else None,
                "days": period_days,
            },
            "calculation_time": timestamp.isoformat(),
        }
        
        # Combine all metrics
        performance_metrics = PerformanceMetrics(
            timestamp=timestamp,
            period_days=period_days,
            
            # Return metrics
            total_return=return_metrics["total_return"],
            total_return_pct=return_metrics["total_return_pct"],
            annualized_return=return_metrics["annualized_return"],
            daily_return_mean=return_metrics["daily_return_mean"],
            daily_return_std=return_metrics["daily_return_std"],
            
            # Risk metrics
            sharpe_ratio=risk_metrics["sharpe_ratio"],
            sortino_ratio=risk_metrics["sortino_ratio"],
            calmar_ratio=risk_metrics["calmar_ratio"],
            max_drawdown=risk_metrics["max_drawdown"],
            volatility_annualized=risk_metrics["volatility_annualized"],
            var_95_1d=risk_metrics["var_95_1d"],
            cvar_95_1d=risk_metrics["cvar_95_1d"],
            
            # Trading metrics
            total_trades=trading_metrics["total_trades"],
            winning_trades=trading_metrics["winning_trades"],
            losing_trades=trading_metrics["losing_trades"],
            win_rate=trading_metrics["win_rate"],
            profit_factor=trading_metrics["profit_factor"],
            avg_win=trading_metrics["avg_win"],
            avg_loss=trading_metrics["avg_loss"],
            avg_trade=trading_metrics["avg_trade"],
            best_trade=trading_metrics["best_trade"],
            worst_trade=trading_metrics["worst_trade"],
            
            # Signal metrics
            total_signals=signal_metrics["total_signals"],
            signal_accuracy=signal_metrics["signal_accuracy"],
            avg_signal_score=signal_metrics["avg_signal_score"],
            forecast_mae=signal_metrics["forecast_mae"],
            forecast_coverage=signal_metrics["forecast_coverage"],
            
            # Portfolio metrics
            avg_position_size=portfolio_metrics["avg_position_size"],
            max_position_size=portfolio_metrics["max_position_size"],
            avg_leverage=portfolio_metrics["avg_leverage"],
            turnover_ratio=portfolio_metrics["turnover_ratio"],
            concentration_hhi=portfolio_metrics["concentration_hhi"],
            
            # Benchmark metrics
            alpha=benchmark_metrics.get("alpha"),
            beta=benchmark_metrics.get("beta"),
            tracking_error=benchmark_metrics.get("tracking_error"),
            information_ratio=benchmark_metrics.get("information_ratio"),
            
            metadata=metadata
        )
        
        # Store in history
        self.performance_metrics_history.append(performance_metrics)
        
        # Limit history size
        if len(self.performance_metrics_history) > 1000:
            self.performance_metrics_history = self.performance_metrics_history[-1000:]
        
        logger.info(f"Calculated performance metrics for {period_days} days: "
                   f"Return={return_metrics['total_return_pct']:.2f}%, "
                   f"Sharpe={risk_metrics['sharpe_ratio']:.2f}, "
                   f"Win Rate={trading_metrics['win_rate']:.1%}")
        
        return performance_metrics
    
    def _filter_by_date(
        self, 
        data: List, 
        start_date: Optional[datetime], 
        end_date: Optional[datetime]
    ) -> List:
        """Filter list of objects by timestamp."""
        if not data:
            return []
        
        filtered = data
        
        if start_date:
            filtered = [item for item in filtered 
                       if hasattr(item, 'timestamp') and item.timestamp >= start_date]
        
        if end_date:
            filtered = [item for item in filtered 
                       if hasattr(item, 'timestamp') and item.timestamp <= end_date]
        
        return filtered
    
    def _calculate_return_metrics(
        self, 
        snapshots: List[PortfolioSnapshot], 
        period_days: int
    ) -> Dict[str, float]:
        """Calculate return-related metrics."""
        if not snapshots or len(snapshots) < 2:
            return {
                "total_return": 0.0,
                "total_return_pct": 0.0,
                "annualized_return": 0.0,
                "daily_return_mean": 0.0,
                "daily_return_std": 0.0,
            }
        
        # Extract values and timestamps
        values = [s.total_value for s in snapshots]
        timestamps = [s.timestamp for s in snapshots]
        
        # Total return
        initial_value = values[0]
        final_value = values[-1]
        total_return = final_value - initial_value
        total_return_pct = total_return / initial_value * 100 if initial_value > 0 else 0.0
        
        # Annualized return
        if period_days > 0:
            annualized_return = ((1 + total_return_pct / 100) ** (365 / period_days) - 1) * 100
        else:
            annualized_return = 0.0
        
        # Daily returns
        daily_returns = []
        for i in range(1, len(values)):
            if values[i-1] > 0:
                daily_return = (values[i] - values[i-1]) / values[i-1]
                daily_returns.append(daily_return)
        
        if daily_returns:
            daily_return_mean = np.mean(daily_returns) * 100  # Percentage
            daily_return_std = np.std(daily_returns) * 100    # Percentage
        else:
            daily_return_mean = 0.0
            daily_return_std = 0.0
        
        return {
            "total_return": total_return,
            "total_return_pct": total_return_pct,
            "annualized_return": annualized_return,
            "daily_return_mean": daily_return_mean,
            "daily_return_std": daily_return_std,
        }
    
    def _calculate_risk_metrics(self, snapshots: List[PortfolioSnapshot]) -> Dict[str, float]:
        """Calculate risk-related metrics."""
        if not snapshots or len(snapshots) < 2:
            return {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "max_drawdown": 0.0,
                "volatility_annualized": 0.0,
                "var_95_1d": 0.0,
                "cvar_95_1d": 0.0,
            }
        
        # Extract values
        values = [s.total_value for s in snapshots]
        
        # Calculate daily returns
        daily_returns = []
        for i in range(1, len(values)):
            if values[i-1] > 0:
                daily_return = (values[i] - values[i-1]) / values[i-1]
                daily_returns.append(daily_return)
        
        if not daily_returns:
            return {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "max_drawdown": 0.0,
                "volatility_annualized": 0.0,
                "var_95_1d": 0.0,
                "cvar_95_1d": 0.0,
            }
        
        # Calculate annualized metrics
        mean_return = np.mean(daily_returns)
        std_return = np.std(daily_returns)
        
        # Annualized volatility
        volatility_annualized = std_return * np.sqrt(365) * 100  # Percentage
        
        # Sharpe ratio
        risk_free_rate = self.tracker_config["risk_free_rate"] / 365  # Daily
        if std_return > 0:
            sharpe_ratio = (mean_return - risk_free_rate) / std_return * np.sqrt(365)
        else:
            sharpe_ratio = 0.0
        
        # Sortino ratio (downside deviation)
        downside_returns = [r for r in daily_returns if r < risk_free_rate]
        if downside_returns and len(downside_returns) >= 2:
            downside_std = np.std(downside_returns)
            if downside_std > 0:
                sortino_ratio = (mean_return - risk_free_rate) / downside_std * np.sqrt(365)
            else:
                sortino_ratio = float('inf') if mean_return > risk_free_rate else 0.0
        else:
            sortino_ratio = float('inf') if mean_return > risk_free_rate else 0.0
        
        # Calmar ratio (return / max drawdown)
        max_drawdown = self._calculate_max_drawdown(values)
        if max_drawdown > 0:
            calmar_ratio = mean_return * 365 / max_drawdown
        else:
            calmar_ratio = float('inf') if mean_return > 0 else 0.0
        
        # Value at Risk (VaR) and Conditional VaR (CVaR)
        var_95_1d = np.percentile(daily_returns, 5) * 100  # 5th percentile (95% confidence)
        cvar_95_1d = np.mean([r for r in daily_returns if r <= np.percentile(daily_returns, 5)]) * 100
        
        return {
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sortino_ratio,
            "calmar_ratio": calmar_ratio,
            "max_drawdown": max_drawdown,
            "volatility_annualized": volatility_annualized,
            "var_95_1d": var_95_1d,
            "cvar_95_1d": cvar_95_1d,
        }
    
    def _calculate_max_drawdown(self, values: List[float]) -> float:
        """Calculate maximum drawdown."""
        peak = values[0]
        max_drawdown = 0.0
        
        for value in values:
            if value > peak:
                peak = value
            
            drawdown = (peak - value) / peak
            max_drawdown = max(max_drawdown, drawdown)
        
        return max_drawdown
    
    def _calculate_trading_metrics(self, trades: List[Order]) -> Dict[str, float]:
        """Calculate trading performance metrics."""
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_trade": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
            }
        
        # Filter executed trades
        executed_trades = [t for t in trades if t.status == "EXECUTED"]
        
        if not executed_trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_trade": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
            }
        
        # Calculate P&L for each trade (simplified)
        trade_pnls = []
        for trade in executed_trades:
            if trade.executed_price and trade.price:
                # Simplified P&L calculation
                price_diff = trade.executed_price - trade.price
                
                if trade.order_type in ["BUY_YES", "BUY_NO"]:
                    # Buying: profit if price goes up
                    pnl = price_diff * trade.quantity
                else:
                    # Selling: profit if price goes down
                    pnl = -price_diff * trade.quantity
                
                trade_pnls.append(pnl - trade.fee_usd)  # Subtract fees
        
        # Calculate metrics
        winning_trades = [p for p in trade_pnls if p > 0]
        losing_trades = [p for p in trade_pnls if p < 0]
        
        total_trades = len(trade_pnls)
        winning_count = len(winning_trades)
        losing_count = len(losing_trades)
        
        win_rate = winning_count / total_trades if total_trades > 0 else 0.0
        
        gross_profit = sum(winning_trades) if winning_trades else 0.0
        gross_loss = abs(sum(losing_trades)) if losing_trades else 0.0
        
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = float('inf') if gross_profit > 0 else 0.0
        
        avg_win = np.mean(winning_trades) if winning_trades else 0.0
        avg_loss = np.mean(losing_trades) if losing_trades else 0.0
        avg_trade = np.mean(trade_pnls) if trade_pnls else 0.0
        
        best_trade = max(trade_pnls) if trade_pnls else 0.0
        worst_trade = min(trade_pnls) if trade_pnls else 0.0
        
        return {
            "total_trades": total_trades,
            "winning_trades": winning_count,
            "losing_trades": losing_count,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_trade": avg_trade,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
        }
    
    def _calculate_signal_metrics(
        self, 
        signals: List[TradingSignal], 
        evaluations: List[ForecastEvaluation]
    ) -> Dict[str, float]:
        """Calculate signal and forecast performance metrics."""
        if not signals:
            return {
                "total_signals": 0,
                "signal_accuracy": 0.0,
                "avg_signal_score": 0.0,
                "forecast_mae": 0.0,
                "forecast_coverage": 0.0,
            }
        
        total_signals = len(signals)
        avg_signal_score = np.mean([s.signal_score for s in signals]) if signals else 0.0
        
        # Calculate signal accuracy (simplified)
        if evaluations:
            # Use forecast evaluations to measure accuracy
            forecast_errors = [e.metrics.get("abs_error", 0) for e in evaluations]
            forecast_mae = np.mean(forecast_errors) if forecast_errors else 0.0
            
            within_pi = [e.metrics.get("within_80_pi", False) for e in evaluations]
            forecast_coverage = np.mean(within_pi) * 100 if within_pi else 0.0
        else:
            forecast_mae = 0.0
            forecast_coverage = 0.0
        
        # Signal accuracy (requires linking signals to outcomes)
        # For now, use a placeholder calculation
        signal_accuracy = 0.0
        if signals and evaluations:
            # Simple accuracy: compare signal direction to price movement
            # This would need proper linking between signals and outcomes
            pass
        
        return {
            "total_signals": total_signals,
            "signal_accuracy": signal_accuracy,
            "avg_signal_score": avg_signal_score,
            "forecast_mae": forecast_mae,
            "forecast_coverage": forecast_coverage,
        }
    
    def _calculate_portfolio_metrics(
        self, 
        snapshots: List[PortfolioSnapshot], 
        trades: List[Order]
    ) -> Dict[str, float]:
        """Calculate portfolio structure metrics."""
        if not snapshots:
            return {
                "avg_position_size": 0.0,
                "max_position_size": 0.0,
                "avg_leverage": 0.0,
                "turnover_ratio": 0.0,
                "concentration_hhi": 0.0,
            }
        
        # Extract metrics from snapshots
        position_sizes = [s.max_position_size for s in snapshots if s.max_position_size]
        leverages = []
        
        for snapshot in snapshots:
            if snapshot.total_value > 0 and snapshot.cash_balance > 0:
                leverage = snapshot.total_value / snapshot.cash_balance
                leverages.append(leverage)
        
        # Calculate average and max position size
        avg_position_size = np.mean(position_sizes) if position_sizes else 0.0
        max_position_size = max(position_sizes) if position_sizes else 0.0
        
        # Calculate average leverage
        avg_leverage = np.mean(leverages) if leverages else 1.0
        
        # Calculate turnover ratio (simplified)
        if snapshots and len(snapshots) > 1:
            period_days = (snapshots[-1].timestamp - snapshots[0].timestamp).days
            if period_days > 0:
                total_trading_volume = sum(
                    t.executed_price * t.executed_quantity 
                    for t in trades 
                    if t.status == "EXECUTED" and t.executed_price and t.executed_quantity
                )
                avg_portfolio_value = np.mean([s.total_value for s in snapshots])
                
                if avg_portfolio_value > 0:
                    turnover_ratio = total_trading_volume / avg_portfolio_value / period_days * 365
                else:
                    turnover_ratio = 0.0
            else:
                turnover_ratio = 0.0
        else:
            turnover_ratio = 0.0
        
        # Calculate concentration HHI (Herfindahl-Hirschman Index)
        # This would require position-level data, using snapshot metadata
        concentration_hhi = 0.0
        if snapshots and snapshots[-1].metadata and "position_details" in snapshots[-1].metadata:
            position_details = snapshots[-1].metadata["position_details"]
            if position_details:
                total_value = snapshots[-1].total_value
                if total_value > 0:
                    position_shares = [
                        details["position_value"] / total_value 
                        for details in position_details.values()
                        if "position_value" in details
                    ]
                    concentration_hhi = sum(share ** 2 for share in position_shares)
        
        return {
            "avg_position_size": avg_position_size,
            "max_position_size": max_position_size,
            "avg_leverage": avg_leverage,
            "turnover_ratio": turnover_ratio,
            "concentration_hhi": concentration_hhi,
        }
    
    def _calculate_benchmark_metrics(
        self, 
        snapshots: List[PortfolioSnapshot], 
        benchmark_returns: Optional[pd.Series]
    ) -> Dict[str, float]:
        """Calculate benchmark comparison metrics."""
        if not benchmark_returns or not snapshots or len(snapshots) < 2:
            return {}
        
        # Align portfolio returns with benchmark returns
        # This is simplified - in practice would need proper date alignment
        
        portfolio_returns = []
        portfolio_dates = []
        
        for i in range(1, len(snapshots)):
            if snapshots[i-1].total_value > 0:
                ret = (snapshots[i].total_value - snapshots[i-1].total_value) / snapshots[i-1].total_value
                portfolio_returns.append(ret)
                portfolio_dates.append(snapshots[i].timestamp.date())
        
        if len(portfolio_returns) < 5:
            return {}
        
        # For now, return placeholder metrics
        return {
            "alpha": 0.0,  # Excess return
            "beta": 1.0,   # Market correlation
            "tracking_error": 0.0,  # Volatility of excess returns
            "information_ratio": 0.0,  # Alpha / tracking error
        }
    
    def generate_performance_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        save_to_file: bool = True
    ) -> str:
        """
        Generate human-readable performance report.
        
        Args:
            start_date: Start date for report
            end_date: End date for report
            save_to_file: Whether to save report to file
            
        Returns:
            Report string
        """
        # Calculate performance metrics
        metrics = self.calculate_performance_metrics(start_date, end_date)
        
        # Generate report sections
        report_sections = [
            self._generate_report_header(metrics),
            self._generate_return_analysis(metrics),
            self._generate_risk_analysis(metrics),
            self._generate_trading_analysis(metrics),
            self._generate_signal_analysis(metrics),
            self._generate_portfolio_analysis(metrics),
            self._generate_conclusion(metrics),
        ]
        
        # Combine sections
        report = "\n\n".join(report_sections)
        
        # Save to file if requested
        if save_to_file and self.tracker_config["save_reports"]:
            self._save_report_to_file(report, start_date, end_date)
        
        # Generate charts if requested
        if self.tracker_config["generate_charts"]:
            self._generate_performance_charts(start_date, end_date)
        
        return report
    
    def _generate_report_header(self, metrics: PerformanceMetrics) -> str:
        """Generate report header section."""
        period_str = f"{metrics.period_days} days"
        if metrics.metadata and "period" in metrics.metadata:
            period = metrics.metadata["period"]
            period_str = f"{period['start']} to {period['end']} ({metrics.period_days} days)"
        
        header = [
            "=" * 80,
            "POLYMARKET TRADING BOT - PERFORMANCE REPORT",
            "=" * 80,
            f"Report Period: {period_str}",
            f"Report Generated: {metrics.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"Total Portfolio Value: ${metrics.metadata['data_points']['portfolio_snapshots']:,} snapshots",
            f"Total Trades: {metrics.total_trades:,}",
            f"Total Signals: {metrics.total_signals:,}",
            "=" * 80,
        ]
        
        return "\n".join(header)
    
    def _generate_return_analysis(self, metrics: PerformanceMetrics) -> str:
        """Generate return analysis section."""
        analysis = [
            "RETURN ANALYSIS",
            "-" * 40,
            f"Total Return: ${metrics.total_return:,.2f} ({metrics.total_return_pct:.2f}%)",
            f"Annualized Return: {metrics.annualized_return:.2f}%",
            f"Average Daily Return: {metrics.daily_return_mean:.4f}%",
            f"Daily Return Std Dev: {metrics.daily_return_std:.4f}%",
            "",
            "Risk-Adjusted Returns:",
            f"  Sharpe Ratio: {metrics.sharpe_ratio:.2f}",
            f"  Sortino Ratio: {metrics.sortino_ratio:.2f}",
            f"  Calmar Ratio: {metrics.calmar_ratio:.2f}",
        ]
        
        # Add benchmark comparison if available
        if metrics.alpha is not None:
            analysis.extend([
                "",
                "Benchmark Comparison:",
                f"  Alpha (Excess Return): {metrics.alpha:.2f}%",
                f"  Beta (Market Correlation): {metrics.beta:.2f}",
                f"  Information Ratio: {metrics.information_ratio:.2f}",
            ])
        
        return "\n".join(analysis)
    
    def _generate_risk_analysis(self, metrics: PerformanceMetrics) -> str:
        """Generate risk analysis section."""
        analysis = [
            "RISK ANALYSIS",
            "-" * 40,
            f"Maximum Drawdown: {metrics.max_drawdown:.2%}",
            f"Annualized Volatility: {metrics.volatility_annualized:.2f}%",
            f"Value at Risk (95%, 1-day): {metrics.var_95_1d:.4f}%",
            f"Conditional VaR (95%, 1-day): {metrics.cvar_95_1d:.4f}%",
            "",
            "Risk Assessment:",
        ]
        
        # Risk assessment based on metrics
        if metrics.max_drawdown > 0.20:
            analysis.append("  ⚠️  HIGH RISK: Maximum drawdown exceeds 20%")
        elif metrics.max_drawdown > 0.10:
            analysis.append("  ⚠️  MODERATE RISK: Maximum drawdown 10-20%")
        else:
            analysis.append("  ✅ LOW RISK: Maximum drawdown under 10%")
        
        if metrics.sharpe_ratio > 1.0:
            analysis.append("  ✅ GOOD: Sharpe ratio above 1.0")
        elif metrics.sharpe_ratio > 0.0:
            analysis.append("  ⚠️  MODERATE: Sharpe ratio 0-1.0")
        else:
            analysis.append("  ❌ POOR: Negative Sharpe ratio")
        
        return "\n".join(analysis)
    
    def _generate_trading_analysis(self, metrics: PerformanceMetrics) -> str:
        """Generate trading performance section."""
        analysis = [
            "TRADING PERFORMANCE",
            "-" * 40,
            f"Total Trades: {metrics.total_trades:,}",
            f"Winning Trades: {metrics.winning_trades:,} ({metrics.win_rate:.1%})",
            f"Losing Trades: {metrics.losing_trades:,} ({1 - metrics.win_rate:.1%})",
            f"Profit Factor: {metrics.profit_factor:.2f}",
            "",
            "Trade Statistics:",
            f"  Average Winning Trade: ${metrics.avg_win:,.2f}",
            f"  Average Losing Trade: ${metrics.avg_loss:,.2f}",
            f"  Average Trade: ${metrics.avg_trade:,.2f}",
            f"  Best Trade: ${metrics.best_trade:,.2f}",
            f"  Worst Trade: ${metrics.worst_trade:,.2f}",
        ]
        
        # Trading assessment
        if metrics.win_rate > 0.6:
            analysis.append("\n  ✅ EXCELLENT: Win rate above 60%")
        elif metrics.win_rate > 0.5:
            analysis.append("\n  ✅ GOOD: Win rate above 50%")
        elif metrics.win_rate > 0.4:
            analysis.append("\n  ⚠️  MODERATE: Win rate 40-50%")
        else:
            analysis.append("\n  ❌ POOR: Win rate below 40%")
        
        if metrics.profit_factor > 2.0:
            analysis.append("  ✅ EXCELLENT: Profit factor above 2.0")
        elif metrics.profit_factor > 1.5:
            analysis.append("  ✅ GOOD: Profit factor 1.5-2.0")
        elif metrics.profit_factor > 1.0:
            analysis.append("  ⚠️  MODERATE: Profit factor 1.0-1.5")
        else:
            analysis.append("  ❌ POOR: Profit factor below 1.0")
        
        return "\n".join(analysis)
    
    def _generate_signal_analysis(self, metrics: PerformanceMetrics) -> str:
        """Generate signal performance section."""
        analysis = [
            "SIGNAL PERFORMANCE",
            "-" * 40,
            f"Total Signals Generated: {metrics.total_signals:,}",
            f"Average Signal Score: {metrics.avg_signal_score:.2f}",
            f"Signal Accuracy: {metrics.signal_accuracy:.1%}",
            "",
            "Forecast Performance:",
            f"  Forecast MAE: {metrics.forecast_mae:.4f}",
            f"  80% PI Coverage: {metrics.forecast_coverage:.1f}%",
        ]
        
        # Signal assessment
        if metrics.avg_signal_score > 0.7:
            analysis.append("\n  ✅ HIGH QUALITY: Average signal score above 0.7")
        elif metrics.avg_signal_score > 0.5:
            analysis.append("\n  ⚠️  MODERATE QUALITY: Average signal score 0.5-0.7")
        else:
            analysis.append("\n  ❌ LOW QUALITY: Average signal score below 0.5")
        
        if metrics.forecast_coverage > 75:
            analysis.append("  ✅ GOOD: Forecast coverage above 75%")
        elif metrics.forecast_coverage > 70:
            analysis.append("  ⚠️  MODERATE: Forecast coverage 70-75%")
        else:
            analysis.append("  ❌ POOR: Forecast coverage below 70%")
        
        return "\n".join(analysis)
    
    def _generate_portfolio_analysis(self, metrics: PerformanceMetrics) -> str:
        """Generate portfolio analysis section."""
        analysis = [
            "PORTFOLIO ANALYSIS",
            "-" * 40,
            f"Average Position Size: ${metrics.avg_position_size:,.2f}",
            f"Maximum Position Size: ${metrics.max_position_size:,.2f}",
            f"Average Leverage: {metrics.avg_leverage:.2f}x",
            f"Annual Turnover Ratio: {metrics.turnover_ratio:.2f}",
            f"Concentration HHI: {metrics.concentration_hhi:.4f}",
        ]
        
        # Portfolio assessment
        if metrics.avg_leverage > 2.0:
            analysis.append("\n  ⚠️  HIGH LEVERAGE: Average leverage above 2.0x")
        elif metrics.avg_leverage > 1.5:
            analysis.append("\n  ⚠️  MODERATE LEVERAGE: Average leverage 1.5-2.0x")
        else:
            analysis.append("\n  ✅ LOW LEVERAGE: Average leverage below 1.5x")
        
        if metrics.concentration_hhi > 0.25:
            analysis.append("  ⚠️  HIGH CONCENTRATION: HHI above 0.25")
        elif metrics.concentration_hhi > 0.15:
            analysis.append("  ⚠️  MODERATE CONCENTRATION: HHI 0.15-0.25")
        else:
            analysis.append("  ✅ WELL DIVERSIFIED: HHI below 0.15")
        
        return "\n".join(analysis)
    
    def _generate_conclusion(self, metrics: PerformanceMetrics) -> str:
        """Generate conclusion section."""
        conclusion = [
            "CONCLUSION & RECOMMENDATIONS",
            "-" * 40,
        ]
        
        # Overall assessment
        positive_factors = []
        negative_factors = []
        
        # Evaluate performance
        if metrics.total_return_pct > 0:
            positive_factors.append(f"Positive total return ({metrics.total_return_pct:.2f}%)")
        else:
            negative_factors.append(f"Negative total return ({metrics.total_return_pct:.2f}%)")
        
        if metrics.sharpe_ratio > 1.0:
            positive_factors.append(f"Good risk-adjusted returns (Sharpe: {metrics.sharpe_ratio:.2f})")
        elif metrics.sharpe_ratio > 0:
            positive_factors.append(f"Positive but moderate risk-adjusted returns")
        else:
            negative_factors.append(f"Poor risk-adjusted returns (Sharpe: {metrics.sharpe_ratio:.2f})")
        
        if metrics.win_rate > 0.5:
            positive_factors.append(f"Profitable trading strategy (Win rate: {metrics.win_rate:.1%})")
        else:
            negative_factors.append(f"Unprofitable trading strategy (Win rate: {metrics.win_rate:.1%})")
        
        # Generate recommendations
        if positive_factors:
            conclusion.append("STRENGTHS:")
            for factor in positive_factors:
                conclusion.append(f"  ✓ {factor}")
        
        if negative_factors:
            conclusion.append("\nAREAS FOR IMPROVEMENT:")
            for factor in negative_factors:
                conclusion.append(f"  ✗ {factor}")
        
        # Specific recommendations
        recommendations = []
        
        if metrics.max_drawdown > 0.15:
            recommendations.append("Consider reducing position sizes or implementing stricter stop losses")
        
        if metrics.forecast_coverage < 70:
            recommendations.append("Improve forecast calibration by adjusting prediction intervals")
        
        if metrics.concentration_hhi > 0.2:
            recommendations.append("Diversify portfolio to reduce concentration risk")
        
        if recommendations:
            conclusion.append("\nSPECIFIC RECOMMENDATIONS:")
            for rec in recommendations:
                conclusion.append(f"  • {rec}")
        
        conclusion.extend([
            "",
            "=" * 80,
            "END OF REPORT",
            "=" * 80,
        ])
        
        return "\n".join(conclusion)
    
    def _save_report_to_file(
        self, 
        report: str, 
        start_date: Optional[datetime], 
        end_date: Optional[datetime]
    ):
        """Save performance report to file."""
        try:
            # Generate filename
            if start_date and end_date:
                filename = f"performance_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.txt"
            else:
                filename = f"performance_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
            
            filepath = Path(self.tracker_config["reports_dir"]) / filename
            
            # Save report
            with open(filepath, 'w') as f:
                f.write(report)
            
            logger.info(f"Saved performance report to {filepath}")
            
        except Exception as e:
            logger.error(f"Error saving performance report: {e}")
    
    def _generate_performance_charts(
        self, 
        start_date: Optional[datetime], 
        end_date: Optional[datetime]
    ):
        """Generate performance visualization charts."""
        try:
            # Filter snapshots by date
            snapshots = self._filter_by_date(self.portfolio_snapshots, start_date, end_date)
            
            if len(snapshots) < 2:
                logger.warning("Insufficient data for chart generation")
                return
            
            # Extract data
            dates = [s.timestamp for s in snapshots]
            values = [s.total_value for s in snapshots]
            returns = [s.daily_return for s in snapshots]
            
            # Create DataFrame
            df = pd.DataFrame({
                'date': dates,
                'portfolio_value': values,
                'daily_return': returns
            })
            df.set_index('date', inplace=True)
            
            # Generate charts
            self._create_equity_curve_chart(df)
            self._create_drawdown_chart(df)
            self._create_returns_distribution_chart(df)
            self._create_rolling_metrics_chart(df)
            
            logger.info("Generated performance charts")
            
        except Exception as e:
            logger.error(f"Error generating performance charts: {e}")
    
    def _create_equity_curve_chart(self, df: pd.DataFrame):
        """Create equity curve chart."""
        try:
            plt.figure(figsize=(12, 6))
            plt.plot(df.index, df['portfolio_value'], linewidth=2)
            plt.title('Portfolio Equity Curve', fontsize=14, fontweight='bold')
            plt.xlabel('Date')
            plt.ylabel('Portfolio Value ($)')
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            # Save chart
            filename = f"equity_curve_{datetime.utcnow().strftime('%Y%m%d')}.png"
            filepath = Path(self.tracker_config["charts_dir"]) / filename
            plt.savefig(filepath, dpi=150)
            plt.close()
            
        except Exception as e:
            logger.error(f"Error creating equity curve chart: {e}")
    
    def _create_drawdown_chart(self, df: pd.DataFrame):
        """Create drawdown chart."""
        try:
            # Calculate drawdown
            peak = df['portfolio_value'].expanding().max()
            drawdown = (df['portfolio_value'] - peak) / peak
            
            plt.figure(figsize=(12, 6))
            plt.fill_between(drawdown.index, drawdown * 100, 0, alpha=0.3, color='red')
            plt.plot(drawdown.index, drawdown * 100, linewidth=2, color='red')
            plt.title('Portfolio Drawdown', fontsize=14, fontweight='bold')
            plt.xlabel('Date')
            plt.ylabel('Drawdown (%)')
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            # Save chart
            filename = f"drawdown_{datetime.utcnow().strftime('%Y%m%d')}.png"
            filepath = Path(self.tracker_config["charts_dir"]) / filename
            plt.savefig(filepath, dpi=150)
            plt.close()
            
        except Exception as e:
            logger.error(f"Error creating drawdown chart: {e}")
    
    def _create_returns_distribution_chart(self, df: pd.DataFrame):
        """Create returns distribution chart."""
        try:
            plt.figure(figsize=(10, 6))
            plt.hist(df['daily_return'].dropna() * 100, bins=50, alpha=0.7, edgecolor='black')
            plt.title('Daily Returns Distribution', fontsize=14, fontweight='bold')
            plt.xlabel('Daily Return (%)')
            plt.ylabel('Frequency')
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            # Save chart
            filename = f"returns_distribution_{datetime.utcnow().strftime('%Y%m%d')}.png"
            filepath = Path(self.tracker_config["charts_dir"]) / filename
            plt.savefig(filepath, dpi=150)
            plt.close()
            
        except Exception as e:
            logger.error(f"Error creating returns distribution chart: {e}")
    
    def _create_rolling_metrics_chart(self, df: pd.DataFrame):
        """Create rolling metrics chart."""
        try:
            # Calculate rolling metrics
            rolling_window = 20
            df['rolling_return'] = df['daily_return'].rolling(rolling_window).mean() * 100
            df['rolling_vol'] = df['daily_return'].rolling(rolling_window).std() * np.sqrt(365) * 100
            df['rolling_sharpe'] = df['rolling_return'] / df['rolling_vol'] * np.sqrt(365)
            
            fig, axes = plt.subplots(3, 1, figsize=(12, 10))
            
            # Rolling returns
            axes[0].plot(df.index, df['rolling_return'], linewidth=2)
            axes[0].set_title(f'{rolling_window}-Day Rolling Average Return', fontsize=12)
            axes[0].set_ylabel('Return (%)')
            axes[0].grid(True, alpha=0.3)
            
            # Rolling volatility
            axes[1].plot(df.index, df['rolling_vol'], linewidth=2, color='orange')
            axes[1].set_title(f'{rolling_window}-Day Rolling Volatility', fontsize=12)
            axes[1].set_ylabel('Volatility (%)')
            axes[1].grid(True, alpha=0.3)
            
            # Rolling Sharpe ratio
            axes[2].plot(df.index, df['rolling_sharpe'], linewidth=2, color='green')
            axes[2].set_title(f'{rolling_window}-Day Rolling Sharpe Ratio', fontsize=12)
            axes[2].set_ylabel('Sharpe Ratio')
            axes[2].set_xlabel('Date')
            axes[2].grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # Save chart
            filename = f"rolling_metrics_{datetime.utcnow().strftime('%Y%m%d')}.png"
            filepath = Path(self.tracker_config["charts_dir"]) / filename
            plt.savefig(filepath, dpi=150)
            plt.close()
            
        except Exception as e:
            logger.error(f"Error creating rolling metrics chart: {e}")


if __name__ == "__main__":
    # Test performance tracker
    from ..trading.portfolio_manager import PortfolioSnapshot
    from ..trading.trade_executor import Order
    from datetime import datetime, timedelta
    import numpy as np
    
    # Initialize tracker
    tracker = PerformanceTracker()
    
    # Create mock portfolio snapshots
    base_value = 10000.0
    for i in range(90):
        snapshot = PortfolioSnapshot(
            timestamp=datetime.utcnow() - timedelta(days=90-i),
            total_value=base_value + np.random.randn() * 200,
            cash_balance=2000.0,
            invested_amount=base_value - 2000.0,
            unrealized_pnl=np.random.randn() * 100,
            realized_pnl=np.random.randn() * 50,
            daily_pnl=np.random.randn() * 50,
            daily_return=np.random.randn() * 0.01,
            drawdown=abs(np.random.randn() * 0.05),
            sharpe_ratio_30d=np.random.randn() * 0.5 + 1.0,
            max_position_size=np.random.rand() * 500,
            active_positions=np.random.randint(1, 5),
            risk_score=np.random.rand(),
            metadata={
                "position_details": {
                    f"market_{j}": {
                        "position_value": np.random.rand() * 1000,
                        "quantity": np.random.rand() * 100,
                        "avg_price": np.random.rand(),
                        "current_price": np.random.rand(),
                        "unrealized_pnl": np.random.randn() * 50
                    }
                    for j in range(3)
                }
            }
        )
        tracker.add_portfolio_snapshot(snapshot)
        base_value = snapshot.total_value
    
    # Create mock trades
    for i in range(50):
        order = Order(
            market_id=f"market_{i % 5}",
            order_type=np.random.choice(["BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"]),
            quantity=np.random.rand() * 100,
            price=np.random.rand(),
            timestamp=datetime.utcnow() - timedelta(days=np.random.randint(1, 90)),
            paper_trade=True
        )
        
        # Simulate execution
        executed_price = order.price * (1 + np.random.randn() * 0.01)
        order.mark_executed(
            executed_price=executed_price,
            executed_quantity=order.quantity,
            fee_usd=order.quantity * executed_price * 0.01,
            slippage=abs(np.random.randn() * 0.001)
        )
        
        tracker.add_trade(order)
    
    # Create mock signals
    for i in range(30):
        from ..forecasting.signal_generator import TradingSignal, SignalType
        
        signal = TradingSignal(
            market_id=f"market_{i % 5}",
            signal_type=np.random.choice(list(SignalType)),
            timestamp=datetime.utcnow() - timedelta(days=np.random.randint(1, 90)),
            forecast_horizon=np.random.randint(1, 25),
            current_price=np.random.rand(),
            forecasted_price=np.random.rand(),
            forecast_confidence=np.random.rand(),
            deviation_pct=np.random.randn() * 0.05,
            confidence_width=np.random.rand() * 0.05,
            signal_score=np.random.rand(),
            position_size_pct=np.random.rand() * 0.1,
            entry_logic="Test signal",
            metadata={"test": True}
        )
        tracker.add_signal(signal)
    
    # Calculate performance metrics
    metrics = tracker.calculate_performance_metrics()
    
    print(f"Performance Metrics:")
    print(f"  Period: {metrics.period_days} days")
    print(f"  Total Return: {metrics.total_return_pct:.2f}%")
    print(f"  Annualized Return: {metrics.annualized_return:.2f}%")
    print(f"  Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
    print(f"  Max Drawdown: {metrics.max_drawdown:.2%}")
    print(f"  Win Rate: {metrics.win_rate:.1%}")
    print(f"  Profit Factor: {metrics.profit_factor:.2f}")
    
    # Generate performance report
    report = tracker.generate_performance_report(save_to_file=False)
    print("\n" + "=" * 80)
    print("PERFORMANCE REPORT PREVIEW:")
    print("=" * 80)
    
    # Print first 50 lines of report
    lines = report.split('\n')
    for i in range(min(50, len(lines))):
        print(lines[i])