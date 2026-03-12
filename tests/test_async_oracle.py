"""
Unit tests for the enterprise async batch oracle module.

All tests are offline — oracle fetches are fully mocked. Tests cover:
  1. BatchResult / MICResult data model (pure logic)
  2. portfolio_can_execute() guard function
  3. _fetch_and_verify_one() sync I/O unit (mocked OracleClient + verify)
  4. batch_oracle_check() async orchestrator (mocked _fetch_and_verify_one)
  5. Fail-closed contract: any failure → valid=False for that MIC
  6. Deduplication of duplicate MICs in the input list

Run offline with:
    pytest tests/test_async_oracle.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from headless_oracle.verify import VerifyResult
from agent.nodes.async_oracle import (
    BatchResult,
    MICResult,
    batch_oracle_check,
    portfolio_can_execute,
    _fetch_and_verify_one,
)
from tests.conftest import TEST_PUBLIC_KEY_HEX, _build_receipt as _make_receipt


# ── Helper ────────────────────────────────────────────────────────────────────

def _run(coro):
    """Run an async coroutine synchronously from a test."""
    return asyncio.run(coro)


def _open(mic: str) -> MICResult:
    return MICResult(mic=mic, valid=True, market_status="OPEN")


def _closed(mic: str) -> MICResult:
    return MICResult(mic=mic, valid=True, market_status="CLOSED")


def _unknown(mic: str, reason: str = "Timeout") -> MICResult:
    return MICResult(mic=mic, valid=False, market_status="UNKNOWN", halt_reason=reason)


# ── 1. MICResult.executable property ─────────────────────────────────────────

class TestMICResultExecutable:
    def test_valid_open_is_executable(self):
        assert _open("XNYS").executable is True

    def test_valid_closed_is_not_executable(self):
        assert _closed("XNYS").executable is False

    def test_invalid_open_is_not_executable(self):
        """oracle_valid=False + status=OPEN must never be executable."""
        r = MICResult(mic="XNYS", valid=False, market_status="OPEN")
        assert r.executable is False

    def test_valid_halted_is_not_executable(self):
        r = MICResult(mic="XNYS", valid=True, market_status="HALTED")
        assert r.executable is False

    def test_valid_unknown_is_not_executable(self):
        r = MICResult(mic="XNYS", valid=True, market_status="UNKNOWN")
        assert r.executable is False


# ── 2. BatchResult logic ──────────────────────────────────────────────────────

class TestBatchResultCanExecute:
    def test_all_open_can_execute(self):
        batch = BatchResult(results={"XNYS": _open("XNYS"), "XNAS": _open("XNAS")})
        assert batch.can_execute() is True

    def test_empty_batch_can_execute(self):
        """No MICs = no positions to gate — vacuously True."""
        assert BatchResult().can_execute() is True

    def test_single_open_can_execute(self):
        assert BatchResult(results={"XNYS": _open("XNYS")}).can_execute() is True

    def test_one_closed_blocks_portfolio(self):
        batch = BatchResult(results={"XNYS": _open("XNYS"), "XLON": _closed("XLON")})
        assert batch.can_execute() is False

    def test_one_invalid_blocks_portfolio(self):
        batch = BatchResult(results={"XNYS": _open("XNYS"), "XLON": _unknown("XLON")})
        assert batch.can_execute() is False

    def test_all_closed_cannot_execute(self):
        batch = BatchResult(results={"XNYS": _closed("XNYS"), "XNAS": _closed("XNAS")})
        assert batch.can_execute() is False


class TestBatchResultHaltedMics:
    def test_halted_mics_excludes_open(self):
        batch = BatchResult(results={
            "XNYS": _open("XNYS"),
            "XLON": _closed("XLON"),
            "XJPX": _unknown("XJPX"),
        })
        halted = batch.halted_mics()
        assert "XLON" in halted
        assert "XJPX" in halted
        assert "XNYS" not in halted

    def test_open_mics_excludes_closed(self):
        batch = BatchResult(results={"XNYS": _open("XNYS"), "XLON": _closed("XLON")})
        assert batch.open_mics() == ["XNYS"]

    def test_all_open_no_halted(self):
        batch = BatchResult(results={"XNYS": _open("XNYS")})
        assert batch.halted_mics() == []


# ── 3. portfolio_can_execute() ────────────────────────────────────────────────

class TestPortfolioCanExecute:
    def test_true_when_all_open(self):
        batch = BatchResult(results={"XNYS": _open("XNYS"), "XNAS": _open("XNAS")})
        assert portfolio_can_execute(batch) is True

    def test_false_when_any_closed(self):
        batch = BatchResult(results={"XNYS": _open("XNYS"), "XLON": _closed("XLON")})
        assert portfolio_can_execute(batch) is False

    def test_false_when_any_invalid(self):
        batch = BatchResult(results={"XNYS": _unknown("XNYS")})
        assert portfolio_can_execute(batch) is False


# ── 4. _fetch_and_verify_one() — sync I/O unit ────────────────────────────────

class TestFetchAndVerifyOne:
    def test_open_receipt_returns_valid_open(self):
        receipt = _make_receipt(mic="XNYS", status="OPEN")
        with (
            patch("agent.nodes.async_oracle.OracleClient") as MockClient,
            patch("agent.nodes.async_oracle.verify") as mock_verify,
            patch("agent.nodes.async_oracle._ORACLE_API_KEY", None),
        ):
            ctx = MockClient.return_value.__enter__.return_value
            ctx.get_demo.return_value = receipt
            mock_verify.return_value = VerifyResult(valid=True)

            result = _fetch_and_verify_one("XNYS")

        assert result.valid is True
        assert result.market_status == "OPEN"
        assert result.executable is True
        assert result.halt_reason is None

    def test_closed_receipt_returns_valid_but_not_executable(self):
        receipt = _make_receipt(mic="XNYS", status="CLOSED")
        with (
            patch("agent.nodes.async_oracle.OracleClient") as MockClient,
            patch("agent.nodes.async_oracle.verify") as mock_verify,
            patch("agent.nodes.async_oracle._ORACLE_API_KEY", None),
        ):
            ctx = MockClient.return_value.__enter__.return_value
            ctx.get_demo.return_value = receipt
            mock_verify.return_value = VerifyResult(valid=True)

            result = _fetch_and_verify_one("XNYS")

        assert result.valid is True
        assert result.market_status == "CLOSED"
        assert result.executable is False
        assert result.halt_reason is not None

    def test_invalid_signature_fails_closed(self):
        receipt = _make_receipt(mic="XNYS", status="OPEN")
        with (
            patch("agent.nodes.async_oracle.OracleClient") as MockClient,
            patch("agent.nodes.async_oracle.verify") as mock_verify,
            patch("agent.nodes.async_oracle._ORACLE_API_KEY", None),
        ):
            ctx = MockClient.return_value.__enter__.return_value
            ctx.get_demo.return_value = receipt
            mock_verify.return_value = VerifyResult(valid=False, reason="INVALID_SIGNATURE")

            result = _fetch_and_verify_one("XNYS")

        assert result.valid is False
        assert result.market_status == "UNKNOWN"
        assert "INVALID_SIGNATURE" in result.halt_reason

    def test_network_error_fails_closed(self):
        with (
            patch("agent.nodes.async_oracle.OracleClient") as MockClient,
            patch("agent.nodes.async_oracle._ORACLE_API_KEY", None),
        ):
            MockClient.return_value.__enter__.side_effect = ConnectionError("timeout")

            result = _fetch_and_verify_one("XNYS")

        assert result.valid is False
        assert result.market_status == "UNKNOWN"
        assert "Oracle unreachable" in result.halt_reason

    def test_uses_get_status_when_api_key_set(self):
        receipt = _make_receipt(mic="XNYS", status="OPEN")
        with (
            patch("agent.nodes.async_oracle.OracleClient") as MockClient,
            patch("agent.nodes.async_oracle.verify") as mock_verify,
            patch("agent.nodes.async_oracle._ORACLE_API_KEY", "ok_live_test"),
        ):
            ctx = MockClient.return_value.__enter__.return_value
            ctx.get_status.return_value = receipt
            mock_verify.return_value = VerifyResult(valid=True)

            result = _fetch_and_verify_one("XNYS")

        ctx.get_status.assert_called_once_with("XNYS")
        ctx.get_demo.assert_not_called()
        assert result.valid is True

    def test_uses_get_demo_when_no_api_key(self):
        receipt = _make_receipt(mic="XNYS", status="OPEN")
        with (
            patch("agent.nodes.async_oracle.OracleClient") as MockClient,
            patch("agent.nodes.async_oracle.verify") as mock_verify,
            patch("agent.nodes.async_oracle._ORACLE_API_KEY", None),
        ):
            ctx = MockClient.return_value.__enter__.return_value
            ctx.get_demo.return_value = receipt
            mock_verify.return_value = VerifyResult(valid=True)

            _fetch_and_verify_one("XNYS")

        ctx.get_demo.assert_called_once_with("XNYS")
        ctx.get_status.assert_not_called()


# ── 5. batch_oracle_check() async orchestrator ───────────────────────────────

class TestBatchOracleCheck:
    def test_all_open_returns_executable_batch(self):
        def fake_fetch(mic):
            return _open(mic)

        with patch("agent.nodes.async_oracle._fetch_and_verify_one", side_effect=fake_fetch):
            result = _run(batch_oracle_check(["XNYS", "XNAS", "XLON"]))

        assert result.can_execute() is True
        assert result.halted_mics() == []
        assert len(result.results) == 3

    def test_empty_list_returns_empty_batch(self):
        result = _run(batch_oracle_check([]))
        assert result.can_execute() is True
        assert result.results == {}

    def test_one_closed_mic_blocks_portfolio(self):
        def fake_fetch(mic):
            return _closed(mic) if mic == "XLON" else _open(mic)

        with patch("agent.nodes.async_oracle._fetch_and_verify_one", side_effect=fake_fetch):
            result = _run(batch_oracle_check(["XNYS", "XNAS", "XLON"]))

        assert result.can_execute() is False
        assert "XLON" in result.halted_mics()
        assert result.results["XNYS"].executable is True

    def test_one_fetch_failure_fails_closed_for_that_mic(self):
        def fake_fetch(mic):
            if mic == "XJPX":
                return _unknown("XJPX", reason="Oracle unreachable: timeout")
            return _open(mic)

        with patch("agent.nodes.async_oracle._fetch_and_verify_one", side_effect=fake_fetch):
            result = _run(batch_oracle_check(["XNYS", "XJPX"]))

        assert result.can_execute() is False
        assert result.results["XNYS"].executable is True
        assert result.results["XJPX"].executable is False

    def test_duplicate_mics_are_deduplicated(self):
        calls = []

        def fake_fetch(mic):
            calls.append(mic)
            return _open(mic)

        with patch("agent.nodes.async_oracle._fetch_and_verify_one", side_effect=fake_fetch):
            result = _run(batch_oracle_check(["XNYS", "XNYS", "XNAS"]))

        # XNYS should only be fetched once
        assert calls.count("XNYS") == 1
        assert len(result.results) == 2

    def test_results_keyed_by_mic_string(self):
        def fake_fetch(mic):
            return _open(mic)

        with patch("agent.nodes.async_oracle._fetch_and_verify_one", side_effect=fake_fetch):
            result = _run(batch_oracle_check(["XNYS", "XLON"]))

        assert "XNYS" in result.results
        assert "XLON" in result.results
        assert result.results["XNYS"].mic == "XNYS"

    def test_all_mics_called(self):
        """Every requested MIC should be fetched."""
        mics_fetched = []

        def fake_fetch(mic):
            mics_fetched.append(mic)
            return _open(mic)

        mics = ["XNYS", "XNAS", "XLON", "XJPX"]
        with patch("agent.nodes.async_oracle._fetch_and_verify_one", side_effect=fake_fetch):
            _run(batch_oracle_check(mics))

        assert set(mics_fetched) == set(mics)
