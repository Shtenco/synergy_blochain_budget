from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict

CLASSIFICATION_KEYS = ("kbk", "grbs", "section", "subsection", "target_article", "expense_type")
APPROPRIATION_TYPES = {"FEDERAL_BUDGET_APPROPRIATION"}
LIMIT_TYPES = {"FEDERAL_BUDGET_LIMIT"}
ACTUAL_TYPES = {"FEDERAL_BUDGET_CASH_EXECUTION"}
COMMITMENT_TYPES = {"FEDERAL_BUDGET_COMMITMENT", "FEDERAL_BUDGET_MONETARY_OBLIGATION"}


def record_key(record: dict) -> tuple:
    dims = record.get("dimensions") or {}
    return (record.get("budget_year"),) + tuple(str(dims.get(k, "")) for k in CLASSIFICATION_KEYS)


@dataclass(frozen=True)
class ReconciliationRow:
    budget_year: int
    kbk: str
    appropriation_kopecks: int
    limit_kopecks: int
    commitments_kopecks: int
    cash_execution_kopecks: int
    control_plan_kopecks: int
    variance_to_control_plan_kopecks: int
    execution_basis_points: int | None
    status: str

    def payload(self) -> dict:
        return asdict(self)


def reconcile(records: list[dict], tolerance_kopecks: int = 1) -> list[dict]:
    buckets = defaultdict(lambda: {"appropriation": 0, "limit": 0, "commitments": 0, "actual": 0})
    for r in records:
        amount = r.get("amount_kopecks")
        if amount is None:
            continue
        rt = r.get("record_type")
        key = record_key(r)
        if rt in APPROPRIATION_TYPES:
            field = "appropriation"
        elif rt in LIMIT_TYPES:
            field = "limit"
        elif rt in ACTUAL_TYPES:
            field = "actual"
        elif rt in COMMITMENT_TYPES:
            field = "commitments"
        else:
            continue
        buckets[key][field] += int(amount)

    out = []
    for key in sorted(buckets):
        year, kbk, *_ = key
        v = buckets[key]
        control_plan = v["limit"] if v["limit"] else v["appropriation"]
        actual = v["actual"]
        variance = control_plan - actual
        if control_plan == 0 and actual:
            status = "MISSING_PLAN"
            bps = None
        elif control_plan == 0:
            status = "NO_ACTIVITY"
            bps = None
        elif abs(variance) <= tolerance_kopecks:
            status = "EXACT"
            bps = 10_000
        elif actual > control_plan:
            status = "OVER_EXECUTED"
            bps = (actual * 10_000) // control_plan
        else:
            status = "UNDER_EXECUTED"
            bps = (actual * 10_000) // control_plan
        out.append(ReconciliationRow(
            int(year or 0), kbk, v["appropriation"], v["limit"], v["commitments"], actual,
            control_plan, variance, bps, status,
        ).payload())
    return out
