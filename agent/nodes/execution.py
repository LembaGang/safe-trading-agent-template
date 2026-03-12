"""
execution_node  — Step 3 (happy path). Replace the stub with your brokerage/DEX integration.
failsafe_node   — Step 3 (halt path). Logs the halt reason and takes no market action.

The graph routes here based on oracle_valid and market_status — see agent/graph.py.
"""

from __future__ import annotations

import json

from agent.state import AgentState


def execution_node(state: AgentState) -> dict:
    """
    Execute the trade. Reached only when oracle_valid=True AND market_status=OPEN.

    ── REPLACE THIS STUB WITH YOUR INTEGRATION ──────────────────────────────
    Options:
      • Alpaca / Interactive Brokers / TD Ameritrade for equities
      • Uniswap / 0x / Cowswap for DeFi
      • QuantConnect / Backtrader for backtesting
    ──────────────────────────────────────────────────────────────────────────

    The receipt in state["oracle_receipt"] is cryptographically signed and can be
    forwarded to downstream agents or logged as an attestation of market state at
    the moment of execution.
    """
    receipt = state.get("oracle_receipt") or {}
    issued_at = receipt.get("issued_at", "unknown")
    expires_at = receipt.get("expires_at", "unknown")

    # Log the oracle attestation alongside the trade for audit trail.
    attestation = {
        "oracle_attested_at": issued_at,
        "oracle_valid_until": expires_at,
        "oracle_status": state["market_status"],
        "oracle_receipt_id": receipt.get("receipt_id"),
    }

    print(f"[EXECUTE] Oracle attestation: {json.dumps(attestation)}")
    print(f"[EXECUTE] Reasoning: {state['reasoning']}")
    print(f"[EXECUTE] Trade intent: {state['trade_intent']} on {state['mic']}")

    # ── Your brokerage call goes here ────────────────────────────────────────
    # order = broker.submit_order(
    #     symbol="AAPL",
    #     qty=100,
    #     side="buy",
    #     type="market",
    #     time_in_force="day",
    # )
    # ─────────────────────────────────────────────────────────────────────────

    return {
        "action": "EXECUTE",
        "result": (
            f"Trade '{state['trade_intent']}' submitted on {state['mic']}. "
            f"Oracle attested OPEN at {issued_at} (valid until {expires_at})."
        ),
    }


def failsafe_node(state: AgentState) -> dict:
    """
    Halt all trading. Reached when:
      • oracle_valid=False (invalid signature, expired receipt, fetch failure)
      • market_status != OPEN (CLOSED / HALTED / UNKNOWN)

    Consumers of Oracle receipts MUST treat UNKNOWN as CLOSED.
    This node enforces that contract — no special-casing UNKNOWN to allow execution.
    """
    reason = state.get("halt_reason") or f"Market is {state['market_status']}"

    print(f"[HALT] {reason}")
    print(f"[HALT] No trade executed. Trade intent '{state['trade_intent']}' discarded.")

    return {
        "action": "HALT",
        "result": f"HALTED: {reason}. Trade intent discarded.",
    }
