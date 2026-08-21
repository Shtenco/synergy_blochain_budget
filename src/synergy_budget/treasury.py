from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .kbk import ExpenseKBK, clean_code
from .tabular import Table, find_header_row, iter_archive_tables, matrix_to_records, money_to_kopecks, normalize_header, normalize_text

DIMENSION_ALIASES = {
    "kbk": ("код бюджетной классификации", "код по бюджетной классификации", "кбк"),
    "grbs": ("грбс", "главного распорядителя", "глава по бк", "глава"),
    "section": ("раздел", "раздела"),
    "subsection": ("подраздел", "подраздела"),
    "target_article": ("целевая статья", "цср"),
    "expense_type": ("вид расходов", "вр"),
    "indicator": ("наименование показателя", "наименование", "показатель"),
}

AMOUNT_RULES = (
    (("кассовое исполнение", "исполнено", "кассовые расходы"), "FEDERAL_BUDGET_CASH_EXECUTION"),
    (("лимит бюджетных обязательств", "лимиты бюджетных обязательств", "лбо"), "FEDERAL_BUDGET_LIMIT"),
    (("бюджетные ассигнования", "утвержденные бюджетные назначения", "сводная бюджетная роспись", "план"), "FEDERAL_BUDGET_APPROPRIATION"),
    (("денежные обязательства",), "FEDERAL_BUDGET_MONETARY_OBLIGATION"),
    (("бюджетные обязательства",), "FEDERAL_BUDGET_COMMITMENT"),
    (("доходы", "поступило доходов", "кассовое поступление"), "FEDERAL_BUDGET_REVENUE_EXECUTION"),
)


@dataclass(frozen=True)
class ParsedRecord:
    record_type: str
    budget_year: int
    amount_kopecks: int
    currency: str
    dimensions: dict[str, object]
    source: dict[str, object]
    visibility: str = "PUBLIC"
    schema_version: str = "sinergy.budget.record/v2"

    def payload(self) -> dict[str, object]:
        return {
            "record_type": self.record_type,
            "budget_year": self.budget_year,
            "amount_kopecks": self.amount_kopecks,
            "currency": self.currency,
            "dimensions": self.dimensions,
            "source": self.source,
            "visibility": self.visibility,
            "schema_version": self.schema_version,
        }


def _column_by_alias(columns: Iterable[str], aliases: Iterable[str]) -> str | None:
    normalized = [(c, normalize_header(c)) for c in columns]
    for alias in aliases:
        needle = normalize_header(alias)
        for original, norm in normalized:
            if needle == norm or needle in norm:
                return original
    return None


def _amount_columns(columns: Iterable[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for col in columns:
        norm = normalize_header(col)
        for needles, record_type in AMOUNT_RULES:
            if any(normalize_header(n) in norm for n in needles):
                out.append((col, record_type))
                break
    return out


def _dimensions(row: dict[str, object], columns: list[str]) -> dict[str, object]:
    dims: dict[str, object] = {}
    for key, aliases in DIMENSION_ALIASES.items():
        col = _column_by_alias(columns, aliases)
        if col:
            value = normalize_text(row.get(col))
            if value:
                dims[key] = value
    if "kbk" in dims:
        code = clean_code(dims["kbk"])
        if len(code) == 20:
            try:
                dims.update(ExpenseKBK.parse(code).dimensions())
                return dims
            except ValueError:
                pass
    needed = ("grbs", "section", "subsection", "target_article", "expense_type")
    if all(k in dims for k in needed):
        try:
            dims.update(ExpenseKBK.from_parts(*(dims[k] for k in needed)).dimensions())
        except ValueError:
            pass
    return dims


def parse_table(table: Table, budget_year: int, source_id: str, artifact_sha256: str | None = None) -> list[ParsedRecord]:
    header = find_header_row(table.rows, required_tokens=("наименование", "раздел", "исполнено"))
    if header is None:
        return []
    rows = matrix_to_records(table, header)
    if not rows:
        return []
    columns = list(rows[0])
    amount_cols = _amount_columns(columns)
    if not amount_cols:
        return []
    out: list[ParsedRecord] = []
    for row_idx, row in enumerate(rows, start=header + 2):
        dims = _dimensions(row, columns)
        indicator = normalize_text(dims.get("indicator"))
        if indicator.lower() in {"итого", "всего"} and len(dims) == 1:
            dims["aggregation"] = "TOTAL"
        for col, record_type in amount_cols:
            amount = money_to_kopecks(row.get(col))
            if amount is None:
                continue
            source = {
                "source_id": source_id,
                "artifact": table.source_name,
                "sheet": table.sheet_name,
                "row": row_idx,
                "amount_column": col,
            }
            if artifact_sha256:
                source["artifact_sha256"] = artifact_sha256
            out.append(ParsedRecord(record_type, budget_year, amount, "RUB", dims, source))
    return out


def parse_artifact(path: Path, budget_year: int, source_id: str, artifact_sha256: str | None = None) -> list[dict[str, object]]:
    data = path.read_bytes()
    records: list[dict[str, object]] = []
    for table in iter_archive_tables(data, path.name):
        records.extend(r.payload() for r in parse_table(table, budget_year, source_id, artifact_sha256))
    return records
