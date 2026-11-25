"""Завантаження результатів добових аукціонів перетину з JAO (www.jao.eu).

Використовується той самий публічний ендпоінт, що й кнопка «Export auction»
на сторінці https://www.jao.eu/auctions/atc . Колонки Excel-експорту:
  H = Offered capacity (MW)  -> поле offeredCapacity
  J = Price (€/MWH)          -> поле price
Правило: якщо H > 0 -> беремо J, інакше -> #DIV/0!
"""
from __future__ import annotations

import datetime as dt
import time
from collections import defaultdict

import requests

EXPORT_URL = "https://www.jao.eu/api/v1/auction/calls/getexportauctions"
DIV0 = "#DIV/0!"

# напрямки, які JAO проводить для кордонів України
JAO_CORRIDORS = ["UA-HU", "HU-UA", "UA-SK", "SK-UA", "UA-PL", "PL-UA"]


def _post(body: dict, retries: int = 4) -> list:
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(EXPORT_URL, json=body, timeout=120,
                              headers={"Accept": "application/json"})
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:  # мережеві збої
            last = str(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"JAO request failed {body}: {last}")


def fetch_corridor(corridor: str, start: dt.date, end: dt.date) -> dict[dt.date, list]:
    """Повертає {дата_постачання: [ціна або '#DIV/0!' по годинах 1..23/24/25]}."""
    out: dict[dt.date, list] = {}
    # запит шматками по ~60 днів
    chunk = dt.timedelta(days=60)
    s = start
    while s <= end:
        e = min(end, s + chunk)
        body = {
            "horizon": "Daily",
            "corridor": corridor,
            "fromdate": (s - dt.timedelta(days=1)).strftime("%Y-%m-%d") + "-00:00:00",
            "todate": e.strftime("%Y-%m-%d") + "-23:59:59",
        }
        rows = _post(body)
        by_auction = defaultdict(list)
        for x in rows:
            by_auction[x["identification"]].append(x)
        for ident, items in by_auction.items():
            # UA-HU-D-DAILYPRODU-261124-01 -> 2026-11-24
            code = ident.split("-")[-2]
            try:
                d = dt.datetime.strptime(code, "%y%m%d").date()
            except ValueError:
                continue
            if not (start <= d <= end):
                continue
            if any(i.get("isCancelled") for i in items):
                continue  # скасований аукціон — не заповнюємо
            values = []
            for i in items:  # порядок годин як у JAO (на 25-год. добу є "02:00-03:00*")
                offered = i.get("offeredCapacity") or 0
                price = i.get("price")
                values.append(float(price) if offered > 0 and price is not None else DIV0)
            out[d] = values
        s = e + dt.timedelta(days=1)
    return out
