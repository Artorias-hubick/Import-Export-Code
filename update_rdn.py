"""Оновлення листів «РДН UA/SK/PL/HUN/MD/RO» у Google Таблиці.

  python update_rdn.py                      # дозаповнити всі листи від останнього заповненого дня до завтра
  python update_rdn.py --zones SK,PL        # лише вибрані
  python update_rdn.py --from 2026-10-01 --to 2026-10-31 --overwrite
  python update_rdn.py --dry-run            # нічого не писати, лише показати, що буде записано

Структура листів (як у наявній таблиці):
  РДН SK, РДН PL  — A дата, B =TEXT(A;"DDD"), C..Z(AA) =AVERAGE(4 чвертей), AB.. 15-хв ціни (EUR)
  РДН HUN/RO/MD   — A дата, B =TEXT, C..Z(AA) годинні ціни (EUR, CET)
  РДН UA          — A дата, B =TEXT, C..Z = ціни за CET (формули на правий блок),
                    AC =A, AD =TEXT, AE..BB ціни ОРЕЕ за київським часом (грн)
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import gsheet
import rdn

SHEETS = {
    "UA": ("РДН UA", "AE"),
    "SK": ("РДН SK", "AB"),
    "PL": ("РДН PL", "AB"),
    "HU": ("РДН HUN", "C"),
    "MD": ("РДН MD", "C"),
    "RO": ("РДН RO", "C"),
}
L = gsheet.col_letter
QSTART = gsheet.col_index("AB")  # перша колонка 15-хв цін
UA_RIGHT = gsheet.col_index("AE")  # година 1 за Києвом


def row_quarters(r: int, d: dt.date, q: list[float]) -> list:
    hours = len(q) // 4
    formulas = [f"=AVERAGE({L(QSTART + 4 * h)}{r}:{L(QSTART + 4 * h + 3)}{r})" for h in range(hours)]
    formulas += [""] * (25 - hours)                      # C..AA
    tail = [""] * max(0, 96 - len(q))                    # очистити зайві чверті (доба 23 год)
    return [d.strftime("%d.%m.%Y"), f'=TEXT(A{r};"DDD")'] + formulas + list(q) + tail


def row_hourly(r: int, d: dt.date, h: list[float]) -> list:
    return [d.strftime("%d.%m.%Y"), f'=TEXT(A{r};"DDD")'] + list(h[:25]) + [""] * (25 - len(h[:25]))


def row_ua(r: int, d: dt.date, h: list[float]) -> list:
    # ліворуч CET: година k (1..23) = київська година k+1 цього ж дня; година 24 = київська година 1 наступного дня
    left = [f"={L(UA_RIGHT + k)}{r}" for k in range(1, 24)] + [f"={L(UA_RIGHT)}{r + 1}"]
    return ([d.strftime("%d.%m.%Y"), f'=TEXT(A{r};"DDD")'] + left + ["", ""]
            + [f"=A{r}", f'=TEXT(AC{r};"DDD")'] + list(h[:25]))


LOOKBACK_DAYS = 10  # щоразу перевіряємо останні N днів, щоб дозаповнити пропуски (напр. збій SDAC)


def main(argv=None) -> int:
    return 0 if not run(argv) else 0


def run(argv=None) -> list[str]:
    """Повертає список зон, для яких у таблиці ще немає останньої дати (зазвичай завтра)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zones", default=",".join(SHEETS))
    ap.add_argument("--from", dest="date_from", type=dt.date.fromisoformat)
    ap.add_argument("--to", dest="date_to", type=dt.date.fromisoformat)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--spreadsheet", default=gsheet.SPREADSHEET_ID)
    args = ap.parse_args(argv)

    svc = gsheet.service()
    date_to = args.date_to or (dt.date.today() + dt.timedelta(days=1))
    missing_last = []
    for zone in [z.strip().upper() for z in args.zones.split(",") if z.strip()]:
        sheet, data_col = SHEETS[zone]
        idx = gsheet.SheetIndex(svc, args.spreadsheet, sheet, data_col)
        if args.date_from:
            start = args.date_from
        else:
            nxt = (idx.last_filled() or dt.date(2024, 1, 1)) + dt.timedelta(days=1)
            start = min(nxt, dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS))
        gaps = [start + dt.timedelta(days=i) for i in range((date_to - start).days + 1)]
        gaps = [d for d in gaps if args.overwrite or d not in idx.filled]
        if not gaps:
            print(f"[{zone}] {sheet}: вже актуально ({idx.last_filled()})")
            continue
        start = gaps[0]
        try:
            data = rdn.fetch(zone, start, date_to)
        except Exception as e:  # одна біржа впала — інші продовжуємо
            print(f"[{zone}] помилка завантаження: {e}", file=sys.stderr)
            missing_last.append(zone)
            continue
        if date_to not in data and date_to not in idx.filled:
            missing_last.append(zone)
        rows = {}
        for d in sorted(data):
            if d in idx.filled and not args.overwrite:
                continue
            r = idx.row_for(d)
            if r is None:
                continue
            v = data[d]
            rows[r] = row_quarters(r, d, v) if zone in ("SK", "PL") else row_ua(r, d, v) if zone == "UA" else row_hourly(r, d, v)
        days = sorted(d for d in data if idx.row_for(d) in rows)
        rng = f"{days[0]}..{days[-1]}" if days else "-"
        if rows and not args.dry_run:
            gsheet.write_rows(svc, args.spreadsheet, sheet, rows)
        print(f"[{zone}] {sheet}: {'буде записано' if args.dry_run else 'записано'} {len(rows)} дн. ({rng})"
              + (f"; ще не опубліковано: {date_to}" if zone in missing_last else ""))
    return missing_last


if __name__ == "__main__":
    sys.exit(main())
