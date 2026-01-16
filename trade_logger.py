"""
Trade Logger Module
===================
Persistent trade logging with file storage and dashboard integration.

Features:
- Log executed trades with full details
- Track open positions and outcomes
- Calculate live PnL
- Persist to JSON lines file
"""

import json
import os
from datetime import datetime
from collections import deque
from typing import Optional, List, Dict, Any
# Note: Threading removed for simplicity in single-process Flask app

# ═══════════════════════════════════════════════════════════════════════════════
# TRADE LOGGER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class TradeLogger:
    """Manages trade logging, persistence, and PnL tracking."""
    
    def __init__(self, log_file: str = "bot_trades.log", bankroll_file: str = "bankroll.json"):
        self.log_file = log_file
        self.bankroll_file = bankroll_file
        self.trades: deque = deque(maxlen=100)  # Keep last 100 trades in memory
        
        # Load initial bankroll
        self.initial_bankroll = 1000.0
        self.current_bankroll = self._load_bankroll()
        
        # Load existing trades on startup
        self._load_trades()
    
    def _load_bankroll(self) -> float:
        """Load current bankroll from file."""
        try:
            if os.path.exists(self.bankroll_file):
                with open(self.bankroll_file, 'r') as f:
                    data = json.load(f)
                    return data.get('current', self.initial_bankroll)
        except Exception as e:
            print(f"Error loading bankroll: {e}")
        return self.initial_bankroll
    
    def _save_bankroll(self):
        """Save current bankroll to file."""
        try:
            with open(self.bankroll_file, 'w') as f:
                json.dump({
                    'initial': self.initial_bankroll,
                    'current': self.current_bankroll,
                    'last_updated': datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"Error saving bankroll: {e}")
    
    def _load_trades(self):
        """Load trades from log file on startup."""
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            trade = json.loads(line)
                            self.trades.append(trade)
        except Exception as e:
            print(f"Error loading trades: {e}")
    
    def log_trade(
        self,
        market_id: str,
        market_question: str,
        direction: str,  # "YES" or "NO"
        size: float,
        price: float,
        edge: float,
        confidence: float,
        whale_signal: float = 0.0,
        momentum_signal: float = 0.0
    ) -> str:
        """
        Log a new trade execution.
        
        Returns: trade_id for later outcome updates
        """
        trade_id = f"T{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        trade = {
            'trade_id': trade_id,
            'timestamp': datetime.now().isoformat(),
            'market_id': market_id,
            'market_question': market_question[:60] + '...' if len(market_question) > 60 else market_question,
            'direction': direction,
            'size': round(size, 2),
            'price': round(price, 4),
            'edge': round(edge * 100, 2),  # Store as percentage
            'confidence': round(confidence * 100, 2),
            'whale_signal': round(whale_signal, 4),
            'momentum_signal': round(momentum_signal, 4),
            'status': 'OPEN',  # OPEN, WON, LOST, CANCELLED
            'outcome': None,
            'pnl': None
        }
        
        self.trades.append(trade)
        self._append_to_file(trade)
        
        # Deduct size from bankroll
        self.current_bankroll -= size
        self._save_bankroll()
        
        return trade_id
    
    def log_outcome(self, trade_id: str, won: bool, pnl: float):
        """Update a trade with its outcome after market resolution."""
        for trade in self.trades:
            if trade['trade_id'] == trade_id:
                trade['status'] = 'WON' if won else 'LOST'
                trade['outcome'] = 'WON' if won else 'LOST'
                trade['pnl'] = round(pnl, 2)
                
                # Update bankroll
                if won:
                    # Return size + profit
                    self.current_bankroll += trade['size'] + pnl
                # If lost, size was already deducted
                
                self._save_bankroll()
                self._rewrite_trades_file()
                break
    
    def log_skip(self, market_question: str, reason: str):
        """Log a skipped trade opportunity with reason."""
        skip_entry = {
            'timestamp': datetime.now().isoformat(),
            'type': 'SKIP',
            'market_question': market_question[:60] + '...' if len(market_question) > 60 else market_question,
            'reason': reason
        }
        
        self.trades.append(skip_entry)
        self._append_to_file(skip_entry)
    
    def _append_to_file(self, trade: Dict):
        """Append a single trade to the log file."""
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(trade) + '\n')
        except Exception as e:
            print(f"Error writing trade: {e}")
    
    def _rewrite_trades_file(self):
        """Rewrite entire trades file (for updates)."""
        try:
            with open(self.log_file, 'w') as f:
                for trade in self.trades:
                    f.write(json.dumps(trade) + '\n')
        except Exception as e:
            print(f"Error rewriting trades: {e}")
    
    def get_recent_trades(self, n: int = 10) -> List[Dict]:
        """Get the last N trades (excluding skips)."""
        trades = [t for t in self.trades if t.get('type') != 'SKIP']
        return list(trades)[-n:]
    
    def get_recent_activity(self, n: int = 10) -> List[Dict]:
        """Get the last N activities (including skips)."""
        return list(self.trades)[-n:]
    
    def get_open_positions(self) -> List[Dict]:
        """Get all trades that are still open (unresolved)."""
        return [t for t in self.trades if t.get('status') == 'OPEN']
    
    def get_total_pnl(self) -> float:
        """Calculate total realized PnL from all resolved trades."""
        total = 0.0
        for trade in self.trades:
            if trade.get('pnl') is not None:
                total += trade['pnl']
        return round(total, 2)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get trading statistics."""
        resolved = [t for t in self.trades if t.get('status') in ['WON', 'LOST']]
        wins = len([t for t in resolved if t.get('status') == 'WON'])
        losses = len([t for t in resolved if t.get('status') == 'LOST'])
        
        total_pnl = 0.0
        for trade in self.trades:
            if trade.get('pnl') is not None:
                total_pnl += trade['pnl']
        
        return {
            'initial_bankroll': self.initial_bankroll,
            'current_bankroll': round(self.current_bankroll, 2),
            'total_pnl': round(total_pnl, 2),
            'total_trades': len([t for t in self.trades if t.get('type') != 'SKIP']),
            'open_positions': len([t for t in self.trades if t.get('status') == 'OPEN']),
            'wins': wins,
            'losses': losses,
            'win_rate': round(wins / len(resolved) * 100, 1) if resolved else 0.0
        }


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

# Singleton instance
_logger: Optional[TradeLogger] = None

def get_trade_logger() -> TradeLogger:
    """Get or create the global trade logger instance."""
    global _logger
    if _logger is None:
        _logger = TradeLogger()
    return _logger


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def log_trade(**kwargs) -> str:
    """Convenience function to log a trade."""
    return get_trade_logger().log_trade(**kwargs)

def log_skip(market_question: str, reason: str):
    """Convenience function to log a skipped trade."""
    get_trade_logger().log_skip(market_question, reason)

def log_outcome(trade_id: str, won: bool, pnl: float):
    """Convenience function to log trade outcome."""
    get_trade_logger().log_outcome(trade_id, won, pnl)

def get_stats() -> Dict[str, Any]:
    """Convenience function to get stats."""
    return get_trade_logger().get_stats()
