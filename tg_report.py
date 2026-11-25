"""Звіт у Telegram про ціни РДН і перетини на D+1, з кнопкою на сайт.

  python tg_report.py              # надіслати звіт на завтра
  python tg_report.py 2026-11-26   # на конкретну дату
  python tg_report.py --dry-run    # лише показати текст

Налаштування (необов'язково, у .env поруч або в KT_bot/.env):
  TELEGRAM_TOKEN      токен бота (той самий, що в KT_bot)
  REPORT_CHAT_ID      за замовчуванням -1004400604747
  REPORT_THREAD_ID    за замовчуванням 2159
  SITE_URL            посилання для кнопки «Відкрити сайт»
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from statistics import mean

import requests

import site_data

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CHAT_ID = "-1004400604747"
DEFAULT_THREAD_ID = "2159"
DEFAULT_SITE_URL = "https://artorias-hubick.github.io/Import-Export-Code/"
PEAK_HOURS = range(8, 20)  # години 9–20 CET
NAMES = {"UA": "🇺🇦 UA", "SK": "🇸🇰 SK", "PL": "🇵🇱 PL", "HU": "🇭🇺 HU", "RO": "🇷🇴 RO", "MD": "🇲🇩 MD"}
NEIGHBOURS = ["SK", "PL", "HU", "RO", "MD"]


def load_env() -> dict:
    env = {}
    for path in (os.path.join(os.path.dirname(HERE), ".env"), os.path.join(HERE, ".env")):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.lstrip().startswith("#"):
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip().strip('"')
    env.update({k: v for k, v in os.environ.items() if k in ("TELEGRAM_TOKEN", "REPORT_CHAT_ID", "REPORT_THREAD_ID", "SITE_URL")})
    return env


class Prices:
    """Погодинні ціни в EUR (UA переводиться за курсом)."""

    def __init__(self, data: dict):
        self.data = data
        self.fx_dates = sorted(data["fx"])

    def fx(self, day: str) -> float:
        past = [d for d in self.fx_dates if d <= day]
        return self.data["fx"][past[-1] if past else self.fx_dates[0]]

    def hours(self, zone: str, day: str) -> list:
        row = self.data["rdn"][zone].get(day)
        if not row:
            return [None] * 24
        k = self.fx(day) if zone == "UA" else 1.0
        return [None if v is None else v / k for v in row]

    def cross(self, key: str, day: str) -> list:
        return self.data["cross"][key].get(day) or [None] * 24

    def avg(self, zone: str, day: str, hours=range(24)):
        vals = [v for h, v in enumerate(self.hours(zone, day)) if v is not None and h in hours]
        return mean(vals) if vals else None


def pct(a, b):
    return None if a is None or not b else (a - b) / abs(b) * 100


def arrow(p) -> str:
    if p is None:
        return "—"
    return f"{'🔺+' if p > 0 else '🔻' if p < 0 else '▫️'}{fmt(p)}%"


def fmt(v, digits=1) -> str:
    return "—" if v is None else f"{v:,.{digits}f}".replace(",", " ").replace(".", ",")


def build(day: dt.date, data: dict) -> str:
    p = Prices(data)
    d, prev = day.isoformat(), (day - dt.timedelta(days=1)).isoformat()
    week = [(day - dt.timedelta(days=i)).isoformat() for i in range(1, 8)]
    lines = [f"📊 <b>Ціни РДН і перетини на {day:%d.%m.%Y}</b>", "<i>EUR/МВт·год, base / peak (9–20 CET)</i>", ""]

    # 1. Ціни РДН і динаміка
    lines.append("<b>РДН</b>  ціна · до вчора · до сер. 7 дн")
    for z in ["UA"] + NEIGHBOURS:
        base, peak = p.avg(z, d), p.avg(z, d, PEAK_HOURS)
        wk = [x for x in (p.avg(z, w) for w in week) if x is not None]
        extra = ""
        if z == "UA" and base is not None:
            extra = f" ({fmt(base * p.fx(d), 0)} грн)"
        lines.append(f"{NAMES[z]}: <b>{fmt(base)}</b> / {fmt(peak)}{extra} · {arrow(pct(base, p.avg(z, prev)))}"
                     f" · {arrow(pct(base, mean(wk) if wk else None))}")

    # 2. Спред і арбітраж з урахуванням перетину
    ua = p.hours("UA", d)
    lines += ["", "<b>Спред сусід − UA і вигідні години</b> (маржа після оплати перетину)"]
    for z in NEIGHBOURS:
        x = p.hours(z, d)
        spread = [b - a for a, b in zip(ua, x) if a is not None and b is not None]
        exp = _margins(x, ua, p.cross(f"UA-{z}", d))
        imp = _margins(ua, x, p.cross(f"{z}-UA", d))
        lines.append(f"{NAMES[z]}: спред {fmt(mean(spread) if spread else None)} · "
                     f"експорт {len(exp)} год ({fmt(mean(exp) if exp else None)}) · "
                     f"імпорт {len(imp)} год ({fmt(mean(imp) if imp else None)})")

    # 3. Перетини
    lines += ["", "<b>Перетини</b>  сер. ціна · годин з потужністю"]
    for z in NEIGHBOURS:
        parts = []
        for key in (f"UA-{z}", f"{z}-UA"):
            vals = [v for v in p.cross(key, d) if v is not None]
            parts.append(f"{key.replace('-', '→')} {fmt(mean(vals) if vals else None, 2)} · {len(vals)}/24")
        lines.append("  ".join(parts))

    # 4. Місяць: середнє з початку місяця проти того ж періоду минулого місяця
    mtd = [(day.replace(day=1) + dt.timedelta(days=i)).isoformat() for i in range(day.day)]
    last_m_end = day.replace(day=1) - dt.timedelta(days=1)
    prev_m = [(last_m_end.replace(day=1) + dt.timedelta(days=i)).isoformat() for i in range(min(day.day, last_m_end.day))]
    ua_m = [v for v in (p.avg("UA", x) for x in mtd) if v is not None]
    ua_pm = [v for v in (p.avg("UA", x) for x in prev_m) if v is not None]
    if ua_m:
        lines += ["", f"<b>UA з початку місяця:</b> {fmt(mean(ua_m))} · до того ж періоду минулого місяця "
                      f"{arrow(pct(mean(ua_m), mean(ua_pm) if ua_pm else None))}"]
    lines.append(f"\n<i>Курс EUR {fmt(p.fx(d), 2)} грн</i>")
    return "\n".join(lines)


def _margins(sell, buy, cross) -> list:
    """Маржа за години, коли продаж дорожчий за купівлю + перетин (лише години з потужністю)."""
    out = []
    for s, b, c in zip(sell, buy, cross):
        if s is not None and b is not None and c is not None and s - b - c > 0:
            out.append(s - b - c)
    return out


def send(day: dt.date | None = None, dry_run: bool = False) -> str:
    day = day or dt.date.today() + dt.timedelta(days=1)
    text = build(day, site_data.load(until=day))
    if dry_run:
        return text
    env = load_env()
    token = env.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Немає TELEGRAM_TOKEN у .env")
    markup = {"inline_keyboard": [[{"text": "📈 Відкрити сайт з графіками", "url": env.get("SITE_URL", DEFAULT_SITE_URL)}]]}
    resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, data={
        "chat_id": env.get("REPORT_CHAT_ID", DEFAULT_CHAT_ID),
        "message_thread_id": env.get("REPORT_THREAD_ID", DEFAULT_THREAD_ID),
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true",
        "reply_markup": json.dumps(markup),
    })
    if not resp.ok:
        raise RuntimeError(f"Telegram {resp.status_code}: {resp.text[:300]}")
    print(f"Звіт за {day} надіслано в Telegram")
    return text


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dates = [dt.date.fromisoformat(a) for a in argv if not a.startswith("--")]
    text = send(dates[0] if dates else None, dry_run="--dry-run" in argv)
    if "--dry-run" in argv:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
