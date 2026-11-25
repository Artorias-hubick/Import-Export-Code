"""Щоденний запуск: перетини (JAO + eap-office) і ціни РДН, з повторами, доки все не буде записано на завтра.

Коли публікуються дані (за київським часом):
  * JAO, добові аукціони UA↔HU / UA↔SK / UA↔PL: остаточні ≈11:22–11:50
  * eap-office (UA↔RO, UA↔MD): до обіду
  * SDAC (SK/PL/HU/RO): остаточні 13:57; OKTE / OPCOM / energy-charts — зазвичай 14:00–14:30
  * ОРЕЕ (UA, РДН): орієнтовно після 13:00

Логіка: перший запуск о 13:00 (Планувальник Windows), далі кожні 20 хв, поки в таблиці не буде
завтрашньої дати для ВСІХ перетинів і ВСІХ цін РДН (крайній час 18:00). Щойно все записано:
оновлюється сайт (docs/) і в Telegram надсилається звіт, а скрипт завершується.
Щоразу перевіряються останні 10 днів, тож пропущені дні дописуються автоматично.

  python run_all.py            # один «цикл дня» з повторами
  python run_all.py --once     # одна спроба без очікування
  python run_all.py --publish  # лише оновити сайт і надіслати звіт (без завантаження)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
import traceback
from zoneinfo import ZoneInfo

import update_crossings
import update_rdn

KYIV = ZoneInfo("Europe/Kyiv")
RETRY_MINUTES = 20
DEADLINE = dt.time(18, 0)
EAP_BACK_DAYS = 3
HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_MARK = os.path.join(HERE, "report_sent.txt")  # дата, за яку звіт уже надіслано


def _step(name: str, fn) -> bool:
    try:
        fn()
        return True
    except Exception:
        print(f"[{name}] помилка:", file=sys.stderr)
        traceback.print_exc()
        return False


def update_eap(first_attempt: bool, tomorrow: dt.date, have_tomorrow: bool) -> None:
    """eap-office: першого разу — останні дні й завтра, далі — лише завтра, поки його немає в таблиці."""
    import eap
    if first_attempt:
        eap.auto(tomorrow - dt.timedelta(days=EAP_BACK_DAYS + 1), tomorrow)
    elif not have_tomorrow:
        eap.auto(tomorrow, tomorrow)
    if os.path.isdir(eap.DL_DIR) and any(f.lower().endswith(".xlsx") for f in os.listdir(eap.DL_DIR)):
        eap.do_import()


def missing_in_sheet(tomorrow: dt.date) -> list[str]:
    import site_data
    return site_data.is_complete(site_data.load(until=tomorrow), tomorrow)


def attempt(first: bool, tomorrow: dt.date, missing_before: list[str]) -> list[str]:
    args = update_crossings.argparse.Namespace(
        corridors=",".join(update_crossings.SHEETS), date_from=None, date_to=None, overwrite=False)
    _step("JAO", lambda: update_crossings.run_gsheet("1h3-Q_c4cIHo4waNnQulKN9Vm8K_4rbbURjZ5b-2UJL8", args))
    _step("РДН", lambda: update_rdn.run([]))
    eap_missing = any(m in ("UA-RO", "RO-UA", "UA-MD", "MD-UA") for m in missing_before)
    _step("eap-office", lambda: update_eap(first, tomorrow, have_tomorrow=not first and not eap_missing))
    try:
        return missing_in_sheet(tomorrow)
    except Exception:
        traceback.print_exc()
        return ["перевірка таблиці"]


def publish(day: dt.date) -> None:
    """Сайт + звіт. Звіт — один раз на дату (повторний запуск у той самий день його не дублює)."""
    import build_site
    import tg_report
    _step("сайт", build_site.main)
    sent = open(REPORT_MARK, encoding="utf-8").read().strip() if os.path.exists(REPORT_MARK) else ""
    if sent == day.isoformat():
        print(f"Звіт за {day} уже надіслано.")
        return
    if _step("звіт", lambda: tg_report.send(day)):
        with open(REPORT_MARK, "w", encoding="utf-8") as f:
            f.write(day.isoformat())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args(argv)
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    if a.publish:
        publish(tomorrow)
        return 0
    missing: list[str] = []
    first = True
    while True:
        now = dt.datetime.now(KYIV)
        print(f"===== {now:%Y-%m-%d %H:%M} (Київ) =====", flush=True)
        missing = attempt(first, tomorrow, missing)
        first = False
        if not missing:
            print(f"Усі перетини й ціни РДН на {tomorrow} записані.", flush=True)
            publish(tomorrow)
            return 0
        print(f"Ще чекаємо на: {', '.join(missing)}", flush=True)
        if a.once or dt.datetime.now(KYIV).time() >= DEADLINE:
            print("Завершення без повних даних — наступний запуск дозаповнить пропуски.")
            _step("сайт", lambda: __import__("build_site").main())
            return 1
        time.sleep(RETRY_MINUTES * 60)


if __name__ == "__main__":
    sys.exit(main())
