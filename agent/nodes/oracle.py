"""
oracle_check_node — Step 2 of the execution gate. The safety primitive.

Execution path:
  1. Fetch a signed receipt from Headless Oracle (live /v5/status or public /v5/demo)
  2. Verify the Ed25519 signature and TTL using the headless-oracle SDK
  3. Return oracle_valid=True only if BOTH checks pass
  4. Set market_status from the receipt (OPEN / CLOSED / HALTED / UNKNOWN)

An agent that skips this node or ignores oracle_valid=False is deliberately
choosing to trade blind. The graph enforces it — see agent/graph.py.

Environment variables:
  ORACLE_API_KEY    — X-Oracle-Key for /v5/status (live receipts, receipt_mode=live)
                      If unset, falls back to /v5/demo (public, receipt_mode=demo)
  ORACLE_PUBLIC_KEY — Hex Ed25519 public key. If set, skips the /v5/keys network call.
                      Recommended for production to eliminate one network round-trip.
"""

from __future__ import annotations

import os
from typing import Any

from headless_oracle import OracleClient, verify
from headless_oracle.verify import VerifyResult

from agent.state import AgentState

_ORACLE_API_KEY: str | None = os.getenv("ORACLE_API_KEY")
_ORACLE_PUBLIC_KEY: str | None = os.getenv("ORACLE_PUBLIC_KEY")


def oracle_check_node(state: AgentState) -> dict[str, Any]:
    """
    Fetch and cryptographically verify a Headless Oracle signed receipt.

    Always sets: oracle_receipt, oracle_valid, market_status, halt_reason.
    Never raises — any failure produces oracle_valid=False, market_status=UNKNOWN.
    """
    mic = state["mic"]

    # ── Step 1: Fetch receipt ─────────────────────────────────────────────────
    receipt: dict[str, Any] | None = None
    try:
        with OracleClient(api_key=_ORACLE_API_KEY) as client:
            if _ORACLE_API_KEY:
                receipt = client.get_status(mic)
            else:
                receipt = client.get_demo(mic)
    except Exception as exc:
        return {
            "oracle_receipt": None,
            "oracle_valid": False,
            "market_status": "UNKNOWN",
            "halt_reason": f"Oracle unreachable: {exc}",
        }

    # ── Step 2: Verify Ed25519 signature + TTL ───────────────────────────────
    result: VerifyResult = verify(receipt, public_key=_ORACLE_PUBLIC_KEY or None)

    if not result.valid:
        return {
            "oracle_receipt": receipt,
            "oracle_valid": False,
            "market_status": "UNKNOWN",
            "halt_reason": f"Receipt invalid ({result.reason}) — treating as CLOSED per fail-closed contract",
        }

    # ── Step 3: Extract status ───────────────────────────────────────────────
    status: str = receipt.get("status", "UNKNOWN")
    halt_reason: str | None = None if status == "OPEN" else f"Market is {status} — halting per fail-closed contract"

    return {
        "oracle_receipt": receipt,
        "oracle_valid": True,
        "market_status": status,
        "halt_reason": halt_reason,
    }
