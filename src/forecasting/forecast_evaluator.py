"""
Forecast evaluation for Polymarket Trading Bot.

This module evaluates the accuracy and quality of TimesFM forecasts,
tracking performance metrics over time.
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass
import json
from pathlib import Path

from .timesfm_forecaster import ForecastResult
from .signal_generator import TradingSignal

logger = logging.getLogger(__name__)


@dataclass
class ForecastEvaluation:
    """Container for forecast evaluation results."""
    market_id: str
    forecast_id: str
    forecast_timestamp: datetime
    evaluation_timestamp: datetime
    actual_price: float
    forecasted_price: float
    metrics: Dict[str, float]
    signal_type: str
    signal_score: float
    realized_pnl: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Calculate derived metrics."""
        # Calculate forecast error
        self.metrics["forecast_error"] = self.actual_price - self.forecasted_price
        self.metrics["abs_error"] = abs(self.metrics["forecast_error"])
        
        # Calculate percentage error
        if self.forecasted_price > 0:
            self.metrics["percentage_error"] = self.metrics["forecast_error"] / self.forecasted_price * 100
        
        # Calculate direction accuracy
        if "forecast_direction" in self.metadata and "actual_direction" in self.metadata:
            self.metrics["direction_accuracy"] = float(
                self.metadata["forecast_direction"] == self.metadata["actual_direction"]
            )


class ForecastEvaluator:
    """Evaluate forecast accuracy and track performance."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize forecast evaluator.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Evaluation metrics configuration
        self.evaluation_config = {
            "evaluation_horizons": [1, 6, 12, 24],  # Hours to evaluate forecasts
            "metrics_to_track": [
                "mae", "rmse", "mape", "coverage_80", "sharpness_80", "calibration_score"
            ],
            "rolling_window_days": 30,
            "min_samples_for_evaluation": 10,
            "save_evaluations": True,
            "evaluation_dir": "evaluations"
        }
        
        # Update with config if provided
        if "evaluation" in self.config:
            self.evaluation_config.update(self.config["evaluation"])
        
        # Initialize storage
        self.evaluations: List[ForecastEvaluation] = []
        self.performance_metrics: Dict[str, Dict[str, Any]] = {}
        
        # Create evaluation directory if needed
        if self.evaluation_config["save_evaluations"]:
            eval_dir = Path(self.evaluation_config["evaluation_dir"])
            eval_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized ForecastEvaluator with config: {self.evaluation_config}")
    
    def evaluate_forecast(
        self,
        forecast_result: ForecastResult,
        actual_price: float,
        evaluation_horizon: int,
        signal: Optional[TradingSignal] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[ForecastEvaluation]:
        """
        Evaluate a single forecast against actual price.
        
        Args:
            forecast_result: ForecastResult to evaluate
            actual_price: Actual price at evaluation horizon
            evaluation_horizon: Horizon index to evaluate (0-based)
            signal: Optional trading signal associated with forecast
            metadata: Additional metadata for evaluation
            
        Returns:
            ForecastEvaluation or None if error
        """
        if evaluation_horizon >= len(forecast_result.point_forecast):
            logger.error(f"Evaluation horizon {evaluation_horizon} out of range "
                        f"(max {len(forecast_result.point_forecast)-1})")
            return None
        
        # Get forecasted price at horizon
        forecasted_price = forecast_result.point_forecast[evaluation_horizon]
        
        # Calculate metrics using TimesFMForecaster's evaluate_forecast method
        # Note: This requires actual prices for the entire horizon
        # For single-point evaluation, we'll calculate simple metrics
        
        # Prepare metadata
        eval_metadata = metadata or {}
        eval_metadata.update({
            "forecast_horizon_index": evaluation_horizon,
            "forecast_horizon_hours": evaluation_horizon + 1,  # Convert to 1-based
            "forecast_confidence_width": forecast_result.confidence_width,
            "signal_generated": signal is not None
        })
        
        # Calculate simple metrics
        error = actual_price - forecasted_price
        abs_error = abs(error)
        
        metrics = {
            "forecast_error": error,
            "abs_error": abs_error,
            "squared_error": error ** 2,
        }
        
        # Calculate percentage error
        if forecasted_price > 0:
            metrics["percentage_error"] = error / forecasted_price * 100
            metrics["abs_percentage_error"] = abs_error / forecasted_price * 100
        
        # Check if actual price is within prediction interval
        if forecast_result.quantile_forecast is not None:
            lower_80 = forecast_result.quantile_forecast[evaluation_horizon, 1]  # 10th percentile
            upper_80 = forecast_result.quantile_forecast[evaluation_horizon, 9]  # 90th percentile
            within_80 = lower_80 <= actual_price <= upper_80
            
            metrics["within_80_pi"] = float(within_80)
            metrics["pi_width"] = upper_80 - lower_80
        
        # Signal information
        signal_type = signal.signal_type.value if signal else "NO_SIGNAL"
        signal_score = signal.signal_score if signal else 0.0
        
        # Create evaluation
        evaluation = ForecastEvaluation(
            market_id=forecast_result.market_id,
            forecast_id=forecast_result.forecast_id,
            forecast_timestamp=forecast_result.forecast_timestamp,
            evaluation_timestamp=datetime.utcnow(),
            actual_price=actual_price,
            forecasted_price=forecasted_price,
            metrics=metrics,
            signal_type=signal_type,
            signal_score=signal_score,
            metadata=eval_metadata
        )
        
        # Store evaluation
        self.evaluations.append(evaluation)
        
        # Save to file if configured
        if self.evaluation_config["save_evaluations"]:
            self._save_evaluation(evaluation)
        
        # Update performance metrics
        self._update_performance_metrics(evaluation)
        
        logger.debug(f"Evaluated forecast {forecast_result.forecast_id}: "
                    f"error={error:.4f}, within_80_pi={metrics.get('within_80_pi', False)}")
        
        return evaluation
    
    def evaluate_forecast_timeseries(
        self,
        forecast_result: ForecastResult,
        actual_prices: np.ndarray,
        signal: Optional[TradingSignal] = None
    ) -> List[ForecastEvaluation]:
        """
        Evaluate forecast against entire timeseries of actual prices.
        
        Args:
            forecast_result: ForecastResult to evaluate
            actual_prices: Array of actual prices matching forecast horizon
            signal: Optional trading signal
            
        Returns:
            List of ForecastEvaluation objects for each horizon point
        """
        if len(actual_prices) != len(forecast_result.point_forecast):
            logger.error(f"Actual prices length {len(actual_prices)} doesn't match "
                        f"forecast length {len(forecast_result.point_forecast)}")
            return []
        
        evaluations = []
        
        for horizon_idx, actual_price in enumerate(actual_prices):
            evaluation = self.evaluate_forecast(
                forecast_result=forecast_result,
                actual_price=actual_price,
                evaluation_horizon=horizon_idx,
                signal=signal if horizon_idx == 0 else None,  # Only include signal for first evaluation
                metadata={"timeseries_evaluation": True}
            )
            
            if evaluation:
                evaluations.append(evaluation)
        
        logger.info(f"Timeseries evaluation complete: {len(evaluations)} points evaluated")
        return evaluations
    
    def get_performance_metrics(
        self,
        market_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get aggregated performance metrics.
        
        Args:
            market_id: Optional market ID to filter by
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            Dictionary of performance metrics
        """
        # Filter evaluations
        filtered_evals = self.evaluations
        
        if market_id:
            filtered_evals = [e for e in filtered_evals if e.market_id == market_id]
        
        if start_date:
            filtered_evals = [e for e in filtered_evals if e.evaluation_timestamp >= start_date]
        
        if end_date:
            filtered_evals = [e for e in filtered_evals if e.evaluation_timestamp <= end_date]
        
        if not filtered_evals:
            return {"error": "No evaluations found for given filters"}
        
        # Calculate metrics
        abs_errors = [e.metrics["abs_error"] for e in filtered_evals]
        squared_errors = [e.metrics.get("squared_error", 0) for e in filtered_evals]
        within_pi = [e.metrics.get("within_80_pi", False) for e in filtered_evals]
        signal_scores = [e.signal_score for e in filtered_evals]
        
        metrics = {
            "total_evaluations": len(filtered_evals),
            "unique_markets": len(set(e.market_id for e in filtered_evals)),
            "time_period": {
                "start": min(e.evaluation_timestamp for e in filtered_evals).isoformat(),
                "end": max(e.evaluation_timestamp for e in filtered_evals).isoformat()
            },
            "accuracy_metrics": {
                "mae": float(np.mean(abs_errors)) if abs_errors else 0.0,
                "rmse": float(np.sqrt(np.mean(squared_errors))) if squared_errors else 0.0,
                "mean_abs_percentage_error": float(np.mean([
                    e.metrics.get("abs_percentage_error", 0) for e in filtered_evals
                ])) if filtered_evals else 0.0,
            },
            "calibration_metrics": {
                "coverage_80": float(np.mean(within_pi) * 100) if within_pi else 0.0,
                "expected_coverage": 80.0,
                "calibration_error": abs(float(np.mean(within_pi) * 100) - 80.0) if within_pi else 0.0,
            },
            "signal_metrics": {
                "mean_signal_score": float(np.mean(signal_scores)) if signal_scores else 0.0,
                "signal_accuracy": self._calculate_signal_accuracy(filtered_evals),
            }
        }
        
        # Add market-specific metrics if market_id not filtered
        if not market_id:
            market_metrics = {}
            for eval_ in filtered_evals:
                if eval_.market_id not in market_metrics:
                    market_metrics[eval_.market_id] = {"count": 0, "errors": []}
                market_metrics[eval_.market_id]["count"] += 1
                market_metrics[eval_.market_id]["errors"].append(eval_.metrics["abs_error"])
            
            # Calculate best/worst performing markets
            market_accuracy = {}
            for market_id, data in market_metrics.items():
                if data["count"] >= 5:  # Minimum samples
                    market_accuracy[market_id] = np.mean(data["errors"])
            
            if market_accuracy:
                metrics["market_performance"] = {
                    "best_markets": sorted(market_accuracy.items(), key=lambda x: x[1])[:5],
                    "worst_markets": sorted(market_accuracy.items(), key=lambda x: x[1], reverse=True)[:5],
                }
        
        # Calculate rolling metrics
        rolling_metrics = self._calculate_rolling_metrics(filtered_evals)
        metrics["rolling_metrics"] = rolling_metrics
        
        return metrics
    
    def _calculate_signal_accuracy(self, evaluations: List[ForecastEvaluation]) -> Dict[str, float]:
        """Calculate signal prediction accuracy."""
        if not evaluations:
            return {}
        
        # Group evaluations with signals
        signal_evals = [e for e in evaluations if e.signal_type != "NO_SIGNAL"]
        if not signal_evals:
            return {"total_signals": 0}
        
        # Calculate direction accuracy
        correct_directions = 0
        for eval_ in signal_evals:
            forecast_direction = 1 if eval_.forecasted_price > 0.5 else -1  # Simple heuristic
            actual_direction = 1 if eval_.actual_price > 0.5 else -1
            
            if forecast_direction == actual_direction:
                correct_directions += 1
        
        total_signals = len(signal_evals)
        accuracy = correct_directions / total_signals if total_signals > 0 else 0.0
        
        # Calculate profit/loss if available
        realized_pnls = [e.realized_pnl for e in signal_evals if e.realized_pnl is not None]
        
        metrics = {
            "total_signals": total_signals,
            "direction_accuracy": accuracy,
            "mean_signal_score": np.mean([e.signal_score for e in signal_evals]),
        }
        
        if realized_pnls:
            metrics.update({
                "total_pnl": float(np.sum(realized_pnls)),
                "mean_pnl_per_signal": float(np.mean(realized_pnls)),
                "win_rate": float(np.mean([p > 0 for p in realized_pnls])),
                "profit_factor": self._calculate_profit_factor(realized_pnls),
            })
        
        return metrics
    
    def _calculate_profit_factor(self, pnls: List[float]) -> float:
        """Calculate profit factor (gross profits / gross losses)."""
        profits = sum(p for p in pnls if p > 0)
        losses = abs(sum(p for p in pnls if p < 0))
        
        if losses == 0:
            return float('inf') if profits > 0 else 0.0
        
        return profits / losses
    
    def _calculate_rolling_metrics(
        self, 
        evaluations: List[ForecastEvaluation]
    ) -> Dict[str, Any]:
        """Calculate rolling window performance metrics."""
        if len(evaluations) < 10:
            return {}
        
        # Convert to DataFrame for easier analysis
        df_data = []
        for eval_ in evaluations:
            df_data.append({
                "timestamp": eval_.evaluation_timestamp,
                "abs_error": eval_.metrics["abs_error"],
                "within_pi": eval_.metrics.get("within_80_pi", False),
                "signal_score": eval_.signal_score,
                "market_id": eval_.market_id
            })
        
        df = pd.DataFrame(df_data)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        
        # Calculate rolling metrics
        window_days = self.evaluation_config["rolling_window_days"]
        window_hours = window_days * 24
        
        rolling_metrics = {}
        
        # MAE rolling
        rolling_mae = df["abs_error"].rolling(f"{window_hours}H").mean()
        rolling_metrics["rolling_mae"] = {
            "current": float(rolling_mae.iloc[-1]) if len(rolling_mae) > 0 else 0.0,
            "trend": self._calculate_trend(rolling_mae.dropna().values),
        }
        
        # Coverage rolling
        if "within_pi" in df.columns:
            rolling_coverage = df["within_pi"].rolling(f"{window_hours}H").mean() * 100
            rolling_metrics["rolling_coverage"] = {
                "current": float(rolling_coverage.iloc[-1]) if len(rolling_coverage) > 0 else 0.0,
                "trend": self._calculate_trend(rolling_coverage.dropna().values),
            }
        
        # Signal score rolling
        rolling_score = df["signal_score"].rolling(f"{window_hours}H").mean()
        rolling_metrics["rolling_signal_score"] = {
            "current": float(rolling_score.iloc[-1]) if len(rolling_score) > 0 else 0.0,
            "trend": self._calculate_trend(rolling_score.dropna().values),
        }
        
        return rolling_metrics
    
    def _calculate_trend(self, series: np.ndarray) -> str:
        """Calculate trend direction from time series."""
        if len(series) < 5:
            return "insufficient_data"
        
        # Simple linear trend
        x = np.arange(len(series))
        slope = np.polyfit(x, series, 1)[0]
        
        if slope > 0.01:
            return "improving"
        elif slope < -0.01:
            return "deteriorating"
        else:
            return "stable"
    
    def _save_evaluation(self, evaluation: ForecastEvaluation):
        """Save evaluation to JSON file."""
        eval_dir = Path(self.evaluation_config["evaluation_dir"])
        
        # Create filename
        filename = f"{evaluation.market_id}_{evaluation.forecast_id}.json"
        filepath = eval_dir / filename
        
        # Convert to dictionary
        eval_dict = {
            "market_id": evaluation.market_id,
            "forecast_id": evaluation.forecast_id,
            "forecast_timestamp": evaluation.forecast_timestamp.isoformat(),
            "evaluation_timestamp": evaluation.evaluation_timestamp.isoformat(),
            "actual_price": evaluation.actual_price,
            "forecasted_price": evaluation.forecasted_price,
            "metrics": evaluation.metrics,
            "signal_type": evaluation.signal_type,
            "signal_score": evaluation.signal_score,
            "realized_pnl": evaluation.realized_pnl,
            "metadata": evaluation.metadata
        }
        
        # Save to file
        with open(filepath, 'w') as f:
            json.dump(eval_dict, f, indent=2)
    
    def load_evaluations(self, filepath: str) -> List[ForecastEvaluation]:
        """Load evaluations from JSON file."""
        evaluations = []
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Handle both single evaluation and list of evaluations
            if isinstance(data, list):
                eval_data = data
            else:
                eval_data = [data]
            
            for eval_dict in eval_data:
                try:
                    evaluation = ForecastEvaluation(
                        market_id=eval_dict["market_id"],
                        forecast_id=eval_dict["forecast_id"],
                        forecast_timestamp=datetime.fromisoformat(eval_dict["forecast_timestamp"]),
                        evaluation_timestamp=datetime.fromisoformat(eval_dict["evaluation_timestamp"]),
                        actual_price=eval_dict["actual_price"],
                        forecasted_price=eval_dict["forecasted_price"],
                        metrics=eval_dict["metrics"],
                        signal_type=eval_dict["signal_type"],
                        signal_score=eval_dict["signal_score"],
                        realized_pnl=eval_dict.get("realized_pnl"),
                        metadata=eval_dict.get("metadata", {})
                    )
                    evaluations.append(evaluation)
                except Exception as e:
                    logger.error(f"Error parsing evaluation: {e}")
                    continue
            
            logger.info(f"Loaded {len(evaluations)} evaluations from {filepath}")
            
        except Exception as e:
            logger.error(f"Error loading evaluations from {filepath}: {e}")
        
        return evaluations
    
    def generate_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> str:
        """
        Generate a human-readable performance report.
        
        Args:
            start_date: Start date for report
            end_date: End date for report
            
        Returns:
            Report string
        """
        # Get performance metrics
        metrics = self.get_performance_metrics(start_date=start_date, end_date=end_date)
        
        if "error" in metrics:
            return f"Report Error: {metrics['error']}"
        
        # Generate report
        report_lines = [
            "=" * 80,
            "FORECAST EVALUATION REPORT",
            "=" * 80,
            f"Period: {metrics['time_period']['start']} to {metrics['time_period']['end']}",
            f"Total Evaluations: {metrics['total_evaluations']}",
            f"Unique Markets: {metrics['unique_markets']}",
            "",
            "ACCURACY METRICS",
            "-" * 40,
            f"MAE (Mean Absolute Error): {metrics['accuracy_metrics']['mae']:.4f}",
            f"RMSE (Root Mean Squared Error): {metrics['accuracy_metrics']['rmse']:.4f}",
            f"MAPE (Mean Abs Percentage Error): {metrics['accuracy_metrics']['mean_abs_percentage_error']:.2f}%",
            "",
            "CALIBRATION METRICS",
            "-" * 40,
            f"80% PI Coverage: {metrics['calibration_metrics']['coverage_80']:.1f}%",
            f"Expected Coverage: {metrics['calibration_metrics']['expected_coverage']:.1f}%",
            f"Calibration Error: {metrics['calibration_metrics']['calibration_error']:.1f}%",
            "",
            "SIGNAL METRICS",
            "-" * 40,
            f"Total Signals: {metrics['signal_metrics'].get('total_signals', 0)}",
            f"Direction Accuracy: {metrics['signal_metrics'].get('direction_accuracy', 0):.1%}",
            f"Mean Signal Score: {metrics['signal_metrics'].get('mean_signal_score', 0):.2f}",
        ]
        
        # Add P&L metrics if available
        if "total_pnl" in metrics['signal_metrics']:
            report_lines.extend([
                "",
                "TRADING PERFORMANCE",
                "-" * 40,
                f"Total P&L: ${metrics['signal_metrics']['total_pnl']:.2f}",
                f"Mean P&L per Signal: ${metrics['signal_metrics']['mean_pnl_per_signal']:.2f}",
                f"Win Rate: {metrics['signal_metrics']['win_rate']:.1%}",
                f"Profit Factor: {metrics['signal_metrics']['profit_factor']:.2f}",
            ])
        
        # Add rolling metrics
        if "rolling_metrics" in metrics:
            rolling = metrics["rolling_metrics"]
            report_lines.extend([
                "",
                "ROLLING METRICS (30-day window)",
                "-" * 40,
                f"Rolling MAE: {rolling.get('rolling_mae', {}).get('current', 0):.4f} "
                f"({rolling.get('rolling_mae', {}).get('trend', 'N/A')})",
                f"Rolling Coverage: {rolling.get('rolling_coverage', {}).get('current', 0):.1f}% "
                f"({rolling.get('rolling_coverage', {}).get('trend', 'N/A')})",
                f"Rolling Signal Score: {rolling.get('rolling_signal_score', {}).get('current', 0):.2f} "
                f"({rolling.get('rolling_signal_score', {}).get('trend', 'N/A')})",
            ])
        
        # Add market performance
        if "market_performance" in metrics:
            market_perf = metrics["market_performance"]
            
            report_lines.extend([
                "",
                "BEST PERFORMING MARKETS (by MAE)",
                "-" * 40,
            ])
            
            for market_id, mae in market_perf.get("best_markets", [])[:3]:
                report_lines.append(f"  {market_id}: MAE={mae:.4f}")
            
            report_lines.extend([
                "",
                "WORST PERFORMING MARKETS (by MAE)",
                "-" * 40,
            ])
            
            for market_id, mae in market_perf.get("worst_markets", [])[:3]:
                report_lines.append(f"  {market_id}: MAE={mae:.4f}")
        
        report_lines.extend([
            "",
            "=" * 80,
            "Report generated: " + datetime.utcnow().isoformat(),
            "=" * 80,
        ])
        
        return "\n".join(report_lines)


if __name__ == "__main__":
    # Test forecast evaluation
    import numpy as np
    from datetime import datetime, timedelta
    
    # Initialize evaluator
    evaluator = ForecastEvaluator()
    
    # Create mock evaluations
    for i in range(20):
        market_id = f"market_{i % 5}"
        
        evaluation = ForecastEvaluation(
            market_id=market_id,
            forecast_id=f"forecast_{i}",
            forecast_timestamp=datetime.utcnow() - timedelta(days=30-i),
            evaluation_timestamp=datetime.utcnow() - timedelta(days=30-i) + timedelta(hours=6),
            actual_price=0.5 + np.random.randn() * 0.1,
            forecasted_price=0.5 + np.random.randn() * 0.1,
            metrics={
                "abs_error": abs(np.random.randn() * 0.05),
                "squared_error": (np.random.randn() * 0.05) ** 2,
                "abs_percentage_error": abs(np.random.randn() * 5),
                "within_80_pi": np.random.choice([True, False], p=[0.8, 0.2]),
            },
            signal_type=np.random.choice(["STRONG_BUY", "MODERATE_BUY", "NEUTRAL", "MODERATE_SELL"]),
            signal_score=np.random.uniform(0.3, 0.9),
            realized_pnl=np.random.randn() * 10,
            metadata={"test": True}
        )
        
        evaluator.evaluations.append(evaluation)
    
    # Generate report
    report = evaluator.generate_report()
    print(report)
    
    # Get performance metrics
    metrics = evaluator.get_performance_metrics()
    print("\nKey metrics:")
    print(f"  MAE: {metrics['accuracy_metrics']['mae']:.4f}")
    print(f"  Coverage: {metrics['calibration_metrics']['coverage_80']:.1f}%")
    print(f"  Signal accuracy: {metrics['signal_metrics'].get('direction_accuracy', 0):.1%}")