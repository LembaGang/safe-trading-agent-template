"""
reasoning_node — Step 1 of the execution gate.

Analyses the trade intent using Claude. If ANTHROPIC_API_KEY is not set,
runs in passthrough mode so the rest of the graph still works for demos.

The LLM is intentionally kept short-context here: its job is pre-trade
reasoning only. It does NOT decide whether to execute — that is the oracle's job.
"""

from __future__ import annotations

import os

from agent.state import AgentState

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

_SYSTEM_PROMPT = """You are a pre-trade reasoning assistant for an autonomous trading agent.

Your only job is to briefly analyse a trade intent before it goes to market verification.
Keep your response to 2-3 sentences maximum. Do NOT decide whether to execute —
that decision is made by a cryptographic market oracle, not by you.

Highlight: what the trade is, any obvious risks, and what a successful execution looks like."""


def reasoning_node(state: AgentState) -> dict:
    """
    Analyse trade intent with an LLM.

    Returns a partial state dict with 'reasoning' populated.
    Falls back to passthrough if ANTHROPIC_API_KEY is not set.
    """
    if not _ANTHROPIC_API_KEY:
        return {"reasoning": f"[LLM not configured — passthrough] Intent: {state['trade_intent']}"}

    # Lazy import so the template works without langchain-anthropic installed
    # when running in passthrough mode.
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        return {"reasoning": "[langchain-anthropic not installed — passthrough]"}

    llm = ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        api_key=_ANTHROPIC_API_KEY,
        max_tokens=150,
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Trade intent: {state['trade_intent']}\n"
                f"Target exchange (MIC): {state['mic']}"
            ),
        },
    ]

    try:
        response = llm.invoke(messages)
        return {"reasoning": response.content}
    except Exception as exc:
        # Never let a failed LLM call block the oracle check.
        return {"reasoning": f"[Reasoning error: {exc}]"}
