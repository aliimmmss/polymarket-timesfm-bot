#!/usr/bin/env python3
"""
Run a single candidate strategy for 24h (dry-run), then compute final metrics.

Usage:
  python scripts/run_validation.py --config config/strategies/candidate_balanced.yaml
"""

import argparse
import subprocess
import sys
import yaml
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from src.analysis.performance_analyzer import PerformanceAnalyzer
from src.trading.trade_journal import TradeJournal

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, help='Path to candidate strategy YAML')
    parser.add_argument('--duration', type=int, default=86400, help='Validation duration (seconds, default 24h)')
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1

    # Load config and ensure unique journal path
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}

    candidate_name = cfg.get('name', config_path.stem)
    journal_path = f"/home/amsan/trading/trading-log-val-{candidate_name}.yaml"
    cfg['trading_log_path'] = journal_path

    # Temporarily write augmented config to a temp file
    temp_config = BASE / 'data' / f'val_config_{candidate_name}.yaml'
    temp_config.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_config, 'w') as f:
        yaml.dump(cfg, f, sort_keys=False)
    print(f"Using temporary config: {temp_config}")

    # Launch validation bot
    cmd = [
        sys.executable,
        str(BASE / 'scripts' / 'btc_15m_monitor_v2.py'),
        '--dry-run',
        '--duration', str(args.duration),
        '--config', str(temp_config)
    ]
    print(f"\n{'='*60}")
    print(f"STARTING VALIDATION: {candidate_name}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Journal: {journal_path}")
    print(f"{'='*60}\n")

    # Stream bot output live
    proc = subprocess.Popen(
        cmd,
        cwd=BASE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    )

    try:
        for line in proc.stdout:
            print(line, end='')
        proc.wait()
    except KeyboardInterrupt:
        print("\nInterrupted — terminating bot...")
        proc.terminate()
        proc.wait()
        return 130

    print(f"\nBot exited with code {proc.returncode}")

    # Analyze the validation run's journal
    journal_file = Path(journal_path)
    if not journal_file.exists():
        print(f"ERROR: Journal not found: {journal_file}")
        return 1

    print(f"\nAnalyzing validation journal: {journal_file}")
    # Load trades from the specific journal file using TradeJournal's mechanism
    # The PerformanceAnalyzer expects to load from default location via TradeJournal.
    # We'll hack: temporarily set config to point to our journal, then analyze.
    # Or simply load journal manually and compute stats.

    with open(journal_file) as f:
        entries = list(yaml.safe_load_all(f))

    all_trades = []
    for entry in entries:
        if isinstance(entry, list):
            all_trades.extend(entry)
        elif isinstance(entry, dict):
            all_trades.append(entry)

    resolved = [t for t in all_trades if t.get('outcome') not in (None, 'filled', '')]
    print(f"Total trades: {len(all_trades)}, Resolved: {len(resolved)}")

    if not resolved:
        print("No resolved trades — cannot evaluate strategy")
        return 1

    # Compute stats
    from collections import Counter, defaultdict
    import numpy as np

    outcomes = Counter(t['outcome'] for t in resolved)
    wins = outcomes.get('win', 0)
    losses = outcomes.get('loss', 0)
    pushes = outcomes.get('push', 0)
    total = wins + losses + pushes
    win_rate = wins / total if total else 0

    pnls = [t.get('pnl_usdc', 0) or 0 for t in resolved]
    total_pnl = sum(pnls)
    avg_pnl = np.mean(pnls) if pnls else 0
    std_pnl = np.std(pnls) if len(pnls) > 1 else 0
    sharpe = avg_pnl / std_pnl if std_pnl > 0 else 0

    # Per-signal breakdown
    signal_stats = defaultdict(lambda: {'wins':0, 'losses':0, 'pushes':0, 'pnl':0.0, 'count':0})
    for t in resolved:
        sig = t.get('strategy', 'UNKNOWN')
        stats = signal_stats[sig]
        stats['count'] += 1
        stats['pnl'] += t.get('pnl_usdc', 0) or 0
        if t['outcome'] == 'win':
            stats['wins'] += 1
        elif t['outcome'] == 'loss':
            stats['losses'] += 1
        elif t['outcome'] == 'push':
            stats['pushes'] += 1

    # Report
    print(f"\n{'='*60}")
    print(f"VALIDATION RESULTS: {candidate_name}")
    print(f"{'='*60}")
    print(f"Resolved trades: {total} ({wins}W/{losses}L/{pushes}P)")
    print(f"Win rate: {win_rate*100:.1f}%")
    print(f"Total P&L: ${total_pnl:.2f}")
    print(f"Avg P&L/trade: ${avg_pnl:.2f}")
    print(f"Sharpe (P&L): {sharpe:.2f}")
    print(f"\nSignal breakdown:")
    for sig, s in sorted(signal_stats.items()):
        wr = s['wins']/(s['wins']+s['losses']) if (s['wins']+s['losses'])>0 else 0
        print(f"  {sig}: {s['wins']}W/{s['losses']}L | WR={wr*100:.0f}% | P&L=${s['pnl']:.2f}")

    # Save report
    report_path = BASE / 'data' / f'validation_report_{candidate_name}.json'
    report = {
        'candidate': candidate_name,
        'timestamp': datetime.now().isoformat(),
        'total_trades': len(all_trades),
        'resolved_trades': total,
        'wins': wins,
        'losses': losses,
        'pushes': pushes,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'sharpe': sharpe,
        'signal_breakdown': {k: v for k, v in signal_stats.items()},
        'journal_path': str(journal_path),
        'duration_seconds': args.duration,
    }
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n✅ Report saved: {report_path}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
