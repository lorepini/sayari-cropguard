"""Unit tests for src.water_balance.

Tests are self-contained: synthetic drivers are generated inline, no parquet
or external data required. All cases run in well under one second.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.water_balance import (
    DEFAULT_CROP_MIX,
    HIGH_DEMAND_MULTIPLIER,
    HOUSEHOLD_DEMAND_L_PER_DAY,
    PUMP_CAPACITY_L_PER_DAY,
    WaterBalanceParams,
    cross_probability,
    crop_demand_l_per_day,
    days_until_critical,
    forecast,
    seasonal_demand_multiplier,
    step,
    total_extraction_l_per_day,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_params() -> WaterBalanceParams:
    return WaterBalanceParams()


@pytest.fixture
def flat_drivers_14d() -> pd.DataFrame:
    """14 days of constant, neutral drivers — useful for monotonicity tests."""
    dates = pd.date_range("2026-05-01", periods=14, freq="D")
    return pd.DataFrame({
        "date": dates,
        "recharge_proxy_mm": [0.0] * 14,
        "local_rainfall_mm": [0.0] * 14,
        "extraction_l": [0.0] * 14,
        "oni_anom": [0.0] * 14,
        "et0_mm": [0.0] * 14,
    })


@pytest.fixture
def heavy_extraction_drivers_14d() -> pd.DataFrame:
    """14 days where extraction dominates — level should fall monotonically."""
    dates = pd.date_range("2026-05-01", periods=14, freq="D")
    return pd.DataFrame({
        "date": dates,
        "recharge_proxy_mm": [0.0] * 14,
        "local_rainfall_mm": [0.0] * 14,
        "extraction_l": [50_000.0] * 14,  # at pump cap, full extraction
        "oni_anom": [0.0] * 14,
        "et0_mm": [5.0] * 14,
    })


# ---------------------------------------------------------------------------
# seasonal_demand_multiplier
# ---------------------------------------------------------------------------

def test_seasonal_multiplier_high_demand_january_exact():
    """January is in HIGH_DEMAND_MONTHS, must return exactly 1.45."""
    assert seasonal_demand_multiplier(1) == 1.45
    assert seasonal_demand_multiplier(1) == HIGH_DEMAND_MULTIPLIER


def test_seasonal_multiplier_low_demand_july_exact():
    """July is NOT a high-demand month, must return exactly 1.0."""
    assert seasonal_demand_multiplier(7) == 1.0


def test_seasonal_multiplier_all_months_well_defined():
    """Every month 1..12 must return either 1.0 or 1.45 (no other values)."""
    for m in range(1, 13):
        v = seasonal_demand_multiplier(m)
        assert v in (1.0, 1.45), f"month {m} returned unexpected {v}"
    # Sanity: April (4) should be high, May (5) should be low.
    assert seasonal_demand_multiplier(4) == 1.45
    assert seasonal_demand_multiplier(5) == 1.0


# ---------------------------------------------------------------------------
# crop_demand_l_per_day
# ---------------------------------------------------------------------------

def test_crop_demand_happy_path_default_mix():
    """Default mix at typical ET0=4.5 mm/day should be near the NGO 30k baseline."""
    demand = crop_demand_l_per_day(et0_mm_per_day=4.5)
    assert demand > 0
    # The DEFAULT_CROP_MIX is calibrated to ~30k at ET0=4.5
    assert 20_000 <= demand <= 45_000


def test_crop_demand_empty_mix_returns_zero():
    """Edge: empty crop_mix yields zero demand."""
    assert crop_demand_l_per_day(et0_mm_per_day=4.5, crop_mix={}) == 0.0


def test_crop_demand_pump_capacity_ceiling():
    """Edge: enormous ET0 must still be capped at pump capacity."""
    huge_demand = crop_demand_l_per_day(et0_mm_per_day=10_000.0)
    assert huge_demand == PUMP_CAPACITY_L_PER_DAY


def test_crop_demand_pump_capacity_override_respected():
    """Custom pump_capacity_l_per_day must clamp the result."""
    custom_cap = 1_000.0
    capped = crop_demand_l_per_day(
        et0_mm_per_day=100.0, pump_capacity_l_per_day=custom_cap
    )
    assert capped == custom_cap


def test_crop_demand_unknown_crop_raises():
    """Crop missing from Kc / canopy tables (and overrides) raises KeyError."""
    with pytest.raises(KeyError):
        crop_demand_l_per_day(et0_mm_per_day=4.5, crop_mix={"unobtainium": 5})


def test_crop_demand_zero_count_skipped():
    """Crops with count <= 0 contribute nothing (not an error)."""
    demand = crop_demand_l_per_day(
        et0_mm_per_day=4.5, crop_mix={"maracuya": 0, "maiz": 0}
    )
    assert demand == 0.0


# ---------------------------------------------------------------------------
# total_extraction_l_per_day
# ---------------------------------------------------------------------------

def test_total_extraction_includes_household_in_low_season():
    """In low-demand month (July, mult=1.0), total = crops + 20k household, capped."""
    crops_only = crop_demand_l_per_day(et0_mm_per_day=4.5)
    total = total_extraction_l_per_day(et0_mm_per_day=4.5, month=7)
    expected = min(crops_only * 1.0 + HOUSEHOLD_DEMAND_L_PER_DAY, PUMP_CAPACITY_L_PER_DAY)
    assert total == pytest.approx(expected)
    # Households add ~20k on top of crops, so total should exceed crops_only.
    assert total > crops_only


def test_total_extraction_capped_at_pump_capacity():
    """Total can never exceed pump capacity, no matter how thirsty the crops."""
    total = total_extraction_l_per_day(et0_mm_per_day=10_000.0, month=1)
    assert total == PUMP_CAPACITY_L_PER_DAY


# ---------------------------------------------------------------------------
# step
# ---------------------------------------------------------------------------

def test_step_zero_drivers_returns_unchanged_level(default_params):
    """All-zero drivers => no level change."""
    h_new = step(
        h_prev_m=3.0,
        recharge_proxy_mm=0.0,
        local_rainfall_mm=0.0,
        extraction_l=0.0,
        oni_anom=0.0,
        et0_mm=0.0,
        params=default_params,
    )
    assert h_new == pytest.approx(3.0)


def test_step_extraction_decreases_level(default_params):
    """Positive extraction lowers the water level."""
    h_new = step(
        h_prev_m=3.0,
        recharge_proxy_mm=0.0,
        local_rainfall_mm=0.0,
        extraction_l=50_000.0,
        oni_anom=0.0,
        et0_mm=0.0,
        params=default_params,
    )
    assert h_new < 3.0


def test_step_rainfall_increases_level(default_params):
    """Local rainfall raises the level."""
    h_new = step(
        h_prev_m=3.0,
        recharge_proxy_mm=0.0,
        local_rainfall_mm=50.0,
        extraction_l=0.0,
        oni_anom=0.0,
        et0_mm=0.0,
        params=default_params,
    )
    assert h_new > 3.0


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------

def test_forecast_adds_predicted_column(flat_drivers_14d, default_params):
    """forecast() must return a DataFrame with `nivel_predicho_m` and same length."""
    fc = forecast(h0_m=3.0, drivers=flat_drivers_14d, params=default_params)
    assert "nivel_predicho_m" in fc.columns
    assert len(fc) == len(flat_drivers_14d)
    # Flat-zero drivers => level stays constant.
    assert fc["nivel_predicho_m"].nunique() == 1
    assert fc["nivel_predicho_m"].iloc[0] == pytest.approx(3.0)


def test_forecast_monotonic_decrease_with_heavy_extraction(
    heavy_extraction_drivers_14d, default_params
):
    """High extraction + zero rainfall => level must fall every step."""
    fc = forecast(
        h0_m=3.5, drivers=heavy_extraction_drivers_14d, params=default_params
    )
    levels = fc["nivel_predicho_m"].to_numpy()
    diffs = levels[1:] - levels[:-1]
    assert (diffs < 0).all(), f"expected strictly monotonic decrease, got diffs={diffs}"
    # And the final value is below the start value.
    assert levels[-1] < 3.5


def test_forecast_does_not_mutate_input(flat_drivers_14d, default_params):
    """forecast() must not mutate the caller's drivers DataFrame."""
    original_cols = list(flat_drivers_14d.columns)
    forecast(h0_m=3.0, drivers=flat_drivers_14d, params=default_params)
    assert list(flat_drivers_14d.columns) == original_cols
    assert "nivel_predicho_m" not in flat_drivers_14d.columns


# ---------------------------------------------------------------------------
# cross_probability
# ---------------------------------------------------------------------------

def _make_ensemble_matrix(member_levels: list[list[float]]) -> pd.DataFrame:
    """Helper: build a (date x member) matrix from per-member daily series."""
    n_days = len(member_levels[0])
    dates = pd.date_range("2026-05-01", periods=n_days, freq="D")
    return pd.DataFrame(
        {f"m{i}": series for i, series in enumerate(member_levels)},
        index=dates,
    )


def test_cross_probability_no_member_crosses_returns_zero():
    """Threshold below all trajectories => probability 0.0."""
    matrix = _make_ensemble_matrix([
        [3.0, 3.0, 3.0, 3.0],
        [2.9, 2.9, 2.9, 2.9],
        [3.1, 3.1, 3.1, 3.1],
    ])
    assert cross_probability(matrix, threshold_m=2.0, horizon_days=4) == 0.0


def test_cross_probability_all_members_cross_returns_one():
    """Threshold above all trajectories => probability 1.0."""
    matrix = _make_ensemble_matrix([
        [3.0, 2.9, 2.8, 2.7],
        [3.0, 2.95, 2.9, 2.85],
        [3.0, 2.9, 2.85, 2.8],
    ])
    assert cross_probability(matrix, threshold_m=5.0, horizon_days=4) == 1.0


def test_cross_probability_half_members_cross_returns_half():
    """Half the ensemble crosses => 0.5."""
    matrix = _make_ensemble_matrix([
        [3.0, 2.5, 2.0, 1.5],   # crosses 2.0 by day 3
        [3.0, 2.9, 2.8, 2.7],   # never crosses
        [3.0, 2.4, 2.0, 1.6],   # crosses
        [3.0, 2.95, 2.9, 2.85], # never crosses
    ])
    assert cross_probability(matrix, threshold_m=2.0, horizon_days=4) == 0.5


def test_cross_probability_horizon_zero_returns_zero():
    """horizon_days <= 0 => 0.0 by contract."""
    matrix = _make_ensemble_matrix([[1.0, 1.0]])
    assert cross_probability(matrix, threshold_m=2.0, horizon_days=0) == 0.0


def test_cross_probability_empty_matrix_returns_zero():
    """Empty matrix => 0.0 by contract."""
    assert cross_probability(pd.DataFrame(), threshold_m=2.0, horizon_days=4) == 0.0


# ---------------------------------------------------------------------------
# days_until_critical
# ---------------------------------------------------------------------------

def test_days_until_critical_returns_none_when_never_crossed():
    """Forecast that always sits above threshold => None."""
    df = pd.DataFrame({
        "date": pd.date_range("2026-05-01", periods=10, freq="D"),
        "nivel_predicho_m": [3.0] * 10,
    })
    assert days_until_critical(df, threshold_m=2.0) is None


def test_days_until_critical_counts_days_correctly():
    """Forecast that crosses on day 5 (index 4) => returns 4."""
    df = pd.DataFrame({
        "date": pd.date_range("2026-05-01", periods=10, freq="D"),
        "nivel_predicho_m": [3.0, 3.0, 3.0, 3.0, 1.5, 1.4, 1.3, 1.2, 1.1, 1.0],
    })
    assert days_until_critical(df, threshold_m=2.0) == 4


def test_days_until_critical_custom_column():
    """Should respect a custom column name."""
    df = pd.DataFrame({
        "date": pd.date_range("2026-05-01", periods=5, freq="D"),
        "level_alt": [3.0, 2.9, 1.5, 1.4, 1.3],
    })
    assert days_until_critical(df, threshold_m=2.0, column="level_alt") == 2


# ---------------------------------------------------------------------------
# Sanity: DEFAULT_CROP_MIX matches NGO 30k crop baseline at ET0=4.5
# ---------------------------------------------------------------------------

def test_default_crop_mix_matches_ngo_baseline():
    """Documented invariant: default mix at ET0=4.5 yields ~30k L/day."""
    demand = crop_demand_l_per_day(
        et0_mm_per_day=4.5, crop_mix=DEFAULT_CROP_MIX
    )
    # Tolerate a wide band — this is calibration intent, not strict equality.
    assert 25_000 <= demand <= 35_000
