"""
Unit tests for Headless Oracle receipt verification.

These tests use the test keypair from conftest.py — no live network calls.
All tests pass TEST_PUBLIC_KEY_HEX directly to verify() to skip the /v5/keys fetch.
"""

from __future__ import annotations

import pytest
from headless_oracle import verify

from tests.conftest import TEST_PUBLIC_KEY_HEX


class TestValidReceipt:
    def test_open_receipt_is_valid(self, open_receipt):
        result = verify(open_receipt, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is True
        assert result.reason is None

    def test_closed_receipt_verifies(self, closed_receipt):
        """Signature is valid even when market is CLOSED — status is data, not auth."""
        result = verify(closed_receipt, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is True

    def test_halted_receipt_verifies(self, halted_receipt):
        result = verify(halted_receipt, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is True

    def test_unknown_receipt_verifies(self, unknown_receipt):
        result = verify(unknown_receipt, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is True


class TestExpiredReceipt:
    def test_expired_returns_false(self, expired_receipt):
        result = verify(expired_receipt, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is False
        assert result.reason == "EXPIRED"

    def test_not_expired_by_default(self, open_receipt):
        """Receipts built with default 60s window should not be expired immediately."""
        result = verify(open_receipt, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is True


class TestTamperedReceipt:
    def test_tampered_status_fails(self, tampered_receipt):
        """Changing status after signing invalidates the Ed25519 signature."""
        result = verify(tampered_receipt, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is False
        assert result.reason == "INVALID_SIGNATURE"

    def test_wrong_public_key_fails(self, open_receipt):
        """Verification with a different public key should fail."""
        import nacl.signing, nacl.encoding
        wrong_key = nacl.signing.SigningKey.generate()
        wrong_pub = wrong_key.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()
        result = verify(open_receipt, public_key=wrong_pub)
        assert result.valid is False
        assert result.reason == "INVALID_SIGNATURE"


class TestMissingFields:
    def test_missing_fields_fails(self, missing_fields_receipt):
        result = verify(missing_fields_receipt, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is False
        assert result.reason == "MISSING_FIELDS"

    def test_empty_dict_fails(self):
        result = verify({}, public_key=TEST_PUBLIC_KEY_HEX)
        assert result.valid is False
        assert result.reason == "MISSING_FIELDS"


class TestInvalidKeyFormat:
    def test_invalid_hex_key_fails(self, open_receipt):
        result = verify(open_receipt, public_key="not-valid-hex!!")
        assert result.valid is False
        assert result.reason == "INVALID_KEY_FORMAT"

    def test_empty_key_string_fails(self, open_receipt):
        result = verify(open_receipt, public_key="")
        assert result.valid is False
        assert result.reason == "INVALID_KEY_FORMAT"
