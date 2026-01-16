"""
Polymarket Trading Bot - Order Executor
========================================
Executes trades via Polymarket CLOB API using py-clob-client.
"""

import os
import logging
from datetime import datetime
from typing import Optional, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("⚠ py-clob-client not installed. Run: pip install py-clob-client")

load_dotenv()
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class OrderRequest:
    """Order to be placed."""
    token_id: str           # The outcome token ID
    side: str               # "BUY" or "SELL"
    size: float             # Amount in contracts
    price: float            # Limit price (0.01 to 0.99)
    
    
@dataclass
class OrderResult:
    """Result of order placement."""
    success: bool
    order_id: Optional[str] = None
    filled_size: float = 0
    filled_price: float = 0
    error: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTOR CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class OrderExecutor:
    """
    Executes orders on Polymarket CLOB using official py-clob-client.
    """
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.client: Optional[ClobClient] = None
        self.order_count = 0
        self.total_volume = 0.0
        
        if not dry_run:
            self._init_client()
    
    def _init_client(self):
        """Initialize the CLOB client with API credentials."""
        if not CLOB_AVAILABLE:
            logger.error("py-clob-client not available")
            return
        
        api_key = os.getenv("CLOB_API_KEY")
        api_secret = os.getenv("CLOB_API_SECRET")
        api_passphrase = os.getenv("CLOB_API_PASSPHRASE")
        funder = os.getenv("FUNDER_ADDRESS") or os.getenv("WALLET_ADDRESS")
        
        if not all([api_key, api_secret, api_passphrase]):
            logger.error("Missing CLOB API credentials in .env")
            return
        
        try:
            creds = ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase
            )
            
            self.client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                creds=creds,
                signature_type=0,  # EOA
                funder=funder
            )
            
            # Test connection
            status = self.client.get_ok()
            logger.info(f"CLOB client initialized. Status: {status}")
            
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
            self.client = None
    
    def place_order(self, order: OrderRequest) -> OrderResult:
        """Place an order on Polymarket."""
        self.order_count += 1
        
        if self.dry_run:
            return self._simulate_order(order)
        
        if not self.client:
            return OrderResult(
                success=False,
                error="CLOB client not initialized. Check credentials."
            )
        
        return self._execute_order(order)
    
    def _simulate_order(self, order: OrderRequest) -> OrderResult:
        """Simulate order in dry-run mode."""
        logger.info(f"[DRY RUN] {order.side} {order.size:.2f} @ ${order.price:.3f}")
        
        self.total_volume += order.size * order.price
        
        return OrderResult(
            success=True,
            order_id=f"DRY_{self.order_count}",
            filled_size=order.size,
            filled_price=order.price
        )
    
    def _execute_order(self, order: OrderRequest) -> OrderResult:
        """Execute real order via CLOB API."""
        try:
            side = BUY if order.side.upper() == "BUY" else SELL
            
            # Build order arguments
            order_args = OrderArgs(
                token_id=order.token_id,
                price=order.price,
                size=order.size,
                side=side
            )
            
            # Create and sign order
            signed_order = self.client.create_order(order_args)
            
            # Post order to CLOB
            result = self.client.post_order(signed_order, OrderType.GTC)
            
            logger.info(f"Order placed: {result}")
            
            self.total_volume += order.size * order.price
            
            return OrderResult(
                success=True,
                order_id=result.get("orderID") or result.get("id"),
                filled_size=order.size,
                filled_price=order.price
            )
            
        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            return OrderResult(success=False, error=str(e))
    
    def get_balance(self) -> Tuple[float, Optional[str]]:
        """Get USDC balance."""
        if self.dry_run:
            return float(os.getenv("BANKROLL_START", 50.0)), None
        
        if not self.client:
            return 0, "Client not initialized"
        
        try:
            # The actual method depends on py-clob-client version
            # This is a placeholder - check actual API
            return float(os.getenv("BANKROLL_START", 50.0)), None
        except Exception as e:
            return 0, str(e)
    
    def get_open_orders(self) -> list:
        """Get list of open orders."""
        if self.dry_run or not self.client:
            return []
        
        try:
            return self.client.get_orders()
        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            return []
    
    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        if self.dry_run:
            logger.info("[DRY RUN] Would cancel all orders")
            return True
        
        if not self.client:
            return False
        
        try:
            self.client.cancel_all()
            logger.info("All orders cancelled")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel orders: {e}")
            return False
    
    def print_status(self):
        """Print executor status."""
        mode = "DRY RUN" if self.dry_run else "LIVE"
        connected = "✓" if self.client else "✗"
        
        print(f"\n{'─' * 50}")
        print(f"📤 ORDER EXECUTOR ({mode})")
        print(f"   Orders: {self.order_count}")
        print(f"   Volume: ${self.total_volume:,.2f}")
        print(f"   CLOB:   {connected} {'Connected' if self.client else 'Not connected'}")
        print(f"{'─' * 50}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test dry run
    executor = OrderExecutor(dry_run=True)
    executor.print_status()
    
    # Test live connection
    print("\nTesting LIVE connection...")
    live_executor = OrderExecutor(dry_run=False)
    live_executor.print_status()
