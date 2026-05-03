#!/usr/bin/env python3
"""
Autonomous Phase 2: After data collection, analyze and validate strategy.

Workflow:
  1. Load pilot journal data (filtered to after a certain date if needed)
  2. Compute performance metrics and optimal thresholds
  3. Generate 3 candidate strategy configs (Conservative, Aggressive, Balanced)
  4. Pick best candidate (Balanced by default)
  5. Run 24h validation with that candidate
  6. After validation, produce final report

Usage (run via cron or manually):
  python scripts/autonomous_phase2.py
"""

import argparse
import json
import logging
import subprocess
import sys
import time
import yaml
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from src.analysis.performance_analyzer import PerformanceAnalyzer
from src.trading.trade_journal import TradeJournal

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def wait_for_pilot(pid_file: Path, timeout: int = 7200):
    """Wait for the pilot process to exit (up to timeout seconds)."""
    logger.info(f"Waiting for pilot to complete (PID from {pid_file})...")
    start = time.time()
    while time.time() - start < timeout:
        if pid_file.exists():
            with open(pid_file) as f:
                pid_str = f.read().strip()
            if pid_str:
                try:
                    import os, signal
                    os.kill(int(pid_str), 0)  # check if process exists
                except OSError:
                    logger.info("Pilot process has terminated")
                    return True
        else:
            # No PID file — assume pilot done
            logger.info("No PID file found — assuming pilot finished")
            return True
        time.sleep(30)
    logger.warning("Timeout waiting for pilot — proceeding anyway")
    return False

def run_analysis():
    """Analyze collected pilot data and generate candidate configs."""
    logger.info("=== Phase 2: Analyzing pilot data ===")
    analyzer = PerformanceAnalyzer(data_dir=str(BASE / 'data'))
    analyzer.load_trades_from_journal()
    analyzer.load_observations_from_csv()

    summary = analyzer.summarize()
    logger.info(f"Total resolved trades: {summary.get('total_trades', 0)}")
    for sig, stats in summary.get('signal_performance', {}).items():
        logger.info(f"  {sig}: {stats['wins']}W {stats['losses']}L  WR={stats['win_rate']*100:.1f}%  P&L=${stats['total_pnl']:.2f}")

    # Save summary JSON
    summary_path = BASE / 'data' / 'optimization_summary.json'
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info(f"Saved analysis to {summary_path}")

    # Generate candidates
    optimal = summary.get('optimal_thresholds', {})
    candidates = analyzer.generate_candidate_strategies(optimal, n=3)

    strategies_dir = BASE / 'data' / 'strategies'
    strategies_dir.mkdir(parents=True, exist_ok=True)

    for i, cand in enumerate(candidates, 1):
        cand.setdefault('name', f"Candidate{i}")
        # Ensure we have thresholds for all required fields
        config_path = strategies_dir / f"{cand['name'].lower().replace(' ', '_')}.yaml"
        save_strategy_config(cand, config_path)
        logger.info(f"Strategy candidate {i}: {cand['name']} → {config_path}")

    return candidates, summary

def save_strategy_config(strategy: dict, path: Path):
    """Save strategy config as YAML with all needed keys."""
    content = f"""strategy:
  weights:
    tpd: {strategy.get('weights', {}).get('tpd', 0.35)}
    cvd: {strategy.get('weights', {}).get('cvd', 0.30)}
    obi: {strategy.get('weights', {}).get('obi', 0.20)}
    time_decay: {strategy.get('weights', {}).get('time_decay', 0.15)}
  thresholds:
    buy_up: {strategy.get('thresholds', {}).get('buy_up', 0.65)}
    buy_down: {strategy.get('thresholds', {}).get('buy_down', 0.65)}
    min_signals: {strategy.get('thresholds', {}).get('min_signals', 3)}

signal_a:
  gap_threshold: {strategy.get('signal_a_gap', 30)}
  max_price: {strategy.get('signal_a_max_price', 0.55)}
  min_time_remaining: 300

signal_b:
  gap_threshold: {strategy.get('signal_b_gap', 50)}
  max_price: {strategy.get('signal_b_max_price', 0.95)}
  max_time_remaining: 180

signal_c:
  cvd_threshold: {strategy.get('signal_c_cvd', 50)}
  obi_threshold: {strategy.get('signal_c_obi', 0.30)}
  max_price: 0.50
  min_time_remaining: 300
"""
    path.write_text(content)

def pick_candidate(candidates):
    """Select best candidate for validation."""
    # Prefer Balanced if present; else take first
    for cand in candidates:
        if 'balanced' in cand['name'].lower():
            return cand
    return candidates[0]

def launch_validation(candidate: dict):
    """Launch run_validation.py for this candidate."""
    # Ensure config has unique journal path
    cand_name = candidate['name'].lower().replace(' ', '_')
    config_path = BASE / 'data' / 'strategies' / f"{cand_name}.yaml"

    # Append trading_log_path to config file (or ensure it's present)
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    journal_path = f"/home/amsan/trading/trading-log-val-{cand_name}.yaml"
    cfg['trading_log_path'] = journal_path
    # Write temporary enriched config
    temp_config = BASE / 'data' / f'val_{cand_name}.yaml'
    with open(temp_config, 'w') as f:
        yaml.dump(cfg, f, sort_keys=False)
    logger.info(f"Validation config: {temp_config}")

    # Launch validation wrapper
    cmd = [
        sys.executable,
        str(BASE / 'scripts' / 'run_validation.py'),
        '--config', str(temp_config),
        '--duration', '86400'  # 24h
    ]
    logger.info(f"Launching validation: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=BASE)
    logger.info(f"Validation PID: {proc.pid}")
    # Write PID for monitoring
    with open(BASE / 'data' / 'validation_pid.txt', 'w') as f:
        f.write(str(proc.pid))
    return proc

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-wait', action='store_true', help="Don't wait for pilot, assume it's done")
    args = parser.parse_args()

    logger.info("="*70)
    logger.info("AUTONOMOUS PHASE 2 — STRATEGY VALIDATION")
    logger.info("="*70)

    pid_file = Path('/tmp/btc_bot_pid')
    if not args.skip_wait:
        wait_for_pilot(pid_file)

    # Step 1: Analyze pilot data
    candidates, summary = run_analysis()

    # Step 2: Pick candidate and launch validation
    best = pick_candidate(candidates)
    logger.info(f"Selected candidate for validation: {best['name']}")

    proc = launch_validation(best)

    # Wait for validation to complete (this blocks ~24h)
    logger.info("Waiting for validation to complete...")
    proc.wait()
    logger.info(f"Validation exited with code {proc.returncode}")

    # Step 3: Final summary already printed by run_validation.py; we can compile master report
    logger.info("Phase 2 complete. Final report generated by validation wrapper.")
    return 0

if __name__ == '__main__':
    sys.exit(main())
