"""
Polymarket Whale Tracker - Arbitrage Scanner
=============================================
Scans Polymarket for arbitrage opportunities where the sum of outcome prices < 1.
"""

import requests
import time
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from config import (
    GAMMA_API_BASE,
    Config,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY
)

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ArbitrageOpportunity:
    """Represents a detected arbitrage opportunity."""
    market_id: str
    question: str
    slug: str
    yes_price: float
    no_price: float
    combined_price: float
    arb_percent: float
    volume_24h: float
    open_interest: float
    url: str
    detected_at: datetime
    
    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "question": self.question[:80] + "..." if len(self.question) > 80 else self.question,
            "slug": self.slug,
            "yes_price": f"${self.yes_price:.3f}",
            "no_price": f"${self.no_price:.3f}",
            "combined": f"${self.combined_price:.3f}",
            "arb_percent": f"{self.arb_percent:.2f}%",
            "volume_24h": f"${self.volume_24h:,.0f}",
            "open_interest": f"${self.open_interest:,.0f}",
            "url": self.url,
            "detected_at": self.detected_at.isoformat()
        }


@dataclass
class MultiOutcomeArb:
    """Arbitrage in multi-outcome markets (sum of all outcomes < 1)."""
    market_id: str
    question: str
    slug: str
    outcomes: List[Dict[str, float]]  # [{name: price}, ...]
    combined_price: float
    arb_percent: float
    volume_24h: float
    url: str
    detected_at: datetime


# ═══════════════════════════════════════════════════════════════════════════════
# API FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_active_markets(limit: int = 100, offset: int = 0) -> List[Dict]:
    """
    Fetch active markets from Gamma API with pagination.
    
    Args:
        limit: Number of markets per request (max 100)
        offset: Pagination offset
    
    Returns:
        List of market dictionaries
    """
    url = f"{GAMMA_API_BASE}/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "offset": offset,
        "order": "volume",
        "ascending": "false"
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url, 
                headers=Config.headers, 
                params=params, 
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  ⚠ API error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY)
            else:
                print(f"  ✗ Failed to fetch markets after {MAX_RETRIES} attempts: {e}")
                return []
    return []


def fetch_market_details(market_id: str) -> Optional[Dict]:
    """Fetch detailed information for a specific market."""
    url = f"{GAMMA_API_BASE}/markets/{market_id}"
    
    try:
        response = requests.get(url, headers=Config.headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ Error fetching market {market_id}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# ARBITRAGE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def check_binary_arbitrage(market: Dict) -> Optional[ArbitrageOpportunity]:
    """
    Check a binary market (YES/NO) for arbitrage opportunity.
    
    Arbitrage exists when: YES_price + NO_price < 1 (minus fees)
    """
    if market.get("closed") or not market.get("active"):
        return None
    
    tokens = market.get("tokens", [])
    if len(tokens) != 2:
        return None  # Not a simple binary market
    
    yes_price = None
    no_price = None
    
    for token in tokens:
        price = float(token.get("price", 0) or 0)
        outcome = token.get("outcome", "").upper()
        
        if "YES" in outcome:
            yes_price = price
        elif "NO" in outcome:
            no_price = price
    
    if yes_price is None or no_price is None:
        return None
    
    combined = yes_price + no_price
    volume_24h = float(market.get("volume24hrs", 0) or 0)
    open_interest = float(market.get("liquidityNum", 0) or 0)
    
    # Check thresholds
    if combined >= Config.scanner.arb_threshold:
        return None
    
    if volume_24h < Config.scanner.min_liquidity_usd:
        return None
    
    arb_percent = (1 - combined) * 100
    
    if arb_percent < Config.scanner.min_arb_percent:
        return None
    
    return ArbitrageOpportunity(
        market_id=market.get("id", ""),
        question=market.get("question", "Unknown"),
        slug=market.get("slug", ""),
        yes_price=yes_price,
        no_price=no_price,
        combined_price=combined,
        arb_percent=arb_percent,
        volume_24h=volume_24h,
        open_interest=open_interest,
        url=f"https://polymarket.com/event/{market.get('slug', '')}",
        detected_at=datetime.utcnow()
    )


def check_multi_outcome_arbitrage(market: Dict) -> Optional[MultiOutcomeArb]:
    """
    Check a multi-outcome market for arbitrage.
    
    Arbitrage exists when: sum of all outcome prices < 1
    """
    if market.get("closed") or not market.get("active"):
        return None
    
    tokens = market.get("tokens", [])
    if len(tokens) <= 2:
        return None  # Binary markets handled separately
    
    outcomes = []
    total_price = 0
    
    for token in tokens:
        price = float(token.get("price", 0) or 0)
        outcome_name = token.get("outcome", "Unknown")
        outcomes.append({"name": outcome_name, "price": price})
        total_price += price
    
    volume_24h = float(market.get("volume24hrs", 0) or 0)
    
    if total_price >= Config.scanner.arb_threshold:
        return None
    
    if volume_24h < Config.scanner.min_liquidity_usd:
        return None
    
    arb_percent = (1 - total_price) * 100
    
    if arb_percent < Config.scanner.min_arb_percent:
        return None
    
    return MultiOutcomeArb(
        market_id=market.get("id", ""),
        question=market.get("question", "Unknown"),
        slug=market.get("slug", ""),
        outcomes=outcomes,
        combined_price=total_price,
        arb_percent=arb_percent,
        volume_24h=volume_24h,
        url=f"https://polymarket.com/event/{market.get('slug', '')}",
        detected_at=datetime.utcnow()
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class ArbitrageScanner:
    """Main scanner for detecting arbitrage opportunities."""
    
    def __init__(self):
        self.binary_opportunities: List[ArbitrageOpportunity] = []
        self.multi_opportunities: List[MultiOutcomeArb] = []
        self.last_scan: Optional[datetime] = None
        self.markets_scanned: int = 0
    
    def scan(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Perform a full scan of all active markets.
        
        Returns:
            Dictionary with scan results and statistics
        """
        start_time = datetime.utcnow()
        
        if verbose:
            print(f"\n{'═' * 70}")
            print(f"🔍 POLYMARKET ARBITRAGE SCANNER")
            print(f"   Started: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"   Threshold: YES + NO < ${Config.scanner.arb_threshold}")
            print(f"   Min Volume: ${Config.scanner.min_liquidity_usd:,}")
            print(f"{'═' * 70}\n")
        
        self.binary_opportunities = []
        self.multi_opportunities = []
        offset = 0
        total_markets = 0
        
        while total_markets < Config.scanner.max_markets_per_scan:
            if verbose:
                print(f"  📡 Fetching markets (offset: {offset})...")
            
            markets = fetch_active_markets(limit=100, offset=offset)
            
            if not markets:
                break
            
            for market in markets:
                # Check binary arbitrage
                binary_arb = check_binary_arbitrage(market)
                if binary_arb:
                    self.binary_opportunities.append(binary_arb)
                    if verbose:
                        print(f"  💰 BINARY ARB: {binary_arb.arb_percent:.2f}% | {binary_arb.question[:50]}...")
                
                # Check multi-outcome arbitrage
                multi_arb = check_multi_outcome_arbitrage(market)
                if multi_arb:
                    self.multi_opportunities.append(multi_arb)
                    if verbose:
                        print(f"  🎯 MULTI ARB: {multi_arb.arb_percent:.2f}% | {multi_arb.question[:50]}...")
            
            total_markets += len(markets)
            offset += 100
            
            if len(markets) < 100:
                break
            
            time.sleep(Config.scanner.sleep_between_calls)
        
        self.last_scan = datetime.utcnow()
        self.markets_scanned = total_markets
        
        # Sort by arbitrage percentage (highest first)
        self.binary_opportunities.sort(key=lambda x: x.arb_percent, reverse=True)
        self.multi_opportunities.sort(key=lambda x: x.arb_percent, reverse=True)
        
        duration = (self.last_scan - start_time).total_seconds()
        
        if verbose:
            self._print_summary(duration)
        
        return {
            "binary_count": len(self.binary_opportunities),
            "multi_count": len(self.multi_opportunities),
            "markets_scanned": total_markets,
            "duration_seconds": duration,
            "binary_opportunities": [o.to_dict() for o in self.binary_opportunities[:10]],
            "timestamp": start_time.isoformat()
        }
    
    def _print_summary(self, duration: float):
        """Print scan summary to console."""
        print(f"\n{'─' * 70}")
        print(f"📊 SCAN COMPLETE")
        print(f"   Markets Scanned: {self.markets_scanned}")
        print(f"   Duration: {duration:.1f}s")
        print(f"   Binary Opportunities: {len(self.binary_opportunities)}")
        print(f"   Multi-Outcome Opportunities: {len(self.multi_opportunities)}")
        print(f"{'─' * 70}")
        
        if self.binary_opportunities:
            print(f"\n🏆 TOP BINARY ARBITRAGE OPPORTUNITIES:")
            for i, opp in enumerate(self.binary_opportunities[:5], 1):
                print(f"\n   {i}. {opp.question[:60]}...")
                print(f"      YES: ${opp.yes_price:.3f} | NO: ${opp.no_price:.3f} | Combined: ${opp.combined_price:.3f}")
                print(f"      Arb: {opp.arb_percent:.2f}% | Volume: ${opp.volume_24h:,.0f}")
                print(f"      URL: {opp.url}")
        else:
            print("\n   No binary arbitrage opportunities found meeting criteria.")
        
        print(f"\n{'═' * 70}\n")
    
    def get_opportunities_json(self) -> str:
        """Export all opportunities as JSON."""
        return json.dumps({
            "scan_time": self.last_scan.isoformat() if self.last_scan else None,
            "markets_scanned": self.markets_scanned,
            "binary_opportunities": [o.to_dict() for o in self.binary_opportunities],
            "multi_opportunities": [
                {
                    "market_id": m.market_id,
                    "question": m.question,
                    "outcomes": m.outcomes,
                    "combined": m.combined_price,
                    "arb_percent": m.arb_percent,
                    "volume_24h": m.volume_24h,
                    "url": m.url
                }
                for m in self.multi_opportunities
            ]
        }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Command-line interface for the scanner."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Polymarket Arbitrage Scanner")
    parser.add_argument("--test", action="store_true", help="Run a single test scan")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between scans (default: 300)")
    
    args = parser.parse_args()
    
    scanner = ArbitrageScanner()
    
    if args.test or not args.loop:
        results = scanner.scan(verbose=not args.json)
        if args.json:
            print(scanner.get_opportunities_json())
    else:
        print("🚀 Starting continuous scan mode...")
        print(f"   Interval: {args.interval} seconds")
        print("   Press Ctrl+C to stop\n")
        
        try:
            while True:
                scanner.scan(verbose=True)
                print(f"⏳ Next scan in {args.interval} seconds...\n")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\n👋 Scanner stopped by user.")


if __name__ == "__main__":
    main()
