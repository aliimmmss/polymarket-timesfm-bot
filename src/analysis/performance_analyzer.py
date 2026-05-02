"""
Performance Analyzer — computes statistics and optimizes strategy parameters.

Analyzes trade journal and observation CSV to:
- Compute win rates per signal type (A/B/C)
- Find optimal threshold ranges (gap, CVD, OBI, time)
- Generate candidate parameter sets via grid search
- Backtest candidates on historical data
"""

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from dataclasses import dataclass

logger = logging.getLogger(__name__)

OBSERVATIONS_DIR = Path('data/observations')
TRADE_JOURNAL_PATH = Path.home() / 'trading' / 'trading-log.yaml'


@dataclass
class Trade:
    """Single trade with outcome."""
    market_slug: str
    signal: str  # BUY_UP, BUY_DOWN, HOLD
    confidence: float
    signal_strength: float
    gap: float
    up_price: float
    cvd_5m: float
    obi: float
    time_remaining: int
    outcome: Optional[str]  # win/loss/push/None
    timestamp: Optional[datetime]


class PerformanceAnalyzer:
    """Analyzes trading performance and discovers optimal parameters."""

    def __init__(self, data_dir: str = 'data'):
        self.data_dir = Path(data_dir)
        self.trades: List[Trade] = []
        self.observations: List[Dict] = []

    def load_trades_from_journal(self) -> int:
        """Load resolved trades from YAML trade journal."""
        if not TRADE_JOURNAL_PATH.exists():
            logger.warning(f"Trade journal not found: {TRADE_JOURNAL_PATH}")
            return 0

        loaded = 0
        with open(TRADE_JOURNAL_PATH, 'r') as f:
            docs = f.read().split('\n---\n')

            for doc in docs:
                if not doc.strip():
                    continue
                try:
                    entry = yaml.safe_load(doc)
                    if not isinstance(entry, dict):
                        continue

                    outcome = entry.get('outcome')
                    if not outcome:
                        continue  # skip unresolved

                    trade = Trade(
                        market_slug=entry.get('market_slug', ''),
                        signal=entry.get('signal', 'HOLD'),
                        confidence=entry.get('confidence', 0.0),
                        signal_strength=entry.get('signal_strength', 0.0),
                        gap=entry.get('gap', 0.0),
                        up_price=entry.get('up_token_price', 0.0),
                        cvd_5m=entry.get('cvd_5m', 0.0),
                        obi=entry.get('obi', 0.0),
                        time_remaining=entry.get('time_remaining_sec', 900),
                        outcome=outcome,
                        timestamp=entry.get('timestamp')
                    )
                    self.trades.append(trade)
                    loaded += 1
                except yaml.YAMLError:
                    continue

        logger.info(f"Loaded {loaded} resolved trades from journal")
        return loaded

    def load_observations_from_csv(self) -> int:
        """Load all observation CSV files."""
        obs_dir = self.data_dir / 'observations'
        if not obs_dir.exists():
            return 0

        loaded = 0
        for csv_file in sorted(obs_dir.glob('observations_*.csv')):
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.observations.append(row)
                    loaded += 1

        logger.info(f"Loaded {loaded} observations from CSV")
        return loaded

    def compute_signal_performance(self) -> Dict[str, Dict]:
        """Compute win/loss stats per signal type."""
        stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pushes': 0, 'pnl': 0.0})

        for trade in self.trades:
            sig = trade.signal
            if trade.outcome == 'win':
                stats[sig]['wins'] += 1
                stats[sig]['pnl'] += 5.0
            elif trade.outcome == 'loss':
                stats[sig]['losses'] += 1
                stats[sig]['pnl'] -= 5.0
            elif trade.outcome == 'push':
                stats[sig]['pushes'] += 1

        result = {}
        for sig, data in stats.items():
            total = data['wins'] + data['losses'] + data['pushes']
            win_rate = data['wins'] / total if total > 0 else 0.0
            result[sig] = {
                'win_rate': round(win_rate, 3),
                'num_trades': total,
                'wins': data['wins'],
                'losses': data['losses'],
                'pushes': data['pushes'],
                'total_pnl': round(data['pnl'], 2)
            }

        return result

    def find_optimal_thresholds(self) -> Dict[str, float]:
        """Grid-search thresholds that maximize win rate."""
        best_score = -1
        best_params = {}

        signal_trades = [t for t in self.trades if t.signal in ('BUY_UP', 'BUY_DOWN')]
        if not signal_trades:
            logger.warning("No signal trades to optimize")
            return {}

        # Gap threshold bins
        gap_bins = [(0, 20), (20, 40), (40, 60), (60, 100), (100, 200)]
        for low, high in gap_bins:
            bin_trades = [t for t in signal_trades if low <= t.gap < high]
            if len(bin_trades) < 3:
                continue
            wins = sum(1 for t in bin_trades if t.outcome == 'win')
            wr = wins / len(bin_trades)
            if wr > best_score:
                best_score = wr
                best_params['gap_threshold'] = low

        # CVD threshold
        cvd_candidates = [20, 30, 50, 70, 100]
        best_cvd_score = -1
        for cvd_th in cvd_candidates:
            high_cvd = [t for t in signal_trades if abs(t.cvd_5m) >= cvd_th]
            if len(high_cvd) < 3:
                continue
            wins = sum(1 for t in high_cvd if t.outcome == 'win')
            wr = wins / len(high_cvd)
            if wr > best_cvd_score:
                best_cvd_score = wr
                best_params['cvd_threshold'] = cvd_th

        # OBI threshold
        obi_candidates = [0.1, 0.2, 0.3, 0.4, 0.5]
        best_obi_score = -1
        for obi_th in obi_candidates:
            high_obi = [t for t in signal_trades if t.obi >= obi_th]
            if len(high_obi) < 3:
                continue
            wins = sum(1 for t in high_obi if t.outcome == 'win')
            wr = wins / len(high_obi)
            if wr > best_obi_score:
                best_obi_score = wr
                best_params['obi_threshold'] = obi_th

        # Time remaining
        time_bins = [(0, 180), (180, 300), (300, 600), (600, 900)]
        best_time_score = -1
        for low, high in time_bins:
            bin_trades = [t for t in signal_trades if low <= t.time_remaining < high]
            if len(bin_trades) < 3:
                continue
            wins = sum(1 for t in bin_trades if t.outcome == 'win')
            wr = wins / len(bin_trades)
            if wr > best_time_score:
                best_time_score = wr
                best_params['time_window'] = (low, high)

        logger.info(f"Optimal thresholds discovered: {best_params}")
        return best_params

    def generate_candidate_strategies(self, optimal: Dict[str, float], n: int = 3) -> List[Dict]:
        """Generate n candidate strategy configs based on optimal thresholds."""
        strategies = []

        strategies.append({
            'name': 'Conservative',
            'weights': {'tpd': 0.40, 'cvd': 0.35, 'obi': 0.15, 'time_decay': 0.10},
            'thresholds': {'buy_up': 0.70, 'buy_down': 0.70, 'min_signals': 4},
            'signal_a_gap': optimal.get('gap_threshold', 30) + 10,
            'signal_a_max_price': 0.50,
            'signal_b_gap': optimal.get('gap_threshold', 50) + 20,
            'signal_c_cvd': optimal.get('cvd_threshold', 50),
            'signal_c_obi': optimal.get('obi_threshold', 0.30),
        })

        strategies.append({
            'name': 'Aggressive',
            'weights': {'tpd': 0.30, 'cvd': 0.30, 'obi': 0.25, 'time_decay': 0.15},
            'thresholds': {'buy_up': 0.60, 'buy_down': 0.60, 'min_signals': 3},
            'signal_a_gap': max(20, optimal.get('gap_threshold', 30) - 5),
            'signal_a_max_price': 0.60,
            'signal_b_gap': max(40, optimal.get('gap_threshold', 50) - 10),
            'signal_c_cvd': optimal.get('cvd_threshold', 50) - 10,
            'signal_c_obi': optimal.get('obi_threshold', 0.30) - 0.05,
        })

        strategies.append({
            'name': 'Balanced',
            'weights': {'tpd': 0.35, 'cvd': 0.30, 'obi': 0.20, 'time_decay': 0.15},
            'thresholds': {'buy_up': 0.65, 'buy_down': 0.65, 'min_signals': 3},
            'signal_a_gap': optimal.get('gap_threshold', 30),
            'signal_a_max_price': 0.55,
            'signal_b_gap': optimal.get('gap_threshold', 50),
            'signal_c_cvd': optimal.get('cvd_threshold', 50),
            'signal_c_obi': optimal.get('obi_threshold', 0.30),
        })

        return strategies[:n]

    def summarize(self) -> Dict:
        """Full performance summary."""
        summary = {
            'total_trades': len(self.trades),
            'signal_performance': self.compute_signal_performance(),
            'optimal_thresholds': self.find_optimal_thresholds(),
            'candidate_strategies': self.generate_candidate_strategies(
                self.find_optimal_thresholds()
            )
        }
        return summary


def main():
    logging.basicConfig(level=logging.INFO)
    analyzer = PerformanceAnalyzer()

    logger.info("Loading data...")
    analyzer.load_trades_from_journal()
    analyzer.load_observations_from_csv()

    logger.info("Generating summary...")
    summary = analyzer.summarize()

    print("\n" + "=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)
    print(f"Total resolved trades: {summary['total_trades']}")
    print("\nSignal Performance:")
    for sig, stats in summary['signal_performance'].items():
        print(f"  {sig}: {stats['wins']}W/{stats['losses']}L/{stats['pushes']}P "
              f"({stats['win_rate']*100:.1f}% win, P&L=${stats['total_pnl']:.2f})")

    print("\nOptimal Thresholds:")
    for k, v in summary['optimal_thresholds'].items():
        print(f"  {k}: {v}")

    print("\nCandidate Strategies:")
    for strat in summary['candidate_strategies']:
        print(f"\n  [{strat['name']}]")
        for k, v in strat.items():
            if k != 'name':
                print(f"    {k}: {v}")


if __name__ == '__main__':
    main()
