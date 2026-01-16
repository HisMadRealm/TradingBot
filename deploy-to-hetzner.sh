#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Polymarket Trading Bot - Deploy to Hetzner
# Server: 178.156.208.100 (TradingBot - CPX11, Ashburn VA)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Run this from your LOCAL machine (Mac):
#   chmod +x deploy-to-hetzner.sh
#   ./deploy-to-hetzner.sh
#
# ═══════════════════════════════════════════════════════════════════════════════

set -e

SERVER="178.156.208.100"
USER="root"
REMOTE_DIR="/opt/polymarket-bot"
LOCAL_DIR="$(dirname "$0")"

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo "  🚀 DEPLOYING POLYMARKET TRADING BOT"
echo "     Server: $SERVER"
echo "     Target: $REMOTE_DIR"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────────────────────────────────────────────
# 1. CREATE REMOTE DIRECTORY
# ─────────────────────────────────────────────────────────────────────────────────

echo "📁 Creating remote directory..."
ssh $USER@$SERVER "mkdir -p $REMOTE_DIR"

# ─────────────────────────────────────────────────────────────────────────────────
# 2. UPLOAD BOT FILES
# ─────────────────────────────────────────────────────────────────────────────────

echo "📤 Uploading bot files..."
rsync -avz --progress \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'venv' \
    --exclude '.DS_Store' \
    "$LOCAL_DIR/" $USER@$SERVER:$REMOTE_DIR/

# ─────────────────────────────────────────────────────────────────────────────────
# 3. SETUP ON SERVER
# ─────────────────────────────────────────────────────────────────────────────────

echo "⚙️ Setting up on server..."
ssh $USER@$SERVER << 'REMOTE_SCRIPT'
set -e

cd /opt/polymarket-bot

echo "📦 Installing Python and dependencies..."
apt-get update -qq
apt-get install -y -qq python3.12 python3.12-venv python3-pip ufw

echo "🐍 Creating virtual environment..."
python3.12 -m venv venv
source venv/bin/activate

echo "📦 Installing Python packages..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "🔒 Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable

echo "⚙️ Installing systemd service..."
cp polymarket-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-bot

echo ""
echo "✅ Setup complete!"
REMOTE_SCRIPT

# ─────────────────────────────────────────────────────────────────────────────────
# 4. DONE
# ─────────────────────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo "  ✅ DEPLOYMENT COMPLETE!"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""
echo "  Next steps:"
echo ""
echo "  1. SSH into your server:"
echo "     ssh root@$SERVER"
echo ""
echo "  2. Verify .env file has your credentials:"
echo "     cat $REMOTE_DIR/.env"
echo ""
echo "  3. Test the bot (dry run):"
echo "     cd $REMOTE_DIR && ./venv/bin/python new_trader.py --scan"
echo ""
echo "  4. Start the bot service:"
echo "     systemctl start polymarket-bot"
echo ""
echo "  5. View logs:"
echo "     tail -f $REMOTE_DIR/bot.log"
echo "     journalctl -u polymarket-bot -f"
echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
