"""
Polymarket Trading Bot - Advanced Signal Aggregator
=====================================================
Enhanced statistical aggregation with:
1. Time-weighted signals (exponential decay)
2. Rolling accuracy tracking
3. Bayesian updating
4. Market-category-specific accuracy
5. Lead-lag analysis (Granger causality)
6. Gaussian Process trajectory prediction
"""

import numpy as np
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import json
import os

try:
    from scipy import stats
    from scipy.special import softmax
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, WhiteKernel, Matern
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

try:
    from statsmodels.tsa.stattools import grangercausalitytests
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False

from whale_collector import WhaleDataCollector, WhaleTrade, MarketSignal
from config import Config

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WhaleStats:
    """Rolling statistics for a whale wallet."""
    wallet: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    recent_trades: List[Dict] = field(default_factory=list)  # Last 20 trades
    
    # Category-specific accuracy
    category_accuracy: Dict[str, float] = field(default_factory=lambda: {
        "crypto_15min": 0.5,
        "crypto_daily": 0.5,
        "politics": 0.5,
        "sports": 0.5,
        "other": 0.5
    })
    
    # Rolling weight (updated based on recent performance)
    rolling_weight: float = 1.0
    
    # Lead score (higher = trades before others)
    lead_score: float = 0.0
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.5
        return self.wins / self.total_trades
    
    @property
    def recent_win_rate(self) -> float:
        """Win rate of last 20 trades."""
        if not self.recent_trades:
            return 0.5
        wins = sum(1 for t in self.recent_trades if t.get("won", False))
        return wins / len(self.recent_trades)
    
    def add_trade_result(self, won: bool, category: str = "other"):
        """Record a trade result."""
        self.total_trades += 1
        if won:
            self.wins += 1
        else:
            self.losses += 1
        
        # Update recent trades (keep last 20)
        self.recent_trades.append({
            "won": won,
            "category": category,
            "timestamp": datetime.utcnow().isoformat()
        })
        if len(self.recent_trades) > 20:
            self.recent_trades.pop(0)
        
        # Update category accuracy with EMA
        alpha = 0.1  # Smoothing factor
        old_acc = self.category_accuracy.get(category, 0.5)
        new_acc = old_acc * (1 - alpha) + (1.0 if won else 0.0) * alpha
        self.category_accuracy[category] = new_acc
        
        # Update rolling weight based on recent performance
        self.rolling_weight = 0.9 * self.rolling_weight + 0.1 * self.recent_win_rate


@dataclass
class AdvancedSignal:
    """Enhanced aggregated signal with full statistics."""
    market_id: str
    market_question: str
    category: str
    
    # Core signal
    direction: float           # -1 to +1
    confidence: float          # 0 to 1
    
    # Bayesian posterior
    prior: float               # Whale-based probability
    likelihood: float          # Momentum likelihood
    posterior: float           # Final Bayesian probability
    
    # Statistical measures
    mean: float
    std: float
    lower_ci: float
    upper_ci: float
    
    # Time-weighted metrics
    time_weighted_mean: float
    decay_factor: float
    
    # Whale consensus
    whale_count: int
    whale_agreement: float     # 0 = split, 1 = unanimous
    lead_whale_signal: float   # Signal from whales who trade first
    
    # GP prediction (if available)
    gp_mean: Optional[float] = None
    gp_std: Optional[float] = None
    
    # Metadata
    total_volume: float = 0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    @property
    def is_significant(self) -> bool:
        """Statistical significance test."""
        return self.lower_ci > 0 or self.upper_ci < 0
    
    @property
    def signal_to_noise(self) -> float:
        """Signal strength relative to uncertainty."""
        if self.std == 0:
            return 0
        return abs(self.mean) / self.std
    
    @property
    def recommended_action(self) -> str:
        if not self.is_significant or self.confidence < 0.4:
            return "HOLD"
        if self.posterior > 0.6:
            return "BUY_YES"
        if self.posterior < 0.4:
            return "BUY_NO"
        return "HOLD"
    
    @property
    def bet_size_multiplier(self) -> float:
        """Suggested bet size multiplier based on confidence."""
        # Base: 1.0, max: 2.0
        return 1.0 + min(1.0, self.confidence * self.signal_to_noise / 2)


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED AGGREGATOR
# ═══════════════════════════════════════════════════════════════════════════════

class AdvancedSignalAggregator:
    """
    Advanced whale signal aggregation with:
    - Time-weighted exponential decay
    - Rolling accuracy tracking
    - Bayesian updating
    - Lead-lag analysis
    - Gaussian Process prediction
    """
    
    def __init__(
        self, 
        collector: WhaleDataCollector = None,
        stats_file: str = "whale_stats.json"
    ):
        self.collector = collector or WhaleDataCollector()
        self.stats_file = stats_file
        
        # Whale statistics (persisted)
        self.whale_stats: Dict[str, WhaleStats] = {}
        self._load_stats()
        
        # Initialize stats for known whales
        for wallet in self.collector.whale_addresses:
            if wallet.lower() not in self.whale_stats:
                self.whale_stats[wallet.lower()] = WhaleStats(wallet=wallet.lower())
        
        # Base PnL weights
        self.whale_pnl = {
            "0x63ce342161250d705dc0b16df89036c8e5f9ba9a": 558000,
            "0x9d84ce0306f8551e02efef1680475fc0f1dc1344": 2600000,
            "0xd218e474776403a330142299f7796e8ba32eb5c9": 958000,
            "0x006cc834cc092684f1b56626e23bedb3835c16ea": 1480000,
            "0xe74a4446efd66a4de690962938f550d8921e40ee": 434000,
            "0x492442eab586f242b53bda933fd5de859c8a3782": 1420000,
        }
        
        # Lead-lag matrix (computed from Granger causality)
        self.lead_lag_matrix: Dict[str, Dict[str, float]] = {}
        
        # Cached signals
        self.signals_cache: Dict[str, AdvancedSignal] = {}
        self.last_aggregation: Optional[datetime] = None
        
        # Time decay parameter (trades older than this many hours have 10% weight)
        self.decay_half_life_hours = 6
    
    def _load_stats(self):
        """Load persisted whale statistics."""
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r') as f:
                    data = json.load(f)
                    for wallet, stats_dict in data.items():
                        self.whale_stats[wallet] = WhaleStats(
                            wallet=wallet,
                            total_trades=stats_dict.get("total_trades", 0),
                            wins=stats_dict.get("wins", 0),
                            losses=stats_dict.get("losses", 0),
                            recent_trades=stats_dict.get("recent_trades", []),
                            category_accuracy=stats_dict.get("category_accuracy", {}),
                            rolling_weight=stats_dict.get("rolling_weight", 1.0),
                            lead_score=stats_dict.get("lead_score", 0.0)
                        )
                logger.info(f"Loaded whale stats for {len(self.whale_stats)} wallets")
            except Exception as e:
                logger.warning(f"Failed to load whale stats: {e}")
    
    def _save_stats(self):
        """Persist whale statistics."""
        try:
            data = {}
            for wallet, stats in self.whale_stats.items():
                data[wallet] = {
                    "total_trades": stats.total_trades,
                    "wins": stats.wins,
                    "losses": stats.losses,
                    "recent_trades": stats.recent_trades,
                    "category_accuracy": stats.category_accuracy,
                    "rolling_weight": stats.rolling_weight,
                    "lead_score": stats.lead_score
                }
            with open(self.stats_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save whale stats: {e}")
    
    # ─────────────────────────────────────────────────────────────────────────
    # TIME-WEIGHTED SIGNALS
    # ─────────────────────────────────────────────────────────────────────────
    
    def _compute_time_weight(self, trade_time: datetime) -> float:
        """
        Exponential decay weight based on trade age.
        Recent trades have more weight.
        """
        hours_ago = (datetime.utcnow() - trade_time).total_seconds() / 3600
        
        # Exponential decay: weight = exp(-lambda * hours)
        # lambda chosen so weight = 0.5 at half_life
        lambda_decay = np.log(2) / self.decay_half_life_hours
        
        return np.exp(-lambda_decay * hours_ago)
    
    # ─────────────────────────────────────────────────────────────────────────
    # DYNAMIC WEIGHTS
    # ─────────────────────────────────────────────────────────────────────────
    
    def _compute_dynamic_weights(self, category: str = "other") -> Dict[str, float]:
        """
        Compute whale weights combining:
        1. Base PnL (softmax)
        2. Rolling accuracy
        3. Category-specific accuracy
        4. Lead score
        """
        weights = {}
        
        for wallet in self.collector.whale_addresses:
            wallet_lower = wallet.lower()
            
            # Base weight from PnL
            pnl = self.whale_pnl.get(wallet_lower, 100000)
            base_weight = pnl / 1e6  # Scale to reasonable range
            
            # Get whale stats
            stats = self.whale_stats.get(wallet_lower)
            
            if stats:
                # Multiply by rolling performance weight
                performance_factor = stats.rolling_weight
                
                # Multiply by category accuracy
                category_acc = stats.category_accuracy.get(category, 0.5)
                category_factor = 0.5 + category_acc  # 0.5 to 1.5
                
                # Boost for lead whales (they trade first)
                lead_factor = 1.0 + (stats.lead_score * 0.2)  # max 20% boost
                
                weights[wallet_lower] = base_weight * performance_factor * category_factor * lead_factor
            else:
                weights[wallet_lower] = base_weight
        
        # Normalize to sum to 1
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        
        return weights
    
    # ─────────────────────────────────────────────────────────────────────────
    # BAYESIAN UPDATING
    # ─────────────────────────────────────────────────────────────────────────
    
    def _bayesian_update(
        self, 
        prior: float, 
        momentum_signal: float,
        momentum_strength: float = 0.5
    ) -> float:
        """
        Bayesian update: combine whale prior with momentum likelihood.
        
        P(direction | momentum, whales) ∝ P(momentum | direction) × P(direction | whales)
        
        Args:
            prior: Whale-based probability (0-1)
            momentum_signal: Direction from momentum (-1 to +1)
            momentum_strength: How much to weight momentum (0-1)
        
        Returns:
            Posterior probability
        """
        # Convert momentum to likelihood
        # If momentum is positive, P(momentum | YES) should be high
        momentum_prob = 0.5 + (momentum_signal * 0.5)  # Convert to 0-1
        
        # Likelihood ratio
        # P(momentum | YES) / P(momentum | NO)
        eps = 0.01
        likelihood_ratio = (momentum_prob + eps) / ((1 - momentum_prob) + eps)
        
        # Prior odds
        prior_odds = (prior + eps) / ((1 - prior) + eps)
        
        # Posterior odds (weighted by momentum strength)
        # Full Bayesian: posterior_odds = prior_odds × likelihood_ratio
        # Weighted: interpolate between prior and full Bayesian
        full_posterior_odds = prior_odds * likelihood_ratio
        weighted_odds = prior_odds ** (1 - momentum_strength) * full_posterior_odds ** momentum_strength
        
        # Convert back to probability
        posterior = weighted_odds / (1 + weighted_odds)
        
        return np.clip(posterior, 0.01, 0.99)
    
    # ─────────────────────────────────────────────────────────────────────────
    # LEAD-LAG ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    
    def compute_lead_lag(self, trades_by_wallet: Dict[str, List[WhaleTrade]]) -> Dict[str, float]:
        """
        Compute lead scores using Granger causality.
        Whales who trade before others get higher scores.
        """
        if not STATSMODELS_AVAILABLE:
            return {w: 0.0 for w in trades_by_wallet.keys()}
        
        lead_scores = defaultdict(float)
        wallets = list(trades_by_wallet.keys())
        
        if len(wallets) < 2:
            return {w: 0.0 for w in wallets}
        
        # Create time series for each wallet (5-min bins)
        # For simplicity, we'll use trade count per hour as the series
        try:
            for i, wallet_a in enumerate(wallets):
                for wallet_b in wallets[i+1:]:
                    trades_a = trades_by_wallet[wallet_a]
                    trades_b = trades_by_wallet[wallet_b]
                    
                    if len(trades_a) < 5 or len(trades_b) < 5:
                        continue
                    
                    # Create hourly trade counts
                    hours = 24
                    now = datetime.utcnow()
                    
                    series_a = []
                    series_b = []
                    
                    for h in range(hours):
                        start = now - timedelta(hours=h+1)
                        end = now - timedelta(hours=h)
                        
                        count_a = sum(1 for t in trades_a if start <= t.timestamp < end)
                        count_b = sum(1 for t in trades_b if start <= t.timestamp < end)
                        
                        series_a.append(count_a)
                        series_b.append(count_b)
                    
                    # Run Granger causality test
                    data = np.column_stack([series_a, series_b])
                    
                    try:
                        # Test if A Granger-causes B
                        result_a_to_b = grangercausalitytests(data, maxlag=2, verbose=False)
                        p_value_a = min(result_a_to_b[lag][0]['ssr_ftest'][1] for lag in [1, 2])
                        
                        # Test if B Granger-causes A
                        result_b_to_a = grangercausalitytests(data[:, ::-1], maxlag=2, verbose=False)
                        p_value_b = min(result_b_to_a[lag][0]['ssr_ftest'][1] for lag in [1, 2])
                        
                        # If A predicts B (low p-value), A is a leader
                        if p_value_a < 0.1:
                            lead_scores[wallet_a] += (1 - p_value_a)
                        if p_value_b < 0.1:
                            lead_scores[wallet_b] += (1 - p_value_b)
                            
                    except Exception:
                        continue
                        
        except Exception as e:
            logger.warning(f"Lead-lag computation failed: {e}")
        
        # Normalize lead scores
        max_score = max(lead_scores.values()) if lead_scores else 1
        if max_score > 0:
            lead_scores = {k: v / max_score for k, v in lead_scores.items()}
        
        # Update whale stats
        for wallet, score in lead_scores.items():
            if wallet in self.whale_stats:
                self.whale_stats[wallet].lead_score = score
        
        return dict(lead_scores)
    
    # ─────────────────────────────────────────────────────────────────────────
    # GAUSSIAN PROCESS PREDICTION
    # ─────────────────────────────────────────────────────────────────────────
    
    def _predict_with_gp(
        self, 
        trades: List[WhaleTrade],
        prediction_horizon_hours: float = 1.0
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Use Gaussian Process to predict future whale position direction.
        
        Returns:
            (mean_prediction, std_prediction) or (None, None) if not enough data
        """
        if not SCIPY_AVAILABLE or len(trades) < 10:
            return None, None
        
        try:
            # Create time series
            now = datetime.utcnow()
            
            # Feature: hours ago
            X = []
            y = []
            
            for trade in trades:
                hours_ago = (now - trade.timestamp).total_seconds() / 3600
                X.append([hours_ago])
                y.append(trade.direction)
            
            X = np.array(X)
            y = np.array(y)
            
            # Normalize
            y_mean = np.mean(y)
            y_std = np.std(y) + 1e-6
            y_normalized = (y - y_mean) / y_std
            
            # Fit GP
            kernel = Matern(nu=1.5) + WhiteKernel(noise_level=0.1)
            gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=2)
            gp.fit(X, y_normalized)
            
            # Predict at t = -prediction_horizon_hours (future)
            X_pred = np.array([[-prediction_horizon_hours]])
            mean_pred, std_pred = gp.predict(X_pred, return_std=True)
            
            # Denormalize
            mean_pred = mean_pred[0] * y_std + y_mean
            std_pred = std_pred[0] * y_std
            
            return float(mean_pred), float(std_pred)
            
        except Exception as e:
            logger.warning(f"GP prediction failed: {e}")
            return None, None
    
    # ─────────────────────────────────────────────────────────────────────────
    # MAIN AGGREGATION
    # ─────────────────────────────────────────────────────────────────────────
    
    def aggregate_market_signals(
        self,
        trades: List[WhaleTrade],
        momentum_signal: float = 0.0,
        momentum_confidence: float = 0.0
    ) -> Optional[AdvancedSignal]:
        """
        Aggregate trades with all advanced methods.
        """
        if not trades:
            return None
        
        market_id = trades[0].market_id
        market_question = trades[0].market_question
        
        # Determine category
        category = self._detect_category(market_question)
        
        # Get dynamic weights
        weights = self._compute_dynamic_weights(category)
        
        # ── TIME-WEIGHTED AGGREGATION ──
        wallet_signals: Dict[str, float] = defaultdict(float)
        wallet_time_weights: Dict[str, float] = defaultdict(float)
        wallet_volumes: Dict[str, float] = defaultdict(float)
        
        for trade in trades:
            wallet = trade.wallet.lower()
            time_weight = self._compute_time_weight(trade.timestamp)
            
            wallet_signals[wallet] += trade.direction * time_weight
            wallet_time_weights[wallet] += time_weight
            wallet_volumes[wallet] += trade.usd_value
        
        # Normalize by time weights
        for wallet in wallet_signals:
            if wallet_time_weights[wallet] > 0:
                wallet_signals[wallet] /= wallet_time_weights[wallet]
        
        if not wallet_signals:
            return None
        
        # ── WEIGHTED ENSEMBLE ──
        weighted_sum = 0.0
        weight_total = 0.0
        signals_list = []
        
        for wallet, signal in wallet_signals.items():
            w = weights.get(wallet, 0.1)
            weighted_sum += signal * w
            weight_total += w
            signals_list.append(signal)
        
        if weight_total == 0:
            return None
        
        mean_direction = weighted_sum / weight_total
        
        # ── STATISTICAL MEASURES ──
        signals_array = np.array(signals_list)
        
        if len(signals_array) > 1:
            std = np.std(signals_array)
            se = std / np.sqrt(len(signals_array))
            ci_margin = 1.96 * se
        else:
            std = 0.5
            ci_margin = 0.5
        
        # ── WHALE AGREEMENT ──
        positive = sum(1 for s in signals_list if s > 0)
        negative = sum(1 for s in signals_list if s < 0)
        total = len(signals_list)
        whale_agreement = max(positive, negative) / total if total > 0 else 0
        
        # ── LEAD WHALE SIGNAL ──
        # Get signal from high lead-score whales
        lead_signal = 0.0
        lead_weight = 0.0
        for wallet, signal in wallet_signals.items():
            stats = self.whale_stats.get(wallet)
            if stats and stats.lead_score > 0.5:
                lead_signal += signal * stats.lead_score
                lead_weight += stats.lead_score
        if lead_weight > 0:
            lead_signal /= lead_weight
        
        # ── BAYESIAN UPDATE ──
        # Prior from whale signals
        prior = 0.5 + (mean_direction * 0.3)  # Conservative scaling
        prior = np.clip(prior, 0.1, 0.9)
        
        # Posterior combining momentum
        posterior = self._bayesian_update(
            prior=prior,
            momentum_signal=momentum_signal,
            momentum_strength=momentum_confidence * 0.5  # Weight by momentum confidence
        )
        
        # ── GAUSSIAN PROCESS ──
        gp_mean, gp_std = self._predict_with_gp(trades)
        
        # ── CONFIDENCE ──
        # Combine multiple factors
        base_confidence = whale_agreement
        if gp_mean is not None and gp_std is not None:
            gp_snr = abs(gp_mean) / (gp_std + 1e-6)
            gp_confidence = min(1.0, gp_snr / 2)
            base_confidence = 0.7 * base_confidence + 0.3 * gp_confidence
        
        # Boost if lead whales agree with ensemble
        if lead_signal * mean_direction > 0:
            base_confidence *= 1.1
        
        confidence = np.clip(base_confidence, 0, 1)
        
        # ── FINAL DIRECTION ──
        max_signal = max(abs(signals_array.max()), abs(signals_array.min()), 1)
        normalized_direction = np.clip(mean_direction / max_signal, -1, 1)
        
        # Time-weighted mean (more recent trades)
        time_weighted_mean = mean_direction  # Already computed with time weights
        
        total_volume = sum(wallet_volumes.values())
        avg_decay = np.mean([wallet_time_weights[w] / (len(trades) / len(wallet_signals)) 
                           for w in wallet_signals if wallet_signals])
        
        return AdvancedSignal(
            market_id=market_id,
            market_question=market_question,
            category=category,
            direction=normalized_direction,
            confidence=confidence,
            prior=prior,
            likelihood=0.5 + momentum_signal * 0.5,
            posterior=posterior,
            mean=mean_direction,
            std=std,
            lower_ci=mean_direction - ci_margin,
            upper_ci=mean_direction + ci_margin,
            time_weighted_mean=time_weighted_mean,
            decay_factor=avg_decay,
            whale_count=len(wallet_signals),
            whale_agreement=whale_agreement,
            lead_whale_signal=lead_signal,
            gp_mean=gp_mean,
            gp_std=gp_std,
            total_volume=total_volume
        )
    
    def _detect_category(self, question: str) -> str:
        """Detect market category from question text."""
        q_lower = question.lower()
        
        if any(x in q_lower for x in ["btc", "eth", "sol", "xrp", "bitcoin", "ethereum"]):
            if any(x in q_lower for x in ["15", "minute", "min", "hour"]):
                return "crypto_15min"
            return "crypto_daily"
        
        if any(x in q_lower for x in ["trump", "biden", "election", "president", "congress"]):
            return "politics"
        
        if any(x in q_lower for x in ["nfl", "nba", "mlb", "game", "match", "score"]):
            return "sports"
        
        return "other"
    
    def get_all_signals(
        self, 
        lookback_hours: int = 24,
        include_gp: bool = True
    ) -> List[AdvancedSignal]:
        """
        Collect data and compute advanced signals for all markets.
        """
        logger.info(f"Computing advanced signals (lookback: {lookback_hours}h)...")
        
        # Collect fresh data
        self.collector.collect_all_whale_data(lookback_hours=lookback_hours)
        
        # Compute lead-lag scores
        trades_by_wallet = {w: self.collector.trades_cache.get(w.lower(), []) 
                          for w in self.collector.whale_addresses}
        self.compute_lead_lag(trades_by_wallet)
        
        # Get trades grouped by market
        markets = self.collector.get_active_markets()
        
        signals = []
        for market_id, trades in markets.items():
            signal = self.aggregate_market_signals(trades)
            if signal:
                signals.append(signal)
                self.signals_cache[market_id] = signal
        
        # Sort by confidence × edge
        signals.sort(key=lambda s: s.confidence * abs(s.direction), reverse=True)
        
        self.last_aggregation = datetime.utcnow()
        self._save_stats()
        
        logger.info(f"Generated {len(signals)} advanced signals")
        return signals
    
    def print_signals(self, signals: List[AdvancedSignal] = None, limit: int = 10):
        """Print detailed signal summary."""
        signals = signals or list(self.signals_cache.values())
        
        print(f"\n{'═' * 80}")
        print(f"🧬 ADVANCED SIGNAL AGGREGATOR")
        print(f"   Time decay half-life: {self.decay_half_life_hours}h")
        print(f"   Last update: {self.last_aggregation.strftime('%H:%M:%S') if self.last_aggregation else 'Never'}")
        print(f"{'═' * 80}\n")
        
        if not signals:
            print("   No signals available.\n")
            return
        
        print(f"{'Market':<35} {'Dir':>6} {'Conf':>6} {'Post':>6} {'Agree':>6} {'GP':>8} {'Action':>10}")
        print("─" * 80)
        
        for s in signals[:limit]:
            q = s.market_question[:33] + ".." if len(s.market_question) > 35 else s.market_question
            gp_str = f"{s.gp_mean:+.2f}" if s.gp_mean is not None else "N/A"
            
            print(f"{q:<35} {s.direction:>+6.2f} {s.confidence:>5.1%} {s.posterior:>5.1%} "
                  f"{s.whale_agreement:>5.1%} {gp_str:>8} {s.recommended_action:>10}")
        
        print()
        
        # Print whale stats
        print("🐳 WHALE PERFORMANCE:")
        print("─" * 80)
        for wallet, stats in sorted(self.whale_stats.items(), 
                                   key=lambda x: x[1].rolling_weight, reverse=True)[:6]:
            print(f"   {wallet[:10]}... | Trades: {stats.total_trades:>4} | "
                  f"WinRate: {stats.win_rate:.1%} | Recent: {stats.recent_win_rate:.1%} | "
                  f"Lead: {stats.lead_score:.2f}")
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n🧬 Testing Advanced Signal Aggregator...\n")
    
    aggregator = AdvancedSignalAggregator()
    
    signals = aggregator.get_all_signals(lookback_hours=24)
    aggregator.print_signals(signals)
    
    # Show top actionable
    top = [s for s in signals if s.confidence > 0.5 and s.is_significant][:5]
    
    if top:
        print("\n🎯 TOP ACTIONABLE SIGNALS:")
        for s in top:
            print(f"   {s.recommended_action}: {s.market_question[:50]}...")
            print(f"      Posterior: {s.posterior:.1%} | Confidence: {s.confidence:.1%}")
            print(f"      GP Prediction: {s.gp_mean:+.2f} ± {s.gp_std:.2f}" if s.gp_mean else "      GP: N/A")
            print(f"      Bet multiplier: {s.bet_size_multiplier:.2f}x")
            print()
