# safe-trading-agent-template

A production-ready LangGraph starter for autonomous trading agents, gated by [Headless Oracle](https://headlessoracle.com) — a cryptographically signed market status primitive.

**The problem this solves:** AI agents using `pytz` or timezone math miscalculate market closures during DST transitions ("the Phantom Hour"), miss exchange holidays, and can't detect sudden circuit breakers. An agent with a funded wallet and a wrong market status causes toxic order flow and bad debt. This template enforces the correct execution gate before any trade leaves the process.

---

## How it works

```
trade intent → [reasoning] → [oracle check] → [execute] or [failsafe]
```

Every trade goes through four gates:

| Gate | Node | What it does |
|------|------|-------------|
| 1 | `reasoning` | LLM analyses the trade intent (Claude Haiku by default) |
| 2 | `oracle_check` | Fetches a signed receipt from Headless Oracle |
| 3 | Ed25519 verify | Checks the cryptographic signature and 60s TTL |
| 4 | Status check | Routes to `execute` only if status is `OPEN` |

If **any** gate fails — invalid signature, expired receipt, CLOSED, HALTED, or UNKNOWN — the agent halts. UNKNOWN is never treated as permissive.

---

## Quick start

```bash
git clone https://github.com/LembaGang/safe-trading-agent-template
cd safe-trading-agent-template

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env — set ORACLE_API_KEY and optionally ANTHROPIC_API_KEY

python examples/demo_without_llm.py   # No LLM key needed
python examples/run_agent.py          # Full LangGraph agent
```

Get an API key at [headlessoracle.com](https://headlessoracle.com).

---

## Without an API key

The template falls back to `/v5/demo` (public endpoint, no auth, `receipt_mode=demo`). Signatures are real and verifiable. Use this for development and CI.

```bash
# No .env needed — just run:
python examples/demo_without_llm.py
```

---

## Supported exchanges

| MIC | Exchange | Timezone |
|-----|----------|----------|
| XNYS | New York Stock Exchange | America/New_York |
| XNAS | NASDAQ | America/New_York |
| XLON | London Stock Exchange | Europe/London |
| XJPX | Japan Exchange Group | Asia/Tokyo |
| XPAR | Euronext Paris | Europe/Paris |
| XHKG | Hong Kong Exchanges | Asia/Hong_Kong |
| XSES | Singapore Exchange | Asia/Singapore |

DST is handled automatically by the oracle (IANA timezone names, never hardcoded UTC offsets).

---

## The 4-step gate in plain Python

No LangGraph? The minimal pattern is four lines:

```python
from headless_oracle import OracleClient, verify

with OracleClient(api_key="ok_live_...") as client:
    receipt = client.get_status("XNYS")

result = verify(receipt, public_key="03dc27993a2c90...") # pin key for prod
if not result.valid:
    raise RuntimeError(f"Receipt invalid: {result.reason}")  # halt

if receipt["status"] != "OPEN":
    raise RuntimeError(f"Market is {receipt['status']} — halting")  # halt

# Market is OPEN and receipt is cryptographically verified — safe to trade
broker.submit_order(...)
```

See `examples/demo_without_llm.py` for the full version with error handling.

---

## Running the tests

```bash
pytest tests/ -v

# Skip live-API integration tests (offline only):
pytest tests/ -v -m "not integration"
```

The test suite uses a generated Ed25519 keypair — no live API calls needed for the unit tests.

---

## Project structure

```
safe-trading-agent-template/
├── agent/
│   ├── graph.py          # LangGraph StateGraph — the 4-gate topology
│   ├── state.py          # AgentState TypedDict
│   └── nodes/
│       ├── reasoning.py  # LLM pre-trade reasoning (Claude Haiku)
│       ├── oracle.py     # Fetch + Ed25519 verify oracle receipt
│       └── execution.py  # Execute (stub) + failsafe (halt) nodes
├── tests/
│   ├── conftest.py              # Test keypair + receipt fixtures
│   ├── test_oracle_verify.py    # Verification unit tests
│   └── test_graph_routing.py    # Full graph routing tests
└── examples/
    ├── run_agent.py         # Full LangGraph agent
    └── demo_without_llm.py  # Minimal gate demo, no LLM
```

---

## Integrating your brokerage

Replace the stub in `agent/nodes/execution.py`:

```python
def execution_node(state: AgentState) -> dict:
    # The oracle receipt in state["oracle_receipt"] is a signed attestation
    # of market state at this exact moment. Log it alongside every order
    # for audit trail and forensic debugging.

    order = broker.submit_order(          # ← your integration here
        symbol="AAPL",
        qty=100,
        side="buy",
        type="market",
    )
    ...
```

The receipt in `state["oracle_receipt"]` is cryptographically signed and portable — you can forward it to downstream agents or store it as proof that the market was OPEN at the time of the trade.

---

## Why cryptographic verification?

A plain API returning `{"status": "OPEN"}` can be faked, cached, replayed, or MITM'd. An Ed25519 signed receipt with a 60-second TTL cannot — any tampering invalidates the signature, and any replay fails the TTL check.

This matters when your agent has a funded wallet. A forged "OPEN" receipt during a circuit breaker can cause your bot to execute against a halted market. The verification step is the last line of defense.

The Headless Oracle public key is at `https://headlessoracle.com/v5/keys`. For production, pin it in your environment (`ORACLE_PUBLIC_KEY`) to eliminate one network round-trip per trade.

---

## Receipt portability (multi-agent patterns)

Signed receipts can be forwarded between agents:

```python
# Agent A fetches and verifies
receipt = client.get_status("XNYS")
assert verify(receipt).valid

# Agent A sends receipt to Agent B (e.g. via message queue)
message_queue.send({"oracle_receipt": receipt, "trade_intent": "..."})

# Agent B re-verifies before acting — never trusts Agent A's word alone
receipt = message["oracle_receipt"]
result = verify(receipt, public_key=ORACLE_PUBLIC_KEY)
if not result.valid or receipt["status"] != "OPEN":
    halt()
```

Each agent in a pipeline re-verifies. No agent trusts another agent's cached result.

---

## Resources

- [Headless Oracle API](https://headlessoracle.com)
- [API documentation](https://headlessoracle.com/docs)
- [Python SDK](https://github.com/LembaGang/headless-oracle-python)
- [JavaScript verify SDK](https://npmjs.com/package/@headlessoracle/verify)
- [DST exploit demo](https://github.com/LembaGang/dst-exploit-demo) — the bug this prevents

---

MIT License. Not financial advice.
