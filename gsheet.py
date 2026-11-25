"""Запис результатів JAO прямо в Google Таблицю «Калькулятор IMPORT_EXPORT (1)».

https://docs.google.com/spreadsheets/d/1h3-Q_c4cIHo4waNnQulKN9Vm8K_4rbbURjZ5b-2UJL8

Структура листів «Прайс Перетину ...»: A = дата, B = =TEXT(A;"DDD"),
C..Z = години 1..24, AA = година 25 (доба переходу на зимовий час).
Значення пишуться як USER_ENTERED, тому "#DIV/0!" стає справжньою помилкою
(так само, як у вже наявних рядках), а числа показуються з комою (локаль uk_UA).

Авторизація — та сама, що в gdrive.py (credentials.json → token.json),
але з доступом до Google Sheets.
"""
from __future__ import annotations

import datetime as dt
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SPREADSHEET_ID = "1h3-Q_c4cIHo4waNnQulKN9Vm8K_4rbbURjZ5b-2UJL8"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HERE = os.path.dirname(os.path.abspath(__file__))
EPOCH = dt.date(1899, 12, 30)


SERVICE_ACCOUNT_FILES = (os.path.join(HERE, "service-account.json"),
                         os.path.join(os.path.dirname(HERE), "service-account.json"))  # той, що в KT_bot


def service(credentials_file: str = None, token_file: str = None):
    credentials_file = credentials_file or os.path.join(HERE, "credentials.json")
    token_file = token_file or os.path.join(HERE, "token_sheets.json")
    if not os.path.exists(credentials_file) and not os.path.exists(token_file):
        # Без OAuth-файлу — сервісний акаунт KT_bot (таблиця має бути відкрита для нього як «Редактор»)
        from google.oauth2 import service_account
        for sa_file in SERVICE_ACCOUNT_FILES:
            if os.path.exists(sa_file):
                creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
                return build("sheets", "v4", credentials=creds, cache_discovery=False)
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def col_letter(idx: int) -> str:
    s = ""
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def _ensure_grid(svc, spreadsheet_id: str, sheet: str, need_rows: int, need_cols: int) -> None:
    """Додає рядки/колонки в кінець листа, якщо їх не вистачає (напр. 100 чвертей на 25-год. добу)."""
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id,
                                  fields="sheets.properties(sheetId,title,gridProperties)").execute()
    for sh in meta["sheets"]:
        p = sh["properties"]
        if p["title"] != sheet:
            continue
        g = p["gridProperties"]
        reqs = []
        if g.get("rowCount", 0) < need_rows:
            reqs.append({"appendDimension": {"sheetId": p["sheetId"], "dimension": "ROWS",
                                             "length": need_rows - g["rowCount"] + 50}})
        if g.get("columnCount", 0) < need_cols:
            reqs.append({"appendDimension": {"sheetId": p["sheetId"], "dimension": "COLUMNS",
                                             "length": need_cols - g["columnCount"]}})
        if reqs:
            svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": reqs}).execute()


def write_rows(svc, spreadsheet_id: str, sheet: str, rows: dict[int, list]) -> None:
    """rows: {номер_рядка: [значення починаючи з колонки A]} — одним batchUpdate."""
    _ensure_grid(svc, spreadsheet_id, sheet, max(rows), max(len(v) for v in rows.values()))
    data = [{"range": f"{_q(sheet)}!A{r}:{col_letter(len(v))}{r}", "values": [v]} for r, v in sorted(rows.items())]
    for i in range(0, len(data), 200):
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data[i:i + 200]},
        ).execute()


def _q(sheet: str) -> str:
    return "'" + sheet.replace("'", "''") + "'"


class SheetIndex:
    """Дата → номер рядка + ознака, чи рядок уже заповнений (C..AA)."""

    def __init__(self, svc, spreadsheet_id: str, sheet: str, data_col: str = "C"):
        """data_col — колонка, за якою визначаємо, що день уже заповнений
        (C для «Прайс Перетину», AB для РДН SK/PL з 15-хв цінами, AE для РДН UA)."""
        self.sheet = sheet
        ci = col_index(data_col) - 1
        res = svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"{_q(sheet)}!A:{data_col}",
            valueRenderOption="UNFORMATTED_VALUE", dateTimeRenderOption="SERIAL_NUMBER",
        ).execute()
        self.date_row: dict[dt.date, int] = {}
        self.filled: set[dt.date] = set()
        self.last_row_with_date = 1
        for i, row in enumerate(res.get("values", []), start=1):
            a = row[0] if row else None
            if isinstance(a, (int, float)) and 30000 < a < 80000:
                d = EPOCH + dt.timedelta(days=int(a))
                self.date_row.setdefault(d, i)
                self.last_row_with_date = max(self.last_row_with_date, i)
                v = row[ci] if len(row) > ci else None
                if isinstance(v, (int, float)) or (isinstance(v, str) and v.startswith("#") and ci == 2):
                    self.filled.add(d)

    def last_filled(self) -> dt.date | None:
        return max(self.filled) if self.filled else None

    def row_for(self, d: dt.date) -> int | None:
        """Рядок для дати; якщо дат ще нема — наступний після останньої дати (дати йдуть підряд)."""
        if d in self.date_row:
            return self.date_row[d]
        last = max(self.date_row) if self.date_row else None
        if last and d > last:
            return self.date_row[last] + (d - last).days
        return None


def write_days(svc, spreadsheet_id: str, sheet: str, idx: SheetIndex,
               days: dict[dt.date, list], overwrite: bool = False) -> list[dt.date]:
    data, written = [], []
    for d in sorted(days):
        if d in idx.filled and not overwrite:
            continue
        r = idx.row_for(d)
        if r is None:
            continue
        vals = list(days[d])[:25]
        row = [d.strftime("%d.%m.%Y"), f'=TEXT(A{r};"DDD")'] + vals + [""] * (25 - len(vals))
        data.append({"range": f"{_q(sheet)}!A{r}:AA{r}", "values": [row]})
        written.append(d)
    if data:
        _ensure_grid(svc, spreadsheet_id, sheet, max(idx.row_for(d) for d in written), 27)
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()
    return written
