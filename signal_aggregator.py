"""
Polymarket Trading Bot - Signal Aggregator
============================================
Mathematical aggregation of whale signals using:
- Weighted ensemble (softmax on PnL)
- Gaussian Process regression for trajectory forecasting
- Correlation analysis and clustering
"""

import numpy as np
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

try:
    from scipy import stats
    from scipy.special import softmax
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("⚠ scipy/sklearn not installed. Run: pip install scipy scikit-learn")

from whale_collector import WhaleDataCollector, WhaleTrade, MarketSignal
from config import Config

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL AGGREGATOR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AggregatedSignal:
    """Final aggregated signal combining all whale data."""
    market_id: str
    market_question: str
    
    # Direction: -1 (strong NO) to +1 (strong YES)
    direction: float
    
    # Confidence: 0 to 1 (based on whale agreement and signal strength)
    confidence: float
    
    # Statistical measures
    mean: float
    std: float
    lower_ci: float  # 95% CI lower bound
    upper_ci: float  # 95% CI upper bound
    
    # Whale participation
    whale_count: int
    total_volume: float
    
    # Timestamp
    timestamp: datetime
    
    @property
    def is_significant(self) -> bool:
        """Check if signal is statistically significant (outside 95% CI of 0)."""
        return self.lower_ci > 0 or self.upper_ci < 0
    
    @property
    def recommended_action(self) -> str:
        """Get recommended trading action."""
        if not self.is_significant:
            return "HOLD"
        if self.direction > 0:
            return "BUY_YES"
        return "BUY_NO"


class SignalAggregator:
    """
    Aggregates whale trading signals using statistical methods.
    """
    
    def __init__(self, collector: WhaleDataCollector = None):
        self.collector = collector or WhaleDataCollector()
        
        # Whale PnL weights (for weighted ensemble)
        # These should ideally be fetched/updated from actual PnL data
        self.whale_pnl = {
            "0x63ce342161250d705dc0b16df89036c8e5f9ba9a": 558000,   # 0x8dxd
            "0x9d84ce0306f8551e02efef1680475fc0f1dc1344": 2600000,  # Top performer
            "0xd218e474776403a330142299f7796e8ba32eb5c9": 958000,
            "0x006cc834cc092684f1b56626e23bedb3835c16ea": 1480000,
            "0xe74a4446efd66a4de690962938f550d8921e40ee": 434000,
            "0x492442eab586f242b53bda933fd5de859c8a3782": 1420000,
        }
        
        self.signals_cache: Dict[str, AggregatedSignal] = {}
        self.last_aggregation: Optional[datetime] = None
    
    def _compute_softmax_weights(self) -> Dict[str, float]:
        """
        Compute wallet weights using softmax on PnL.
        Higher PnL = higher influence on aggregated signal.
        """
        if not SCIPY_AVAILABLE:
            # Fallback to equal weights
            return {w: 1.0 / len(self.whale_pnl) for w in self.whale_pnl}
        
        # Normalize PnL values and apply softmax
        wallets = list(self.whale_pnl.keys())
        pnl_values = np.array([self.whale_pnl[w] for w in wallets])
        
        # Scale to prevent overflow
        pnl_scaled = pnl_values / 1e6  # Scale to millions
        weights = softmax(pnl_scaled)
        
        return dict(zip(wallets, weights))
    
    def aggregate_market_signals(
        self, 
        trades: List[WhaleTrade],
        time_bins_hours: int = 1
    ) -> Optional[AggregatedSignal]:
        """
        Aggregate trades into a single directional signal.
        
        Uses weighted average of directional signals from each whale.
        """
        if not trades:
            return None
        
        market_id = trades[0].market_id
        market_question = trades[0].market_question
        
        # Compute wallet weights
        weights = self._compute_softmax_weights()
        
        # Aggregate by wallet
        wallet_signals: Dict[str, float] = defaultdict(float)
        wallet_volumes: Dict[str, float] = defaultdict(float)
        
        for trade in trades:
            wallet = trade.wallet.lower()
            wallet_signals[wallet] += trade.direction
            wallet_volumes[wallet] += trade.usd_value
        
        # Weighted ensemble
        if not wallet_signals:
            return None
        
        weighted_sum = 0.0
        weight_total = 0.0
        signals = []
        
        for wallet, signal in wallet_signals.items():
            w = weights.get(wallet.lower(), 0.1)
            weighted_sum += signal * w
            weight_total += w
            signals.append(signal)
        
        if weight_total == 0:
            return None
        
        # Compute statistics
        mean_direction = weighted_sum / weight_total
        signals_array = np.array(signals)
        
        if len(signals_array) > 1:
            std = np.std(signals_array)
            se = std / np.sqrt(len(signals_array))
            ci_margin = 1.96 * se  # 95% CI
        else:
            std = 0
            ci_margin = 0
        
        # Normalize direction to [-1, 1]
        max_signal = max(abs(signals_array.max()), abs(signals_array.min()), 1)
        normalized_direction = np.clip(mean_direction / max_signal, -1, 1)
        
        # Confidence based on agreement and signal strength
        agreement = 1.0 - (std / (max_signal + 1e-6))  # Higher agreement = higher confidence
        strength = abs(normalized_direction)
        confidence = np.clip(agreement * strength, 0, 1)
        
        total_volume = sum(wallet_volumes.values())
        
        return AggregatedSignal(
            market_id=market_id,
            market_question=market_question,
            direction=normalized_direction,
            confidence=confidence,
            mean=mean_direction,
            std=std,
            lower_ci=mean_direction - ci_margin,
            upper_ci=mean_direction + ci_margin,
            whale_count=len(wallet_signals),
            total_volume=total_volume,
            timestamp=datetime.utcnow()
        )
    
    def detect_whale_consensus(self, trades: List[WhaleTrade]) -> Tuple[float, float]:
        """
        Detect if whales are in consensus (all betting same direction).
        
        Returns:
            (consensus_score, dominant_direction)
            consensus_score: 0 = no consensus, 1 = full consensus
            dominant_direction: positive = YES, negative = NO
        """
        if not trades:
            return 0.0, 0.0
        
        # Group by wallet
        wallet_directions: Dict[str, float] = defaultdict(float)
        
        for trade in trades:
            wallet_directions[trade.wallet.lower()] += trade.direction
        
        if not wallet_directions:
            return 0.0, 0.0
        
        # Check consensus
        directions = list(wallet_directions.values())
        positive = sum(1 for d in directions if d > 0)
        negative = sum(1 for d in directions if d < 0)
        total = len(directions)
        
        if total == 0:
            return 0.0, 0.0
        
        dominant = positive if positive > negative else -negative
        consensus = max(positive, negative) / total
        
        avg_direction = np.mean(directions)
        
        return consensus, avg_direction
    
    def cluster_whale_behavior(self, trades: List[WhaleTrade], n_clusters: int = 3) -> Dict:
        """
        Cluster whale trading behavior using K-means.
        Identifies different trading strategies/patterns.
        """
        if not SCIPY_AVAILABLE or len(trades) < n_clusters:
            return {"clusters": [], "labels": []}
        
        # Extract features
        features = []
        for t in trades:
            features.append([
                t.direction,
                t.size,
                t.price,
                t.usd_value
            ])
        
        if len(features) < n_clusters:
            return {"clusters": [], "labels": []}
        
        X = np.array(features)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X_scaled)
        
        return {
            "clusters": kmeans.cluster_centers_.tolist(),
            "labels": labels.tolist(),
            "inertia": kmeans.inertia_
        }
    
    def get_all_market_signals(self, lookback_hours: int = 24) -> List[AggregatedSignal]:
        """
        Collect whale data and compute aggregated signals for all active markets.
        """
        logger.info(f"Aggregating whale signals (lookback: {lookback_hours}h)...")
        
        # Collect fresh data
        self.collector.collect_all_whale_data(lookback_hours=lookback_hours)
        
        # Get trades grouped by market
        markets = self.collector.get_active_markets()
        
        signals = []
        for market_id, trades in markets.items():
            signal = self.aggregate_market_signals(trades)
            if signal:
                signals.append(signal)
                self.signals_cache[market_id] = signal
        
        # Sort by confidence
        signals.sort(key=lambda s: s.confidence, reverse=True)
        
        self.last_aggregation = datetime.utcnow()
        logger.info(f"Generated {len(signals)} market signals")
        
        return signals
    
    def get_top_signals(self, min_confidence: float = 0.3, limit: int = 10) -> List[AggregatedSignal]:
        """Get top signals by confidence."""
        signals = list(self.signals_cache.values())
        filtered = [s for s in signals if s.confidence >= min_confidence]
        filtered.sort(key=lambda s: (s.confidence, abs(s.direction)), reverse=True)
        return filtered[:limit]
    
    def print_signals(self, signals: List[AggregatedSignal] = None):
        """Print signal summary."""
        signals = signals or list(self.signals_cache.values())
        
        print(f"\n{'═' * 70}")
        print(f"🐳 WHALE SIGNAL AGGREGATOR")
        print(f"   Last update: {self.last_aggregation.strftime('%H:%M:%S') if self.last_aggregation else 'Never'}")
        print(f"   Markets tracked: {len(signals)}")
        print(f"{'═' * 70}\n")
        
        if not signals:
            print("   No signals available.\n")
            return
        
        print(f"{'Market':<40} {'Dir':>6} {'Conf':>6} {'Action':>10} {'Whales':>6}")
        print("─" * 70)
        
        for s in signals[:10]:
            q = s.market_question[:38] + ".." if len(s.market_question) > 40 else s.market_question
            direction = f"{s.direction:+.2f}"
            confidence = f"{s.confidence:.1%}"
            action = s.recommended_action
            
            print(f"{q:<40} {direction:>6} {confidence:>6} {action:>10} {s.whale_count:>6}")
        
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n🔬 Testing Signal Aggregator...\n")
    
    aggregator = SignalAggregator()
    
    # Get signals
    signals = aggregator.get_all_market_signals(lookback_hours=24)
    
    # Print results
    aggregator.print_signals(signals)
    
    # Show top actionable signals
    top = aggregator.get_top_signals(min_confidence=0.3, limit=5)
    
    if top:
        print("\n🎯 TOP ACTIONABLE SIGNALS:")
        for s in top:
            print(f"   {s.recommended_action}: {s.market_question[:50]}...")
            print(f"      Direction: {s.direction:+.2f} | Confidence: {s.confidence:.1%}")
            print(f"      95% CI: [{s.lower_ci:.2f}, {s.upper_ci:.2f}]")
            print()
