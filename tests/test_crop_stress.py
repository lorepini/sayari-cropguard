"""Unit tests for src.crop_stress.

All inputs are synthesized inline — no parquet, no network.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.crop_stress import (
    DEFICIT_FRACTION_THRESHOLD,
    HEAT_HARMFUL_C,
    HEAT_THRESHOLD_C,
    CropStressSummary,
    crop_stress_forecast,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cool_low_et_forecast() -> pd.DataFrame:
    """14 cool days with low ET0 — no heat stress, no supply stress expected."""
    return pd.DataFrame({
        "date": pd.date_range("2026-06-01", periods=14, freq="D"),
        "tmax_c": [25.0] * 14,
        "et0_mm": [3.0] * 14,
    })


@pytest.fixture
def hot_harmful_forecast() -> pd.DataFrame:
    """14 days of harmful heat (>35 C) — heat-driven stress on every day."""
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=14, freq="D"),
        "tmax_c": [38.0] * 14,
        "et0_mm": [6.0] * 14,
    })


@pytest.fixture
def extreme_et_forecast() -> pd.DataFrame:
    """14 days with absurd ET0 — guarantees crop_total > supply cap, supply stress."""
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=14, freq="D"),
        "tmax_c": [32.0] * 14,           # heat-day but not heat-harmful
        "et0_mm": [50.0] * 14,           # absurdly high to force shortfall
    })


# ---------------------------------------------------------------------------
# Output shape & happy path
# ---------------------------------------------------------------------------

def test_output_shape_and_columns(cool_low_et_forecast):
    per_day, summaries = crop_stress_forecast(cool_low_et_forecast)
    expected_cols = {
        "date", "tmax_c", "et0_mm",
        "total_demand_l", "crop_supply_cap_l", "supplied_l", "deficit_l",
        "heat_day", "heat_harmful", "supply_stress", "stress_day",
    }
    assert expected_cols.issubset(per_day.columns)
    assert len(per_day) == len(cool_low_et_forecast)
    assert isinstance(summaries, list)
    assert all(isinstance(s, CropStressSummary) for s in summaries)
    # Default mix has 3 crops with positive count.
    assert len(summaries) == 3


def test_no_stress_under_cool_calm_conditions(cool_low_et_forecast):
    """Cool days (<30 C) with low ET0 in low-demand season should yield no stress days."""
    per_day, summaries = crop_stress_forecast(cool_low_et_forecast)
    assert (~per_day["heat_harmful"]).all()
    assert (~per_day["heat_day"]).all()  # 25 C < 30 C threshold
    assert (per_day["deficit_l"] <= 0.001).all()  # tolerance for FP
    assert (~per_day["stress_day"]).all()
    assert all(s.stress_days == 0 for s in summaries)
    assert all(s.peak_stress_reason == "none" for s in summaries)


# ---------------------------------------------------------------------------
# Heat-harmful path
# ---------------------------------------------------------------------------

def test_heat_harmful_flags_every_day_and_marks_stress(hot_harmful_forecast):
    """tmax > 35 C => heat_harmful, stress_day, summaries report heat_harmful peak."""
    per_day, summaries = crop_stress_forecast(hot_harmful_forecast)
    assert per_day["heat_harmful"].all()
    assert per_day["heat_day"].all()  # 38 > 30 too
    assert per_day["stress_day"].all()
    # Every crop should report stress_days == 14 because heat_harmful is system-wide.
    assert all(s.stress_days == len(hot_harmful_forecast) for s in summaries)
    # At least one crop's peak reason should be heat_harmful (it dominates).
    assert any(s.peak_stress_reason == "heat_harmful" for s in summaries)


# ---------------------------------------------------------------------------
# Supply stress path
# ---------------------------------------------------------------------------

def test_supply_stress_when_demand_exceeds_cap(extreme_et_forecast):
    """Extreme ET0 + January (high-demand multiplier) forces deficit > 0."""
    per_day, summaries = crop_stress_forecast(extreme_et_forecast)
    assert (per_day["deficit_l"] > 0).all()
    assert per_day["supply_stress"].all()
    # Sum of supplied_l per day must equal crop_supply_cap_l (the proportional
    # allocator should saturate the cap when crop_total > cap).
    cap = per_day["crop_supply_cap_l"].iloc[0]
    assert (per_day["supplied_l"].round(3) == round(cap, 3)).all()


# ---------------------------------------------------------------------------
# Crop-mix override + custom pump cap
# ---------------------------------------------------------------------------

def test_custom_crop_mix_only_returns_those_crops(cool_low_et_forecast):
    """Passing a single-crop mix yields exactly one summary."""
    per_day, summaries = crop_stress_forecast(
        cool_low_et_forecast, crop_mix={"maracuya": 100}
    )
    assert len(summaries) == 1
    assert summaries[0].crop == "maracuya"
    # avg_daily_demand_l > 0 since count > 0 and ET0 > 0.
    assert summaries[0].avg_daily_demand_l > 0


def test_threshold_constants_are_floats():
    """Sanity that constants are exposed and have expected values."""
    assert HEAT_THRESHOLD_C == 30.0
    assert HEAT_HARMFUL_C == 35.0
    assert 0 < DEFICIT_FRACTION_THRESHOLD < 1
