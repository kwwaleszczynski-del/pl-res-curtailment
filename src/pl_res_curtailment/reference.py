"""Annual redispatch volumes reported by the Polish regulator (URE) and the sources of the legal context.

URE publishes a yearly summary of the redispatch reports that the TSO (PSE) and the DSOs file under Art. 13(4) of
Regulation (EU) 2019/943 and Art. 9c(7q) of the Polish Energy Law. The figures below are transcribed by hand from
those PDFs (MWh) and are used as a cross-check and to extend the trend before the PSE report starts.

Usage:
    ure_annual()            # tidy frame: year, ordered_by, technology, reason, mwh
"""
from __future__ import annotations

import pandas as pd

URE_REPORTS = {
    2023: "https://www.ure.gov.pl/download/9/15075/Sprawozdanie-redysponowanie.pdf",
    2024: "https://www.ure.gov.pl/download/9/15780/Sprawozdaniedotredysponowaniaza2024r.pdf",
}

# year, ordered by, technology, reason, MWh (non-market redispatch outside the balancing market)
_URE_ROWS = [
    (2023, "TSO", "pv", "total", 24_256.0),
    (2023, "TSO", "wind", "total", 41_816.0),
    (2023, "DSO", "pv", "network", 3_228.0),
    (2023, "DSO", "wind", "network", 934.0),
    (2024, "TSO", "pv", "balancing", 595_168.4),
    (2024, "TSO", "pv", "network", 2_095.7),
    (2024, "TSO", "wind", "balancing", 118_047.6),
    (2024, "TSO", "wind", "network", 7_027.7),
    (2024, "DSO", "pv", "network", 24_121.1),
    (2024, "DSO", "wind", "network", 2_799.6),
]

LEGAL_SOURCES = {
    "regulation_2019_943": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02019R0943-20240716",
    "minister_reply_11689": "https://api.sejm.gov.pl/sejm/term10/interpellations/attachment/ATTDLZHXH/i11689-o1.pdf",
    "pse_compensation_conditions": "https://www.pse.pl/documents/20182/4168830618/Warunki_skladania_Wniosku_o_rekompensate.pdf",
    "pse_pv_page": "https://www.pse.pl/instalacje-pv",
    "pse_wind_page": "https://www.pse.pl/instalacje-fw",
}


def ure_annual() -> pd.DataFrame:
    return pd.DataFrame(_URE_ROWS, columns=["year", "ordered_by", "technology", "reason", "mwh"])


def ure_tso_totals() -> pd.DataFrame:
    """GWh ordered by the TSO per year and technology (index year, columns pv, wind)."""
    u = ure_annual()
    u = u[u["ordered_by"] == "TSO"]
    return u.pivot_table(index="year", columns="technology", values="mwh", aggfunc="sum") / 1000
