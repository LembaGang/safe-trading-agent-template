"""
async_oracle.py — Enterprise async batch oracle verification.

The bottleneck for multi-position agents running serial oracle checks:
  50 positions × ~200ms HTTP round-trip = ~10 seconds of pure I/O wait.

This module eliminates that with concurrent async execution:
  50 positions × asyncio.gather = ~200ms total (bounded by the slowest receipt).

Two fetch strategies — same fail-closed contract for both:
  No API key  → N concurrent calls to /v5/demo via asyncio.to_thread
  API key set → N concurrent calls to /v5/status via asyncio.to_thread
               (Power users: swap to a single client.get_batch() call for 1 HTTP round-trip)

Fail-closed guarantee:
  Any exception, invalid signature, expired TTL, or non-OPEN status produces
  valid=False for the affected MIC. ALL MICs must be valid + OPEN for
  BatchResult.can_execute() to return True. UNKNOWN is never permissive.

Usage:
    import asyncio
    from agent.nodes.async_oracle import batch_oracle_check, portfolio_can_execute

    result = asyncio.run(batch_oracle_check(["XNYS", "XNAS", "XLON"]))

    if portfolio_can_execute(result):
        broker.submit_portfolio_orders(...)
    else:
        print(f"Halted MICs: {result.halted_mics()}")

Environment variables:
  ORACLE_API_KEY    — Enables /v5/status (live, authenticated). Falls back to /v5/demo if unset.
  ORACLE_PUBLIC_KEY — Hex Ed25519 public key. Pins the key to avoid one /v5/keys fetch per call.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from headless_oracle import OracleClient, verify
from headless_oracle.verify import VerifyResult

_ORACLE_API_KEY: str | None = os.getenv("ORACLE_API_KEY")
_ORACLE_PUBLIC_KEY: str | None = os.getenv("ORACLE_PUBLIC_KEY")


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class MICResult:
    """Oracle verification result for a single MIC."""

    mic: str
    valid: bool           # True only if sig verified + TTL ok
    market_status: str    # OPEN / CLOSED / HALTED / UNKNOWN
    receipt: dict[str, Any] | None = None
    halt_reason: str | None = None

    @property
    def executable(self) -> bool:
        """True only when this MIC is safe to trade on."""
        return self.valid and self.market_status == "OPEN"


@dataclass
class BatchResult:
    """Aggregate oracle results for a multi-MIC batch check."""

    results: dict[str, MICResult] = field(default_factory=dict)

    def can_execute(self) -> bool:
        """
        Portfolio-level execution gate.

        Returns True only when EVERY requested MIC is valid and OPEN.
        An empty batch (no MICs) returns True vacuously — the caller
        has no positions to gate, so no trade is blocked.
        """
        return all(r.executable for r in self.results.values())

    def halted_mics(self) -> list[str]:
        """Return MIC codes where trading is blocked (non-OPEN or invalid receipt)."""
        return [mic for mic, r in self.results.items() if not r.executable]

    def open_mics(self) -> list[str]:
        """Return MIC codes where trading is cleared."""
        return [mic for mic, r in self.results.items() if r.executable]


# ── Core sync unit (I/O + verify for one MIC) ─────────────────────────────────

def _fetch_and_verify_one(mic: str) -> MICResult:
    """
    Fetch and verify a signed oracle receipt for a single MIC.

    This is the synchronous unit that async_oracle wraps with asyncio.to_thread.
    Keeping it sync preserves compatibility with the OracleClient (sync httpx).

    Never raises. All failure modes return valid=False with a descriptive halt_reason.
    """
    # Step 1: Fetch receipt
    try:
        with OracleClient(api_key=_ORACLE_API_KEY) as client:
            receipt: dict[str, Any] = (
                client.get_status(mic) if _ORACLE_API_KEY
                else client.get_demo(mic)
            )
    except Exception as exc:
        return MICResult(
            mic=mic,
            valid=False,
            market_status="UNKNOWN",
            receipt=None,
            halt_reason=f"Oracle unreachable: {exc}",
        )

    # Step 2: Verify Ed25519 signature + TTL
    result: VerifyResult = verify(receipt, public_key=_ORACLE_PUBLIC_KEY or None)
    if not result.valid:
        return MICResult(
            mic=mic,
            valid=False,
            market_status="UNKNOWN",
            receipt=receipt,
            halt_reason=f"Receipt invalid ({result.reason}) — fail-closed",
        )

    # Step 3: Extract status
    status: str = receipt.get("status", "UNKNOWN")
    return MICResult(
        mic=mic,
        valid=True,
        market_status=status,
        receipt=receipt,
        halt_reason=None if status == "OPEN" else f"Market is {status}",
    )


# ── Async orchestrator ────────────────────────────────────────────────────────

async def batch_oracle_check(mics: list[str]) -> BatchResult:
    """
    Fetch and verify oracle receipts for N MICs concurrently.

    Each MIC check runs in a thread (via asyncio.to_thread) so the sync
    OracleClient HTTP calls don't block the event loop. All N checks run
    concurrently — total latency is bounded by the single slowest receipt.

    Args:
        mics: MIC codes to check (e.g. ["XNYS", "XNAS", "XLON"]).
              Duplicate MICs are deduplicated before fetching.

    Returns:
        BatchResult. Call .can_execute() before submitting portfolio orders.
        Call .halted_mics() to log which exchanges blocked execution.

    Never raises. All failures produce valid=False for the affected MIC.
    """
    if not mics:
        return BatchResult()

    unique_mics = list(dict.fromkeys(mics))  # deduplicate, preserve order

    # Each to_thread call gets its own OracleClient — no shared state.
    tasks = [asyncio.to_thread(_fetch_and_verify_one, mic) for mic in unique_mics]
    mic_results: list[MICResult] = await asyncio.gather(*tasks)

    return BatchResult(results={r.mic: r for r in mic_results})


# ── Portfolio guard helper ────────────────────────────────────────────────────

def portfolio_can_execute(batch_result: BatchResult) -> bool:
    """
    Strict AND gate for multi-exchange portfolios.

    Returns True only when every MIC in the batch is verified OPEN.
    One closed or unreachable exchange halts the entire portfolio.

    For strategies that should gate per-position independently (not as a block),
    iterate batch_result.results and check each MICResult.executable directly.
    """
    return batch_result.can_execute()
