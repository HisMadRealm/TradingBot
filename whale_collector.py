"""
Polymarket Trading Bot - Whale Data Collector
===============================================
Fetches trade data from Polymarket APIs for whale wallet analysis.

Updated: Jan 2026 - Switched to Data API /trades which returns all recent trades.
New approach: Fetch recent trades, identify large-volume wallets as "whales".
"""

import requests
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import json

from config import Config, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WhaleTrade:
    """A single trade by a whale wallet."""
    wallet: str
    market_id: str
    market_question: str
    outcome: str          # "YES" or "NO" or "Up" or "Down"
    side: str             # "BUY" or "SELL"
    size: float           # In contracts
    price: float          # 0-1
    usd_value: float
    timestamp: datetime
    
    @property
    def direction(self) -> float:
        """Net directional signal: positive = bullish, negative = bearish."""
        # BUY YES = bullish (+1), SELL YES = bearish (-1)
        # BUY NO = bearish (-1), SELL NO = bullish (+1)
        outcome_upper = self.outcome.upper()
        base = 1.0 if self.side == "BUY" else -1.0
        if outcome_upper in ["NO", "DOWN"]:
            base *= -1
        return base * self.size


@dataclass
class WhalePosition:
    """Current position held by a whale."""
    wallet: str
    market_id: str
    market_question: str
    outcome: str
    size: float
    avg_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    last_updated: datetime


@dataclass
class MarketSignal:
    """Aggregated signal for a specific market."""
    market_id: str
    market_question: str
    direction: float        # -1 to +1 (bearish to bullish)
    confidence: float       # 0 to 1
    whale_count: int        # Number of whales in this market
    total_volume: float     # Total USD traded
    mean_price: float       # Average entry price
    variance: float         # Signal variance
    timestamp: datetime


# ═══════════════════════════════════════════════════════════════════════════════
# WHALE DATA COLLECTOR
# ═══════════════════════════════════════════════════════════════════════════════

class WhaleDataCollector:
    """
    Collects and aggregates trade data for whale analysis.
    
    New approach (Jan 2026):
    - Fetch all recent trades from Data API
    - Filter for crypto markets
    - Identify whale wallets by trade volume
    """
    
    def __init__(self, whale_addresses: List[str] = None):
        # Keep for backwards compat, but now used as high-priority wallets
        self.whale_addresses = whale_addresses or Config.whale.known_whales
        self.trades_cache: Dict[str, List[WhaleTrade]] = {}
        self.positions_cache: Dict[str, List[WhalePosition]] = {}
        self.last_fetch: Optional[datetime] = None
        
        # Whale weights (for priority ordering)
        self.whale_weights = {
            "0x63ce342161250d705dc0b16df89036c8e5f9ba9a": 1.5,  # 0x8dxd
            "0x9d84ce0306f8551e02efef1680475fc0f1dc1344": 1.2,
            "0xd218e474776403a330142299f7796e8ba32eb5c9": 1.0,
            "0x006cc834cc092684f1b56626e23bedb3835c16ea": 1.0,
            "0xe74a4446efd66a4de690962938f550d8921e40ee": 0.8,
            "0x492442eab586f242b53bda933fd5de859c8a3782": 0.8,
        }
    
    # ─────────────────────────────────────────────────────────────────────────
    # DATA API - Primary Source
    # ─────────────────────────────────────────────────────────────────────────
    
    def fetch_recent_trades(self, limit: int = 500) -> List[WhaleTrade]:
        """
        Fetch recent trades from Data API.
        Returns trades across all markets with wallet info.
        """
        url = f"{DATA_API_BASE}/trades"
        params = {"limit": limit}
        
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            
            trades = []
            for item in data:
                try:
                    # Parse Unix timestamp
                    ts = item.get("timestamp", 0)
                    if isinstance(ts, (int, float)):
                        timestamp = datetime.fromtimestamp(ts)
                    else:
                        timestamp = datetime.utcnow()
                    
                    side = item.get("side", "BUY").upper()
                    outcome = item.get("outcome", "YES")
                    size = float(item.get("size", 0) or 0)
                    price = float(item.get("price", 0) or 0)
                    wallet = item.get("proxyWallet", "").lower()
                    
                    trade = WhaleTrade(
                        wallet=wallet,
                        market_id=item.get("conditionId", item.get("asset", "")),
                        market_question=item.get("title", "Unknown"),
                        outcome=outcome,
                        side=side,
                        size=size,
                        price=price,
                        usd_value=size * price,
                        timestamp=timestamp
                    )
                    trades.append(trade)
                except Exception as e:
                    logger.debug(f"Error parsing trade: {e}")
                    continue
            
            logger.info(f"[DataAPI] Fetched {len(trades)} recent trades")
            return trades
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"[DataAPI] Failed: {e}")
            return []
    
    # ─────────────────────────────────────────────────────────────────────────
    # CRYPTO MARKET FILTERING
    # ─────────────────────────────────────────────────────────────────────────
    
    def filter_crypto_trades(self, trades: List[WhaleTrade]) -> List[WhaleTrade]:
        """Filter for crypto market trades (BTC/ETH/SOL/XRP)."""
        crypto_keywords = ['btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana', 'xrp', 'ripple']
        crypto_trades = []
        
        for trade in trades:
            question_lower = trade.market_question.lower()
            if any(kw in question_lower for kw in crypto_keywords):
                crypto_trades.append(trade)
        
        logger.info(f"[Filter] {len(crypto_trades)} crypto trades of {len(trades)} total")
        return crypto_trades
    
    def identify_whale_wallets(
        self, 
        trades: List[WhaleTrade], 
        min_volume_usd: float = 100.0
    ) -> Dict[str, List[WhaleTrade]]:
        """
        Identify wallets with significant trading volume.
        Groups trades by wallet, filters for big players.
        """
        wallet_trades: Dict[str, List[WhaleTrade]] = {}
        wallet_volume: Dict[str, float] = {}
        
        for trade in trades:
            wallet = trade.wallet
            if wallet not in wallet_trades:
                wallet_trades[wallet] = []
                wallet_volume[wallet] = 0
            wallet_trades[wallet].append(trade)
            wallet_volume[wallet] += trade.usd_value
        
        # Filter to significant wallets
        whale_wallets = {
            w: wallet_trades[w] 
            for w, vol in wallet_volume.items() 
            if vol >= min_volume_usd
        }
        
        logger.info(f"[Whales] Identified {len(whale_wallets)} whale wallets")
        return whale_wallets
    
    # ─────────────────────────────────────────────────────────────────────────
    # MAIN COLLECTION METHOD
    # ─────────────────────────────────────────────────────────────────────────
    
    def collect_all_whale_data(self, lookback_hours: int = 24) -> Dict[str, Any]:
        """
        Collect recent crypto market trades and identify whale activity.
        """
        logger.info("Collecting crypto market trades...")
        
        # Fetch all recent trades
        all_trades = self.fetch_recent_trades(limit=500)
        
        if not all_trades:
            logger.warning("No trades fetched from API")
            return {
                "trades": [], 
                "positions": [], 
                "whale_count": 0, 
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Filter for crypto markets
        crypto_trades = self.filter_crypto_trades(all_trades)
        
        if not crypto_trades:
            logger.warning("No crypto trades found")
            return {
                "trades": [], 
                "positions": [], 
                "whale_count": 0, 
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Identify whale wallets
        whale_groups = self.identify_whale_wallets(crypto_trades, min_volume_usd=50.0)
        
        # Cache by wallet
        self.trades_cache = whale_groups
        self.last_fetch = datetime.utcnow()
        
        all_whale_trades = []
        for wallet_trades in whale_groups.values():
            all_whale_trades.extend(wallet_trades)
        
        logger.info(f"Total: {len(all_whale_trades)} trades from {len(whale_groups)} wallets")
        
        return {
            "trades": all_whale_trades,
            "positions": [],
            "whale_count": len(whale_groups),
            "timestamp": self.last_fetch.isoformat()
        }
    
    # ─────────────────────────────────────────────────────────────────────────
    # ACCESSOR METHODS
    # ─────────────────────────────────────────────────────────────────────────
    
    def fetch_whale_trades(
        self, 
        wallet: str, 
        lookback_hours: int = 24,
        limit: int = 100
    ) -> List[WhaleTrade]:
        """Get trades for a specific wallet."""
        if wallet.lower() in self.trades_cache:
            return self.trades_cache[wallet.lower()]
        
        if not self.trades_cache:
            self.collect_all_whale_data(lookback_hours=lookback_hours)
        
        return self.trades_cache.get(wallet.lower(), [])
    
    def get_market_activity(self, market_id: str = None) -> List[WhaleTrade]:
        """Get all trades for a specific market or all markets."""
        trades = []
        for wallet_trades in self.trades_cache.values():
            for t in wallet_trades:
                if market_id is None or t.market_id == market_id:
                    trades.append(t)
        return trades
    
    def get_active_markets(self) -> Dict[str, List[WhaleTrade]]:
        """Group all trades by market."""
        markets: Dict[str, List[WhaleTrade]] = {}
        
        for wallet_trades in self.trades_cache.values():
            for trade in wallet_trades:
                if trade.market_id not in markets:
                    markets[trade.market_id] = []
                markets[trade.market_id].append(trade)
        
        return markets
    
    # ─────────────────────────────────────────────────────────────────────────
    # DEPRECATED - For backwards compatibility
    # ─────────────────────────────────────────────────────────────────────────
    
    def fetch_whale_positions_gamma(self, wallet: str) -> List[WhalePosition]:
        """Deprecated - returns empty list."""
        return []
    
    def fetch_whale_positions_subgraph(self, wallet: str) -> List[WhalePosition]:
        """Deprecated - returns empty list."""
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    collector = WhaleDataCollector()
    
    print(f"\n{'═' * 60}")
    print(f"🐳 WHALE DATA COLLECTOR TEST")
    print(f"{'═' * 60}\n")
    
    # Collect all data
    result = collector.collect_all_whale_data(lookback_hours=24)
    
    print(f"Trades: {len(result['trades'])}")
    print(f"Whale wallets: {result['whale_count']}")
    
    if result['trades']:
        print("\nSample trades:")
        for t in result['trades'][:5]:
            print(f"  {t.side} {t.outcome} | ${t.usd_value:.2f} @ {t.price:.3f}")
            print(f"    Market: {t.market_question[:50]}...")
    
    # Get active markets
    markets = collector.get_active_markets()
    print(f"\nActive markets: {len(markets)}")
    
    for market_id, trades in list(markets.items())[:3]:
        print(f"\n  Market: {trades[0].market_question[:40]}...")
        print(f"  Trades: {len(trades)} | Total: ${sum(t.usd_value for t in trades):.2f}")
