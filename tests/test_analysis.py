from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import synthetic_frame
from pl_res_curtailment import analysis as an
from pl_res_curtailment.data import QH


@pytest.fixture(scope="module")
def result(frame):
    hourly = pd.DataFrame({"day": pd.to_datetime(["2024-04-14", "2024-04-14", "2024-05-05"]), "hour": [10, 11, 9],
                           "technology": ["pv", "wind", "pv"], "mw": [1000.0, 500.0, 2000.0],
                           "published": ["", "", ""]})
    return an.analyse(frame, announcements=hourly, meta={"data_downloaded": "2026-07-01"})


def test_volumes_add_up(result, frame):
    m, a = result.monthly, result.annual
    assert m["total_gwh"].sum() == pytest.approx((frame[["pv_balance", "pv_network", "wind_balance",
                                                         "wind_network"]].sum().sum()) * QH / 1000)
    assert a["pv_gwh"].sum() == pytest.approx(m["pv_gwh"].sum())
    jan = m.loc["2025-01"]
    sel = frame.index.tz_convert("Europe/Warsaw").strftime("%Y-%m") == "2025-01"
    pv_cur = frame.loc[sel, ["pv_balance", "pv_network"]].sum(axis=1)
    assert jan["pv_share"] == pytest.approx(pv_cur.sum() / (frame.loc[sel, "pv"] + pv_cur).sum())


def test_coverage_counts_dst_months(result):
    m = result.monthly
    assert m.at["2025-03", "intervals"] == 2972 and m.at["2025-10", "intervals"] == 2980
    assert (m["coverage"] == 1.0).all()
    assert result.annual.at[2025, "coverage"] == 1.0
    assert result.annual.at[2026, "coverage"] < 0.6
    assert result.last_full_year == 2025


def test_value_uses_floors(result, frame):
    energy = frame[["pv_balance", "pv_network", "wind_balance", "wind_network"]].sum(axis=1) * QH
    a = result.annual
    assert a["value_rce"].sum() == pytest.approx((energy * frame["rce"]).sum() / 1e6)
    assert a["value_rce_floor"].sum() == pytest.approx((energy * frame["rce"].clip(lower=0)).sum() / 1e6)
    assert a["value_cen_floor"].sum() == pytest.approx((energy * frame["cen"].clip(lower=0)).sum() / 1e6)
    assert (a["value_rce_floor"] >= a["value_rce"]).all()
    v = result.value
    assert v["gwh"].sum() == pytest.approx(a["total_gwh"].sum())
    assert v.loc[(2025, "pv"), "rce_floor"] + v.loc[(2025, "wind"), "rce_floor"] == pytest.approx(
        a.at[2025, "value_rce_floor"])


def test_drivers_point_at_low_residual_load_and_exports(result):
    for d in result.drivers.values():
        assert d["share_of_time"].sum() == pytest.approx(1.0)
        assert d["share_of_energy"].sum() == pytest.approx(1.0)
    r = result.drivers["residual"]
    assert r.at["< 4", "p_order"] == 1.0 and r.at[">= 14", "p_order"] < 0.05      # only random network orders
    e = result.drivers["export"]
    assert e.loc[[i for i in e.index if i.startswith("export")], "share_of_energy"].sum() > 0.9


def test_day_types_and_top_days(result):
    dt = result.daytype
    assert dt.at[("Apr-Sep", "sunday_holiday"), "mean_gwh_per_day"] > dt.at[("Apr-Sep", "workday"), "mean_gwh_per_day"]
    assert dt["days"].sum() == 546
    top = result.top_days
    assert top["total_gwh"].is_monotonic_decreasing
    assert set(top["day_type"]) <= {"workday", "saturday", "sunday_holiday"}


def test_overlap_with_negative_prices(result, frame):
    o = result.overlap
    neg = frame["rce"] < 0
    assert o.at["all", "neg_qh"] == neg.sum()
    assert o.at["all", "neg_with_order"] == 1.0          # in the synthetic data every negative price is a surplus
    assert 0 < o.at["all", "order_at_neg"] < 1


def test_implied_voluntary_finds_the_injected_wind_reduction(result):
    vr = result.voluntary_range
    w = vr.loc["wind"]
    assert 0.15 < w["neg_no_order_share"] < 0.25 or np.isnan(w["neg_no_order_share"])
    assert 0.12 < w["neg_ordered_share"] < 0.25
    assert w["central_gwh"] > 0 and w["low_gwh"] > 0 and bool(w["identified"])
    p = vr.loc["pv"]
    assert abs(p["neg_ordered_share"]) < 0.05
    shares = an.negative_shares(result.voluntary)
    assert list(shares.index) == ["wind", "pv"] and shares.at["wind", "shortfall"] > 10


def test_no_voluntary_reduction_gives_no_shortfall():
    f = an.prepare(synthetic_frame(date(2025, 4, 1), date(2025, 9, 30), seed=5, voluntary_wind=0.0))
    vol = an.implied_voluntary(f, "wind")
    x = vol[(vol["variant"] == "month x hour") & (vol["year"] == "all")].set_index("group")
    assert abs(x.at["negative, ordered", "shortfall_share"]) < 0.05


def test_trend_and_sources(result):
    t = result.summary()["trend"]
    assert t["yoy"]["months"] == "01..06" and t["yoy"]["year"] == 2026
    assert t["complete_months"] == 18
    assert result.monthly["rolling12_gwh"].notna().sum() == 7
    s = result.sources
    assert s.at[2024, "announced_pv"] == pytest.approx(3.0) and s.at[2024, "announced_wind"] == pytest.approx(0.5)
    assert s.at[2024, "ure_pv"] == pytest.approx(597.2641)


def test_summary_is_json_serialisable(result):
    s = result.summary()
    text = json.dumps(s, allow_nan=False)
    assert "NaN" not in text
    assert set(s["annual"]) == {"2025", "2026"}
    assert s["voluntary"]["wind"]["identified"] in (True, False)


def test_analyse_rejects_frames_without_system_data(frame):
    empty = frame.assign(demand=np.nan)
    with pytest.raises(ValueError):
        an.analyse(empty)
