"""Curtailment metrics on the combined 15-minute frame (see ``data.combine``).

Definitions (per quarter-hour, MW; energy = MW x 0.25 h):
    curtailed PV / wind     ordered reduction for balancing + for network constraints
    potential output        actual output + curtailed output
    potential residual load demand - potential PV - potential wind
    share of potential      curtailed energy / potential energy
    value at RCE            curtailed energy x RCE (signed), or x max(RCE, 0)
    CEN estimate            curtailed energy x max(CEN, 0): the sales part of the compensation as PSE describes it

Usage:
    result = analyse(frame, announcements=hourly, meta={"data_downloaded": "2026-10-26"})
    result.summary()
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pl_res_curtailment.announcements import monthly_volumes
from pl_res_curtailment.calendar_pl import day_type, holiday_name
from pl_res_curtailment.data import QH, TZ
from pl_res_curtailment.reference import ure_tso_totals

TECHS = ("pv", "wind")
FULL = 0.97                      # coverage from which a month or year counts as complete
VOL_MIN_PLAN = {"pv": 200.0, "wind": 100.0}
VARIANTS = {"month x hour": ["month_n", "hour"], "season x hour x level": ["season", "hour", "level"],
            "season x level": ["season", "level"], "level": ["level"]}
GROUPS = ("negative, ordered", "negative, no order", "positive, ordered", "positive, no order")

DRIVERS = {
    # column, bin edges, labels, title
    "residual": ("residual_pot", [-np.inf, 4e3, 6e3, 8e3, 10e3, 12e3, 14e3, np.inf],
                 ["< 4", "4-6", "6-8", "8-10", "10-12", "12-14", ">= 14"],
                 "Potential residual load (GW): demand minus PV and wind before curtailment"),
    "export": ("net_export", [-np.inf, -2e3, -1e3, 0, 1e3, 2e3, 3e3, np.inf],
               ["import > 2", "import 1-2", "import 0-1", "export 0-1", "export 1-2", "export 2-3", "export > 3"],
               "Net cross-border exchange (GW)"),
    "price": ("rce", [-np.inf, -100, 0, 50, 150, 300, 500, np.inf],
              ["< -100", "-100 to 0", "0-50", "50-150", "150-300", "300-500", ">= 500"],
              "RCE price (PLN/MWh)"),
    "demand": ("demand", [-np.inf, 13e3, 15e3, 17e3, 19e3, 21e3, 23e3, np.inf],
               ["< 13", "13-15", "15-17", "17-19", "19-21", "21-23", ">= 23"], "Demand (GW)"),
    "pv_share": ("pv_pot_share", [-np.inf, 10, 30, 50, 60, 70, 80, np.inf],
                 ["< 10", "10-30", "30-50", "50-60", "60-70", "70-80", ">= 80"],
                 "Potential PV output as % of demand"),
}


@dataclass
class Analysis:
    frame: pd.DataFrame
    monthly: pd.DataFrame
    annual: pd.DataFrame
    value: pd.DataFrame
    profile: pd.DataFrame
    hour_tech: pd.DataFrame
    drivers: dict[str, pd.DataFrame]
    daytype: pd.DataFrame
    top_days: pd.DataFrame
    overlap: pd.DataFrame
    voluntary: pd.DataFrame
    voluntary_range: pd.DataFrame
    legacy_monthly: pd.DataFrame
    sources: pd.DataFrame
    meta: dict = field(default_factory=dict)

    @property
    def last_full_year(self) -> int | None:
        full = self.annual[self.annual["coverage"] >= FULL]
        return int(full.index.max()) if len(full) else None

    def summary(self) -> dict:
        a, out = self.annual, {"meta": self.meta}
        out["period"] = {"first_interval_utc": f"{self.frame.index.min():%Y-%m-%d %H:%M}",
                         "last_interval_utc": f"{self.frame.index.max():%Y-%m-%d %H:%M}"}
        out["totals"] = {k: _r(self.monthly[k].sum(), 1) for k in
                         ("pv_balance", "pv_network", "wind_balance", "wind_network", "total_gwh")}
        out["annual"] = {str(y): {k: _r(v, 4) for k, v in row.items()} for y, row in a.iterrows()}
        out["trend"] = trend(self.monthly)
        out["cen_spikes"] = {k: _r(v, 4) for k, v in cen_spikes(self.frame).items()}
        out["value"] = {f"{y}-{t}": {k: _r(v, 3) for k, v in row.items()} for (y, t), row in self.value.iterrows()}
        out["overlap"] = {str(y): {k: _r(v, 4) for k, v in row.items()} for y, row in self.overlap.iterrows()}
        out["voluntary"] = {t: {k: _r(v, 4) for k, v in row.items()} for t, row in self.voluntary_range.iterrows()}
        out["daytype"] = [{k: _r(v, 3) for k, v in row.items()} for row in self.daytype.reset_index().to_dict("records")]
        out["drivers"] = {name: {str(i): {k: _r(v, 4) for k, v in row.items()} for i, row in d.iterrows()}
                          for name, d in self.drivers.items()}
        out["top_days"] = [{k: _r(v, 2) for k, v in row.items()}
                           for row in self.top_days.head(10).reset_index().to_dict("records")]
        out["sources"] = {str(y): {k: _r(v, 1) for k, v in row.items()} for y, row in self.sources.iterrows()}
        return out


def _r(v, nd: int):
    """JSON-safe value: rounded float (None for NaN), int, bool or str."""
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, str):
        return v
    v = float(v)
    return None if math.isnan(v) or math.isinf(v) else round(v, nd)


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Intervals with published demand, with calendar columns and derived quantities."""
    f = frame[frame["demand"].notna()].copy()
    local = f.index.tz_convert(TZ)
    f["date"] = local.date
    f["month"] = local.strftime("%Y-%m")
    f["month_n"] = local.month
    f["year"] = local.year
    f["hour"] = local.hour
    f["season"] = (f["month_n"] % 12) // 3
    f["cur_pv"] = f["pv_balance"] + f["pv_network"]
    f["cur_wind"] = f["wind_balance"] + f["wind_network"]
    f["cur"] = f["cur_pv"] + f["cur_wind"]
    f["pv_pot"] = f["pv"] + f["cur_pv"]
    f["wind_pot"] = f["wind"] + f["cur_wind"]
    f["residual_pot"] = f["demand"] - f["pv_pot"] - f["wind_pot"]
    f["net_export"] = -f["exchange"]
    f["pv_pot_share"] = 100 * f["pv_pot"] / f["demand"]
    types = {d: day_type(d) for d in pd.unique(f["date"])}
    f["day_type"] = f["date"].map(types)
    return f


def _quarter_hours(start: pd.Timestamp, end: pd.Timestamp) -> int:
    return len(pd.date_range(start, end, freq="15min", inclusive="left"))


def _expected(periods, kind: str) -> pd.Series:
    out = {}
    for p in periods:
        if kind == "month":
            start = pd.Timestamp(f"{p}-01", tz=TZ)
            out[p] = _quarter_hours(start, start + pd.DateOffset(months=1))
        else:
            start = pd.Timestamp(f"{p}-01-01", tz=TZ)
            out[p] = _quarter_hours(start, start + pd.DateOffset(years=1))
    return pd.Series(out)


def aggregate(f: pd.DataFrame, key: str) -> pd.DataFrame:
    """Volumes, shares, frequency, value and negative-price overlap per month or year."""
    g = f.groupby(key)
    e = QH / 1000          # MW per interval -> GWh
    ordered = f["cur"] > 0
    neg = f["rce"] < 0
    out = pd.DataFrame({"intervals": g.size()})
    out["coverage"] = out["intervals"] / _expected(out.index, key)
    for c in ("pv_balance", "pv_network", "wind_balance", "wind_network"):
        out[c] = g[c].sum() * e
    out["pv_gwh"] = out["pv_balance"] + out["pv_network"]
    out["wind_gwh"] = out["wind_balance"] + out["wind_network"]
    out["total_gwh"] = out["pv_gwh"] + out["wind_gwh"]
    out["pv_output_gwh"] = g["pv"].sum() * e
    out["wind_output_gwh"] = g["wind"].sum() * e
    out["pv_share"] = out["pv_gwh"] / (out["pv_output_gwh"] + out["pv_gwh"])
    out["wind_share"] = out["wind_gwh"] / (out["wind_output_gwh"] + out["wind_gwh"])
    out["hours_ordered"] = ordered.groupby(f[key]).sum() / 4
    out["days_ordered"] = f.loc[ordered].groupby(key)["date"].nunique()
    out["days_ordered"] = out["days_ordered"].fillna(0)
    out["peak_mw"] = g["cur"].max()
    energy = f["cur"] * QH
    out["value_rce"] = (energy * f["rce"]).groupby(f[key]).sum() / 1e6
    out["value_rce_floor"] = (energy * f["rce"].clip(lower=0)).groupby(f[key]).sum() / 1e6
    out["value_cen_floor"] = (energy * f["cen"].clip(lower=0)).groupby(f[key]).sum() / 1e6
    out["cen_coverage"] = energy.where(f["cen"].notna(), 0).groupby(f[key]).sum() / energy.groupby(f[key]).sum()
    out["neg_qh"] = neg.groupby(f[key]).sum()
    out["neg_qh_ordered"] = (neg & ordered).groupby(f[key]).sum()
    out["share_at_neg"] = energy.where(neg, 0).groupby(f[key]).sum() / energy.groupby(f[key]).sum()
    return out


def trend(monthly: pd.DataFrame) -> dict:
    """Year-on-year change over the complete months that the latest year shares with the year before."""
    full = monthly[monthly["coverage"] >= FULL]
    if full.empty:
        return {}
    years = sorted({m[:4] for m in full.index})
    out = {"complete_months": int(len(full)), "first_complete_month": full.index.min(),
           "last_complete_month": full.index.max()}
    if len(years) >= 2:
        last, prev = years[-1], years[-2]
        months = [m[5:] for m in full.index if m.startswith(last) and f"{prev}-{m[5:]}" in full.index]
        if months:
            now = full.loc[[f"{last}-{m}" for m in months]]
            before = full.loc[[f"{prev}-{m}" for m in months]]
            out["yoy"] = {"months": f"{months[0]}..{months[-1]}", "year": int(last), "previous": int(prev)}
            for c in ("pv_gwh", "wind_gwh", "total_gwh", "value_rce_floor", "hours_ordered"):
                a, b = float(now[c].sum()), float(before[c].sum())
                out["yoy"][c] = [_r(b, 1), _r(a, 1), _r(a / b - 1, 3) if b else None]
    roll = full["total_gwh"].rolling(12).sum().dropna()
    if len(roll):
        out["rolling12_last"] = {"to": roll.index[-1], "gwh": _r(roll.iloc[-1], 1)}
        out["rolling12_first"] = {"to": roll.index[0], "gwh": _r(roll.iloc[0], 1)}
    return out


def value_table(f: pd.DataFrame) -> pd.DataFrame:
    """Per year and technology: curtailed GWh and its value (mln PLN) at RCE, RCE >= 0 and CEN >= 0."""
    rows = []
    for (year, tech), d in [((y, t), g) for y, g in f.groupby("year") for t in TECHS]:
        energy = d[f"cur_{tech}"] * QH
        gwh = energy.sum() / 1000
        row = {"year": year, "tech": tech, "gwh": gwh,
               "rce": (energy * d["rce"]).sum() / 1e6,
               "rce_floor": (energy * d["rce"].clip(lower=0)).sum() / 1e6,
               "cen_floor": (energy * d["cen"].clip(lower=0)).sum() / 1e6}
        row["rce_avg"] = row["rce"] * 1e6 / (gwh * 1000) if gwh else np.nan
        row["cen_avg"] = (energy * d["cen"]).sum() / energy.where(d["cen"].notna(), 0).sum() if gwh else np.nan
        rows.append(row)
    return pd.DataFrame(rows).set_index(["year", "tech"])


def cen_spikes(f: pd.DataFrame, threshold: float = 1000.0) -> dict:
    """How much of the CEN-based value comes from quarter-hours with CEN above ``threshold`` PLN/MWh."""
    energy = f["cur"] * QH
    value = energy * f["cen"].clip(lower=0)
    spike = f["cen"] > threshold
    total_e, total_v = energy[f["cen"].notna()].sum(), value.sum()
    return {"threshold": threshold, "energy_share": energy[spike].sum() / total_e if total_e else np.nan,
            "value_share": value[spike].sum() / total_v if total_v else np.nan,
            "energy_share_cen_positive": energy[f["cen"] > 0].sum() / total_e if total_e else np.nan}


def binned(f: pd.DataFrame, column: str, edges, labels) -> pd.DataFrame:
    d = f[f[column].notna()]
    cat = pd.cut(d[column], edges, labels=labels, right=False)
    g = d.groupby(cat, observed=False)
    total = (d["cur"] * QH).sum()
    out = pd.DataFrame({"intervals": g.size()})
    out["share_of_time"] = out["intervals"] / len(d)
    out["p_order"] = (d["cur"] > 0).groupby(cat, observed=False).mean()
    out["mean_mw"] = g["cur"].mean()
    out["share_of_energy"] = (d["cur"] * QH).groupby(cat, observed=False).sum() / total if total else np.nan
    out.index = out.index.astype(str)
    return out


def daily(f: pd.DataFrame) -> pd.DataFrame:
    g = f.groupby("date")
    out = pd.DataFrame({
        "pv_gwh": g["cur_pv"].sum() * QH / 1000, "wind_gwh": g["cur_wind"].sum() * QH / 1000,
        "peak_mw": g["cur"].max(), "min_rce": g["rce"].min(), "min_residual_gw": g["residual_pot"].min() / 1000,
        "max_export_gw": g["net_export"].max() / 1000, "month_n": g["month_n"].first(),
        "day_type": g["day_type"].first(),
    })
    out["total_gwh"] = out["pv_gwh"] + out["wind_gwh"]
    return out


def daytype_table(day: pd.DataFrame) -> pd.DataFrame:
    """Curtailment by day type within the PV season (April-September) and the rest of the year."""
    season = np.where(day["month_n"].between(4, 9), "Apr-Sep", "Oct-Mar")
    rows = []
    for (s, t), d in day.groupby([season, day["day_type"]]):
        rows.append({"season": s, "day_type": t, "days": len(d), "share_days_ordered": float((d["total_gwh"] > 0).mean()),
                     "mean_gwh_per_day": float(d["total_gwh"].mean()), "total_gwh": float(d["total_gwh"].sum())})
    return pd.DataFrame(rows).set_index(["season", "day_type"])


def top_days(day: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    top = day.sort_values("total_gwh", ascending=False).head(n).copy()
    top["weekday"] = [d.strftime("%a") for d in top.index]
    top["holiday"] = [holiday_name(d) or "" for d in top.index]
    top.index = [f"{d:%Y-%m-%d}" for d in top.index]
    top.index.name = "date"
    return top[["weekday", "day_type", "holiday", "pv_gwh", "wind_gwh", "total_gwh", "peak_mw", "min_rce",
                "min_residual_gw", "max_export_gw"]]


def overlap_table(f: pd.DataFrame) -> pd.DataFrame:
    """Negative RCE quarter-hours and PSE orders: how often they coincide, per year and in total."""
    rows = {}
    for key, d in [*f.groupby("year"), ("all", f)]:
        neg, ordered = d["rce"] < 0, d["cur"] > 0
        e = d["cur"] * QH / 1000
        rows[str(key)] = {
            "neg_qh": int(neg.sum()), "ordered_qh": int(ordered.sum()),
            "neg_with_order": float((neg & ordered).sum() / neg.sum()) if neg.sum() else np.nan,
            "order_at_neg": float((neg & ordered).sum() / ordered.sum()) if ordered.sum() else np.nan,
            "gwh_at_neg": float(e[neg].sum()), "gwh_at_pos": float(e[~neg & d["rce"].notna()].sum()),
            "pv_gwh_at_neg": float((d["cur_pv"] * QH / 1000)[neg].sum()),
            "wind_gwh_at_neg": float((d["cur_wind"] * QH / 1000)[neg].sum()),
        }
    return pd.DataFrame(rows).T


def implied_voluntary(f: pd.DataFrame, tech: str) -> pd.DataFrame:
    """Output below PSE's day-ahead plan that PSE orders do not explain, by price sign and order status.

    Expected output = plan x (actual / plan) of comparable quarter-hours with a non-negative price and no order;
    shortfall = expected - actual - ordered curtailment. Four definitions of "comparable" are computed.
    """
    act, plan, cur = tech, f"{tech}_plan", f"cur_{tech}"
    d = f.loc[(f[plan] > VOL_MIN_PLAN[tech]) & f[act].notna() & f["rce"].notna(),
              [act, plan, cur, "rce", "hour", "month_n", "season", "year"]].copy()
    if len(d) < 500:
        return pd.DataFrame()
    d["level"] = pd.qcut(d[plan], 8, labels=False, duplicates="drop")
    neg, ordered = d["rce"] < 0, d[cur] > 0
    d["group"] = np.select([neg & ordered, neg & ~ordered, ~neg & ordered], list(GROUPS[:3]), GROUPS[3])
    base = d[~neg & ~ordered]
    rows = []
    for name, keys in VARIANTS.items():
        ratio = (base.groupby(keys)[act].sum() / base.groupby(keys)[plan].sum()).rename("ratio").reset_index()
        r = d[keys].merge(ratio, on=keys, how="left")["ratio"].to_numpy()
        e = pd.DataFrame({"expected": d[plan].to_numpy() * r, "delivered": d[act].to_numpy(),
                          "ordered": d[cur].to_numpy(), "group": d["group"].to_numpy(), "year": d["year"].to_numpy()})
        e = e[np.isfinite(e["expected"])]
        e["shortfall"] = e["expected"] - e["delivered"] - e["ordered"]
        for (year, group), x in [*e.groupby(["year", "group"]), *(((("all", g), x) for g, x in e.groupby("group")))]:
            s = x[["expected", "delivered", "ordered", "shortfall"]].sum() * QH / 1000
            rows.append({"tech": tech, "variant": name, "year": str(year), "group": group, "intervals": len(x),
                         **{f"{k}_gwh": float(v) for k, v in s.items()},
                         "shortfall_share": float(s["shortfall"] / s["expected"]) if s["expected"] else np.nan})
    return pd.DataFrame(rows)


def voluntary_range(vol: pd.DataFrame) -> pd.DataFrame:
    """Per technology: implied voluntary reduction at negative prices, GWh, central value and range.

    naive    = shortfall in all negative-price quarter-hours;
    adjusted = naive minus the shortfall share seen in positive-price quarter-hours with an order (a placebo: there
               the shortfall cannot be voluntary) times the expected output of negative-price quarter-hours with an
               order.
    """
    rows = {}
    for tech, v in vol[vol["year"] == "all"].groupby("tech"):
        est = {}
        for name, x in v.groupby("variant"):
            x = x.set_index("group")
            negs = [g for g in GROUPS[:2] if g in x.index]
            naive = float(x.loc[negs, "shortfall_gwh"].sum())
            placebo = float(x.at[GROUPS[2], "shortfall_share"]) if GROUPS[2] in x.index else 0.0
            exp_ord = float(x.at[GROUPS[0], "expected_gwh"]) if GROUPS[0] in x.index else 0.0
            est[name] = (naive, naive - placebo * exp_ord, placebo)
        central = est.get("month x hour", next(iter(est.values())))
        allv = [a for a, _, _ in est.values()] + [b for _, b, _ in est.values()]
        x = v[v["variant"] == "month x hour"].set_index("group")
        rows[tech] = {"central_gwh": central[0], "low_gwh": min(allv), "high_gwh": max(allv),
                      "placebo_share": central[2],
                      "neg_expected_gwh": float(x.loc[[g for g in GROUPS[:2] if g in x.index], "expected_gwh"].sum()),
                      "neg_ordered_gwh": float(x.loc[[g for g in GROUPS[:2] if g in x.index], "ordered_gwh"].sum()),
                      "neg_no_order_share": float(x.at[GROUPS[1], "shortfall_share"]) if GROUPS[1] in x.index else np.nan,
                      "neg_ordered_share": float(x.at[GROUPS[0], "shortfall_share"]) if GROUPS[0] in x.index else np.nan}
    out = pd.DataFrame(rows).T
    if len(out):
        # the estimate is only reported as identified when the placebo bias is small next to the effect
        out["identified"] = (out["low_gwh"] > 0) & (out["placebo_share"].abs() < 0.03)
    return out


def negative_shares(vol: pd.DataFrame) -> pd.DataFrame:
    """Per technology, in negative-price quarter-hours: ordered and unexplained output as % of expected output."""
    if vol.empty:
        return pd.DataFrame(columns=["ordered", "shortfall"])
    v = vol[(vol["variant"] == "month x hour") & (vol["year"] == "all") & vol["group"].isin(GROUPS[:2])]
    s = v.groupby("tech")[["expected_gwh", "ordered_gwh", "shortfall_gwh"]].sum()
    s = s.reindex([t for t in ("wind", "pv") if t in s.index])
    return pd.DataFrame({"ordered": 100 * s["ordered_gwh"] / s["expected_gwh"],
                         "shortfall": 100 * s["shortfall_gwh"] / s["expected_gwh"]})


def sources_table(annual: pd.DataFrame, legacy: pd.DataFrame) -> pd.DataFrame:
    """GWh per year from the PSE report, the PSE announcements and the URE reports (TSO orders)."""
    ure = ure_tso_totals()
    years = sorted(set(ure.index) | set(annual.index))
    rows = {}
    for y in years:
        lm = legacy[legacy.index.str.startswith(str(y))] if len(legacy) else pd.DataFrame()
        row = {
            "report_pv": annual.at[y, "pv_gwh"] if y in annual.index else 0.0,
            "report_wind": annual.at[y, "wind_gwh"] if y in annual.index else 0.0,
            "announced_pv": float(lm["pv"].sum()) if "pv" in lm else 0.0,
            "announced_wind": float(lm["wind"].sum()) if "wind" in lm else 0.0,
            "announced_other": float(lm.drop(columns=[c for c in ("pv", "wind") if c in lm]).sum().sum()) if len(lm) else 0.0,
            "ure_pv": ure.at[y, "pv"] if y in ure.index else np.nan,
            "ure_wind": ure.at[y, "wind"] if y in ure.index else np.nan,
        }
        row["coverage_pv"] = (row["report_pv"] + row["announced_pv"]) / row["ure_pv"] if row["ure_pv"] else np.nan
        row["coverage_wind"] = ((row["report_wind"] + row["announced_wind"]) / row["ure_wind"]
                                if row["ure_wind"] else np.nan)
        rows[y] = row
    return pd.DataFrame(rows).T


def analyse(frame: pd.DataFrame, announcements: pd.DataFrame | None = None, meta: dict | None = None) -> Analysis:
    f = prepare(frame)
    if f.empty:
        raise ValueError("no intervals with both redispatch and system data")
    monthly = aggregate(f, "month")
    annual = aggregate(f, "year")
    full = monthly["coverage"] >= FULL
    monthly["rolling12_gwh"] = monthly["total_gwh"].where(full).rolling(12).sum()
    profile = f.pivot_table(index="month", columns="hour", values="cur", aggfunc="mean")
    hour_tech = pd.DataFrame({t: f.groupby("hour")[f"cur_{t}"].sum() * QH / 1000 for t in TECHS})
    drivers = {name: binned(f, col, edges, labels) for name, (col, edges, labels, _) in DRIVERS.items()}
    day = daily(f)
    vol = pd.concat([implied_voluntary(f, t) for t in TECHS], ignore_index=True)
    legacy = monthly_volumes(announcements) if announcements is not None else pd.DataFrame()
    return Analysis(
        frame=f, monthly=monthly, annual=annual, value=value_table(f), profile=profile, hour_tech=hour_tech,
        drivers=drivers, daytype=daytype_table(day), top_days=top_days(day), overlap=overlap_table(f),
        voluntary=vol, voluntary_range=voluntary_range(vol) if len(vol) else pd.DataFrame(),
        legacy_monthly=legacy, sources=sources_table(annual, legacy), meta=dict(meta or {}),
    )
