"""
Polymarket Trading Bot - New Unified Trader
=============================================
Clean implementation integrating all fixed components:
- WhaleDataCollector for crypto trade signals
- MarketFinder for active crypto markets
- EVCalculator for trade decisions
- DiagnosticLogger for instrumentation

This replaces the old fragmented trading logic with a streamlined pipeline.

Created: Jan 2026
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from whale_collector import WhaleDataCollector, WhaleTrade
from market_finder import MarketFinder, CryptoMarket
from ev_calculator import EVCalculator, TradeOpportunity  
from diagnostic_logger import DiagnosticLogger, MarketCandidate
from position_manager import PositionManager
from price_feed import PriceFeed
from threshold_controller import ThresholdController
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL FUSION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FusedSignal:
    """Combined signal from whale data and momentum."""
    market_id: str
    market_question: str
    coin_symbol: str
    direction: str
    
    # Model probability estimate
    p_model: float
    confidence: float
    
    # Component signals
    whale_signal: float         # -1 to +1
    whale_volume: float
    whale_count: int
    momentum_signal: float      # -1 to +1 from price action
    
    # Market data
    yes_price: float
    no_price: float
    volume_24h: float
    liquidity: float


class SignalFuser:
    """
    Fuses whale signals with momentum to produce probability estimates.
    
    Default weights: 60% whale, 40% momentum
    """
    
    def __init__(
        self,
        whale_weight: float = 0.6,
        momentum_weight: float = 0.4,
        crypto_specialist_boost: float = 1.5  # Boost for known good wallets
    ):
        self.whale_weight = whale_weight
        self.momentum_weight = momentum_weight
        self.crypto_specialist_boost = crypto_specialist_boost
        
        # Crypto specialist wallets (known to perform well on crypto)
        self.crypto_specialists = [
            "0x63ce342161250d705dc0b16df89036c8e5f9ba9a",  # 0x8dxd
        ]
    
    def compute_whale_signal(
        self, 
        trades: List[WhaleTrade],
        target_coin: str
    ) -> Tuple[float, float, int]:
        """
        Compute aggregate whale signal for a coin.
        
        Returns:
            (signal_direction, total_volume, whale_count)
        """
        if not trades:
            return 0.0, 0.0, 0
        
        weighted_direction = 0.0
        total_volume = 0.0
        wallets_seen = set()
        
        for trade in trades:
            # Check if trade is for target coin
            question = trade.market_question.lower()
            if target_coin.lower() not in question:
                continue
            
            # Apply boost for crypto specialists
            boost = 1.0
            if trade.wallet.lower() in [w.lower() for w in self.crypto_specialists]:
                boost = self.crypto_specialist_boost
            
            # Aggregate signal
            direction = trade.direction * boost
            weighted_direction += direction * trade.usd_value
            total_volume += trade.usd_value
            wallets_seen.add(trade.wallet)
        
        if total_volume > 0:
            avg_direction = weighted_direction / total_volume
            # Normalize to [-1, +1]
            signal = max(-1, min(1, avg_direction / 100))  # Divide by typical trade size
        else:
            signal = 0.0
        
        return signal, total_volume, len(wallets_seen)
    
    def fuse_signals(
        self,
        market: CryptoMarket,
        whale_trades: List[WhaleTrade],
        momentum: float = 0.0  # From price feed, -1 to +1
    ) -> FusedSignal:
        """
        Fuse whale signals and momentum into a single probability estimate.
        """
        # Get whale signal for this coin
        whale_signal, whale_volume, whale_count = self.compute_whale_signal(
            whale_trades, 
            market.coin_symbol
        )
        
        # Combined signal
        combined = (
            self.whale_weight * whale_signal + 
            self.momentum_weight * momentum
        )
        
        # Convert to probability
        # combined is in [-1, +1], map to probability [0, 1]
        # Positive = UP direction favored
        if market.direction == "UP":
            p_model = 0.5 + (combined / 2)
        else:
            # For DOWN markets, invert the signal interpretation
            p_model = 0.5 - (combined / 2)
        
        # Clamp to valid range
        p_model = max(0.05, min(0.95, p_model))
        
        # Confidence based on agreement and volume
        confidence = min(1.0, whale_volume / 1000) * abs(combined)
        
        return FusedSignal(
            market_id=market.market_id,
            market_question=market.question,
            coin_symbol=market.coin_symbol,
            direction=market.direction,
            p_model=p_model,
            confidence=confidence,
            whale_signal=whale_signal,
            whale_volume=whale_volume,
            whale_count=whale_count,
            momentum_signal=momentum,
            yes_price=market.yes_price,
            no_price=market.no_price,
            volume_24h=market.volume_24h,
            liquidity=market.liquidity
        )


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED TRADING BOT
# ═══════════════════════════════════════════════════════════════════════════════

class NewUnifiedTrader:
    """
    Clean implementation of the trading bot with:
    - Working data pipeline (whale_collector, market_finder)
    - EV-based decision logic (ev_calculator)
    - Full instrumentation (diagnostic_logger)
    - Risk management (position_manager)
    - Adaptive thresholds (threshold_controller)
    """
    
    def __init__(
        self,
        dry_run: bool = True,
        min_confidence: float = 0.25,  # Much lower than old 40%
        max_position_pct: float = 0.05,
    ):
        self.dry_run = dry_run
        self.min_confidence = min_confidence
        self.max_position_pct = max_position_pct
        
        # Components
        self.whale_collector = WhaleDataCollector()
        self.market_finder = MarketFinder()
        self.ev_calculator = EVCalculator(
            min_ev_frac=0.001,
            max_position_pct=max_position_pct
        )
        self.signal_fuser = SignalFuser()
        self.diagnostic_logger = DiagnosticLogger()
        self.position_manager = PositionManager()
        self.price_feed = PriceFeed()
        self.threshold_controller = ThresholdController()
        
        # State
        self.cycle_count = 0
        self.last_whale_refresh = None
        self.whale_trades: List[WhaleTrade] = []
        
        logger.info(f"NewUnifiedTrader initialized (dry_run={dry_run})")
    
    def refresh_whale_signals(self):
        """Refresh whale trade data."""
        result = self.whale_collector.collect_all_whale_data(lookback_hours=24)
        self.whale_trades = result.get("trades", [])
        self.last_whale_refresh = datetime.now(timezone.utc)
        logger.info(f"Loaded {len(self.whale_trades)} whale trades from {result.get('whale_count', 0)} wallets")
    
    def find_opportunities(self) -> List[TradeOpportunity]:
        """Find and evaluate all trading opportunities."""
        # Get current markets with activity
        markets = self.market_finder.find_markets_from_trades()
        
        if not markets:
            logger.warning("No active crypto markets found")
            return []
        
        # Get price momentum
        self.price_feed.fetch_prices()
        
        opportunities = []
        bankroll = self.position_manager.bankroll
        
        for market in markets:
            # Get momentum signal
            momentum_signal = self.price_feed.calculate_momentum(market.coin_id)
            momentum = 0.0
            if momentum_signal:
                # Convert to [-1, +1]
                momentum = momentum_signal.change_percent / 2
                momentum = max(-1, min(1, momentum))
            
            # Fuse signals
            fused = self.signal_fuser.fuse_signals(
                market=market,
                whale_trades=self.whale_trades,
                momentum=momentum
            )
            
            # Skip if low confidence
            if fused.confidence < self.min_confidence:
                self._log_rejection(fused, bankroll, ["LOW_CONFIDENCE"])
                continue
            
            # Evaluate with EV calculator
            opportunity = self.ev_calculator.evaluate_opportunity(
                market_id=fused.market_id,
                market_question=fused.market_question,
                coin_symbol=fused.coin_symbol,
                direction=fused.direction,
                p_model=fused.p_model,
                yes_price=fused.yes_price,
                no_price=fused.no_price,
                bankroll=bankroll,
                liquidity=fused.liquidity,
                spread=market.spread
            )
            
            # Log to diagnostic database
            self._log_candidate(fused, opportunity, bankroll)
            
            if opportunity.passes_ev_check:
                opportunities.append(opportunity)
            else:
                logger.debug(f"Rejected {market.coin_symbol} {market.direction}: {opportunity.rejection_reasons}")
        
        # Sort by EV
        opportunities.sort(key=lambda x: x.ev_net, reverse=True)
        
        logger.info(f"Found {len(opportunities)} opportunities from {len(markets)} markets")
        return opportunities
    
    def _log_candidate(
        self, 
        fused: FusedSignal, 
        opportunity: TradeOpportunity,
        bankroll: float
    ):
        """Log candidate to diagnostic database."""
        candidate = MarketCandidate(
            timestamp=datetime.now(timezone.utc).isoformat(),
            market_id=fused.market_id,
            market_question=fused.market_question,
            coin_symbol=fused.coin_symbol,
            direction=fused.direction,
            p_model_raw=fused.p_model,
            p_model_calibrated=fused.p_model,  # TODO: Add calibration
            p_market=fused.yes_price,
            edge_raw=opportunity.edge,
            edge_net=opportunity.ev_net / opportunity.suggested_size_usd if opportunity.suggested_size_usd > 0 else 0,
            fees_est=opportunity.fees_est,
            slippage_est=opportunity.slippage_est,
            ci_low=fused.p_model - 0.1,  # Placeholder
            ci_high=fused.p_model + 0.1,
            confidence=fused.confidence,
            liquidity=fused.liquidity,
            volume_24h=fused.volume_24h,
            spread=0.02,
            kelly_fraction=opportunity.kelly_fraction,
            size_usd=opportunity.suggested_size_usd,
            bankroll=bankroll,
            final_decision="TRADE" if opportunity.passes_ev_check else "REJECT",
            rejection_reasons=opportunity.rejection_reasons,
            ev_net=opportunity.ev_net,
            ev_per_bankroll=opportunity.ev_net / bankroll if bankroll > 0 else 0
        )
        self.diagnostic_logger.log_candidate(candidate)
    
    def _log_rejection(
        self, 
        fused: FusedSignal, 
        bankroll: float,
        reasons: List[str]
    ):
        """Log early rejection to diagnostic database."""
        candidate = MarketCandidate(
            timestamp=datetime.now(timezone.utc).isoformat(),
            market_id=fused.market_id,
            market_question=fused.market_question,
            coin_symbol=fused.coin_symbol,
            direction=fused.direction,
            p_model_raw=fused.p_model,
            p_model_calibrated=fused.p_model,
            p_market=fused.yes_price,
            edge_raw=0,
            edge_net=0,
            fees_est=0,
            slippage_est=0,
            ci_low=fused.p_model - 0.1,
            ci_high=fused.p_model + 0.1,
            confidence=fused.confidence,
            liquidity=fused.liquidity,
            volume_24h=fused.volume_24h,
            spread=0.02,
            kelly_fraction=0,
            size_usd=0,
            bankroll=bankroll,
            final_decision="REJECT",
            rejection_reasons=reasons,
            ev_net=0,
            ev_per_bankroll=0
        )
        self.diagnostic_logger.log_candidate(candidate)
    
    def execute_trade(self, opportunity: TradeOpportunity) -> bool:
        """Execute a trade."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would trade: {opportunity.coin_symbol} {opportunity.side} ${opportunity.suggested_size_usd:.2f}")
            return True
        
        # TODO: Implement actual trade execution via Polymarket API
        logger.warning("Live trading not yet implemented")
        return False
    
    def run_cycle(self) -> int:
        """Run one trading cycle."""
        self.cycle_count += 1
        logger.info(f"{'─' * 40}")
        logger.info(f"Cycle {self.cycle_count}")
        
        # Check if trading is allowed (kill switch, daily limits)
        can_trade, reason = self.threshold_controller.can_trade()
        if not can_trade:
            logger.warning(f"Trading blocked: {reason}")
            return 0
        
        # Update adaptive thresholds
        self.threshold_controller.update_thresholds(
            current_bankroll=self.position_manager.bankroll,
            starting_bankroll=self.position_manager.starting_bankroll
        )
        thresholds = self.threshold_controller.get_thresholds()
        self.min_confidence = thresholds.min_confidence
        self.ev_calculator.min_ev_frac = thresholds.min_ev_frac
        
        # Refresh whale data every 5 minutes
        if (
            self.last_whale_refresh is None or
            (datetime.now(timezone.utc) - self.last_whale_refresh).seconds > 300
        ):
            self.refresh_whale_signals()
        
        # Find opportunities
        opportunities = self.find_opportunities()
        
        if not opportunities:
            logger.info("No opportunities found")
            return 0
        
        # Execute best opportunity
        trades_executed = 0
        for opp in opportunities[:1]:  # Only trade best one per cycle
            self.ev_calculator.print_opportunity(opp)
            
            if self.execute_trade(opp):
                trades_executed += 1
                # Record trade with threshold controller
                self.threshold_controller.record_trade(pnl=0)  # PnL unknown until settled
        
        return trades_executed
    
    def run(self, cycles: int = 10, interval: int = 60):
        """Run the trading bot."""
        logger.info(f"\n{'═' * 60}")
        logger.info(f"🤖 NEW UNIFIED TRADER")
        logger.info(f"   Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        logger.info(f"   Cycles: {cycles}")
        logger.info(f"   Interval: {interval}s")
        logger.info(f"{'═' * 60}\n")
        
        total_trades = 0
        
        for i in range(cycles):
            try:
                trades = self.run_cycle()
                total_trades += trades
            except Exception as e:
                logger.error(f"Cycle error: {e}")
            
            if i < cycles - 1:
                time.sleep(interval)
        
        # Print summary
        logger.info(f"\n{'═' * 60}")
        logger.info(f"SUMMARY")
        logger.info(f"   Cycles: {self.cycle_count}")
        logger.info(f"   Trades: {total_trades}")
        logger.info(f"{'═' * 60}")
        
        # Print rejection report
        self.diagnostic_logger.print_rejection_report(hours=1)
        self.threshold_controller.print_status()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="New Unified Trading Bot")
    parser.add_argument("--live", action="store_true", help="Run in live mode (executes real trades)")
    parser.add_argument("--cycles", type=int, default=5, help="Number of trading cycles")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between cycles")
    parser.add_argument("--scan", action="store_true", help="Just scan for opportunities, don't enter trading loop")
    
    args = parser.parse_args()
    
    trader = NewUnifiedTrader(dry_run=not args.live)
    
    if args.scan:
        # Just scan once
        trader.refresh_whale_signals()
        opportunities = trader.find_opportunities()
        
        print(f"\n📊 Found {len(opportunities)} opportunities\n")
        for opp in opportunities[:5]:
            trader.ev_calculator.print_opportunity(opp)
    else:
        trader.run(cycles=args.cycles, interval=args.interval)
