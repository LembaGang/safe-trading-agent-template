"""
graph.py — The LangGraph execution graph for the safe trading agent.

Graph topology:
                    ┌─────────────┐
                    │  reasoning  │  ← LLM analyses trade intent
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │oracle_check │  ← Fetch + verify Ed25519 receipt
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              │ oracle_valid=True        │ oracle_valid=False
              │ AND market_status=OPEN   │ OR market_status != OPEN
              │                          │
       ┌──────▼──────┐          ┌────────▼────────┐
       │  execution  │          │    failsafe      │
       └──────┬──────┘          └────────┬─────────┘
              │                          │
              └────────────┬─────────────┘
                           │
                          END

Fail-closed routing: any non-OPEN status (CLOSED, HALTED, UNKNOWN) routes to
failsafe. An invalid or expired oracle receipt also routes to failsafe.
UNKNOWN is never treated as permissive — see ADR-002.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from agent.state import AgentState
from agent.nodes.reasoning import reasoning_node
from agent.nodes.oracle import oracle_check_node
from agent.nodes.execution import execution_node, failsafe_node


def _route_after_oracle(state: AgentState) -> str:
    """
    The single routing decision in the graph.

    Returns "execute" only when BOTH conditions are met:
      1. Signature verification passed (oracle_valid=True)
      2. Market is OPEN

    Everything else — including UNKNOWN — routes to failsafe.
    This function is tested directly in tests/test_graph_routing.py.
    """
    if state["oracle_valid"] and state["market_status"] == "OPEN":
        return "execute"
    return "failsafe"


def build_graph() -> StateGraph:
    """
    Build and compile the LangGraph execution graph.

    Returns a compiled graph ready for .invoke() or .stream().

    Usage:
        graph = build_graph()
        result = graph.invoke({
            "mic": "XNYS",
            "trade_intent": "Buy 100 shares of AAPL at market",
            "reasoning": "",
            "oracle_receipt": None,
            "oracle_valid": False,
            "market_status": "NOT_CHECKED",
            "halt_reason": None,
            "action": "",
            "result": "",
        })
        print(result["action"])   # "EXECUTE" or "HALT"
        print(result["result"])   # Human-readable outcome
    """
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("reasoning", reasoning_node)
    workflow.add_node("oracle_check", oracle_check_node)
    workflow.add_node("execution", execution_node)
    workflow.add_node("failsafe", failsafe_node)

    # Wire the graph
    workflow.set_entry_point("reasoning")
    workflow.add_edge("reasoning", "oracle_check")
    workflow.add_conditional_edges(
        "oracle_check",
        _route_after_oracle,
        {
            "execute": "execution",
            "failsafe": "failsafe",
        },
    )
    workflow.add_edge("execution", END)
    workflow.add_edge("failsafe", END)

    return workflow.compile()


# Exported for unit tests
route_after_oracle = _route_after_oracle
