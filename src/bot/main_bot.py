"""
Main bot orchestration module for Polymarket Trading Bot.

This module orchestrates the complete trading pipeline:
- Data collection → Feature engineering → Forecasting → Signal generation → Trade execution
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import traceback
from dataclasses import dataclass
import json
from pathlib import Path

from ..data_collection.data_fetcher import DataFetcher
from ..data_collection.feature_engineering import FeatureEngineer
from ..forecasting.timesfm_forecaster import TimesFMForecaster
from ..forecasting.signal_generator import SignalGenerator
from ..forecasting.forecast_evaluator import ForecastEvaluator
from ..trading.trade_executor import TradeExecutor
from ..trading.portfolio_manager import PortfolioManager
from ..trading.risk_manager import RiskManager
from ..trading.performance_tracker import PerformanceTracker

logger = logging.getLogger(__name__)


@dataclass
class BotState:
    """Container for bot state."""
    timestamp: datetime
    bot_status: str  # RUNNING, PAUSED, STOPPED, ERROR
    current_cycle: int
    active_markets: List[str]
    active_positions: Dict[str, Any]
    portfolio_value: float
    cash_balance: float
    total_trades: int
    total_signals: int
    last_error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "bot_status": self.bot_status,
            "current_cycle": self.current_cycle,
            "active_markets": self.active_markets,
            "active_positions": self.active_positions,
            "portfolio_value": self.portfolio_value,
            "cash_balance": self.cash_balance,
            "total_trades": self.total_trades,
            "total_signals": self.total_signals,
            "last_error": self.last_error,
            "metadata": self.metadata
        }


class PolymarketBot:
    """Main trading bot orchestrator."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the Polymarket trading bot.
        
        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        self.config = self._load_config(config_path)
        
        # Setup logging
        self._setup_logging()
        
        # Initialize components
        logger.info("Initializing Polymarket Trading Bot components...")
        
        # Data components
        self.data_fetcher = DataFetcher(self.config.get("data_collection", {}))
        self.feature_engineer = FeatureEngineer(self.config.get("feature_engineering", {}))
        
        # Forecasting components
        self.forecaster = TimesFMForecaster(self.config.get("forecasting", {}))
        self.signal_generator = SignalGenerator(self.config.get("signal_generation", {}))
        self.forecast_evaluator = ForecastEvaluator(self.config.get("forecast_evaluation", {}))
        
        # Trading components
        self.trade_executor = TradeExecutor(self.config.get("trade_execution", {}))
        self.portfolio_manager = PortfolioManager(self.config.get("portfolio_management", {}))
        self.risk_manager = RiskManager(self.config.get("risk_management", {}))
        self.performance_tracker = PerformanceTracker(self.config.get("performance_tracking", {}))
        
        # Bot state
        self.state = BotState(
            timestamp=datetime.utcnow(),
            bot_status="STOPPED",
            current_cycle=0,
            active_markets=[],
            active_positions={},
            portfolio_value=self.portfolio_manager.get_portfolio_value(),
            cash_balance=self.portfolio_manager.cash_balance,
            total_trades=0,
            total_signals=0
        )
        
        # Runtime parameters
        self.running = False
        self.cycle_interval = self.config.get("bot", {}).get("cycle_interval_minutes", 60)
        self.market_filter = self.config.get("bot", {}).get("market_filter", {})
        self.paper_trading = self.config.get("trade_execution", {}).get("paper_trading", True)
        
        # State persistence
        self.state_file = Path(self.config.get("bot", {}).get("state_file", "bot_state.json"))
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Polymarket Trading Bot initialized. Paper trading: {self.paper_trading}")
    
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """
        Load configuration from file or use defaults.
        
        Args:
            config_path: Path to configuration file
            
        Returns:
            Configuration dictionary
        """
        default_config = {
            "bot": {
                "cycle_interval_minutes": 60,
                "market_filter": {
                    "min_liquidity_usd": 1000,
                    "max_days_to_resolution": 90,
                    "min_market_age_hours": 24,
                },
                "state_file": "bot_state.json",
                "log_file": "polymarket_bot.log",
            },
            "data_collection": {
                "api_endpoint": "https://gamma-api.polymarket.com",
                "poll_interval_minutes": 5,
                "historical_days": 30,
            },
            "feature_engineering": {
                "technical_indicators": {
                    "sma_periods": [12, 24, 48, 168],
                    "ema_periods": [6, 12, 24],
                    "rsi_period": 14,
                    "bb_period": 20,
                    "atr_period": 14,
                }
            },
            "forecasting": {
                "model_version": "google/timesfm-2.5-200m-pytorch",
                "forecast_horizon_hours": 24,
                "confidence_level": 0.95,
            },
            "signal_generation": {
                "strategies": {
                    "probability_mispricing": {
                        "min_deviation": 0.02,
                        "confidence_threshold": 0.8,
                    }
                }
            },
            "trade_execution": {
                "paper_trading": True,
                "max_position_size_usd": 1000,
                "default_slippage": 0.001,
            },
            "portfolio_management": {
                "initial_capital": 10000.0,
                "max_position_size_pct": 0.10,
                "max_portfolio_risk": 0.20,
            },
            "risk_management": {
                "max_portfolio_var_95_1d": 0.05,
                "max_drawdown_limit": 0.20,
                "stop_loss_pct": 0.05,
            },
            "performance_tracking": {
                "performance_window_days": 30,
                "generate_charts": True,
            }
        }
        
        # Load from file if provided
        if config_path:
            try:
                with open(config_path, 'r') as f:
                    file_config = json.load(f)
                
                # Deep merge with defaults
                def deep_merge(base, override):
                    for key, value in override.items():
                        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                            deep_merge(base[key], value)
                        else:
                            base[key] = value
                    return base
                
                config = deep_merge(default_config.copy(), file_config)
                logger.info(f"Loaded configuration from {config_path}")
                
            except Exception as e:
                logger.error(f"Error loading config from {config_path}: {e}")
                logger.info("Using default configuration")
                config = default_config
        else:
            config = default_config
            logger.info("Using default configuration")
        
        return config
    
    def _setup_logging(self):
        """Setup logging configuration."""
        log_config = self.config.get("bot", {}).get("logging", {})
        log_level = log_config.get("level", "INFO")
        log_file = log_config.get("file", "polymarket_bot.log")
        
        # Create log directory if needed
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Configure logging
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
    
    async def run_single_cycle(self) -> bool:
        """
        Run a single bot cycle.
        
        Returns:
            True if cycle completed successfully, False otherwise
        """
        cycle_start = datetime.utcnow()
        logger.info(f"Starting bot cycle {self.state.current_cycle}")
        
        try:
            # Step 1: Fetch market data
            logger.info("Step 1: Fetching market data...")
            markets_data = await self.data_fetcher.fetch_active_markets()
            
            if not markets_data:
                logger.warning("No market data fetched")
                return False
            
            # Filter markets
            filtered_markets = self._filter_markets(markets_data)
            self.state.active_markets = list(filtered_markets.keys())
            
            logger.info(f"Processing {len(filtered_markets)} filtered markets")
            
            # Step 2: Fetch historical data for filtered markets
            logger.info("Step 2: Fetching historical data...")
            market_histories = {}
            for market_id, market_info in filtered_markets.items():
                history = await self.data_fetcher.fetch_market_history(
                    market_id=market_id,
                    hours_back=168  # 1 week
                )
                
                if history and len(history) >= 48:  # Minimum 48 data points
                    market_histories[market_id] = {
                        "info": market_info,
                        "history": history
                    }
                else:
                    logger.debug(f"Insufficient history for market {market_id}")
            
            if not market_histories:
                logger.warning("No markets with sufficient history")
                return False
            
            # Step 3: Engineer features
            logger.info("Step 3: Engineering features...")
            market_features = {}
            for market_id, data in market_histories.items():
                feature_set = self.feature_engineer.create_features_from_prices(
                    market_id=market_id,
                    prices=data["history"],
                    current_timestamp=datetime.utcnow()
                )
                
                if feature_set:
                    market_features[market_id] = {
                        "features": feature_set.features,
                        "current_price": feature_set.yes_price
                    }
            
            if not market_features:
                logger.warning("No features engineered")
                return False
            
            # Step 4: Generate forecasts
            logger.info("Step 4: Generating forecasts...")
            forecasts = {}
            for market_id, data in market_histories.items():
                if market_id in market_features:
                    # Extract price history for forecasting
                    price_history = [p["yes_price"] for p in data["history"]]
                    price_array = np.array(price_history)
                    
                    forecast = self.forecaster.forecast(
                        market_id=market_id,
                        price_history=price_array,
                        horizon_hours=24,
                        features=market_features[market_id]["features"]
                    )
                    
                    if forecast:
                        forecasts[market_id] = forecast
            
            if not forecasts:
                logger.warning("No forecasts generated")
                return False
            
            # Step 5: Generate trading signals
            logger.info("Step 5: Generating trading signals...")
            signals = {}
            for market_id, forecast in forecasts.items():
                if market_id in market_features:
                    signal = self.signal_generator.generate_signal(
                        market_id=market_id,
                        forecast_result=forecast,
                        current_price=market_features[market_id]["current_price"],
                        market_features=market_features[market_id]["features"],
                        strategy="probability_mispricing"
                    )
                    
                    if signal:
                        signals[market_id] = signal
                        self.state.total_signals += 1
            
            if not signals:
                logger.info("No trading signals generated")
                return True  # No signals is not an error
            
            # Step 6: Filter and prioritize signals
            logger.info("Step 6: Filtering signals...")
            filtered_signals = self.signal_generator.filter_signals(
                signals=signals,
                min_score=0.5,
                max_positions=5
            )
            
            # Step 7: Risk-adjusted position sizing
            logger.info("Step 7: Calculating risk-adjusted positions...")
            portfolio_value = self.portfolio_manager.get_portfolio_value()
            
            for market_id, signal in filtered_signals.items():
                # Calculate risk-adjusted position size
                volatility = market_features[market_id]["features"].get("atr_percent", 0.1)
                
                risk_adjusted_size = self.risk_manager.get_risk_adjusted_position_size(
                    signal=signal,
                    portfolio_value=portfolio_value,
                    current_price=signal.current_price,
                    volatility=volatility
                )
                
                # Update signal with risk-adjusted size
                signal.position_size_pct = risk_adjusted_size
            
            # Step 8: Execute trades
            logger.info("Step 8: Executing trades...")
            executed_orders = []
            
            for market_id, signal in filtered_signals.items():
                # Check portfolio constraints
                position_limits = self.portfolio_manager.get_position_limits(
                    market_id=market_id,
                    position_type="YES",  # Assuming YES positions
                    current_price=signal.current_price
                )
                
                # Check risk limits
                portfolio_risk = self.risk_manager.calculate_portfolio_risk(
                    portfolio_manager=self.portfolio_manager,
                    market_prices={market_id: {"YES": signal.current_price, "NO": 1 - signal.current_price}}
                )
                
                position_allowed, reason = self.portfolio_manager.check_trade_allowed(
                    market_id=market_id,
                    position_type="YES",
                    quantity=position_limits["available_quantity"],
                    price=signal.current_price,
                    trade_value=position_limits["available_value"]
                )
                
                if position_allowed:
                    # Execute trade
                    order = await self.trade_executor.execute_signal(
                        market_id=market_id,
                        signal_type=signal.signal_type.value,
                        position_size_pct=signal.position_size_pct,
                        current_price=signal.current_price,
                        portfolio_value=portfolio_value,
                        metadata={
                            "signal_score": signal.signal_score,
                            "forecast_deviation": signal.deviation_pct,
                            "forecast_confidence": signal.forecast_confidence,
                        }
                    )
                    
                    if order and order.status == "EXECUTED":
                        executed_orders.append(order)
                        self.state.total_trades += 1
                        
                        # Update portfolio
                        self.portfolio_manager.update_position_from_order(order)
                        
                        logger.info(f"Executed trade for {market_id}: "
                                  f"{order.order_type} {order.executed_quantity:.2f} @ {order.executed_price:.4f}")
                else:
                    logger.debug(f"Trade not allowed for {market_id}: {reason}")
            
            # Step 9: Update portfolio and risk metrics
            logger.info("Step 9: Updating portfolio and risk metrics...")
            
            # Update market prices for portfolio valuation
            current_prices = {}
            for market_id in set(list(market_features.keys()) + list(self.portfolio_manager.positions.keys())):
                if market_id in market_features:
                    current_prices[market_id] = {
                        "YES": market_features[market_id]["current_price"],
                        "NO": 1 - market_features[market_id]["current_price"]
                    }
            
            # Update portfolio snapshot
            self.portfolio_manager.update_position_prices(current_prices)
            self.portfolio_manager.create_snapshot(current_prices)
            
            # Update performance tracker
            for snapshot in self.portfolio_manager.snapshots[-len(executed_orders):]:
                self.performance_tracker.add_portfolio_snapshot(snapshot)
            
            for order in executed_orders:
                self.performance_tracker.add_trade(order)
            
            for signal in filtered_signals.values():
                self.performance_tracker.add_signal(signal)
            
            # Step 10: Generate performance report (if needed)
            if self.state.current_cycle % 24 == 0:  # Daily report
                logger.info("Generating daily performance report...")
                report = self.performance_tracker.generate_performance_report(
                    start_date=cycle_start - timedelta(days=1),
                    end_date=cycle_start
                )
                
                # Log summary
                logger.info("Daily Performance Summary:")
                summary_lines = report.split('\n')[:20]
                for line in summary_lines:
                    logger.info(line)
            
            # Update bot state
            self.state.timestamp = datetime.utcnow()
            self.state.portfolio_value = self.portfolio_manager.get_portfolio_value()
            self.state.cash_balance = self.portfolio_manager.cash_balance
            self.state.active_positions = {
                pos.position_id: {
                    "market_id": pos.market_id,
                    "type": pos.position_type,
                    "quantity": pos.quantity,
                    "value": pos.quantity * pos.current_price
                }
                for pos in self.portfolio_manager.positions.values()
            }
            
            # Save state
            self.save_state()
            
            cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
            logger.info(f"Bot cycle {self.state.current_cycle} completed in {cycle_duration:.1f} seconds")
            
            return True
            
        except Exception as e:
            error_msg = f"Error in bot cycle: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            
            self.state.last_error = error_msg
            self.save_state()
            
            return False
    
    def _filter_markets(self, markets_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter markets based on criteria.
        
        Args:
            markets_data: Dictionary of market data
            
        Returns:
            Filtered dictionary of markets
        """
        filtered = {}
        filter_config = self.market_filter
        
        for market_id, market_info in markets_data.items():
            # Apply filters
            
            # Liquidity filter
            min_liquidity = filter_config.get("min_liquidity_usd", 1000)
            liquidity = market_info.get("liquidity_usd", 0)
            if liquidity < min_liquidity:
                continue
            
            # Days to resolution filter
            max_days = filter_config.get("max_days_to_resolution", 90)
            days_to_resolution = market_info.get("days_to_resolution", 365)
            if days_to_resolution > max_days:
                continue
            
            # Market age filter
            min_age = filter_config.get("min_market_age_hours", 24)
            market_age = market_info.get("market_age_hours", 0)
            if market_age < min_age:
                continue
            
            # Volume filter (optional)
            min_volume = filter_config.get("min_daily_volume_usd", 100)
            volume = market_info.get("daily_volume_usd", 0)
            if volume < min_volume:
                continue
            
            # Add to filtered
            filtered[market_id] = market_info
        
        return filtered
    
    async def run(self):
        """Run the bot continuously."""
        if self.running:
            logger.warning("Bot is already running")
            return
        
        logger.info("Starting Polymarket Trading Bot...")
        self.running = True
        self.state.bot_status = "RUNNING"
        self.save_state()
        
        try:
            while self.running:
                # Run cycle
                success = await self.run_single_cycle()
                
                if not success:
                    logger.error("Bot cycle failed, waiting before retry...")
                    await asyncio.sleep(300)  # 5 minutes before retry
                
                # Increment cycle counter
                self.state.current_cycle += 1
                
                # Wait for next cycle
                if self.running:
                    logger.info(f"Waiting {self.cycle_interval} minutes for next cycle...")
                    await asyncio.sleep(self.cycle_interval * 60)
                
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Fatal error in bot run loop: {e}")
            logger.error(traceback.format_exc())
        finally:
            self.stop()
    
    def stop(self):
        """Stop the bot."""
        logger.info("Stopping Polymarket Trading Bot...")
        self.running = False
        self.state.bot_status = "STOPPED"
        self.save_state()
    
    def pause(self):
        """Pause the bot."""
        logger.info("Pausing Polymarket Trading Bot...")
        self.running = False
        self.state.bot_status = "PAUSED"
        self.save_state()
    
    def resume(self):
        """Resume the bot."""
        logger.info("Resuming Polymarket Trading Bot...")
        self.running = True
        self.state.bot_status = "RUNNING"
        self.save_state()
    
    def save_state(self):
        """Save bot state to file."""
        try:
            state_dict = self.state.to_dict()
            
            with open(self.state_file, 'w') as f:
                json.dump(state_dict, f, indent=2)
            
            logger.debug(f"Saved bot state to {self.state_file}")
            
        except Exception as e:
            logger.error(f"Error saving bot state: {e}")
    
    def load_state(self):
        """Load bot state from file."""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    state_dict = json.load(f)
                
                self.state = BotState(
                    timestamp=datetime.fromisoformat(state_dict["timestamp"]),
                    bot_status=state_dict["bot_status"],
                    current_cycle=state_dict["current_cycle"],
                    active_markets=state_dict["active_markets"],
                    active_positions=state_dict["active_positions"],
                    portfolio_value=state_dict["portfolio_value"],
                    cash_balance=state_dict["cash_balance"],
                    total_trades=state_dict["total_trades"],
                    total_signals=state_dict["total_signals"],
                    last_error=state_dict.get("last_error"),
                    metadata=state_dict.get("metadata")
                )
                
                logger.info(f"Loaded bot state from {self.state_file}")
                
                # Update portfolio manager if needed
                if self.state.bot_status in ["RUNNING", "PAUSED"]:
                    # Load portfolio state if exists
                    portfolio_file = Path("portfolio_state.json")
                    if portfolio_file.exists():
                        self.portfolio_manager.load_portfolio(str(portfolio_file))
                
            else:
                logger.info("No saved state found, starting fresh")
                
        except Exception as e:
            logger.error(f"Error loading bot state: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current bot status."""
        return {
            "running": self.running,
            "state": self.state.to_dict(),
            "portfolio_value": self.portfolio_manager.get_portfolio_value(),
            "cash_balance": self.portfolio_manager.cash_balance,
            "active_positions": len(self.portfolio_manager.positions),
            "total_trades": self.state.total_trades,
            "total_signals": self.state.total_signals,
            "last_cycle": self.state.current_cycle,
            "paper_trading": self.paper_trading,
        }
    
    async def run_backtest(
        self,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float = 10000.0
    ) -> Dict[str, Any]:
        """
        Run a backtest on historical data.
        
        Args:
            start_date: Start date for backtest
            end_date: End date for backtest
            initial_capital: Initial capital for backtest
            
        Returns:
            Backtest results
        """
        logger.info(f"Starting backtest from {start_date} to {end_date}")
        
        # This is a placeholder for backtest implementation
        # In a real implementation, this would:
        # 1. Fetch historical market data for the period
        # 2. Run the trading pipeline on historical data
        # 3. Track performance without actual execution
        # 4. Return detailed results
        
        logger.warning("Backtest functionality not yet implemented")
        
        return {
            "status": "not_implemented",
            "message": "Backtest functionality is planned for future release",
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "initial_capital": initial_capital
        }


# Helper function to import numpy
import numpy as np


if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def example():
        # Initialize bot
        bot = PolymarketBot()
        
        # Load saved state if exists
        bot.load_state()
        
        # Run a single cycle
        print("Running single cycle...")
        success = await bot.run_single_cycle()
        
        if success:
            print("Cycle completed successfully")
            
            # Get status
            status = bot.get_status()
            print(f"Portfolio value: ${status['portfolio_value']:.2f}")
            print(f"Active positions: {status['active_positions']}")
            print(f"Total trades: {status['total_trades']}")
        else:
            print("Cycle failed")
        
        # Save state
        bot.save_state()
    
    # Run example
    asyncio.run(example())