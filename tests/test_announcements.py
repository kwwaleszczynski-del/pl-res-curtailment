"""Parsing of PSE's text announcements on synthetic pages built like the www.pse.pl articles."""
from __future__ import annotations

import pandas as pd
import pytest

from pl_res_curtailment import announcements as ann


def page(body: str, published: str = "13 kwietnia 2024, 10:46") -> str:
    return (f'<html><body><div class="date">{published}</div><div class="journal-content-article">'
            f"<style>.aui .padding-border{{ padding: 30px; }}</style>{body}</div>\n</div></body></html>")


INTRO = ("Ze względu na nadpodaż generacji w KSE oraz konieczność przywrócenia zdolności regulacyjnych KSE, PSE "
         "wprowadzają nierynkową redukcję generacji")


def test_listed_hours_with_struck_values_and_separators():
    html = page("<p>Komunikat o nierynkowym redysponowaniu jednostek wytwórczych PV w KSE w dn. 23.06.2024 "
                f"(aktualizacja)</p><p>{INTRO} w dn. 23.06.2024 w wysokości:</p>"
                "<p>1 417 MW w godz. 07:00 - 08:00,</p><p>2261MW w godz. 08:01 - 09:00,</p>"
                "<p>3289 <s>2897</s> MW&nbsp;w godz. 10:00 - 12:00,</p><p><s>970</s> 1687 MW w godz. 17:01 – 18:00.</p>"
                "<p><s>1417 MW w godz. 07:00 - 08:00</s></p>"
                "<p>PSE announcement on non-market redispatch of PV generation 99 MW w godz. 20:00 - 21:00</p>")
    a = ann.parse_page(html)
    assert a.tech == "pv" and a.update and a.mode == "replace"
    assert a.day == pd.Timestamp(2024, 6, 23)
    assert a.published == pd.Timestamp(2024, 4, 13, 10, 46)
    assert a.hours == {7: 1417.0, 8: 2261.0, 10: 3289.0, 11: 3289.0, 17: 1687.0}


def test_patch_and_stated_formats():
    patch = page("Komunikat o nierynkowym redysponowaniu jednostek wytwórczych PV w KSE w dn. 17.05.2024 "
                 "(aktualizacja) W dniu 17.05.2024 zmieniono wartość redukcji generacji PV. w godz. 10:01 – 11:00 "
                 "z wartości 715 MW na nową wartość 2777 MW w godz. 16:01 - 17:00 387 MW na nową wartość 0 MW.")
    a = ann.parse_page(patch)
    assert a.mode == "patch" and a.hours == {10: 2777.0, 16: 0.0}
    stated = page("Komunikat o nierynkowym redysponowaniu jednostek wytwórczych Farm Wiatrowych w KSE w dn. "
                  f"15.06.2024 (aktualizacja) {INTRO} farm wiatrowych w dn. 15.06.2024 w wysokości: w godz. 11:01 – "
                  "12:00 redukcja wyniesie 173 MW, w godz. 12:01 – 13:00 redukcja wyniesie 337 MW.")
    b = ann.parse_page(stated)
    assert b.tech == "wind" and b.hours == {11: 173.0, 12: 337.0}


@pytest.mark.parametrize("who, tech", [("PV", "pv"), ("Farm Wiatrowych", "wind"),
                                       ("PV i Farm Wiatrowych", "pv+wind"), ("", "unspecified")])
def test_technology_from_title(who, tech):
    a = ann.parse_page(page(f"Komunikat o nierynkowym redysponowaniu jednostek wytwórczych {who} w KSE w "
                            f"02.05.2024 {INTRO} w dn. 02.05.2024 w wysokości: 872 MW w godz. 12:01 - 13:00."))
    assert a.tech == tech and a.day == pd.Timestamp(2024, 5, 2) and a.hours == {12: 872.0}


def test_announcements_without_hourly_volumes():
    press = ann.parse_page(page("PSE poleciły redukcję generacji źródeł OZE ze względów bilansowych 2 lipca 2023 r. "
                                "w godzinach od 11 do 17 wystąpiła nadwyżka podaży.", "3 lipca 2023, 14:52"),
                           title="PSE poleciły redukcję generacji źródeł OZE")
    assert press.hours == {} and press.day == pd.Timestamp(2023, 7, 2) and "press release" in press.note
    capacity = ann.parse_page(page("Komunikat o nierynkowym redysponowaniu jednostek wytwórczych PV w KSE w dn. "
                                   f"31.03.2024 {INTRO} poprzez wydanie polecenia wyłączenia w godz. 12:00 - 17:00 "
                                   "źródeł fotowoltaicznych o łącznej mocy zainstalowanej 3237 MW."))
    assert capacity.hours == {} and "installed capacity" in capacity.note
    assert ann.parse_page("<html>no date</html>") is None


def _a(published, day, hours, update=False, mode=None, tech="pv"):
    return ann.Announcement(pd.Timestamp(published), "t", day=pd.Timestamp(day), tech=tech, update=update,
                            mode=mode or ("replace" if update else "merge"), hours=hours)


def test_combine_replace_merge_patch():
    items = [
        _a("2024-03-10 07:02", "2024-03-10", {7: 649.0, 15: 1011.0, 16: 563.0}),
        _a("2024-03-10 16:00", "2024-03-10", {7: 649.0, 15: 1011.0}, update=True),       # shortened: drops 16
        _a("2024-09-14 22:36", "2024-09-15", {0: 506.0, 1: 1300.0}, tech="wind"),
        _a("2024-09-15 06:29", "2024-09-15", {8: 502.0}, tech="wind"),                    # later hours added
        _a("2024-05-17 08:11", "2024-05-17", {10: 715.0, 11: 745.0}),
        _a("2024-05-17 09:50", "2024-05-17", {10: 2777.0, 16: 0.0}, update=True, mode="patch"),
        ann.Announcement(pd.Timestamp("2023-04-30 11:00"), "press", note="press release without hourly volumes"),
    ]
    hourly, events = ann.combine_announcements(items)
    day = lambda d, t: dict(hourly[(hourly["day"] == pd.Timestamp(d)) & (hourly["technology"] == t)]
                            [["hour", "mw"]].itertuples(index=False))
    assert day("2024-03-10", "pv") == {7: 649.0, 15: 1011.0}
    assert day("2024-09-15", "wind") == {0: 506.0, 1: 1300.0, 8: 502.0}
    assert day("2024-05-17", "pv") == {10: 2777.0, 11: 745.0}                            # 0 MW is not a row
    assert len(events) == 1


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, 0

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls += 1
        text = self.pages[min(self.calls, len(self.pages)) - 1]
        return type("R", (), {"text": text, "raise_for_status": lambda self: None})()


def test_list_pages_stops_when_the_portal_repeats_the_last_page():
    link = '<a href="https://www.pse.pl/x/-/asset_publisher/A/content/{0}?safeargs={1}">{2}</a>'
    p1 = link.format("komunikat-1", "aa", "Komunikat o nierynkowym redysponowaniu 1") + link.format("k-1", "aa", "Więcej...")
    p2 = link.format("komunikat-2", "bb", "Komunikat o nierynkowym redysponowaniu 2")
    p3 = link.format("komunikat-2", "cc", "Komunikat o nierynkowym redysponowaniu 2")   # same article, new args
    session = FakeSession([p1, p2, p3])
    items = ann.list_pages(session, pause=0)
    assert [t for _, t in items] == ["Komunikat o nierynkowym redysponowaniu 1", "Komunikat o nierynkowym redysponowaniu 2"]
    assert session.calls == 3


def test_write_and_read_tables(tmp_path):
    hourly, events = ann.combine_announcements([_a("2024-03-10 07:02", "2024-03-10", {7: 649.0})])
    ann.write_tables(hourly, events, tmp_path)
    h, e = ann.read_tables(tmp_path)
    assert h.loc[0, "day"] == pd.Timestamp(2024, 3, 10) and h.loc[0, "mw"] == 649.0 and e.empty


def test_packaged_tables_match_the_report_on_the_overlap_day():
    hourly, events = ann.packaged_tables()
    sept24 = hourly[hourly["day"] == pd.Timestamp(2024, 9, 24)].set_index("hour")["mw"].to_dict()
    assert sept24 == {12: 817.0, 13: 1042.0, 14: 884.0}       # the report poze-redoze: 817.2, 1042.0, 883.0 MW
    assert hourly["day"].min() == pd.Timestamp(2023, 12, 25)
    assert hourly["day"].max() == pd.Timestamp(2024, 9, 24)
    assert set(hourly["technology"]) <= set(ann.TECH_LABELS)
    monthly = ann.monthly_volumes(hourly)
    assert 450 < monthly["pv"].sum() < 600 and 50 < monthly["wind"].sum() < 100
    assert len(events) >= 5
