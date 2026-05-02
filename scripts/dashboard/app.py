#!/usr/bin/env python3
"""Flask web dashboard for Polymarket Trading Bot monitoring.

Access: http://localhost:5000
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from flask import Flask, render_template, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('dashboard')

app = Flask(__name__, template_folder='templates', static_folder='static')

DATA_DIR = Path(__file__).parent.parent.parent / 'data'
PAPER_TRADES_DIR = DATA_DIR / 'paper_trades'


def get_latest_paper_trades(limit: int = 50) -> List[Dict]:
    trades = []
    if not PAPER_TRADES_DIR.exists():
        return trades
    
    json_files = sorted(PAPER_TRADES_DIR.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True)
    
    for file in json_files[:10]:
        try:
            with open(file) as f:
                data = json.load(f)
                if 'trades' in data:
                    for trade in data['trades']:
                        trade['source_file'] = file.name
                        trades.append(trade)
        except Exception as e:
            logger.error(f"Error reading {file}: {e}")
    
    trades.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return trades[:limit]


def get_portfolio_stats() -> Dict:
    trades = get_latest_paper_trades(1000)
    
    if not trades:
        return {
            'total_trades': 0,
            'paper_balance': 40.0,
            'total_pnl': 0.0,
            'win_rate': 0.0,
            'wins': 0,
            'losses': 0,
        }
    
    total_pnl = sum(t.get('pnl', 0) or 0 for t in trades)
    wins = sum(1 for t in trades if (t.get('pnl') or 0) > 0)
    losses = sum(1 for t in trades if (t.get('pnl') or 0) < 0)
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    latest_balance = trades[0].get('paper_balance_after', 40.0) if trades else 40.0
    
    return {
        'total_trades': len(trades),
        'paper_balance': latest_balance,
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'wins': wins,
        'losses': losses,
    }


def create_templates():
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    base = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{% block title %}Dashboard{% endblock %}</title>
    <style>
        body { font-family: sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 0; }
        .navbar { background: #161b22; padding: 1rem 2rem; border-bottom: 1px solid #30363d; }
        .navbar h1 { color: #58a6ff; margin: 0; }
        .nav-links { margin-top: 0.5rem; }
        .nav-links a { color: #c9d1d9; text-decoration: none; margin-right: 1.5rem; }
        .nav-links a:hover { color: #58a6ff; }
        .container { max-width: 1200px; margin: 2rem auto; padding: 0 2rem; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; }
        .stat { background: #0d1117; padding: 1rem; border-radius: 6px; }
        .stat-value { font-size: 2rem; font-weight: bold; color: #58a6ff; }
        .stat-label { color: #8b949e; font-size: 0.875rem; }
        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { padding: 0.75rem; border-bottom: 1px solid #30363d; text-align: left; }
        th { color: #8b949e; }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>🤖 Polymarket Bot</h1>
        <div class="nav-links">
            <a href="/">Overview</a>
            <a href="/trades">Trades</a>
            <a href="/signals">Signals</a>
            <a href="/positions">Positions</a>
            <a href="/status">Status</a>
        </div>
    </nav>
    <div class="container">
        {% block content %}{% endblock %}
    </div>
</body>
</html>'''
    
    index = '''{% extends "base.html" %}
{% block content %}
<div class="grid">
    <div class="card">
        <h2>Portfolio</h2>
        <div class="stat">
            <div class="stat-value" id="balance">$40.00</div>
            <div class="stat-label">Paper Balance</div>
        </div>
        <div class="stat" style="margin-top:1rem;">
            <div class="stat-value" id="pnl">$0.00</div>
            <div class="stat-label">Total P&L</div>
        </div>
    </div>
    <div class="card">
        <h2>Performance</h2>
        <div class="stat">
            <div class="stat-value" id="win-rate">0%</div>
            <div class="stat-label">Win Rate</div>
        </div>
        <div class="stat" style="margin-top:1rem;">
            <div class="stat-value" id="total-trades">0</div>
            <div class="stat-label">Total Trades</div>
        </div>
    </div>
</div>
<script>
async function update() {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('balance').textContent = '$' + d.portfolio.paper_balance.toFixed(2);
    document.getElementById('pnl').textContent = '$' + d.portfolio.total_pnl.toFixed(2);
    document.getElementById('win-rate').textContent = d.portfolio.win_rate.toFixed(1) + '%';
    document.getElementById('total-trades').textContent = d.portfolio.total_trades;
}
update();
setInterval(update, 5000);
</script>
{% endblock %}'''
    
    trades = '''{% extends "base.html" %}
{% block content %}
<div class="card">
    <h2>Trade History</h2>
    <table>
        <thead><tr><th>Time</th><th>Signal</th><th>Side</th><th>Price</th><th>Size</th><th>P&L</th></tr></thead>
        <tbody id="tb"><tr><td colspan="6" style="text-align:center;">Loading...</td></tr></tbody>
    </table>
</div>
<script>
async function load() {
    const r = await fetch('/api/trades');
    const t = await r.json();
    document.getElementById('tb').innerHTML = t.length ? t.map(x => {
        const tm = new Date(x.timestamp).toLocaleString();
        const cl = (x.pnl||0)>0 ? 'positive' : (x.pnl||0)<0 ? 'negative' : '';
        return `<tr><td>${tm}</td><td>${x.signal}</td><td>${x.side}</td><td>${x.price?.toFixed(4)||'-'}</td><td>$${x.size_usdc?.toFixed(2)||'-'}</td><td class="${cl}">${x.pnl?'$'+x.pnl.toFixed(2):'-'}</td></tr>`;
    }).join('') : '<tr><td colspan="6" style="text-align:center;">No trades</td></tr>';
}
load();
setInterval(load, 10000);
</script>
{% endblock %}'''
    
    (templates_dir / 'base.html').write_text(base)
    (templates_dir / 'index.html').write_text(index)
    (templates_dir / 'trades.html').write_text(trades)
    (templates_dir / 'signals.html').write_text(trades.replace('Trade History', 'Signal History'))
    (templates_dir / 'positions.html').write_text('''{% extends "base.html" %}{% block content %}<div class="card"><h2>Positions</h2><p>No positions</p></div>{% endblock %}''')
    (templates_dir / 'status.html').write_text('''{% extends "base.html" %}{% block content %}<div class="card"><h2>Status</h2><p>Dry Run: Active</p></div>{% endblock %}''')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/trades')
def trades():
    return render_template('trades.html')


@app.route('/signals')
def signals():
    return render_template('signals.html')


@app.route('/positions')
def positions():
    return render_template('positions.html')


@app.route('/status')
def status_page():
    return render_template('status.html')


@app.route('/api/trades')
def api_trades():
    return jsonify(get_latest_paper_trades(request.args.get('limit', 50, type=int)))


@app.route('/api/status')
def api_status():
    return jsonify({'portfolio': get_portfolio_stats(), 'timestamp': datetime.now().isoformat()})


if __name__ == '__main__':
    create_templates()
    # Try ports 5000-5010
    port = 5000
    import socket
    for p in range(5000, 5011):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', p))
        sock.close()
        if result != 0:  # Port available
            port = p
            break
    
    logger.info(f"Dashboard: http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
