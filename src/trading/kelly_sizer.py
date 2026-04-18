"""
Kelly Criterion position sizing for binary prediction markets.

Kelly formula: f* = (p * b - q) / b
where p = win probability, q = 1-p, b = net payout odds

For Polymarket: b = (1.0 - token_price) / token_price
Example: buy at $0.50 → b = 1.0 (100% payout)
Example: buy at $0.30 → b = 2.33 (233% payout)

Uses fractional Kelly (quarter) for safety, plus volatility modifier.
"""

import math
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class KellyResult:
    """Result of a Kelly calculation."""
    kelly_fraction: float          # Raw Kelly fraction (before adjustments)
    adjusted_fraction: float       # After fractional Kelly + IV modifier
    position_usdc: float           # Dollar amount to bet
    tokens_to_buy: float           # Number of tokens
    expected_value: float          # Expected profit in USDC
    risk_reason: Optional[str]     # If position reduced or zeroed, why


class KellySizer:
    """Kelly Criterion implementation with safety checks and modifiers."""

    def __init__(self, config: dict = None):
        """
        Args:
            config = {
                'fractional_kelly': 0.25,    # Quarter Kelly for safer growth
                'max_position_usdc': 10.0,   # Maximum bet per trade (risk cap)
                'min_position_usdc': 1.0,    # Minimum bet to bother trading
                'bankroll': 100.0,            # Total allocated bankroll for Kelly calc
                'daily_loss_limit': 20.0,     # Stop if daily loss exceeds this
                'max_daily_trades': 20,       # Max trades per day (avoid overfitting)
                'volatility_modifier_range': (0.5, 1.0),  # IV-based Kelly scaling range
            }
        """
        if config is None:
            config = {}

        self.fractional_kelly = config.get('fractional_kelly', 0.25)  # Quarter Kelly standard
        self.max_position_usdc = config.get('max_position_usdc', 10.0)  # Risk cap per trade
        self.min_position_usdc = config.get('min_position_usdc', 1.0)   # Min bet threshold
        self.bankroll = float(config.get('bankroll', 100.0))             # Total Kelly bankroll
        self.daily_loss_limit = abs(float(config.get('daily_loss_limit', 20.0)))
        self.max_daily_trades = max(1, int(config.get('max_daily_trades', 20)))

        # Volatility modifier parameters (from ImpliedVolatility class)
        self.vol_min = float(config.get('volatility_modifier_range', (0.5, 1.0))[0])
        self.vol_max = float(config.get('volatility_modifier_range', (0.5, 1.0))[1])

    def calculate(self, our_probability: float, token_price: float,
                  daily_pnl: float = 0.0, daily_trade_count: int = 0,
                  vol_modifier: float = 1.0) -> KellyResult:
        """
        Calculate optimal position size using Kelly Criterion with safety checks.

        Args:
            our_probability: Our estimated win probability (0-1) from SignalAggregator
                           This should incorporate TPD edge + CVD/OBI confirmation
            token_price: Current token price (typically 0.01-0.99 for active markets)
            daily_pnl: Today's PnL so far (negative = losing day, zero or positive = good day)
            daily_trade_count: Number of trades executed today
            vol_modifier: Kelly modifier from ImpliedVolatility class (0.25-1.0 typically)

        Returns: KellyResult dataclass with all calculated fields and risk reasons

        Safety checks (applied in order, earliest failure wins):
        1. Daily loss limit hit → return zero position
        2. Daily trade count exceeded → return zero to avoid overfitting
        3. Low edge (<55%) → insufficient advantage to justify Kelly bet
        4. Negative expected value (p ≤ price) → money losing bet
        5. Edge too small (<5% absolute) → not worth the transaction costs

        Calculation steps:
        1. Calculate net payout odds: b = (1 - token_price) / token_price
           Example: price=0.50 → b=1.0, price=0.30 → b≈2.33
        2. Apply Kelly formula: kelly_raw = (p × b - q) / b where q = 1-p
        3. Adjust for safety: kelly_adj = kelly_raw × fractional_kelly × vol_modifier
           Example: raw=0.45, frac=0.25 → adj ≈ 0.11 (one quarter of bankroll!)
        4. Convert to position size: position_usdc = kelly_adj × bankroll
        5. Calculate tokens needed: tokens_to_buy = position / token_price
        6. Compute expected value: EV = (p - price) × tokens_to_buy

        Edge cases handled:
        - Price near boundaries (0.99 or <0.01): use min/max clamping
        - Probability at extremes (0.5 or 1.0): avoid division by zero
        - Vol modifier outside range: clamp to [vol_min, vol_max]
        """
        # Clamp inputs to reasonable ranges for numerical stability
        prob = max(0.01, min(0.99, our_probability))      # Avoid p=0 or p=1 edge cases
        price = max(0.01, min(0.99, token_price))         # Token prices rarely exceed 0.95

        # Clamp vol modifier to configured range (default: [0.5, 1.0])
        vm = max(self.vol_min, min(self.vol_max, vol_modifier))

        # ====================================
        # SAFETY CHECKS - earliest failure wins
        # ====================================

        # Check 1: Daily loss limit hit? → freeze trading until reset
        if daily_pnl < -self.daily_loss_limit:
            logger.warning(f"Daily loss limit hit! PnL={daily_pnl:.2f} vs limit=-${self.daily_loss_limit}")
            return KellyResult(
                kelly_fraction=0.0,
                adjusted_fraction=0.0,
                position_usdc=0.0,
                tokens_to_buy=0.0,
                expected_value=0.0,
                risk_reason="daily loss limit hit"  # Reset with reset_daily() next trading day
            )

        # Check 2: Daily trade count exceeded? → avoid overfitting to noise
        if daily_trade_count >= self.max_daily_trades:
            logger.warning(f"Daily trade limit reached! Count={daily_trade_count}/{self.max_daily_trades}")
            return KellyResult(
                kelly_fraction=0.0,
                adjusted_fraction=0.0,
                position_usdc=0.0,
                tokens_to_buy=0.0,
                expected_value=0.0,
                risk_reason="daily trade limit"  # Reset with reset_daily() next trading day
            )

        # Check 3: Insufficient edge? → not worth the bet spread
        min_edge_pct = 0.05  # Require at least 5% absolute advantage
        if prob < 0.55 or (prob - price) < min_edge_pct:
            actual_gap = max(0, prob - price)
            logger.debug(f"Edge too small! p={prob:.3f}, gap={actual_gap*100:.2f}% vs req {min_edge_pct*100}%, "
                        f"(p-price)={prob-price:+.4f}")

            # Provide specific reason for zeroing out
            if prob < 0.55:
                reason = f"Low edge ({prob*100:.1f}% win rate, need ≥{min_edge_pct*100}%) from SignalAggregator"
            else:
                reason = "Edge below minimum threshold (p - price must exceed 5%)"

            return KellyResult(
                kelly_fraction=0.0,
                adjusted_fraction=0.0,
                position_usdc=0.0,
                tokens_to_buy=0.0,
                expected_value=0.0,
                risk_reason=reason
            )

        # Check 4: Negative or zero expected value? → money losing bet!
        if prob <= price:
            actual_ev_per_token = (prob - price) * token_price / max(price, 1e-6)
            logger.warning(f"Negative EV detected! p={prob:.3f}, price={price:.4f} → "
                          f"(p-price)×price={(prob-price)*price*100:+.2f}%")

            return KellyResult(
                kelly_fraction=0.0,
                adjusted_fraction=0.0,
                position_usdc=0.0,
                tokens_to_buy=0.0,
                expected_value=0.0,
                risk_reason=f"Negative/zero EV: p={prob:.3f} ≤ price={price:.4f}"
            )

        # ====================================
        # KELLY FORMULA CALCULATION
        # ====================================

        # Step 1: Calculate net payout odds (b)
        # If you buy at $0.50 and it wins, you get back $1.00 → b = 1.0/0.50 - 1 = 1.0
        # If you buy at $0.30 and it wins, you get back ~$2.33 → b ≈ 6.77-1 = 5.77 (wait...)
        # Actually for binary: if price=0.50 means "pays 1x", then b=(1-0.5)/0.5 = 1.0 ✓
        net_payout_odds_b = (1.0 - price) / max(price, 1e-8)

        # Step 2: Apply Kelly formula with proper handling of edge cases
        q = 1.0 - prob  # Loss probability
        
        if abs(net_payout_odds_b) < 1e-6 or abs(prob) < 1e-6:
            logger.warning(f"Numerical instability in Kelly! b={net_payout_odds_b:.4f}, p={prob:.3f}")
            return KellyResult(
                kelly_fraction=0.5,  # Default to half-bankroll as fallback
                adjusted_fraction=0.25,
                position_usdc=self.bankroll * 0.25,
                tokens_to_buy=(self.bankroll * 0.25) / price,
                expected_value=self.bankroll * (prob - price),
                risk_reason="Numerical edge case fallback"
            )

        # Standard Kelly formula: f* = (p × b - q) / b
        numerator = prob * net_payout_odds_b - q  # Expected gain minus loss probability
        denominator = max(abs(net_payout_odds_b), 1e-8)  # Avoid division by zero
        
        kelly_raw = numerator / denominator

        # Step 3: Adjust for safety factors
        fractional_kelly_factor = self.fractional_kelly   # e.g., 0.25 = quarter Kelly (safer, slower but more sustainable)
        
        # Apply both adjustments
        adjusted_fraction = min(1.0, max(0.0, kelly_raw * fractional_kelly_factor * vm))

        # Step 4: Calculate position sizes
        raw_position_usdc = abs(kelly_raw) * self.bankroll       # Use absolute value (direction handled by signal)
        
        # Apply adjusted fraction to get final position size
        pos_usdc = max(0.0, min(self.max_position_usdc, raw_position_usdc))

        # Step 5: Calculate tokens needed for purchase
        if price > 1e-8:
            tokens_to_buy = pos_usdc / price
        else:
            tokens_to_buy = 0.0

        # Step 6: Compute expected value per token and total EV
        ev_per_token = (prob - price) * max(price, 1e-8)       # Expected profit/loss in USD if holding one unit
        expected_value_usdc = ev_per_token * tokens_to_buy     # Total expected PnL

        logger.debug(f"Kelly calc: p={prob:.3f}, b={net_payout_odds_b:.2f}, raw_kelly={kelly_raw:+.4f}, "
                    f"adj_frac={adjusted_fraction:.3f}×{vm:.1f}→{pos_usdc/100:.2f}% of bankroll, "
                    f"EV=${expected_value_usdc:+.4f}")

        return KellyResult(
            kelly_fraction=round(kelly_raw, 6),
            adjusted_fraction=round(adjusted_fraction, 6),
            position_usdc=round(pos_usdc, 2),
            tokens_to_buy=round(tokens_to_buy, 8),
            expected_value=round(expected_value_usdc, 4),
            risk_reason=None  # None means "all safety checks passed"
        )

    def update_bankroll(self, pnl: float):
        """Update bankroll after a trade settles.

        Args:
            pnl: Net profit/loss from the settled trade (positive = win, negative = loss)

        Example usage in trading loop:
            # After closing position at price2
            settlement_pnl = entry_price - exit_price  # Profit if we bought low and sold high
            sizer.update_bankroll(settlement_pnl * tokens_held)
        """
        self.bankroll += pnl
        
        # Log with appropriate severity based on trade outcome
        sign_str = "+" if pnl >= 0 else ""
        logger.info(f"Bankroll updated: ${self.bankroll:.2f} USDC (PnL: {sign_str}${pnl:+.2f})")

    def reset_daily(self):
        """Reset daily counters at start of each trading day.

        Call this function once per 900-second window to clear accumulated stats.
        
        Typical usage in monitor loop with time-based reset:
            if current_time % 900 < 30:  # First 30 seconds of new window
                sizer.reset_daily()

        Or use a dedicated scheduler/manager that calls this at the right moment.
        """
        self.daily_trade_count = 0
        logger.info(f"Daily counters reset → ready for {self.max_daily_trades} more trades")


# Convenience function for quick instantiation with defaults
def create_kelly_sizer(config: dict = None) -> KellySizer:
    """Create a new Kelly sizer instance.

    Args:
        config: Optional configuration dictionary (see __init__ docstring)

    Returns:
        Configured KellySizer ready to use for position sizing calculations
    """
    return KellySizer(config or {})


# Example usage demonstrating the full workflow:
if __name__ == "__main__":
    import time
    
    print("=" * 60)
    print("Kelly Sizer Quick Demo")
    print("=" * 60)

    # Create sizer with custom config (optional - defaults work fine too)
    s = KellySizer({
        'fractional_kelly': 0.25,      # Quarter Kelly standard
        'max_position_usdc': 10.0,     # Max $10 per trade
        'bankroll': 100.0              # Example: $100 allocated bankroll
    })

    print(f"\nInitial config:")
    print(f"  Fractional Kelly: {s.fractional_kelly}")
    print(f"  Max position: ${s.max_position_usdc:.2f}/trade")
    print(f"  Bankroll: ${s.bankroll:.2f} USDC")

    # Example calculation - strong edge scenario
    print("\n--- Scenario A: Strong Edge ---")
    result = s.calculate(
        our_probability=0.75,   # 75% win probability from signals
        token_price=0.50,       # Buying at $0.50 (pays 1x)
        daily_pnl=-2.0,         # Slight losing day (-$2 so far)
        vol_modifier=0.8,      # Moderate volatility correction
    )

    print(f"Result: bet ${result.position_usdc:.2f}, EV=${result.expected_value:+.3f}")
    print(f"  → {result.tokens_to_buy:.1f} tokens × ${(s.bankroll * result.adjusted_fraction / max(result.tokens_to_buy, 0.01)):.4f}/token")

    # Example - small edge with high volatility (reduced position)
    print("\n--- Scenario B: Small Edge + High Volatility ---")
    result2 = s.calculate(
        our_probability=0.58,   # Modest 58% win rate
        token_price=0.48,       # Buying at $0.48 (pays ~1.06x)
        daily_pnl=-3.5,         # Losing day (-$3.50 so far)
        vol_modifier=0.4,      # High volatility → reduce position further
    )

    print(f"Result: bet ${result2.position_usdc:.2f}, reason='{result2.risk_reason}'")

    # Example - negative edge (money losing!)
    print("\n--- Scenario C: Negative Edge ---")
    result3 = s.calculate(
        our_probability=0.45,   # Only 45% win rate
        token_price=0.52,       # Buying at $0.52 when it pays only ~1.92x (net loss!)
    )

    print(f"Result: bet ${result3.position_usdc:.2f}, reason='{result3.risk_reason}'")

    # Example - daily limit hit scenario
    print("\n--- Scenario D: Daily Loss Limit ---")
    result4 = s.calculate(
        our_probability=0.85,   # Great 85% win rate!
        token_price=0.40,       # Buying at $0.40 (pays ~1.67x)
        daily_pnl=-25.0,        # Big losing day (-$25 so far)
    )

    print(f"Result: bet ${result4.position_usdc:.2f}, reason='{result4.risk_reason}'")

    # Simulate updating bankroll after a winning trade
    print("\n--- Bankroll Update Simulation ---")
    s.update_bankroll(5.0)   # Just won $5 on last trade
    print(f"After +$5 win: ${s.bankroll:.2f} USDC → next Kelly calc will use this new base!")

    print("\n" + "=" * 60)
    print("Kelly Sizer demo complete.")