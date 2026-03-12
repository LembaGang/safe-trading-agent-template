"""
run_agent.py — Full example: LangGraph agent gated by Headless Oracle.

Requirements:
  1. Copy .env.example to .env and populate it
  2. pip install -r requirements.txt
  3. python examples/run_agent.py

The agent will:
  1. Reason about the trade intent (Claude Haiku if ANTHROPIC_API_KEY is set)
  2. Fetch a signed market receipt from Headless Oracle
  3. Verify the Ed25519 signature and TTL
  4. Execute (stub) if OPEN, halt if anything else
"""

from __future__ import annotations

import os
import json
import sys
from pathlib import Path

# Load .env from repo root
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from agent.graph import build_graph


def run(mic: str = "XNYS", trade_intent: str = "Buy 100 shares of AAPL at market open") -> None:
    graph = build_graph()

    initial_state = {
        "mic": mic,
        "trade_intent": trade_intent,
        "reasoning": "",
        "oracle_receipt": None,
        "oracle_valid": False,
        "market_status": "NOT_CHECKED",
        "halt_reason": None,
        "action": "",
        "result": "",
    }

    print(f"\n{'='*60}")
    print(f"  Safe Trading Agent — Headless Oracle Gate")
    print(f"  Exchange : {mic}")
    print(f"  Intent   : {trade_intent}")
    print(f"{'='*60}\n")

    result = graph.invoke(initial_state)

    print(f"\n{'='*60}")
    print(f"  FINAL RESULT")
    print(f"{'='*60}")
    print(f"  Action         : {result['action']}")
    print(f"  Market status  : {result['market_status']}")
    print(f"  Oracle valid   : {result['oracle_valid']}")
    print(f"  Reasoning      : {result['reasoning'][:100]}...")
    if result.get("halt_reason"):
        print(f"  Halt reason    : {result['halt_reason']}")
    print(f"\n  {result['result']}")
    print(f"{'='*60}\n")

    if result.get("oracle_receipt"):
        print("Oracle receipt (signed attestation):")
        receipt = {k: v for k, v in result["oracle_receipt"].items() if k != "signature"}
        print(json.dumps(receipt, indent=2))
        print(f"  signature: {result['oracle_receipt'].get('signature', '')[:32]}...[truncated]")


if __name__ == "__main__":
    mic = os.getenv("DEFAULT_MIC", "XNYS")
    intent = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Buy 100 shares of AAPL at market open"
    run(mic=mic, trade_intent=intent)
