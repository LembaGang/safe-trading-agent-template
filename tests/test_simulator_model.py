"""
Unit tests for the Capital Loss Simulator pure computation model.

All tests are offline and side-effect-free — no Streamlit, no network calls.
Tests cover:
  1. simulate() financial calculations
  2. Fail-closed oracle property: oracle bot always produces $0 loss
  3. Loss monotonicity (more orders / higher spread → more loss)
  4. build_phantom_hour_timeline() data structure
  5. phantom_trade_times() distribution
"""

from __future__ import annotations

import pytest

from simulator.model import (
    TradeScenario,
    simulate,
    build_phantom_hour_timeline,
    phantom_trade_times,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _scenario(**overrides) -> TradeScenario:
    """Base scenario with sensible defaults. Override any field via kwargs."""
    defaults = dict(
        asset="SPY",
        price_per_unit=450.0,
        position_size=10_000,
        n_phantom_trades=5,
        regular_spread_bps=1.0,
        after_hours_spread_bps=30.0,
        mev_extraction_bps=15.0,
        gap_risk_bps=50.0,
    )
    defaults.update(overrides)
    return TradeScenario(**defaults)


# ── 1. Oracle bot is always $0 ────────────────────────────────────────────────

class TestOracleBotAlwaysZeroLoss:
    def test_oracle_loss_is_zero(self):
        output = simulate(_scenario())
        assert output.oracle_bot.total_loss == 0.0

    def test_oracle_execution_cost_is_zero(self):
        output = simulate(_scenario())
        assert output.oracle_bot.total_execution_cost == 0.0

    def test_oracle_gap_risk_is_zero(self):
        output = simulate(_scenario())
        assert output.oracle_bot.gap_risk_cost == 0.0

    def test_oracle_executed_is_false(self):
        """Oracle bot must not place any orders."""
        output = simulate(_scenario())
        assert output.oracle_bot.executed is False

    def test_oracle_loss_pct_is_zero(self):
        output = simulate(_scenario())
        assert output.oracle_bot.loss_pct == 0.0

    def test_saved_by_oracle_equals_naive_loss(self):
        """saved_by_oracle should exactly equal the naive bot's loss."""
        output = simulate(_scenario())
        assert output.saved_by_oracle == output.naive_bot.total_loss


# ── 2. Naive bot loss is positive ────────────────────────────────────────────

class TestNaiveBotLossIsPositive:
    def test_naive_total_loss_positive(self):
        output = simulate(_scenario())
        assert output.naive_bot.total_loss > 0.0

    def test_naive_executed_is_true(self):
        output = simulate(_scenario())
        assert output.naive_bot.executed is True

    def test_naive_loss_pct_positive(self):
        output = simulate(_scenario())
        assert output.naive_bot.loss_pct > 0.0

    def test_position_value_correct(self):
        output = simulate(_scenario(price_per_unit=100.0, position_size=1000))
        assert output.naive_bot.position_value == 100_000.0


# ── 3. Zero-position edge case ────────────────────────────────────────────────

class TestZeroPosition:
    def test_zero_position_zero_loss(self):
        output = simulate(_scenario(position_size=0))
        assert output.naive_bot.total_loss == 0.0
        assert output.oracle_bot.total_loss == 0.0

    def test_zero_position_zero_pct(self):
        output = simulate(_scenario(position_size=0))
        assert output.naive_bot.loss_pct == 0.0


# ── 4. Loss monotonicity ──────────────────────────────────────────────────────

class TestLossMonotonicity:
    def test_more_trades_more_loss(self):
        low  = simulate(_scenario(n_phantom_trades=1))
        high = simulate(_scenario(n_phantom_trades=10))
        assert high.naive_bot.total_loss > low.naive_bot.total_loss

    def test_higher_spread_more_loss(self):
        low  = simulate(_scenario(after_hours_spread_bps=10.0))
        high = simulate(_scenario(after_hours_spread_bps=80.0))
        assert high.naive_bot.total_execution_cost > low.naive_bot.total_execution_cost

    def test_higher_mev_more_loss(self):
        low  = simulate(_scenario(mev_extraction_bps=5.0))
        high = simulate(_scenario(mev_extraction_bps=40.0))
        assert high.naive_bot.total_execution_cost > low.naive_bot.total_execution_cost

    def test_higher_gap_risk_more_loss(self):
        low  = simulate(_scenario(gap_risk_bps=10.0))
        high = simulate(_scenario(gap_risk_bps=100.0))
        assert high.naive_bot.gap_risk_cost > low.naive_bot.gap_risk_cost

    def test_larger_position_more_loss(self):
        small = simulate(_scenario(position_size=100))
        large = simulate(_scenario(position_size=100_000))
        assert large.naive_bot.total_loss > small.naive_bot.total_loss

    def test_loss_scales_linearly_with_position(self):
        s1 = simulate(_scenario(position_size=1_000))
        s2 = simulate(_scenario(position_size=10_000))
        # 10× position should produce ~10× loss (same % costs)
        assert abs(s2.naive_bot.total_loss / s1.naive_bot.total_loss - 10.0) < 0.01

    def test_naive_always_worse_than_oracle(self):
        output = simulate(_scenario())
        assert output.naive_bot.total_loss > output.oracle_bot.total_loss

    def test_saved_by_oracle_always_nonnegative(self):
        output = simulate(_scenario())
        assert output.saved_by_oracle >= 0.0


# ── 5. Timeline data structure ────────────────────────────────────────────────

class TestTimeline:
    def test_timeline_covers_full_window(self):
        points = build_phantom_hour_timeline()
        times = [p.utc_time for p in points]
        assert "19:00" in times
        assert "21:30" in times

    def test_before_real_close_market_is_open(self):
        points = build_phantom_hour_timeline()
        point_1930 = next(p for p in points if p.utc_time == "19:30")
        assert point_1930.actual_open == 1
        assert point_1930.naive_belief == 1

    def test_phantom_hour_naive_open_actual_closed(self):
        """Between 20:00 and 21:00 UTC: actual=CLOSED, naive=OPEN."""
        points = build_phantom_hour_timeline()
        point_2030 = next(p for p in points if p.utc_time == "20:30")
        assert point_2030.actual_open == 0    # Real market is CLOSED
        assert point_2030.naive_belief == 1   # Naive bot thinks OPEN

    def test_after_naive_close_both_closed(self):
        """After 21:00 UTC: both actual and naive belief are CLOSED."""
        points = build_phantom_hour_timeline()
        point_2115 = next(p for p in points if p.utc_time == "21:15")
        assert point_2115.actual_open == 0
        assert point_2115.naive_belief == 0

    def test_real_close_at_2000(self):
        """At 20:00 UTC exactly, the actual market should be CLOSED."""
        points = build_phantom_hour_timeline()
        point_2000 = next(p for p in points if p.utc_time == "20:00")
        assert point_2000.actual_open == 0

    def test_timeline_has_no_gaps(self):
        """Timeline should be minute-resolution with no missing steps."""
        points = build_phantom_hour_timeline()
        # 19:00 to 21:30 = 150 minutes + 1 = 151 points
        assert len(points) == 151


# ── 6. phantom_trade_times() ─────────────────────────────────────────────────

class TestPhantomTradeTimes:
    def test_zero_trades_returns_empty(self):
        assert phantom_trade_times(0) == []

    def test_one_trade_returns_single_time(self):
        times = phantom_trade_times(1)
        assert len(times) == 1

    def test_n_trades_returns_n_times(self):
        for n in [1, 3, 5, 10]:
            assert len(phantom_trade_times(n)) == n

    def test_trades_within_phantom_hour(self):
        """All trade times should fall within the 20:00–21:00 UTC window."""
        times = phantom_trade_times(10)
        for t in times:
            hour, minute = map(int, t.split(":"))
            assert hour == 20, f"Expected hour 20, got {t}"
            assert 0 <= minute <= 59

    def test_negative_n_returns_empty(self):
        assert phantom_trade_times(-1) == []
