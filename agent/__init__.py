"""
safe-trading-agent-template — LangGraph agent gated by Headless Oracle.

The 4-step execution gate:
  1. reasoning  — LLM analyses the trade intent
  2. oracle      — Fetch + Ed25519-verify a signed market receipt
  3. execute     — Only runs if oracle_valid=True AND market_status=OPEN
  4. failsafe    — Runs for CLOSED / HALTED / UNKNOWN / invalid signature

Import the pre-built graph:
    from agent.graph import build_graph
    graph = build_graph()
    result = graph.invoke({"mic": "XNYS", "trade_intent": "Buy 100 AAPL", ...})
"""

from agent.graph import build_graph

__all__ = ["build_graph"]
