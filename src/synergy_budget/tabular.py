from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Iterator

MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_UNCOMPRESSED = 2_000_000_000
SUPPORTED = {".csv", ".txt", ".xls", ".xlsx", ".xml", ".json"}


@dataclass(frozen=True)
class Table:
    source_name: str
    sheet_name: str
    rows: list[list[object]]


def normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\xa0", " ").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_header(value: object) -> str:
    text = normalize_text(value).lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", " ", text).strip()


def money_to_kopecks(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    text = normalize_text(value)
    if not text or text in {"-", "—", "–", "…", "..."}:
        return None
    text = text.replace(" ", "").replace("\u202f", "").replace(",", ".")
    text = re.sub(r"[^0-9.+-]", "", text)
    if text.count(".") > 1:
        first, *rest = text.split(".")
        text = first + "".join(rest[:-1]) + "." + rest[-1]
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _decode_csv(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1251", "koi8-r"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def read_csv_bytes(data: bytes, source_name: str) -> list[Table]:
    text = _decode_csv(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    rows = [list(row) for row in csv.reader(io.StringIO(text), dialect)]
    return [Table(source_name, "CSV", rows)]


def read_xlsx_bytes(data: bytes, source_name: str) -> list[Table]:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to parse XLSX; install project extra 'excel'") from exc
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out: list[Table] = []
    try:
        for ws in wb.worksheets:
            rows = [list(row) for row in ws.iter_rows(values_only=True)]
            out.append(Table(source_name, ws.title, rows))
    finally:
        wb.close()
    return out


def read_xls_bytes(data: bytes, source_name: str) -> list[Table]:
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError("xlrd>=2.0.1 is required to parse legacy XLS; install project extra 'excel'") from exc
    book = xlrd.open_workbook(file_contents=data, on_demand=True)
    out: list[Table] = []
    try:
        for sh in book.sheets():
            out.append(Table(source_name, sh.name, [sh.row_values(i) for i in range(sh.nrows)]))
    finally:
        book.release_resources()
    return out


def read_table_bytes(data: bytes, filename: str) -> list[Table]:
    ext = Path(filename).suffix.lower()
    if ext in {".csv", ".txt"}:
        return read_csv_bytes(data, filename)
    if ext == ".xlsx":
        return read_xlsx_bytes(data, filename)
    if ext == ".xls":
        return read_xls_bytes(data, filename)
    return []


def iter_archive_tables(data: bytes, archive_name: str) -> Iterator[Table]:
    if not zipfile.is_zipfile(io.BytesIO(data)):
        yield from read_table_bytes(data, archive_name)
        return
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("archive member limit exceeded")
        total = sum(i.file_size for i in infos)
        if total > MAX_ARCHIVE_UNCOMPRESSED:
            raise ValueError("archive uncompressed-size limit exceeded")
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or "../" in name or name.startswith("../"):
                raise ValueError(f"unsafe archive path: {name}")
            ext = Path(name).suffix.lower()
            if ext not in SUPPORTED and ext != ".zip":
                continue
            payload = zf.read(info)
            nested_name = f"{archive_name}!{name}"
            if ext == ".zip":
                yield from iter_archive_tables(payload, nested_name)
            else:
                yield from read_table_bytes(payload, nested_name)


def find_header_row(rows: list[list[object]], required_tokens: Iterable[str] = ()) -> int | None:
    tokens = tuple(normalize_header(t) for t in required_tokens)
    best: tuple[int, int] | None = None
    for idx, row in enumerate(rows[:80]):
        cells = [normalize_header(c) for c in row]
        nonempty = sum(bool(c) for c in cells)
        hits = sum(any(t in c for c in cells if c) for t in tokens)
        score = hits * 100 + nonempty
        if nonempty >= 2 and (best is None or score > best[0]):
            best = (score, idx)
    return None if best is None else best[1]


def matrix_to_records(table: Table, header_row: int) -> list[dict[str, object]]:
    headers = [normalize_text(x) or f"column_{i+1}" for i, x in enumerate(table.rows[header_row])]
    seen: dict[str, int] = {}
    unique: list[str] = []
    for h in headers:
        count = seen.get(h, 0) + 1
        seen[h] = count
        unique.append(h if count == 1 else f"{h}__{count}")
    out: list[dict[str, object]] = []
    for row in table.rows[header_row + 1 :]:
        if not any(normalize_text(v) for v in row):
            continue
        values = list(row) + [None] * max(0, len(unique) - len(row))
        out.append({unique[i]: values[i] for i in range(len(unique))})
    return out
