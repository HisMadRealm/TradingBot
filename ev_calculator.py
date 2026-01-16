"""
Polymarket Trading Bot - EV Calculator
=======================================
Expected Value calculations for trade decisions.

Replaces the old brittle "edge >= 10%" rule with proper EV-net calculations.

EV_net = (p_cal * payout_if_win - (1 - p_cal) * cost_if_lose) - fees - slippage

Trade only if:
1. EV_net > 0
2. EV_net / bankroll > min_ev_frac

Created: Jan 2026
"""

from dataclasses import dataclass
from typing import Tuple, Optional, List
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradeOpportunity:
    """Evaluated trade opportunity with EV calculations."""
    market_id: str
    market_question: str
    coin_symbol: str
    direction: str              # "UP" or "DOWN"
    
    # Probabilities
    p_model: float              # Our predicted probability (calibrated)
    p_market: float             # Market implied probability (YES price)
    
    # Prices
    yes_price: float
    no_price: float
    
    # Side: which token to buy
    side: str                   # "BUY_YES" or "BUY_NO"
    entry_price: float          # Price we'd pay
    
    # EV calculations
    payout_if_win: float        # Profit per contract if we win
    cost_if_lose: float         # Loss per contract if we lose
    ev_gross: float             # Raw EV before costs
    fees_est: float             # Estimated fees
    slippage_est: float         # Estimated slippage  
    ev_net: float               # Net EV after costs
    
    # Sizing
    kelly_fraction: float       # Kelly optimal fraction
    suggested_size_usd: float   # Suggested trade size in USD
    
    # Decision
    passes_ev_check: bool       # EV_net > 0 and EV_net / bankroll > threshold
    rejection_reasons: List[str]

    @property
    def edge(self) -> float:
        """Edge as a simple percentage."""
        return abs(self.p_model - self.p_market)
    
    @property
    def ev_per_dollar(self) -> float:
        """EV per dollar risked (return rate)."""
        if self.entry_price <= 0:
            return 0
        return self.ev_net / self.entry_price


# ═══════════════════════════════════════════════════════════════════════════════
# EV CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

class EVCalculator:
    """
    Calculates Expected Value for trade opportunities.
    
    For binary markets:
    - YES token pays $1 if outcome is YES, $0 otherwise
    - NO token pays $1 if outcome is NO, $0 otherwise
    - Entry price = cost to buy one token
    - Profit if win = $1 - entry_price
    - Loss if lose = entry_price (you lose your stake)
    """
    
    def __init__(
        self,
        base_fee_pct: float = 0.02,        # 2% base fee estimate
        base_slippage_pct: float = 0.01,   # 1% base slippage
        min_ev_frac: float = 0.001,        # 0.1% of bankroll minimum
        max_kelly_fraction: float = 0.25,   # Never bet more than 25% Kelly
        max_position_pct: float = 0.05,     # 5% max position size
    ):
        self.base_fee_pct = base_fee_pct
        self.base_slippage_pct = base_slippage_pct
        self.min_ev_frac = min_ev_frac
        self.max_kelly_fraction = max_kelly_fraction
        self.max_position_pct = max_position_pct
    
    def estimate_fees(self, size_usd: float, spread: float = 0) -> float:
        """Estimate trading fees."""
        # Base platform fee + spread impact
        return size_usd * (self.base_fee_pct + spread / 2)
    
    def estimate_slippage(self, size_usd: float, liquidity: float) -> float:
        """
        Estimate slippage based on order size vs liquidity.
        Larger orders relative to liquidity = more slippage.
        """
        if liquidity <= 0:
            return size_usd * 0.10  # 10% slippage if no liquidity data
        
        # Impact model: slippage increases with order size / liquidity
        impact_ratio = size_usd / liquidity
        slippage_pct = self.base_slippage_pct + (impact_ratio * 0.5)
        slippage_pct = min(slippage_pct, 0.15)  # Cap at 15%
        
        return size_usd * slippage_pct
    
    def calculate_kelly(
        self, 
        probability: float, 
        win_payout: float, 
        loss_cost: float
    ) -> float:
        """
        Calculate Kelly Criterion optimal bet fraction.
        
        f* = (p * b - q) / b
        where:
            p = probability of winning
            q = probability of losing = 1 - p
            b = odds received on win (win_payout / loss_cost)
        """
        if loss_cost <= 0 or win_payout <= 0:
            return 0
        
        p = probability
        q = 1 - p
        odds = win_payout / loss_cost
        
        kelly = (p * odds - q) / odds
        
        # Clamp to reasonable range
        kelly = max(0, min(kelly, self.max_kelly_fraction))
        
        return kelly
    
    def evaluate_opportunity(
        self,
        market_id: str,
        market_question: str,
        coin_symbol: str,
        direction: str,
        p_model: float,        # Our predicted probability
        yes_price: float,      # Market YES price
        no_price: float,       # Market NO price
        bankroll: float,       # Current bankroll
        liquidity: float = 10000,  # Market liquidity
        spread: float = 0.02,      # Bid-ask spread
    ) -> TradeOpportunity:
        """
        Evaluate a market opportunity and calculate EV.
        
        Returns a TradeOpportunity with full EV breakdown.
        """
        rejection_reasons = []
        
        # Market implied probability is the YES price
        p_market = yes_price
        
        # Determine which side to take
        # If our model says p > market, buy YES
        # If our model says p < market, buy NO (bet on DOWN)
        if p_model > p_market:
            side = "BUY_YES"
            entry_price = yes_price
            # If YES wins: we get $1, profit = 1 - entry_price
            # If NO wins: we lose our stake
            payout_if_win = 1.0 - entry_price
            cost_if_lose = entry_price
            win_prob = p_model
        else:
            side = "BUY_NO"
            entry_price = no_price
            # If NO wins: we get $1, profit = 1 - entry_price
            # If YES wins: we lose our stake
            payout_if_win = 1.0 - entry_price
            cost_if_lose = entry_price
            win_prob = 1.0 - p_model
        
        # Calculate EV
        # EV_gross = P(win) * payout - P(lose) * cost
        ev_gross = win_prob * payout_if_win - (1 - win_prob) * cost_if_lose
        
        # Calculate Kelly fraction for sizing
        kelly = self.calculate_kelly(win_prob, payout_if_win, cost_if_lose)
        
        # Suggested size (fractional Kelly)
        suggested_size = bankroll * kelly * 0.5  # Half-Kelly for safety
        suggested_size = min(suggested_size, bankroll * self.max_position_pct)
        suggested_size = max(suggested_size, 0)
        
        # Estimate costs
        fees = self.estimate_fees(suggested_size, spread)
        slippage = self.estimate_slippage(suggested_size, liquidity)
        
        # Net EV
        ev_net = ev_gross * suggested_size - fees - slippage
        
        # Decision checks
        passes_ev_check = True
        
        if ev_net <= 0:
            passes_ev_check = False
            rejection_reasons.append("EV_NET_NEGATIVE")
        
        ev_frac = ev_net / bankroll if bankroll > 0 else 0
        if ev_frac < self.min_ev_frac and ev_net > 0:
            passes_ev_check = False
            rejection_reasons.append("EV_FRAC_TOO_LOW")
        
        if entry_price > 0.95 or entry_price < 0.05:
            rejection_reasons.append("EXTREME_PRICE")
        
        if suggested_size < 1.0:
            passes_ev_check = False
            rejection_reasons.append("SIZE_TOO_SMALL")
        
        if liquidity < 100:
            rejection_reasons.append("LOW_LIQUIDITY")
        
        return TradeOpportunity(
            market_id=market_id,
            market_question=market_question,
            coin_symbol=coin_symbol,
            direction=direction,
            p_model=p_model,
            p_market=p_market,
            yes_price=yes_price,
            no_price=no_price,
            side=side,
            entry_price=entry_price,
            payout_if_win=payout_if_win,
            cost_if_lose=cost_if_lose,
            ev_gross=ev_gross,
            fees_est=fees,
            slippage_est=slippage,
            ev_net=ev_net,
            kelly_fraction=kelly,
            suggested_size_usd=suggested_size,
            passes_ev_check=passes_ev_check and len(rejection_reasons) == 0,
            rejection_reasons=rejection_reasons
        )
    
    def print_opportunity(self, opp: TradeOpportunity):
        """Print formatted opportunity details."""
        status = "✅ TRADE" if opp.passes_ev_check else "❌ REJECT"
        
        print(f"\n{'─' * 60}")
        print(f"📊 {opp.coin_symbol} {opp.direction} | {status}")
        print(f"{'─' * 60}")
        print(f"   Question: {opp.market_question[:50]}...")
        print(f"   Side: {opp.side} @ ${opp.entry_price:.3f}")
        print(f"")
        print(f"   Model Prob:  {opp.p_model:.1%}")
        print(f"   Market Prob: {opp.p_market:.1%}")
        print(f"   Edge:        {opp.edge:.1%}")
        print(f"")
        print(f"   Win Payout:  ${opp.payout_if_win:.3f}")
        print(f"   Loss Cost:   ${opp.cost_if_lose:.3f}")
        print(f"   EV Gross:    ${opp.ev_gross:.4f} per contract")
        print(f"   Fees Est:    ${opp.fees_est:.2f}")
        print(f"   Slippage:    ${opp.slippage_est:.2f}")
        print(f"   EV Net:      ${opp.ev_net:.2f}")
        print(f"")
        print(f"   Kelly Frac:  {opp.kelly_fraction:.2%}")
        print(f"   Size:        ${opp.suggested_size_usd:.2f}")
        
        if opp.rejection_reasons:
            print(f"")
            print(f"   Rejections:  {', '.join(opp.rejection_reasons)}")
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    calc = EVCalculator()
    
    print(f"\n{'═' * 60}")
    print("📈 EV CALCULATOR TEST")
    print(f"{'═' * 60}")
    
    # Test case 1: Good opportunity
    opp1 = calc.evaluate_opportunity(
        market_id="test1",
        market_question="BTC Up or Down - January 15, 7:30PM ET",
        coin_symbol="BTC",
        direction="UP",
        p_model=0.70,      # We think 70% chance of UP
        yes_price=0.55,    # Market says 55%
        no_price=0.45,
        bankroll=1000,
        liquidity=5000,
        spread=0.02
    )
    calc.print_opportunity(opp1)
    
    # Test case 2: Marginal opportunity
    opp2 = calc.evaluate_opportunity(
        market_id="test2",
        market_question="ETH Up or Down - January 15, 8PM ET",
        coin_symbol="ETH",
        direction="UP",
        p_model=0.52,      # We think 52% chance
        yes_price=0.50,    # Market says 50% - only 2% edge
        no_price=0.50,
        bankroll=1000,
        liquidity=3000,
        spread=0.03
    )
    calc.print_opportunity(opp2)
    
    # Test case 3: Bad opportunity (negative EV)
    opp3 = calc.evaluate_opportunity(
        market_id="test3",
        market_question="SOL Up or Down - January 15, 8:15PM ET",
        coin_symbol="SOL",
        direction="DOWN",
        p_model=0.45,      # We think only 45% down
        yes_price=0.60,    # Market says 60% up
        no_price=0.40,
        bankroll=1000,
        liquidity=2000,
        spread=0.05
    )
    calc.print_opportunity(opp3)
