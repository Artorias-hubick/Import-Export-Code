"""Точковий запис значень у .xlsx без перезбирання книги.

openpyxl при збереженні втрачає графіки/малюнки/зведені, тому тут ми
змінюємо лише XML потрібних аркушів, а всі інші частини архіву копіюємо
байт-у-байт. Excel перерахує формули при відкритті (fullCalcOnLoad).
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import tempfile
import zipfile

from lxml import etree

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
Q = lambda t: f"{{{NS}}}{t}"  # noqa: E731
EXCEL_EPOCH = dt.date(1899, 12, 30)
FIRST_HOUR_COL = 3  # C = година 1, ..., Z = година 24, AA = година 25 (доба переходу на зимовий час)


def col_letter(idx: int) -> str:
    s = ""
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    wb = etree.fromstring(zf.read("xl/workbook.xml"))
    rels = etree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid2target = {r.get("Id"): r.get("Target") for r in rels}
    res = {}
    for sh in wb.iter(Q("sheet")):
        t = rid2target[sh.get(f"{{{RNS}}}id")]
        t = t.lstrip("/")
        res[sh.get("name")] = t if t.startswith("xl/") else "xl/" + t
    return res


class SheetPatcher:
    """Аркуш виду: A = дата, B = день тижня, C.. = години 1..25."""

    def __init__(self, xml: bytes):
        self.root = etree.fromstring(xml)
        self.sheet_data = self.root.find(Q("sheetData"))
        self.rows = {int(r.get("r")): r for r in self.sheet_data.iter(Q("row"))}
        self.date_rows: dict[dt.date, int] = {}
        for rn, row in self.rows.items():
            c = self._cell(row, 1)
            if c is None:
                continue
            v = c.find(Q("v"))
            if v is None or c.get("t") in ("s", "str", "e", "inlineStr"):
                continue
            try:
                serial = float(v.text)
            except (TypeError, ValueError):
                continue
            if 30000 < serial < 80000:
                d = EXCEL_EPOCH + dt.timedelta(days=int(serial))
                self.date_rows.setdefault(d, rn)

    @staticmethod
    def _cell(row, col):
        for c in row.iter(Q("c")):
            if col_index(c.get("r")) == col:
                return c
        return None

    def row_has_data(self, d: dt.date) -> bool:
        row = self.rows[self.date_rows[d]]
        for c in row.iter(Q("c")):
            ci = col_index(c.get("r"))
            if FIRST_HOUR_COL <= ci < FIRST_HOUR_COL + 25 and c.find(Q("v")) is not None:
                return True
        return False

    def last_filled_date(self) -> dt.date | None:
        filled = [d for d in self.date_rows if self.row_has_data(d)]
        return max(filled) if filled else None

    def _style_above(self, rn: int, col: int) -> str | None:
        for r in range(rn - 1, max(1, rn - 40), -1):
            row = self.rows.get(r)
            if row is None:
                continue
            c = self._cell(row, col)
            if c is not None and c.get("s") is not None:
                return c.get("s")
        return None

    def ensure_date_row(self, d: dt.date) -> bool:
        """Продовжує колонку дат: якщо рядка з датою d немає, але є рядок з d-1,
        записує d у наступний рядок (A = дата, B = =TEXT(A;"DDD") як у книзі)."""
        if d in self.date_rows:
            return True
        prev = self.date_rows.get(d - dt.timedelta(days=1))
        if prev is None:
            return False
        rn = prev + 1
        row = self.rows.get(rn)
        if row is None:
            row = etree.SubElement(self.sheet_data, Q("row"))
            row.set("r", str(rn))
            self.rows[rn] = row
            rows = sorted(self.sheet_data.findall(Q("row")), key=lambda r: int(r.get("r")))
            for r in rows:
                self.sheet_data.remove(r)
            for r in rows:
                self.sheet_data.append(r)
        prev_row = self.rows[prev]
        # A: дата (стиль як у попереднього рядка з датою)
        a = self._cell(row, 1)
        if a is None:
            a = etree.SubElement(row, Q("c"))
            a.set("r", f"A{rn}")
        pa = self._cell(prev_row, 1)
        if pa is not None and pa.get("s") is not None:
            a.set("s", pa.get("s"))
        for ch in list(a):
            a.remove(ch)
        a.attrib.pop("t", None)
        etree.SubElement(a, Q("v")).text = str((d - EXCEL_EPOCH).days)
        # B: день тижня, якщо там ще нема формули
        b = self._cell(row, 2)
        if b is None or b.find(Q("f")) is None:
            if b is None:
                b = etree.SubElement(row, Q("c"))
                b.set("r", f"B{rn}")
            pb = self._cell(prev_row, 2)
            if pb is not None and pb.get("s") is not None:
                b.set("s", pb.get("s"))
            for ch in list(b):
                b.remove(ch)
            b.set("t", "str")
            etree.SubElement(b, Q("f")).text = f'TEXT(A{rn},"DDD")'
            etree.SubElement(b, Q("v")).text = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"][d.weekday()]
        cells = sorted(row.findall(Q("c")), key=lambda c: col_index(c.get("r")))
        for c in cells:
            row.remove(c)
        for c in cells:
            row.append(c)
        row.attrib.pop("spans", None)
        self.date_rows[d] = rn
        return True

    def write_day(self, d: dt.date, values: list) -> bool:
        rn = self.date_rows.get(d)
        if rn is None:
            return False
        row = self.rows[rn]
        existing = {col_index(c.get("r")): c for c in row.findall(Q("c"))}
        for i, val in enumerate(values[:25]):
            col = FIRST_HOUR_COL + i
            c = existing.get(col)
            if c is None:
                c = etree.SubElement(row, Q("c"))
                c.set("r", f"{col_letter(col)}{rn}")
                s = self._style_above(rn, col)
                if s is not None:
                    c.set("s", s)
                existing[col] = c
            for child in list(c):
                c.remove(child)
            v = etree.SubElement(c, Q("v"))
            if isinstance(val, str):
                c.set("t", "e")
                v.text = val
            else:
                if "t" in c.attrib:
                    del c.attrib["t"]
                v.text = "%.10g" % float(val)
        # впорядкувати клітинки рядка за колонками
        cells = sorted(row.findall(Q("c")), key=lambda c: col_index(c.get("r")))
        for c in cells:
            row.remove(c)
        for c in cells:
            row.append(c)
        if "spans" in row.attrib:
            del row.attrib["spans"]
        return True

    def tobytes(self) -> bytes:
        return etree.tostring(self.root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _force_recalc(xml: bytes) -> bytes:
    root = etree.fromstring(xml)
    calc = root.find(Q("calcPr"))
    if calc is None:
        calc = etree.SubElement(root, Q("calcPr"))
    calc.set("fullCalcOnLoad", "1")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def open_sheets(path: str, names: list[str]) -> dict[str, SheetPatcher]:
    with zipfile.ZipFile(path) as zf:
        paths = sheet_paths(zf)
        return {n: SheetPatcher(zf.read(paths[n])) for n in names if n in paths}


def save(src: str, dst: str, patched: dict[str, SheetPatcher]) -> None:
    with zipfile.ZipFile(src) as zin:
        paths = sheet_paths(zin)
        replace = {paths[n]: p.tobytes() for n, p in patched.items()}
        replace["xl/workbook.xml"] = _force_recalc(zin.read("xl/workbook.xml"))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        tmp.close()
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = replace.get(item.filename)
                if data is None:
                    zout.writestr(item, zin.read(item.filename))
                else:
                    zout.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED)
    shutil.move(tmp.name, dst)
