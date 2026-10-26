from datetime import date

import pandas as pd
import pytest

from conftest import FakeClient, pse_frames, synthetic_frame
from pl_res_curtailment.data import COLUMNS, combine, load_frame, redispatch_part


@pytest.fixture(scope="module")
def short():
    return synthetic_frame(date(2025, 3, 28), date(2025, 4, 3), seed=3)


def test_redispatch_sign_and_empty_values(short):
    raw = pse_frames(short)["poze-redoze"]
    part = redispatch_part(raw)
    assert (part >= 0).all().all()
    assert part.notna().all().all()
    assert part["pv_balance"].sum() == pytest.approx(short["pv_balance"].sum())
    assert (raw["pv_red_balance"].isna() == (part["pv_balance"] == 0).to_numpy()).all()


def test_combine_restores_columns(short):
    out = combine(pse_frames(short))
    assert list(out.columns) == COLUMNS
    assert len(out) == len(short)
    assert out.index[0] == short.index[0]
    pd.testing.assert_series_equal(out["exchange"], short["exchange"], check_names=False, check_index_type=False,
                                   check_freq=False)
    assert out["rce"].sum() == pytest.approx(short["rce"].sum())


def test_combine_keeps_redispatch_rows_when_other_series_are_missing(short):
    raw = pse_frames(short)
    raw["crb-rozl"] = raw["crb-rozl"].iloc[:-96]          # imbalance prices published a day later
    out = combine(raw)
    assert len(out) == len(short)
    assert out["cen"].isna().sum() == 96


def test_load_frame_requests_whole_months_and_clips(short):
    client = FakeClient(pse_frames(short))
    out, last = load_frame(client, date(2025, 3, 29), date(2025, 4, 2))
    assert {(s, e) for _, s, e in client.calls} == {(date(2025, 3, 1), date(2025, 4, 30))}
    local_days = sorted({t.date() for t in out.index.tz_convert("Europe/Warsaw")})
    assert local_days[0] == date(2025, 3, 29) and local_days[-1] == date(2025, 4, 2)
    assert len(out) == 92 + 96 * 4                           # 30 March 2025 is the spring DST day
    assert last["his-wlk-cal"] == out.index.max()


def test_load_frame_without_redispatch_data(short):
    frames = pse_frames(short)
    frames["poze-redoze"] = frames["poze-redoze"].iloc[0:0]
    out, _ = load_frame(FakeClient(frames), date(2025, 3, 29), date(2025, 4, 2))
    assert out.empty
