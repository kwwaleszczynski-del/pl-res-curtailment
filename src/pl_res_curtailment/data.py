"""The PSE series of the tracker as one 15-minute frame.

All series come from the PSE reports API through the ``pse-opendata`` client, which caches whole months as Parquet
files (``./data`` by default) and downloads a month again until its revision window has passed (90 days for the
redispatch report).

Columns of the combined frame (index: interval start, UTC):

    pv_balance, pv_network       PV curtailed for balancing / for network constraints, MW (>= 0, 0 = no order)
    wind_balance, wind_network   the same for wind
    demand, pv, wind             actual demand and actual PV and wind generation, MW
    exchange                     cross-border exchange balance, MW, + = import, - = export
    rce, cen                     RCE market price and imbalance price CEN, PLN/MWh
    pv_plan, wind_plan           PV and wind generation in PSE's day-ahead coordinated plan (PKD), MW

Usage:
    client = make_client(Path("data"))
    frame, last = load_frame(client, HISTORY_START, date(2026, 10, 25))
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pse_opendata as pse

log = logging.getLogger("pl_res_curtailment")

TZ = "Europe/Warsaw"
HISTORY_START = date(2024, 9, 24)      # first business day of the report poze-redoze
QH = 0.25                               # hours per interval

# report -> {PSE field: column of the combined frame}
SOURCES: dict[str, dict[str, str]] = {
    "poze-redoze": {"pv_red_balance": "pv_balance", "pv_red_network": "pv_network",
                    "wi_red_balance": "wind_balance", "wi_red_network": "wind_network"},
    "his-wlk-cal": {"demand": "demand", "pv": "pv", "wi": "wind", "swm_p": "swm_p", "swm_np": "swm_np"},
    "rce-pln": {"rce_pln": "rce"},
    "crb-rozl": {"cen_cost": "cen"},
    "pdgopkd": {"gen_fv": "pv_plan", "gen_wi": "wind_plan"},
}
REDISPATCH = ["pv_balance", "pv_network", "wind_balance", "wind_network"]
COLUMNS = [*REDISPATCH, "demand", "pv", "wind", "exchange", "rce", "cen", "pv_plan", "wind_plan"]


def make_client(data_dir: Path, offline: bool = False) -> pse.Client:
    """Client caching in ``data_dir``; a failed download falls back to an older cached copy of the month."""
    return pse.Client(cache_dir=data_dir, offline=offline, allow_stale=True)


def redispatch_part(raw: pd.DataFrame) -> pd.DataFrame:
    """PSE publishes the reduction as negative MW and leaves intervals without an order empty; here: >= 0, 0."""
    part = raw.set_index("start_utc")[list(SOURCES["poze-redoze"])].rename(columns=SOURCES["poze-redoze"])
    return (-part).fillna(0.0).clip(lower=0.0)


def combine(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combined frame from the frames of pse-opendata keyed by report name (see ``SOURCES``).

    Rows are the intervals of the redispatch report; the other series are aligned on the interval start and are
    NaN where they have no value.
    """
    frame = redispatch_part(raw["poze-redoze"])
    for report, fields in SOURCES.items():
        if report == "poze-redoze":
            continue
        part = raw[report].set_index("start_utc")[list(fields)].rename(columns=fields)
        frame = frame.join(part[~part.index.duplicated(keep="last")], how="left")
    frame["exchange"] = frame.pop("swm_p") + frame.pop("swm_np")
    frame.index.name = "start_utc"
    return frame[COLUMNS].sort_index()


def load_frame(client: pse.Client, start: date, end: date) -> tuple[pd.DataFrame, dict[str, pd.Timestamp | None]]:
    """Combined frame for business days ``start``..``end`` and the last interval start with data per report.

    The first and last months are requested whole, so that pse-opendata caches them (it stores whole months only)
    and ``--offline`` can rebuild the same result; days outside ``start``..``end`` are dropped here.
    """
    month_start, month_end = start.replace(day=1), (pd.Timestamp(end) + pd.offsets.MonthEnd(0)).date()
    raw, last = {}, {}
    for report, fields in SOURCES.items():
        frame = client.get(report, month_start, month_end, fields=list(fields), dropna=report != "poze-redoze")
        frame = frame[(frame["business_date"] >= start) & (frame["business_date"] <= end)]
        values = frame[list(fields)].notna().any(axis=1)
        last[report] = frame.loc[values, "start_utc"].max() if values.any() else None
        log.info("%s: %d rows, last interval with data %s", report, len(frame), last[report])
        raw[report] = frame
    if raw["poze-redoze"].empty:
        return pd.DataFrame(columns=COLUMNS), last
    return combine(raw), last
