"""Перетини UA-RO, RO-UA, UA-MD, MD-UA з eap-office.ua.energy (Укренерго).

Сайт закритий для запитів з-за меж України, тому скрипт працює ЛИШЕ на вашому ПК
і відкриває ваш встановлений Google Chrome (через Playwright).

Режими:
  py eap.py browser      — відкрити Chrome на «Результати аукціонів → Добові».
                           Скрипт пробує сам натиснути «Гість»; далі ви ставите дату,
                           тиснете «Експорт в Excel» (можна для кількох дат поспіль) —
                           усі завантажені файли автоматично зберігаються в eap_downloads\\.
                           Одночасно всі запити сайту пишуться в eap_capture.json —
                           надішліть цей файл, і я зроблю повністю автоматичне завантаження без кліків.
                           Закрийте вікно Chrome, коли закінчите.
  py eap.py import       — розібрати всі Excel з eap_downloads\\ і записати в Google Таблицю
                           (правило: є «Запропонована» (B) > 0 → «Гранична ціна» (E), інакше #DIV/0!).
  py eap.py import --overwrite        — перезаписати вже заповнені дні
  py eap.py inspect FILE.xlsx         — показати, як скрипт розпізнав файл (для перевірки)

Файли після успішного імпорту переносяться в eap_downloads\\imported\\.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DL_DIR = os.path.join(HERE, "eap_downloads")
CAPTURE = os.path.join(HERE, "eap_capture.json")
PROFILE = os.path.join(HERE, "chrome_profile_eap")
START_URL = "https://eap-office.ua.energy/pages/results/daily"
DIV0 = "#DIV/0!"

SHEETS = {
    "UA-RO": "Прайс Перетину UA-RO",
    "RO-UA": "Прайс Перетину RO-UA",
    "UA-MD": "Прайс Перетину UA-MD",
    "MD-UA": "Прайс Перетину MD-UA",
}

# --------------------------------------------------------------------- browser
def browser() -> None:
    from playwright.sync_api import sync_playwright

    os.makedirs(DL_DIR, exist_ok=True)
    log = []

    def on_response(resp):
        try:
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            item = {"url": resp.url, "method": req.method, "status": resp.status,
                    "post": req.post_data, "type": resp.headers.get("content-type", "")}
            if "json" in item["type"]:
                txt = resp.text()
                item["body"] = txt[:20000]
            log.append(item)
            with open(CAPTURE, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def on_download(d):
        name = d.suggested_filename or "export.xlsx"
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(DL_DIR, f"{stamp}_{name}")
        d.save_as(path)
        print("Збережено:", path)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, channel="chrome", headless=False,
                                                   accept_downloads=True, locale="uk-UA")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ctx.on("response", on_response)
        ctx.on("page", lambda pg: pg.on("download", on_download))
        page.on("download", on_download)
        page.goto(START_URL, wait_until="domcontentloaded")
        for text in ("Увійти як гість", "Гість", "Guest", "Продовжити як гість"):
            try:
                page.get_by_text(text, exact=False).first.click(timeout=4000)
                print("Натиснуто:", text)
                page.wait_for_load_state("networkidle", timeout=15000)
                if "results/daily" not in page.url:
                    page.goto(START_URL, wait_until="domcontentloaded")
                break
            except Exception:
                continue
        print("\nChrome відкрито. Оберіть дату → «Експорт в Excel» (можна багато дат).")
        print("Коли закінчите — закрийте вікно Chrome.\n")
        try:
            while ctx.pages:
                ctx.pages[0].wait_for_timeout(1000)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    print(f"Запити сайту: {CAPTURE}\nФайли: {DL_DIR}\nДалі: py eap.py import")


# --------------------------------------------------------------------- auto
AUTO_WAIT_MS = 30000


def _shown_date(page) -> dt.date:
    page.wait_for_function(
        "() => /\\d{2}\\.\\d{2}\\.\\d{4}/.test(((document.querySelector('#previousPeriod') || {}).parentElement || {}).innerText || '')",
        timeout=AUTO_WAIT_MS)
    text = page.locator("span.checked:has(#previousPeriod)").first.inner_text()
    return dt.datetime.strptime(re.search(r"\d{2}\.\d{2}\.\d{4}", text)[0], "%d.%m.%Y").date()


def _go_to_date(page, target: dt.date) -> bool:
    """Гортає «Період аукціону» стрілками до target. False — якщо сайт далі не пускає."""
    for _ in range(400):
        cur = _shown_date(page)
        if cur == target:
            return True
        page.click("#previousPeriod" if cur > target else "#nextPeriod")
        try:
            page.wait_for_function(
                "old => !(document.querySelector('#previousPeriod') || {}).parentElement.innerText.includes(old)",
                arg=cur.strftime("%d.%m.%Y"), timeout=AUTO_WAIT_MS)
        except Exception:
            return False
    return False


def _wait_table_for(page, day: dt.date) -> bool:
    """Після зміни дати сайт підвантажує таблицю не одразу, і експорт віддав би попередню добу.
    Чекаємо, поки «Дата проведення аукціону» в таблиці стане day - 1 (добовий аукціон — напередодні)."""
    expected = (day - dt.timedelta(days=1)).strftime("%d.%m.%Y")
    try:
        page.wait_for_function(
            "d => [...document.querySelectorAll('nb-tab.content-active span.checked')]"
            ".some(s => s.innerText.trim() === d)", arg=expected, timeout=AUTO_WAIT_MS)
        page.wait_for_timeout(2000)  # дати таблиці домалюватись (networkidle сайт не досягає)
        return True
    except Exception:
        return False


def auto(date_from: dt.date, date_to: dt.date) -> None:
    """Без кліків: для кожної дати й кожного напряму натискає «Експорт в Excel» і зберігає файл."""
    from playwright.sync_api import sync_playwright

    os.makedirs(DL_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, channel="chrome", headless=False,
                                                   accept_downloads=True, locale="uk-UA")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(START_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#xlsxExportBtn", timeout=AUTO_WAIT_MS * 2)
        day = date_to
        while day >= date_from:
            if not _go_to_date(page, day):
                print(f"{day}: дата недоступна на сайті — пропускаю")
                day -= dt.timedelta(days=1)
                continue
            if not _wait_table_for(page, day):
                print(f"{day}: таблиця не оновилась — пропускаю, щоб не записати чужу дату")
                day -= dt.timedelta(days=1)
                continue
            # Один файл містить усі напрями (окремі аркуші), тож вистачає одного експорту на дату
            with page.expect_download(timeout=AUTO_WAIT_MS) as info:
                page.locator("#xlsxExportBtn:visible").first.click()
            info.value.save_as(os.path.join(DL_DIR, f"eap {day:%Y-%m-%d}.xlsx"))
            print(f"{day}: збережено", flush=True)
            day -= dt.timedelta(days=1)
        ctx.close()
    print(f"Файли: {DL_DIR}\nДалі: py eap.py import")


# --------------------------------------------------------------------- parsing
COUNTRY = [("UA", r"укра|ukr|\bua\b|10Y1001C--000182|10Y1001C--00003F|ОЕС"),
           ("RO", r"румун|roman|\bro\b|10YRO-TEL"),
           ("MD", r"молдов|moldov|\bmd\b|10Y1001A1001A990")]


def direction(text: str) -> str | None:
    """'Україна - Румунія', 'UA→RO', 'RO > UA', 'UA-MD' ... → 'UA-RO' і т.д."""
    t = str(text)
    hits = []
    for code, rx in COUNTRY:
        m = re.search(rx, t, re.I)
        if m:
            hits.append((m.start(), code))
    if len(hits) < 2:
        return None
    hits.sort()
    d = f"{hits[0][1]}-{hits[1][1]}"
    return d if d in SHEETS else None


def to_date(v) -> dt.date | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", str(v or ""))
    if m:
        return dt.date(int(m[3]), int(m[2]), int(m[1]))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    return None


def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def hour_no(v) -> int | None:
    if isinstance(v, (int, float)) and 1 <= v <= 25:
        return int(v)
    s = str(v or "")
    m = re.match(r"\s*(\d{1,2}):\d{2}", s)            # 00:00-01:00
    if m:
        return int(m[1]) + 1
    m = re.match(r"\s*(\d{1,2})\s*$", s)
    if m and 1 <= int(m[1]) <= 25:
        return int(m[1])
    return None


def parse_file(path: str, verbose=False) -> dict[str, dict[dt.date, dict[int, object]]]:
    """→ {напрям: {дата: {година: ціна або #DIV/0!}}}"""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: dict = defaultdict(lambda: defaultdict(dict))
    fname_dir = direction(os.path.basename(path))
    fname_date = to_date(os.path.basename(path))
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        # заголовок: рядок, де є «Запропон» і «Гранич»
        hdr_i, cols = None, {}
        for i, r in enumerate(rows[:30]):
            low = [str(c or "").lower() for c in r]
            if any("запропон" in c for c in low) and any("гранич" in c for c in low):
                hdr_i = i
                for j, c in enumerate(low):
                    if "дата / час" in c or "учасник" in c:
                        # eap-office: «Дата / час» — номер години; «Кількість учасників» — не година
                        if "дата / час" in c and "hour" not in cols:
                            cols["hour"] = j
                        continue
                    if "запропон" in c and "offer" not in cols:
                        cols["offer"] = j
                    elif "гранич" in c and "price" not in cols:
                        cols["price"] = j
                    elif ("напрям" in c or "перетин" in c or "межа" in c or "аукціон" in c) and "dir" not in cols:
                        cols["dir"] = j
                    elif ("дата" in c or "доба" in c or "день" in c) and "date" not in cols:
                        cols["date"] = j
                    elif ("годин" in c or "період" in c or "інтервал" in c or "час" in c) and "hour" not in cols:
                        cols["hour"] = j
                break
        if hdr_i is None:
            hdr_i, cols = 0, {"offer": 1, "price": 4}        # як описано: B і E
        # контекст над таблицею (напрям/дата можуть бути в шапці або в назві листа)
        ctx_text = " ".join(str(c) for r in rows[:hdr_i] for c in r if c) + " " + ws.title
        cur_dir = direction(ctx_text) or direction(ws.title) or fname_dir
        cur_date = to_date(ctx_text) or fname_date
        seq = defaultdict(int)
        if verbose:
            print(f"[{ws.title}] заголовок у рядку {hdr_i + 1}: {cols}; напрям={cur_dir}; дата={cur_date}")
        for r in rows[hdr_i + 1:]:
            if not any(c not in (None, "") for c in r):
                continue
            line = " ".join(str(c) for c in r if c is not None)
            d_row = direction(r[cols["dir"]]) if "dir" in cols and cols["dir"] < len(r) else None
            if d_row is None and "offer" in cols and to_num(r[cols["offer"]] if cols["offer"] < len(r) else None) is None:
                d_row = direction(line)                   # рядок-підзаголовок з напрямом
                if d_row:
                    cur_dir = d_row
                    dd = to_date(line)
                    cur_date = dd or cur_date
                    continue
            dirn = d_row or cur_dir
            day = (to_date(r[cols["date"]]) if "date" in cols and cols["date"] < len(r) else None) or cur_date
            h = hour_no(r[cols["hour"]]) if "hour" in cols and cols["hour"] < len(r) else hour_no(r[0])
            if not dirn or not day:
                continue
            if h is None:
                seq[(dirn, day)] += 1
                h = seq[(dirn, day)]
            elif h in out[dirn][day]:                     # друга 03:00 у добу переходу на зимовий
                h = max(out[dirn][day]) + 1
            offer = to_num(r[cols["offer"]]) if cols["offer"] < len(r) else None
            price = to_num(r[cols["price"]]) if cols["price"] < len(r) else None
            out[dirn][day][h] = price if (offer and offer > 0 and price is not None) else DIV0
    wb.close()  # інакше Windows не дасть перенести файл у imported
    return out


def has_results(parsed) -> bool:
    """Чи є в файлі хоч одна година з пропускною спроможністю (ціна, а не #DIV/0!)."""
    return any(v != DIV0 for days in parsed.values() for hours in days.values() for v in hours.values())


def merge(dst, src):
    for d, days in src.items():
        for day, hours in days.items():
            dst.setdefault(d, {}).setdefault(day, {}).update(hours)


# --------------------------------------------------------------------- import
def do_import(overwrite=False) -> list[str]:
    import gsheet
    files = [os.path.join(DL_DIR, f) for f in sorted(os.listdir(DL_DIR))
             if f.lower().endswith((".xlsx", ".xlsm"))] if os.path.isdir(DL_DIR) else []
    if not files:
        print("eap_downloads порожня — спочатку: py eap.py browser")
        return []
    data: dict = {}
    for f in list(files):
        try:
            parsed = parse_file(f)
            if not has_results(parsed):
                # Результати ще не опубліковані (усюди 0) — не записуємо, щоб наступний запуск узяв справжні
                print(f"{os.path.basename(f)}: результатів ще немає — пропускаю")
                files.remove(f)
                os.remove(f)
                continue
            merge(data, parsed)
        except Exception as e:
            print(f"Не вдалося прочитати {f}: {e}", file=sys.stderr)
    if not data:
        print("У файлах не знайдено напрямів UA-RO/RO-UA/UA-MD/MD-UA. Перевірте: py eap.py inspect <файл>")
        return []
    svc = gsheet.service()
    for dirn, days in sorted(data.items()):
        sheet = SHEETS[dirn]
        idx = gsheet.SheetIndex(svc, gsheet.SPREADSHEET_ID, sheet)
        rows = {d: [hours.get(h, "") for h in range(1, max(hours) + 1)] for d, hours in days.items()}
        written = gsheet.write_days(svc, gsheet.SPREADSHEET_ID, sheet, idx, rows, overwrite)
        rng = f"{min(written)}..{max(written)}" if written else "-"
        print(f"[{dirn}] {sheet}: записано {len(written)} дн. ({rng}); у файлах {len(days)} дн.")
    done = os.path.join(DL_DIR, "imported")
    os.makedirs(done, exist_ok=True)
    for f in files:
        shutil.move(f, os.path.join(done, os.path.basename(f)))
    return sorted(data)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "browser"
    if cmd == "browser":
        browser()
    elif cmd == "auto":
        # py eap.py auto 2026-09-27 2026-11-26   (без дат — лише завтра)
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        dates = [dt.date.fromisoformat(a) for a in argv[1:3]]
        auto(dates[0] if dates else tomorrow, dates[1] if len(dates) > 1 else (dates[0] if dates else tomorrow))
    elif cmd == "import":
        do_import("--overwrite" in argv)
    elif cmd == "inspect" and len(argv) > 1:
        res = parse_file(argv[1], verbose=True)
        for dirn, days in sorted(res.items()):
            for day, hours in sorted(days.items()):
                print(dirn, day, [hours.get(h, "") for h in range(1, max(hours) + 1)])
        if not res:
            print("Нічого не розпізнано — надішліть цей файл, підлаштую розбір.")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
