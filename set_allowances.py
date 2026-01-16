#!/usr/bin/env python3
"""
Polymarket Token Allowance Setup
=================================
One-time script to approve USDC and conditional tokens for trading.

This is required before placing orders on Polymarket.
Only needs to be run ONCE per wallet.

Usage:
    python set_allowances.py
"""

import os
import sys
import getpass

try:
    from py_clob_client.client import ClobClient
except ImportError:
    print("❌ Missing py-clob-client. Install with:")
    print("   pip install py-clob-client")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet

WALLET_ADDRESS = "0xe2a134a9e9d3a812a71336e0b2a5078736ccd594"

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 70)
    print("  🔓 POLYMARKET TOKEN ALLOWANCE SETUP")
    print("═" * 70)
    print()
    print("  This approves USDC and conditional tokens for trading.")
    print("  Only needs to be run ONCE per wallet.")
    print()
    print("  ⚠️  This will submit transactions to Polygon (requires MATIC for gas)")
    print()
    print("  Wallet: " + WALLET_ADDRESS)
    print()
    print("═" * 70)
    print()
    
    confirm = input("Do you want to proceed? (yes/no): ")
    if confirm.lower() != "yes":
        print("Aborted.")
        sys.exit(0)
    
    print()
    private_key = getpass.getpass("🔑 Paste your private key (input hidden): ")
    
    if not private_key:
        print("❌ No private key provided. Aborting.")
        sys.exit(1)
    
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    
    print()
    print("🔄 Connecting to Polymarket...")
    
    try:
        client = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=private_key,
            signature_type=0
        )
        
        print("✓ Connected")
        print()
        print("🔄 Setting token allowances...")
        print("   (This submits transactions to Polygon)")
        print()
        
        # Set allowances
        result = client.set_allowances()
        
        print("═" * 70)
        print("  ✅ ALLOWANCES SET SUCCESSFULLY!")
        print("═" * 70)
        print()
        print("  You can now place orders on Polymarket.")
        print()
        print("  Verify on PolygonScan:")
        print(f"  https://polygonscan.com/address/{WALLET_ADDRESS}")
        print()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print("Common issues:")
        print("  - Insufficient MATIC for gas")
        print("  - Wrong private key")
        print("  - Network congestion")
        sys.exit(1)
    
    finally:
        private_key = "0" * 66
        del private_key


if __name__ == "__main__":
    main()
