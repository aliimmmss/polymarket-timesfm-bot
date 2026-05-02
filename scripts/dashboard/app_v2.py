#!/usr/bin/env python3
"""Enhanced Flask dashboard for Polymarket Trading Bot.

Features:
- Chart.js visualizations (P&L, BTC price)
- Signal accuracy tracking
- BTC price history
- Config editor
- Export JSON/CSV
"""

import os
import sys
import json
import csv
import logging
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
from io import StringIO

from flask import Flask, render_template, jsonify, request, send_file

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('dashboard_v2')

app = Flask(__name__, template_folder='templates', static_folder='static')

DATA_DIR = Path(__file__).parent.parent.parent / 'data'
PAPER_TRADES_DIR = DATA_DIR / 'paper_trades'
LOGS_DIR = DATA_DIR / 'logs'
DB_PATH = DATA_DIR / 'trading.db'

# Store BTC prices history in memory (backup)
btc_price_history: List[Dict] = []


def get_latest_paper_trades(limit: int = 100) -> List[Dict]:
    trades = []
    if not PAPER_TRADES_DIR.exists():
        return trades
    
    json_files = sorted(PAPER_TRADES_DIR.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True)
    
    for file in json_files[:20]:
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
        return {'total_trades': 0, 'paper_balance': 1000.0, 'total_pnl': 0.0,
                'win_rate': 0.0, 'wins': 0, 'losses': 0, 'avg_trade': 0.0,
                'largest_win': 0.0, 'largest_loss': 0.0, 'sharpe': 0.0}
    
    total_pnl = sum(t.get('pnl', 0) or 0 for t in trades)
    wins = sum(1 for t in trades if (t.get('pnl') or 0) > 0)
    losses = sum(1 for t in trades if (t.get('pnl') or 0) < 0)
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    latest_balance = trades[0].get('paper_balance_after', 1000.0) if trades else 1000.0
    
    # Calculate additional metrics
    pnls = [t.get('pnl', 0) or 0 for t in trades]
    avg_trade = sum(pnls) / len(pnls) if pnls else 0
    largest_win = max(pnls) if pnls else 0
    largest_loss = min(pnls) if pnls else 0
    
    # Calculate Sharpe ratio (simplified)
    if len(pnls) > 1:
        sharpe = statistics.mean(pnls) / statistics.stdev(pnls) if statistics.stdev(pnls) != 0 else 0
    else:
        sharpe = 0
    
    return {
        'total_trades': len(trades),
        'paper_balance': latest_balance,
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'wins': wins,
        'losses': losses,
        'avg_trade': avg_trade,
        'largest_win': largest_win,
        'largest_loss': largest_loss,
        'sharpe': sharpe,
    }


def get_signal_accuracy() -> Dict:
    """Calculate signal accuracy based on trade results."""
    trades = get_latest_paper_trades(500)
    
    signals = {'BUY_UP': {'correct': 0, 'total': 0}, 'BUY_DOWN': {'correct': 0, 'total': 0}}
    
    for trade in trades:
        signal = trade.get('signal')
        pnl = trade.get('pnl', 0) or 0
        
        if signal in signals:
            signals[signal]['total'] += 1
            if pnl > 0:
                signals[signal]['correct'] += 1
    
    result = {}
    for sig, data in signals.items():
        accuracy = (data['correct'] / data['total'] * 100) if data['total'] > 0 else 0
        result[sig] = {'accuracy': accuracy, 'trades': data['total'], 'wins': data['correct']}
    
    return result


def get_daily_pnl_history() -> List[Dict]:
    """Get P&L history by day."""
    trades = get_latest_paper_trades(1000)
    
    daily = {}
    for trade in trades:
        date = trade.get('timestamp', '').split('T')[0] if 'T' in str(trade.get('timestamp')) else trade.get('timestamp', '').split()[0]
        if date:
            if date not in daily:
                daily[date] = []
            daily[date].append(trade.get('pnl', 0) or 0)
    
    history = []
    for date in sorted(daily.keys()):
        history.append({'date': date, 'pnl': sum(daily[date]), 'trades': len(daily[date])})
    
    return history


def get_cumulative_pnl() -> List[Dict]:
    """Get cumulative P&L over time."""
    daily = get_daily_pnl_history()
    cumulative = []
    total = 0
    for day in daily:
        total += day['pnl']
        cumulative.append({'date': day['date'], 'pnl': total})
    return cumulative


def get_btc_price() -> float:
    """Fetch current BTC price."""
    try:
        import requests
        r = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd', timeout=5)
        price = r.json()['bitcoin']['usd']
        
        # Store in history
        global btc_price_history
        btc_price_history.append({'timestamp': datetime.now().isoformat(), 'price': price})
        if len(btc_price_history) > 100:
            btc_price_history = btc_price_history[-100:]
        
        return price
    except Exception as e:
        logger.error(f"BTC price fetch failed: {e}")
        return 0.0


def get_config() -> Dict:
    """Read bot configuration."""
    config_path = Path(__file__).parent.parent.parent / 'config' / 'config.json'
    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except:
            pass
    
    # Default config
    return {
        'dry_run': True,
        'max_order_size': 10.0,
        'daily_loss_limit': 20.0,
        'monitor_interval': 300,
        'signature_type': 0,
    }


def save_config(config: Dict) -> bool:
    """Save bot configuration."""
    try:
        config_path = Path(__file__).parent.parent.parent / 'config' / 'config.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Save config failed: {e}")
        return False


@app.route('/')
def index():
    return render_template('index_v2.html')


@app.route('/trades')
def trades_page():
    return render_template('trades_v2.html')


@app.route('/signals')
def signals_page():
    return render_template('signals_v2.html')


@app.route('/charts')
def charts_page():
    return render_template('charts.html')


@app.route('/config')
def config_page():
    return render_template('config.html', config=get_config())


# API Endpoints

@app.route('/api/portfolio')
def api_portfolio():
    return jsonify(get_portfolio_stats())


@app.route('/api/trades')
def api_trades():
    return jsonify(get_latest_paper_trades(request.args.get('limit', 100, type=int)))


@app.route('/api/signals')
def api_signals():
    return jsonify(get_signal_accuracy())


@app.route('/api/status')
def api_status():
    return jsonify({
        'portfolio': get_portfolio_stats(),
        'signals': get_signal_accuracy(),
        'btc_price': get_btc_price(),
        'timestamp': datetime.now().isoformat(),
    })


@app.route('/api/pnl/daily')
def api_daily_pnl():
    return jsonify(get_daily_pnl_history())


@app.route('/api/pnl/cumulative')
def api_cumulative_pnl():
    return jsonify(get_cumulative_pnl())


@app.route('/api/btc/price')
def api_btc_price():
    return jsonify({'price': get_btc_price(), 'history': btc_price_history})


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'POST':
        new_config = request.json
        if save_config(new_config):
            return jsonify({'success': True, 'config': new_config})
        return jsonify({'success': False, 'error': 'Save failed'}), 500
    return jsonify(get_config())


@app.route('/api/export/json')
def export_json():
    """Export all data as JSON."""
    data = {
        'trades': get_latest_paper_trades(1000),
        'portfolio': get_portfolio_stats(),
        'signals': get_signal_accuracy(),
        'daily_pnl': get_daily_pnl_history(),
        'exported_at': datetime.now().isoformat(),
    }
    
    output = StringIO()
    json.dump(data, output, indent=2)
    output.seek(0)
    
    return send_file(
        StringIO(output.getvalue()),
        mimetype='application/json',
        as_attachment=True,
        download_name=f'polymarket_bot_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    )


@app.route('/api/export/csv')
def export_csv():
    """Export trades as CSV."""
    trades = get_latest_paper_trades(1000)
    
    output = StringIO()
    writer = csv.writer(output)
    
    if trades:
        headers = trades[0].keys()
        writer.writerow(headers)
        for trade in trades:
            writer.writerow([trade.get(h, '') for h in headers])
    
    output.seek(0)
    
    return send_file(
        StringIO(output.getvalue()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'polymarket_trades_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )


def create_templates():
    """Create enhanced HTML templates."""
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    static_dir = Path(__file__).parent / 'static'
    static_dir.mkdir(exist_ok=True)
    
    # Base template with Chart.js
    base = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{% block title %}Dashboard V2{% endblock %}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117; 
            color: #c9d1d9;
            margin: 0;
            line-height: 1.6;
        }
        .navbar { 
            background: #161b22; 
            padding: 1rem 2rem; 
            border-bottom: 1px solid #30363d;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .navbar h1 { color: #58a6ff; margin: 0; font-size: 1.5rem; }
        .nav-links { display: flex; gap: 1rem; }
        .nav-links a { color: #c9d1d9; text-decoration: none; padding: 0.5rem 1rem; border-radius: 6px; }
        .nav-links a:hover, .nav-links a.active { background: #21262d; color: #58a6ff; }
        .container { max-width: 1400px; margin: 2rem auto; padding: 0 2rem; }
        .card { 
            background: #161b22; 
            border: 1px solid #30363d; 
            border-radius: 12px; 
            padding: 1.5rem; 
            margin-bottom: 1.5rem;
        }
        .card h2 { margin-top: 0; color: #e6edf3; }
        .grid { display: grid; gap: 1.5rem; }
        .grid-2 { grid-template-columns: repeat(2, 1fr); }
        .grid-3 { grid-template-columns: repeat(3, 1fr); }
        .grid-4 { grid-template-columns: repeat(4, 1fr); }
        .stat { 
            background: #0d1117; 
            padding: 1.25rem 1rem; 
            border-radius: 8px;
            border: 1px solid #21262d;
        }
        .stat-value { 
            font-size: 2.5rem; 
            font-weight: 700; 
            color: #58a6ff;
            letter-spacing: -0.02em;
        }
        .stat-label { color: #8b949e; font-size: 0.875rem; margin-top: 0.25rem; }
        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        .neutral { color: #8b949e; }
        .btn {
            background: #238636;
            color: white;
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }
        .btn:hover { background: #2ea043; }
        .btn-secondary { background: #21262d; }
        .btn-secondary:hover { background: #30363d; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem; border-bottom: 1px solid #30363d; text-align: left; }
        th { color: #8b949e; font-weight: 500; }
        tr:hover { background: #0d1117; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; margin-bottom: 0.5rem; color: #8b949e; }
        .form-group input, .form-group select {
            width: 100%;
            padding: 0.5rem;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            color: #c9d1d9;
        }
        .badge { 
            padding: 0.25rem 0.5rem; 
            border-radius: 4px; 
            font-size: 0.75rem; 
            font-weight: 500;
        }
        .badge-buy { background: #238636; color: white; }
        .badge-sell { background: #f85149; color: white; }
        .chart-container { position: relative; height: 300px; }
        .export-btns { display: flex; gap: 1rem; margin-bottom: 1rem; }
        @media (max-width: 768px) {
            .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>🤖 Polymarket Bot v2</h1>
        <div class="nav-links">
            <a href="/" {% if request.path == '/' %}class="active"{% endif %}>Overview</a>
            <a href="/trades" {% if request.path == '/trades' %}class="active"{% endif %}>Trades</a>
            <a href="/charts" {% if request.path == '/charts' %}class="active"{% endif %}>Charts</a>
            <a href="/config" {% if request.path == '/config' %}class="active"{% endif %}>Config</a>
        </div>
    </nav>
    <div class="container">
        {% block content %}{% endblock %}
    </div>
    <footer style="text-align: center; padding: 2rem; color: #8b949e;">
        <small>Auto-refreshes every 5s • Export: <a href="/api/export/json">JSON</a> | <a href="/api/export/csv">CSV</a></small>
    </footer>
</body>
</html>'''
    
    # Overview page
    index_v2 = '''{% extends "base.html" %}
{% block content %}
<div class="grid grid-4">
    <div class="card">
        <h2>Portfolio</h2>
        <div class="stat">
            <div class="stat-value" id="balance">$1,000.00</div>
            <div class="stat-label">Paper Balance</div>
        </div>
        <div class="stat" style="margin-top:1rem;">
            <div class="stat-value" id="total-pnl">$0.00</div>
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
    <div class="card">
        <h2>Stats</h2>
        <div class="stat">
            <div class="stat-value" id="avg-trade">$0.00</div>
            <div class="stat-label">Avg Trade</div>
        </div>
        <div class="stat" style="margin-top:1rem;">
            <div class="stat-value" id="sharpe">0.00</div>
            <div class="stat-label">Sharpe Ratio</div>
        </div>
    </div>
    <div class="card">
        <h2>Extremes</h2>
        <div class="stat">
            <div class="stat-value positive" id="largest-win">$0.00</div>
            <div class="stat-label">Largest Win</div>
        </div>
        <div class="stat" style="margin-top:1rem;">
            <div class="stat-value negative" id="largest-loss">$0.00</div>
            <div class="stat-label">Largest Loss</div>
        </div>
    </div>
</div>

<div class="card">
    <h2>Recent Trades</h2>
    <div class="export-btns">
        <a href="/api/export/json" class="btn btn-secondary">Export JSON</a>
        <a href="/api/export/csv" class="btn btn-secondary">Export CSV</a>
    </div>
    <table>
        <thead>
            <tr><th>Time</th><th>Signal</th><th>Side</th><th>Price</th><th>Size</th><th>P&L</th></tr>
        </thead>
        <tbody id="trades-tbody"><tr><td colspan="6" style="text-align:center;">Loading...</td></tr></tbody>
    </table>
</div>

<script>
async function update() {
    const r = await fetch('/api/status');
    const d = await r.json();
    const p = d.portfolio;
    
    document.getElementById('balance').textContent = '$' + p.paper_balance.toFixed(2);
    document.getElementById('total-pnl').textContent = (p.total_pnl >= 0 ? '+' : '') + '$' + p.total_pnl.toFixed(2);
    document.getElementById('total-pnl').className = 'stat-value ' + (p.total_pnl >= 0 ? 'positive' : 'negative');
    document.getElementById('win-rate').textContent = p.win_rate.toFixed(1) + '%';
    document.getElementById('total-trades').textContent = p.total_trades;
    document.getElementById('avg-trade').textContent = (p.avg_trade >= 0 ? '+' : '') + '$' + p.avg_trade.toFixed(2);
    document.getElementById('avg-trade').className = 'stat-value ' + (p.avg_trade >= 0 ? 'positive' : 'negative');
    document.getElementById('sharpe').textContent = p.sharpe.toFixed(2);
    document.getElementById('largest-win').textContent = '+$' + p.largest_win.toFixed(2);
    document.getElementById('largest-loss').textContent = '-$' + Math.abs(p.largest_loss).toFixed(2);
}

async function loadTrades() {
    const r = await fetch('/api/trades?limit=10');
    const t = await r.json();
    document.getElementById('trades-tbody').innerHTML = t.length ? t.map(x => {
        const tm = new Date(x.timestamp).toLocaleString();
        const cl = (x.pnl||0)>0 ? 'positive' : (x.pnl||0)<0 ? 'negative' : 'neutral';
        return `<tr>
            <td>${tm}</td>
            <td><span class="badge badge-${x.side==='BUY'?'buy':'sell'}">${x.signal}</span></td>
            <td>${x.side}</td>
            <td>${x.price?.toFixed(4)||'-'}</td>
            <td>$${x.size_usdc?.toFixed(2)||'-'}</td>
            <td class="${cl}">${x.pnl?(x.pnl>0?'+':'')+'$'+x.pnl.toFixed(2):'-'}</td>
        </tr>`;
    }).join('') : '<tr><td colspan="6" style="text-align:center;">No trades yet</td></tr>';
}

update();
loadTrades();
setInterval(() => { update(); loadTrades(); }, 5000);
</script>
{% endblock %}'''
    
    # Trades page
    trades_v2 = '''{% extends "base.html" %}
{% block content %}
<div class="card">
    <h2>All Trades</h2>
    <div class="export-btns">
        <a href="/api/export/json" class="btn btn-secondary">Export JSON</a>
        <a href="/api/export/csv" class="btn btn-secondary">Export CSV</a>
    </div>
    <table>
        <thead>
            <tr><th>Time</th><th>Market</th><th>Signal</th><th>Side</th><th>Price</th><th>Size</th><th>P&L</th><th>Conf</th></tr>
        </thead>
        <tbody id="tbody"><tr><td colspan="8" style="text-align:center;">Loading...</td></tr></tbody>
    </table>
</div>
<script>
async function load() {
    const r = await fetch('/api/trades?limit=100');
    const t = await r.json();
    document.getElementById('tbody').innerHTML = t.length ? t.map(x => {
        const tm = new Date(x.timestamp).toLocaleString();
        const cl = (x.pnl||0)>0 ? 'positive' : (x.pnl||0)<0 ? 'negative' : 'neutral';
        return `<tr>
            <td>${tm}</td>
            <td>${x.market_slug||'-'}</td>
            <td><span class="badge badge-${x.side==='BUY'?'buy':'sell'}">${x.signal}</span></td>
            <td>${x.side}</td>
            <td>${x.price?.toFixed(4)||'-'}</td>
            <td>$${x.size_usdc?.toFixed(2)||'-'}</td>
            <td class="${cl}">${x.pnl?(x.pnl>0?'+':'')+'$'+x.pnl.toFixed(2):'-'}</td>
            <td>${x.confidence?(x.confidence*100).toFixed(0)+'%':'-'}</td>
        </tr>`;
    }).join('') : '<tr><td colspan="8" style="text-align:center;">No trades</td></tr>';
}
load();
setInterval(load, 10000);
</script>
{% endblock %}'''
    
    # Charts page with Chart.js
    charts = '''{% extends "base.html" %}
{% block content %}
<div class="grid grid-2">
    <div class="card">
        <h2>Cumulative P&L</h2>
        <div class="chart-container"><canvas id="cumulativeChart"></canvas></div>
    </div>
    <div class="card">
        <h2>Daily P&L</h2>
        <div class="chart-container"><canvas id="dailyChart"></canvas></div>
    </div>
</div>

<div class="card">
    <h2>Signal Accuracy</h2>
    <div class="chart-container"><canvas id="signalChart"></canvas></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#30363d';

async function loadCumulative() {
    const r = await fetch('/api/pnl/cumulative');
    const data = await r.json();
    
    new Chart(document.getElementById('cumulativeChart'), {
        type: 'line',
        data: {
            labels: data.map(d => d.date),
            datasets: [{
                label: 'Cumulative P&L',
                data: data.map(d => d.pnl),
                borderColor: '#58a6ff',
                backgroundColor: 'rgba(88, 166, 255, 0.1)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { ticks: { callback: v => '$' + v.toFixed(2) } }
            }
        }
    });
}

async function loadDaily() {
    const r = await fetch('/api/pnl/daily');
    const data = await r.json();
    
    new Chart(document.getElementById('dailyChart'), {
        type: 'bar',
        data: {
            labels: data.map(d => d.date),
            datasets: [{
                label: 'Daily P&L',
                data: data.map(d => d.pnl),
                backgroundColor: data.map(d => d.pnl >= 0 ? '#238636' : '#f85149'),
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { ticks: { callback: v => '$' + v.toFixed(2) } }
            }
        }
    });
}

async function loadSignals() {
    const r = await fetch('/api/signals');
    const data = await r.json();
    
    new Chart(document.getElementById('signalChart'), {
        type: 'bar',
        data: {
            labels: Object.keys(data),
            datasets: [{
                label: 'Accuracy %',
                data: Object.values(data).map(d => d.accuracy),
                backgroundColor: '#58a6ff',
            }, {
                label: 'Total Trades',
                data: Object.values(data).map(d => d.trades),
                backgroundColor: '#8b949e',
                yAxisID: 'y1'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: { display: true, text: 'Accuracy %' },
                    max: 100
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: { display: true, text: 'Trade Count' },
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
}

loadCumulative();
loadDaily();
loadSignals();
</script>
{% endblock %}'''
    
    # Config page
    config = '''{% extends "base.html" %}
{% block content %}
<div class="grid grid-2">
    <div class="card">
        <h2>Bot Configuration</h2>
        <form id="config-form">
            <div class="form-group">
                <label>Dry Run Mode</label>
                <select name="dry_run" id="dry_run">
                    <option value="true" {% if config.dry_run %}selected{% endif %}>Enabled</option>
                    <option value="false" {% if not config.dry_run %}selected{% endif %}>Disabled</option>
                </select>
            </div>
            <div class="form-group">
                <label>Max Order Size (USDC)</label>
                <input type="number" name="max_order_size" id="max_order_size" value="{{config.max_order_size}}" step="0.1">
            </div>
            <div class="form-group">
                <label>Daily Loss Limit (USDC)</label>
                <input type="number" name="daily_loss_limit" id="daily_loss_limit" value="{{config.daily_loss_limit}}" step="0.1">
            </div>
            <div class="form-group">
                <label>Monitor Interval (seconds)</label>
                <input type="number" name="monitor_interval" id="monitor_interval" value="{{config.monitor_interval}}" step="10">
            </div>
            <div class="form-group">
                <label>Signature Type (0=EOA, 1/2=Proxy)</label>
                <input type="number" name="signature_type" id="signature_type" value="{{config.signature_type}}" min="0" max="2">
            </div>
            <button type="submit" class="btn">Save Config</button>
        </form>
        <div id="save-result" style="margin-top:1rem;"></div>
    </div>
    
    <div class="card">
        <h2>Quick Actions</h2>
        <p style="color:#8b949e;margin-bottom:1rem;">Configuration affects live trading. Changes take effect on next bot restart.</p>
        <a href="/api/export/json" class="btn" style="margin-right:0.5rem;">Export JSON</a>
        <a href="/api/export/csv" class="btn btn-secondary">Export CSV</a>
        <h3 style="margin-top:2rem;">JSON Preview</h3>
        <pre id="config-preview" style="background:#0d1117;padding:1rem;border-radius:6px;font-size:0.875rem;overflow-x:auto;">{{config|tojson(indent=2)}}</pre>
    </div>
</div>

<script>
document.getElementById('config-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const config = {
        dry_run: form.get('dry_run') === 'true',
        max_order_size: parseFloat(form.get('max_order_size')),
        daily_loss_limit: parseFloat(form.get('daily_loss_limit')),
        monitor_interval: parseInt(form.get('monitor_interval')),
        signature_type: parseInt(form.get('signature_type'))
    };
    
    const r = await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(config)
    });
    
    const result = await r.json();
    document.getElementById('save-result').innerHTML = result.success 
        ? '<span class="positive">✓ Config saved!</span>'
        : '<span class="negative">✗ Save failed</span>';
    
    if (result.success) {
        document.getElementById('config-preview').textContent = JSON.stringify(config, null, 2);
    }
});
</script>
{% endblock %}'''
    
    # Write templates
    (templates_dir / 'base.html').write_text(base)
    (templates_dir / 'index_v2.html').write_text(index_v2)
    (templates_dir / 'trades_v2.html').write_text(trades_v2)
    (templates_dir / 'charts.html').write_text(charts)
    (templates_dir / 'config.html').write_text(config)
    
    logger.info("Enhanced templates created")


if __name__ == '__main__':
    create_templates()
    
    # Try ports 5000-5010
    port = 5000
    import socket
    for p in range(5000, 5011):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', p))
        sock.close()
        if result != 0:
            port = p
            break
    
    logger.info(f"Dashboard v2: http://localhost:{port}")
    logger.info("Features: Charts, Config Editor, Export, Signal Accuracy")
    app.run(host='0.0.0.0', port=port, debug=False)
