"""
Polymarket Trading Bot - Web Dashboard
=======================================
Simple Flask web interface showing bot status, strategy explanation, and math.

Access at http://178.156.208.100:8080
"""

from flask import Flask, render_template_string, jsonify
import json
import os
from datetime import datetime

# Import trade logger for live stats
try:
    from trade_logger import get_trade_logger
except ImportError:
    get_trade_logger = None

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="30">
    <title>🐳 Polymarket Trading Bot</title>
    <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a25;
            --accent: #00d4aa;
            --accent-dim: #00a080;
            --text-primary: #ffffff;
            --text-secondary: #a0a0b0;
            --border: #2a2a3a;
            --success: #00ff88;
            --warning: #ffaa00;
            --danger: #ff4466;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'SF Mono', 'Consolas', monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        header {
            text-align: center;
            padding: 3rem 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 2rem;
        }
        
        h1 {
            font-size: 2.5rem;
            color: var(--accent);
            margin-bottom: 0.5rem;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 1.1rem;
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
        }
        
        .card h2 {
            color: var(--accent);
            font-size: 1.2rem;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .card h3 {
            color: var(--text-primary);
            font-size: 1rem;
            margin: 1rem 0 0.5rem;
        }
        
        .card p, .card li {
            color: var(--text-secondary);
            font-size: 0.9rem;
        }
        
        .card ul {
            list-style: none;
            padding-left: 0;
        }
        
        .card li {
            padding: 0.3rem 0;
            padding-left: 1.5rem;
            position: relative;
        }
        
        .card li::before {
            content: "→";
            position: absolute;
            left: 0;
            color: var(--accent);
        }
        
        .stat-row {
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--border);
        }
        
        .stat-label {
            color: var(--text-secondary);
        }
        
        .stat-value {
            color: var(--accent);
            font-weight: bold;
        }
        
        .math-block {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            margin: 1rem 0;
            font-family: 'Times New Roman', serif;
            font-size: 1.1rem;
            text-align: center;
            color: var(--text-primary);
        }
        
        .code-block {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            margin: 0.5rem 0;
            font-size: 0.85rem;
            overflow-x: auto;
            color: var(--accent);
        }
        
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: bold;
        }
        
        .status-running {
            background: rgba(0, 255, 136, 0.2);
            color: var(--success);
        }
        
        .status-stopped {
            background: rgba(255, 68, 102, 0.2);
            color: var(--danger);
        }
        
        .whale-list {
            margin-top: 1rem;
        }
        
        .whale-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem;
            background: var(--bg-secondary);
            border-radius: 6px;
            margin-bottom: 0.5rem;
            font-size: 0.85rem;
        }
        
        .whale-addr {
            font-family: monospace;
            color: var(--accent);
            text-decoration: none;
        }
        
        .whale-addr:hover {
            text-decoration: underline;
            color: var(--success);
        }
        
        .whale-profit {
            color: var(--success);
        }
        
        /* Trade log table styles */
        .trade-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
            margin-top: 1rem;
        }
        
        .trade-table th, .trade-table td {
            padding: 0.5rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        
        .trade-table th {
            color: var(--accent);
            font-weight: bold;
        }
        
        .pnl-positive { color: var(--success); }
        .pnl-negative { color: var(--danger); }
        .pnl-neutral { color: var(--text-secondary); }
        
        .bankroll-highlight {
            font-size: 1.5rem;
            color: var(--accent);
            font-weight: bold;
        }
        
        .big-number {
            font-size: 1.3rem;
            font-weight: bold;
        }
        
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
            border-top: 1px solid var(--border);
            margin-top: 2rem;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 1rem;
            }
            h1 {
                font-size: 1.8rem;
            }
            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🐳🧬 Polymarket Trading Bot</h1>
            <p class="subtitle">Unified Trader with EV-Net Decision Logic + Adaptive Thresholds</p>
        </header>
        
        <div class="grid">
            <!-- Status Card with Bankroll -->
            <div class="card">
                <h2>📊 Bot Status</h2>
                <div class="stat-row">
                    <span class="stat-label">Status</span>
                    <span class="status-badge {{ 'status-running' if status.running else 'status-stopped' }}">
                        {{ 'RUNNING' if status.running else 'STOPPED' }}
                    </span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Mode</span>
                    <span class="stat-value">{{ status.mode }}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Whales Tracked</span>
                    <span class="stat-value">{{ status.whale_count }}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Last Refresh</span>
                    <span class="stat-value">{{ status.last_update }}</span>
                </div>
            </div>
            
            <!-- Live Bankroll & PnL Card -->
            <div class="card">
                <h2>💰 Live Bankroll</h2>
                <div style="text-align: center; padding: 1rem 0;">
                    <div class="bankroll-highlight">${{ "%.2f"|format(trading_stats.current_bankroll) }}</div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.5rem;">Current Balance</div>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Starting</span>
                    <span class="stat-value">${{ "%.2f"|format(trading_stats.initial_bankroll) }}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Total P&L</span>
                    <span class="{{ 'pnl-positive' if trading_stats.total_pnl >= 0 else 'pnl-negative' }} big-number">
                        {{ "+" if trading_stats.total_pnl >= 0 else "" }}${{ "%.2f"|format(trading_stats.total_pnl) }}
                    </span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Win Rate</span>
                    <span class="stat-value">{{ trading_stats.win_rate }}%</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Trades (W/L)</span>
                    <span class="stat-value">{{ trading_stats.wins }}/{{ trading_stats.losses }}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Open Positions</span>
                    <span class="stat-value">{{ trading_stats.open_positions }}</span>
                </div>
            </div>
            
            <!-- What It Does -->
            <div class="card">
                <h2>🤖 What This Bot Does</h2>
                <p>Unified trading bot that finds positive-EV opportunities using whale signals and price momentum.</p>
                
                <h3>Core Strategy (Jan 2026)</h3>
                <ul>
                    <li><strong>Dynamic whale discovery</strong> - Identifies whale wallets by volume ≥$50</li>
                    <li>Fuses whale signals (60%) with price momentum (40%)</li>
                    <li><strong>EV-net decisions</strong> - Trades only if expected value > 0</li>
                    <li><strong>Adaptive thresholds</strong> - Auto-adjusts based on trade rate</li>
                    <li>Nighttime mode (2x stricter) + kill switch safety</li>
                </ul>
            </div>
            
            <!-- Whales Tracked -->
            <div class="card">
                <h2>🐋 Whales Tracked</h2>
                <div class="whale-list">
                    <div class="whale-item">
                        <a href="https://polymarket.com/profile/0x63ce342161250d705dc0b16df89036c8e5f9ba9a" target="_blank" class="whale-addr">0x8dxd (Primary)</a>
                        <span class="whale-profit">+$558k</span>
                    </div>
                    <div class="whale-item">
                        <a href="https://polymarket.com/profile/0x9d84ce0306f8551e02efef1680475fc0f1dc1344" target="_blank" class="whale-addr">0x9d84...9344</a>
                        <span class="whale-profit">+$2.6M</span>
                    </div>
                    <div class="whale-item">
                        <a href="https://polymarket.com/profile/0xd218e474776403a330142299f7796e8ba32eb5c9" target="_blank" class="whale-addr">0xd218...b5c9</a>
                        <span class="whale-profit">+$958k</span>
                    </div>
                    <div class="whale-item">
                        <a href="https://polymarket.com/profile/0x006cc834cc092684f1b56626e23bedb3835c16ea" target="_blank" class="whale-addr">0x006c...16ea</a>
                        <span class="whale-profit">+$1.48M</span>
                    </div>
                    <div class="whale-item">
                        <a href="https://polymarket.com/profile/0xe74a4446efd66a4de690962938f550d8921a40ee" target="_blank" class="whale-addr">0xe74A...40Ee</a>
                        <span class="whale-profit">+$434k</span>
                    </div>
                    <div class="whale-item">
                        <a href="https://polymarket.com/profile/0x492442eab586f242b53bda933fd5de859c8a3782" target="_blank" class="whale-addr">0x4924...3782</a>
                        <span class="whale-profit">+$1.42M</span>
                    </div>
                </div>
            </div>
            
            <!-- Math Section -->
            <div class="card">
                <h2>📐 The Math</h2>
                
                <h3>1. Signal Fusion (Weighted Average)</h3>
                <div class="math-block">
                    Signal = (Momentum × 0.4) + (Whale × 0.6)
                </div>
                
                <h3>2. Bayesian Update</h3>
                <div class="math-block">
                    P(direction | data) ∝ P(momentum | direction) × P(direction | whales)
                </div>
                
                <h3>3. Time-Weighted Decay</h3>
                <div class="math-block">
                    weight(t) = e<sup>-λt</sup> where λ = ln(2) / 6 hours
                </div>
                
                <h3>4. Confidence Interval</h3>
                <div class="math-block">
                    95% CI = μ ± 1.96 × (σ / √n)
                </div>
            </div>
            
            <!-- Features -->
            <div class="card">
                <h2>✨ New Features (v2.0)</h2>
                <ul>
                    <li><strong>EV-Net Logic</strong> - Kelly sizing with fee/slippage estimation</li>
                    <li><strong>Adaptive Thresholds</strong> - Target 15 trades/day, auto-adjusts</li>
                    <li><strong>Nighttime Mode</strong> - 2x stricter 11PM-7AM UTC</li>
                    <li><strong>Kill Switch</strong> - 10% daily loss limit protection</li>
                    <li><strong>Trade-Based Market Discovery</strong> - Finds active markets from trades</li>
                    <li><strong>Dynamic Whale ID</strong> - Volume-based whale identification</li>
                    <li><strong>SQLite Diagnostics</strong> - Full rejection breakdown logging</li>
                </ul>
            </div>
            
            <!-- Configuration -->
            <div class="card">
                <h2>⚙️ Configuration</h2>
                <div class="stat-row">
                    <span class="stat-label">Starting Bankroll</span>
                    <span class="stat-value">${{ config.bankroll }}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Bet Size</span>
                    <span class="stat-value">{{ config.bet_size }}% of bankroll</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Min Edge Threshold</span>
                    <span class="stat-value">{{ config.edge_threshold }}%</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Max Position</span>
                    <span class="stat-value">${{ config.max_position }}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Time Decay Half-Life</span>
                    <span class="stat-value">6 hours</span>
                </div>
            </div>
            
            <!-- Live Crypto Prices - 2 Column Width -->
            <div class="card" style="grid-column: span 2;">
                <h2>📈 Live Crypto Prices</h2>
                <p style="color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 1rem;">
                    Used for momentum signal calculation (CoinGecko API)
                </p>
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem;">
                    {% for coin in crypto_prices %}
                    <div style="background: var(--bg-secondary); border-radius: 8px; padding: 1rem; text-align: center;">
                        <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">{{ coin.icon }}</div>
                        <div style="font-weight: bold; color: var(--text-primary);">{{ coin.symbol }}</div>
                        <div class="bankroll-highlight" style="font-size: 1.1rem;">${{ "%.2f"|format(coin.price) if coin.price < 1000 else "%.0f"|format(coin.price) }}</div>
                        <div style="margin-top: 0.5rem;">
                            <span class="{{ 'pnl-positive' if coin.change >= 0 else 'pnl-negative' }}">
                                {{ "+" if coin.change >= 0 else "" }}{{ "%.2f"|format(coin.change) }}%
                            </span>
                            <span style="color: var(--text-secondary); font-size: 0.8rem;">15m</span>
                        </div>
                        <div style="margin-top: 0.3rem; font-size: 0.75rem; color: var(--text-secondary);">
                            Signal: <span style="color: {{ 'var(--success)' if coin.momentum > 0 else 'var(--danger)' if coin.momentum < 0 else 'var(--text-secondary)' }};">
                                {{ "↑ BULLISH" if coin.momentum > 0.5 else "↓ BEARISH" if coin.momentum < -0.5 else "→ NEUTRAL" }}
                            </span>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        
        <!-- How the Bot Trades - Full Width Section -->
        <div class="card" style="margin-bottom: 2rem;">
            <h2>🔄 How & When the Bot Trades</h2>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 2rem; margin-top: 1rem;">
                <!-- Trading Loop -->
                <div>
                    <h3>Trading Loop (Every 60 Seconds)</h3>
                    <div class="code-block" style="font-size: 0.8rem; line-height: 1.8;">
1. Fetch whale trades from Data API<br>
   ↓<br>
2. Identify whales (volume ≥ $50)<br>
   ↓<br>
3. Find crypto markets from trade data<br>
   ↓<br>
4. Fuse signals (60% whale + 40% momentum)<br>
   ↓<br>
5. Calculate EV-net (after fees/slippage)<br>
   ↓<br>
6. Execute if EV > 0 (Kelly-sized)
                    </div>
                </div>
                
                <!-- Decision Criteria -->
                <div>
                    <h3>When Does It Trade?</h3>
                    <p style="margin-bottom: 0.5rem;">The bot trades when:</p>
                    <ul>
                        <li>EV-net > 0 (after fees + slippage)</li>
                        <li>EV / bankroll > min threshold</li>
                        <li>Confidence above adaptive threshold</li>
                        <li>Not in kill switch mode</li>
                        <li>Daily trade limit not reached</li>
                        <li>Size ≤ 5% of bankroll</li>
                    </ul>
                </div>
                
                <!-- Signal Flow -->
                <div>
                    <h3>Signal Decision</h3>
                    <div class="math-block" style="font-size: 0.9rem; text-align: left; padding: 1rem;">
                        <strong>Momentum</strong> (40%) + <strong>Whale</strong> (60%)<br><br>
                        → Bayesian Update → Posterior Probability<br><br>
                        If posterior > 60% → <span style="color: var(--success);">BUY YES</span><br>
                        If posterior < 40% → <span style="color: var(--danger);">BUY NO</span><br>
                        Otherwise → <span style="color: var(--warning);">HOLD</span>
                    </div>
                </div>
            </div>
            
            <!-- Target Markets -->
            <div style="margin-top: 1.5rem; padding: 1rem; background: var(--bg-secondary); border-radius: 8px;">
                <h3 style="margin-bottom: 0.5rem;">🎯 Target Markets</h3>
                <p>15-Minute Crypto Binary Markets like:</p>
                <p style="color: var(--accent); font-style: italic;">"Will BTC be above $97,000 at 3:00 PM UTC?"</p>
                <p style="font-size: 0.85rem; margin-top: 0.5rem;">These resolve quickly (~15 min) allowing many small, high-frequency trades.</p>
            </div>
        </div>
        
        <!-- Recent Trades Section -->
        <div class="card" style="margin-bottom: 2rem;">
            <h2>📜 Recent Activity</h2>
            {% if recent_trades %}
            <table class="trade-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Market</th>
                        <th>Side</th>
                        <th>Size</th>
                        <th>Edge</th>
                        <th>Status</th>
                        <th>P&L</th>
                    </tr>
                </thead>
                <tbody>
                    {% for trade in recent_trades %}
                    <tr>
                        <td>{{ trade.timestamp[:16] if trade.timestamp else '-' }}</td>
                        <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            {{ trade.market_question if trade.market_question else trade.reason if trade.type == 'SKIP' else '-' }}
                        </td>
                        <td>
                            {% if trade.type == 'SKIP' %}
                                <span style="color: var(--warning);">SKIP</span>
                            {% else %}
                                <span style="color: {{ 'var(--success)' if trade.direction == 'YES' else 'var(--danger)' }};">
                                    {{ trade.direction }}
                                </span>
                            {% endif %}
                        </td>
                        <td>{{ "$%.2f"|format(trade.size) if trade.size else '-' }}</td>
                        <td>{{ "%.1f%%"|format(trade.edge) if trade.edge else '-' }}</td>
                        <td>
                            {% if trade.status == 'OPEN' %}
                                <span style="color: var(--accent);">OPEN</span>
                            {% elif trade.status == 'WON' %}
                                <span style="color: var(--success);">WON</span>
                            {% elif trade.status == 'LOST' %}
                                <span style="color: var(--danger);">LOST</span>
                            {% elif trade.type == 'SKIP' %}
                                <span style="color: var(--text-secondary);">-</span>
                            {% else %}
                                <span>{{ trade.status }}</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if trade.pnl is not none %}
                                <span class="{{ 'pnl-positive' if trade.pnl >= 0 else 'pnl-negative' }}">
                                    {{ "+" if trade.pnl >= 0 else "" }}${{ "%.2f"|format(trade.pnl) }}
                                </span>
                            {% else %}
                                -
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p style="color: var(--text-secondary); text-align: center; padding: 2rem;">
                No trades yet. Bot is scanning for opportunities...
            </p>
            {% endif %}
        </div>
        
        <footer style="height: 2rem;"></footer>
    </div>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Main dashboard page."""
    # Load whale stats if available
    whale_stats = {}
    try:
        if os.path.exists('whale_stats.json'):
            with open('whale_stats.json', 'r') as f:
                whale_stats = json.load(f)
    except:
        pass
    
    # Check if bot is running by looking for the process or a status file
    running = True  # Default to showing running - we started it
    try:
        # Check if status file exists (bot updates this)
        if os.path.exists('bot_status.txt'):
            with open('bot_status.txt', 'r') as f:
                running = f.read().strip() == 'running'
        else:
            # Check via process list for new_trader
            import subprocess
            result = subprocess.run(['pgrep', '-f', 'new_trader'], capture_output=True)
            running = result.returncode == 0
    except:
        running = True  # Assume running if check fails
    
    status = {
        'running': running,
        'mode': 'ACTIVE',
        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'whale_count': len(whale_stats) if whale_stats else 6
    }
    
    config = {
        'bankroll': 1000,
        'bet_size': 5,
        'edge_threshold': 10,
        'max_position': 50
    }
    
    # Get trading stats and recent trades
    trading_stats = {
        'initial_bankroll': 1000.0,
        'current_bankroll': 1000.0,
        'total_pnl': 0.0,
        'total_trades': 0,
        'open_positions': 0,
        'wins': 0,
        'losses': 0,
        'win_rate': 0.0
    }
    recent_trades = []
    
    try:
        if get_trade_logger is not None:
            logger = get_trade_logger()
            trading_stats = logger.get_stats()
            recent_trades = logger.get_recent_activity(10)
            # Reverse to show newest first
            recent_trades = list(reversed(recent_trades))
    except Exception as e:
        print(f"Error loading trade stats: {e}")
    
    # Fetch crypto prices from CoinGecko
    crypto_prices = [
        {'symbol': 'BTC', 'icon': '₿', 'price': 97000.0, 'change': 0.0, 'momentum': 0.0},
        {'symbol': 'ETH', 'icon': 'Ξ', 'price': 3300.0, 'change': 0.0, 'momentum': 0.0},
        {'symbol': 'SOL', 'icon': '◎', 'price': 185.0, 'change': 0.0, 'momentum': 0.0},
        {'symbol': 'XRP', 'icon': '✕', 'price': 2.30, 'change': 0.0, 'momentum': 0.0},
    ]
    
    try:
        import requests
        # CoinGecko API for price data
        coins = ['bitcoin', 'ethereum', 'solana', 'ripple']
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd&include_24hr_change=true"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if 'bitcoin' in data:
                crypto_prices[0]['price'] = data['bitcoin'].get('usd', 97000)
                crypto_prices[0]['change'] = data['bitcoin'].get('usd_24h_change', 0) / 96  # Approx 15min from 24h
                crypto_prices[0]['momentum'] = 1.0 if crypto_prices[0]['change'] > 0.1 else (-1.0 if crypto_prices[0]['change'] < -0.1 else 0.0)
            if 'ethereum' in data:
                crypto_prices[1]['price'] = data['ethereum'].get('usd', 3300)
                crypto_prices[1]['change'] = data['ethereum'].get('usd_24h_change', 0) / 96
                crypto_prices[1]['momentum'] = 1.0 if crypto_prices[1]['change'] > 0.1 else (-1.0 if crypto_prices[1]['change'] < -0.1 else 0.0)
            if 'solana' in data:
                crypto_prices[2]['price'] = data['solana'].get('usd', 185)
                crypto_prices[2]['change'] = data['solana'].get('usd_24h_change', 0) / 96
                crypto_prices[2]['momentum'] = 1.0 if crypto_prices[2]['change'] > 0.1 else (-1.0 if crypto_prices[2]['change'] < -0.1 else 0.0)
            if 'ripple' in data:
                crypto_prices[3]['price'] = data['ripple'].get('usd', 2.30)
                crypto_prices[3]['change'] = data['ripple'].get('usd_24h_change', 0) / 96
                crypto_prices[3]['momentum'] = 1.0 if crypto_prices[3]['change'] > 0.1 else (-1.0 if crypto_prices[3]['change'] < -0.1 else 0.0)
    except Exception as e:
        print(f"Error fetching crypto prices: {e}")
    
    return render_template_string(
        DASHBOARD_HTML, 
        status=status, 
        config=config,
        trading_stats=trading_stats,
        recent_trades=recent_trades,
        crypto_prices=crypto_prices
    )


@app.route('/api/status')
def api_status():
    """API endpoint for bot status."""
    import subprocess
    try:
        result = subprocess.run(['systemctl', 'is-active', 'polymarket-bot'], 
                               capture_output=True, text=True)
        running = result.stdout.strip() == 'active'
    except:
        running = False
    
    whale_stats = {}
    try:
        if os.path.exists('whale_stats.json'):
            with open('whale_stats.json', 'r') as f:
                whale_stats = json.load(f)
    except:
        pass
    
    return jsonify({
        'running': running,
        'whale_count': len(whale_stats),
        'timestamp': datetime.now().isoformat()
    })


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
