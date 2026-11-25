"""Оновлює дані сайту (docs/data.js) з Google Таблиці і пушить їх на GitHub (GitHub Pages).

  python build_site.py            # оновити data.js і запушити
  python build_site.py --no-push  # лише оновити локально (відкрити docs/index.html у браузері)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

import site_data

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
DATA_JS = os.path.join(DOCS, "data.js")


def write_data(data: dict) -> str:
    payload = dict(data, updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    os.makedirs(DOCS, exist_ok=True)
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write("window.DATA=")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    return DATA_JS


def git_push(message: str) -> None:
    if not os.path.isdir(os.path.join(HERE, ".git")):
        print("Сайт: це не git-репозиторій — пуш пропущено")
        return
    run = lambda *a: subprocess.run(["git", *a], cwd=HERE, capture_output=True, text=True, encoding="utf-8")
    run("add", "docs")
    if run("diff", "--cached", "--quiet").returncode == 0:
        print("Сайт: дані не змінились")
        return
    res = run("commit", "-m", message)
    if res.returncode != 0:
        raise RuntimeError(f"git commit: {res.stderr or res.stdout}")
    res = run("push")
    if res.returncode != 0:
        raise RuntimeError(f"git push: {res.stderr or res.stdout}")
    print("Сайт: дані запушено на GitHub")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    data = site_data.load()
    path = write_data(data)
    print(f"Сайт: оновлено {path}")
    if "--no-push" not in argv:
        git_push(f"data: site update {dt.date.today():%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
