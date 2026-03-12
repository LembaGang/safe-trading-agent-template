"""
Test fixtures for the safe-trading-agent-template test suite.

Key fixture: make_receipt() — generates a properly signed Headless Oracle receipt
using a test Ed25519 keypair. Tests that need to verify receipts pass the
TEST_PUBLIC_KEY_HEX constant to the verify() call instead of hitting the live API.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta

import nacl.signing
import nacl.encoding
import pytest

# ── Test keypair (generated once per test session) ───────────────────────────
_TEST_SIGNING_KEY = nacl.signing.SigningKey.generate()
TEST_PUBLIC_KEY_HEX: str = (
    _TEST_SIGNING_KEY.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()
)


def _sign_receipt(payload: dict) -> str:
    """Sign a canonical payload dict and return hex signature."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _TEST_SIGNING_KEY.sign(canonical).signature.hex()


def _build_receipt(
    mic: str = "XNYS",
    status: str = "OPEN",
    source: str = "SCHEDULE",
    receipt_mode: str = "live",
    expires_in_seconds: int = 60,
) -> dict:
    """Build and sign a valid market receipt."""
    now = datetime.now(timezone.utc)
    issued_at = now.isoformat().replace("+00:00", "Z")
    expires_at = (now + timedelta(seconds=expires_in_seconds)).isoformat().replace("+00:00", "Z")

    payload = {
        "expires_at": expires_at,
        "issued_at": issued_at,
        "issuer": "headlessoracle.com",
        "mic": mic,
        "public_key_id": "test-key-1",
        "receipt_id": "test-receipt-abc123",
        "receipt_mode": receipt_mode,
        "schema_version": "v5.0",
        "source": source,
        "status": status,
    }
    return {**payload, "signature": _sign_receipt(payload)}


@pytest.fixture
def open_receipt() -> dict:
    return _build_receipt(status="OPEN")


@pytest.fixture
def closed_receipt() -> dict:
    return _build_receipt(status="CLOSED")


@pytest.fixture
def halted_receipt() -> dict:
    return _build_receipt(status="HALTED", source="OVERRIDE")


@pytest.fixture
def unknown_receipt() -> dict:
    return _build_receipt(status="UNKNOWN", source="SYSTEM")


@pytest.fixture
def expired_receipt() -> dict:
    return _build_receipt(status="OPEN", expires_in_seconds=-10)


@pytest.fixture
def tampered_receipt() -> dict:
    """Valid signature but status field changed after signing."""
    receipt = _build_receipt(status="CLOSED")
    receipt["status"] = "OPEN"  # Tampered — signature now invalid
    return receipt


@pytest.fixture
def missing_fields_receipt() -> dict:
    return {"status": "OPEN", "mic": "XNYS"}


# ── Default initial graph state ──────────────────────────────────────────────
@pytest.fixture
def base_state() -> dict:
    return {
        "mic": "XNYS",
        "trade_intent": "Buy 100 shares of AAPL at market",
        "reasoning": "",
        "oracle_receipt": None,
        "oracle_valid": False,
        "market_status": "NOT_CHECKED",
        "halt_reason": None,
        "action": "",
        "result": "",
    }
