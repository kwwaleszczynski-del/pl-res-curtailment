"""Static HTML dashboard (Plotly.js from the official CDN) for GitHub Pages.

Figures are written as plain Plotly JSON with colour tokens ("@pv", "@wind", ...) that the page resolves for the
light or dark theme, so one file follows the reader's colour scheme.

Usage:
    write_dashboard(result, Path("docs"), status={"redispatch to": "..."})
"""
from __future__ import annotations

import calendar
import html
import json
import math
from pathlib import Path

import pandas as pd

from pl_res_curtailment.analysis import DRIVERS, FULL, Analysis, negative_shares
from pl_res_curtailment.reference import LEGAL_SOURCES, URE_REPORTS

PLOTLY_JS = "https://cdn.plot.ly/plotly-2.35.2.min.js"
REPO_URL = "https://github.com/kwwaleszczynski-del/pl-res-curtailment"
TIME_AXIS = {"type": "category", "tickvals": [f"{h:02d}:00" for h in range(0, 24, 3)]}
DAY_LABELS = {"workday": "Workday", "saturday": "Saturday", "sunday_holiday": "Sunday / holiday"}


def _num(values, nd: int = 3) -> list:
    out = []
    for v in values:
        v = None if v is None else float(v)
        out.append(None if v is None or math.isnan(v) or math.isinf(v) else round(v, nd))
    return out


def _x_months(index) -> list[str]:
    return [f"{m}-01" for m in index]


def _bar(x, y, name, colour, **kw) -> dict:
    return {"type": "bar", "x": x, "y": _num(y), "name": name, "marker": {"color": colour}, **kw}


def _line(x, y, name, colour, **kw) -> dict:
    return {"type": "scatter", "mode": "lines+markers", "x": x, "y": _num(y), "name": name,
            "line": {"color": colour, "width": 2}, "marker": {"size": 7, "color": colour}, **kw}


def _hatched(colour: str) -> dict:
    """Bar fill for the announcements era: the series colour with surface-coloured diagonal hatching."""
    return {"color": colour, "pattern": {"shape": "/", "bgcolor": colour, "fgcolor": "@surface", "size": 7,
                                         "solidity": 0.35}}


def _driver_fig(d: pd.DataFrame, title: str) -> dict:
    return {"data": [{
        "type": "bar", "x": list(d.index), "y": _num(100 * d["p_order"], 1), "name": "Quarter-hours with an order",
        "marker": {"color": "@wind"}, "customdata": [[a, b, c] for a, b, c in zip(
            _num(100 * d["share_of_energy"], 1), _num(100 * d["share_of_time"], 1), _num(d["mean_mw"], 0))],
        "text": [f"{v:.0f}%" if v is not None else "" for v in _num(100 * d["share_of_energy"], 1)],
        "textposition": "outside", "textfont": {"color": "@ink2", "size": 11},
        "hovertemplate": ("%{x}: order in %{y:.0f}% of quarter-hours<br>%{customdata[1]:.1f}% of the time, "
                          "%{customdata[0]:.1f}% of curtailed energy<br>mean curtailment %{customdata[2]} MW"
                          "<extra></extra>")}],
        "layout": {"xaxis": {"title": {"text": title}, "type": "category"},
                   "yaxis": {"title": {"text": "% of quarter-hours with an order"}, "range": [0, 115]},
                   "bargap": 0.3, "showlegend": False}}


def figures(r: Analysis) -> dict[str, dict]:
    """Plotly figure specs keyed by the id of their container on the page."""
    m, lg = r.monthly, r.legacy_monthly
    x = _x_months(m.index)
    gwh = "%{y:.1f} GWh"
    monthly = []
    if len(lg):
        lx = _x_months(lg.index)
        for col, colour, name in (("pv", "@pv", "PV, PSE announcements"), ("wind", "@wind", "Wind, PSE announcements")):
            if col in lg:
                monthly.append(_bar(lx, lg[col], name, colour, marker=_hatched(colour), hovertemplate=gwh))
        other = lg.drop(columns=[c for c in ("pv", "wind") if c in lg]).sum(axis=1)
        if other.sum() > 0:
            monthly.append(_bar(lx, other, "Technology not stated, announcements", "@muted",
                                marker=_hatched("@muted"), hovertemplate=gwh))
    monthly += [_bar(x, m["pv_gwh"], "PV, PSE report", "@pv", hovertemplate=gwh),
                _bar(x, m["wind_gwh"], "Wind, PSE report", "@wind", hovertemplate=gwh)]
    full = m[m["coverage"] >= FULL]
    xf = _x_months(full.index)
    figs = {
        "monthly": {"data": monthly, "layout": {"barmode": "stack", "bargap": 0.2, "hovermode": "x unified",
                                                "yaxis": {"title": {"text": "GWh per month"}}}},
        "share": {"data": [
            _line(xf, 100 * full["pv_share"], "PV", "@pv", hovertemplate="%{y:.1f}%"),
            _line(xf, 100 * full["wind_share"], "Wind", "@wind", hovertemplate="%{y:.1f}%"),
        ], "layout": {"yaxis": {"title": {"text": "% of potential output"}}, "hovermode": "x unified"}},
        "network": {"data": [
            _bar(x, 1000 * m["pv_network"], "PV", "@pv", hovertemplate="%{y:.0f} MWh"),
            _bar(x, 1000 * m["wind_network"], "Wind", "@wind", hovertemplate="%{y:.0f} MWh"),
        ], "layout": {"barmode": "stack", "bargap": 0.2, "hovermode": "x unified",
                      "yaxis": {"title": {"text": "MWh per month"}}}},
        "rolling": {"data": [
            _line(x, m["rolling12_gwh"], "12-month sum", "@ink2", hovertemplate="%{y:.0f} GWh", connectgaps=False),
        ], "layout": {"yaxis": {"title": {"text": "GWh in the last 12 months"}}, "showlegend": False}},
    }
    p = r.profile.loc[[i for i in r.profile.index if m.at[i, "coverage"] >= FULL]]
    hours = [f"{h:02d}:00" for h in p.columns]
    figs["heat"] = {"data": [{
        "type": "heatmap", "z": [_num(row, 0) for row in p.to_numpy()], "x": hours, "y": list(p.index),
        "colorscale": "@seq", "zmin": 0, "colorbar": {"title": {"text": "MW"}, "thickness": 12},
        "hovertemplate": "%{y} %{x}: %{z:.0f} MW mean<extra></extra>",
    }], "layout": {"yaxis": {"autorange": "reversed", "type": "category"}, "xaxis": TIME_AXIS}}
    ht = r.hour_tech
    hx = [f"{h:02d}:00" for h in ht.index]
    figs["hour_tech"] = {"data": [_bar(hx, ht["pv"], "PV", "@pv", hovertemplate=gwh),
                                  _bar(hx, ht["wind"], "Wind", "@wind", hovertemplate=gwh)],
                         "layout": {"barmode": "stack", "bargap": 0.15, "hovermode": "x unified", "xaxis": TIME_AXIS,
                                    "yaxis": {"title": {"text": "GWh since the start of the report"}}}}
    for name in ("residual", "export", "price", "pv_share"):
        figs[f"drv_{name}"] = _driver_fig(r.drivers[name], DRIVERS[name][3])
    dt = r.daytype.reset_index()
    figs["daytype"] = {"data": [
        _bar([DAY_LABELS[t] for t in s["day_type"]], s["mean_gwh_per_day"], season, colour,
             customdata=_num(100 * s["share_days_ordered"], 0),
             hovertemplate="%{y:.1f} GWh per day; orders on %{customdata}% of days<extra>" + season + "</extra>")
        for season, colour in (("Apr-Sep", "@pv"), ("Oct-Mar", "@wind"))
        for s in [dt[dt["season"] == season].set_index("day_type").reindex(list(DAY_LABELS)).reset_index()]
    ], "layout": {"barmode": "group", "bargap": 0.3, "yaxis": {"title": {"text": "GWh per day"}}}}
    a = r.annual
    ya = [f"{y}" if c >= FULL else f"{y} (part)" for y, c in zip(a.index, a["coverage"])]
    figs["value"] = {"data": [
        _bar(ya, a["value_rce"], "Energy x RCE", "@axis", hovertemplate="%{y:.1f} mln PLN"),
        _bar(ya, a["value_rce_floor"], "Energy x max(RCE, 0)", "@ink2", hovertemplate="%{y:.1f} mln PLN"),
        _bar(ya, a["value_cen_floor"], "Energy x max(CEN, 0)", "@aqua", hovertemplate="%{y:.1f} mln PLN"),
    ], "layout": {"barmode": "group", "bargap": 0.3, "yaxis": {"title": {"text": "mln PLN"}},
                  "xaxis": {"type": "category"}}}
    figs["value_monthly"] = {"data": [
        _line(x, m["value_rce_floor"], "Energy x max(RCE, 0)", "@ink2", hovertemplate="%{y:.1f} mln PLN"),
        _line(x, m["value_cen_floor"], "Energy x max(CEN, 0)", "@aqua", hovertemplate="%{y:.1f} mln PLN"),
    ], "layout": {"yaxis": {"title": {"text": "mln PLN per month"}}, "hovermode": "x unified"}}
    figs["neg_hours"] = {"data": [
        _bar(x, m["neg_qh_ordered"] / 4, "With a PSE order", "@wind", hovertemplate="%{y:.2f} h"),
        _bar(x, (m["neg_qh"] - m["neg_qh_ordered"]) / 4, "Without an order", "@axis", hovertemplate="%{y:.2f} h"),
    ], "layout": {"barmode": "stack", "bargap": 0.2, "hovermode": "x unified", "yaxis": {"title": {"text": "hours"}}}}
    ns = negative_shares(r.voluntary)
    if len(ns):
        labels = ["PV" if t == "pv" else "Wind" for t in ns.index]
        figs["voluntary"] = {"data": [
            _bar(labels, ns[c], name, colour, text=[f"{v:.1f}%" for v in ns[c]], textposition="outside",
                 textfont={"color": "@ink2"}, hovertemplate="%{y:.1f}% of expected output")
            for c, name, colour in (("ordered", "Ordered by PSE", "@wind"), ("shortfall", "Unexplained shortfall", "@aqua"))
        ], "layout": {"barmode": "group", "bargap": 0.35, "yaxis": {"title": {"text": "% of expected output"}},
                      "xaxis": {"type": "category"}}}
    src = r.sources
    sx = [str(y) for y in src.index]
    figs["sources"] = {"data": [
        _bar(sx, src["report_pv"] + src["report_wind"], "PSE report (from 24.09.2024)", "@wind",
             hovertemplate="%{y:.0f} GWh"),
        _bar(sx, src["announced_pv"] + src["announced_wind"] + src["announced_other"],
             "PSE announcements (to 23.09.2024)", "@wind",
             marker=_hatched("@wind"),
             hovertemplate="%{y:.0f} GWh"),
        {"type": "scatter", "mode": "markers", "x": sx, "y": _num(src["ure_pv"] + src["ure_wind"], 1),
         "name": "URE annual report (TSO orders)", "marker": {"color": "@ink", "size": 12, "symbol": "line-ew-open",
                                                               "line": {"width": 3, "color": "@ink"}},
         "hovertemplate": "%{y:.0f} GWh<extra>URE</extra>"},
    ], "layout": {"barmode": "stack", "bargap": 0.4, "yaxis": {"title": {"text": "GWh per year"}},
                  "xaxis": {"type": "category"}}}
    return figs


def _fmt(v, spec: str, suffix: str = "") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "n/a"
    return f"{v:{spec}}{suffix}"


def _tile(label: str, value: str, sub: str) -> str:
    return (f'<div class="tile"><div class="label">{label}</div><div class="value">{value}</div>'
            f'<div class="sub">{sub}</div></div>')


def kpi_tiles(r: Analysis) -> str:
    a = r.annual
    groups = []
    last_full = r.last_full_year
    latest = a.index.max()
    for year, note in ((last_full, "last full year"), (latest, "year to date")):
        if year is None or year not in a.index or (note == "year to date" and year == last_full):
            continue
        row = a.loc[year]
        cells = [
            _tile("Curtailed energy", _fmt(row["total_gwh"], ",.0f", " GWh"),
                  f"PV {_fmt(row['pv_gwh'], ',.0f')} GWh, wind {_fmt(row['wind_gwh'], ',.0f')} GWh"),
            _tile("Share of potential output", f"PV {_fmt(100 * row['pv_share'], '.1f', '%')}",
                  f"wind {_fmt(100 * row['wind_share'], '.1f', '%')}; orders on {row['days_ordered']:.0f} days"),
            _tile("Value at RCE (price floored at 0)", _fmt(row["value_rce_floor"], ",.0f", " mln PLN"),
                  f"signed RCE {_fmt(row['value_rce'], ',.0f')}; CEN-based estimate "
                  f"{_fmt(row['value_cen_floor'], ',.0f')} mln PLN"),
            _tile("Curtailed at negative prices", _fmt(100 * row["share_at_neg"], ".0f", "%"),
                  f"orders in {_fmt(100 * row['neg_qh_ordered'] / row['neg_qh'] if row['neg_qh'] else float('nan'), '.0f', '%')}"
                  f" of {row['neg_qh']:.0f} negative quarter-hours"),
        ]
        groups.append(f'<div class="tile-group"><h3>{year} <span>{note}</span></h3>'
                      f'<div class="tiles">{"".join(cells)}</div></div>')
    return "\n".join(groups)


TABLE_COLS = {"coverage": ("Coverage", ".0%"), "pv_gwh": ("PV GWh", ",.1f"), "wind_gwh": ("Wind GWh", ",.1f"),
              "pv_network": ("of which network, PV", ",.2f"), "wind_network": ("network, wind", ",.2f"),
              "pv_share": ("PV share", ".1%"), "wind_share": ("Wind share", ".1%"),
              "hours_ordered": ("Hours with orders", ",.0f"), "days_ordered": ("Days", ".0f"),
              "peak_mw": ("Peak MW", ",.0f"), "value_rce": ("Value RCE", ",.1f"),
              "value_rce_floor": ("RCE >= 0", ",.1f"), "value_cen_floor": ("CEN >= 0", ",.1f"),
              "neg_qh": ("Negative QH", ".0f"), "share_at_neg": ("At negative price", ".0%")}


def table_html(frame: pd.DataFrame, first: str, cols: dict = TABLE_COLS) -> str:
    head = "".join(f"<th>{html.escape(label)}</th>" for label, _ in cols.values())
    rows = []
    for key, row in frame.iterrows():
        cells = "".join(f"<td>{html.escape(_fmt(row[c], spec) if not isinstance(row[c], str) else row[c])}</td>"
                        for c, (_, spec) in cols.items())
        rows.append(f"<tr><th>{html.escape(str(key))}</th>{cells}</tr>")
    return f'<table><thead><tr><th>{first}</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


TOP_COLS = {"weekday": ("Day", "s"), "holiday": ("Holiday", "s"), "pv_gwh": ("PV GWh", ".1f"),
            "wind_gwh": ("Wind GWh", ".1f"), "total_gwh": ("Total GWh", ".1f"), "peak_mw": ("Peak MW", ",.0f"),
            "min_rce": ("Min RCE", ",.0f"), "min_residual_gw": ("Min residual GW", ".1f"),
            "max_export_gw": ("Max export GW", ".1f")}


def texts(r: Analysis) -> dict[str, str]:
    s = r.summary()
    out = {}
    d = r.drivers["residual"]
    low = d.loc[["< 4", "4-6", "6-8"]]
    out["drivers"] = (f"When demand minus potential PV and wind fell below 8 GW ({100 * low['share_of_time'].sum():.0f}% "
                      f"of the time), PSE ordered curtailment in {100 * (low['p_order'] * low['intervals']).sum() / low['intervals'].sum():.0f}% "
                      f"of quarter-hours; these hours hold {100 * low['share_of_energy'].sum():.0f}% of all curtailed energy.")
    e = r.drivers["export"]
    exp = e.loc[[i for i in e.index if i.startswith("export")]]
    out["export"] = (f"{100 * exp['share_of_energy'].sum():.0f}% of the curtailed energy fell in quarter-hours with net "
                     f"exports; with exports above 3 GW an order was in force {100 * e.at['export > 3', 'p_order']:.0f}% "
                     f"of the time.")
    dt = r.daytype
    try:
        sun, work = dt.at[("Apr-Sep", "sunday_holiday"), "mean_gwh_per_day"], dt.at[("Apr-Sep", "workday"), "mean_gwh_per_day"]
        out["daytype"] = (f"From April to September a Sunday or public holiday averaged {sun:.1f} GWh of curtailment, "
                          f"a workday {work:.1f} GWh: {sun / work:.1f} times less.")
    except KeyError:
        out["daytype"] = ""
    o = r.overlap.loc["all"]
    out["overlap"] = (f"PSE orders were in force in {100 * o['neg_with_order']:.0f}% of the {o['neg_qh']:.0f} quarter-hours "
                      f"with a negative RCE price, but only {100 * o['order_at_neg']:.0f}% of the quarter-hours with an "
                      f"order had a negative price: {o['gwh_at_neg']:.0f} of {o['gwh_at_neg'] + o['gwh_at_pos']:.0f} GWh "
                      f"were curtailed at negative prices.")
    vr = r.voluntary_range
    parts = []
    if "wind" in vr.index:
        w = vr.loc["wind"]
        parts.append(f"Wind: in negative-price quarter-hours without an order, output was "
                     f"{100 * w['neg_no_order_share']:.0f}% below the expectation; across all negative-price quarter-hours "
                     f"the unexplained shortfall is about {w['central_gwh']:.0f} GWh (range {w['low_gwh']:.0f} to "
                     f"{w['high_gwh']:.0f} GWh), next to {w['neg_ordered_gwh']:.0f} GWh ordered by PSE in the same "
                     f"quarter-hours. The plan is published after the day-ahead auction, so reductions already "
                     f"scheduled in it are not counted: the figure is a lower bound.")
    if "pv" in vr.index:
        p = vr.loc["pv"]
        parts.append(f"PV: the estimate is not identified. In positive-price quarter-hours with an order, actual plus "
                     f"curtailed PV was already {100 * abs(p['placebo_share']):.0f}% "
                     f"{'above' if p['placebo_share'] < 0 else 'below'} the expectation, so the range "
                     f"({p['low_gwh']:.0f} to {p['high_gwh']:.0f} GWh) cannot separate voluntary curtailment from "
                     f"forecast error and from how PSE counts the ordered volume.")
    out["voluntary"] = " ".join(parts)
    c = s.get("cen_spikes", {})
    out["cen"] = ""
    if c.get("value_share") is not None:
        out["cen"] = (f"The CEN-based figure exceeds the value at RCE: in curtailment quarter-hours CEN was positive for "
                      f"{100 * c['energy_share_cen_positive']:.0f}% of the energy, typically higher than RCE, and the "
                      f"floor at zero drops its negative values. CEN above {c['threshold']:,.0f} PLN/MWh, in "
                      f"{100 * c['energy_share']:.1f}% of the curtailed energy, makes {100 * c['value_share']:.0f}% of "
                      f"the estimate.")
    t = s.get("trend", {})
    yoy = t.get("yoy")
    if yoy:
        first, last = (calendar.month_name[int(k)] for k in yoy["months"].split(".."))
        hours = yoy["hours_ordered"][2]
        out["trend"] = (f"From {first} to {last} {yoy['year']} PSE curtailed {yoy['total_gwh'][1]:,.0f} GWh against "
                        f"{yoy['total_gwh'][0]:,.0f} GWh a year earlier ({100 * yoy['total_gwh'][2]:+.0f}%; PV "
                        f"{100 * yoy['pv_gwh'][2]:+.0f}%, wind {100 * yoy['wind_gwh'][2]:+.0f}%), while the number of "
                        f"hours with orders {'fell' if hours < 0 else 'rose'} by {abs(100 * hours):.0f}%.")
    else:
        out["trend"] = ""
    src = r.sources
    if 2024 in src.index and src.at[2024, "ure_pv"] > 0:
        out["sources"] = (f"For 2024 the announcements and the report add up to {100 * src.at[2024, 'coverage_pv']:.0f}% of the "
                          f"PV and {100 * src.at[2024, 'coverage_wind']:.0f}% of the wind volume that URE reports for TSO "
                          f"orders; a few orders were announced without hourly MW.")
    else:
        out["sources"] = ""
    return out


def write_dashboard(r: Analysis, out_dir: Path, status: dict[str, str] | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    t = texts(r)
    links = {**LEGAL_SOURCES, **{f"ure_{y}": u for y, u in URE_REPORTS.items()}}
    page = TEMPLATE
    replacements = {
        "%%PLOTLY%%": PLOTLY_JS, "%%REPO%%": REPO_URL, "%%KPIS%%": kpi_tiles(r),
        "%%TREND%%": html.escape(t["trend"]), "%%SOURCES_TEXT%%": html.escape(t["sources"]),
        "%%DRIVERS%%": html.escape(t["drivers"]), "%%EXPORT%%": html.escape(t["export"]),
        "%%DAYTYPE%%": html.escape(t["daytype"]), "%%OVERLAP%%": html.escape(t["overlap"]),
        "%%VOLUNTARY%%": html.escape(t["voluntary"]), "%%CEN%%": html.escape(t["cen"]),
        "%%ANNUAL%%": table_html(r.annual, "Year"),
        "%%MONTHLY%%": table_html(r.monthly.iloc[::-1], "Month"),
        "%%TOPDAYS%%": table_html(r.top_days, "Date", TOP_COLS),
        "%%STATUS%%": html.escape(" | ".join(f"{k}: {v}" for k, v in (status or {}).items())),
        "%%GENERATED%%": html.escape(str(r.meta.get("generated_utc", ""))),
        "%%DOWNLOADED%%": html.escape(str(r.meta.get("data_downloaded", ""))),
        "%%FIGURES%%": json.dumps(figures(r), separators=(",", ":")).replace("</", "<\\/"),
    }
    for key, url in links.items():
        replacements[f"%%L_{key}%%"] = url
    for key, value in replacements.items():
        page = page.replace(key, value)
    path = out_dir / "index.html"
    path.write_text(page, encoding="utf-8")
    r.monthly.round(4).to_csv(out_dir / "monthly.csv")
    r.annual.round(4).to_csv(out_dir / "annual.csv")
    return path


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Poland RES Curtailment Tracker</title>
<meta name="description" content="How much PV and wind power the Polish TSO curtails through non-market redispatch, when, why and what it is worth, on PSE open data.">
<script src="%%PLOTLY%%" charset="utf-8"></script>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --border: rgba(11,11,11,0.10); --accent: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --border: rgba(255,255,255,0.10); --accent: #3987e5;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --border: rgba(255,255,255,0.10); --accent: #3987e5;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 0 0 4px; }
h3 { font-size: 15px; margin: 0 0 8px; }
h3 span { color: var(--muted); font-weight: 400; }
p { margin: 4px 0 12px; color: var(--ink2); }
a { color: var(--accent); }
.lead { max-width: 860px; }
.meta { font-size: 13px; color: var(--muted); }
.tile-group { margin: 20px 0 8px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
.tile .label { font-size: 13px; color: var(--ink2); }
.tile .value { font-size: 28px; font-weight: 600; margin: 2px 0; }
.tile .sub { font-size: 12px; color: var(--muted); }
.section-title { margin: 28px 0 0; font-size: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 16px; margin-top: 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 14px 6px;
  min-width: 0; }
.card.wide { grid-column: 1 / -1; }
.chart { width: 100%; height: 340px; }
.note { font-size: 13px; color: var(--muted); }
.legal p, .legal li { font-size: 14px; color: var(--ink2); }
.legal ul { margin: 4px 0 12px; padding-left: 20px; }
.flag { display: inline-block; font-size: 12px; font-weight: 600; color: var(--ink); border: 1px solid var(--border);
  border-radius: 6px; padding: 1px 6px; margin-left: 4px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; width: 100%; }
th, td { padding: 4px 8px; border-bottom: 1px solid var(--grid); text-align: right; white-space: nowrap; }
thead th { color: var(--ink2); font-weight: 600; }
tbody th { text-align: left; font-weight: 600; }
details summary { cursor: pointer; color: var(--accent); margin: 8px 0; }
footer { margin-top: 32px; font-size: 13px; color: var(--muted); }
@media (max-width: 520px) { .grid { grid-template-columns: 1fr; } .chart { height: 300px; } }
</style>
</head>
<body>
<main>
<h1>How much solar and wind power does Poland curtail?</h1>
<p class="lead">A tracker of non-market redispatch of PV and wind ordered by PSE, the Polish transmission system
operator, built from PSE's public data: the curtailed volume every 15 minutes since 24 September 2024 (report
<code>poze-redoze</code>), set against demand, generation, cross-border exchange and prices, and extended back to
December 2023 with PSE's earlier text announcements. Volumes are the reductions PSE ordered, by technology and by
reason: balancing of the power system or network constraints.</p>
<p class="meta">Generated %%GENERATED%% UTC. Data: %%STATUS%%. <a href="%%REPO%%">Code and method</a></p>
%%KPIS%%

<h2 class="section-title">How much</h2>
<div class="grid">
<section class="card wide"><h2>Curtailed energy per month</h2><p>%%TREND%% Hatched bars before 24 September 2024
are the hourly MW of PSE's announcements (ordered reductions, last published version of each day).</p>
<div id="monthly" class="chart" style="height:380px"></div></section>
<section class="card"><h2>Share of potential output</h2><p>Curtailed energy divided by actual plus curtailed output.
The PV denominator is all PV including rooftop systems that are never curtailed, so the share for farms that can be
curtailed is higher.</p><div id="share" class="chart"></div></section>
<section class="card"><h2>Trend: last 12 months</h2><p>Rolling sum over twelve complete months.</p>
<div id="rolling" class="chart"></div></section>
<section class="card"><h2>Comparison with the regulator</h2><p>%%SOURCES_TEXT%% URE reports:
<a href="%%L_ure_2023%%">2023</a>, <a href="%%L_ure_2024%%">2024</a>.</p><div id="sources" class="chart"></div></section>
<section class="card"><h2>Why: network constraints</h2><p>Almost all orders are for balancing (a surplus of generation
over demand and exports). Orders for network constraints are small and tend to fall at positive prices.</p>
<div id="network" class="chart"></div></section>
</div>

<h2 class="section-title">When</h2>
<div class="grid">
<section class="card"><h2>Month and hour of day</h2><p>Mean curtailed power (PV + wind), MW, by local time.</p>
<div id="heat" class="chart" style="height:440px"></div></section>
<section class="card"><h2>Hour of day by technology</h2><p>Total curtailed energy by hour of day since the start of the
report: PV at midday, wind also at night and around holidays.</p><div id="hour_tech" class="chart" style="height:440px"></div></section>
<section class="card"><h2>Low residual load</h2><p>%%DRIVERS%% Labels: share of all curtailed energy in the bin.</p>
<div id="drv_residual" class="chart"></div></section>
<section class="card"><h2>Exports</h2><p>%%EXPORT%%</p><div id="drv_export" class="chart"></div></section>
<section class="card"><h2>Prices</h2><p>Orders by RCE price in the same quarter-hour. RCE is set the day before;
curtailment is ordered close to real time.</p><div id="drv_price" class="chart"></div></section>
<section class="card"><h2>High PV</h2><p>Orders by potential PV output as a share of demand.</p>
<div id="drv_pv_share" class="chart"></div></section>
<section class="card"><h2>Weekends and holidays</h2><p>%%DAYTYPE%%</p><div id="daytype" class="chart"></div></section>
<section class="card"><h2>Days with the most curtailment</h2><p class="note">System-level figures; residual load is
potential (before curtailment).</p><div class="table-wrap">%%TOPDAYS%%</div></section>
</div>

<h2 class="section-title">What it is worth</h2>
<div class="grid">
<section class="card"><h2>Value of the curtailed energy</h2><p>Curtailed energy priced at the RCE market price
(signed, and with negative prices set to zero), and the sales part of the compensation as PSE describes its method:
energy times the imbalance price CEN, zero when CEN is at or below zero. Support schemes (CfD auctions, green
certificates) are compensated on top and cannot be estimated from public data.</p><div id="value" class="chart"></div></section>
<section class="card"><h2>Value per month</h2><p>%%CEN%%</p><div id="value_monthly" class="chart"></div></section>
<section class="card wide legal"><h2>Compensation rules <span class="flag">to verify</span></h2>
<p>Context as read on 26 October 2026 from the sources linked below. The law and PSE's procedures change often;
check the current texts before relying on any of this. This is not legal advice.</p>
<ul>
<li><b>EU law.</b> <a href="%%L_regulation_2019_943%%">Regulation (EU) 2019/943</a>, Art. 13: non-market redispatch is
allowed only when no market-based alternative is available, all market-based resources have been used, too few
facilities are available for competition, or congestion is regular and predictable (para. 3); generation from
renewables may be redispatched downwards only if no other alternative exists or other solutions would result in
significantly disproportionate costs or severe risks to network security (para. 6); non-market redispatch is subject
to financial compensation by the operator that requests it, at least the higher of the additional operating cost and
the net revenues from selling the electricity on the day-ahead market that the facility would have earned, including
volume-based support, except for producers that accepted a connection agreement without a guarantee of firm delivery
(para. 7). Operators report reasons, volumes and measures yearly to the regulator (para. 4).</li>
<li><b>Polish law.</b> The Energy Law (Prawo energetyczne), Art. 9c(7a), lets the TSO order wind and solar units to
switch off or reduce output in the cases of Art. 13(3) and on the principles of Art. 13(6) of the Regulation, subject
to compensation under Art. 13(7); units without active power control (Art. 9c(7f)) are curtailed for balancing only
in a declared threat to security of supply; the yearly report to URE is due by 1 March (Art. 9c(7q)). The rules came
with the amendment of 28 July 2023 (Dz.U. 2023 poz. 1681), in force since 7 September 2023; until the grid code
(IRiESP) sets detailed rules, compensation is calculated and paid under a contract (Art. 30(5) of that act).</li>
<li><b>PSE's method</b>, as described in the <a href="%%L_minister_reply_11689%%">Minister of Energy's reply to
interpellation 11689</a> (24 September 2025): the sales part is the energy not produced times CEN (CRO before
14 June 2024) for each quarter-hour, zero when the price is at or below zero; the support part follows the scheme
(the auction CfD settlement, or the certificate price at the first TGE session after the day); prices of sales
contracts (PPAs) are not used. Owners apply through PSE's portal (PV since October 2024, wind since May 2025); see
<a href="%%L_pse_compensation_conditions%%">conditions of the application</a>, <a href="%%L_pse_pv_page%%">PV</a> and
<a href="%%L_pse_wind_page%%">wind</a> pages. Since 24 June 2025 PSE selects units by their average relative
redispatch coefficient to spread curtailment more evenly.</li>
</ul></section>
</div>

<h2 class="section-title">Negative prices: ordered and voluntary curtailment</h2>
<div class="grid">
<section class="card"><h2>Hours with negative RCE</h2><p>%%OVERLAP%%</p><div id="neg_hours" class="chart"></div></section>
<section class="card"><h2>Expected output in negative-price quarter-hours</h2><p>Expected output = PSE's day-ahead
plan for PV or wind scaled by the ratio of actual to plan in comparable quarter-hours (same month and hour) with a
non-negative price and no order. Output that is neither delivered nor ordered is the unexplained shortfall: market
participants switching off on their own, plus forecast error. %%VOLUNTARY%%</p><div id="voluntary" class="chart"></div></section>
</div>

<section class="card wide" style="margin-top:16px"><h2>Annual figures</h2>
<p class="note">GWh, mln PLN; partial years are marked by coverage. Download: <a href="annual.csv">annual.csv</a>,
<a href="monthly.csv">monthly.csv</a>.</p>
<div class="table-wrap">%%ANNUAL%%</div>
<details><summary>Monthly figures</summary><div class="table-wrap">%%MONTHLY%%</div></details></section>
<footer>
<p>Source: information obtained from www.pse.pl (PSE S.A. public reports, api.raporty.pse.pl: poze-redoze, his-wlk-cal,
rce-pln, crb-rozl, pdgopkd; announcements on www.pse.pl), state as of %%DOWNLOADED%%. The information has been
processed in whole or in part (aggregated, combined, parsed from text); it is not an official PSE publication. URE
figures from its yearly redispatch reports. Not legal or investment advice.</p>
</footer>
</main>
<script>
const FIGS = %%FIGURES%%;
const THEMES = {
  light: { surface: "#fcfcfb", ink: "#0b0b0b", ink2: "#52514e", muted: "#898781", grid: "#e1e0d9", axis: "#c3c2b7",
    wind: "#2a78d6", pv: "#eb6834", aqua: "#1baf7a",
    seq: [[0, "#fcfcfb"], [0.15, "#cde2fb"], [0.4, "#6da7ec"], [0.65, "#2a78d6"], [0.85, "#1c5cab"], [1, "#0d366b"]] },
  dark: { surface: "#1a1a19", ink: "#f0efec", ink2: "#c3c2b7", muted: "#898781", grid: "#2c2c2a", axis: "#383835",
    wind: "#3987e5", pv: "#d95926", aqua: "#199e70",
    seq: [[0, "#1a1a19"], [0.15, "#104281"], [0.4, "#256abf"], [0.65, "#5598e7"], [0.85, "#9ec5f4"], [1, "#e6f0fc"]] },
};
function themeName() {
  const forced = document.documentElement.dataset.theme;
  if (forced === "light" || forced === "dark") return forced;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function resolve(value, t) {
  if (typeof value === "string" && value.startsWith("@") && value.slice(1) in t) return t[value.slice(1)];
  if (Array.isArray(value)) return value.map(v => resolve(v, t));
  if (value && typeof value === "object") {
    const out = {};
    for (const k in value) out[k] = resolve(value[k], t);
    return out;
  }
  return value;
}
function axis(t, extra) {
  return Object.assign({ gridcolor: t.grid, linecolor: t.axis, zerolinecolor: t.axis, tickfont: { color: t.muted },
    title: { font: { color: t.ink2, size: 12 } }, automargin: true }, extra || {});
}
function render() {
  if (!window.Plotly) return;
  const t = THEMES[themeName()];
  for (const id in FIGS) {
    const el = document.getElementById(id);
    if (!el) continue;
    const fig = resolve(FIGS[id], t);
    const lay = fig.layout || {};
    const layout = Object.assign({}, lay, {
      paper_bgcolor: t.surface, plot_bgcolor: t.surface,
      font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: t.ink, size: 12 },
      margin: { l: 56, r: 16, t: 8, b: 40 },
      legend: { orientation: "h", y: -0.2, font: { color: t.ink2 } },
      hoverlabel: { bgcolor: t.surface, bordercolor: t.axis, font: { color: t.ink } },
      xaxis: axis(t, lay.xaxis), yaxis: axis(t, lay.yaxis),
    });
    Plotly.react(el, fig.data, layout, { responsive: true, displaylogo: false });
  }
}
render();
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
</script>
</body>
</html>
"""
