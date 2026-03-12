"""
async_oracle.py — Enterprise async batch oracle verification.

The bottleneck for multi-position agents running serial oracle checks:
  50 positions × ~200ms HTTP round-trip = ~10 seconds of pure I/O wait.

This module eliminates that with two strategies, selected automatically:

  Strategy A — /v5/batch (API key set, default):
    Single HTTP connection, single round-trip, N receipts returned in order.
    100 positions → 1 request, ~200ms. Thread-pool usage: 1 slot.

  Strategy B — N concurrent /v5/demo calls (no API key):
    N asyncio.to_thread calls, each in its own thread. Total latency still
    bounded by the slowest receipt, not the sum. Thread-pool usage: N slots.

Both paths converge on the same verify() logic and fail-closed contract:
  Any exception, invalid signature, expired TTL, or non-OPEN status produces
  valid=False for the affected MIC. ALL MICs must be valid + OPEN for
  BatchResult.can_execute() to return True. UNKNOWN is never permissive.

Usage:
    import asyncio
    from agent.nodes.async_oracle import batch_oracle_check, portfolio_can_execute

    # Authenticated (API key in env) — single /v5/batch call:
    result = asyncio.run(batch_oracle_check(["XNYS", "XNAS", "XLON"]))

    # Explicit concurrent path (e.g. demo mode, no API key):
    result = asyncio.run(batch_oracle_check(["XNYS", "XNAS"], use_batch=False))

    if portfolio_can_execute(result):
        broker.submit_portfolio_orders(...)
    else:
        print(f"Halted MICs: {result.halted_mics()}")

Environment variables:
  ORACLE_API_KEY    — Enables /v5/status and /v5/batch (authenticated).
                      Absent → /v5/demo concurrent path.
  ORACLE_PUBLIC_KEY — Hex Ed25519 public key. Pins the key to skip the
                      /v5/keys round-trip on every verify() call.
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
        """True only when this MIC is verified and OPEN."""
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


# ── Sync unit: one MIC, one HTTP call ─────────────────────────────────────────

def _fetch_and_verify_one(mic: str) -> MICResult:
    """
    Fetch and verify a signed oracle receipt for a single MIC.

    Used by Strategy B (concurrent /v5/demo, or fallback per-MIC /v5/status).
    Each call opens its own OracleClient — no shared HTTP state.
    Never raises. All failure modes return valid=False.
    """
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

    result: VerifyResult = verify(receipt, public_key=_ORACLE_PUBLIC_KEY or None)
    if not result.valid:
        return MICResult(
            mic=mic,
            valid=False,
            market_status="UNKNOWN",
            receipt=receipt,
            halt_reason=f"Receipt invalid ({result.reason}) — fail-closed",
        )

    status: str = receipt.get("status", "UNKNOWN")
    return MICResult(
        mic=mic,
        valid=True,
        market_status=status,
        receipt=receipt,
        halt_reason=None if status == "OPEN" else f"Market is {status}",
    )


# ── Sync unit: all MICs, one HTTP call (/v5/batch) ────────────────────────────

def _fetch_batch_one_shot(mics: list[str]) -> list[MICResult]:
    """
    Fetch signed receipts for N MICs in a single /v5/batch HTTP call.

    Requires ORACLE_API_KEY. Reduces N HTTP round-trips to 1, and N thread-pool
    slots to 1. This is the Strategy A path for authenticated production agents.

    Response schema: {"receipts": [{...}, ...]} in the same order as the input.

    Never raises. On total batch failure all MICs fail closed. On a missing or
    malformed individual receipt that MIC fails closed, others are unaffected.
    """
    try:
        with OracleClient(api_key=_ORACLE_API_KEY) as client:
            response: dict[str, Any] = client.get_batch(mics)
    except Exception as exc:
        # Catastrophic: can't reach /v5/batch at all — fail all MICs closed.
        return [
            MICResult(
                mic=mic,
                valid=False,
                market_status="UNKNOWN",
                halt_reason=f"Batch fetch failed: {exc}",
            )
            for mic in mics
        ]

    # Parse batch response: {"receipts": [{receipt}, ...]} ordered by input.
    receipts: list[Any] = response.get("receipts", [])

    results: list[MICResult] = []
    for i, mic in enumerate(mics):
        receipt = receipts[i] if i < len(receipts) else None

        if not isinstance(receipt, dict):
            results.append(MICResult(
                mic=mic,
                valid=False,
                market_status="UNKNOWN",
                halt_reason="Missing or malformed receipt in batch response — fail-closed",
            ))
            continue

        verify_result: VerifyResult = verify(receipt, public_key=_ORACLE_PUBLIC_KEY or None)
        if not verify_result.valid:
            results.append(MICResult(
                mic=mic,
                valid=False,
                market_status="UNKNOWN",
                receipt=receipt,
                halt_reason=f"Receipt invalid ({verify_result.reason}) — fail-closed",
            ))
            continue

        status: str = receipt.get("status", "UNKNOWN")
        results.append(MICResult(
            mic=mic,
            valid=True,
            market_status=status,
            receipt=receipt,
            halt_reason=None if status == "OPEN" else f"Market is {status}",
        ))

    return results


# ── Async orchestrator ────────────────────────────────────────────────────────

async def batch_oracle_check(
    mics: list[str],
    *,
    use_batch: bool = True,
) -> BatchResult:
    """
    Fetch and verify oracle receipts for N MICs.

    Strategy selection (automatic unless overridden):
      API key set + use_batch=True  → single /v5/batch call (1 thread, 1 request)
      No API key  OR use_batch=False → N concurrent /v5/demo calls via asyncio.gather

    Args:
        mics:      MIC codes to check. Duplicates are deduplicated before fetching.
        use_batch: Set False to force the per-MIC concurrent path even when
                   ORACLE_API_KEY is set (e.g. for testing or explicit override).

    Returns:
        BatchResult. Call .can_execute() before submitting portfolio orders.
        Call .halted_mics() to identify which exchanges blocked execution.

    Never raises. All failures produce valid=False for the affected MIC.
    """
    if not mics:
        return BatchResult()

    unique_mics = list(dict.fromkeys(mics))  # deduplicate, preserve order

    if _ORACLE_API_KEY and use_batch:
        # Strategy A: single /v5/batch HTTP call — 1 thread, 1 round-trip.
        mic_results = await asyncio.to_thread(_fetch_batch_one_shot, unique_mics)
    else:
        # Strategy B: N concurrent calls, each in its own thread.
        tasks = [asyncio.to_thread(_fetch_and_verify_one, mic) for mic in unique_mics]
        mic_results = await asyncio.gather(*tasks)

    return BatchResult(results={r.mic: r for r in mic_results})


# ── Portfolio guard helper ────────────────────────────────────────────────────

def portfolio_can_execute(batch_result: BatchResult) -> bool:
    """
    Strict AND gate for multi-exchange portfolios.

    Returns True only when every MIC in the batch is verified OPEN.
    One closed or unreachable exchange halts the entire portfolio.

    For per-position independent gating (not a portfolio-wide block),
    iterate batch_result.results and check each MICResult.executable directly.
    """
    return batch_result.can_execute()
