#!/usr/bin/env python3
"""
Polymarket API Credentials Generator
=====================================
This script generates L2 API credentials from your private key.

SECURITY NOTES:
- Your private key is used ONLY to sign a message and derive credentials
- After running, copy the output to your .env file
- DELETE this script after use (or at least clear your terminal history)
- The generated API credentials are what the bot uses for trading

Usage:
    python generate_creds.py
"""

import os
import sys
import getpass

# Check for required packages
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
except ImportError:
    print("❌ Missing py-clob-client. Install with:")
    print("   pip install py-clob-client")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Polymarket CLOB endpoints
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet

# Your wallet address (from setup)
WALLET_ADDRESS = "0xe2a134a9e9d3a812a71336e0b2a5078736ccd594"

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 70)
    print("  🔐 POLYMARKET API CREDENTIALS GENERATOR")
    print("═" * 70)
    print()
    print("  This will generate L2 API credentials for trading.")
    print("  Your private key is used ONLY to sign a message.")
    print()
    print("  Wallet: " + WALLET_ADDRESS)
    print()
    print("═" * 70)
    print()
    
    # Prompt for private key (hidden input)
    print("⚠️  ACTION REQUIRED:")
    print("   Export your private key from MetaMask:")
    print("   → MetaMask → ⋮ → Account Details → Show Private Key")
    print()
    
    private_key = getpass.getpass("🔑 Paste your private key (input hidden): ")
    
    # Validate format
    if not private_key:
        print("❌ No private key provided. Aborting.")
        sys.exit(1)
    
    # Add 0x prefix if missing
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    
    if len(private_key) != 66:
        print("❌ Invalid private key length. Should be 64 hex chars (or 66 with 0x prefix).")
        sys.exit(1)
    
    print()
    print("🔄 Connecting to Polymarket CLOB...")
    
    try:
        # Initialize client with private key
        client = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=private_key,
            signature_type=0  # EOA (MetaMask)
        )
        
        print("✓ Connected to CLOB")
        print()
        print("🔄 Generating API credentials...")
        print("   (This signs an EIP-712 message - no gas required)")
        print()
        
        # Generate or derive API credentials
        creds = client.create_or_derive_api_creds()
        
        print("═" * 70)
        print("  ✅ SUCCESS! Your API Credentials:")
        print("═" * 70)
        print()
        print(f"  CLOB_API_KEY={creds.api_key}")
        print(f"  CLOB_API_SECRET={creds.api_secret}")
        print(f"  CLOB_API_PASSPHRASE={creds.api_passphrase}")
        print()
        print("═" * 70)
        print()
        print("📋 NEXT STEPS:")
        print()
        print("  1. Copy the 3 lines above into your .env file")
        print("  2. Delete your private key from clipboard/history")
        print("  3. You can now run the bot with these L2 credentials")
        print("     (No more private key needed!)")
        print()
        print("═" * 70)
        
    except Exception as e:
        print(f"❌ Error generating credentials: {e}")
        print()
        print("Common issues:")
        print("  - Wrong private key")
        print("  - Network connectivity")
        print("  - Polymarket API unavailable")
        sys.exit(1)
    
    finally:
        # Clear the private key from memory
        private_key = "0" * 66
        del private_key


if __name__ == "__main__":
    main()
