from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .canonical import object_hash

PUBLIC = "PUBLIC"
AGGREGATED = "AGGREGATED"
RESTRICTED_REFERENCE = "RESTRICTED_REFERENCE"


@dataclass(frozen=True)
class BudgetRecord:
    record_type: str
    budget_year: int
    amount_kopecks: int | None
    currency: str
    dimensions: dict[str, Any]
    source: dict[str, Any]
    visibility: str = PUBLIC
    schema_version: str = "sinergy.budget.record/v1"

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["record_id"] = object_hash(value)
        return value


@dataclass(frozen=True)
class Artifact:
    source_id: str
    url: str
    final_url: str
    sha256: str
    byte_size: int
    content_type: str | None
    retrieved_at: str
    relative_path: str
    status: str = "downloaded"

    def payload(self) -> dict[str, Any]:
        return asdict(self)
