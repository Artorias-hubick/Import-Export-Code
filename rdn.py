"""Ціни РДН (day-ahead) України та сусідніх країн.

Джерела (звірені з наявними даними в Google Таблиці):
  UA  — ОРЕЕ (Оператор ринку), https://www.oree.com.ua/index.php/pricectr  [грн/МВт·год, київський час]
  SK  — OKTE (оператор ринку Словаччини), https://isot.okte.sk/api/v1/dam/results  [EUR, 15-хв]
  PL  — energy-charts.info (Fraunhofer ISE, дані ENTSO-E / SDAC), bzn=PL  [EUR, 15-хв]
  HU  — energy-charts.info, bzn=HU  [EUR → годинне середнє, CET]
  RO  — OPCOM (біржа Румунії), https://www.opcom.ro/rapoarte-pzu-raportPIP-export-csv/DD/MM/YYYY/en
        [EUR, 15-хв інтервали за часом біржі → годинне середнє; година 1 = інтервали 1–4]
  MD  — у таблиці лист «РДН MD» = ціни RO (Молдова не має власного РДН з публічними цінами)

Години рахуються за місцевим часом відповідного листа:
  SK/PL/HU — CET/CEST, RO/MD — інтервали OPCOM (година 1 = 00:00–01:00 CET), UA — київський час.
Годинна ціна = середнє чотирьох 15-хв цін, округлення до 0,01 «половина вгору».
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import time
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import requests

CET = ZoneInfo("Europe/Budapest")
KYIV = ZoneInfo("Europe/Kyiv")
UA_AGENT = {"User-Agent": "Mozilla/5.0 (rdn-crossings script)"}


def _get(url, *, params=None, data=None, method="GET", retries=4, timeout=90):
    last = None
    for attempt in range(retries):
        try:
            r = requests.request(method, url, params=params, data=data, timeout=timeout, headers=UA_AGENT)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def hround(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hourly_from_quarters(q: list[float]) -> list[float]:
    return [hround(sum(q[i:i + 4]) / len(q[i:i + 4])) for i in range(0, len(q), 4)]


# ---------------------------------------------------------------- SK (OKTE)
def okte_quarters(start: dt.date, end: dt.date) -> dict[dt.date, list[float]]:
    out = {}
    d = start
    while d <= end:
        e = min(end, d + dt.timedelta(days=30))
        rows = _get("https://isot.okte.sk/api/v1/dam/results",
                    params={"deliveryDayFrom": d.isoformat(), "deliveryDayTo": e.isoformat()}).json()
        by_day = defaultdict(list)
        for x in rows:
            by_day[dt.date.fromisoformat(x["deliveryDay"])].append((x["period"], x["price"]))
        for day, items in by_day.items():
            items.sort()
            if items and all(p is not None for _, p in items):
                out[day] = [float(p) for _, p in items]
        d = e + dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------- energy-charts (PL/HU/RO)
def energy_charts_quarters(bzn: str, start: dt.date, end: dt.date, tz=CET) -> dict[dt.date, list[float]]:
    """15-хв ціни, згруповані за добою в часовому поясі tz (для 60-хв даних дублюємо ×4)."""
    r = _get("https://api.energy-charts.info/price",
             params={"bzn": bzn, "start": (start - dt.timedelta(days=1)).isoformat(),
                     "end": (end + dt.timedelta(days=1)).isoformat()}).json()
    ts, pr = r.get("unix_seconds") or [], r.get("price") or []
    step = (ts[1] - ts[0]) if len(ts) > 1 else 900
    by_day = defaultdict(list)
    for t, p in zip(ts, pr):
        lt = dt.datetime.fromtimestamp(t, tz)
        if start <= lt.date() <= end:
            by_day[lt.date()].append(p)
    out = {}
    for day, vals in by_day.items():
        if any(v is None for v in vals):
            continue
        if step == 3600:
            vals = [v for v in vals for _ in range(4)]
        n_expected = int((dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), tz).timestamp()
                          - dt.datetime.combine(day, dt.time(), tz).timestamp()) // 900)
        if len(vals) == n_expected:
            out[day] = [float(v) for v in vals]
    return out


# ---------------------------------------------------------------- RO (OPCOM)
def opcom_hourly(start: dt.date, end: dt.date) -> dict[dt.date, list[float]]:
    out = {}
    d = start
    while d <= end:
        r = _get(f"https://www.opcom.ro/rapoarte-pzu-raportPIP-export-csv/{d:%d}/{d:%m}/{d:%Y}/en")
        q = {}
        for line in r.text.splitlines():
            cells = [c.strip().strip('"') for c in line.split('","')]
            if len(cells) >= 3 and cells[0].strip('"') == "Romania" and cells[1].isdigit():
                try:
                    q[int(cells[1])] = float(cells[2])
                except ValueError:
                    pass
        if q and sorted(q) == list(range(1, len(q) + 1)):
            vals = [q[i] for i in sorted(q)]
            out[d] = hourly_from_quarters(vals) if len(vals) > 25 else vals
        d += dt.timedelta(days=1)
        time.sleep(0.3)
    return out


# ---------------------------------------------------------------- UA (OREE)
def oree_hourly(start: dt.date, end: dt.date) -> dict[dt.date, list[float]]:
    out = {}
    months = sorted({(d.year, d.month) for d in (start + dt.timedelta(days=i)
                                                 for i in range((end - start).days + 1))})
    for y, m in months:
        r = _get("https://www.oree.com.ua/index.php/pricectr/data_view", method="POST",
                 data={"date": f"{m:02d}.{y}", "market": "DAM", "zone": "IPS"})
        content = json.loads(r.text)["content"]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.S):
            cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
            if not cells or not re.fullmatch(r"\d\d\.\d\d\.\d{4}", cells[0]):
                continue
            day = dt.datetime.strptime(cells[0], "%d.%m.%Y").date()
            vals = [float(c.replace(" ", "").replace(",", ".")) for c in cells[1:] if c not in ("", "-")]
            if start <= day <= end and len(vals) >= 23:
                out[day] = vals
    return out


def fetch(zone: str, start: dt.date, end: dt.date) -> dict[dt.date, list[float]]:
    """Повертає для SK/PL — 15-хв ціни, для HU/RO/MD — годинні (CET), для UA — годинні (Київ)."""
    if zone == "SK":
        return okte_quarters(start, end)
    if zone == "PL":
        return energy_charts_quarters("PL", start, end)
    if zone == "HU":
        q = energy_charts_quarters("HU", start, end)
        return {d: hourly_from_quarters(v) for d, v in q.items()}
    if zone in ("RO", "MD"):
        return opcom_hourly(start, end)
    if zone == "UA":
        return oree_hourly(start, end)
    raise ValueError(zone)
