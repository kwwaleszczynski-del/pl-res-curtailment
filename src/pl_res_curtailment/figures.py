"""Static PNG figures for the README (matplotlib, light theme).

Colour roles (validated categorical slots): wind = blue, PV = orange, third measure = aqua; a technology that is not
stated is neutral grey; announcements before the PSE report are hatched.

Usage:
    paths = save_all(result, Path("docs/img"))
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from pl_res_curtailment.analysis import DRIVERS, FULL, Analysis, negative_shares  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
WIND, PV, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SEQ = LinearSegmentedColormap.from_list("blue", ["#fcfcfb", "#cde2fb", "#6da7ec", "#2a78d6", "#1c5cab", "#0d366b"])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"], "font.size": 10,
    "text.color": INK, "axes.labelcolor": INK2, "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
    "axes.titlesize": 11, "axes.titleweight": "semibold", "axes.titlelocation": "left",
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "lines.linewidth": 2,
    "hatch.color": SURFACE, "hatch.linewidth": 1.2, "axes.axisbelow": True,
})


def _months(index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime([f"{m}-01" for m in index]))


def fig_monthly(r: Analysis):
    m, lg = r.monthly, r.legacy_monthly
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9.5, 6.6), sharex=True, gridspec_kw={"height_ratios": [1.6, 1]})
    w = 24
    if len(lg):
        x = _months(lg.index)
        bottom = np.zeros(len(lg))
        for col, colour, label in (("pv", PV, "PV (announcements)"), ("wind", WIND, "Wind (announcements)")):
            if col in lg:
                a1.bar(x, lg[col], w, bottom=bottom, color=colour, alpha=0.55, hatch="///", label=label,
                       edgecolor=SURFACE, linewidth=0.8)
                bottom += lg[col].to_numpy()
        other = lg.drop(columns=[c for c in ("pv", "wind") if c in lg]).sum(axis=1)
        if other.sum() > 0:
            a1.bar(x, other, w, bottom=bottom, color=MUTED, alpha=0.7, hatch="///", label="Not split (announcements)",
                   edgecolor=SURFACE, linewidth=0.8)
    x = _months(m.index)
    # September 2024 has both sources: the report part is stacked on top of the announcements
    base = lg.sum(axis=1).reindex(m.index).fillna(0.0).to_numpy() if len(lg) else np.zeros(len(m))
    a1.bar(x, m["pv_gwh"], w, bottom=base, color=PV, label="PV (PSE report)", edgecolor=SURFACE, linewidth=0.8)
    a1.bar(x, m["wind_gwh"], w, bottom=base + m["pv_gwh"].to_numpy(), color=WIND, label="Wind (PSE report)",
           edgecolor=SURFACE, linewidth=0.8)
    a1.grid(axis="x", visible=False)
    a1.set_ylabel("GWh per month")
    a1.set_title("Curtailment ordered by PSE (non-market redispatch), GWh per month")
    a1.legend(loc="upper left", ncols=3, fontsize=8.5)
    full = m[m["coverage"] >= FULL]
    xf = _months(full.index)
    a2.plot(xf, 100 * full["pv_share"], color=PV, marker="o", ms=4, label="PV")
    a2.plot(xf, 100 * full["wind_share"], color=WIND, marker="o", ms=4, label="Wind")
    a2.set_ylabel("% of potential output")
    a2.set_title("Curtailed share of potential output (actual + curtailed)")
    a2.legend(loc="upper left", ncols=2, fontsize=9)
    fig.tight_layout()
    return fig


def fig_when(r: Analysis):
    p = r.profile.loc[[i for i in r.profile.index if r.monthly.at[i, "coverage"] >= FULL]]
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    im = ax.imshow(p.to_numpy(), aspect="auto", cmap=SEQ, vmin=0, interpolation="nearest")
    ax.set_yticks(range(len(p)), p.index, fontsize=8)
    ax.set_xticks(range(0, 24, 2), [f"{h:02d}:00" for h in range(0, 24, 2)])
    ax.grid(False)
    ax.set_xlabel("local time (start of hour)")
    ax.set_title("When: mean curtailed power by month and hour of day (MW, PV + wind)")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED)
    fig.tight_layout()
    return fig


def fig_drivers(r: Analysis):
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    for ax, name in zip(axes.flat[:3], ("residual", "export", "price")):
        d = r.drivers[name]
        x = np.arange(len(d))
        ax.bar(x, 100 * d["p_order"], 0.62, color=WIND)
        for i, (p, s) in enumerate(zip(d["p_order"], d["share_of_energy"])):
            ax.text(i, 100 * p + 2, f"{100 * s:.0f}%", ha="center", fontsize=8, color=INK2)
        ax.set_xticks(x, d.index, fontsize=8, rotation=20)
        ax.grid(axis="x", visible=False)
        ax.set_ylim(0, 112)
        ax.set_ylabel("% of quarter-hours with an order")
        ax.set_title(DRIVERS[name][3].split(":")[0])
    dt = r.daytype.reset_index()
    ax = axes.flat[3]
    labels = {"workday": "Workday", "saturday": "Saturday", "sunday_holiday": "Sunday / holiday"}
    x = np.arange(3)
    for k, (season, colour) in enumerate((("Apr-Sep", PV), ("Oct-Mar", WIND))):
        s = dt[dt["season"] == season].set_index("day_type").reindex(list(labels))
        ax.bar(x + (k - 0.5) * 0.36, s["mean_gwh_per_day"], 0.34, color=colour, label=season)
    ax.set_xticks(x, list(labels.values()))
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("GWh per day")
    ax.set_title("Mean curtailment per day by day type")
    ax.legend(fontsize=9)
    fig.suptitle("Bars: share of quarter-hours with a PSE order; labels: share of all curtailed energy in the bin",
                 fontsize=9, color=INK2, x=0.01, ha="left")
    fig.tight_layout()
    return fig


def fig_value(r: Analysis):
    a = r.annual
    fig, ax = plt.subplots(figsize=(9, 4.4))
    x = np.arange(len(a))
    cols = (("value_rce", "Energy x RCE", AXIS), ("value_rce_floor", "Energy x max(RCE, 0)", INK2),
            ("value_cen_floor", "Energy x max(CEN, 0): PSE method, sales part", AQUA))
    for k, (c, label, colour) in enumerate(cols):
        bars = ax.bar(x + (k - 1) * 0.27, a[c], 0.25, color=colour, label=label)
        ax.bar_label(bars, fmt="%.0f", fontsize=8, color=INK2, padding=2)
    ax.set_xticks(x, [f"{y}{'' if c >= FULL else ' (part)'}" for y, c in zip(a.index, a["coverage"])])
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("mln PLN")
    ax.set_title("Value of the curtailed energy")
    ax.legend(fontsize=8.5, loc="upper left")
    fig.tight_layout()
    return fig


def fig_negative(r: Analysis):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.4), gridspec_kw={"width_ratios": [1.6, 1]})
    m = r.monthly
    x = _months(m.index)
    a1.bar(x, m["neg_qh_ordered"] / 4, 24, color=WIND, label="with a PSE order")
    a1.bar(x, (m["neg_qh"] - m["neg_qh_ordered"]) / 4, 24, bottom=m["neg_qh_ordered"] / 4, color=AXIS,
           label="without an order")
    a1.grid(axis="x", visible=False)
    a1.set_ylabel("hours")
    a1.set_title("Hours with a negative RCE price")
    a1.legend(fontsize=9, loc="upper left")
    s = negative_shares(r.voluntary)
    xs = np.arange(len(s))
    for k, (c, label, colour) in enumerate((("ordered", "ordered by PSE", WIND),
                                            ("shortfall", "unexplained shortfall", AQUA))):
        bars = a2.bar(xs + (k - 0.5) * 0.36, s[c], 0.34, color=colour, label=label)
        a2.bar_label(bars, fmt="%.1f%%", fontsize=8, color=INK2, padding=2)
    a2.axhline(0, color=AXIS, lw=0.8)
    a2.set_xticks(xs, ["PV" if t == "pv" else "Wind" for t in s.index])
    a2.grid(axis="x", visible=False)
    a2.set_ylabel("% of expected output")
    a2.set_title("Negative-price quarter-hours: output not delivered")
    a2.legend(fontsize=8.5, loc="upper right")
    fig.tight_layout()
    return fig


FIGURES = {"monthly_volumes": fig_monthly, "when": fig_when, "drivers": fig_drivers, "value": fig_value,
           "negative_prices": fig_negative}


def save_all(r: Analysis, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, make in FIGURES.items():
        fig = make(r)
        path = out_dir / f"{name}.png"
        fig.savefig(path, dpi=110)
        plt.close(fig)
        paths.append(path)
    return paths
