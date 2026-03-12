"""
Tests for LangGraph execution routing logic.

Two layers of tests:
  1. Unit — test the routing function directly with pre-built states (fast, no mocking)
  2. Integration — test the full graph with mocked oracle + reasoning nodes

All tests are offline — no live API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from headless_oracle.verify import VerifyResult

from agent.graph import build_graph, route_after_oracle
from tests.conftest import TEST_PUBLIC_KEY_HEX


# ── 1. Routing function unit tests ────────────────────────────────────────────

class TestRouteAfterOracle:
    """The routing function is the single source of truth for execution gating."""

    def test_open_and_valid_routes_to_execute(self):
        state = {"oracle_valid": True, "market_status": "OPEN"}
        assert route_after_oracle(state) == "execute"

    def test_closed_routes_to_failsafe(self):
        state = {"oracle_valid": True, "market_status": "CLOSED"}
        assert route_after_oracle(state) == "failsafe"

    def test_halted_routes_to_failsafe(self):
        state = {"oracle_valid": True, "market_status": "HALTED"}
        assert route_after_oracle(state) == "failsafe"

    def test_unknown_routes_to_failsafe(self):
        """UNKNOWN is always treated as CLOSED — fail-closed contract."""
        state = {"oracle_valid": True, "market_status": "UNKNOWN"}
        assert route_after_oracle(state) == "failsafe"

    def test_invalid_signature_routes_to_failsafe_even_if_open(self):
        """Invalid sig + OPEN status must still halt — oracle_valid=False wins."""
        state = {"oracle_valid": False, "market_status": "OPEN"}
        assert route_after_oracle(state) == "failsafe"

    def test_fetch_failure_routes_to_failsafe(self):
        """Oracle unreachable (oracle_receipt=None) must halt."""
        state = {"oracle_valid": False, "market_status": "UNKNOWN"}
        assert route_after_oracle(state) == "failsafe"


# ── 2. Full graph integration tests ─────────────────────────────────────────

def _make_graph_state(base_state: dict, **overrides) -> dict:
    return {**base_state, **overrides}


class TestFullGraphOpenMarket:
    def test_open_market_executes(self, base_state, open_receipt):
        with (
            patch("agent.nodes.oracle.OracleClient") as MockClient,
            patch("agent.nodes.oracle.verify") as mock_verify,
            patch("agent.nodes.reasoning._ANTHROPIC_API_KEY", None),
        ):
            client_ctx = MockClient.return_value.__enter__.return_value
            client_ctx.get_demo.return_value = open_receipt
            mock_verify.return_value = VerifyResult(valid=True)

            graph = build_graph()
            result = graph.invoke(base_state)

        assert result["action"] == "EXECUTE"
        assert "EXECUTE" in result["result"] or "submitted" in result["result"]
        assert result["oracle_valid"] is True
        assert result["market_status"] == "OPEN"

    def test_action_and_result_populated(self, base_state, open_receipt):
        with (
            patch("agent.nodes.oracle.OracleClient") as MockClient,
            patch("agent.nodes.oracle.verify") as mock_verify,
            patch("agent.nodes.reasoning._ANTHROPIC_API_KEY", None),
        ):
            client_ctx = MockClient.return_value.__enter__.return_value
            client_ctx.get_demo.return_value = open_receipt
            mock_verify.return_value = VerifyResult(valid=True)

            graph = build_graph()
            result = graph.invoke(base_state)

        assert result["action"] != ""
        assert result["result"] != ""


class TestFullGraphClosedMarket:
    def test_closed_market_halts(self, base_state, closed_receipt):
        with (
            patch("agent.nodes.oracle.OracleClient") as MockClient,
            patch("agent.nodes.oracle.verify") as mock_verify,
            patch("agent.nodes.reasoning._ANTHROPIC_API_KEY", None),
        ):
            client_ctx = MockClient.return_value.__enter__.return_value
            client_ctx.get_demo.return_value = closed_receipt
            mock_verify.return_value = VerifyResult(valid=True)

            graph = build_graph()
            result = graph.invoke(base_state)

        assert result["action"] == "HALT"
        assert "HALT" in result["result"]
        assert result["market_status"] == "CLOSED"

    def test_halted_market_halts(self, base_state, halted_receipt):
        with (
            patch("agent.nodes.oracle.OracleClient") as MockClient,
            patch("agent.nodes.oracle.verify") as mock_verify,
            patch("agent.nodes.reasoning._ANTHROPIC_API_KEY", None),
        ):
            client_ctx = MockClient.return_value.__enter__.return_value
            client_ctx.get_demo.return_value = halted_receipt
            mock_verify.return_value = VerifyResult(valid=True)

            graph = build_graph()
            result = graph.invoke(base_state)

        assert result["action"] == "HALT"
        assert result["market_status"] == "HALTED"

    def test_unknown_market_halts(self, base_state, unknown_receipt):
        """UNKNOWN must halt — no special-casing."""
        with (
            patch("agent.nodes.oracle.OracleClient") as MockClient,
            patch("agent.nodes.oracle.verify") as mock_verify,
            patch("agent.nodes.reasoning._ANTHROPIC_API_KEY", None),
        ):
            client_ctx = MockClient.return_value.__enter__.return_value
            client_ctx.get_demo.return_value = unknown_receipt
            mock_verify.return_value = VerifyResult(valid=True)

            graph = build_graph()
            result = graph.invoke(base_state)

        assert result["action"] == "HALT"
        assert result["market_status"] == "UNKNOWN"


class TestFullGraphOracleFailures:
    def test_invalid_signature_halts(self, base_state, open_receipt):
        """Even if the market is OPEN, invalid sig must halt."""
        with (
            patch("agent.nodes.oracle.OracleClient") as MockClient,
            patch("agent.nodes.oracle.verify") as mock_verify,
            patch("agent.nodes.reasoning._ANTHROPIC_API_KEY", None),
        ):
            client_ctx = MockClient.return_value.__enter__.return_value
            client_ctx.get_demo.return_value = open_receipt
            mock_verify.return_value = VerifyResult(valid=False, reason="INVALID_SIGNATURE")

            graph = build_graph()
            result = graph.invoke(base_state)

        assert result["action"] == "HALT"
        assert result["oracle_valid"] is False

    def test_oracle_unreachable_halts(self, base_state):
        """Network failure → oracle_valid=False → halt."""
        with (
            patch("agent.nodes.oracle.OracleClient") as MockClient,
            patch("agent.nodes.reasoning._ANTHROPIC_API_KEY", None),
        ):
            MockClient.return_value.__enter__.side_effect = Exception("Connection refused")

            graph = build_graph()
            result = graph.invoke(base_state)

        assert result["action"] == "HALT"
        assert result["market_status"] == "UNKNOWN"

    def test_expired_receipt_halts(self, base_state, expired_receipt):
        """Expired receipt fails verification → halt."""
        with (
            patch("agent.nodes.oracle.OracleClient") as MockClient,
            patch("agent.nodes.reasoning._ANTHROPIC_API_KEY", None),
        ):
            client_ctx = MockClient.return_value.__enter__.return_value
            client_ctx.get_demo.return_value = expired_receipt
            # Let the real verify() run — it will catch the expired TTL
            # No need to mock verify here

            graph = build_graph()
            result = graph.invoke({
                **base_state,
                # Inject test public key so verify() doesn't hit the live /v5/keys endpoint
            })

        # oracle_check_node runs verify() which hits /v5/keys unless ORACLE_PUBLIC_KEY is set.
        # The expired_receipt has a past expires_at, so TTL check fires before key fetch.
        assert result["action"] == "HALT"
