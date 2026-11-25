"""Оновлення листів «Прайс Перетину ...» у «Калькулятор IMPORT_EXPORT.xlsx».

Приклади:
  # дозаповнити всі порожні дати від останньої заповненої до завтра
  python update_crossings.py "Калькулятор IMPORT_EXPORT.xlsx"

  # конкретний період, з перезаписом уже заповнених рядків
  python update_crossings.py book.xlsx --from 2026-11-01 --to 2026-11-24 --overwrite

  # зберегти в інший файл
  python update_crossings.py book.xlsx -o book_new.xlsx

  # писати прямо в Google Таблицю (основний режим)
  python update_crossings.py --gsheet
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile

import jao
import xlsx_patch

DRIVE_FILE_ID = "1tZJZBoDH8CLQu0RzTIFds8PLgK2E9Wso"  # Калькулятор IMPORT_EXPORT.xlsx

# напрямок JAO -> назва листа в книзі
SHEETS = {
    "UA-HU": "Прайс Перетину UA-HUN",
    "HU-UA": "Прайс Перетину HUN-UA",
    "UA-SK": "Прайс Перетину UA-SK",
    "SK-UA": "Прайс Перетину SK-UA",
    "UA-PL": "Прайс Перетину UA-PL",
    "PL-UA": "Прайс Перетину PL-UA",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workbook", nargs="?", help="локальний xlsx (не потрібен з --gsheet / --drive)")
    ap.add_argument("--gsheet", nargs="?", const="1h3-Q_c4cIHo4waNnQulKN9Vm8K_4rbbURjZ5b-2UJL8", metavar="SPREADSHEET_ID",
                    help="писати прямо в Google Таблицю (основний режим)")
    ap.add_argument("--drive", nargs="?", const=DRIVE_FILE_ID, metavar="FILE_ID",
                    help="завантажити файл з Google Drive, оновити і залити новою версією того самого файлу")
    ap.add_argument("-o", "--output", help="куди зберегти (за замовчуванням — той самий файл)")
    ap.add_argument("--from", dest="date_from", type=dt.date.fromisoformat,
                    help="перша дата (за замовчуванням — день після останнього заповненого рядка)")
    ap.add_argument("--to", dest="date_to", type=dt.date.fromisoformat,
                    help="остання дата (за замовчуванням — завтра, D+1)")
    ap.add_argument("--overwrite", action="store_true", help="перезаписувати вже заповнені рядки")
    ap.add_argument("--corridors", default=",".join(SHEETS), help="список напрямків через кому")
    args = ap.parse_args(argv)

    if args.gsheet:
        run_gsheet(args.gsheet, args)
        return 0
    if args.drive:
        import gdrive
        svc = gdrive.service()
        tmpdir = tempfile.mkdtemp()
        local = os.path.join(tmpdir, "book.xlsx")
        meta = gdrive.download(svc, args.drive, local)
        print(f"Завантажено з Drive: {meta['name']} (змінено {meta['modifiedTime']})")
        if run(local, local, args):
            res = gdrive.upload_new_revision(svc, args.drive, local, meta["modifiedTime"])
            print(f"Залито нову версію на Drive: {res['name']} ({res['modifiedTime']})")
        return 0
    if not args.workbook:
        ap.error("вкажіть --gsheet, --drive або шлях до xlsx")
    run(args.workbook, args.output or args.workbook, args)
    return 0


LOOKBACK_DAYS = 10


def run_gsheet(spreadsheet_id: str, args) -> list[str]:
    """Повертає список напрямків, для яких ще немає результатів на останню дату (D+1)."""
    import gsheet
    svc = gsheet.service()
    corridors = [c.strip() for c in args.corridors.split(",") if c.strip()]
    date_to = args.date_to or (dt.date.today() + dt.timedelta(days=1))
    missing_last = []
    for corr in corridors:
        name = SHEETS[corr]
        idx = gsheet.SheetIndex(svc, spreadsheet_id, name)
        start = args.date_from
        if start is None:
            last = idx.last_filled()
            nxt = (last + dt.timedelta(days=1)) if last else dt.date(2024, 1, 1)
            start = min(nxt, dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS))
        gaps = [start + dt.timedelta(days=i) for i in range((date_to - start).days + 1)]
        gaps = [d for d in gaps if args.overwrite or d not in idx.filled]
        if not gaps:
            print(f"[{corr}] {name}: вже актуально (останній день {idx.last_filled()})")
            continue
        start = gaps[0]
        try:
            data = jao.fetch_corridor(corr, start, date_to)
        except Exception as e:
            print(f"[{corr}] помилка JAO: {e}", file=sys.stderr)
            missing_last.append(corr)
            continue
        if date_to not in data and date_to not in idx.filled:
            missing_last.append(corr)
        written = gsheet.write_days(svc, spreadsheet_id, name, idx, data, args.overwrite)
        missing = [d for d in (start + dt.timedelta(days=i) for i in range((date_to - start).days + 1)) if d not in data]
        rng = f"{written[0]}..{written[-1]}" if written else "-"
        print(f"[{corr}] {name}: записано {len(written)} дн. ({rng}); немає даних JAO {len(missing)}")
    return missing_last


def run(workbook: str, output: str, args) -> bool:
    """Повертає True, якщо книгу змінено і збережено в output."""
    corridors = [c.strip() for c in args.corridors.split(",") if c.strip()]
    sheets = xlsx_patch.open_sheets(workbook, [SHEETS[c] for c in corridors])
    date_to = args.date_to or (dt.date.today() + dt.timedelta(days=1))

    changed = {}
    for corr in corridors:
        name = SHEETS[corr]
        sp = sheets.get(name)
        if sp is None:
            print(f"[{corr}] лист «{name}» не знайдено — пропуск", file=sys.stderr)
            continue
        start = args.date_from
        if start is None:
            last = sp.last_filled_date()
            start = (last + dt.timedelta(days=1)) if last else dt.date(2024, 1, 1)
        if start > date_to:
            print(f"[{corr}] {name}: вже актуально (останній рядок {start - dt.timedelta(days=1)})")
            continue
        data = jao.fetch_corridor(corr, start, date_to)
        written, skipped, missing = [], [], []
        d = start
        while d <= date_to:
            if d not in data:
                missing.append(d)
            elif not sp.ensure_date_row(d):
                print(f"[{corr}] у листі немає рядка з датою {d}", file=sys.stderr)
            elif sp.row_has_data(d) and not args.overwrite:
                skipped.append(d)
            else:
                sp.write_day(d, data[d])
                written.append(d)
            d += dt.timedelta(days=1)
        if written:
            changed[name] = sp
        rng = f"{written[0]}..{written[-1]}" if written else "-"
        print(f"[{corr}] {name}: записано {len(written)} дн. ({rng}); "
              f"пропущено заповнених {len(skipped)}; немає даних JAO {len(missing)}"
              + (f" ({', '.join(map(str, missing[:5]))}{'...' if len(missing) > 5 else ''})" if missing else ""))

    if changed:
        xlsx_patch.save(workbook, output, changed)
        print(f"Збережено: {output}")
        return True
    print("Змін немає.")
    return False


if __name__ == "__main__":
    sys.exit(main())
