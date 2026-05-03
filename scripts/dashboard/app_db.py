#!/usr/bin/env python3
"""Flask dashboard reading directly from trading.db"""

import os, sys, sqlite3, logging
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template_string

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('dashboard_db')

app = Flask(__name__)
DB_PATH = Path('/home/amsan/polymarket-timesfm-bot/data/trading.db')

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Polymarket Bot Dashboard</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 0; }
        .navbar { background: #161b22; padding: 1rem 2rem; border-bottom: 1px solid #30363d; }
        .navbar h1 { color: #58a6ff; margin: 0; }
        .container { max-width: 1200px; margin: 2rem auto; padding: 0 2rem; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
        .stat { background: #0d1117; padding: 1rem; border-radius: 6px; text-align: center; }
        .stat-value { font-size: 2rem; font-weight: bold; color: #58a6ff; }
        .stat-label { color: #8b949e; font-size: 0.875rem; }
        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.875rem; }
        th, td { padding: 0.75rem; border-bottom: 1px solid #30363d; text-align: left; }
        th { color: #8b949e; }
        .refresh { margin-top: 1rem; color: #8b949e; font-size: 0.875rem; }
        .empty { color: #8b949e; font-style: italic; }
    </style>
</head>
<body>
    <nav class="navbar"><h1>Polymarket BTC 15m Bot</h1></nav>
    <div class="container">
        <div class="grid">
            <div class="card"><h2>Portfolio</h2>
                <div class="stat"><div class="stat-value" id="balance">$40.00</div><div class="stat-label">Paper Balance</div></div>
                <div class="stat" style="margin-top:1rem"><div class="stat-value" id="pnl">$0.00</div><div class="stat-label">Total P&L</div></div>
            </div>
            <div class="card"><h2>Performance</h2>
                <div class="stat"><div class="stat-value" id="trades">0</div><div class="stat-label">Total Trades</div></div>
                <div class="stat" style="margin-top:1rem"><div class="stat-value" id="winrate">0%</div><div class="stat-label">Win Rate</div></div>
            </div>
            <div class="card"><h2>Current Market</h2>
                <div class="stat"><div class="stat-value" id="market">—</div><div class="stat-label">Market ID</div></div>
                <div class="stat" style="margin-top:1rem"><div class="stat-value" id="up">0.000</div><div class="stat-label">Up Token Price</div></div>
            </div>
        </div>

        <div class="card">
            <h2>Open Positions</h2>
            <table>
                <thead><tr><th>Market</th><th>Side</th><th>Entry</th><th>Current</th><th>Size($)</th><th>Unrealized P&L</th></tr></thead>
                <tbody id="positions-body"></tbody>
            </table>
        </div>

        <div class="card">
            <h2>Recent Trades</h2>
            <table>
                <thead><tr><th>Time</th><th>Market</th><th>Side</th><th>Price</th><th>Up&nbsp;Price</th><th>Size&nbsp;($)</th><th>Status</th><th>P&L</th></tr></thead>
                <tbody id="trades-body"></tbody>
            </table>
        </div>

        <p class="refresh">Auto-refresh every 5s | Pilot PID: ''' + os.popen('pgrep -f btc_15m_monitor_v2').read().strip() + '''</p>
    </div>

<script>
async function refresh() {
    const s = await fetch('/api/status').then(r=>r.json());
    document.getElementById('balance').textContent = '$' + s.portfolio.paper_balance.toFixed(2);
    document.getElementById('pnl').textContent = '$' + s.portfolio.total_pnl.toFixed(2);
    document.getElementById('pnl').className = s.portfolio.total_pnl >= 0 ? 'stat-value positive' : 'stat-value negative';
    document.getElementById('trades').textContent = s.portfolio.total_trades;
    document.getElementById('winrate').textContent = s.portfolio.win_rate.toFixed(1) + '%';
    document.getElementById('market').textContent = s.current_market ? s.current_market.slice(-12) : '—';
    document.getElementById('up').textContent = s.latest_signal ? s.latest_signal.polymarket_up_price.toFixed(3) : '0.000';

    const positions = await fetch('/api/positions').then(r=>r.json());
    document.getElementById('positions-body').innerHTML = positions.map(p => `
        <tr>
            <td>${p.market_slug ? p.market_slug.slice(-25) : '—'}</td>
            <td>${p.side}</td>
            <td>${p.avg_entry_price?.toFixed(3) || 0}</td>
            <td>${p.current_price?.toFixed(3) || 0}</td>
            <td>$${(p.balance||0).toFixed(0)}</td>
            <td class="${p.unrealized_pnl >= 0 ? 'positive' : 'negative'}">${(p.unrealized_pnl||0).toFixed(2)}</td>
        </tr>`).join('') || '<tr><td colspan="6" class="empty">No open positions</td></tr>';

    const trades = await fetch('/api/trades').then(r=>r.json());
    document.getElementById('trades-body').innerHTML = trades.map(t => `
        <tr>
            <td>${new Date(t.timestamp).toLocaleString()}</td>
            <td>${t.market_slug ? t.market_slug.slice(-25) : '—'}</td>
            <td>${t.side}</td>
            <td>${(t.price||0).toFixed(3)}</td>
            <td>${(t.polymarket_up_price||0).toFixed(3)}</td>
            <td>$${(t.size_usdc||0).toFixed(0)}</td>
            <td>${t.status}</td>
            <td class="${(t.pnl||0) >= 0 ? 'positive' : 'negative'}">${(t.pnl||0).toFixed(2)}</td>
        </tr>`).join('') || '<tr><td colspan="8" class="empty">No trades yet</td></tr>';
}
setInterval(refresh, 5000);
refresh();
</script>
</body>
</html>'''

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def status():
    conn = get_db()
    trades = conn.execute("SELECT * FROM trades ORDER BY timestamp DESC").fetchall()

    # Portfolio stats
    if trades:
        pnl = sum(t['pnl'] or 0 for t in trades)
        wins = sum(1 for t in trades if (t['pnl'] or 0) > 0)
        losses = sum(1 for t in trades if (t['pnl'] or 0) < 0)
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        
        # Compute dynamic paper balance: initial_capital + realized P&L - capital locked in open trades
        initial_capital = 1000.0  # default; will be overridden by config if available
        try:
            import yaml, os
            config_path = os.path.expanduser('~/polymarket-timesfm-bot/data/pilot_config.yaml')
            if os.path.exists(config_path):
                with open(config_path) as fh:
                    user_cfg = yaml.safe_load(fh) or {}
                initial_capital = user_cfg.get('initial_capital', 1000.0)
        except Exception:
            pass
        
        # Open trades: capital currently deployed (size_usdc)
        open_trades = [t for t in trades if t['pnl'] is None]
        locked_capital = sum(t['size_usdc'] or 0 for t in open_trades)
        balance = initial_capital + pnl - locked_capital
    else:
        pnl = wins = losses = win_rate = 0
        balance = 1000.0  # default starting capital

    # Latest signal from signals table (may be empty)
    latest_signal = conn.execute("SELECT * FROM signals ORDER BY timestamp DESC LIMIT 1").fetchone()
    current_market = latest_signal['market_id'] if latest_signal else (trades[0]['market_slug'] if trades else None)

    return jsonify({
        'portfolio': {
            'total_trades': len(trades),
            'paper_balance': balance,
            'total_pnl': pnl,
            'win_rate': win_rate,
            'wins': wins,
            'losses': losses
        },
        'current_market': current_market,
        'latest_signal': dict(latest_signal) if latest_signal else None
    })

@app.route('/api/trades')
def trades():
    conn = get_db()
    rows = conn.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 50").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/signals')
def signals():
    conn = get_db()
    rows = conn.execute("SELECT * FROM signals ORDER BY timestamp DESC LIMIT 50").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/positions')
def positions():
    conn = get_db()
    rows = conn.execute("SELECT * FROM positions ORDER BY timestamp DESC").fetchall()
    return jsonify([dict(r) for r in rows])

if __name__ == '__main__':
    print(f"Dashboard DB: {DB_PATH}")
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
