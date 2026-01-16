"""
Polymarket Whale Tracker - Main Orchestrator
=============================================
Runs scanner, whale tracker, and real-time monitor concurrently.
"""

import asyncio
import signal
import sys
import time
import argparse
from datetime import datetime
from typing import Optional

from config import Config
from scanner import ArbitrageScanner
from whale_tracker import WhaleTracker
from notifier import notifier


class WhaleTrackerOrchestrator:
    """Main orchestrator that runs all components."""
    
    def __init__(self):
        self.scanner = ArbitrageScanner()
        self.tracker = WhaleTracker()
        self.running = False
        self.start_time: Optional[datetime] = None
    
    def print_banner(self):
        banner = """
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║   🐳  POLYMARKET WHALE TRACKER v1.0                                           ║
║       Real-time Smart Money & Whale Wallet Intelligence System                ║
║                                                                               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║   Components:                                                                 ║
║   • Arbitrage Scanner    - Detects pricing inefficiencies                     ║
║   • Whale Tracker        - Monitors profitable wallets                        ║
║   • Real-time Monitor    - WebSocket order book feeds                         ║
║   • Alert System         - Console / Discord / Telegram                       ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
        """
        print(banner)
    
    def run_scanner(self, verbose: bool = True) -> dict:
        """Run a single arbitrage scan."""
        notifier.info("Scanner", "Starting arbitrage scan...")
        results = self.scanner.scan(verbose=verbose)
        
        if results["binary_count"] > 0:
            notifier.success(
                "Arbitrage Found",
                f"Found {results['binary_count']} binary + {results['multi_count']} multi-outcome opportunities"
            )
        
        return results
    
    def run_whale_discovery(self, min_pnl: float = 10000) -> list:
        """Discover and start tracking top wallets."""
        notifier.info("Whale Discovery", f"Searching for wallets with PnL >= ${min_pnl:,.0f}")
        
        discovered = self.tracker.discover_top_wallets(min_pnl=min_pnl)
        
        for addr in discovered[:10]:
            self.tracker.add_wallet(addr)
        
        notifier.success("Whales Found", f"Now tracking {len(self.tracker.tracked_wallets)} wallets")
        
        return discovered
    
    def run_whale_refresh(self, verbose: bool = True) -> dict:
        """Refresh all tracked whale positions."""
        return self.tracker.refresh_all(verbose=verbose)
    
    def run_continuous(self, scan_interval: int = 300, whale_interval: int = 60):
        """Run continuous scanning loop."""
        self.running = True
        self.start_time = datetime.utcnow()
        
        def signal_handler(sig, frame):
            print("\n\n👋 Shutting down gracefully...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        notifier.info("Continuous Mode", f"Scan interval: {scan_interval}s | Whale refresh: {whale_interval}s")
        
        last_scan = 0
        last_whale = 0
        
        try:
            while self.running:
                now = time.time()
                
                # Run arbitrage scan
                if now - last_scan >= scan_interval:
                    self.run_scanner(verbose=True)
                    last_scan = now
                
                # Refresh whale positions
                if now - last_whale >= whale_interval:
                    self.run_whale_refresh(verbose=True)
                    last_whale = now
                
                time.sleep(10)  # Check every 10 seconds
        
        except Exception as e:
            notifier.critical("Error", f"Orchestrator error: {e}")
        
        finally:
            duration = (datetime.utcnow() - self.start_time).total_seconds() / 60
            print(f"\n📊 Session Summary: Ran for {duration:.1f} minutes")
    
    def run_once(self):
        """Run a single scan cycle."""
        self.print_banner()
        
        print("\n" + "─" * 70)
        print("📡 STEP 1: Scanning for Arbitrage Opportunities")
        print("─" * 70)
        self.run_scanner()
        
        print("\n" + "─" * 70)
        print("🔍 STEP 2: Discovering Whale Wallets")
        print("─" * 70)
        self.run_whale_discovery()
        
        print("\n" + "─" * 70)
        print("📊 STEP 3: Refreshing Whale Positions")
        print("─" * 70)
        self.run_whale_refresh()
        
        print("\n" + "═" * 70)
        print("✅ SCAN COMPLETE")
        print("═" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Whale Tracker - Smart Money Intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --scan-once          # Single scan cycle
  python main.py --loop               # Continuous monitoring
  python main.py --scanner            # Arbitrage scanner only
  python main.py --whales             # Whale tracker only
        """
    )
    
    parser.add_argument("--scan-once", action="store_true", help="Run a single scan cycle")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--scanner", action="store_true", help="Run arbitrage scanner only")
    parser.add_argument("--whales", action="store_true", help="Run whale tracker only")
    parser.add_argument("--discover", action="store_true", help="Discover top wallets")
    parser.add_argument("--interval", type=int, default=300, help="Scan interval (seconds)")
    parser.add_argument("--min-pnl", type=float, default=10000, help="Min PnL for whale discovery")
    parser.add_argument("--quiet", action="store_true", help="Reduce output verbosity")
    
    args = parser.parse_args()
    
    orchestrator = WhaleTrackerOrchestrator()
    
    if args.scanner:
        orchestrator.print_banner()
        orchestrator.run_scanner(verbose=not args.quiet)
    
    elif args.whales:
        orchestrator.print_banner()
        if args.discover:
            orchestrator.run_whale_discovery(min_pnl=args.min_pnl)
        orchestrator.run_whale_refresh(verbose=not args.quiet)
    
    elif args.loop:
        orchestrator.print_banner()
        if args.discover:
            orchestrator.run_whale_discovery(min_pnl=args.min_pnl)
        orchestrator.run_continuous(scan_interval=args.interval)
    
    else:  # Default: scan-once
        orchestrator.run_once()


if __name__ == "__main__":
    main()
