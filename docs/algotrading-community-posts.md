# Algotrading Community Posts — Headless Oracle

Draft posts for r/algotrading, r/Python, and X/Twitter. All code blocks are verified against
`headless-oracle==0.1.0` (PyPI). Run `pip install headless-oracle` to confirm locally.

---

## Reddit — r/algotrading

**Title:** Stop trusting timezone math for market hours — use a cryptographically signed oracle instead (with Python code)

**Body:**

---

If your algo is computing market open/close times locally with `pytz` or `datetime`, you have a bug waiting to happen. During DST transitions ("the Phantom Hour"), your bot thinks the market is open when it isn't — or vice versa. Miss a circuit breaker? Same problem.

I published a Python SDK that gives you a signed Ed25519 receipt from Headless Oracle with a 60-second TTL. The signature proves the status wasn't cached, faked, or MITM'd. If verification fails, you halt. No exceptions.

**Install:**

```bash
pip install headless-oracle
```

**4-line minimal pattern:**

```python
from headless_oracle import OracleClient, verify

with OracleClient(api_key="ok_live_your_key_here") as client:
    receipt = client.get_status("XNYS")  # authenticated, live receipt

result = verify(receipt, public_key="03dc27993a2c90856cdeb45e228ac065f18f69f0933c917b2336c1e75712f178")
if not result.valid:
    raise RuntimeError(f"Receipt invalid: {result.reason}")  # EXPIRED / INVALID_SIGNATURE / etc.

if receipt["status"] != "OPEN":
    raise RuntimeError(f"Market is {receipt['status']} — halting")

# Cryptographically verified OPEN — safe to trade
broker.submit_order(symbol="AAPL", qty=100, side="buy", type="market")
```

**No API key? Use the public demo endpoint** (rate-limited, same signature format):

```python
from headless_oracle import OracleClient, verify

with OracleClient() as client:            # no api_key → /v5/demo
    receipt = client.get_demo("XNYS")    # public, rate-limited

result = verify(receipt)                  # fetches public key from /v5/keys automatically
if not result.valid:
    raise RuntimeError(result.reason)

print(receipt["status"])   # OPEN / CLOSED / HALTED / UNKNOWN
print(receipt["issued_at"])
print(receipt["expires_at"])
```

**VerifyResult fields:**

```python
result.valid   # bool — True only if signature is good AND TTL is current
result.reason  # None on success, or one of:
               # "MISSING_FIELDS" | "EXPIRED" | "UNKNOWN_KEY" |
               # "INVALID_SIGNATURE" | "KEY_FETCH_FAILED" | "INVALID_KEY_FORMAT"
```

**Full LangGraph template** (4-gate execution graph with Ed25519 verification built in):
https://github.com/LembaGang/safe-trading-agent-template

Supported exchanges: XNYS, XNAS, XLON, XJPX, XPAR, XHKG, XSES

---

## Reddit — r/Python

**Title:** I published headless-oracle on PyPI — a typed Python SDK for cryptographically verified market status receipts

**Body:**

---

`headless-oracle` is now on PyPI.

```bash
pip install headless-oracle
```

It wraps the Headless Oracle V5 API and gives you:

- `OracleClient` — typed HTTP client (context manager, sync, built on httpx)
- `verify()` — Ed25519 signature + TTL verification (built on PyNaCl)
- `VerifyResult` — dataclass with `.valid: bool` and `.reason: str | None`

**Basic usage:**

```python
from headless_oracle import OracleClient, verify, VerifyResult

# Fetch a signed market status receipt
with OracleClient(api_key="ok_live_your_key_here") as client:
    receipt = client.get_status("XNYS")   # dict matching the V5 schema

# Verify Ed25519 signature and 60-second TTL
result: VerifyResult = verify(receipt, public_key="03dc27993a2c90...")
# Pin the public key for production — skips the /v5/keys network round-trip

if result.valid:
    print(f"Market is {receipt['status']}")   # OPEN / CLOSED / HALTED
else:
    print(f"Verification failed: {result.reason}")
```

**OracleClient methods:**

```python
client.get_status("XNYS")         # authenticated — live signed receipt
client.get_demo("XNYS")           # public — rate-limited signed receipt
client.get_batch(["XNYS", "XLON"]) # authenticated — multiple MICs, one call
client.get_schedule("XNYS")       # next open/close times
client.list_exchanges()           # all supported exchanges
client.get_keys()                 # public key registry
client.get_health()               # signed liveness receipt
```

**Error handling:** `OracleClient` raises `OracleError` (subclass of `Exception`) on non-2xx
responses. `verify()` never raises — it always returns a `VerifyResult`.

```python
from headless_oracle import OracleClient
from headless_oracle.client import OracleError

try:
    with OracleClient(api_key="ok_live_...") as client:
        receipt = client.get_status("XNYS")
except OracleError as e:
    print(f"HTTP {e.status_code}: {e.body}")
```

Source: https://github.com/LembaGang/headless-oracle-python

---

## X / Twitter Thread

**Tweet 1 (hook):**

Your algo is probably computing market hours wrong.

`pytz` + timezone math = silent failures during DST.
Miss a circuit breaker = trade against a halted market.

Here's how to fix it in 6 lines of Python: 🧵

---

**Tweet 2 (install):**

```bash
pip install headless-oracle
```

Headless Oracle returns a cryptographically signed receipt.
Ed25519. 60-second TTL. Can't be faked, cached, or replayed.

---

**Tweet 3 (code):**

```python
from headless_oracle import OracleClient, verify

with OracleClient(api_key="ok_live_...") as client:
    receipt = client.get_status("XNYS")

result = verify(receipt, public_key="03dc279...")
if not result.valid:
    halt(result.reason)  # EXPIRED / INVALID_SIGNATURE

if receipt["status"] != "OPEN":
    halt(receipt["status"])  # CLOSED / HALTED / UNKNOWN

broker.submit_order(...)  # cryptographically cleared ✓
```

---

**Tweet 4 (VerifyResult):**

`verify()` never raises. Returns:

```python
result.valid   # True = good sig + TTL current
result.reason  # None | "EXPIRED" | "INVALID_SIGNATURE" | ...
```

Fail-closed by design. Unknown state = halt.

---

**Tweet 5 (free tier):**

No API key? Public demo endpoint:

```python
with OracleClient() as client:
    receipt = client.get_demo("XNYS")

result = verify(receipt)   # fetches public key automatically
print(receipt["status"])   # OPEN / CLOSED / HALTED / UNKNOWN
```

Real signatures. Rate-limited. Perfect for dev and CI.

---

**Tweet 6 (LangGraph template):**

Building an autonomous trading agent with LangGraph?

Free template: 4-gate execution graph with oracle verification built in.

reasoning → oracle_check → execute OR halt

→ github.com/LembaGang/safe-trading-agent-template

---

**Tweet 7 (close):**

Supported: XNYS XNAS XLON XJPX XPAR XHKG XSES

DST handled by the oracle (IANA tz names, no hardcoded offsets).

pip install headless-oracle
headlessoracle.com
