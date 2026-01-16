"""
Polymarket Trading Bot - Price Feed
====================================
Real-time crypto price fetching from CoinGecko for momentum signals.
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from collections import deque
import logging

from config import COINGECKO_API, Config, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PricePoint:
    """A single price observation."""
    coin_id: str
    price: float
    timestamp: datetime
    
    @property
    def age_seconds(self) -> float:
        return (datetime.utcnow() - self.timestamp).total_seconds()


@dataclass
class MomentumSignal:
    """Momentum calculation result."""
    coin_id: str
    symbol: str
    current_price: float
    price_1m_ago: float
    change_percent: float
    direction: str  # "UP" or "DOWN"
    confidence: float  # 0.0 to 1.0
    timestamp: datetime
    
    @property
    def predicted_probability(self) -> float:
        """Convert momentum to probability prediction."""
        # Simple linear scaling: 1% move = 5% probability shift from 50%
        base_prob = 0.50
        shift = self.change_percent * 5  # 1% price change = 5% prob shift
        
        if self.direction == "UP":
            prob = base_prob + (shift / 100)
        else:
            prob = base_prob - (shift / 100)
        
        # Clamp to valid range
        return max(0.05, min(0.95, prob))


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE FEED
# ═══════════════════════════════════════════════════════════════════════════════

class PriceFeed:
    """
    Fetches real-time crypto prices from CoinGecko.
    Maintains rolling price history for momentum calculations.
    """
    
    def __init__(self, coins: List[str] = None, history_seconds: int = 120):
        self.coins = coins or Config.trading.target_coins
        self.history_seconds = history_seconds
        
        # Rolling price history per coin: {coin_id: deque of PricePoints}
        self.price_history: Dict[str, deque] = {
            coin: deque(maxlen=history_seconds) for coin in self.coins
        }
        
        self.last_fetch: Optional[datetime] = None
        self.fetch_count = 0
        self.error_count = 0
    
    def fetch_prices(self) -> Dict[str, float]:
        """
        Fetch current prices for all target coins.
        
        Returns:
            Dict mapping coin_id to current USD price
        """
        coin_ids = ",".join(self.coins)
        url = f"{COINGECKO_API}/simple/price"
        params = {
            "ids": coin_ids,
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }
        
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            
            prices = {}
            now = datetime.utcnow()
            
            for coin_id in self.coins:
                if coin_id in data:
                    price = data[coin_id].get("usd", 0)
                    prices[coin_id] = price
                    
                    # Add to history
                    self.price_history[coin_id].append(
                        PricePoint(coin_id=coin_id, price=price, timestamp=now)
                    )
            
            self.last_fetch = now
            self.fetch_count += 1
            
            logger.debug(f"Fetched prices: {prices}")
            return prices
            
        except requests.exceptions.RequestException as e:
            self.error_count += 1
            logger.warning(f"Price fetch error: {e}")
            return {}
    
    def get_price_at(self, coin_id: str, seconds_ago: int) -> Optional[float]:
        """Get historical price from cache."""
        if coin_id not in self.price_history:
            return None
        
        history = self.price_history[coin_id]
        if not history:
            return None
        
        target_time = datetime.utcnow() - timedelta(seconds=seconds_ago)
        
        # Find closest price point
        closest = None
        min_diff = float('inf')
        
        for point in history:
            diff = abs((point.timestamp - target_time).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest = point
        
        # Only return if within 10 seconds of target
        if closest and min_diff <= 10:
            return closest.price
        
        return None
    
    def calculate_momentum(self, coin_id: str, lookback_seconds: int = 60) -> Optional[MomentumSignal]:
        """
        Calculate momentum signal for a coin.
        
        Args:
            coin_id: CoinGecko coin ID
            lookback_seconds: How far back to compare (default 60s)
        
        Returns:
            MomentumSignal with direction and confidence
        """
        if coin_id not in self.price_history:
            return None
        
        history = self.price_history[coin_id]
        if len(history) < 2:
            return None
        
        # Current price
        current = history[-1]
        
        # Price from lookback_seconds ago
        past_price = self.get_price_at(coin_id, lookback_seconds)
        
        if not past_price or past_price == 0:
            return None
        
        # Calculate change
        change_percent = ((current.price - past_price) / past_price) * 100
        direction = "UP" if change_percent >= 0 else "DOWN"
        
        # Confidence based on magnitude of move
        confidence = min(1.0, abs(change_percent) / 2.0)  # 2% move = full confidence
        
        symbol = Config.trading.coin_symbols.get(coin_id, coin_id.upper())
        
        return MomentumSignal(
            coin_id=coin_id,
            symbol=symbol,
            current_price=current.price,
            price_1m_ago=past_price,
            change_percent=change_percent,
            direction=direction,
            confidence=confidence,
            timestamp=current.timestamp
        )
    
    def get_all_signals(self) -> List[MomentumSignal]:
        """Calculate momentum signals for all tracked coins."""
        signals = []
        
        for coin_id in self.coins:
            signal = self.calculate_momentum(coin_id)
            if signal:
                signals.append(signal)
        
        return signals
    
    def print_status(self):
        """Print current price status."""
        print(f"\n{'─' * 60}")
        print(f"📈 PRICE FEED STATUS")
        print(f"   Last fetch: {self.last_fetch.strftime('%H:%M:%S') if self.last_fetch else 'Never'}")
        print(f"   Fetches: {self.fetch_count} | Errors: {self.error_count}")
        print(f"{'─' * 60}")
        
        for coin_id in self.coins:
            history = self.price_history.get(coin_id, [])
            if history:
                current = history[-1]
                signal = self.calculate_momentum(coin_id)
                
                symbol = Config.trading.coin_symbols.get(coin_id, coin_id)
                
                if signal:
                    arrow = "↑" if signal.direction == "UP" else "↓"
                    print(f"   {symbol}: ${current.price:,.2f} {arrow} {signal.change_percent:+.2f}%")
                else:
                    print(f"   {symbol}: ${current.price:,.2f}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time
    
    print("🔄 Starting price feed test...")
    feed = PriceFeed()
    
    for i in range(10):
        prices = feed.fetch_prices()
        feed.print_status()
        
        signals = feed.get_all_signals()
        if signals:
            print("\n   Momentum Signals:")
            for s in signals:
                print(f"   → {s.symbol}: {s.direction} | Predicted prob: {s.predicted_probability:.1%}")
        
        time.sleep(10)
