"""
AgentState — the single shared state dict passed through every LangGraph node.

Every node returns a partial dict; LangGraph merges it into the running state.
All fields have safe defaults so nodes can read them without KeyError.
"""

from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class AgentState(TypedDict):
    # ── Input ────────────────────────────────────────────────────────────────
    mic: str            # Exchange MIC code (e.g. "XNYS")
    trade_intent: str   # Human-readable description of what to trade

    # ── Reasoning node output ────────────────────────────────────────────────
    reasoning: str      # LLM analysis (empty string if LLM not configured)

    # ── Oracle node output ───────────────────────────────────────────────────
    oracle_receipt: dict[str, Any] | None  # Raw signed receipt (or None on fetch failure)
    oracle_valid: bool                     # True only if Ed25519 sig verified and TTL ok
    market_status: str                     # OPEN / CLOSED / HALTED / UNKNOWN / NOT_CHECKED
    halt_reason: str | None               # Human-readable reason for halt (None if OPEN)

    # ── Terminal output ──────────────────────────────────────────────────────
    action: str    # "EXECUTE" or "HALT"
    result: str    # Final message describing what happened
