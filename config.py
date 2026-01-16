"""
Polymarket Trading Bot - Configuration
=======================================
Central configuration for trading bot, CLOB API, and risk management.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
COINGECKO_API = "https://api.coingecko.com/api/v3"
SUBGRAPH_URL = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/prod/gn"

# ═══════════════════════════════════════════════════════════════════════════════
# CREDENTIALS (from .env)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Credentials:
    """API credentials loaded from environment."""
    private_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", ""))
    api_key: str = field(default_factory=lambda: os.getenv("CLOB_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("CLOB_API_SECRET", ""))
    api_passphrase: str = field(default_factory=lambda: os.getenv("CLOB_API_PASSPHRASE", ""))
    wallet_address: str = field(default_factory=lambda: os.getenv("WALLET_ADDRESS", ""))
    
    def is_valid(self) -> bool:
        return bool(self.private_key and self.wallet_address)


# ═══════════════════════════════════════════════════════════════════════════════
# TRADING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradingConfig:
    """Configuration for the momentum trading bot."""
    
    # Bankroll Management
    bankroll_start: float = float(os.getenv("BANKROLL_START", "50.0"))
    bet_size_percent: float = float(os.getenv("BET_SIZE_PCT", "0.05"))  # 5% per trade
    min_bankroll: float = float(os.getenv("MIN_BANKROLL", "10.0"))       # Stop if below
    max_position_usd: float = float(os.getenv("MAX_POSITION_USD", "100.0"))
    
    # Edge Detection
    edge_threshold: float = float(os.getenv("EDGE_THRESHOLD", "0.10"))  # 10% minimum edge
    min_probability: float = 0.20   # Don't bet if prob < 20% or > 80%
    max_probability: float = 0.80
    
    # Target Markets
    target_coins: List[str] = field(default_factory=lambda: [
        "bitcoin", "ethereum", "solana", "ripple"
    ])
    coin_symbols: dict = field(default_factory=lambda: {
        "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "ripple": "XRP"
    })
    
    # Market Filters
    min_liquidity_usd: float = 5000.0
    market_duration_minutes: int = 15  # Target 15-minute markets
    
    # Timing
    scan_interval_seconds: int = 30
    price_lookback_seconds: int = 60   # 1-min momentum
    
    # Modes
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"


# ═══════════════════════════════════════════════════════════════════════════════
# WHALE TRACKING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WhaleConfig:
    """Configuration for whale wallet tracking."""
    
    min_pnl_to_track: float = 10000
    alert_on_position_usd: float = 5000
    position_refresh_seconds: int = 60
    
    # Known whale wallets
    known_whales: List[str] = field(default_factory=lambda: [
        # ~$2.6M+ profit in 30 days, 63% win rate
        "0x9d84ce0306f8551e02efef1680475fc0f1dc1344",
        # ~$958k profit in 30 days, 67% win rate
        "0xd218e474776403a330142299f7796e8ba32eb5c9",
        # +$1.48M+ overall profit
        "0x006cc834Cc092684F1B56626E23BEdB3835c16ea",
        # +$434k+ profit
        "0xe74A4446EfD66A4de690962938F550D8921E40Ee",
        # $691k → $1.42M+, high-volume bot
        "0x492442EaB586F242B53bDa933fD5dE859c8A3782",
        # 0x8dxd - $313 → $558k+, 98% win rate, PRIMARY TARGET
        "0x63ce342161250d705dc0b16df89036c8e5f9ba9a",
    ])
    
    # Primary whale to copy (0x8dxd)
    primary_whale: str = "0x63ce342161250d705dc0b16df89036c8e5f9ba9a"


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNER CONFIGURATION (unchanged from before)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScannerConfig:
    arb_threshold: float = 0.99
    min_arb_percent: float = 0.5
    min_liquidity_usd: float = 5000
    min_open_interest: float = 1000
    sleep_between_calls: float = 2.0
    max_markets_per_scan: int = 500
    scan_interval_seconds: int = 300


# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NotificationConfig:
    enable_console: bool = True
    console_verbosity: str = "INFO"
    discord_webhook_url: Optional[str] = os.getenv("DISCORD_WEBHOOK_URL")
    telegram_bot_token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")
    min_seconds_between_alerts: int = 30


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL CONFIG INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

class Config:
    """Global configuration container."""
    
    credentials = Credentials()
    trading = TradingConfig()
    whale = WhaleConfig()
    scanner = ScannerConfig()
    notification = NotificationConfig()
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "PolymarketTradingBot/2.0"
    }
    
    @classmethod
    def validate(cls) -> bool:
        """Check if required credentials are present."""
        if not cls.credentials.is_valid():
            print("⚠ Missing credentials. Set POLYMARKET_PRIVATE_KEY and WALLET_ADDRESS in .env")
            return False
        return True


# HTTP settings
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_DELAY = 5
CONSOLE_WIDTH = 100
