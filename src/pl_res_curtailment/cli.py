"""Command line interface.

Usage:
    python -m pl_res_curtailment fetch                          # download / refresh the PSE data cache only
    python -m pl_res_curtailment report                         # tables in results/, README figures in docs/img/
    python -m pl_res_curtailment dashboard --out docs           # static HTML dashboard for GitHub Pages
    python -m pl_res_curtailment report --offline --end 2026-10-25   # rebuild from the cache, fixed last day
    python -m pl_res_curtailment announcements                  # re-parse PSE's 2023-2024 announcements

Data are cached as monthly Parquet files in ./data (override with --data-dir or PLRC_DATA_DIR). The last day
analysed is yesterday (Europe/Warsaw) unless --end is given. Exit code 2 means that no redispatch or system data
were available, so nothing was written.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from pl_res_curtailment import announcements as ann
from pl_res_curtailment.analysis import Analysis, analyse
from pl_res_curtailment.data import HISTORY_START, TZ, load_frame, make_client

log = logging.getLogger("pl_res_curtailment")


def _date(s: str) -> date:
    return date.fromisoformat(s)


def _local(ts: pd.Timestamp | None) -> str:
    return "no data" if ts is None or pd.isna(ts) else f"{(ts + pd.Timedelta(minutes=15)).tz_convert(TZ):%Y-%m-%d %H:%M}"


def _downloaded(args) -> str:
    """Date the PSE data were obtained: today, or the newest cache file when running offline."""
    files = list(args.data_dir.rglob("*.parquet"))
    if args.offline and files:
        return f"{datetime.fromtimestamp(max(f.stat().st_mtime for f in files)):%Y-%m-%d}"
    return f"{date.today():%Y-%m-%d}"


def run_analysis(args) -> tuple[Analysis, dict[str, str]] | None:
    client = make_client(args.data_dir, offline=args.offline)
    frame, last = load_frame(client, HISTORY_START, args.end)
    if frame.empty or frame["demand"].notna().sum() == 0:
        log.error("no redispatch or system data from the API or the cache - nothing written")
        return None
    hourly, _ = ann.packaged_tables()
    meta = {
        "generated_utc": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M}",
        "data_downloaded": _downloaded(args),
        "last_day": f"{args.end:%Y-%m-%d}",
        "last_order_local_end": _local(last.get("poze-redoze")),
        "last_system_local_end": _local(last.get("his-wlk-cal")),
        "last_cen_local_end": _local(last.get("crb-rozl")),
    }
    result = analyse(frame, announcements=hourly, meta=meta)
    status = {"redispatch report to": f"{args.end:%Y-%m-%d}", "imbalance prices to": meta["last_cen_local_end"]}
    return result, status


def write_report(result: Analysis, results_dir: Path, img_dir: Path | None) -> None:
    from pl_res_curtailment.figures import save_all

    results_dir.mkdir(parents=True, exist_ok=True)
    result.monthly.round(4).to_csv(results_dir / "monthly.csv")
    result.annual.round(4).to_csv(results_dir / "annual.csv")
    result.value.round(4).to_csv(results_dir / "value.csv")
    result.profile.round(1).to_csv(results_dir / "month_hour_mw.csv")
    result.daytype.round(4).to_csv(results_dir / "day_type.csv")
    result.top_days.round(3).to_csv(results_dir / "top_days.csv")
    result.overlap.round(4).to_csv(results_dir / "negative_prices.csv")
    result.voluntary.round(4).to_csv(results_dir / "voluntary_shortfall.csv", index=False)
    result.sources.round(2).to_csv(results_dir / "sources.csv")
    result.legacy_monthly.round(3).to_csv(results_dir / "announcements_monthly.csv")
    pd.concat({k: v for k, v in result.drivers.items()}, names=["driver", "bin"]).round(4).to_csv(
        results_dir / "drivers.csv")
    summary = result.summary()
    summary["meta"] = {k: v for k, v in summary["meta"].items() if k != "generated_utc"}   # stable between runs
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log.info("tables written to %s", results_dir)
    if img_dir is not None:
        for path in save_all(result, img_dir):
            log.info("figure %s", path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pl-res-curtailment", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "report", "dashboard", "announcements"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", type=Path, default=Path(os.environ.get("PLRC_DATA_DIR", "data")))
        p.add_argument("-v", "--verbose", action="store_true")
        if name == "announcements":
            p.add_argument("--out", type=Path, default=Path(__file__).parent / "data",
                           help="folder for the parsed CSV tables (default: the package data)")
            continue
        p.add_argument("--end", type=_date, default=None, help="last business day (default: yesterday, Warsaw)")
        p.add_argument("--offline", action="store_true", help="use the cache only, no API calls")
        if name == "report":
            p.add_argument("--results", type=Path, default=Path("results"), help="folder for CSV/JSON tables")
            p.add_argument("--img", type=Path, default=Path("docs/img"), help="folder for README figures")
            p.add_argument("--no-figures", action="store_true")
        if name == "dashboard":
            p.add_argument("--out", type=Path, default=Path("docs"), help="output folder of the static page")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "announcements":
        pages = ann.download_pages(args.data_dir / "announcements")
        hourly, events = ann.build_tables(pages)
        for path in ann.write_tables(hourly, events, args.out):
            log.info("written %s", path)
        return 0
    if args.end is None:
        args.end = pd.Timestamp.now(tz=TZ).date() - timedelta(days=1)
    if args.cmd == "fetch":
        load_frame(make_client(args.data_dir, offline=args.offline), HISTORY_START, args.end)
        return 0
    analysed = run_analysis(args)
    if analysed is None:
        return 2
    result, status = analysed
    if args.cmd == "report":
        write_report(result, args.results, None if args.no_figures else args.img)
    else:
        from pl_res_curtailment.dashboard import write_dashboard

        path = write_dashboard(result, args.out, status=status)
        log.info("dashboard written to %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
