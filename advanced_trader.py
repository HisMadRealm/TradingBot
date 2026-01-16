"""
Polymarket Advanced Trading Bot
================================
Full trading bot using advanced statistical aggregation.

Features:
- Time-weighted whale signals (exponential decay)
- Bayesian fusion of momentum + whale signals
- Rolling accuracy tracking per whale
- Lead-lag analysis (Granger causality)
- Gaussian Process trajectory prediction
- Category-specific whale accuracy

Usage:
    python advanced_trader.py --scan     # Scan for signals
    python advanced_trader.py --dry-run  # Simulation
    python advanced_trader.py --live     # Real trading
"""

import argparse
import logging
import signal as sig
import sys
import time
import uuid
from datetime import datetime
from typing import Optional, List

from config import Config
from price_feed import PriceFeed, MomentumSignal
from market_finder import MarketFinder, CryptoMarket
from position_manager import PositionManager, Trade
from executor import OrderExecutor, OrderRequest
from whale_collector import WhaleDataCollector
from advanced_aggregator import AdvancedSignalAggregator, AdvancedSignal
from notifier import notifier

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

def setup_logging(log_file: str = "bot.log", level: str = "INFO"):
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    
    return logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED TRADING BOT
# ═══════════════════════════════════════════════════════════════════════════════

class AdvancedTradingBot:
    """
    Trading bot with advanced statistical aggregation.
    """
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.running = False
        self.cycle_count = 0
        
        # Core components
        self.price_feed = PriceFeed()
        self.market_finder = MarketFinder()
        self.position_manager = PositionManager()
        self.executor = OrderExecutor(dry_run=dry_run)
        
        # Advanced whale aggregation
        self.whale_collector = WhaleDataCollector()
        self.aggregator = AdvancedSignalAggregator(self.whale_collector)
        
        self.logger = logging.getLogger(__name__)
        
        # Stats
        self.signals_generated = 0
        self.trades_executed = 0
        self.start_time = datetime.utcnow()
        
        # Cache
        self.whale_signals: dict = {}
        self.last_whale_refresh = None
        self.momentum_cache: dict = {}
    
    def print_banner(self):
        mode = "🧪 DRY RUN" if self.dry_run else "🔴 LIVE TRADING"
        
        print(f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║   🧬🐳 POLYMARKET ADVANCED TRADER v4.0                                        ║
║         Statistical Whale Aggregation + Bayesian Fusion                       ║
║                                                                               ║
║   {mode:<60}           ║
║                                                                               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║   ✓ Time-weighted signals (6h half-life)                                      ║
║   ✓ Bayesian updating (momentum as likelihood)                                ║
║   ✓ Rolling accuracy tracking per whale                                       ║
║   ✓ Granger causality lead-lag detection                                      ║
║   ✓ Gaussian Process trajectory prediction                                    ║
╚═══════════════════════════════════════════════════════════════════════════════╝
        """)
    
    def refresh_whale_signals(self, lookback_hours: int = 24):
        """Refresh advanced whale signals."""
        self.logger.info("Computing advanced whale signals...")
        
        signals = self.aggregator.get_all_signals(lookback_hours=lookback_hours)
        self.whale_signals = {s.market_id: s for s in signals}
        self.last_whale_refresh = datetime.utcnow()
        
        self.logger.info(f"Computed {len(signals)} advanced signals")
    
    def find_opportunities(self) -> List[AdvancedSignal]:
        """Find trading opportunities using advanced signals."""
        opportunities = []
        
        # Get momentum signals
        momentum_signals = self.price_feed.get_all_signals()
        momentum_by_coin = {s.coin_id: s for s in momentum_signals}
        
        # Get current markets
        markets = self.market_finder.find_crypto_markets(min_minutes_left=3.0)
        
        if not markets:
            return []
        
        for market in markets:
            if self.position_manager.has_position(market.market_id):
                continue
            
            # Get pre-computed whale signal
            whale_signal = self.whale_signals.get(market.market_id)
            
            if whale_signal is None:
                continue
            
            # Get momentum for additional Bayesian update
            momentum = momentum_by_coin.get(market.coin_id)
            
            if momentum:
                # Re-compute signal with momentum
                whale_trades = self.whale_collector.get_market_activity(market.market_id)
                if whale_trades:
                    # Convert momentum to signal
                    if market.direction == momentum.direction:
                        mom_signal = (momentum.predicted_probability - 0.5) * 2
                    else:
                        mom_signal = (0.5 - momentum.predicted_probability) * 2
                    
                    whale_signal = self.aggregator.aggregate_market_signals(
                        trades=whale_trades,
                        momentum_signal=mom_signal,
                        momentum_confidence=momentum.confidence
                    )
            
            if whale_signal is None:
                continue
            
            # Check if signal is actionable
            if whale_signal.confidence >= 0.4 and whale_signal.is_significant:
                self.signals_generated += 1
                opportunities.append(whale_signal)
        
        # Sort by expected value
        opportunities.sort(
            key=lambda s: s.confidence * abs(s.direction) * s.bet_size_multiplier,
            reverse=True
        )
        
        return opportunities
    
    def execute_opportunity(self, signal: AdvancedSignal) -> Optional[Trade]:
        """Execute an advanced trading signal."""
        can_trade, reason = self.position_manager.can_trade()
        if not can_trade:
            self.logger.warning(f"Cannot trade: {reason}")
            return None
        
        # Calculate position size with confidence multiplier
        base_size = self.position_manager.calculate_position_size()
        size = base_size * signal.bet_size_multiplier
        size = min(size, Config.trading.max_position_usd)
        
        if size < 1.0:
            return None
        
        # Determine action
        action = signal.recommended_action
        if action == "HOLD":
            return None
        
        # Get market price (we'd need to look this up)
        entry_price = signal.posterior if action == "BUY_YES" else (1 - signal.posterior)
        entry_price = max(0.05, min(0.95, entry_price))
        
        # Place order
        order = OrderRequest(
            token_id="yes" if action == "BUY_YES" else "no",
            side="BUY",
            size=size / entry_price,
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
            market_id=signal.market_id,
            market_question=signal.market_question,
            coin_symbol=signal.category,
            direction=signal.direction,
            action=action,
            size_usd=size,
            entry_price=entry_price,
            predicted_prob=signal.posterior,
            market_prob=signal.prior,
            edge=abs(signal.posterior - signal.prior)
        )
        
        self.position_manager.record_trade(trade)
        
        # Notification with advanced stats
        gp_info = f"GP: {signal.gp_mean:+.2f}" if signal.gp_mean else ""
        
        notifier.success(
            f"Trade [ADV]: {signal.category}",
            f"{action} ${size:.2f} | Post: {signal.posterior:.1%} | "
            f"Agree: {signal.whale_agreement:.0%} {gp_info}"
        )
        
        return trade
    
    def run_cycle(self) -> int:
        """Run one trading cycle."""
        self.cycle_count += 1
        self.logger.info(f"─── Cycle {self.cycle_count} ───")
        
        # Update prices
        prices = self.price_feed.fetch_prices()
        if not prices:
            self.logger.warning("Failed to fetch prices")
            return 0
        
        # Refresh whale signals every 10 minutes
        if (
            self.last_whale_refresh is None or
            (datetime.utcnow() - self.last_whale_refresh).seconds > 600
        ):
            self.refresh_whale_signals()
        
        # Find opportunities
        opportunities = self.find_opportunities()
        self.logger.info(f"Found {len(opportunities)} opportunities")
        
        if not opportunities:
            return 0
        
        # Execute best opportunity
        trades = 0
        for opp in opportunities[:1]:
            self.logger.info(
                f"Signal: {opp.category} {opp.recommended_action} | "
                f"Posterior: {opp.posterior:.1%} | Conf: {opp.confidence:.1%} | "
                f"SNR: {opp.signal_to_noise:.2f}"
            )
            
            if self.execute_opportunity(opp):
                trades += 1
        
        return trades
    
    def run(self, max_cycles: int = None):
        """Main trading loop."""
        self.running = True
        self.print_banner()
        
        def shutdown(signum, frame):
            self.logger.info("Shutdown...")
            self.running = False
        
        sig.signal(sig.SIGINT, shutdown)
        sig.signal(sig.SIGTERM, shutdown)
        
        self.refresh_whale_signals()
        self.position_manager.print_status()
        
        self.logger.info("Starting advanced trading loop...")
        
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
        print("\n📡 ADVANCED SCAN (no trading)...\n")
        
        # Get prices
        self.price_feed.fetch_prices()
        time.sleep(2)
        self.price_feed.fetch_prices()
        self.price_feed.print_status()
        
        # Compute advanced signals
        self.refresh_whale_signals()
        self.aggregator.print_signals()
        
        # Find opportunities
        self.market_finder.find_crypto_markets()
        opportunities = self.find_opportunities()
        
        print(f"\n{'═' * 80}")
        print(f"🎯 ADVANCED TRADING SIGNALS")
        print(f"{'═' * 80}\n")
        
        if not opportunities:
            print("   No opportunities meeting advanced criteria.\n")
        else:
            for i, s in enumerate(opportunities[:5], 1):
                print(f"   {i}. {s.market_question[:50]}...")
                print(f"      Action: {s.recommended_action}")
                print(f"      Posterior: {s.posterior:.1%} (Prior: {s.prior:.1%})")
                print(f"      Confidence: {s.confidence:.1%} | Agreement: {s.whale_agreement:.0%}")
                print(f"      95% CI: [{s.lower_ci:.2f}, {s.upper_ci:.2f}]")
                if s.gp_mean is not None:
                    print(f"      GP Forecast: {s.gp_mean:+.2f} ± {s.gp_std:.2f}")
                print(f"      Bet multiplier: {s.bet_size_multiplier:.2f}x")
                print()
    
    def print_summary(self):
        """Print session summary."""
        duration = (datetime.utcnow() - self.start_time).total_seconds() / 60
        stats = self.position_manager.get_session_stats()
        
        print(f"\n{'═' * 80}")
        print(f"📊 ADVANCED SESSION SUMMARY")
        print(f"{'═' * 80}")
        print(f"   Duration:      {duration:.1f} min")
        print(f"   Cycles:        {self.cycle_count}")
        print(f"   Signals:       {self.signals_generated}")
        print(f"   Trades:        {self.trades_executed}")
        print(f"   P&L:           ${stats['pnl']:+.2f}")
        print(f"{'═' * 80}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Advanced Trader - Statistical Whale Aggregation"
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
        confirm = input("   Type 'CONFIRM': ")
        if confirm != "CONFIRM":
            print("   Aborted.")
            sys.exit(0)
    
    bot = AdvancedTradingBot(dry_run=dry_run)
    
    if args.scan:
        bot.scan_only()
    else:
        bot.run(max_cycles=args.cycles)


if __name__ == "__main__":
    main()
