"""
Polymarket Real-time WebSocket Monitor
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Set
from dataclasses import dataclass

try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

from config import CLOB_WS_URL

@dataclass
class OrderBookUpdate:
    market_id: str
    timestamp: datetime
    bids: List[Dict]
    asks: List[Dict]
    
    @property
    def best_bid(self) -> float:
        return max((b["price"] for b in self.bids), default=0)
    
    @property
    def best_ask(self) -> float:
        return min((a["price"] for a in self.asks), default=1)
    
    @property
    def spread_percent(self) -> float:
        mid = (self.best_bid + self.best_ask) / 2
        return ((self.best_ask - self.best_bid) / mid * 100) if mid > 0 else 0


class RealtimeMonitor:
    def __init__(self):
        self.subscribed: Set[str] = set()
        self.price_cache: Dict[str, float] = {}
        self.updates: Dict[str, OrderBookUpdate] = {}
        self.running = False
        self.ws = None
    
    async def connect(self) -> bool:
        if not WS_AVAILABLE:
            print("❌ Install websockets: pip install websockets")
            return False
        try:
            self.ws = await websockets.connect(CLOB_WS_URL, ping_interval=30)
            print("✓ WebSocket connected")
            return True
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False
    
    async def subscribe(self, market_ids: List[str]):
        for mid in market_ids:
            if mid not in self.subscribed and self.ws:
                await self.ws.send(json.dumps({"type": "subscribe", "channel": "book", "market": mid}))
                self.subscribed.add(mid)
    
    async def listen(self, duration: int = 60):
        if not self.ws:
            return
        self.running = True
        start = datetime.utcnow()
        count = 0
        
        try:
            async for msg in self.ws:
                if not self.running or (datetime.utcnow() - start).seconds >= duration:
                    break
                data = json.loads(msg)
                if data.get("type") == "book":
                    count += 1
                    if count % 50 == 0:
                        print(f"  📊 {count} updates received")
        except Exception as e:
            print(f"  ⚠ Error: {e}")
        finally:
            self.running = False
            print(f"  Total: {count} updates")
    
    async def close(self):
        self.running = False
        if self.ws:
            await self.ws.close()


async def run_monitor(market_ids: List[str], duration: int = 60):
    monitor = RealtimeMonitor()
    if await monitor.connect():
        await monitor.subscribe(market_ids)
        await monitor.listen(duration)
    await monitor.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--markets", nargs="+", help="Market IDs")
    parser.add_argument("--duration", type=int, default=60)
    args = parser.parse_args()
    
    if not args.markets:
        print("Usage: python realtime_monitor.py --markets <id1> <id2>")
        return
    
    asyncio.run(run_monitor(args.markets, args.duration))


if __name__ == "__main__":
    main()
