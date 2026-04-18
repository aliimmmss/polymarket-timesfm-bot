"""
Signal Aggregator — combines multiple signal sources into unified trading decision.

Signal Sources:
1. TPD (Token Price Disagreement) — how mispriced is the market vs BTC reality
2. CVD (Cumulative Volume Delta) — buying/selling pressure from Binance trades
3. OBI (Order Book Imbalance) — orderbook bid/ask pressure (-1 to +1)
4. TimesFM — 24-72hr BTC momentum forecast (updated hourly)
5. Time Decay — optimal trading window factor (peaks at 7.5 min remaining)
"""

import math
import time
import logging
from typing import Optional
from dataclasses import dataclass, asdict


logger = logging.getLogger(__name__)


@dataclass
class SignalComponent:
    """One signal component's contribution."""
    name: str
    score: float       # 0.0 to 1.0, where >0.5 = bullish
    direction: str     # "UP", "DOWN", or "NEUTRAL"
    weight: float      # How much this signal counts in the aggregate


@dataclass
class AggregatedSignal:
    """The final unified trading decision."""
    signal: str            # "BUY_UP", "BUY_DOWN", or "HOLD"
    confidence: float      # 0.0 to 1.0
    agreement_count: int   # How many of 5 signals agree
    components: dict       # name -> SignalComponent
    reasoning: str         # Human-readable explanation


class SignalAggregator:
    def __init__(self, config: dict = None):
        """
        Args:
            config: dict with 'weights' and 'thresholds'
                    weights: {'tpd': 0.30, 'cvd': 0.25, 'obi': 0.15, 'timesfm': 0.20, 'time_decay': 0.10}
                    thresholds: {'buy_up': 0.65, 'buy_down': 0.65, 'min_signals': 3}
        """
        if config is None:
            config = {}
        self.weights = config.get('weights', {
            'tpd': 0.30, 'cvd': 0.25, 'obi': 0.15,
            'timesfm': 0.20, 'time_decay': 0.10
        })
        self.thresholds = config.get('thresholds', {
            'buy_up': 0.65, 'buy_down': 0.65, 'min_signals': 3
        })
        self.timesfm_signal = None  # Updated hourly
        self.timesfm_updated = 0

    def update_timesfm(self, signal: dict):
        """
        Called once per hour with TimesFM forecast result.
        signal = {'direction': 'UP'|'DOWN', 'confidence': 0.0-1.0, 'up_prob': 0.0-1.0}
        """
        self.timesfm_signal = signal
        self.timesfm_updated = time.time()

    def evaluate(self, market_state: dict) -> AggregatedSignal:
        """
        Evaluate all signals and produce unified decision.

        Args:
            market_state = {
                'btc_price': float,         # Current BTC price
                'ptb': float,               # Price To Beat
                'up_price': float,          # Polymarket Up token price
                'down_price': float,        # Polymarket Down token price
                'time_remaining': int,      # Seconds remaining in window
                'window_duration': int,     # Total window duration (900)
                'cvd_1m': float,            # CVD last 1 minute
                'cvd_3m': float,            # CVD last 3 minutes
                'cvd_5m': float,            # CVD last 5 minutes
                'obi': float,               # Order Book Imbalance (-1 to +1)
            }

        Returns: AggregatedSignal dataclass
        """
        components = []

        # 1. TPD (Token Price Disagreement) - highest weight because it's the core mispricing signal
        tpd_comp = self._score_tpd(
            market_state['btc_price'] - market_state['ptb'],
            market_state['up_price'],
            market_state.get('down_price')
        )
        components.append(tpd_comp)

        # 2. CVD (Cumulative Volume Delta) - second highest weight, real-time momentum confirmation
        cvd_comp = self._score_cvd(
            market_state['cvd_1m'],
            market_state['cvd_3m'],
            market_state['cvd_5m']
        )
        components.append(cvd_comp)

        # 3. OBI (Order Book Imbalance) - real-time orderflow pressure
        obi_comp = self._score_obi(market_state.get('obi', 0.0))
        components.append(obi_comp)

        # 4. TimesFM momentum - longer-term trend confirmation, updated hourly
        timesfm_comp = self._score_timesfm()
        components.append(timesfm_comp)

        # 5. Time decay factor - optimal trading window scoring
        time_decay_comp = self._score_time_decay(
            market_state.get('time_remaining', 900),
            market_state.get('window_duration', 900)
        )
        components.append(time_decay_comp)

        # Aggregate all components into final decision
        return self._aggregate(components, market_state['btc_price'] - market_state['ptb'], 
                            market_state['up_price'])

    def _score_tpd(self, gap: float, up_price: float, down_price=None) -> SignalComponent:
        """
        Token Price Disagreement scoring.

        If BTC > PTB (gap > 0), Up token SHOULD be expensive.
        If it's still cheap, that's a mispricing signal.

        Score formula:
        - expected_up_price = 1 / (1 + math.exp(-gap / 50))
          (sigmoid mapping: gap=$50 → ~0.73, gap=$100 → ~0.88, gap=$20 → ~0.55)
        - mispricing = expected_up_price - up_price
        - If mispricing > 0.1: STRONG buy Up signal
        - score = min(1.0, max(0.0, 0.5 + mispricing * 2))
        - direction = "UP" if gap > 0 and up_price < expected_up_price
        - direction = "DOWN" if gap < 0 and down_price < expected_down_price
        - direction = "NEUTRAL" otherwise
        """
        # Calculate expected Up price using sigmoid function
        expected_up_price = 1.0 / (1.0 + math.exp(-gap / 50))

        # Expected Down price (symmetric) - calculate first to avoid scoping issues
        if down_price is not None:
            expected_down_price = 2.0 - expected_up_price  # If Up=0.73, then Down=1.27
        else:
            expected_down_price = 2.0 - expected_up_price  # Default to symmetric when unknown

        # Calculate mispricing for both sides (handle None gracefully)
        up_misprice = expected_up_price - up_price
        down_misprice = expected_down_price - down_price if down_price else None

        # Determine direction and score based on primary signal (Up side)
        if gap > 0:  # BTC above PTB, Up should be expensive
            if up_price < expected_up_price:  # But still cheap → bullish divergence!
                mispricing = min(1.0, max(0.0, 0.5 + up_misprice * 2))
                direction = "UP"
            elif up_price >= expected_up_price:  # Correctly priced or expensive
                mispricing = min(1.0, max(0.0, 0.5 - (up_price - expected_up_price) * 2))
                direction = "NEUTRAL"
            else:
                mispricing = min(1.0, max(0.0, 0.5 + up_misprice * 2))
                direction = "UP"
        elif gap < 0:  # BTC below PTB, Down should be expensive
            if down_price and down_price < expected_down_price:
                mispricing = min(1.0, max(0.0, 0.5 + abs(down_misprice) * 2))
                direction = "DOWN"
            elif down_price and down_price >= expected_down_price:
                mispricing = min(1.0, max(0.0, 0.5 - (down_price - expected_down_price) * 2))
                direction = "NEUTRAL"
            else:
                mispricing = min(1.0, max(0.0, 0.5 + abs(down_misprice) * 2))
                direction = "DOWN"
        else:  # Gap is zero (BTC = PTB), neutral signal
            mispricing = 0.5
            direction = "NEUTRAL"

        score = min(1.0, max(0.0, abs(mispricing)))

        logger.debug(f"TPD: gap=${gap:.2f}, up={up_price:.4f}, expected_up={expected_up_price:.3f}, "\
                   f"misprice={up_misprice:+.4f} → score={score:.3f}, dir={direction}")

        return SignalComponent(
            name="tpd",
            score=round(score, 4),
            direction=direction,
            weight=self.weights['tpd']
        )

    def _score_cvd(self, cvd_1m: float, cvd_3m: float, cvd_5m: float) -> SignalComponent:
        """
        CVD Momentum scoring.

        - Weighted: weighted_cvd = 0.2*cvd_1m + 0.3*cvd_3m + 0.5*cvd_5m
        - Normalize with tanh: score = 0.5 + 0.5 * math.tanh(weighted_cvd / 100)
          This maps CVD to 0-1: CVD=0 → 0.5, CVD=+100 → ~0.99, CVD=-100 → ~0.01
        - direction = "UP" if score > 0.55, "DOWN" if score < 0.45, else "NEUTRAL"
        """
        # Weighted combination of all time windows
        weighted_cvd = (0.2 * cvd_1m + 0.3 * cvd_3m + 0.5 * cvd_5m)

        # Normalize to 0-1 range using tanh for smooth S-curve mapping
        score = 0.5 + 0.5 * math.tanh(weighted_cvd / 100)

        # Determine direction based on momentum strength
        if score > 0.55:
            direction = "UP"
            reason = f"Weighted CVD={weighted_cvd:+.1f} → strong buying pressure ({score:.3f})"
        elif score < 0.45:
            direction = "DOWN"
            reason = f"Weighted CVD={weighted_cvd:+.1f} → strong selling pressure ({score:.3f})"
        else:
            # Near neutral, check if it's trending toward one side
            if abs(weighted_cvd) > 20:
                direction = "UP" if weighted_cvd > 0 else "DOWN"
                reason = f"Weighted CVD={weighted_cvd:+.1f} → mild {direction.lower()} pressure ({score:.3f})"
            else:
                direction = "NEUTRAL"
                reason = f"Weighted CVD={weighted_cvd:+.1f} ≈ neutral ({score:.3f})"

        logger.debug(f"CVD: 1m={cvd_1m:+.1f}, 3m={cvd_3m:+.1f}, 5m={cvd_5m:+.1f} → "\
                   f"weighted={weighted_cvd:+.1f} → score={score:.3f}, dir={direction}")

        return SignalComponent(
            name="cvd",
            score=round(score, 4),
            direction=direction,
            weight=self.weights['cvd']
        )

    def _score_obi(self, obi: float) -> SignalComponent:
        """
        Order Book Imbalance scoring.

        - OBI is already -1 to +1
        - score = (obi + 1) / 2  (maps to 0-1)
        - direction = "UP" if obi > 0.1, "DOWN" if obi < -0.1, else "NEUTRAL"
        """
        # Map OBI from [-1, +1] → [0, 1]
        score = (obi + 1) / 2

        # Determine direction based on meaningful imbalance threshold
        if abs(obi) > 0.3:  # Use 0.3 instead of 0.1 for more reliable signal
            direction = "UP" if obi > 0 else "DOWN"
            reason = f"OBI={obi:+.2f} → strong {'bullish' if obi > 0 else 'bearish'} orderbook ({score:.3f})"
        elif abs(obi) > 0.1:
            direction = "UP" if obi > 0 else "DOWN"
            reason = f"OBI={obi:+.2f} → mild {'bullish' if obi > 0 else 'bearish'} orderbook ({score:.3f})"
        else:
            direction = "NEUTRAL"
            reason = f"OBI={obi:+.4f} ≈ balanced ({score:.3f})"

        logger.debug(f"OBI: {obi:+.2f} → score={(obi+1)/2:.3f}, dir={direction}")

        return SignalComponent(
            name="obi",
            score=round(score, 4),
            direction=direction,
            weight=self.weights['obi']
        )

    def _score_timesfm(self) -> SignalComponent:
        """
        TimesFM momentum scoring.

        - If no TimesFM signal: return NEUTRAL, score=0.5
        - score = timesfm_confidence if direction is "UP", else 1 - confidence
        - direction from cached timesfm_signal
        """
        # Check for available TimesFM data
        if self.timesfm_signal is None or \
           (abs(time.time() - self.timesfm_updated) > 3600 and not self._has_recent_timesfm()):
            return SignalComponent(
                name="timesfm",
                score=0.5,      # Neutral when no data
                direction="NEUTRAL",
                weight=self.weights['timesfm']
            )

        signal = self.timesfm_signal

        if signal.get('direction') == 'UP':
            score = signal.get('confidence', 0.5)
            reason = f"TimesFM forecasts UP with {signal.get('up_prob', 0):.1%} probability ({score:.3f})"
        elif signal.get('direction') == 'DOWN':
            # Invert confidence for bearish signals
            score = 1 - (signal.get('confidence', 0.5))
            reason = f"TimesFM forecasts DOWN with {signal.get('down_prob', 1-signal.get('up_prob', 0)): .1%} probability ({score:.3f})"
        else:
            # Unknown direction, treat as neutral
            score = signal.get('confidence', 0.5) if 'confidence' in signal else 0.5
            reason = f"TimesFM data available but unclear direction (defaulting to {signal})"

        logger.debug(f"TimesFM: dir={signal.get('direction', 'unknown')}, conf={score:.3f}")

        return SignalComponent(
            name="timesfm",
            score=round(score, 4),
            direction=signal.get('direction', 'NEUTRAL'),
            weight=self.weights['timesfm']
        )

    def _has_recent_timesfm(self) -> bool:
        """Check if TimesFM signal is recent (within last hour)."""
        return abs(time.time() - self.timesfm_updated) < 3600 or \
               (self.timesfm_signal and 'direction' in str(self.timesfm_signal))

    def _score_time_decay(self, time_remaining: int, window_duration: int = 900) -> SignalComponent:
        """
        Time decay factor.

        - Optimal trading window: 300-600s remaining (5-10 min in)
        - score = 1.0 - abs(time_remaining - 450) / 450
        - Peaks at 450s (7.5 min) → score = 1.0
        - At 0s or 900s → score = 0.0
        - direction always "NEUTRAL" (time doesn't indicate direction)
        """
        if time_remaining <= 0 or time_remaining >= window_duration:
            score = 0.0
        else:
            # Calculate distance from optimal point (450 seconds in, i.e., 7.5 min remaining)
            time_in_window = max(180, min(window_duration - time_remaining, 900))
            optimal_time = 360 + 90  # 300-600s range

            if abs(time_in_window - optimal_time) > 270:  # Beyond the useful window
                score = max(0.01, min(0.99, (abs(time_in_window - optimal_time) / 540) ** 2))
            else:
                distance_from_optimal = abs(time_in_window - optimal_time)
                max_distance = min(optimal_time, (window_duration - optimal_time))

                # Use sigmoid-like curve for smooth transition
                if max_distance > 0:
                    normalized_dist = distance_from_optimal / max_distance
                    score = 1.0 - (normalized_dist ** 2) * self.weights['time_decay']
                else:
                    score = 1.0

        direction = "NEUTRAL"

        logger.debug(f"Time decay: remaining={time_remaining}s, in_window={time_in_window}s → score={score:.3f}")

        return SignalComponent(
            name="time_decay",
            score=round(score, 4),
            direction=direction,
            weight=self.weights['time_decay']
        )

    def _aggregate(self, components: list, gap: float, up_price: float) -> AggregatedSignal:
        """
        Weighted aggregation of all component scores.

        Steps:
        1. Count directional agreements (ignore NEUTRAL)
           - Count how many say UP, how many say DOWN
        2. Calculate weighted average score:
           weighted_score = sum(comp.score * comp.weight for comp in components)
        3. Determine direction: majority of non-neutral signals
        4. Apply thresholds:
           - If agreement_count < min_signals: signal = "HOLD"
           - If direction is UP and weighted_score >= buy_up threshold: "BUY_UP"
           - If direction is DOWN and weighted_score >= buy_down threshold: "BUY_DOWN"
           - Otherwise: "HOLD"
        5. Build reasoning string, e.g.:
           "BUY_UP: TPD(bullish,0.85) + CVD(bullish,0.72) + TimesFM(bullish,0.72) agree.
            Gap=$33 but Up only $0.62. Strong buying pressure confirms."
        """
        # Initialize counters - these count how many signals say UP vs DOWN
        up_count = 0
        down_count = 0
        direction_parts = []

        total_weight = sum(self.weights.values())

        # Count each component (components is a list, not dict)
        for comp in components:
            name = getattr(comp, 'name', f"component_{list(components).index(comp)+1}")
            if comp.direction == "UP":
                up_count += 1
                direction_parts.append(f"{name}(bullish,{comp.score:.2f})")
            elif comp.direction == "DOWN":
                down_count += 1
                direction_parts.append(f"{name}(bearish,{comp.score:.2f})")

        non_neutral_count = up_count + down_count
        agreement_count = max(up_count, down_count)

        # Weighted average confidence - MUST calculate BEFORE use!
        weighted_score = sum(comp.score * comp.weight for comp in components)
        overall_confidence = (weighted_score / total_weight) if total_weight > 0 else 0.5
        overall_confidence = min(1.0, max(0.0, overall_confidence))

        # Determine signal - MUST define final_signal before use!
        min_signals = self.thresholds['min_signals']
        
        if non_neutral_count < min_signals:
            signal = "HOLD"
        elif up_count > down_count:
            if overall_confidence >= self.thresholds['buy_up']:
                signal = "BUY_UP"
            else:
                signal = "HOLD"
        elif down_count > up_count:
            down_score = 1.0 - overall_confidence
            if down_score >= self.thresholds['buy_down']:
                signal = "BUY_DOWN"
            else:
                signal = "HOLD"
        else:
            signal = "HOLD"

        # Build reasoning - MUST define final_signal before use!
        if signal == "HOLD":
            if non_neutral_count < min_signals:
                reasoning = f"HOLD: Only {non_neutral_count} signals agree (need {min_signals}). " + ", ".join(direction_parts)
            else:
                reasoning = f"HOLD: Confidence too low. " + ", ".join(direction_parts)
        elif signal == "BUY_UP":
            reasoning = f"BUY_UP: " + " + ".join(direction_parts) + f". Gap=${gap:.0f} Up={up_price:.2f}."
        else:  # BUY_DOWN
            reasoning = f"BUY_DOWN: " + " + ".join(direction_parts) + f". Gap=${gap:.0f}."

        logger.info(f"Aggregated: signal={signal}, confidence={overall_confidence:.3f}, "\
                   f"agreement={agreement_count}/{len(components)}, reasoning='{reasoning}'")

        return AggregatedSignal(
            signal, 
            round(overall_confidence, 4), 
            agreement_count, 
            {comp.name: comp for comp in components},
            reasoning
        )
