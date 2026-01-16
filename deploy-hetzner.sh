#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Polymarket Trading Bot - Hetzner Deployment Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# This script deploys the trading bot to a fresh Hetzner VPS (Ubuntu 24.04)
#
# Usage:
#   1. Create a Hetzner Cloud VPS (CX22 or CAX11, ~€4/month)
#   2. SSH into the server
#   3. Run: curl -sSL <this-script-url> | bash
#   OR copy this script and run locally after SSHing in
#
# ═══════════════════════════════════════════════════════════════════════════════

set -e

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "  🤖 POLYMARKET TRADING BOT - HETZNER DEPLOYMENT"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────────────────────────────────────────────
# 1. SYSTEM SETUP
# ─────────────────────────────────────────────────────────────────────────────────

echo "📦 Updating system packages..."
sudo apt update && sudo apt upgrade -y

echo "📦 Installing Python 3.12 and dependencies..."
sudo apt install -y python3.12 python3.12-venv python3-pip git ufw

# ─────────────────────────────────────────────────────────────────────────────────
# 2. FIREWALL SETUP
# ─────────────────────────────────────────────────────────────────────────────────

echo "🔒 Configuring firewall (SSH only)..."
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw --force enable

# ─────────────────────────────────────────────────────────────────────────────────
# 3. CREATE BOT USER
# ─────────────────────────────────────────────────────────────────────────────────

echo "👤 Creating bot user..."
if ! id "tradingbot" &>/dev/null; then
    sudo useradd -m -s /bin/bash tradingbot
fi

# ─────────────────────────────────────────────────────────────────────────────────
# 4. SETUP BOT DIRECTORY
# ─────────────────────────────────────────────────────────────────────────────────

BOT_DIR="/opt/polymarket-bot"
echo "📁 Setting up bot directory at $BOT_DIR..."

sudo mkdir -p $BOT_DIR
sudo chown tradingbot:tradingbot $BOT_DIR

# ─────────────────────────────────────────────────────────────────────────────────
# 5. UPLOAD BOT FILES
# ─────────────────────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo "  📤 UPLOAD YOUR BOT FILES"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""
echo "From your LOCAL machine, run:"
echo ""
echo "  scp -r 'Trading Bot/'* root@YOUR_SERVER_IP:$BOT_DIR/"
echo ""
echo "Then create .env file:"
echo ""
echo "  ssh root@YOUR_SERVER_IP"
echo "  cd $BOT_DIR"
echo "  cp .env.example .env"
echo "  nano .env  # Add your credentials"
echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"

# ─────────────────────────────────────────────────────────────────────────────────
# 6. SETUP PYTHON VENV
# ─────────────────────────────────────────────────────────────────────────────────

echo "🐍 Setting up Python virtual environment..."
sudo -u tradingbot bash << 'EOF'
cd /opt/polymarket-bot
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
EOF

# ─────────────────────────────────────────────────────────────────────────────────
# 7. INSTALL SYSTEMD SERVICE
# ─────────────────────────────────────────────────────────────────────────────────

echo "⚙️ Installing systemd service..."
sudo tee /etc/systemd/system/polymarket-bot.service > /dev/null << 'EOF'
[Unit]
Description=Polymarket Crypto Trading Bot
After=network.target

[Service]
Type=simple
User=tradingbot
Group=tradingbot
WorkingDirectory=/opt/polymarket-bot
Environment="PATH=/opt/polymarket-bot/venv/bin"
ExecStart=/opt/polymarket-bot/venv/bin/python crypto_trader.py --dry-run
Restart=always
RestartSec=30

# Logging
StandardOutput=append:/opt/polymarket-bot/bot.log
StandardError=append:/opt/polymarket-bot/bot.log

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable polymarket-bot

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo "  ✅ DEPLOYMENT COMPLETE"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Upload your bot files (see instructions above)"
echo ""
echo "  2. Configure credentials:"
echo "     cd $BOT_DIR && nano .env"
echo ""
echo "  3. Test the bot:"
echo "     cd $BOT_DIR && ./venv/bin/python crypto_trader.py --scan"
echo ""
echo "  4. Start the service (DRY RUN mode):"
echo "     sudo systemctl start polymarket-bot"
echo ""
echo "  5. Check logs:"
echo "     tail -f $BOT_DIR/bot.log"
echo "     journalctl -u polymarket-bot -f"
echo ""
echo "  6. When ready for LIVE trading, edit the service:"
echo "     sudo nano /etc/systemd/system/polymarket-bot.service"
echo "     Change: --dry-run  →  --live"
echo "     sudo systemctl daemon-reload && sudo systemctl restart polymarket-bot"
echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
