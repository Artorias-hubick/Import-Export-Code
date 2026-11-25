"""Робота з файлом «Калькулятор IMPORT_EXPORT.xlsx» прямо на Google Drive.

Файл за посиланням https://docs.google.com/spreadsheets/d/<ID>/edit — це xlsx,
а не нативна Google Таблиця, тому Sheets API клітинки в ньому не змінює.
Натомість скрипт:
  1) завантажує поточну версію файлу з Drive,
  2) дописує дані локально (лише потрібні аркуші, решта книги не змінюється),
  3) заливає результат НОВОЮ ВЕРСІЄЮ ТОГО САМОГО файлу (files.update).
Посилання, gid листів і доступи лишаються ті самі; попередні версії видно
в Drive → «Керувати версіями».

Авторизація (один раз):
  * console.cloud.google.com → новий проєкт → увімкнути «Google Drive API»
  * APIs & Services → Credentials → Create credentials → OAuth client ID →
    тип «Desktop app» → завантажити JSON і покласти поруч як credentials.json
  * перший запуск відкриє браузер для входу під вашим акаунтом;
    токен збережеться в token.json, далі вхід не потрібен.
"""
from __future__ import annotations

import io
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HERE = os.path.dirname(os.path.abspath(__file__))


def service(credentials_file: str = None, token_file: str = None):
    credentials_file = credentials_file or os.path.join(HERE, "credentials.json")
    token_file = token_file or os.path.join(HERE, "token.json")
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
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def download(svc, file_id: str, dst: str) -> dict:
    meta = svc.files().get(fileId=file_id, fields="id,name,mimeType,modifiedTime,headRevisionId",
                           supportsAllDrives=True).execute()
    if meta["mimeType"] != XLSX_MIME:
        raise RuntimeError(f"Очікувався xlsx, а файл має тип {meta['mimeType']}")
    req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    with io.FileIO(dst, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()
    return meta


def upload_new_revision(svc, file_id: str, src: str, expected_modified: str | None = None) -> dict:
    if expected_modified:
        cur = svc.files().get(fileId=file_id, fields="modifiedTime", supportsAllDrives=True).execute()
        if cur["modifiedTime"] != expected_modified:
            raise RuntimeError("Файл на Drive змінився, поки скрипт працював "
                               f"({expected_modified} → {cur['modifiedTime']}). Запустіть ще раз.")
    media = MediaFileUpload(src, mimetype=XLSX_MIME, resumable=True)
    return svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True,
                              fields="id,name,modifiedTime,headRevisionId").execute()
