"""Unit tests for src.calibration.attach_extraction_profile.

Tests are inline-synthetic; no Excel / parquet dependency.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.calibration import attach_extraction_profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_drivers_2y() -> pd.DataFrame:
    """~24 months of daily driver dates, drivers themselves don't matter here."""
    dates = pd.date_range("2022-06-01", "2024-06-01", freq="D")
    n = len(dates)
    return pd.DataFrame({
        "date": dates,
        "recharge_proxy_mm": [0.0] * n,
        "local_rainfall_mm": [0.0] * n,
        "et0_mm": [0.0] * n,
        "oni_anom": [0.0] * n,
    })


@pytest.fixture
def two_step_history() -> pd.DataFrame:
    """Two NGO observations -> step profile with two distinct levels."""
    return pd.DataFrame({
        "date": [pd.Timestamp("2022-12-31"), pd.Timestamp("2023-12-31")],
        "extraction_l_per_day": [30_000.0, 50_000.0],
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_attach_extraction_step_change_zero_before_and_jumps(
    synthetic_drivers_2y, two_step_history
):
    """Days before first observation = 0; days at/after first obs take that
    value; days at/after second obs jump to the second value."""
    out = attach_extraction_profile(synthetic_drivers_2y, two_step_history)
    assert "extraction_l" in out.columns
    assert len(out) == len(synthetic_drivers_2y)

    out_dates = pd.to_datetime(out["date"])

    # Before 2022-12-31 -> 0
    pre = out.loc[out_dates < pd.Timestamp("2022-12-31"), "extraction_l"]
    assert (pre == 0.0).all()

    # 2022-12-31 .. 2023-12-30 -> 30_000
    mid = out.loc[
        (out_dates >= pd.Timestamp("2022-12-31"))
        & (out_dates < pd.Timestamp("2023-12-31")),
        "extraction_l",
    ]
    assert (mid == 30_000.0).all()

    # 2023-12-31 onwards -> 50_000
    post = out.loc[out_dates >= pd.Timestamp("2023-12-31"), "extraction_l"]
    assert (post == 50_000.0).all()


def test_attach_extraction_does_not_mutate_input(synthetic_drivers_2y, two_step_history):
    """The function must return a new DataFrame, not mutate the caller's drivers."""
    cols_before = list(synthetic_drivers_2y.columns)
    _ = attach_extraction_profile(synthetic_drivers_2y, two_step_history)
    assert "extraction_l" not in synthetic_drivers_2y.columns
    assert list(synthetic_drivers_2y.columns) == cols_before


def test_attach_extraction_handles_unsorted_history(synthetic_drivers_2y):
    """History given out of date order must still produce the correct step profile."""
    history_unsorted = pd.DataFrame({
        "date": [pd.Timestamp("2023-12-31"), pd.Timestamp("2022-12-31")],
        "extraction_l_per_day": [50_000.0, 30_000.0],
    })
    out = attach_extraction_profile(synthetic_drivers_2y, history_unsorted)
    out_dates = pd.to_datetime(out["date"])

    # First-step value applies on its own date.
    on_first = out.loc[out_dates == pd.Timestamp("2022-12-31"), "extraction_l"].iloc[0]
    assert on_first == 30_000.0

    # Second-step value applies from its own date onward.
    on_second = out.loc[out_dates == pd.Timestamp("2023-12-31"), "extraction_l"].iloc[0]
    assert on_second == 50_000.0

    # Final row uses the latest step value.
    assert out["extraction_l"].iloc[-1] == 50_000.0
