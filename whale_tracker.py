"""
Polymarket Whale Tracker - Wallet Monitoring
=============================================
Tracks whale wallets and their positions via Polymarket subgraph.
"""

import requests
import time
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from config import (
    SUBGRAPH_URL,
    GAMMA_API_BASE,
    Config,
    REQUEST_TIMEOUT
)

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WalletPosition:
    """A position held by a wallet."""
    market_id: str
    market_question: str
    outcome: str
    size: float
    avg_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    
    @property
    def pnl_percent(self) -> float:
        if self.avg_price == 0:
            return 0
        return ((self.current_price - self.avg_price) / self.avg_price) * 100


@dataclass
class WhaleWallet:
    """Represents a whale wallet we're tracking."""
    address: str
    alias: Optional[str] = None
    total_realized_pnl: float = 0
    total_unrealized_pnl: float = 0
    positions: List[WalletPosition] = field(default_factory=list)
    last_updated: Optional[datetime] = None
    
    @property
    def total_pnl(self) -> float:
        return self.total_realized_pnl + self.total_unrealized_pnl


@dataclass
class WhaleActivity:
    """A significant activity by a whale wallet."""
    wallet_address: str
    activity_type: str  # "BUY", "SELL", "NEW_POSITION", "CLOSE_POSITION"
    market_question: str
    outcome: str
    size_usd: float
    price: float
    timestamp: datetime
    
    def __str__(self) -> str:
        return (
            f"🐳 {self.activity_type} | {self.wallet_address[:10]}... | "
            f"${self.size_usd:,.0f} | {self.outcome} @ ${self.price:.3f} | "
            f"{self.market_question[:40]}..."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SUBGRAPH QUERIES
# ═══════════════════════════════════════════════════════════════════════════════

def query_subgraph(query: str, variables: Dict = None) -> Optional[Dict]:
    """Execute a GraphQL query against the Polymarket subgraph."""
    try:
        response = requests.post(
            SUBGRAPH_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            print(f"  ⚠ Subgraph query error: {data['errors']}")
            return None
        
        return data.get("data")
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Subgraph request failed: {e}")
        return None


def fetch_top_traders(limit: int = 50) -> List[Dict]:
    """
    Fetch top traders by realized PnL from the subgraph.
    
    Note: The actual query structure depends on the subgraph schema.
    This is a template that may need adjustment based on the live schema.
    """
    query = """
    query TopTraders($limit: Int!) {
        userPositions(
            first: $limit
            orderBy: realizedPnl
            orderDirection: desc
            where: { realizedPnl_gt: "0" }
        ) {
            id
            user
            realizedPnl
            market {
                id
                question
            }
        }
    }
    """
    
    result = query_subgraph(query, {"limit": limit})
    
    if result and "userPositions" in result:
        return result["userPositions"]
    
    return []


def fetch_wallet_positions(wallet_address: str) -> List[Dict]:
    """
    Fetch all positions for a specific wallet address.
    """
    query = """
    query WalletPositions($wallet: String!) {
        userPositions(
            where: { user: $wallet }
            orderBy: value
            orderDirection: desc
        ) {
            id
            market {
                id
                question
                slug
            }
            outcome
            size
            averagePrice
            realizedPnl
            value
        }
    }
    """
    
    result = query_subgraph(query, {"wallet": wallet_address.lower()})
    
    if result and "userPositions" in result:
        return result["userPositions"]
    
    return []


def fetch_recent_trades(wallet_address: str, limit: int = 20) -> List[Dict]:
    """
    Fetch recent trades for a wallet.
    """
    query = """
    query RecentTrades($wallet: String!, $limit: Int!) {
        trades(
            where: { maker: $wallet }
            first: $limit
            orderBy: timestamp
            orderDirection: desc
        ) {
            id
            market {
                id
                question
            }
            outcome
            side
            price
            size
            timestamp
        }
    }
    """
    
    result = query_subgraph(query, {"wallet": wallet_address.lower(), "limit": limit})
    
    if result and "trades" in result:
        return result["trades"]
    
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# ALTERNATIVE: LEADERBOARD SCRAPING (Backup method)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_leaderboard_from_api() -> List[Dict]:
    """
    Attempt to fetch leaderboard data from Polymarket's public endpoints.
    
    Note: This endpoint may not be officially documented and could change.
    """
    try:
        # Try the gamma API leaderboard endpoint
        url = f"{GAMMA_API_BASE}/leaderboard"
        response = requests.get(url, headers=Config.headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            return response.json()
        
        # If that fails, the leaderboard might require authentication
        print("  ⚠ Leaderboard endpoint not available publicly")
        return []
        
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Failed to fetch leaderboard: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# WHALE TRACKER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class WhaleTracker:
    """Main tracker for monitoring whale wallets."""
    
    def __init__(self):
        self.tracked_wallets: Dict[str, WhaleWallet] = {}
        self.recent_activities: List[WhaleActivity] = []
        self.last_refresh: Optional[datetime] = None
        
        # Initialize with known whales from config
        for address in Config.whale.known_whales:
            self.add_wallet(address)
    
    def add_wallet(self, address: str, alias: Optional[str] = None):
        """Add a wallet to track."""
        address_lower = address.lower()
        if address_lower not in self.tracked_wallets:
            self.tracked_wallets[address_lower] = WhaleWallet(
                address=address_lower,
                alias=alias
            )
            print(f"  ✓ Now tracking wallet: {alias or address[:16]}...")
    
    def remove_wallet(self, address: str):
        """Stop tracking a wallet."""
        address_lower = address.lower()
        if address_lower in self.tracked_wallets:
            del self.tracked_wallets[address_lower]
            print(f"  ✓ Stopped tracking wallet: {address[:16]}...")
    
    def discover_top_wallets(self, min_pnl: float = None, limit: int = 20) -> List[str]:
        """
        Discover top performing wallets from the subgraph.
        
        Returns list of wallet addresses.
        """
        print("\n🔍 Discovering top performing wallets...")
        
        min_pnl = min_pnl or Config.whale.min_pnl_to_track
        
        # Try subgraph first
        top_traders = fetch_top_traders(limit=limit * 2)
        
        discovered = []
        seen_users = set()
        
        for position in top_traders:
            user = position.get("user", "")
            pnl = float(position.get("realizedPnl", 0))
            
            if user and user not in seen_users and pnl >= min_pnl:
                seen_users.add(user)
                discovered.append(user)
                
                if len(discovered) >= limit:
                    break
        
        print(f"  Found {len(discovered)} wallets with PnL >= ${min_pnl:,.0f}")
        
        return discovered
    
    def refresh_wallet_positions(self, wallet_address: str) -> Optional[WhaleWallet]:
        """Refresh position data for a specific wallet."""
        address_lower = wallet_address.lower()
        
        if address_lower not in self.tracked_wallets:
            self.add_wallet(address_lower)
        
        wallet = self.tracked_wallets[address_lower]
        
        # Fetch positions from subgraph
        position_data = fetch_wallet_positions(address_lower)
        
        if not position_data:
            print(f"  ⚠ No positions found for {address_lower[:16]}...")
            return wallet
        
        wallet.positions = []
        total_realized = 0
        total_unrealized = 0
        
        for pos in position_data:
            try:
                realized = float(pos.get("realizedPnl", 0))
                size = float(pos.get("size", 0))
                avg_price = float(pos.get("averagePrice", 0))
                value = float(pos.get("value", 0))
                
                # Calculate unrealized PnL (simplified)
                current_value = value
                cost_basis = size * avg_price
                unrealized = current_value - cost_basis
                
                total_realized += realized
                total_unrealized += unrealized
                
                market = pos.get("market", {})
                
                wallet.positions.append(WalletPosition(
                    market_id=market.get("id", ""),
                    market_question=market.get("question", "Unknown"),
                    outcome=pos.get("outcome", "Unknown"),
                    size=size,
                    avg_price=avg_price,
                    current_price=value / size if size > 0 else 0,
                    unrealized_pnl=unrealized,
                    realized_pnl=realized
                ))
            except (ValueError, TypeError) as e:
                continue
        
        wallet.total_realized_pnl = total_realized
        wallet.total_unrealized_pnl = total_unrealized
        wallet.last_updated = datetime.utcnow()
        
        return wallet
    
    def refresh_all(self, verbose: bool = True) -> Dict[str, Any]:
        """Refresh data for all tracked wallets."""
        start_time = datetime.utcnow()
        
        if verbose:
            print(f"\n{'═' * 70}")
            print(f"🐳 WHALE WALLET TRACKER")
            print(f"   Tracking {len(self.tracked_wallets)} wallets")
            print(f"   Started: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"{'═' * 70}\n")
        
        results = []
        
        for address in list(self.tracked_wallets.keys()):
            if verbose:
                wallet = self.tracked_wallets[address]
                name = wallet.alias or f"{address[:10]}..."
                print(f"  📊 Refreshing {name}...")
            
            wallet = self.refresh_wallet_positions(address)
            
            if wallet:
                results.append({
                    "address": wallet.address,
                    "alias": wallet.alias,
                    "realized_pnl": wallet.total_realized_pnl,
                    "unrealized_pnl": wallet.total_unrealized_pnl,
                    "total_pnl": wallet.total_pnl,
                    "position_count": len(wallet.positions)
                })
            
            time.sleep(1)  # Rate limiting
        
        self.last_refresh = datetime.utcnow()
        duration = (self.last_refresh - start_time).total_seconds()
        
        if verbose:
            self._print_summary(results, duration)
        
        return {
            "wallets_refreshed": len(results),
            "duration_seconds": duration,
            "wallets": results,
            "timestamp": start_time.isoformat()
        }
    
    def _print_summary(self, results: List[Dict], duration: float):
        """Print tracking summary."""
        print(f"\n{'─' * 70}")
        print(f"📊 REFRESH COMPLETE ({duration:.1f}s)")
        print(f"{'─' * 70}")
        
        if not results:
            print("   No wallet data available. Add wallets or run discovery.")
            return
        
        # Sort by total PnL
        sorted_results = sorted(results, key=lambda x: x["total_pnl"], reverse=True)
        
        print(f"\n{'Address':<20} {'Alias':<15} {'Realized':<15} {'Unrealized':<15} {'Total PnL':<15}")
        print("─" * 80)
        
        for w in sorted_results:
            addr = w["address"][:18] + ".."
            alias = (w["alias"] or "-")[:13]
            realized = f"${w['realized_pnl']:,.0f}"
            unrealized = f"${w['unrealized_pnl']:,.0f}"
            total = f"${w['total_pnl']:,.0f}"
            
            print(f"{addr:<20} {alias:<15} {realized:<15} {unrealized:<15} {total:<15}")
        
        print(f"\n{'═' * 70}\n")
    
    def get_top_positions(self, limit: int = 10) -> List[Dict]:
        """Get the highest conviction positions across all tracked whales."""
        all_positions = []
        
        for wallet in self.tracked_wallets.values():
            for pos in wallet.positions:
                all_positions.append({
                    "wallet": wallet.alias or wallet.address[:16],
                    "market": pos.market_question,
                    "outcome": pos.outcome,
                    "size": pos.size,
                    "avg_price": pos.avg_price,
                    "unrealized_pnl": pos.unrealized_pnl
                })
        
        # Sort by position size (USD value)
        all_positions.sort(key=lambda x: abs(x["size"]), reverse=True)
        
        return all_positions[:limit]
    
    def export_json(self) -> str:
        """Export all tracking data as JSON."""
        return json.dumps({
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
            "wallets": [
                {
                    "address": w.address,
                    "alias": w.alias,
                    "realized_pnl": w.total_realized_pnl,
                    "unrealized_pnl": w.total_unrealized_pnl,
                    "total_pnl": w.total_pnl,
                    "positions": [
                        {
                            "market": p.market_question[:60],
                            "outcome": p.outcome,
                            "size": p.size,
                            "avg_price": p.avg_price,
                            "unrealized_pnl": p.unrealized_pnl
                        }
                        for p in w.positions
                    ]
                }
                for w in self.tracked_wallets.values()
            ]
        }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Command-line interface for whale tracker."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Polymarket Whale Tracker")
    parser.add_argument("--discover", action="store_true", help="Discover top wallets")
    parser.add_argument("--track", type=str, help="Add wallet address to track")
    parser.add_argument("--refresh", action="store_true", help="Refresh all tracked wallets")
    parser.add_argument("--top-positions", action="store_true", help="Show top whale positions")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--min-pnl", type=float, default=10000, help="Min PnL for discovery")
    
    args = parser.parse_args()
    
    tracker = WhaleTracker()
    
    if args.discover:
        discovered = tracker.discover_top_wallets(min_pnl=args.min_pnl)
        print(f"\nDiscovered {len(discovered)} whale wallets:")
        for i, addr in enumerate(discovered, 1):
            print(f"  {i}. {addr}")
        
        # Auto-add discovered wallets
        for addr in discovered[:10]:  # Track top 10
            tracker.add_wallet(addr)
    
    if args.track:
        tracker.add_wallet(args.track)
    
    if args.refresh or (not args.discover and not args.track and not args.top_positions):
        results = tracker.refresh_all(verbose=not args.json)
        if args.json:
            print(tracker.export_json())
    
    if args.top_positions:
        positions = tracker.get_top_positions()
        print("\n🏆 TOP WHALE POSITIONS:")
        for i, pos in enumerate(positions, 1):
            print(f"\n  {i}. {pos['market'][:50]}...")
            print(f"     Wallet: {pos['wallet']}")
            print(f"     {pos['outcome']} | Size: ${pos['size']:,.0f} | Avg: ${pos['avg_price']:.3f}")


if __name__ == "__main__":
    main()
