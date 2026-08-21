import json
from pathlib import Path

import pytest

from synergy_budget.mock_corpus import (
    AMBIGUOUS, MOCK_MARKER, PUBLIC_CORPORA, MockCorpusConfig,
    assert_mock_only, generate_mock_corpus, validate_mock_corpus,
)
from synergy_budget.eis import parse_eis_artifact
from synergy_budget.treasury import parse_artifact

def test_mock_config_requires_100_percent():
    with pytest.raises(ValueError):
        MockCorpusConfig(traceable_pct=64).validate()

def test_demo_ground_truth_metrics(tmp_path: Path):
    root = tmp_path / "mock"
    manifest = generate_mock_corpus(root, MockCorpusConfig(start_year=2026,end_year=2026,contracts_per_year=100,kbk_per_year=12,institutions_per_year=8,seed=7,emit_raw=True))
    m = manifest["coverage_metrics"]
    assert m["public_contracts"] == 100
    assert m["traceable_contracts_pct"] == 65.0
    assert m["ambiguity_rate_pct"] == 5.0
    assert m["unresolved_kbk_rate_pct"] == 10.0
    assert m["public_proof_coverage_pct"] == 100.0
    assert 0 < m["federal_cash_traceability_pct"] < 100

def test_all_public_corpora_have_files(tmp_path: Path):
    manifest = generate_mock_corpus(tmp_path/"mock", MockCorpusConfig(start_year=2026,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=8,emit_raw=False))
    for corpus in PUBLIC_CORPORA:
        assert manifest["files"][corpus], corpus

def test_every_canonical_record_is_hard_marked_mock(tmp_path: Path):
    root=tmp_path/"mock"
    generate_mock_corpus(root, MockCorpusConfig(start_year=2026,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=9,emit_raw=False))
    records=[json.loads(x) for x in (root/"canonical"/"all_records.jsonl").read_text("utf-8").splitlines() if x.strip()]
    assert_mock_only(records)
    assert (root/"MOCK_ONLY").read_text("utf-8").strip() == MOCK_MARKER

def test_mock_guard_rejects_real_record():
    with pytest.raises(ValueError):
        assert_mock_only([{"record_type":"REALISH","budget_year":2026}])

def test_generation_is_deterministic(tmp_path: Path):
    cfg=MockCorpusConfig(start_year=2025,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=123,emit_raw=False)
    a=generate_mock_corpus(tmp_path/"a",cfg); b=generate_mock_corpus(tmp_path/"b",cfg)
    assert a["record_merkle_root"] == b["record_merkle_root"]
    assert a["coverage_metrics"] == b["coverage_metrics"]

def test_raw_treasury_roundtrip(tmp_path: Path):
    root=tmp_path/"mock"
    generate_mock_corpus(root, MockCorpusConfig(start_year=2026,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=10,emit_raw=True))
    rows=parse_artifact(root/"raw"/"treasury_federal_budget"/"2026"/"federal-budget-2026.zip",2026,"treasury-federal-budget")
    types={r["record_type"] for r in rows}
    assert {"FEDERAL_BUDGET_APPROPRIATION","FEDERAL_BUDGET_LIMIT","FEDERAL_BUDGET_COMMITMENT","FEDERAL_BUDGET_MONETARY_OBLIGATION","FEDERAL_BUDGET_CASH_EXECUTION"} <= types

def test_raw_eis_roundtrip(tmp_path: Path):
    root=tmp_path/"mock"
    generate_mock_corpus(root, MockCorpusConfig(start_year=2026,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=11,emit_raw=True))
    rows=parse_eis_artifact(root/"raw"/"eis_procurement"/"2026"/"eis-2026.zip",2026)
    types={r["record_type"] for r in rows}
    assert "PROCUREMENT_CONTRACT" in types and "PROCUREMENT_PAYMENT" in types
    assert sum(r["record_type"]=="PROCUREMENT_CONTRACT" for r in rows)==100

def test_validator_recomputes_ground_truth(tmp_path: Path):
    root=tmp_path/"mock"
    generate_mock_corpus(root, MockCorpusConfig(start_year=2025,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=12,emit_raw=False))
    assert validate_mock_corpus(root)["ok"]

def test_only_metadata_reference_for_classified_annex(tmp_path: Path):
    root=tmp_path/"mock"
    generate_mock_corpus(root, MockCorpusConfig(start_year=2026,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=13,emit_raw=False))
    rows=[json.loads(x) for x in (root/"canonical"/"pravo_budget_law"/"2026.jsonl").read_text("utf-8").splitlines() if x.strip()]
    ref=next(r for r in rows if r["record_type"]=="CLASSIFIED_ANNEX_REFERENCE")
    assert ref["amount_kopecks"] is None
    assert ref["dimensions"]["policy"]=="metadata_only_no_content"
    assert "content" not in ref["dimensions"]

def test_ambiguous_contracts_are_unique_records(tmp_path: Path):
    root=tmp_path/"mock"
    generate_mock_corpus(root, MockCorpusConfig(start_year=2026,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=14,emit_raw=False))
    rows=[json.loads(x) for x in (root/"canonical"/"eis_procurement"/"2026.jsonl").read_text("utf-8").splitlines() if x.strip()]
    ambiguous=[r for r in rows if r["record_type"]=="PROCUREMENT_CONTRACT" and r["dimensions"].get("mock_truth_status")==AMBIGUOUS]
    assert len(ambiguous)==5
    assert len({r["record_id"] for r in ambiguous})==5

def test_no_real_anchor_files_generated(tmp_path: Path):
    root=tmp_path/"mock"
    generate_mock_corpus(root, MockCorpusConfig(start_year=2026,end_year=2026,contracts_per_year=100,kbk_per_year=8,institutions_per_year=4,seed=15,emit_raw=False))
    assert not (root/"data"/"ledger"/"blocks.jsonl").exists()
    assert not (root/"anchor.json").exists()
