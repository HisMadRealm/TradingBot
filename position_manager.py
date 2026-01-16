"""
Polymarket Trading Bot - Position Manager
==========================================
Bankroll management, position tracking, and risk controls.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
import logging

from config import Config

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    """Record of a single trade."""
    trade_id: str
    market_id: str
    market_question: str
    coin_symbol: str
    direction: str          # "UP" or "DOWN"
    action: str             # "BUY_YES" or "BUY_NO"
    size_usd: float
    entry_price: float
    predicted_prob: float
    market_prob: float
    edge: float
    status: str = "OPEN"    # OPEN, WON, LOST, CANCELLED
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class DailyStats:
    """Daily trading statistics."""
    date: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    volume: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# POSITION MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class PositionManager:
    """
    Manages bankroll, tracks positions, and enforces risk limits.
    """
    
    def __init__(self, data_file: str = "positions.json"):
        self.data_file = data_file
        
        # Current state
        self.bankroll: float = Config.trading.bankroll_start
        self.starting_bankroll: float = Config.trading.bankroll_start
        self.trades: List[Trade] = []
        self.open_positions: Dict[str, Trade] = {}  # market_id -> Trade
        
        # Daily tracking
        self.daily_stats: Dict[str, DailyStats] = {}
        self.session_start = datetime.utcnow()
        
        # Load persisted state
        self._load_state()
    
    def _load_state(self):
        """Load state from disk."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.bankroll = data.get("bankroll", self.bankroll)
                    self.starting_bankroll = data.get("starting_bankroll", self.starting_bankroll)
                    logger.info(f"Loaded state: bankroll=${self.bankroll:.2f}")
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")
    
    def _save_state(self):
        """Persist state to disk."""
        try:
            data = {
                "bankroll": self.bankroll,
                "starting_bankroll": self.starting_bankroll,
                "last_updated": datetime.utcnow().isoformat(),
                "open_positions": {k: v.to_dict() for k, v in self.open_positions.items()},
                "recent_trades": [t.to_dict() for t in self.trades[-50:]]
            }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # RISK CHECKS
    # ─────────────────────────────────────────────────────────────────────────
    
    def can_trade(self) -> tuple[bool, str]:
        """Check if we're allowed to trade."""
        
        # Check minimum bankroll
        if self.bankroll < Config.trading.min_bankroll:
            return False, f"Bankroll ${self.bankroll:.2f} below minimum ${Config.trading.min_bankroll}"
        
        # Check daily loss limit
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today in self.daily_stats:
            daily = self.daily_stats[today]
            max_daily_loss = self.starting_bankroll * 0.20  # 20% daily loss limit
            if daily.pnl < -max_daily_loss:
                return False, f"Daily loss limit reached (${daily.pnl:.2f})"
        
        return True, "OK"
    
    def calculate_position_size(self) -> float:
        """Calculate position size for next trade."""
        size = self.bankroll * Config.trading.bet_size_percent
        
        # Cap at max position
        size = min(size, Config.trading.max_position_usd)
        
        # Ensure we have enough
        size = min(size, self.bankroll * 0.95)  # Leave 5% buffer
        
        return round(size, 2)
    
    def has_position(self, market_id: str) -> bool:
        """Check if we already have a position in this market."""
        return market_id in self.open_positions
    
    # ─────────────────────────────────────────────────────────────────────────
    # TRADE RECORDING
    # ─────────────────────────────────────────────────────────────────────────
    
    def record_trade(self, trade: Trade):
        """Record a new trade."""
        self.trades.append(trade)
        self.open_positions[trade.market_id] = trade
        
        # Update bankroll (deduct position size)
        self.bankroll -= trade.size_usd
        
        # Update daily stats
        self._update_daily_stats(trade)
        
        # Save
        self._save_state()
        
        logger.info(f"Recorded trade: {trade.coin_symbol} {trade.action} ${trade.size_usd:.2f}")
    
    def close_trade(self, market_id: str, won: bool, exit_price: float):
        """Close an open trade."""
        if market_id not in self.open_positions:
            return
        
        trade = self.open_positions[market_id]
        
        if won:
            # Won: get back position value at $1 minus fees
            pnl = (trade.size_usd / trade.entry_price) - trade.size_usd
            pnl *= 0.98  # 2% fee assumption
            trade.status = "WON"
        else:
            # Lost: lose entire position
            pnl = -trade.size_usd
            trade.status = "LOST"
        
        trade.exit_price = exit_price
        trade.pnl = pnl
        
        # Update bankroll
        if won:
            self.bankroll += trade.size_usd + pnl
        
        # Update daily stats
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today in self.daily_stats:
            self.daily_stats[today].pnl += pnl
            if won:
                self.daily_stats[today].wins += 1
            else:
                self.daily_stats[today].losses += 1
        
        # Remove from open
        del self.open_positions[market_id]
        
        self._save_state()
        
        logger.info(f"Closed trade: {trade.coin_symbol} - {'WON' if won else 'LOST'} ${pnl:+.2f}")
    
    def _update_daily_stats(self, trade: Trade):
        """Update daily statistics."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        if today not in self.daily_stats:
            self.daily_stats[today] = DailyStats(date=today)
        
        self.daily_stats[today].trades += 1
        self.daily_stats[today].volume += trade.size_usd
    
    # ─────────────────────────────────────────────────────────────────────────
    # REPORTING
    # ─────────────────────────────────────────────────────────────────────────
    
    def get_session_stats(self) -> Dict:
        """Get current session statistics."""
        total_trades = len(self.trades)
        won = sum(1 for t in self.trades if t.status == "WON")
        lost = sum(1 for t in self.trades if t.status == "LOST")
        total_pnl = sum(t.pnl or 0 for t in self.trades)
        
        return {
            "session_start": self.session_start.isoformat(),
            "bankroll": self.bankroll,
            "starting_bankroll": self.starting_bankroll,
            "pnl": total_pnl,
            "pnl_percent": (total_pnl / self.starting_bankroll) * 100 if self.starting_bankroll else 0,
            "total_trades": total_trades,
            "wins": won,
            "losses": lost,
            "win_rate": (won / total_trades * 100) if total_trades else 0,
            "open_positions": len(self.open_positions)
        }
    
    def print_status(self):
        """Print current status."""
        stats = self.get_session_stats()
        
        print(f"\n{'═' * 60}")
        print(f"💰 POSITION MANAGER STATUS")
        print(f"{'═' * 60}")
        print(f"   Bankroll:    ${stats['bankroll']:,.2f} ({stats['pnl']:+.2f})")
        print(f"   Trades:      {stats['total_trades']} ({stats['wins']}W / {stats['losses']}L)")
        print(f"   Win Rate:    {stats['win_rate']:.1f}%")
        print(f"   Open Pos:    {stats['open_positions']}")
        print(f"{'═' * 60}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    pm = PositionManager()
    pm.print_status()
    
    can_trade, reason = pm.can_trade()
    print(f"Can trade: {can_trade} ({reason})")
    print(f"Position size: ${pm.calculate_position_size():.2f}")
