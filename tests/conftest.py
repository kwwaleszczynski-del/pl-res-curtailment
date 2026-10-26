"""Synthetic 15-minute data in the shapes of ``data.combine`` and of pse-opendata frames (no network).

Tests never depend on the datetime resolution of pandas (ns in pandas 2, us in pandas 3 for some constructors):
timestamps are compared as ``pd.Timestamp`` values or calendar fields, never as integers or dtype strings.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pl_res_curtailment.calendar_pl import day_type
from pl_res_curtailment.data import COLUMNS, SOURCES, TZ


def quarter_hours(start: date, end: date) -> pd.DatetimeIndex:
    """Interval starts (UTC) of local delivery days start..end inclusive (92, 96 or 100 per day)."""
    idx = pd.date_range(pd.Timestamp(start, tz=TZ), pd.Timestamp(end + timedelta(days=1), tz=TZ), freq="15min",
                        inclusive="left")
    return pd.DatetimeIndex(idx.tz_convert("UTC"), name="start_utc")


def synthetic_frame(start: date, end: date, seed: int = 0, voluntary_wind: float = 0.2) -> pd.DataFrame:
    """Combined frame with PSE-like curtailment: orders when potential residual load is low, negative prices at
    large surpluses, and wind farms that reduce output by ``voluntary_wind`` on their own at negative prices."""
    rng = np.random.default_rng(seed)
    idx = quarter_hours(start, end)
    local = idx.tz_convert(TZ)
    n = len(idx)
    hour = np.asarray(local.hour + local.minute / 60, dtype=float)
    doy = np.asarray(local.day_of_year, dtype=float)
    summer = 0.5 + 0.5 * np.cos((doy - 172) / 365 * 2 * np.pi)
    daylight = 8 + 8 * summer
    sun = np.clip(np.sin((hour - (12.5 - daylight / 2)) / daylight * np.pi), 0, None)
    days = np.asarray([d.date() for d in local])
    free = np.asarray([day_type(d) != "workday" for d in days])
    pv_pot = 15000 * (0.35 + 0.65 * summer) * sun * rng.uniform(0.75, 1.0, n)
    wind_pot = np.clip(3500 + 2500 * np.sin(np.arange(n) / 400) + rng.normal(0, 500, n), 50, None)
    demand = 18000 + 2500 * np.exp(-((hour - 19) ** 2) / 6) + 1500 * (1 - summer) - 2500 * free
    demand = demand + rng.normal(0, 300, n)
    residual = demand - pv_pot - wind_pot
    exchange = np.clip(0.3 * (residual - 9000), -4000, 3000)                     # + = import
    rce = 450 + 0.06 * (residual - 10000) + rng.normal(0, 20, n)
    cen = rce + rng.normal(0, 150, n)
    surplus = np.clip(6500 - residual, 0, None) * 0.6
    share_pv = np.where(pv_pot + wind_pot > 0, pv_pot / (pv_pot + wind_pot), 0)
    cur_pv, cur_wind = surplus * share_pv, surplus * (1 - share_pv)
    network = rng.random(n) < 0.02
    pv_net = np.where(network, 20.0, 0.0)
    wind_net = np.where(network, 30.0, 0.0)
    pv = pv_pot - cur_pv - pv_net
    wind = wind_pot - cur_wind - wind_net
    wind = wind - voluntary_wind * wind * (rce < 0)
    frame = pd.DataFrame({
        "pv_balance": cur_pv, "pv_network": pv_net, "wind_balance": cur_wind, "wind_network": wind_net,
        "demand": demand, "pv": pv, "wind": wind, "exchange": exchange, "rce": rce, "cen": cen,
        "pv_plan": pv_pot * rng.uniform(0.95, 1.05, n), "wind_plan": wind_pot * rng.uniform(0.9, 1.1, n),
    }, index=idx)
    return frame[COLUMNS]


def pse_frames(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The combined frame split back into frames as pse-opendata returns them (redispatch negative, NaN = none)."""
    start = pd.Series(frame.index)
    times = pd.DataFrame({
        "start_utc": start, "end_utc": start + pd.Timedelta(minutes=15),
        "start_local": start.dt.tz_convert(TZ), "end_local": (start + pd.Timedelta(minutes=15)).dt.tz_convert(TZ),
    })
    times["business_date"] = times["start_local"].dt.date
    inverse = {"swm_p": frame["exchange"] - 400.0, "swm_np": pd.Series(400.0, index=frame.index)}
    out = {}
    for report, fields in SOURCES.items():
        cols = {}
        for pse_name, col in fields.items():
            values = inverse[pse_name] if pse_name in inverse else frame[col]
            if report == "poze-redoze":
                values = (-values).where(values > 0)
            cols[pse_name] = values.to_numpy()
        out[report] = pd.concat([times, pd.DataFrame(cols)], axis=1)
    return out


class FakeClient:
    """Stands in for ``pse_opendata.Client``: serves the synthetic frames and records the requested ranges."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames
        self.calls: list[tuple[str, date, date]] = []

    def get(self, report, start, end=None, *, fields=None, dropna=False):
        self.calls.append((report, start, end))
        f = self.frames[report]
        f = f[(f["business_date"] >= start) & (f["business_date"] <= (end or start))]
        cols = list(fields) if fields else [c for c in f.columns if c not in
                                            ("start_utc", "end_utc", "start_local", "end_local", "business_date")]
        f = f[["start_utc", "end_utc", "start_local", "end_local", "business_date", *cols]]
        if dropna:
            f = f.dropna(subset=cols, how="all")
        return f.reset_index(drop=True)


@pytest.fixture(scope="session")
def frame():
    """1 January 2025 - 30 June 2026."""
    return synthetic_frame(date(2025, 1, 1), date(2026, 6, 30), seed=1)
