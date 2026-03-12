"""
Capital Loss Simulator — The Phantom Hour
─────────────────────────────────────────
Streamlit application. Run with:

    streamlit run simulator/app.py

No API key required. The simulation is fully offline. Optionally set
ORACLE_API_KEY in .env to fetch a live oracle receipt for the Oracle Bot panel.
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
import plotly.graph_objects as go

# Load .env from repo root (best-effort; not required for the simulation)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from simulator.model import (
    TradeScenario,
    simulate,
    build_phantom_hour_timeline,
    phantom_trade_times,
    PHANTOM_SCENARIO_DATE,
)


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Capital Loss Simulator: The Phantom Hour",
    page_icon="💸",
    layout="wide",
)


# ── Sidebar — simulation parameters ──────────────────────────────────────────

with st.sidebar:
    st.header("Simulation Parameters")

    asset = st.selectbox(
        "Asset",
        ["SPY", "AAPL", "QQQ", "NVDA", "BTC"],
        index=0,
    )

    price_per_unit = st.number_input(
        "Asset price (USD)",
        min_value=1.0,
        max_value=100_000.0,
        value=450.0,
        step=1.0,
        format="%.2f",
    )

    position_size = st.slider(
        "Position size (shares / units)",
        min_value=100,
        max_value=100_000,
        value=10_000,
        step=100,
    )

    n_phantom_trades = st.slider(
        "Orders fired in phantom hour",
        min_value=1,
        max_value=20,
        value=5,
        help="How many orders the naive bot submits during the 20:00–21:00 UTC phantom window.",
    )

    st.divider()
    st.subheader("Cost assumptions (bps)")
    st.caption("1 basis point = 0.01% of position value")

    after_hours_spread = st.slider(
        "After-hours spread (bps)",
        min_value=5,
        max_value=100,
        value=30,
        help="Bid-ask spread in ECNs and dark pools after NYSE close. Typically 10–30× wider than intraday.",
    )

    mev_extraction = st.slider(
        "MEV / adverse selection (bps)",
        min_value=0,
        max_value=50,
        value=15,
        help="Cost of dark-pool information leakage, front-running, and sandwich attacks.",
    )

    gap_risk = st.slider(
        "Overnight gap risk (bps)",
        min_value=0,
        max_value=200,
        value=50,
        help="Expected adverse price gap at next-day open on any un-exited position.",
    )


# ── Run simulation ────────────────────────────────────────────────────────────

scenario = TradeScenario(
    asset=asset,
    price_per_unit=price_per_unit,
    position_size=position_size,
    n_phantom_trades=n_phantom_trades,
    after_hours_spread_bps=float(after_hours_spread),
    mev_extraction_bps=float(mev_extraction),
    gap_risk_bps=float(gap_risk),
)

output = simulate(scenario)


# ── Header ────────────────────────────────────────────────────────────────────

st.title("💸 Capital Loss Simulator: The Phantom Hour")
st.markdown(
    f"""
**Scenario:** NYSE · {asset} · {PHANTOM_SCENARIO_DATE} · Summer (EDT, UTC‑4)

A naive bot hardcodes **UTC‑5 (EST)** as the Eastern offset year-round.
During summer, the correct offset is **UTC‑4 (EDT)**.
This 1-hour error creates a *phantom hour* where the bot believes the market is
**OPEN** but NYSE has already halted. Every order fired in that window
executes in after-hours dark pools — wide spreads, MEV exposure, gap risk.

The **Headless Oracle bot** fetches a cryptographically signed receipt, verifies
the Ed25519 signature, reads `status = "CLOSED"`, and halts before the first order leaves the process.
""",
    unsafe_allow_html=False,
)


# ── Timeline chart ────────────────────────────────────────────────────────────

st.header("The Phantom Hour: What the Naive Bot Sees vs. Reality")

timeline = build_phantom_hour_timeline()
times           = [p.utc_time for p in timeline]
actual_status   = [p.actual_open for p in timeline]
naive_status    = [p.naive_belief for p in timeline]
trade_times     = phantom_trade_times(n_phantom_trades)

fig = go.Figure()

# Actual market status — ground truth
fig.add_trace(go.Scatter(
    x=times,
    y=actual_status,
    mode="lines",
    name="Actual NYSE Status",
    line=dict(color="#22c55e", width=3),
    fill="tozeroy",
    fillcolor="rgba(34, 197, 94, 0.15)",
))

# Naive bot's belief
fig.add_trace(go.Scatter(
    x=times,
    y=naive_status,
    mode="lines",
    name="Naive Bot's Belief",
    line=dict(color="#f97316", width=3, dash="dash"),
    fill="tozeroy",
    fillcolor="rgba(249, 115, 22, 0.08)",
))

# Highlight the phantom hour region
fig.add_vrect(
    x0="20:00", x1="21:00",
    fillcolor="rgba(239, 68, 68, 0.12)",
    layer="below",
    line_width=0,
    annotation_text="Phantom Hour",
    annotation_position="top left",
    annotation_font=dict(color="#ef4444", size=13),
)

# Real close marker
fig.add_vline(
    x="20:00",
    line_color="#22c55e",
    line_dash="dot",
    line_width=2,
    annotation_text="Real close 20:00 UTC",
    annotation_position="top right",
    annotation_font=dict(color="#22c55e", size=11),
)

# Trade execution markers (naive bot's phantom orders)
if trade_times:
    fig.add_trace(go.Scatter(
        x=trade_times,
        y=[1.05] * len(trade_times),
        mode="markers+text",
        marker=dict(symbol="triangle-down", size=16, color="#ef4444"),
        text=["ORDER"] * len(trade_times),
        textposition="top center",
        textfont=dict(size=9, color="#ef4444"),
        name="Naive Bot Orders (after close)",
    ))

fig.update_layout(
    xaxis_title="UTC Time",
    yaxis=dict(
        title="Market Status",
        tickvals=[0, 1],
        ticktext=["CLOSED", "OPEN"],
        range=[-0.1, 1.3],
    ),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=380,
    margin=dict(t=60, b=40, l=60, r=40),
    plot_bgcolor="#0e1117",
    paper_bgcolor="#0e1117",
    font=dict(color="#fafafa"),
)

st.plotly_chart(fig, use_container_width=True)


# ── Side-by-side bot comparison ───────────────────────────────────────────────

st.header("Side-by-Side Execution Comparison")

col_naive, col_oracle = st.columns(2, gap="large")

with col_naive:
    st.subheader("❌ Naive Bot — pytz / hardcoded offset")

    st.code(
        """\
import pytz
from datetime import datetime

# Bug: always uses EST (-5), even in summer (should be EDT -4)
eastern = pytz.timezone('US/Eastern')
now_utc = datetime.utcnow()

# On 2024-07-15 at 20:30 UTC:
#   now_utc.replace(tzinfo=pytz.utc)
#   .astimezone(eastern) → 15:30 EST (WRONG)
#   Naive bot sees 15:30 → market is "OPEN" ← BUG

# Naive bot fires orders into a halted market.
broker.submit_order("SPY", qty=position_size, side="buy")
""",
        language="python",
    )

    naive = output.naive_bot
    st.markdown("**What happened:**")
    st.error(naive.verdict)

    st.markdown("**Cost breakdown:**")
    st.table({
        "Component": [
            f"After-hours spread ({after_hours_spread} bps × {n_phantom_trades} trades)",
            f"MEV / adverse selection ({mev_extraction} bps × {n_phantom_trades} trades)",
            f"Overnight gap risk ({gap_risk} bps on ${naive.position_value:,.0f})",
            "**TOTAL LOSS**",
        ],
        "Amount": [
            f"${naive.position_value * (after_hours_spread / 10000) * n_phantom_trades:,.2f}",
            f"${naive.position_value * (mev_extraction / 10000) * n_phantom_trades:,.2f}",
            f"${naive.gap_risk_cost:,.2f}",
            f"**${naive.total_loss:,.2f}**",
        ],
    })

    st.metric(
        label="Simulated Loss",
        value=f"${naive.total_loss:,.2f}",
        delta=f"-{naive.loss_pct:.2f}% of position",
        delta_color="inverse",
    )


with col_oracle:
    st.subheader("✅ Oracle Bot — Headless Oracle SDK")

    st.code(
        """\
from headless_oracle import OracleClient, verify

# No timezone math. No UTC offset arithmetic.
with OracleClient(api_key=ORACLE_API_KEY) as client:
    receipt = client.get_status("XNYS")

result = verify(receipt, public_key=ORACLE_PUBLIC_KEY)
if not result.valid:
    halt(result.reason)   # EXPIRED / INVALID_SIGNATURE

# At 20:30 UTC on 2024-07-15:
# receipt["status"] == "CLOSED"  ← cryptographically attested
# Ed25519 signature: valid  ✓
# TTL: 58 seconds remaining  ✓

if receipt["status"] != "OPEN":
    halt()  # ← triggered here. No order placed.
""",
        language="python",
    )

    oracle = output.oracle_bot
    st.markdown("**What happened:**")
    st.success(oracle.verdict)

    # Show a fake oracle receipt for illustration
    st.markdown("**Oracle receipt (illustrative):**")
    st.json({
        "status": "CLOSED",
        "mic": "XNYS",
        "issued_at": "2024-07-15T20:30:01Z",
        "expires_at": "2024-07-15T20:31:01Z",
        "source": "SCHEDULE",
        "receipt_mode": "live",
        "schema_version": "v5.0",
        "issuer": "headlessoracle.com",
        "signature": "ed25519:a3f8...c291  ✓ verified",
    })

    st.metric(
        label="Simulated Loss",
        value="$0.00",
        delta="Halted before execution",
        delta_color="off",
    )


# ── The damage number ─────────────────────────────────────────────────────────

st.divider()
st.header("💸 Total Simulated Financial Damage")

dmg_col, saved_col, pct_col = st.columns(3)
with dmg_col:
    st.metric(
        "Naive bot loss",
        f"${output.naive_bot.total_loss:,.2f}",
        help="After-hours execution cost + overnight gap risk",
    )
with saved_col:
    st.metric(
        "Saved by oracle",
        f"${output.saved_by_oracle:,.2f}",
        delta="Oracle halted — $0 loss",
        delta_color="normal",
    )
with pct_col:
    st.metric(
        "Loss as % of position",
        f"{output.naive_bot.loss_pct:.3f}%",
        help=f"On a ${output.naive_bot.position_value:,.0f} position",
    )

st.caption(
    f"Position: {position_size:,} × {asset} @ ${price_per_unit:.2f} = "
    f"${output.naive_bot.position_value:,.2f}. "
    f"Assumptions: {after_hours_spread}bps after-hours spread, "
    f"{mev_extraction}bps MEV, {gap_risk}bps gap risk. "
    f"Adjust sliders to model your scenario."
)


# ── The fix ───────────────────────────────────────────────────────────────────

st.divider()
st.header("The Fix: 4 Lines of Python")
st.markdown(
    "Replace all timezone math with a cryptographically signed receipt. "
    "No DST. No hardcoded offsets. No prayer."
)

st.code(
    """\
pip install headless-oracle
""",
    language="bash",
)

st.code(
    """\
from headless_oracle import OracleClient, verify

with OracleClient(api_key="ok_live_...") as client:
    receipt = client.get_status("XNYS")   # signed Ed25519 receipt, 60s TTL

result = verify(receipt, public_key="03dc27993a2c90...")  # pin key for prod
if not result.valid:
    raise RuntimeError(f"Receipt invalid: {result.reason}")  # HALT

if receipt["status"] != "OPEN":
    raise RuntimeError(f"Market is {receipt['status']} — halting")  # HALT

# Cryptographically verified OPEN. Safe to trade.
broker.submit_order(...)
""",
    language="python",
)

st.markdown(
    "Free demo endpoint (no API key needed): "
    "[headlessoracle.com](https://headlessoracle.com) · "
    "LangGraph template: "
    "[github.com/LembaGang/safe-trading-agent-template](https://github.com/LembaGang/safe-trading-agent-template)"
)
