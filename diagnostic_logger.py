"""
Polymarket Trading Bot - Diagnostic Logger
===========================================
Structured logging for trade candidates with SQLite persistence.

Features:
- Log every market candidate with full decision metrics
- Track rejections by reason
- Generate rejection breakdown reports
- SQLite persistence for analysis

Created: Jan 2026
"""

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketCandidate:
    """Full decision record for a market candidate."""
    timestamp: str
    market_id: str
    market_question: str
    coin_symbol: str
    direction: str
    
    # Probabilities
    p_model_raw: float          # Raw model probability
    p_model_calibrated: float   # Calibrated probability
    p_market: float             # Market implied probability
    
    # Edge calculations
    edge_raw: float             # Raw edge = p_model - p_market
    edge_net: float             # Net edge after costs
    fees_est: float             # Estimated fees
    slippage_est: float         # Estimated slippage
    
    # Uncertainty
    ci_low: float               # 95% CI lower bound
    ci_high: float              # 95% CI upper bound
    confidence: float           # Confidence score 0-1
    
    # Market conditions
    liquidity: float            # Market liquidity USD
    volume_24h: float           # 24h volume
    spread: float               # Bid-ask spread
    
    # Sizing
    kelly_fraction: float       # Kelly criterion fraction
    size_usd: float             # Proposed trade size
    bankroll: float             # Current bankroll
    
    # Decision
    final_decision: str         # "TRADE" or "REJECT"
    rejection_reasons: List[str] # List of rejection reasons
    
    # EV calculation
    ev_net: float               # Net expected value
    ev_per_bankroll: float      # EV as % of bankroll


# ═══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC LOGGER
# ═══════════════════════════════════════════════════════════════════════════════

class DiagnosticLogger:
    """
    Logs trade candidates with full decision metrics.
    Persists to SQLite for analysis and reporting.
    """
    
    def __init__(self, db_path: str = "diagnostic_log.db"):
        self.db_path = Path(db_path)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    market_id TEXT NOT NULL,
                    market_question TEXT,
                    coin_symbol TEXT,
                    direction TEXT,
                    p_model_raw REAL,
                    p_model_calibrated REAL,
                    p_market REAL,
                    edge_raw REAL,
                    edge_net REAL,
                    fees_est REAL,
                    slippage_est REAL,
                    ci_low REAL,
                    ci_high REAL,
                    confidence REAL,
                    liquidity REAL,
                    volume_24h REAL,
                    spread REAL,
                    kelly_fraction REAL,
                    size_usd REAL,
                    bankroll REAL,
                    final_decision TEXT,
                    rejection_reasons TEXT,
                    ev_net REAL,
                    ev_per_bankroll REAL
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON candidates(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision 
                ON candidates(final_decision)
            """)
            conn.commit()
    
    def log_candidate(self, candidate: MarketCandidate):
        """Log a market candidate to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO candidates (
                    timestamp, market_id, market_question, coin_symbol, direction,
                    p_model_raw, p_model_calibrated, p_market,
                    edge_raw, edge_net, fees_est, slippage_est,
                    ci_low, ci_high, confidence,
                    liquidity, volume_24h, spread,
                    kelly_fraction, size_usd, bankroll,
                    final_decision, rejection_reasons,
                    ev_net, ev_per_bankroll
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                candidate.timestamp,
                candidate.market_id,
                candidate.market_question,
                candidate.coin_symbol,
                candidate.direction,
                candidate.p_model_raw,
                candidate.p_model_calibrated,
                candidate.p_market,
                candidate.edge_raw,
                candidate.edge_net,
                candidate.fees_est,
                candidate.slippage_est,
                candidate.ci_low,
                candidate.ci_high,
                candidate.confidence,
                candidate.liquidity,
                candidate.volume_24h,
                candidate.spread,
                candidate.kelly_fraction,
                candidate.size_usd,
                candidate.bankroll,
                candidate.final_decision,
                json.dumps(candidate.rejection_reasons),
                candidate.ev_net,
                candidate.ev_per_bankroll
            ))
            conn.commit()
    
    def get_record_count(self, hours: int = None) -> int:
        """Get count of records, optionally filtered by time."""
        with sqlite3.connect(self.db_path) as conn:
            if hours:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
                result = conn.execute(
                    "SELECT COUNT(*) FROM candidates WHERE timestamp >= ?", 
                    (cutoff,)
                ).fetchone()
            else:
                result = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()
            return result[0]
    
    def get_rejection_breakdown(self, hours: int = 6) -> Dict[str, Any]:
        """
        Compute rejection breakdown for last N hours.
        Returns percentage rejected by each rule.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            # Get all candidates in time window
            rows = conn.execute("""
                SELECT final_decision, rejection_reasons
                FROM candidates
                WHERE timestamp >= ?
            """, (cutoff,)).fetchall()
        
        if not rows:
            return {
                "hours": hours,
                "total_candidates": 0,
                "trades": 0,
                "rejections": 0,
                "rejection_rate": 0.0,
                "rejection_breakdown": {},
                "common_combinations": []
            }
        
        total = len(rows)
        trades = sum(1 for d, _ in rows if d == "TRADE")
        rejections = total - trades
        
        # Count rejection reasons
        reason_counts: Dict[str, int] = {}
        combo_counts: Dict[str, int] = {}
        
        for decision, reasons_json in rows:
            if decision == "REJECT":
                reasons = json.loads(reasons_json) if reasons_json else []
                
                # Count individual reasons
                for reason in reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                
                # Count combinations
                if reasons:
                    combo_key = "+".join(sorted(reasons))
                    combo_counts[combo_key] = combo_counts.get(combo_key, 0) + 1
        
        # Convert to percentages
        rejection_breakdown = {
            reason: {
                "count": count,
                "pct_of_rejections": round(count / rejections * 100, 1) if rejections else 0,
                "pct_of_total": round(count / total * 100, 1)
            }
            for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1])
        }
        
        # Top combinations
        common_combinations = [
            {"reasons": combo.split("+"), "count": count}
            for combo, count in sorted(combo_counts.items(), key=lambda x: -x[1])[:10]
        ]
        
        return {
            "hours": hours,
            "total_candidates": total,
            "trades": trades,
            "rejections": rejections,
            "rejection_rate": round(rejections / total * 100, 1) if total else 0,
            "trade_rate_per_hour": round(trades / hours, 2),
            "rejection_breakdown": rejection_breakdown,
            "common_combinations": common_combinations
        }
    
    def get_recent_candidates(self, limit: int = 20) -> List[Dict]:
        """Get most recent candidates."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM candidates
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]
    
    def print_rejection_report(self, hours: int = 6):
        """Print formatted rejection breakdown report."""
        report = self.get_rejection_breakdown(hours)
        
        print(f"\n{'═' * 60}")
        print(f"📊 REJECTION BREAKDOWN (Last {report['hours']} hours)")
        print(f"{'═' * 60}\n")
        
        print(f"Total candidates: {report['total_candidates']}")
        print(f"Trades executed:  {report['trades']}")
        print(f"Rejections:       {report['rejections']} ({report['rejection_rate']}%)")
        print(f"Trade rate:       {report.get('trade_rate_per_hour', 0)} per hour\n")
        
        if report['rejection_breakdown']:
            print("Rejection reasons:")
            print("-" * 50)
            for reason, data in report['rejection_breakdown'].items():
                print(f"  {reason:30} {data['count']:4} ({data['pct_of_rejections']:5.1f}%)")
        
        if report['common_combinations']:
            print("\nCommon rejection combinations:")
            print("-" * 50)
            for combo in report['common_combinations'][:5]:
                reasons = ", ".join(combo['reasons'])
                print(f"  {combo['count']:4}x: {reasons}")
        
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

_logger: Optional[DiagnosticLogger] = None

def get_diagnostic_logger() -> DiagnosticLogger:
    """Get or create the global diagnostic logger instance."""
    global _logger
    if _logger is None:
        _logger = DiagnosticLogger()
    return _logger


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def log_candidate(**kwargs) -> MarketCandidate:
    """Convenience function to log a candidate."""
    candidate = MarketCandidate(**kwargs)
    get_diagnostic_logger().log_candidate(candidate)
    return candidate

def get_rejection_report(hours: int = 6) -> Dict[str, Any]:
    """Convenience function to get rejection breakdown."""
    return get_diagnostic_logger().get_rejection_breakdown(hours)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test the logger
    logger_instance = DiagnosticLogger("test_diagnostic.db")
    
    # Add some test candidates
    for i in range(5):
        candidate = MarketCandidate(
            timestamp=datetime.now(timezone.utc).isoformat(),
            market_id=f"test_market_{i}",
            market_question="BTC Up or Down - Test",
            coin_symbol="BTC",
            direction="UP",
            p_model_raw=0.6 + i * 0.05,
            p_model_calibrated=0.58 + i * 0.05,
            p_market=0.5,
            edge_raw=0.1 + i * 0.02,
            edge_net=0.08 + i * 0.02,
            fees_est=0.01,
            slippage_est=0.01,
            ci_low=0.45,
            ci_high=0.75,
            confidence=0.4 + i * 0.1,
            liquidity=5000.0,
            volume_24h=10000.0,
            spread=0.02,
            kelly_fraction=0.05,
            size_usd=50.0,
            bankroll=1000.0,
            final_decision="TRADE" if i % 3 == 0 else "REJECT",
            rejection_reasons=[] if i % 3 == 0 else ["LOW_CONFIDENCE", "HIGH_SPREAD"],
            ev_net=5.0 if i % 3 == 0 else -1.0,
            ev_per_bankroll=0.005 if i % 3 == 0 else -0.001
        )
        logger_instance.log_candidate(candidate)
    
    print(f"Records in DB: {logger_instance.get_record_count()}")
    logger_instance.print_rejection_report(hours=1)
    
    # Cleanup test DB
    Path("test_diagnostic.db").unlink()
