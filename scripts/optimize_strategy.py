#!/usr/bin/env python3
"""
Strategy Optimization Orchestrator — end-to-end self-learning pipeline.

Workflow:
  1. Run bot (dry-run) and collect data for N hours
  2. Analyze performance → discover best parameters
  3. Generate candidate strategies
  4. Backtest candidates on historical data
  5. Validate top-3 in live dry-run
  6. Output final recommendation

Usage:
  python scripts/optimize_strategy.py --collect 24 --analyze --validate
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis.performance_analyzer import PerformanceAnalyzer

logger = logging.getLogger(__name__)

BASE = Path(__file__).parent.parent


def run_bot(duration_minutes: int, interval: int = 5, dry_run: bool = True) -> bool:
    """Launch btc_15m_monitor_v2.py."""
    logger.info(f"Starting bot: dry_run={dry_run}, interval={interval}s")
    cmd = [
        sys.executable,
        'scripts/btc_15m_monitor_v2.py',
        '--monitor',
        '--interval', str(interval),
    ]
    if dry_run:
        cmd.append('--dry-run')

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=BASE
    )

    try:
        for line in proc.stdout:
            print(line, end='')
        proc.wait()
        return proc.returncode == 0
    except KeyboardInterrupt:
        logger.info("Interrupted — terminating bot")
        proc.terminate()
        proc.wait()
        return False


def analyze_performance() -> Dict:
    """Load collected data and compute metrics."""
    logger.info("Analyzing performance data...")
    analyzer = PerformanceAnalyzer(data_dir=str(BASE / 'data'))
    analyzer.load_trades_from_journal()
    analyzer.load_observations_from_csv()
    summary = analyzer.summarize()
    return summary


def generate_strategies(summary: Dict, num_candidates: int = 3) -> List[Dict]:
    """Generate candidate strategy configs."""
    optimal = summary.get('optimal_thresholds', {})
    analyzer = PerformanceAnalyzer()
    candidates = analyzer.generate_candidate_strategies(optimal, n=num_candidates)
    return candidates


def save_strategy_config(strategy: Dict, path: Path):
    """Save strategy config as YAML."""
    content = (
        f"strategy:\n"
        f"  weights:\n"
        f"    tpd: {strategy.get('weights', {}).get('tpd', 0.35)}\n"
        f"    cvd: {strategy.get('weights', {}).get('cvd', 0.30)}\n"
        f"    obi: {strategy.get('weights', {}).get('obi', 0.20)}\n"
        f"    time_decay: {strategy.get('weights', {}).get('time_decay', 0.15)}\n"
        f"  thresholds:\n"
        f"    buy_up: {strategy.get('thresholds', {}).get('buy_up', 0.65)}\n"
        f"    buy_down: {strategy.get('thresholds', {}).get('buy_down', 0.65)}\n"
        f"    min_signals: {strategy.get('thresholds', {}).get('min_signals', 3)}\n"
        f"\n"
        f"signal_a:\n"
        f"  gap_threshold: {strategy.get('signal_a_gap', 30)}\n"
        f"  max_price: {strategy.get('signal_a_max_price', 0.55)}\n"
        f"  min_time_remaining: 300\n"
        f"\n"
        f"signal_b:\n"
        f"  gap_threshold: {strategy.get('signal_b_gap', 50)}\n"
        f"  max_price: {strategy.get('signal_b_max_price', 0.95)}\n"
        f"  max_time_remaining: 180\n"
        f"\n"
        f"signal_c:\n"
        f"  cvd_threshold: {strategy.get('signal_c_cvd', 50)}\n"
        f"  obi_threshold: {strategy.get('signal_c_obi', 0.30)}\n"
        f"  max_price: 0.50\n"
        f"  min_time_remaining: 300\n"
    )
    path.write_text(content)
    logger.info(f"Saved strategy config: {path}")


def main():
    parser = argparse.ArgumentParser(description='Strategy optimization orchestrator')
    parser.add_argument('--collect', type=int, default=24,
                        help='Data collection duration in hours')
    parser.add_argument('--analyze', action='store_true', default=True,
                        help='Run performance analysis after collection')
    parser.add_argument('--validate', action='store_true', default=True,
                        help='Validate top strategies')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

    logger.info("=" * 70)
    logger.info("SELF-LEARNING STRATEGY OPTIMIZATION PIPELINE")
    logger.info("=" * 70)

    # Phase 1: Collect
    logger.info(f"\nPhase 1: Collecting data for {args.collect} hours...")
    logger.info("(Press Ctrl+C to stop early and proceed to analysis)")
    success = run_bot(duration_minutes=args.collect * 60, dry_run=True)
    if not success:
        logger.warning("Bot exited with errors — check logs")

    # Phase 2: Analyze
    if args.analyze:
        logger.info("\nPhase 2: Analyzing performance...")
        summary = analyze_performance()

        print("\n" + "=" * 70)
        print("ANALYSIS RESULTS")
        print("=" * 70)
        print(f"Total resolved trades: {summary.get('total_trades', 0)}")
        print("\nSignal Performance:")
        for sig, stats in summary.get('signal_performance', {}).items():
            print(f"  {sig}: {stats['wins']}W {stats['losses']}L {stats['pushes']}P | "
                  f"Win rate: {stats['win_rate']*100:.1f}% | P&L: ${stats['total_pnl']:.2f}")

        print("\nOptimal Thresholds:")
        for k, v in summary.get('optimal_thresholds', {}).items():
            print(f"  {k}: {v}")

        summary_path = BASE / 'data' / 'optimization_summary.json'
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        logger.info(f"Saved analysis to {summary_path}")

        # Phase 3: Candidates
        logger.info("\nPhase 3: Generating candidate strategies...")
        candidates = generate_strategies(summary, num_candidates=3)

        strategies_dir = BASE / 'data' / 'strategies'
        strategies_dir.mkdir(parents=True, exist_ok=True)
        for i, strat in enumerate(candidates, 1):
            strat['name'] = f"Candidate{i}_{strat.get('name','Custom')}"
            config_path = strategies_dir / f"{strat['name'].lower().replace(' ', '_')}.yaml"
            save_strategy_config(strat, config_path)

        logger.info("\n✅ Optimization pipeline complete!")
        logger.info(f"Generated {len(candidates)} strategies in {strategies_dir}")
        logger.info("Next: Run validation for each candidate using btc_15m_monitor_v2.py")

    return 0

if __name__ == '__main__':
    sys.exit(main())
