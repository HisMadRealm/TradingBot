"""
Polymarket Trading Bot - Market Finder
=======================================
Finds and filters 15-minute crypto binary markets.

Updated: Jan 2026 - Added ability to find markets from active trades data.
"""

import requests
import re
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging

from config import GAMMA_API_BASE, Config, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CryptoMarket:
    """A 15-minute crypto binary market."""
    market_id: str
    question: str
    slug: str
    coin_id: str           # e.g., "bitcoin"
    coin_symbol: str       # e.g., "BTC"
    direction: str         # "UP" or "DOWN"
    yes_price: float
    no_price: float
    volume_24h: float
    liquidity: float
    end_time: Optional[datetime]
    url: str
    
    @property
    def minutes_remaining(self) -> float:
        if not self.end_time:
            return 0
        return (self.end_time - datetime.utcnow()).total_seconds() / 60
    
    @property
    def implied_probability(self) -> float:
        """Market's implied probability of YES outcome."""
        return self.yes_price
    
    @property
    def spread(self) -> float:
        """Bid-ask spread estimation."""
        return max(0, 1 - (self.yes_price + self.no_price))
    
    def edge_vs_prediction(self, predicted_prob: float) -> Tuple[float, str]:
        """
        Calculate edge and recommended action.
        
        Returns:
            (edge_percent, action) where action is "BUY_YES", "BUY_NO", or "SKIP"
        """
        if predicted_prob > self.yes_price:
            edge = predicted_prob - self.yes_price
            return (edge, "BUY_YES")
        else:
            edge = self.yes_price - predicted_prob
            return (edge, "BUY_NO")


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET FINDER
# ═══════════════════════════════════════════════════════════════════════════════

class MarketFinder:
    """
    Finds 15-minute crypto binary markets on Polymarket.
    Parses market questions to extract coin and direction.
    
    Updated regex patterns to match current Polymarket market format.
    """
    
    # Crypto coin detection patterns - flexible matching
    CRYPTO_PATTERNS = {
        "bitcoin": [
            r"\bBTC\b",
            r"\bBitcoin\b",
            r"\bbitcoin\b",
            r"\bBitcoin\s+price\b",
        ],
        "ethereum": [
            r"\bETH\b",
            r"\bEthereum\b",
            r"\bethereum\b",
            r"\bEther\b",
        ],
        "solana": [
            r"\bSOL\b",
            r"\bSolana\b",
            r"\bsolana\b",
        ],
        "ripple": [
            r"\bXRP\b",
            r"\bRipple\b",
            r"\bripple\b",
        ],
        "dogecoin": [
            r"\bDOGE\b",
            r"\bDogecoin\b",
        ],
    }
    
    # Time window patterns - multiple formats used by Polymarket
    TIME_PATTERNS = [
        # "12:00 to 12:15 PM" or "12:00 → 12:15"
        re.compile(r"(\d{1,2}:\d{2})\s*(?:to|→|-|–)\s*(\d{1,2}:\d{2})", re.IGNORECASE),
        # "15-minute" or "15 minute" or "15min" or "15-min"
        re.compile(r"15[-\s]?min(?:ute)?", re.IGNORECASE),
        # "next 15 min" or "in 15 min"
        re.compile(r"(?:next|in)\s*15\s*min", re.IGNORECASE),
        # "short-term" crypto markets often resolve quickly
        re.compile(r"(?:hourly|short[-\s]?term)", re.IGNORECASE),
        # Time range like "12:00 PM UTC"
        re.compile(r"\d{1,2}:\d{2}\s*(?:AM|PM)?\s*(?:UTC|EST|PST)?", re.IGNORECASE),
    ]
    
    # Category tags that indicate crypto price markets
    CRYPTO_CATEGORIES = [
        "crypto",
        "cryptocurrency", 
        "bitcoin",
        "ethereum",
        "price",
        "trading",
    ]
    
    DIRECTION_UP = re.compile(
        r"\b(up|higher|above|rise|increase|exceed|go\s+up|rally|hit)\b", 
        re.IGNORECASE
    )
    DIRECTION_DOWN = re.compile(
        r"\b(down|lower|below|fall|decrease|drop|go\s+down|decline|stay\s+below)\b", 
        re.IGNORECASE
    )
    
    def __init__(self):
        self.last_scan: Optional[datetime] = None
        self.markets_found: List[CryptoMarket] = []
        self.all_markets_cache: List[Dict] = []  # Raw market data cache
    
    def fetch_markets(self, limit: int = 200) -> List[Dict]:
        """Fetch active markets from Gamma API."""
        url = f"{GAMMA_API_BASE}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "order": "volume",
            "ascending": "false"
        }
        
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(
                    url, headers=Config.headers, params=params, timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                markets = response.json()
                self.all_markets_cache = markets
                return markets
            except requests.exceptions.RequestException as e:
                logger.warning(f"Market fetch error (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        
        return []
    
    def _detect_coin(self, question: str, tags: List[str] = None) -> Optional[Tuple[str, str]]:
        """
        Detect which cryptocurrency the market is about.
        
        Returns:
            (coin_id, symbol) or None if not detected
        """
        text = question.lower()
        tags_text = " ".join(tags or []).lower()
        
        for coin_id, patterns in self.CRYPTO_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, question, re.IGNORECASE):
                    symbol = Config.trading.coin_symbols.get(coin_id, coin_id.upper())
                    return (coin_id, symbol)
        
        # Check tags as fallback
        for coin_id in self.CRYPTO_PATTERNS.keys():
            if coin_id in tags_text:
                symbol = Config.trading.coin_symbols.get(coin_id, coin_id.upper())
                return (coin_id, symbol)
        
        return None
    
    def _detect_direction(self, question: str) -> Optional[str]:
        """Detect if market asks about price going UP or DOWN."""
        if self.DIRECTION_UP.search(question):
            return "UP"
        elif self.DIRECTION_DOWN.search(question):
            return "DOWN"
        return None
    
    def _is_time_based_market(self, question: str, market_data: Dict) -> bool:
        """
        Check if this is a short-term/time-based market.
        More flexible matching than before.
        """
        # Check question text with multiple patterns
        for pattern in self.TIME_PATTERNS:
            if pattern.search(question):
                return True
        
        # Check market category/tags
        tags = market_data.get("tags", []) or []
        if isinstance(tags, str):
            tags = [tags]
        tags_lower = [t.lower() for t in tags if t]
        
        for cat in self.CRYPTO_CATEGORIES:
            if cat in tags_lower:
                return True
        
        # Check market group/category field
        group = market_data.get("group", "").lower()
        category = market_data.get("category", "").lower()
        
        if any(c in group or c in category for c in ["crypto", "price", "minute"]):
            return True
        
        # Check if end time is within next few hours (indicating short-term market)
        end_date_str = market_data.get("endDate")
        if end_date_str:
            try:
                end_time = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                hours_until_end = (end_time - datetime.utcnow()).total_seconds() / 3600
                if 0 < hours_until_end < 4:  # Ends within 4 hours
                    return True
            except:
                pass
        
        return False
    
    def parse_market(self, market: Dict) -> Optional[CryptoMarket]:
        """
        Parse a market to see if it's a crypto binary market.
        
        Returns:
            CryptoMarket if valid, None otherwise
        """
        question = market.get("question", "")
        
        # Detect cryptocurrency
        coin_result = self._detect_coin(question, market.get("tags"))
        if not coin_result:
            return None
        
        coin_id, coin_symbol = coin_result
        
        # Check if it's a time-based/short-term market
        if not self._is_time_based_market(question, market):
            # Still include if it's a crypto market with good volume
            volume_24h = float(market.get("volume24hrs", 0) or 0)
            if volume_24h < Config.trading.min_liquidity_usd * 2:
                return None
        
        # Detect direction
        direction = self._detect_direction(question)
        if not direction:
            # Default to UP if question asks about hitting a price target
            if re.search(r"hit|reach|exceed", question, re.IGNORECASE):
                direction = "UP"
            else:
                return None
        
        # Extract prices
        tokens = market.get("tokens", [])
        if len(tokens) != 2:
            return None
        
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
        
        # Check liquidity
        volume_24h = float(market.get("volume24hrs", 0) or 0)
        liquidity = float(market.get("liquidityNum", market.get("liquidity", 0)) or 0)
        
        if volume_24h < Config.trading.min_liquidity_usd:
            return None
        
        # Parse end time if available
        end_time = None
        end_date_str = market.get("endDate")
        if end_date_str:
            try:
                end_time = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            except:
                pass
        
        return CryptoMarket(
            market_id=market.get("id", ""),
            question=question,
            slug=market.get("slug", ""),
            coin_id=coin_id,
            coin_symbol=coin_symbol,
            direction=direction,
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=volume_24h,
            liquidity=liquidity,
            end_time=end_time,
            url=f"https://polymarket.com/event/{market.get('slug', '')}"
        )
    
    def find_crypto_markets(self, min_minutes_left: float = 2.0) -> List[CryptoMarket]:
        """
        Find all active crypto markets.
        
        Args:
            min_minutes_left: Skip markets ending soon
        
        Returns:
            List of valid CryptoMarket objects
        """
        logger.info("Scanning for crypto markets...")
        
        raw_markets = self.fetch_markets(limit=200)
        
        if not raw_markets:
            logger.warning("No markets fetched")
            return []
        
        found = []
        rejected_reasons = {"no_coin": 0, "no_direction": 0, "low_liquidity": 0, "ending_soon": 0}
        
        for market in raw_markets:
            parsed = self.parse_market(market)
            
            if parsed:
                # Skip if ending too soon
                if parsed.end_time and parsed.minutes_remaining < min_minutes_left:
                    rejected_reasons["ending_soon"] += 1
                    continue
                
                found.append(parsed)
        
        self.markets_found = found
        self.last_scan = datetime.utcnow()
        
        logger.info(f"Found {len(found)} crypto markets (from {len(raw_markets)} total)")
        if found:
            coins = set(m.coin_symbol for m in found)
            logger.info(f"Coins: {', '.join(coins)}")
        
        return found
    
    def find_markets_for_coin(self, coin_id: str) -> List[CryptoMarket]:
        """Get markets for a specific coin."""
        return [m for m in self.markets_found if m.coin_id == coin_id]
    
    def get_market_by_id(self, market_id: str) -> Optional[CryptoMarket]:
        """Get a specific market by ID."""
        for m in self.markets_found:
            if m.market_id == market_id:
                return m
        return None
    
    # ─────────────────────────────────────────────────────────────────────────
    # TRADE-BASED MARKET DISCOVERY (New Method - Jan 2026)
    # ─────────────────────────────────────────────────────────────────────────
    
    def find_markets_from_trades(self) -> List[CryptoMarket]:
        """
        Find crypto markets by looking at where trades are happening.
        More reliable than querying the markets endpoint.
        """
        logger.info("Scanning for crypto markets from trade data...")
        
        url = f"{DATA_API_BASE}/trades"
        params = {"limit": 500}
        
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            trades = response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch trades: {e}")
            return []
        
        # Group trades by market (conditionId)
        market_trades: Dict[str, List[Dict]] = {}
        for trade in trades:
            title = trade.get("title", "")
            # Filter for crypto markets
            if not any(kw in title.lower() for kw in ['btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana', 'xrp']):
                continue
            
            condition_id = trade.get("conditionId", "")
            if condition_id not in market_trades:
                market_trades[condition_id] = []
            market_trades[condition_id].append(trade)
        
        logger.info(f"Found {len(market_trades)} active crypto markets from trades")
        
        # Build CryptoMarket objects
        markets = []
        for condition_id, trades_list in market_trades.items():
            # Get info from first trade
            sample = trades_list[0]
            question = sample.get("title", "Unknown")
            slug = sample.get("slug", "")
            
            # Detect coin and direction
            coin_result = self._detect_coin(question, [])
            if not coin_result:
                continue
            coin_id, coin_symbol = coin_result
            
            direction = self._detect_direction(question)
            if not direction:
                # Look for Up/Down in question
                if "up" in question.lower():
                    direction = "UP"
                elif "down" in question.lower():
                    direction = "DOWN"
                else:
                    continue
            
            # Estimate prices from recent trades
            up_prices = [float(t.get("price", 0)) for t in trades_list 
                         if t.get("outcome", "").lower() in ["up", "yes"]]
            down_prices = [float(t.get("price", 0)) for t in trades_list 
                           if t.get("outcome", "").lower() in ["down", "no"]]
            
            yes_price = sum(up_prices) / len(up_prices) if up_prices else 0.5
            no_price = sum(down_prices) / len(down_prices) if down_prices else 0.5
            
            # Calculate volume
            volume = sum(float(t.get("size", 0)) * float(t.get("price", 0)) for t in trades_list)
            
            market = CryptoMarket(
                market_id=condition_id,
                question=question,
                slug=slug,
                coin_id=coin_id,
                coin_symbol=coin_symbol,
                direction=direction,
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=volume,
                liquidity=volume * 5,  # Rough estimate
                end_time=None,  # Would need separate lookup
                url=f"https://polymarket.com/event/{slug}"
            )
            markets.append(market)
        
        # Sort by volume
        markets.sort(key=lambda m: m.volume_24h, reverse=True)
        self.markets_found = markets
        self.last_scan = datetime.now(timezone.utc)
        
        logger.info(f"Found {len(markets)} crypto markets")
        return markets
    
    def print_markets(self):
        """Print found markets."""
        print(f"\n{'═' * 70}")
        print(f"📊 CRYPTO MARKETS")
        print(f"   Found: {len(self.markets_found)}")
        print(f"   Scanned: {self.last_scan.strftime('%H:%M:%S') if self.last_scan else 'Never'}")
        print(f"{'═' * 70}\n")
        
        if not self.markets_found:
            print("   No crypto markets found.\n")
            print("   Debug info:")
            print(f"   - Total markets fetched: {len(self.all_markets_cache)}")
            if self.all_markets_cache:
                sample = self.all_markets_cache[:3]
                for m in sample:
                    print(f"   - Sample: {m.get('question', 'N/A')[:50]}...")
            return
        
        for m in self.markets_found[:10]:
            print(f"   {m.coin_symbol} {m.direction}")
            print(f"      YES: ${m.yes_price:.3f} | NO: ${m.no_price:.3f}")
            print(f"      Volume: ${m.volume_24h:,.0f} | Liquidity: ${m.liquidity:,.0f}")
            if m.end_time:
                print(f"      Ends in: {m.minutes_remaining:.1f} min")
            print()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    finder = MarketFinder()
    
    # Try trade-based discovery first (more reliable)
    print("\n🔍 Finding markets from trade data...")
    markets = finder.find_markets_from_trades()
    
    if markets:
        finder.print_markets()
    else:
        # Fallback to Gamma API
        print("\n🔍 Falling back to Gamma API...")
        markets = finder.find_crypto_markets()
        finder.print_markets()

