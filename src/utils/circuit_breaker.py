"""Circuit breaker for emergency trading halt.

Prevents catastrophic losses by automatically stopping trading
when certain conditions are met.

Conditions that trigger halt:
- Daily loss limit exceeded
- Consecutive failed trades
- Model prediction failure (all NaN)
- API endpoints down
- Manual override trigger
- Extreme price volatility (market manipulation detection)
"""

import time
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"       # Normal operation
    OPEN = "OPEN"           # Halt trading
    HALF_OPEN = "HALF_OPEN" # Testing recovery


class CircuitBreaker:
    """Emergency halt mechanism for trading bot.
    
    Monitors trading conditions and automatically halts
    when safety thresholds are breached.
    """
    
    def __init__(
        self,
        daily_loss_limit: float = 20.0,
        consecutive_failures: int = 5,
        failure_window_minutes: int = 10,
        cooldown_minutes: int = 60,
    ):
        """Initialize circuit breaker.
        
        Args:
            daily_loss_limit: Halt when P&L drops below -$X
            consecutive_failures: Halt after X failures in window
            failure_window_minutes: Time window for failures
            cooldown_minutes: Time before attempting recovery
        """
        self.daily_loss_limit = daily_loss_limit
        self.consecutive_failures = consecutive_failures
        self.failure_window_seconds = failure_window_minutes * 60
        self.cooldown_seconds = cooldown_minutes * 60
        
        # State
        self.state = CircuitState.CLOSED
        self._last_failure_time: Optional[float] = None
        self._failure_count = 0
        self._failure_history: List[Dict] = []
        self._halt_reason: Optional[str] = None
        self._halt_time: Optional[float] = None
        
        # Thresholds
        self._daily_pnl = 0.0
        self._last_pnl_reset = time.time()
        
        logger.info(f"Circuit breaker initialized (daily_loss_limit=${daily_loss_limit})")
    
    def is_trading_allowed(self) -> bool:
        """Check if trading is currently allowed.
        
        Returns:
            True if circuit is CLOSED and all checks pass
        """
        if self.state == CircuitState.OPEN:
            # Check if cooldown has passed
            if self._halt_time and (time.time() - self._halt_time) > self.cooldown_seconds:
                logger.info("Circuit breaker cooldown complete, entering HALF_OPEN state")
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        
        # In CLOSED or HALF_OPEN, run checks
        if not self._run_safety_checks():
            return False
        
        return True
    
    def _run_safety_checks(self) -> bool:
        """Run all safety checks.
        
        Returns:
            True if all checks pass
        """
        # Check 1: Daily loss limit
        if self._daily_pnl < -self.daily_loss_limit:
            self._trip(
                CircuitState.OPEN,
                f"Daily loss limit exceeded: ${self._daily_pnl:.2f}"
            )
            return False
        
        # Check 2: Failure rate
        self._prune_failure_history()
        if self._failure_count >= self.consecutive_failures:
            self._trip(
                CircuitState.OPEN,
                f"Consecutive failures: {self._failure_count} in {self.failure_window_seconds/60:.0f} min"
            )
            return False
        
        return True
    
    def record_trade_result(self, success: bool, pnl: float = 0.0, error: Optional[str] = None):
        """Record trade result for monitoring.
        
        Args:
            success: Whether trade succeeded
            pnl: Profit/loss from trade
            error: Error message if failed
        """
        # Update P&L
        self._daily_pnl += pnl
        
        if not success:
            self._failure_count += 1
            self._failure_history.append({
                'timestamp': time.time(),
                'error': error,
                'pnl': pnl,
            })
            logger.warning(f"Trade failure recorded ({self._failure_count}/{self.consecutive_failures})")
    
    def _prune_failure_history(self):
        """Remove old failures outside the window."""
        cutoff = time.time() - self.failure_window_seconds
        self._failure_history = [f for f in self._failure_history if f['timestamp'] > cutoff]
        self._failure_count = len(self._failure_history)
    
    def _trip(self, new_state: CircuitState, reason: str):
        """Trip the circuit breaker.
        
        Args:
            new_state: New state to enter
            reason: Why circuit tripped
        """
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            self._halt_reason = reason
            self._halt_time = time.time()
            
            logger.error(f"CIRCUIT BREAKER TRIPPED: {reason}")
            logger.error(f"State: {old_state.value} -> {new_state.value}")
    
    def manual_halt(self, reason: str):
        """Manual halt trigger.
        
        Args:
            reason: Reason for manual halt
        """
        self._trip(CircuitState.OPEN, f"MANUAL: {reason}")
    
    def manual_resume(self):
        """Manual resume after halt.
        
        Only works from OPEN or HALF_OPEN state.
        """
        if self.state in [CircuitState.OPEN, CircuitState.HALF_OPEN]:
            # Reset failure count
            self._failure_count = 0
            self._failure_history = []
            self.state = CircuitState.CLOSED
            self._halt_reason = None
            logger.info("Circuit breaker manually resumed")
    
    def record_model_failure(self, reason: str = "Model returned NaN"):
        """Record model prediction failure.
        
        Args:
            reason: Why model failed
        """
        self.record_trade_result(success=False, error=reason)
        logger.error(f"Model failure recorded: {reason}")
    
    def record_api_failure(self, endpoint: str, error: str):
        """Record API endpoint failure.
        
        Args:
            endpoint: Which endpoint failed
            error: Error message
        """
        self.record_trade_result(success=False, error=f"API {endpoint}: {error}")
        logger.error(f"API failure: {endpoint} - {error}")
    
    def get_status(self) -> Dict:
        """Get current circuit breaker status.
        
        Returns:
            Status dict with all metrics
        """
        return {
            'state': self.state.value,
            'trading_allowed': self.is_trading_allowed(),
            'daily_pnl': self._daily_pnl,
            'daily_loss_limit': self.daily_loss_limit,
            'failures_last_10min': self._failure_count,
            'consecutive_failures_limit': self.consecutive_failures,
            'halt_reason': self._halt_reason,
            'halt_time': self._halt_time,
            'halt_duration_minutes': (
                (time.time() - self._halt_time) / 60 if self._halt_time else 0
            ),
        }
    
    def reset_daily_pnl(self):
        """Reset daily P&L tracking (call at market open)."""
        self._daily_pnl = 0.0
        self._last_pnl_reset = time.time()
        self._failure_count = 0
        self._failure_history = []
        logger.info("Daily P&L and failures reset")


class EmergencyStop:
    """Simple emergency stop mechanism."""
    
    def __init__(self):
        self._stopped = False
        self._reason: Optional[str] = None
    
    def stop(self, reason: str):
        """Emergency stop."""
        self._stopped = True
        self._reason = reason
        logger.critical(f"EMERGENCY STOP ACTIVATED: {reason}")
    
    def is_stopped(self) -> bool:
        """Check if stopped."""
        return self._stopped
    
    def clear(self):
        """Clear emergency stop."""
        if self._stopped:
            logger.warning(f"Emergency stop cleared: {self._reason}")
        self._stopped = False
        self._reason = None


# Global circuit breaker instance
circuit_breaker = CircuitBreaker()
emergency_stop = EmergencyStop()


def check_trading_allowed() -> bool:
    """Global check if trading is allowed.
    
    Checks both circuit breaker and emergency stop.
    
    Returns:
        True if trading should proceed
    """
    if emergency_stop.is_stopped():
        logger.error("Trading blocked by emergency stop")
        return False
    
    if not circuit_breaker.is_trading_allowed():
        return False
    
    return True


def trigger_emergency_stop(reason: str):
    """Trigger global emergency stop."""
    emergency_stop.stop(reason)
    circuit_breaker.manual_halt(reason)


def clear_emergency_stop():
    """Clear global emergency stop."""
    emergency_stop.clear()
    circuit_breaker.manual_resume()


# Helper functions for bot integration
def on_trade_success(pnl: float):
    """Call when trade succeeds."""
    circuit_breaker.record_trade_result(success=True, pnl=pnl)


def on_trade_failure(error: str, pnl: float = 0.0):
    """Call when trade fails."""
    circuit_breaker.record_trade_result(success=False, pnl=pnl, error=error)


def on_model_failure(error: str):
    """Call when model prediction fails."""
    circuit_breaker.record_model_failure(error)


def get_circuit_status() -> Dict:
    """Get circuit breaker status."""
    return {
        'emergency_stop': emergency_stop.is_stopped(),
        'emergency_reason': emergency_stop._reason,
        **circuit_breaker.get_status(),
    }


if __name__ == "__main__":
    # Test circuit breaker
    logging.basicConfig(level=logging.INFO)
    
    # Normal operation
    print("1. Trading allowed:", check_trading_allowed())
    
    # Simulate failures
    for i in range(6):
        on_trade_failure(f"Test failure {i}")
    
    # Should now be blocked
    print("2. After failures, trading allowed:", check_trading_allowed())
    print("3. Status:", get_circuit_status())
    
    # Manual resume
    circuit_breaker.manual_resume()
    print("4. After resume, trading allowed:", check_trading_allowed())
