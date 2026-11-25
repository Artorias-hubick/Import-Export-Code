"""Читає ціни РДН, перетини й курс з Google Таблиці у простий словник для сайту та звіту.

Усі години — за CET (як у колонках C..Z таблиці). РДН UA — у грн, решта — EUR.
Результат:
  {"rdn": {"UA": {"2026-11-25": [24 значення або None], ...}, ...},
   "cross": {"UA-PL": {...}, ...},
   "fx": {"2026-11-25": 48.65, ...}}     # купівля EUR, Ощадбанк (лист «Архів курсу»)
"""
from __future__ import annotations

import datetime as dt

import gsheet

START = dt.date(2024, 1, 1)
HOURS = 24

RDN_SHEETS = {"UA": "РДН UA", "SK": "РДН SK", "PL": "РДН PL", "HU": "РДН HUN", "RO": "РДН RO", "MD": "РДН MD"}
CROSS_SHEETS = {
    "UA-PL": "Прайс Перетину UA-PL", "PL-UA": "Прайс Перетину PL-UA",
    "UA-SK": "Прайс Перетину UA-SK", "SK-UA": "Прайс Перетину SK-UA",
    "UA-HU": "Прайс Перетину UA-HUN", "HU-UA": "Прайс Перетину HUN-UA",
    "UA-RO": "Прайс Перетину UA-RO", "RO-UA": "Прайс Перетину RO-UA",
    "UA-MD": "Прайс Перетину UA-MD", "MD-UA": "Прайс Перетину MD-UA",
}
FX_SHEET = "Архів курсу"


def _date(v) -> dt.date | None:
    if isinstance(v, (int, float)) and 30000 < v < 80000:
        return gsheet.EPOCH + dt.timedelta(days=int(v))
    return None


def _num(v):
    return round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _parse_hourly(rows: list, until: dt.date) -> dict[str, list]:
    out = {}
    for row in rows:
        d = _date(row[0]) if row else None
        if not d or d < START or d > until:
            continue
        cells = row[2:2 + HOURS]
        # #DIV/0! (немає пропускної спроможності) — день заповнений, але ціни немає
        if any(_num(c) is not None or (isinstance(c, str) and c.startswith("#")) for c in cells):
            out[d.isoformat()] = [_num(cells[h]) if h < len(cells) else None for h in range(HOURS)]
    return out


def _parse_fx(rows: list) -> dict[str, float]:
    out = {}
    for row in rows[2:]:
        d = _date(row[0]) if row else None
        rate = _num(row[2]) if len(row) > 2 else None
        if d and d >= START and rate:
            out[d.isoformat()] = rate
    return out


def load(svc=None, until: dt.date | None = None) -> dict:
    svc = svc or gsheet.service()
    until = until or dt.date.today() + dt.timedelta(days=1)
    names = list(RDN_SHEETS.values()) + list(CROSS_SHEETS.values())
    ranges = [f"{gsheet._q(n)}!A2:Z" for n in names] + [f"{gsheet._q(FX_SHEET)}!A1:C"]
    res = svc.spreadsheets().values().batchGet(
        spreadsheetId=gsheet.SPREADSHEET_ID, ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE", dateTimeRenderOption="SERIAL_NUMBER").execute()
    blocks = [vr.get("values", []) for vr in res["valueRanges"]]
    keys = list(RDN_SHEETS) + list(CROSS_SHEETS)
    parsed = {k: _parse_hourly(b, until) for k, b in zip(keys, blocks)}
    return {
        "rdn": {k: parsed[k] for k in RDN_SHEETS},
        "cross": {k: parsed[k] for k in CROSS_SHEETS},
        "fx": _parse_fx(blocks[-1]),
    }


def is_complete(data: dict, day: dt.date) -> list[str]:
    """Чого ще немає в таблиці на день `day` (порожній список — усе записано)."""
    key = day.isoformat()
    missing = [z for z, s in data["rdn"].items() if key not in s]
    missing += [c for c, s in data["cross"].items() if key not in s]
    return missing
