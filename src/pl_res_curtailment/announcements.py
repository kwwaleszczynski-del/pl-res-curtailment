"""Hourly curtailment volumes from PSE's text announcements, December 2023 - September 2024.

Before the report ``poze-redoze`` started (business day 2024-09-24), PSE announced each non-market curtailment of
PV and wind on www.pse.pl ("Komunikat o nierynkowym redysponowaniu jednostek wytwórczych ... w KSE w dn.
DD.MM.YYYY") with the ordered reduction in MW for each hour. This module pages through the announcement list,
parses the hourly values and keeps the last published version of each day and technology. The parsed tables ship
with the package (``data/announcements_hourly.csv``, ``data/announcements_events.csv``), so the analysis never needs
the website; ``python -m pl_res_curtailment announcements`` downloads the pages again and rebuilds them.

Parsing rules:
    - struck-through values (<s>, <del>, <strike>) are superseded values and are dropped;
    - "1 135 MW w godz. 10:00 - 11:00" and "... 10:01 - 11:00" both mean the local clock hour 10:00-11:00,
      "07:01 - 09:00" means two hours;
    - "w godz. 10:01 - 11:00 z wartości 715 MW na nową wartość 2777 MW" and "w godz. 11:01 - 12:00 redukcja wyniesie
      173 MW" are read as well; the first form patches single hours of an earlier announcement;
    - an announcement titled "aktualizacja" replaces the earlier hours of its day and technology, another
      announcement for the same day adds hours (PSE issued separate notices for later hours of a day);
    - announcements without hourly MW (press releases of 2022-2023, an order given as installed capacity) are kept
      as events without volume.

Usage:
    pages = download_pages(Path("data/announcements"))
    hourly, events = build_tables(pages)
    hourly, events = packaged_tables()
"""
from __future__ import annotations

import binascii
import hashlib
import html
import logging
import re
import time
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("pl_res_curtailment")

LIST_URL = "https://www.pse.pl/informacje-o-pracy-systemu-elektroenergetycznego"
_PORTLET = "101_INSTANCE_Rt2wKqPRCy71"
_MONTHS = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6, "lipca": 7,
           "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12}
_HOURS = r"(\d{1,2})[:.](\d\d)\s*[-–]\s*(\d{1,2})[:.](\d\d)"
_RELEVANT = ("redysponow", "redukcj", "ograniczenie generacji")
TECH_LABELS = {"pv": "PV", "wind": "Wind", "pv+wind": "PV and wind (not split)",
               "unspecified": "Technology not stated"}


@dataclass
class Page:
    url: str
    title: str
    html: str


@dataclass
class Announcement:
    published: pd.Timestamp          # display date of the article, Polish local time (naive)
    title: str
    day: pd.Timestamp | None = None  # day of the curtailment
    tech: str | None = None          # pv, wind, pv+wind, unspecified
    update: bool = False             # title says "aktualizacja"
    mode: str = "merge"              # merge, replace or patch
    hours: dict[int, float] = field(default_factory=dict)   # local clock hour -> MW
    note: str = ""


def _session_get(session: requests.Session, url: str, **kw) -> str:
    r = session.get(url, headers={"User-Agent": "Mozilla/5.0 (pl-res-curtailment)"}, timeout=60, **kw)
    r.raise_for_status()
    return r.text


def list_pages(session: requests.Session, max_pages: int = 40, pause: float = 1.0) -> list[tuple[str, str]]:
    """(url, title) of all articles in the PSE list "Informacje o pracy systemu elektroenergetycznego"."""
    items: list[tuple[str, str]] = []
    for cur in range(1, max_pages + 1):
        p = f"_{_PORTLET}_"
        query = (f"p_p_id={_PORTLET}&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view&p_p_col_id=column-2"
                 f"&p_p_col_count=1&{p}delta=10&{p}keywords=&{p}advancedSearch=false&{p}andOperator=true"
                 f"&p_r_p_564233524_resetCur=false&{p}cur={cur}")
        text = _session_get(session, LIST_URL, params={"safeargs": binascii.hexlify(query.encode()).decode()})
        found = [(html.unescape(u), html.unescape(t).strip()) for u, t in
                 re.findall(r'<a[^>]+href="([^"]*/content/[^"]+)"[^>]*>\s*([^<]{10,300}?)\s*</a>', text)]
        seen = {u.split("?")[0] for u, _ in items}
        new = {u.split("?")[0]: (u, t) for u, t in found if not t.startswith("Więcej") and u.split("?")[0] not in seen}
        log.info("announcement list page %d: %d new articles", cur, len(new))
        if not new:      # past the last page the portal repeats the last one
            break
        items += new.values()
        time.sleep(pause)
    return items


def download_pages(cache_dir: Path, pause: float = 1.0, session: requests.Session | None = None) -> list[Page]:
    """Article pages about curtailment, cached as HTML files in ``cache_dir`` (the list is always read again)."""
    session = session or requests.Session()
    cache_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for url, title in list_pages(session, pause=pause):
        if not any(k in title.lower() for k in _RELEVANT):
            continue
        path = cache_dir / (hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:12] + ".html")
        if not path.exists():
            path.write_text(_session_get(session, url), encoding="utf-8")
            time.sleep(pause)
        pages.append(Page(url, title, path.read_text(encoding="utf-8")))
    log.info("%d announcement pages", len(pages))
    return pages


def article_text(page_html: str) -> str:
    """Polish text of the article body with struck-through values removed."""
    m = re.search(r'<div class="journal-content-article">(.*?)</div>\s*</div>', page_html, re.S)
    body = m.group(1) if m else page_html
    body = re.sub(r"<(s|del|strike)\b[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body)).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    end = text.find("PSE announcement")
    return text[:end].strip() if end > 0 else text


def _published(page_html: str) -> pd.Timestamp | None:
    m = re.search(r"(\d{1,2}) ([a-ząćęłńóśźż]+) (\d{4}), (\d\d):(\d\d)", page_html)
    if not m or m.group(2) not in _MONTHS:
        return None
    return pd.Timestamp(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)), int(m.group(4)), int(m.group(5)))


def _hours(h1: str, m1: str, h2: str, m2: str) -> list[int]:
    """Clock hours covered by "h1:m1 - h2:m2" ("12:01 - 13:00" and "12:00 - 13:00" are both hour 12)."""
    end = int(h2) if int(m2) == 0 else int(h2) + 1
    return list(range(int(h1), end))


def parse_page(page_html: str, title: str = "") -> Announcement | None:
    """One article; None when it has no publication date."""
    published = _published(page_html)
    if published is None:
        return None
    text = article_text(page_html)
    head = re.search(r"Komunikat o nierynkowym redysponowaniu jednostek wytwórczych\s*(.*?)\s*w KSE\s*w\s*"
                     r"(?:dn\.\s*)?(\d\d)\.(\d\d)\.(\d{4})(.{0,40})", text)
    if head is None:
        m = re.search(r"(\d{1,2}) ([a-ząćęłńóśźż]+) (\d{4}) r\.", text)
        day = (pd.Timestamp(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
               if m and m.group(2) in _MONTHS else None)
        return Announcement(published, title or text[:120], day=day, note="press release without hourly volumes")
    who = head.group(1)
    tech = ("pv+wind" if re.search(r"PV i", who) else "pv" if who.strip() == "PV"
            else "wind" if "Wiatr" in who else "unspecified")
    a = Announcement(published, title or head.group(0).strip(), tech=tech,
                     day=pd.Timestamp(int(head.group(4)), int(head.group(3)), int(head.group(2))),
                     update="aktualizacja" in head.group(5).lower())
    patches = re.findall(r"w godz\.?\s*" + _HOURS + r",?\s*(?:z wartości\s*)?(\d+)\s*MW\s*na nową wartość\s*(\d+)"
                         r"\s*MW", text)
    stated = re.findall(r"w godz\.?\s*" + _HOURS + r"\s*redukcja wyniesie\s*(\d+)\s*MW", text)
    listed = re.findall(r"(\d{1,2}(?: \d{3})+|\d+)\s*MW\s*w godz\.?\s*" + _HOURS, text)
    if patches:
        a.mode = "patch"
        for h1, m1, h2, m2, _old, new in patches:
            a.hours.update({h: float(new) for h in _hours(h1, m1, h2, m2)})
    else:
        a.mode = "replace" if a.update else "merge"
        for h1, m1, h2, m2, mw in stated:
            a.hours.update({h: float(mw) for h in _hours(h1, m1, h2, m2)})
        for mw, h1, m1, h2, m2 in listed:
            a.hours.update({h: float(mw.replace(" ", "")) for h in _hours(h1, m1, h2, m2)})
    if not a.hours:
        a.note = ("estimated total reduction without hourly values" if "Szacunkowa" in text
                  else "order stated as installed capacity, not as hourly MW" if "mocy zainstalowanej" in text
                  else "no hourly MW in the announcement")
    return a


def combine_announcements(items: list[Announcement]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(hourly volumes, events without volume) from parsed articles, in order of publication."""
    state: dict[tuple, dict[int, float]] = {}
    source: dict[tuple, pd.Timestamp] = {}
    events = []
    for a in sorted(items, key=lambda x: x.published):
        if not a.hours:
            events.append({"published": a.published, "day": a.day, "technology": a.tech, "title": a.title,
                           "note": a.note})
            continue
        key = (a.day, a.tech)
        current = {} if a.mode == "replace" else state.get(key, {})
        state[key] = {**current, **a.hours}
        source[key] = a.published
    rows = [{"day": day, "hour": h, "technology": tech, "mw": mw, "published": source[(day, tech)]}
            for (day, tech), hours in state.items() for h, mw in hours.items() if mw > 0]
    hourly = pd.DataFrame(rows, columns=["day", "hour", "technology", "mw", "published"])
    hourly = hourly.sort_values(["day", "technology", "hour"]).reset_index(drop=True)
    events = pd.DataFrame(events, columns=["published", "day", "technology", "title", "note"])
    return hourly, events.sort_values("published").reset_index(drop=True)


def build_tables(pages: list[Page]) -> tuple[pd.DataFrame, pd.DataFrame]:
    parsed = [a for a in (parse_page(p.html, p.title) for p in pages) if a is not None]
    return combine_announcements(parsed)


def write_tables(hourly: pd.DataFrame, events: pd.DataFrame, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, frame in (("announcements_hourly.csv", hourly), ("announcements_events.csv", events)):
        frame = frame.copy()
        for col in ("day", "published"):
            frame[col] = [None if pd.isna(v) else (f"{v:%Y-%m-%d}" if col == "day" else f"{v:%Y-%m-%d %H:%M}")
                          for v in frame[col]]
        frame.to_csv(folder / name, index=False, lineterminator="\n")
        out.append(folder / name)
    return out


def read_tables(folder: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tables written by ``write_tables``; by default the copies shipped with the package."""
    def read(name: str) -> pd.DataFrame:
        if folder is not None:
            return pd.read_csv(folder / name)
        with resources.files("pl_res_curtailment").joinpath("data", name).open("r", encoding="utf-8") as fh:
            return pd.read_csv(fh)
    hourly, events = read("announcements_hourly.csv"), read("announcements_events.csv")
    hourly["day"] = pd.to_datetime(hourly["day"])
    events["day"] = pd.to_datetime(events["day"])
    return hourly, events


def packaged_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    return read_tables(None)


def monthly_volumes(hourly: pd.DataFrame) -> pd.DataFrame:
    """GWh per month (index 'YYYY-MM') and technology; each hourly MW value is one hour of reduction."""
    if hourly.empty:
        return pd.DataFrame()
    month = pd.to_datetime(hourly["day"]).dt.strftime("%Y-%m")
    out = hourly.pivot_table(index=month, columns="technology", values="mw", aggfunc="sum").fillna(0.0) / 1000
    out.index.name = "month"
    return out
