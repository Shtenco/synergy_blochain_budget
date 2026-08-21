from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .canonical import object_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    budget_year INTEGER NOT NULL,
    amount_kopecks INTEGER,
    kbk TEXT,
    registry_number TEXT,
    contract_number TEXT,
    ikz TEXT,
    customer_inn TEXT,
    supplier_inn TEXT,
    payment_id TEXT,
    source_file TEXT,
    payload_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_year_type ON records(budget_year, record_type);
CREATE INDEX IF NOT EXISTS idx_records_year_kbk ON records(budget_year, kbk);
CREATE INDEX IF NOT EXISTS idx_records_registry ON records(registry_number);
CREATE INDEX IF NOT EXISTS idx_records_contract ON records(contract_number);
CREATE INDEX IF NOT EXISTS idx_records_ikz ON records(ikz);
CREATE INDEX IF NOT EXISTS idx_records_customer ON records(customer_inn);
CREATE INDEX IF NOT EXISTS idx_records_supplier ON records(supplier_inn);
CREATE INDEX IF NOT EXISTS idx_records_payment ON records(payment_id);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA temp_store=MEMORY")
    db.executescript(SCHEMA)
    return db


def _row(record: dict, source_file: str) -> tuple:
    dims = record.get("dimensions") or {}
    record_id = str(record.get("record_id") or object_hash(record))
    return (
        record_id,
        str(record.get("record_type") or "UNKNOWN"),
        int(record.get("budget_year") or 0),
        int(record["amount_kopecks"]) if record.get("amount_kopecks") is not None else None,
        str(dims.get("kbk") or ""),
        str(dims.get("registry_number") or ""),
        str(dims.get("contract_number") or ""),
        str(dims.get("ikz") or ""),
        str(dims.get("customer_inn") or ""),
        str(dims.get("supplier_inn") or ""),
        str(dims.get("payment_id") or ""),
        source_file,
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        datetime.now(timezone.utc).isoformat(),
    )


def ingest_records(db: sqlite3.Connection, records: Iterable[dict], source_file: str = "", batch_size: int = 5000) -> dict:
    sql = """INSERT OR IGNORE INTO records(
        record_id,record_type,budget_year,amount_kopecks,kbk,registry_number,contract_number,ikz,
        customer_inn,supplier_inn,payment_id,source_file,payload_json,ingested_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    batch = []
    seen = 0
    before = db.total_changes
    for record in records:
        seen += 1
        batch.append(_row(record, source_file))
        if len(batch) >= batch_size:
            db.executemany(sql, batch); db.commit(); batch.clear()
    if batch:
        db.executemany(sql, batch); db.commit()
    inserted = db.total_changes - before
    return {"seen": seen, "inserted": inserted, "duplicates": seen - inserted}


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def ingest_jsonl(db: sqlite3.Connection, paths: Iterable[Path], batch_size: int = 5000) -> dict:
    total = {"seen": 0, "inserted": 0, "duplicates": 0, "files": 0}
    for path in paths:
        result = ingest_records(db, iter_jsonl(path), source_file=path.as_posix(), batch_size=batch_size)
        total["files"] += 1
        for key in ("seen", "inserted", "duplicates"):
            total[key] += result[key]
    return total


def iter_records(db: sqlite3.Connection, *, year: int | None = None, record_types: Iterable[str] | None = None) -> Iterator[dict]:
    where = []
    args: list[object] = []
    if year is not None:
        where.append("budget_year=?"); args.append(int(year))
    types = list(record_types or [])
    if types:
        where.append("record_type IN (%s)" % ",".join("?" for _ in types)); args.extend(types)
    sql = "SELECT payload_json FROM records" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY record_id"
    for (payload,) in db.execute(sql, args):
        yield json.loads(payload)


def stats(db: sqlite3.Connection) -> dict:
    total = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    years = {str(y): n for y, n in db.execute("SELECT budget_year,COUNT(*) FROM records GROUP BY budget_year ORDER BY budget_year")}
    types = {t: n for t, n in db.execute("SELECT record_type,COUNT(*) FROM records GROUP BY record_type ORDER BY record_type")}
    return {"schema_version": "sinergy.budget.warehouse-stats/v1", "records": total, "by_year": years, "by_type": types}
