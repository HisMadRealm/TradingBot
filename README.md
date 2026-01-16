# 🧬🐳 Polymarket Advanced Trading Bot

Meta-trading bot with **advanced statistical whale aggregation

## Advanced Features

| Feature | Description |
|---------|-------------|
| **Time-weighted signals** | Exponential decay (6h half-life) - recent trades matter more |
| **Bayesian fusion** | Whale signals as prior, momentum as likelihood |
| **Rolling accuracy** | Per-whale win rate tracking (last 20 trades) |
| **Lead-lag analysis** | Granger causality to find whales who trade first |
| **Gaussian Process** | Probabilistic trajectory forecasting |
| **Category accuracy** | Track whale performance by market type |
| **Dynamic sizing** | Bet multiplier based on signal confidence |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Advanced scan (recommended first)
python advanced_trader.py --scan

# Dry run
python advanced_trader.py --dry-run

# Live trading
python advanced_trader.py --live
```

## Bot Versions

| Bot | Description | Command |
|-----|-------------|---------|
| `advanced_trader.py` | **Full statistics** - GP, Bayesian, lead-lag | `python advanced_trader.py --scan` |
| `unified_trader.py` | **Simpler** - weighted fusion only | `python unified_trader.py --scan` |
| `crypto_trader.py` | **Momentum only** - no whale signals | `python crypto_trader.py --scan` |

## Signal Math

### Bayesian Update
```
posterior = P(direction | whales, momentum)
         ∝ P(momentum | direction) × P(direction | whales)
```

### Time Decay
```
weight(trade) = exp(-λ × hours_ago)
λ = ln(2) / half_life  # 6 hours default
```

### Dynamic Bet Sizing
```
multiplier = 1.0 + min(1.0, confidence × signal_to_noise / 2)
# Range: 1.0x to 2.0x base size
```

## Whale Stats Tracking

The bot persists whale performance to `whale_stats.json`:
- Total trades and win rate
- Recent 20 trades win rate
- Category-specific accuracy (crypto, politics, sports)
- Lead score (from Granger causality)
- Rolling weight (EMA of performance)

## Files

| File | Purpose |
|------|---------|
| `advanced_trader.py` | Main advanced bot |
| `advanced_aggregator.py` | Statistical aggregation |
| `signal_aggregator.py` | Simple aggregator |
| `whale_collector.py` | Fetch whale data |
| `price_feed.py` | Momentum signals |
| `executor.py` | CLOB orders |
| `whale_stats.json` | Persisted whale performance |

## Deployment

```bash
# Copy to Hetzner
scp -r "Trading Bot/"* root@YOUR_IP:/opt/polymarket-bot/

# On server
./deploy-hetzner.sh
sudo systemctl start polymarket-bot
tail -f bot.log
```

## ⚠️ Warnings

- **Real money at risk**
- **No guarantees** - past whale performance ≠ future results
- **Test with `--dry-run` first**
- Polymarket has fees on 15-min markets (Jan 2026)
