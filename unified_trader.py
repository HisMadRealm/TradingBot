"""
Polymarket Unified Trading Bot
===============================
Combines momentum signals + whale aggregation for trading decisions.

This is the main entry point that fuses:
1. CoinGecko price momentum signals
2. Whale wallet signal aggregation
3. Statistical confidence measures

Usage:
    python unified_trader.py --dry-run          # Simulation mode
    python unified_trader.py --live             # Real trading
    python unified_trader.py --scan             # Just scan for signals
"""

import argparse
import logging
import signal as sig
import sys
import time
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

from config import Config
from price_feed import PriceFeed, MomentumSignal
from market_finder import MarketFinder, CryptoMarket
from position_manager import PositionManager, Trade
from executor import OrderExecutor, OrderRequest
from whale_collector import WhaleDataCollector
from signal_aggregator import SignalAggregator, AggregatedSignal
from notifier import notifier

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

def setup_logging(log_file: str = "bot.log", level: str = "INFO"):
    """Configure logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL FUSION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FusedSignal:
    """Combined signal from multiple sources."""
    market: CryptoMarket
    
    # Individual signals
    momentum_signal: Optional[MomentumSignal]
    whale_signal: Optional[AggregatedSignal]
    
    # Fused result
    direction: float          # -1 to +1
    confidence: float         # 0 to 1
    edge: float               # Expected edge vs market
    
    # Weights used
    momentum_weight: float
    whale_weight: float
    
    # Recommended action
    action: str               # "BUY_YES", "BUY_NO", "HOLD"
    
    @property
    def should_trade(self) -> bool:
        """Check if signal meets trading thresholds."""
        return (
            self.confidence >= 0.5 and
            self.edge >= Config.trading.edge_threshold and
            self.action != "HOLD"
        )


class SignalFusion:
    """
    Fuses momentum and whale signals using weighted average.
    
    Methods:
    1. Simple weighted average
    2. Bayesian update (use whale as prior, momentum as likelihood)
    """
    
    def __init__(
        self,
        momentum_weight: float = 0.4,
        whale_weight: float = 0.6
    ):
        self.momentum_weight = momentum_weight
        self.whale_weight = whale_weight
    
    def fuse(
        self,
        market: CryptoMarket,
        momentum: Optional[MomentumSignal],
        whale: Optional[AggregatedSignal]
    ) -> FusedSignal:
        """
        Combine momentum and whale signals for a market.
        """
        # Extract directional signals
        momentum_direction = 0.0
        momentum_confidence = 0.0
        
        if momentum:
            # Momentum: positive change = bullish if market asks about UP
            if market.direction == momentum.direction:
                momentum_direction = momentum.predicted_probability - 0.5
            else:
                momentum_direction = 0.5 - momentum.predicted_probability
            momentum_direction *= 2  # Scale to [-1, 1]
            momentum_confidence = momentum.confidence
        
        whale_direction = 0.0
        whale_confidence = 0.0
        
        if whale:
            whale_direction = whale.direction
            whale_confidence = whale.confidence
        
        # Compute weights (normalize if one source missing)
        if momentum and whale:
            mw = self.momentum_weight
            ww = self.whale_weight
        elif momentum:
            mw = 1.0
            ww = 0.0
        elif whale:
            mw = 0.0
            ww = 1.0
        else:
            # No signals
            return FusedSignal(
                market=market,
                momentum_signal=momentum,
                whale_signal=whale,
                direction=0.0,
                confidence=0.0,
                edge=0.0,
                momentum_weight=0.0,
                whale_weight=0.0,
                action="HOLD"
            )
        
        # Weighted average of directions
        total_weight = mw + ww
        fused_direction = (
            momentum_direction * mw + whale_direction * ww
        ) / total_weight
        
        # Confidence is min of available confidences (conservative)
        # or weighted average
        fused_confidence = (
            momentum_confidence * mw + whale_confidence * ww
        ) / total_weight
        
        # Boost confidence if signals agree
        if momentum and whale:
            if (momentum_direction > 0) == (whale_direction > 0):
                # Signals agree - boost confidence
                fused_confidence = min(1.0, fused_confidence * 1.2)
            else:
                # Signals disagree - reduce confidence
                fused_confidence *= 0.7
        
        # Calculate edge
        # Edge = predicted prob - market prob
        predicted_prob = 0.5 + (fused_direction * 0.5)  # Convert to 0-1
        edge = abs(predicted_prob - market.yes_price)
        
        # Determine action
        if fused_direction > 0.1 and edge >= Config.trading.edge_threshold:
            action = "BUY_YES"
        elif fused_direction < -0.1 and edge >= Config.trading.edge_threshold:
            action = "BUY_NO"
        else:
            action = "HOLD"
        
        return FusedSignal(
            market=market,
            momentum_signal=momentum,
            whale_signal=whale,
            direction=fused_direction,
            confidence=fused_confidence,
            edge=edge,
            momentum_weight=mw / total_weight,
            whale_weight=ww / total_weight,
            action=action
        )


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED TRADING BOT
# ═══════════════════════════════════════════════════════════════════════════════

class UnifiedTradingBot:
    """
    Main trading bot combining momentum + whale signals.
    """
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.running = False
        self.cycle_count = 0
        
        # Components
        self.price_feed = PriceFeed()
        self.market_finder = MarketFinder()
        self.position_manager = PositionManager()
        self.executor = OrderExecutor(dry_run=dry_run)
        
        # Whale components
        self.whale_collector = WhaleDataCollector()
        self.signal_aggregator = SignalAggregator(self.whale_collector)
        
        # Signal fusion
        self.fusion = SignalFusion(
            momentum_weight=0.4,
            whale_weight=0.6  # Whale signals weighted higher
        )
        
        self.logger = logging.getLogger(__name__)
        
        # Stats
        self.signals_generated = 0
        self.trades_executed = 0
        self.start_time = datetime.utcnow()
        
        # Cache
        self.whale_signals: Dict[str, AggregatedSignal] = {}
        self.last_whale_refresh = None
    
    def print_banner(self):
        """Print startup banner."""
        mode = "🧪 DRY RUN" if self.dry_run else "🔴 LIVE TRADING"
        
        print(f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║   🐳🤖 POLYMARKET UNIFIED TRADER v3.0                                         ║
║         Momentum + Whale Signal Aggregation                                   ║
║                                                                               ║
║   {mode:<60}           ║
║                                                                               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║   Signals:   Momentum (40%) + Whale Ensemble (60%)                            ║
║   Whales:    {len(self.whale_collector.whale_addresses)} tracked (0x8dxd primary)                             ║
║   Edge:      {Config.trading.edge_threshold*100:.0f}% minimum | Size: {Config.trading.bet_size_percent*100:.0f}% of bankroll                       ║
╚═══════════════════════════════════════════════════════════════════════════════╝
        """)
    
    def refresh_whale_signals(self, lookback_hours: int = 24):
        """Refresh whale signal aggregation."""
        self.logger.info("Refreshing whale signals...")
        
        signals = self.signal_aggregator.get_all_market_signals(
            lookback_hours=lookback_hours
        )
        
        self.whale_signals = {s.market_id: s for s in signals}
        self.last_whale_refresh = datetime.utcnow()
        
        self.logger.info(f"Loaded {len(signals)} whale signals")
    
    def find_opportunities(self) -> List[FusedSignal]:
        """Find trading opportunities using fused signals."""
        opportunities = []
        
        # Get momentum signals
        momentum_signals = self.price_feed.get_all_signals()
        momentum_by_coin = {s.coin_id: s for s in momentum_signals}
        
        # Get current markets
        markets = self.market_finder.find_crypto_markets(min_minutes_left=3.0)
        
        if not markets:
            return []
        
        for market in markets:
            # Skip if we have position
            if self.position_manager.has_position(market.market_id):
                continue
            
            # Get momentum signal for this coin
            momentum = momentum_by_coin.get(market.coin_id)
            
            # Get whale signal for this market
            whale = self.whale_signals.get(market.market_id)
            
            # Fuse signals
            fused = self.fusion.fuse(market, momentum, whale)
            
            if fused.should_trade:
                opportunities.append(fused)
                self.signals_generated += 1
        
        # Sort by edge * confidence (expected value)
        opportunities.sort(
            key=lambda f: f.edge * f.confidence,
            reverse=True
        )
        
        return opportunities
    
    def execute_opportunity(self, fused: FusedSignal) -> Optional[Trade]:
        """Execute a fused trading signal."""
        market = fused.market
        
        # Risk checks
        can_trade, reason = self.position_manager.can_trade()
        if not can_trade:
            self.logger.warning(f"Cannot trade: {reason}")
            return None
        
        # Calculate position size
        # Boost size if whale confidence is high
        base_size = self.position_manager.calculate_position_size()
        
        if fused.whale_signal and fused.whale_signal.confidence > 0.7:
            size = min(base_size * 1.5, Config.trading.max_position_usd)
        else:
            size = base_size
        
        if size < 1.0:
            return None
        
        # Determine token
        if fused.action == "BUY_YES":
            token_id = "yes"
            entry_price = market.yes_price
        else:
            token_id = "no"
            entry_price = market.no_price
        
        # Place order
        order = OrderRequest(
            token_id=token_id,
            side="BUY",
            size=size / entry_price,  # Convert to contracts
            price=entry_price
        )
        
        result = self.executor.place_order(order)
        
        if not result.success:
            self.logger.error(f"Order failed: {result.error}")
            return None
        
        self.trades_executed += 1
        
        # Record trade
        trade = Trade(
            trade_id=result.order_id or str(uuid.uuid4())[:8],
            market_id=market.market_id,
            market_question=market.question,
            coin_symbol=market.coin_symbol,
            direction=market.direction,
            action=fused.action,
            size_usd=size,
            entry_price=entry_price,
            predicted_prob=0.5 + fused.direction * 0.5,
            market_prob=market.yes_price,
            edge=fused.edge
        )
        
        self.position_manager.record_trade(trade)
        
        # Notify
        source = "WHALE+MOM" if fused.momentum_signal and fused.whale_signal else (
            "WHALE" if fused.whale_signal else "MOMENTUM"
        )
        
        notifier.success(
            f"Trade [{source}]: {market.coin_symbol}",
            f"{fused.action} ${size:.2f} @ ${entry_price:.3f} | Edge: {fused.edge*100:.1f}%"
        )
        
        return trade
    
    def run_cycle(self) -> int:
        """Run one trading cycle."""
        self.cycle_count += 1
        self.logger.info(f"─── Cycle {self.cycle_count} ───")
        
        # 1. Update prices
        prices = self.price_feed.fetch_prices()
        if not prices:
            self.logger.warning("Failed to fetch prices")
            return 0
        
        # 2. Refresh whale signals periodically (every 10 minutes)
        if (
            self.last_whale_refresh is None or
            (datetime.utcnow() - self.last_whale_refresh).seconds > 600
        ):
            self.refresh_whale_signals()
        
        # 3. Find opportunities
        opportunities = self.find_opportunities()
        self.logger.info(f"Found {len(opportunities)} opportunities")
        
        if not opportunities:
            return 0
        
        # 4. Execute best opportunity
        trades = 0
        for opp in opportunities[:1]:
            self.logger.info(
                f"Signal: {opp.market.coin_symbol} {opp.action} | "
                f"Edge: {opp.edge*100:.1f}% | Conf: {opp.confidence:.1%} | "
                f"Dir: {opp.direction:+.2f}"
            )
            
            if self.execute_opportunity(opp):
                trades += 1
        
        return trades
    
    def run(self, max_cycles: int = None):
        """Main bot loop."""
        self.running = True
        self.print_banner()
        
        def shutdown(signum, frame):
            self.logger.info("Shutdown signal received...")
            self.running = False
        
        sig.signal(sig.SIGINT, shutdown)
        sig.signal(sig.SIGTERM, shutdown)
        
        # Initial whale data
        self.refresh_whale_signals()
        self.position_manager.print_status()
        
        self.logger.info(f"Starting unified trading loop...")
        
        try:
            while self.running:
                try:
                    trades = self.run_cycle()
                    
                    if trades > 0:
                        self.position_manager.print_status()
                    
                    if max_cycles and self.cycle_count >= max_cycles:
                        break
                    
                    can_trade, reason = self.position_manager.can_trade()
                    if not can_trade:
                        self.logger.warning(f"Stopping: {reason}")
                        break
                    
                    time.sleep(Config.trading.scan_interval_seconds)
                    
                except Exception as e:
                    self.logger.error(f"Cycle error: {e}", exc_info=True)
                    time.sleep(30)
        
        finally:
            self.print_summary()
    
    def scan_only(self):
        """Scan for signals without trading."""
        self.print_banner()
        print("\n📡 SCANNING (no trading)...\n")
        
        # Get prices
        self.price_feed.fetch_prices()
        time.sleep(2)
        self.price_feed.fetch_prices()
        self.price_feed.print_status()
        
        # Get whale signals
        self.refresh_whale_signals()
        self.signal_aggregator.print_signals()
        
        # Get markets and opportunities
        self.market_finder.find_crypto_markets()
        self.market_finder.print_markets()
        
        opportunities = self.find_opportunities()
        
        print(f"\n{'═' * 70}")
        print(f"🎯 FUSED TRADING SIGNALS")
        print(f"{'═' * 70}\n")
        
        if not opportunities:
            print("   No opportunities meeting criteria.\n")
        else:
            for i, opp in enumerate(opportunities[:5], 1):
                m = opp.market
                print(f"   {i}. {m.coin_symbol} {m.direction} → {opp.action}")
                print(f"      Direction: {opp.direction:+.2f} | Confidence: {opp.confidence:.1%}")
                print(f"      Edge: {opp.edge*100:.1f}% | Weights: Mom {opp.momentum_weight:.0%} / Whale {opp.whale_weight:.0%}")
                
                if opp.whale_signal:
                    print(f"      Whale consensus: {opp.whale_signal.whale_count} whales, CI [{opp.whale_signal.lower_ci:.2f}, {opp.whale_signal.upper_ci:.2f}]")
                print()
    
    def print_summary(self):
        """Print session summary."""
        duration = (datetime.utcnow() - self.start_time).total_seconds() / 60
        stats = self.position_manager.get_session_stats()
        
        print(f"\n{'═' * 70}")
        print(f"📊 SESSION SUMMARY")
        print(f"{'═' * 70}")
        print(f"   Duration:      {duration:.1f} minutes")
        print(f"   Cycles:        {self.cycle_count}")
        print(f"   Signals:       {self.signals_generated}")
        print(f"   Trades:        {self.trades_executed}")
        print(f"   Win Rate:      {stats['win_rate']:.1f}%")
        print(f"   P&L:           ${stats['pnl']:+.2f}")
        print(f"   Final Bank:    ${stats['bankroll']:.2f}")
        print(f"{'═' * 70}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Unified Trader - Momentum + Whale Signals"
    )
    
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--cycles", type=int, default=None)
    parser.add_argument("--log-level", type=str, default="INFO")
    
    args = parser.parse_args()
    
    setup_logging(level=args.log_level)
    
    dry_run = not args.live
    
    if args.live:
        print("\n⚠️  LIVE TRADING MODE")
        confirm = input("   Type 'CONFIRM' to proceed: ")
        if confirm != "CONFIRM":
            print("   Aborted.")
            sys.exit(0)
    
    bot = UnifiedTradingBot(dry_run=dry_run)
    
    if args.scan:
        bot.scan_only()
    else:
        bot.run(max_cycles=args.cycles)


if __name__ == "__main__":
    main()
