"""
Polymarket Trading Bot - Threshold Controller
==============================================
Adaptive threshold management based on trade frequency and drawdown.

Features:
- Adjusts min_ev_frac and min_confidence based on trade count
- Loosens thresholds if trades < target, tightens if > target
- Nighttime mode with stricter limits
- Respects drawdown kill switch

Created: Jan 2026
"""

import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ThresholdState:
    """Current threshold configuration."""
    min_ev_frac: float = 0.001      # Minimum EV as fraction of bankroll
    min_confidence: float = 0.25     # Minimum signal confidence
    max_position_pct: float = 0.05   # Maximum position size
    
    # Derived from base
    base_min_ev_frac: float = 0.001
    base_min_confidence: float = 0.25
    
    # Adjustment factors
    adjustment_factor: float = 1.0   # Multiplier on base thresholds
    
    # Time-based
    is_nighttime: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "min_ev_frac": self.min_ev_frac,
            "min_confidence": self.min_confidence,
            "max_position_pct": self.max_position_pct,
            "adjustment_factor": self.adjustment_factor,
            "is_nighttime": self.is_nighttime
        }


@dataclass 
class TradingSession:
    """Tracks daily trading activity."""
    date: str
    trades_executed: int = 0
    trades_profitable: int = 0
    total_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    peak_bankroll: float = 0.0
    current_bankroll: float = 0.0
    
    @property
    def win_rate(self) -> float:
        if self.trades_executed == 0:
            return 0.0
        return self.trades_profitable / self.trades_executed


# ═══════════════════════════════════════════════════════════════════════════════
# THRESHOLD CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════════

class ThresholdController:
    """
    Manages adaptive trading thresholds based on market conditions
    and trading performance.
    
    - Target: 5-25 trades per day
    - Loosens thresholds if under-trading
    - Tightens thresholds if over-trading or drawdown rising
    - Nighttime (11PM-7AM) has 2x stricter thresholds
    """
    
    def __init__(
        self,
        target_trades_per_day: int = 15,
        min_trades_per_day: int = 5,
        max_trades_per_day: int = 25,
        max_daily_loss_pct: float = 0.10,  # 10% daily loss = kill switch
        data_file: str = "thresholds.json"
    ):
        self.target_trades = target_trades_per_day
        self.min_trades = min_trades_per_day
        self.max_trades = max_trades_per_day
        self.max_daily_loss_pct = max_daily_loss_pct
        self.data_file = Path(data_file)
        
        # Current state
        self.state = ThresholdState()
        self.session = TradingSession(date=self._today())
        
        # Kill switch
        self.kill_switch_active = False
        self.kill_switch_reason: Optional[str] = None
        
        # Load persisted state
        self._load_state()
    
    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    def _current_hour(self) -> int:
        return datetime.now(timezone.utc).hour
    
    def _load_state(self):
        """Load state from disk."""
        if self.data_file.exists():
            try:
                with open(self.data_file) as f:
                    data = json.load(f)
                    
                    # Load session if same day
                    session_data = data.get("session", {})
                    if session_data.get("date") == self._today():
                        self.session = TradingSession(**session_data)
                    
                    # Check if kill switch was active
                    if data.get("kill_switch_active"):
                        self.kill_switch_active = True
                        self.kill_switch_reason = data.get("kill_switch_reason")
            except Exception as e:
                logger.warning(f"Failed to load threshold state: {e}")
    
    def _save_state(self):
        """Persist state to disk."""
        data = {
            "state": self.state.to_dict(),
            "session": {
                "date": self.session.date,
                "trades_executed": self.session.trades_executed,
                "trades_profitable": self.session.trades_profitable,
                "total_pnl": self.session.total_pnl,
                "max_drawdown_pct": self.session.max_drawdown_pct,
                "peak_bankroll": self.session.peak_bankroll,
                "current_bankroll": self.session.current_bankroll
            },
            "kill_switch_active": self.kill_switch_active,
            "kill_switch_reason": self.kill_switch_reason
        }
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def is_nighttime(self) -> bool:
        """Check if we're in nighttime mode (11PM - 7AM UTC)."""
        hour = self._current_hour()
        return hour >= 23 or hour < 7
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed.
        
        Returns:
            (can_trade, reason)
        """
        # Kill switch check
        if self.kill_switch_active:
            return False, f"Kill switch active: {self.kill_switch_reason}"
        
        # Reset session if new day
        if self.session.date != self._today():
            self.session = TradingSession(date=self._today())
            self.kill_switch_active = False
            self.kill_switch_reason = None
            logger.info("Reset trading session for new day")
        
        # Check daily trade limit
        if self.session.trades_executed >= self.max_trades:
            return False, f"Daily trade limit reached ({self.max_trades})"
        
        return True, "OK"
    
    def update_thresholds(self, current_bankroll: float, starting_bankroll: float):
        """
        Update thresholds based on current performance.
        
        Call this at the start of each trading cycle.
        """
        # Update session bankroll tracking
        self.session.current_bankroll = current_bankroll
        if current_bankroll > self.session.peak_bankroll:
            self.session.peak_bankroll = current_bankroll
        
        # Calculate drawdown
        if self.session.peak_bankroll > 0:
            drawdown = (self.session.peak_bankroll - current_bankroll) / self.session.peak_bankroll
            self.session.max_drawdown_pct = max(self.session.max_drawdown_pct, drawdown)
        
        # Check for daily loss limit (kill switch)
        daily_pnl_pct = (current_bankroll - starting_bankroll) / starting_bankroll if starting_bankroll > 0 else 0
        if daily_pnl_pct < -self.max_daily_loss_pct:
            self.kill_switch_active = True
            self.kill_switch_reason = f"Daily loss limit exceeded ({daily_pnl_pct:.1%})"
            logger.warning(f"KILL SWITCH ACTIVATED: {self.kill_switch_reason}")
            self._save_state()
            return
        
        # Calculate trade rate adjustment
        hour_of_day = self._current_hour()
        hours_elapsed = max(1, hour_of_day if hour_of_day > 0 else 1)
        expected_trades = (hours_elapsed / 24) * self.target_trades
        
        # Calculate adjustment factor
        if expected_trades > 0:
            trade_rate = self.session.trades_executed / expected_trades
        else:
            trade_rate = 1.0
        
        # Adjust thresholds
        if trade_rate < 0.5:
            # Under-trading: loosen thresholds (but cap at 50% looser)
            self.state.adjustment_factor = max(0.5, 1.0 - (0.5 - trade_rate))
        elif trade_rate > 1.5:
            # Over-trading: tighten thresholds (but cap at 2x stricter)
            self.state.adjustment_factor = min(2.0, 1.0 + (trade_rate - 1.5))
        else:
            # On target: gradual return to baseline
            self.state.adjustment_factor = 0.9 * self.state.adjustment_factor + 0.1 * 1.0
        
        # Apply nighttime multiplier
        self.state.is_nighttime = self.is_nighttime()
        night_multiplier = 2.0 if self.state.is_nighttime else 1.0
        
        # Apply drawdown multiplier (tighten if in drawdown)
        drawdown_multiplier = 1.0
        if self.session.max_drawdown_pct > 0.05:
            drawdown_multiplier = 1.0 + self.session.max_drawdown_pct * 2
        
        # Calculate final thresholds
        total_multiplier = self.state.adjustment_factor * night_multiplier * drawdown_multiplier
        self.state.min_ev_frac = self.state.base_min_ev_frac * total_multiplier
        self.state.min_confidence = min(0.8, self.state.base_min_confidence * total_multiplier)
        
        logger.debug(
            f"Thresholds: adj={self.state.adjustment_factor:.2f}, "
            f"night={night_multiplier:.1f}, drawdown={drawdown_multiplier:.2f} → "
            f"min_ev={self.state.min_ev_frac:.4f}, min_conf={self.state.min_confidence:.2f}"
        )
        
        self._save_state()
    
    def record_trade(self, pnl: float):
        """Record a completed trade."""
        self.session.trades_executed += 1
        self.session.total_pnl += pnl
        if pnl > 0:
            self.session.trades_profitable += 1
        
        self._save_state()
    
    def get_thresholds(self) -> ThresholdState:
        """Get current threshold state."""
        return self.state
    
    def reset_kill_switch(self):
        """Manually reset the kill switch (use with caution)."""
        self.kill_switch_active = False
        self.kill_switch_reason = None
        self._save_state()
        logger.info("Kill switch manually reset")
    
    def print_status(self):
        """Print current status."""
        print(f"\n{'═' * 50}")
        print(f"📊 THRESHOLD CONTROLLER STATUS")
        print(f"{'═' * 50}")
        print(f"  Date: {self.session.date}")
        print(f"  Trades: {self.session.trades_executed} / {self.target_trades} target")
        print(f"  Win Rate: {self.session.win_rate:.1%}")
        print(f"  PnL: ${self.session.total_pnl:.2f}")
        print(f"  Max Drawdown: {self.session.max_drawdown_pct:.1%}")
        print()
        print(f"  Thresholds:")
        print(f"    Min EV Frac: {self.state.min_ev_frac:.4f}")
        print(f"    Min Confidence: {self.state.min_confidence:.2f}")
        print(f"    Adjustment: {self.state.adjustment_factor:.2f}x")
        print(f"    Nighttime Mode: {'YES' if self.state.is_nighttime else 'NO'}")
        print()
        can, reason = self.can_trade()
        print(f"  Can Trade: {'✅' if can else '❌'} {reason}")
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    controller = ThresholdController()
    
    # Simulate some trades
    controller.update_thresholds(current_bankroll=1000, starting_bankroll=1000)
    controller.print_status()
    
    # Simulate a profitable trade
    controller.record_trade(pnl=10.0)
    controller.update_thresholds(current_bankroll=1010, starting_bankroll=1000)
    controller.print_status()
