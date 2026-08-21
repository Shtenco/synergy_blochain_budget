from __future__ import annotations

import json
from pathlib import Path

from .models import BudgetRecord


def load_seed(path: Path) -> list[dict]:
    raw = json.loads(path.read_text("utf-8"))
    records: list[dict] = []
    for item in raw["records"]:
        r = BudgetRecord(
            record_type=item["record_type"],
            budget_year=int(item["budget_year"]),
            amount_kopecks=item.get("amount_kopecks"),
            currency=item.get("currency", "RUB"),
            dimensions=item.get("dimensions", {}),
            source=item["source"],
            visibility=item.get("visibility", "PUBLIC"),
        )
        records.append(r.payload())
    return records
