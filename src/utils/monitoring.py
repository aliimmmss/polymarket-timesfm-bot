"""Monitoring and metrics collection for the trading bot.

Collects Prometheus metrics:
- Trade latency and volume
- Signal generation performance
- API call statistics
- Circuit breaker state
- Portfolio P&L
"""

import time
import logging
from typing import Dict, Optional, Callable
from functools import wraps
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Try to import Prometheus client
try:
    from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    logger.warning("prometheus_client not available, metrics disabled")
    PROMETHEUS_AVAILABLE = False
    
    # Stub classes for when prometheus is not installed
    class StubMetric:
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    
    Counter = Gauge = Histogram = Info = StubMetric


@dataclass
class MetricSnapshot:
    """Snapshot of metrics for debugging/diagnostics."""
    timestamp: float
    trades_total: int = 0
    trades_success: int = 0
    trades_failed: int = 0
    daily_pnl: float = 0.0
    signals_generated: int = 0
    latency_avg_ms: float = 0.0
    circuit_state: str = "CLOSED"


class MetricsCollector:
    """Collect and expose Prometheus metrics for the trading bot."""
    
    def __init__(self, port: int = 8080):
        """Initialize metrics collector.
        
        Args:
            port: Port for Prometheus metrics endpoint
        """
        self.port = port
        self._setup_metrics()
        
        if PROMETHEUS_AVAILABLE:
            try:
                start_http_server(port)
                logger.info(f"Prometheus metrics server started on port {port}")
            except Exception as e:
                logger.warning(f"Could not start metrics server: {e}")
    
    def _setup_metrics(self):
        """Initialize Prometheus metrics."""
        # Trade metrics
        self.trades_total = Counter(
            'polymarket_trades_total',
            'Total trades executed',
            ['side', 'signal_type', 'status']
        )
        
        self.trade_size = Histogram(
            'polymarket_trade_size_usdc',
            'Trade size in USDC',
            buckets=[1, 5, 10, 25, 50, 100, 250]
        )
        
        self.trade_pnl = Gauge(
            'polymarket_trade_pnl',
            'Trade P&L',
            ['side', 'signal_type']
        )
        
        self.trade_latency = Histogram(
            'polymarket_trade_latency_seconds',
            'Time from signal to execution',
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )
        
        # Signal metrics
        self.signals_generated = Counter(
            'polymarket_signals_generated_total',
            'Total signals generated',
            ['signal_type', 'confidence_high']
        )
        
        self.signal_accuracy = Gauge(
            'polymarket_signal_accuracy',
            'Signal accuracy percentage',
            ['signal_type']
        )
        
        # Portfolio metrics
        self.portfolio_value = Gauge(
            'polymarket_portfolio_value',
            'Total portfolio value in USDC'
        )
        
        self.portfolio_pnl = Gauge(
            'polymarket_portfolio_pnl',
            'Portfolio P&L'
        )
        
        self.positions_count = Gauge(
            'polymarket_positions_count',
            'Number of open positions'
        )
        
        # Circuit breaker metrics
        self.circuit_state = Gauge(
            'polymarket_circuit_state',
            'Circuit breaker state (0=closed, 1=half-open, 2=open)'
        )
        
        self.circuit_trips = Counter(
            'polymarket_circuit_trips_total',
            'Number of circuit breaker trips',
            ['reason']
        )
        
        # API metrics
        self.api_calls = Counter(
            'polymarket_api_calls_total',
            'API calls by endpoint',
            ['endpoint', 'status']
        )
        
        self.api_latency = Histogram(
            'polymarket_api_latency_seconds',
            'API latency by endpoint',
            ['endpoint'],
            buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
        )
        
        # Forecast metrics
        self.forecast_latency = Histogram(
            'polymarket_forecast_latency_seconds',
            'Signal generation time',
            buckets=[1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
        )
        
        self.forecast_accuracy = Gauge(
            'polymarket_forecast_accuracy',
            'Forecast accuracy vs actual'
        )
        
        # System metrics
        self.bot_info = Info(
            'polymarket_bot',
            'Bot version and configuration'
        )
    
    def record_trade(
        self,
        side: str,
        signal_type: str,
        size_usdc: float,
        pnl: Optional[float] = None,
        latency_seconds: Optional[float] = None,
        success: bool = True
    ):
        """Record trade execution.
        
        Args:
            side: 'BUY' or 'SELL'
            signal_type: 'BUY_UP', 'BUY_DOWN', etc.
            size_usdc: Trade size
            pnl: Profit/loss
            latency_seconds: Execution latency
            success: Whether trade succeeded
        """
        status = 'success' if success else 'failed'
        self.trades_total.labels(side=side, signal_type=signal_type, status=status).inc()
        self.trade_size.observe(size_usdc)
        
        if pnl is not None:
            self.trade_pnl.labels(side=side, signal_type=signal_type).set(pnl)
        
        if latency_seconds:
            self.trade_latency.observe(latency_seconds)
    
    def record_signal(
        self,
        signal_type: str,
        confidence: float,
        executed: bool = False
    ):
        """Record signal generation.
        
        Args:
            signal_type: Signal classification
            confidence: Signal confidence (0-1)
            executed: Whether trade was executed
        """
        confidence_high = 'high' if confidence > 0.7 else 'low'
        self.signals_generated.labels(
            signal_type=signal_type,
            confidence_high=confidence_high
        ).inc()
    
    def record_portfolio(
        self,
        total_value: float,
        total_pnl: float,
        positions_count: int
    ):
        """Record portfolio state.
        
        Args:
            total_value: Portfolio value in USDC
            total_pnl: Total P&L
            positions_count: Number of open positions
        """
        self.portfolio_value.set(total_value)
        self.portfolio_pnl.set(total_pnl)
        self.positions_count.set(positions_count)
    
    def record_circuit_state(self, state: str):
        """Record circuit breaker state.
        
        Args:
            state: 'CLOSED', 'OPEN', or 'HALF_OPEN'
        """
        state_map = {'CLOSED': 0, 'HALF_OPEN': 1, 'OPEN': 2}
        self.circuit_state.set(state_map.get(state, 0))
    
    def record_circuit_trip(self, reason: str):
        """Record circuit breaker trip.
        
        Args:
            reason: Why circuit tripped
        """
        self.circuit_trips.labels(reason=reason).inc()
    
    def record_api_call(
        self,
        endpoint: str,
        latency_seconds: float,
        success: bool = True
    ):
        """Record API call.
        
        Args:
            endpoint: API endpoint name
            latency_seconds: Call duration
            success: Whether call succeeded
        """
        status = 'success' if success else 'error'
        self.api_calls.labels(endpoint=endpoint, status=status).inc()
        self.api_latency.labels(endpoint=endpoint).observe(latency_seconds)
    
    def record_forecast(
        self,
        latency_seconds: float,
        accuracy: Optional[float] = None
    ):
        """Record forecast generation.
        
        Args:
            latency_seconds: Forecast generation time
            accuracy: Accuracy vs actual (0-1)
        """
        self.forecast_latency.observe(latency_seconds)
        if accuracy is not None:
            self.forecast_accuracy.set(accuracy)
    
    def set_bot_info(self, version: str, dry_run: bool, network: str):
        """Set bot metadata.
        
        Args:
            version: Bot version
            dry_run: Whether in dry run mode
            network: Network (mainnet/polygon)
        """
        self.bot_info.info({
            'version': version,
            'dry_run': str(dry_run),
            'network': network,
        })
    
    def timed_api_call(self, endpoint: str):
        """Decorator/context manager for timing API calls.
        
        Usage:
            @metrics.timed_api_call('get_markets')
            def fetch_markets():
                ...
            
            with metrics.timed_api_call('get_price'):
                price = fetch_price()
        """
        class Timer:
            def __init__(timer_self, metrics, endpoint):
                timer_self.metrics = metrics
                timer_self.endpoint = endpoint
                timer_self.start = None
            
            def __enter__(timer_self):
                timer_self.start = time.time()
                return timer_self
            
            def __exit__(timer_self, exc_type, exc_val, exc_tb):
                latency = time.time() - timer_self.start
                timer_self.metrics.record_api_call(
                    timer_self.endpoint,
                    latency,
                    success=(exc_type is None)
                )
        
        return Timer(self, endpoint)


class PerformanceTracker:
    """Track trading performance over time."""
    
    def __init__(self):
        self._daily_stats: Dict[str, Dict] = {}
        self._trades: list = []
        
    def record_trade(self, trade_result: Dict):
        """Record a trade for performance tracking."""
        self._trades.append({
            'timestamp': time.time(),
            'side': trade_result.get('side'),
            'pnl': trade_result.get('pnl', 0),
            'success': trade_result.get('success', False),
        })
    
    def get_daily_summary(self, days: int = 1) -> Dict:
        """Get summary for last N days."""
        cutoff = time.time() - (days * 24 * 3600)
        recent = [t for t in self._trades if t['timestamp'] > cutoff]
        
        if not recent:
            return {}
        
        total_pnl = sum(t['pnl'] for t in recent)
        wins = sum(1 for t in recent if t['pnl'] > 0)
        losses = sum(1 for t in recent if t['pnl'] <= 0)
        
        return {
            'total_trades': len(recent),
            'total_pnl': total_pnl,
            'wins': wins,
            'losses': losses,
            'win_rate': wins / len(recent) if recent else 0,
            'avg_pnl': total_pnl / len(recent) if recent else 0,
        }


# Global metrics instance
_metrics: Optional[MetricsCollector] = None


def get_metrics(port: int = 8080) -> MetricsCollector:
    """Get or create global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector(port=port)
    return _metrics


def record_trade(*args, **kwargs):
    """Global helper to record trade."""
    if _metrics:
        _metrics.record_trade(*args, **kwargs)


def record_signal(*args, **kwargs):
    """Global helper to record signal."""
    if _metrics:
        _metrics.record_signal(*args, **kwargs)


def record_portfolio(*args, **kwargs):
    """Global helper to record portfolio."""
    if _metrics:
        _metrics.record_portfolio(*args, **kwargs)


def timed_api_call(endpoint: str):
    """Global helper for timed API calls."""
    if _metrics:
        return _metrics.timed_api_call(endpoint)
    # Return dummy context manager if no metrics
    class DummyTimer:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    return DummyTimer()


if __name__ == "__main__":
    # Test metrics
    logging.basicConfig(level=logging.INFO)
    
    metrics = MetricsCollector(port=8081)
    metrics.set_bot_info("1.0.0", dry_run=True, network="polygon")
    
    # Simulate some metrics
    metrics.record_trade('BUY', 'BUY_UP', 5.0, 0.5, 2.5)
    metrics.record_signal('BUY_UP', 0.85)
    metrics.record_portfolio(1010.0, 10.0, 2)
    
    print("Metrics server running on http://localhost:8081/metrics")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down")
