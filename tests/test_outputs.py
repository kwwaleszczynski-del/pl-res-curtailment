"""PNG figures, HTML dashboard and the CLI end to end on synthetic data (no network)."""
from __future__ import annotations

import json
import re
from datetime import date

import pytest

from conftest import FakeClient, pse_frames, synthetic_frame
from pl_res_curtailment import cli, figures
from pl_res_curtailment.analysis import analyse
from pl_res_curtailment.announcements import packaged_tables
from pl_res_curtailment.dashboard import figures as dashboard_figures
from pl_res_curtailment.dashboard import write_dashboard


@pytest.fixture(scope="module")
def result(frame):
    return analyse(frame, announcements=packaged_tables()[0], meta={"data_downloaded": "2026-07-01",
                                                                    "generated_utc": "2026-07-01 06:30"})


def test_figures_are_written(result, tmp_path):
    paths = figures.save_all(result, tmp_path)
    assert [p.name for p in paths] == [f"{k}.png" for k in figures.FIGURES]
    assert all(p.stat().st_size > 10_000 for p in paths)


def test_dashboard_page(result, tmp_path):
    path = write_dashboard(result, tmp_path, status={"redispatch report to": "2026-06-30"})
    page = path.read_text(encoding="utf-8")
    assert "%%" not in page
    for fig_id in dashboard_figures(result):
        assert f'id="{fig_id}"' in page
    assert "https://cdn.plot.ly/plotly-2.35.2.min.js" in page
    assert "to verify" in page and "not legal advice" in page.lower()
    assert "www.pse.pl" in page and "2026-07-01" in page
    data = json.loads(re.search(r"const FIGS = (\{.*?\});\nconst THEMES", page, re.S).group(1).replace("<\\/", "</"))
    assert len(data["monthly"]["data"]) >= 4                  # announcements + report traces
    assert (tmp_path / "annual.csv").exists() and (tmp_path / "monthly.csv").exists()


@pytest.fixture()
def fake_api(monkeypatch):
    frames = pse_frames(synthetic_frame(date(2026, 3, 1), date(2026, 5, 31), seed=7))
    client = FakeClient(frames)
    monkeypatch.setattr(cli, "make_client", lambda data_dir, offline=False: client)
    return client


def test_cli_report_and_dashboard(fake_api, tmp_path):
    results, img, docs = tmp_path / "results", tmp_path / "img", tmp_path / "docs"
    args = ["--data-dir", str(tmp_path / "data"), "--end", "2026-05-31"]
    assert cli.main(["report", *args, "--results", str(results), "--img", str(img)]) == 0
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    assert "generated_utc" not in summary["meta"] and summary["meta"]["last_day"] == "2026-05-31"
    assert summary["period"]["last_interval_utc"] == "2026-05-31 21:45"
    for name in ("monthly.csv", "annual.csv", "drivers.csv", "voluntary_shortfall.csv", "top_days.csv"):
        assert (results / name).exists()
    assert len(list(img.glob("*.png"))) == len(figures.FIGURES)
    assert cli.main(["dashboard", *args, "--out", str(docs)]) == 0
    assert (docs / "index.html").exists()


def test_cli_exit_code_without_data(monkeypatch, tmp_path):
    frames = pse_frames(synthetic_frame(date(2026, 3, 1), date(2026, 3, 5)))
    frames["poze-redoze"] = frames["poze-redoze"].iloc[0:0]
    monkeypatch.setattr(cli, "make_client", lambda data_dir, offline=False: FakeClient(frames))
    assert cli.main(["dashboard", "--data-dir", str(tmp_path), "--end", "2026-03-05", "--out", str(tmp_path)]) == 2
    assert not (tmp_path / "index.html").exists()
