import json
from pathlib import Path

from synergy_budget.ledger import append_block, build_snapshot, verify_chain
from synergy_budget.merkle import merkle_root, ZERO_ROOT
from synergy_budget.seed import load_seed


def test_empty_root():
    assert merkle_root([]) == ZERO_ROOT


def test_merkle_is_deterministic():
    assert merkle_root([b"a", b"b", b"c"]) == merkle_root([b"a", b"b", b"c"])


def test_chain_verifies(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    snapshot = build_snapshot([{"a": 1}], [{"b": 2}], as_of="2026-08-21T00:00:00+00:00")
    append_block(ledger, snapshot)
    append_block(ledger, snapshot)
    assert verify_chain(ledger)[0]


def test_tampering_is_detected(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    snapshot = build_snapshot([{"a": 1}], [], as_of="2026-08-21T00:00:00+00:00")
    append_block(ledger, snapshot)
    block = json.loads(ledger.read_text("utf-8"))
    block["metadata"]["evil"] = True
    ledger.write_text(json.dumps(block) + "\n", "utf-8")
    assert not verify_chain(ledger)[0]


def test_budget_identity():
    root = Path(__file__).resolve().parents[1]
    records = load_seed(root / "data/seed/federal_budget_2026_core.json")
    by_type = {r["record_type"]: r for r in records}
    revenue = by_type["FEDERAL_BUDGET_REVENUE_PLAN"]["amount_kopecks"]
    expense = by_type["FEDERAL_BUDGET_EXPENDITURE_PLAN"]["amount_kopecks"]
    deficit = by_type["FEDERAL_BUDGET_DEFICIT_PLAN"]["amount_kopecks"]
    assert expense - revenue == deficit
