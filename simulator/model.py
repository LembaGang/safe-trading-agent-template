"""
model.py — Pure simulation model for the Capital Loss Simulator.

All functions are side-effect-free (no I/O, no Streamlit). Tested in
tests/test_simulator_model.py. The Streamlit app (app.py) calls these
functions and renders their output.

The Phantom Hour Bug
────────────────────
A naive bot computes market hours using a hardcoded UTC offset. During
Daylight Saving Time (DST), the correct offset for US Eastern Time shifts
between UTC-5 (EST, winter) and UTC-4 (EDT, summer). A bot that hard-codes
UTC-5 year-round will believe the NYSE closes at 21:00 UTC — but during
summer (EDT), the market actually closes at 20:00 UTC.

This creates a 60-minute window where the naive bot believes the market is
OPEN but the exchange has already halted. Any orders fired in that window
execute in after-hours dark pools: wide spreads, MEV exposure, gap risk.

The Oracle Bot detects `status = "CLOSED"` in the signed receipt and halts
before the first phantom order is placed. Loss: $0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


# ── DST scenario data ─────────────────────────────────────────────────────────

# The canonical "Phantom Hour" scenario: a summer trading day where a bot
# using UTC-5 (EST) year-round fires 60 minutes after real market close.
PHANTOM_SCENARIO_DATE = "2024-07-15"          # Summer, NYSE in EDT (UTC-4)
REAL_CLOSE_UTC   = "2024-07-15T20:00:00Z"    # 4:00 PM EDT = 20:00 UTC
NAIVE_CLOSE_UTC  = "2024-07-15T21:00:00Z"    # Naive bot thinks close = 21:00 UTC (EST offset)
REAL_OPEN_UTC    = "2024-07-15T13:30:00Z"    # 9:30 AM EDT = 13:30 UTC
NAIVE_OPEN_UTC   = "2024-07-15T14:30:00Z"    # Naive bot thinks open = 14:30 UTC

PHANTOM_START_UTC = REAL_CLOSE_UTC            # Phantom hour starts at real close
PHANTOM_END_UTC   = NAIVE_CLOSE_UTC           # Phantom hour ends at naive bot's "close"


# ── Input / output models ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class TradeScenario:
    """User-configurable parameters for the loss simulation."""

    asset: str                      # Display name (e.g. "SPY")
    price_per_unit: float           # Current asset price in USD
    position_size: int              # Shares / units per trade
    n_phantom_trades: int           # How many orders the naive bot fires in the phantom hour

    # Cost assumptions (all in basis points = 1/100th of 1%)
    regular_spread_bps: float = 1.0       # Intraday spread for a liquid instrument
    after_hours_spread_bps: float = 30.0  # After-hours spreads are 10-30× wider
    mev_extraction_bps: float = 15.0      # MEV / dark-pool adverse selection
    gap_risk_bps: float = 50.0            # Overnight gap risk on un-exited position


@dataclass(frozen=True)
class TradeResult:
    """Financial outcome for one bot's execution strategy."""

    bot_label: str
    position_value: float

    # Per-trade costs
    cost_per_trade: float
    n_trades: int

    # Aggregate
    total_execution_cost: float
    gap_risk_cost: float
    total_loss: float
    loss_pct: float          # total_loss / position_value × 100

    # Human-readable verdict
    executed: bool           # True if orders were placed, False if halted
    verdict: str             # One-line outcome description


@dataclass(frozen=True)
class SimulationOutput:
    """Full output from a simulation run."""

    naive_bot: TradeResult
    oracle_bot: TradeResult
    saved_by_oracle: float   # naive_bot.total_loss − oracle_bot.total_loss (always ≥ 0)
    scenario: TradeScenario


# ── Computation ───────────────────────────────────────────────────────────────

def _bps_to_fraction(bps: float) -> float:
    return bps / 10_000.0


def simulate(scenario: TradeScenario) -> SimulationOutput:
    """
    Run the Phantom Hour simulation and return financial outcomes for both bots.

    Naive bot: executes n_phantom_trades orders in the phantom hour (after real
    market close but before naive bot's computed close). Each order incurs:
      - after_hours_spread (wider bid-ask in ECNs/dark pools)
      - mev_extraction (adverse selection / sandwich attack cost)
    After the phantom hour, the un-exited position carries overnight gap risk.

    Oracle bot: receives a signed CLOSED receipt, verifies it, and halts.
    Zero orders placed, zero execution cost, zero gap risk.
    """
    position_value = scenario.price_per_unit * scenario.position_size

    # ── Naive bot costs ────────────────────────────────────────────────────────
    naive_cost_per_trade = position_value * (
        _bps_to_fraction(scenario.after_hours_spread_bps)
        + _bps_to_fraction(scenario.mev_extraction_bps)
    )
    naive_total_execution = naive_cost_per_trade * scenario.n_phantom_trades
    naive_gap_risk = position_value * _bps_to_fraction(scenario.gap_risk_bps)
    naive_total_loss = naive_total_execution + naive_gap_risk

    naive_result = TradeResult(
        bot_label="Naive Bot",
        position_value=position_value,
        cost_per_trade=naive_cost_per_trade,
        n_trades=scenario.n_phantom_trades,
        total_execution_cost=naive_total_execution,
        gap_risk_cost=naive_gap_risk,
        total_loss=naive_total_loss,
        loss_pct=naive_total_loss / position_value * 100 if position_value > 0 else 0.0,
        executed=True,
        verdict=(
            f"Executed {scenario.n_phantom_trades} order(s) into dark pools after market close. "
            f"Incurred {scenario.after_hours_spread_bps:.0f}bps after-hours spread + "
            f"{scenario.mev_extraction_bps:.0f}bps MEV extraction per trade."
        ),
    )

    # ── Oracle bot costs ───────────────────────────────────────────────────────
    oracle_result = TradeResult(
        bot_label="Oracle Bot",
        position_value=position_value,
        cost_per_trade=0.0,
        n_trades=0,
        total_execution_cost=0.0,
        gap_risk_cost=0.0,
        total_loss=0.0,
        loss_pct=0.0,
        executed=False,
        verdict=(
            "Oracle receipt returned status=CLOSED. Ed25519 signature verified. "
            "All orders halted before execution. No exposure."
        ),
    )

    return SimulationOutput(
        naive_bot=naive_result,
        oracle_bot=oracle_result,
        saved_by_oracle=naive_total_loss,
        scenario=scenario,
    )


# ── Timeline data for the visualisation ──────────────────────────────────────

@dataclass(frozen=True)
class TimelinePoint:
    utc_time: str    # ISO-8601 UTC timestamp
    actual_open: int   # 1 = market open, 0 = closed (ground truth)
    naive_belief: int  # 1 = naive bot thinks open, 0 = thinks closed


def build_phantom_hour_timeline() -> list[TimelinePoint]:
    """
    Generate minute-resolution timeline data for the Phantom Hour chart.

    Window: 19:00 UTC to 21:30 UTC on the scenario date.
    Real market close: 20:00 UTC.
    Naive bot's computed close: 21:00 UTC (UTC-5 hardcoded).
    """
    base = datetime(2024, 7, 15, 19, 0, 0, tzinfo=timezone.utc)
    real_close = datetime(2024, 7, 15, 20, 0, 0, tzinfo=timezone.utc)
    naive_close = datetime(2024, 7, 15, 21, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 7, 15, 21, 30, 0, tzinfo=timezone.utc)

    points: list[TimelinePoint] = []
    current = base
    while current <= end:
        actual = 1 if current < real_close else 0
        naive = 1 if current < naive_close else 0
        points.append(TimelinePoint(
            utc_time=current.strftime("%H:%M"),
            actual_open=actual,
            naive_belief=naive,
        ))
        current += timedelta(minutes=1)

    return points


def phantom_trade_times(n_trades: int) -> list[str]:
    """
    Evenly-spaced UTC times at which the naive bot fires orders in the phantom hour.

    The phantom hour runs 20:00–21:00 UTC. Trades are spread across this window.
    """
    if n_trades <= 0:
        return []
    start = datetime(2024, 7, 15, 20, 5, 0, tzinfo=timezone.utc)
    end   = datetime(2024, 7, 15, 20, 55, 0, tzinfo=timezone.utc)
    if n_trades == 1:
        return [start.strftime("%H:%M")]
    delta = (end - start) / (n_trades - 1)
    return [
        (start + delta * i).strftime("%H:%M")
        for i in range(n_trades)
    ]
