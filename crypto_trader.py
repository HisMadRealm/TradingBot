"""
Polymarket Momentum Trading Bot
================================
15-minute crypto binary market trading bot using momentum signals.

Based on the strategy of whale 0x8dxd who turned $313 → $558k+ with 98% win rate.

Usage:
    python crypto_trader.py --dry-run          # Test mode (no real trades)
    python crypto_trader.py --live             # Live trading mode
    python crypto_trader.py --scan             # Just scan for opportunities
"""

import argparse
import logging
import signal
import sys
import time
import uuid
from datetime import datetime
from typing import Optional, List

from config import Config
from price_feed import PriceFeed, MomentumSignal
from market_finder import MarketFinder, CryptoMarket
from position_manager import PositionManager, Trade
from executor import OrderExecutor, OrderRequest, OrderResult
from notifier import notifier

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def setup_logging(log_file: str = "bot.log", level: str = "INFO"):
    """Configure logging to file and console."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TRADING BOT
# ═══════════════════════════════════════════════════════════════════════════════

class CryptoTradingBot:
    """
    Main trading bot for 15-minute crypto markets.
    
    Strategy:
    1. Fetch real-time prices from CoinGecko
    2. Calculate 1-minute momentum (price change %)
    3. Find matching Polymarket 15-min markets
    4. Compare momentum prediction vs market odds
    5. If edge > threshold, place bet
    """
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.running = False
        self.cycle_count = 0
        
        # Initialize components
        self.price_feed = PriceFeed()
        self.market_finder = MarketFinder()
        self.position_manager = PositionManager()
        self.executor = OrderExecutor(dry_run=dry_run)
        
        self.logger = logging.getLogger(__name__)
        
        # Stats
        self.signals_generated = 0
        self.trades_attempted = 0
        self.start_time = datetime.utcnow()
    
    def print_banner(self):
        """Print startup banner."""
        mode = "🧪 DRY RUN MODE" if self.dry_run else "🔴 LIVE TRADING MODE"
        
        banner = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║   🤖  POLYMARKET CRYPTO MOMENTUM TRADER v2.0                                  ║
║       15-Minute Binary Market Trading Bot                                     ║
║                                                                               ║
║   {mode:<60}           ║
║                                                                               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║   Strategy: Whale 0x8dxd ($313 → $558k+, 98% win rate)                        ║
║   Target:   BTC, ETH, SOL, XRP 15-minute markets                              ║
║   Edge:     {Config.trading.edge_threshold*100:.0f}% minimum required                                         ║
║   Size:     {Config.trading.bet_size_percent*100:.0f}% of bankroll per trade                                   ║
╚═══════════════════════════════════════════════════════════════════════════════╝
        """
        print(banner)
        
        if not self.dry_run:
            print("⚠️  WARNING: Real money trading enabled!")
            print("    Ensure your .env credentials are correct.\n")
    
    # ─────────────────────────────────────────────────────────────────────────
    # MAIN TRADING LOGIC
    # ─────────────────────────────────────────────────────────────────────────
    
    def find_opportunities(self) -> List[dict]:
        """
        Find trading opportunities by matching momentum signals to markets.
        
        Returns:
            List of opportunity dicts with market, signal, and edge info
        """
        opportunities = []
        
        # Get momentum signals
        signals = self.price_feed.get_all_signals()
        
        if not signals:
            self.logger.debug("No momentum signals available")
            return []
        
        # Get current markets
        markets = self.market_finder.find_crypto_markets(min_minutes_left=3.0)
        
        if not markets:
            self.logger.debug("No suitable markets found")
            return []
        
        # Match signals to markets
        for signal in signals:
            self.signals_generated += 1
            
            # Find markets for this coin
            coin_markets = [m for m in markets if m.coin_id == signal.coin_id]
            
            for market in coin_markets:
                # Skip if we already have a position
                if self.position_manager.has_position(market.market_id):
                    continue
                
                # Determine if signal matches market direction
                # If momentum is UP and market is asking "will it go UP?" → high predicted prob
                # If momentum is DOWN and market is asking "will it go UP?" → low predicted prob
                
                if market.direction == signal.direction:
                    predicted_prob = signal.predicted_probability
                else:
                    predicted_prob = 1 - signal.predicted_probability
                
                # Calculate edge
                edge, action = market.edge_vs_prediction(predicted_prob)
                
                # Check if edge meets threshold
                if edge >= Config.trading.edge_threshold:
                    opportunities.append({
                        "market": market,
                        "signal": signal,
                        "predicted_prob": predicted_prob,
                        "market_prob": market.implied_probability,
                        "edge": edge,
                        "action": action
                    })
        
        # Sort by edge (highest first)
        opportunities.sort(key=lambda x: x["edge"], reverse=True)
        
        return opportunities
    
    def execute_opportunity(self, opp: dict) -> Optional[Trade]:
        """Execute a trading opportunity."""
        market: CryptoMarket = opp["market"]
        signal: MomentumSignal = opp["signal"]
        
        # Risk checks
        can_trade, reason = self.position_manager.can_trade()
        if not can_trade:
            self.logger.warning(f"Cannot trade: {reason}")
            return None
        
        # Calculate position size
        size = self.position_manager.calculate_position_size()
        
        if size < 1.0:
            self.logger.warning(f"Position size too small: ${size:.2f}")
            return None
        
        # Determine which token to buy
        if opp["action"] == "BUY_YES":
            token_id = "yes"  # Would need actual token ID from market data
            entry_price = market.yes_price
        else:
            token_id = "no"
            entry_price = market.no_price
        
        # Create and place order
        order = OrderRequest(
            market_id=market.market_id,
            token_id=token_id,
            side="BUY",
            size=size,
            price=entry_price
        )
        
        self.trades_attempted += 1
        result = self.executor.place_order(order)
        
        if not result.success:
            self.logger.error(f"Order failed: {result.error}")
            notifier.warning("Order Failed", result.error or "Unknown error")
            return None
        
        # Record trade
        trade = Trade(
            trade_id=result.order_id or str(uuid.uuid4())[:8],
            market_id=market.market_id,
            market_question=market.question,
            coin_symbol=signal.symbol,
            direction=market.direction,
            action=opp["action"],
            size_usd=result.filled_size,
            entry_price=result.filled_price,
            predicted_prob=opp["predicted_prob"],
            market_prob=opp["market_prob"],
            edge=opp["edge"]
        )
        
        self.position_manager.record_trade(trade)
        
        # Notify
        notifier.success(
            f"Trade: {signal.symbol} {opp['action']}",
            f"${size:.2f} @ ${entry_price:.3f} | Edge: {opp['edge']*100:.1f}%"
        )
        
        return trade
    
    def run_cycle(self) -> int:
        """
        Run one trading cycle.
        
        Returns:
            Number of trades executed
        """
        self.cycle_count += 1
        
        self.logger.info(f"─── Cycle {self.cycle_count} ───")
        
        # 1. Update prices
        prices = self.price_feed.fetch_prices()
        if not prices:
            self.logger.warning("Failed to fetch prices")
            return 0
        
        # 2. Find opportunities
        opportunities = self.find_opportunities()
        
        self.logger.info(f"Found {len(opportunities)} opportunities")
        
        if not opportunities:
            return 0
        
        # 3. Execute best opportunity (one trade per cycle to manage risk)
        trades_executed = 0
        
        for opp in opportunities[:1]:  # Only take best one
            market = opp["market"]
            signal = opp["signal"]
            
            self.logger.info(
                f"Opportunity: {signal.symbol} {opp['action']} | "
                f"Edge: {opp['edge']*100:.1f}% | "
                f"Momentum: {signal.change_percent:+.2f}%"
            )
            
            trade = self.execute_opportunity(opp)
            if trade:
                trades_executed += 1
        
        return trades_executed
    
    def run(self, max_cycles: int = None):
        """
        Main bot loop.
        
        Args:
            max_cycles: Stop after N cycles (None = run forever)
        """
        self.running = True
        self.print_banner()
        
        # Signal handlers for graceful shutdown
        def shutdown(signum, frame):
            self.logger.info("Shutdown signal received...")
            self.running = False
        
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
        
        # Initial status
        self.position_manager.print_status()
        
        self.logger.info(f"Starting trading loop (interval: {Config.trading.scan_interval_seconds}s)")
        
        try:
            while self.running:
                try:
                    trades = self.run_cycle()
                    
                    if trades > 0:
                        self.position_manager.print_status()
                    
                    # Check exit conditions
                    if max_cycles and self.cycle_count >= max_cycles:
                        self.logger.info(f"Reached max cycles ({max_cycles})")
                        break
                    
                    # Rate limit check
                    can_trade, reason = self.position_manager.can_trade()
                    if not can_trade:
                        self.logger.warning(f"Stopping: {reason}")
                        break
                    
                    # Sleep until next cycle
                    self.logger.debug(f"Sleeping {Config.trading.scan_interval_seconds}s...")
                    time.sleep(Config.trading.scan_interval_seconds)
                    
                except Exception as e:
                    self.logger.error(f"Cycle error: {e}", exc_info=True)
                    time.sleep(30)  # Wait and retry
        
        finally:
            self.print_summary()
    
    def scan_only(self):
        """Just scan for opportunities without trading."""
        self.print_banner()
        print("\n📡 SCANNING FOR OPPORTUNITIES (no trading)...\n")
        
        # Fetch prices
        self.price_feed.fetch_prices()
        time.sleep(2)
        self.price_feed.fetch_prices()  # Get second data point for momentum
        
        self.price_feed.print_status()
        
        # Find markets
        self.market_finder.find_crypto_markets()
        self.market_finder.print_markets()
        
        # Find opportunities
        opportunities = self.find_opportunities()
        
        print(f"\n{'═' * 70}")
        print(f"🎯 TRADING OPPORTUNITIES (Edge >= {Config.trading.edge_threshold*100:.0f}%)")
        print(f"{'═' * 70}\n")
        
        if not opportunities:
            print("   No opportunities meeting edge threshold.\n")
        else:
            for i, opp in enumerate(opportunities[:5], 1):
                m = opp["market"]
                s = opp["signal"]
                
                print(f"   {i}. {s.symbol} {m.direction}")
                print(f"      Market: {m.question[:50]}...")
                print(f"      Action: {opp['action']}")
                print(f"      Edge: {opp['edge']*100:.1f}% | Momentum: {s.change_percent:+.2f}%")
                print(f"      Predicted: {opp['predicted_prob']:.1%} vs Market: {opp['market_prob']:.1%}")
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
        print(f"   Trades:        {stats['total_trades']} ({stats['wins']}W / {stats['losses']}L)")
        print(f"   Win Rate:      {stats['win_rate']:.1f}%")
        print(f"   P&L:           ${stats['pnl']:+.2f}")
        print(f"   Final Bank:    ${stats['bankroll']:.2f}")
        print(f"{'═' * 70}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Crypto Momentum Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Run in simulation mode (default: True)"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Enable live trading with real funds"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Just scan for opportunities, don't trade"
    )
    parser.add_argument(
        "--cycles", type=int, default=None,
        help="Stop after N cycles"
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(level=args.log_level)
    
    # Determine mode
    dry_run = not args.live
    
    if args.live:
        print("\n⚠️  LIVE TRADING MODE SELECTED")
        print("   This will use REAL MONEY from your Polymarket account.")
        confirm = input("   Type 'CONFIRM' to proceed: ")
        if confirm != "CONFIRM":
            print("   Aborted.")
            sys.exit(0)
    
    # Create and run bot
    bot = CryptoTradingBot(dry_run=dry_run)
    
    if args.scan:
        bot.scan_only()
    else:
        bot.run(max_cycles=args.cycles)


if __name__ == "__main__":
    main()
