"""
demo_without_llm.py — Minimal demo showing ONLY the oracle verification gate.

No ANTHROPIC_API_KEY needed. Shows the core primitive:
  fetch receipt → verify sig → check TTL → check OPEN → execute or halt

Run: python examples/demo_without_llm.py

This is the pattern to copy when integrating Headless Oracle into an
existing agent framework without LangGraph.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from headless_oracle import OracleClient, verify

ORACLE_API_KEY = os.getenv("ORACLE_API_KEY")
ORACLE_PUBLIC_KEY = os.getenv("ORACLE_PUBLIC_KEY")
MIC = os.getenv("DEFAULT_MIC", "XNYS")


def safe_execute(trade_intent: str) -> None:
    """
    The canonical 4-step execution gate.

    Step 1: Fetch signed receipt
    Step 2: Verify Ed25519 signature
    Step 3: Check TTL (handled inside verify())
    Step 4: Check status == OPEN
    """
    print(f"\n[Gate] Checking market status for {MIC}...")

    # ── Step 1: Fetch ────────────────────────────────────────────────────────
    try:
        with OracleClient(api_key=ORACLE_API_KEY) as client:
            receipt = client.get_status(MIC) if ORACLE_API_KEY else client.get_demo(MIC)
    except Exception as exc:
        print(f"[HALT] Oracle unreachable: {exc}")
        print("[HALT] Treating as UNKNOWN → CLOSED per fail-closed contract.")
        return

    print(f"[Gate] Receipt received: status={receipt['status']}, "
          f"expires_at={receipt['expires_at']}, "
          f"receipt_mode={receipt['receipt_mode']}")

    # ── Steps 2 + 3: Verify signature and TTL ───────────────────────────────
    result = verify(receipt, public_key=ORACLE_PUBLIC_KEY or None)

    if not result.valid:
        print(f"[HALT] Signature verification failed: {result.reason}")
        print("[HALT] Forged or expired receipt — no trade executed.")
        return

    print(f"[Gate] Ed25519 signature valid. TTL ok.")

    # ── Step 4: Check status ─────────────────────────────────────────────────
    status = receipt.get("status", "UNKNOWN")

    if status != "OPEN":
        print(f"[HALT] Market is {status}. No trade executed.")
        if status == "UNKNOWN":
            print("[HALT] UNKNOWN is treated as CLOSED per fail-closed contract.")
        return

    # ── Execute ──────────────────────────────────────────────────────────────
    print(f"[EXECUTE] All gates passed. Executing: {trade_intent}")
    # broker.submit_order(...)
    print(f"[EXECUTE] Done. Oracle attested OPEN at {receipt['issued_at']}")


if __name__ == "__main__":
    safe_execute("Buy 100 AAPL at market")
