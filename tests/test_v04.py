import hashlib
import http.server
import json
import socketserver
import threading
from pathlib import Path

from synergy_budget.archive_node import append_manifest, download_resumable
from synergy_budget.bulk import _DiscoveryParser, discover_filter_pages
from synergy_budget.coverage import compute_coverage
from synergy_budget.canonical import object_hash
from synergy_budget.proofs import build_record_proof_bundle


def test_discovery_parser_finds_server_filter_values():
    p = _DiscoveryParser()
    p.feed('<select name="filter_type"><option value="43">годовой</option><option value="45">ежемесячный</option></select>')
    assert p.options["filter_type"] == [("43", "годовой"), ("45", "ежемесячный")]


def test_coverage_metrics_exact_denominators():
    traces = [
        {"budget_year": 2026, "trace_id": "a", "registry_number": "1", "contract_number": "A", "ikz": "", "contract_amount_kopecks": 10000, "status": "TRACEABLE", "kbk": "K1", "kbk_resolution": {"status": "RESOLVED"}, "ambiguous_payment_links": []},
        {"budget_year": 2026, "trace_id": "b", "registry_number": "2", "contract_number": "B", "ikz": "", "contract_amount_kopecks": 30000, "status": "PARTIAL_KBK_UNRESOLVED", "kbk": "K2", "kbk_resolution": {"status": "UNRESOLVED"}, "ambiguous_payment_links": [{"payment_ref": "p"}]},
    ]
    records = [
        {"record_type": "BUDGET_TRACE_COMMITMENT", "budget_year": 2026, "dimensions": {"trace_id": "a"}},
        {"record_type": "BUDGET_TRACE_COMMITMENT", "budget_year": 2026, "dimensions": {"trace_id": "b"}},
    ]
    for r in records: r["record_id"] = object_hash(r)
    proofs = build_record_proof_bundle([records[0]])
    m = compute_coverage(traces, records, proofs)
    assert m["traceable_rub_pct"] == 25.0
    assert m["traceable_contracts_pct"] == 50.0
    assert m["ambiguity_rate_pct"] == 50.0
    assert m["unresolved_kbk_rate_pct"] == 50.0
    assert m["public_proof_coverage_pct"] == 50.0


def test_zero_denominators_are_none():
    m = compute_coverage([], [], None)
    assert m["traceable_rub_pct"] is None
    assert m["public_proof_coverage_pct"] is None


def test_resumable_download_and_content_address(tmp_path: Path):
    payload = b"budget-data-" * 10000
    served = tmp_path / "served"; served.mkdir(); (served / "report.zip").write_bytes(payload)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
    old = Path.cwd()
    import os
    os.chdir(served)
    try:
        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            port = server.server_address[1]
            out = tmp_path / "archive"
            result = download_resumable(f"http://127.0.0.1:{port}/report.zip", out, "test", ["127.0.0.1"], retries=0)
            assert result.sha256 == hashlib.sha256(payload).hexdigest()
            assert Path(result.relative_path).read_bytes() == payload
            server.shutdown()
    finally:
        os.chdir(old)


def test_manifest_deduplicates(tmp_path: Path):
    from synergy_budget.archive_node import DownloadResult
    x = DownloadResult("s", "u", "u", "a"*64, 1, None, None, "t", "p")
    path = tmp_path / "m.json"
    append_manifest(path, [x]); out = append_manifest(path, [x])
    assert len(out["artifacts"]) == 1


def test_contract_identity_deduplicates_trace_revisions():
    traces = [
        {"budget_year": 2026, "trace_id": "old", "registry_number": "R1", "contract_number": "C1", "ikz": "I1", "contract_amount_kopecks": 10000, "status": "TRACEABLE", "kbk": "K", "kbk_resolution": {"status": "RESOLVED"}, "ambiguous_payment_links": []},
        {"budget_year": 2026, "trace_id": "new", "registry_number": "R1", "contract_number": "C1", "ikz": "I1", "contract_amount_kopecks": 10000, "status": "TRACEABLE", "kbk": "K", "kbk_resolution": {"status": "RESOLVED"}, "ambiguous_payment_links": []},
    ]
    m = compute_coverage(traces)
    assert m["public_contracts"] == 1
    assert m["traceable_rub_kopecks"] == 10000


def test_tampered_proof_is_not_counted():
    record = {"record_type": "BUDGET_TRACE_COMMITMENT", "budget_year": 2026, "dimensions": {"trace_id": "x"}}
    record["record_id"] = object_hash(record)
    bundle = build_record_proof_bundle([record])
    bad = json.loads(json.dumps(bundle)); bad["proofs"][0]["record_hash"] = "0" * 64
    m = compute_coverage([], [record], bad)
    assert m["verified_public_proofs"] == 0
    assert m["public_proof_coverage_pct"] == 0.0


def test_soi_plan_rejects_embedded_secret(tmp_path: Path):
    from synergy_budget.eis_soi import load_request_plan
    p = tmp_path / "soi.json"; p.write_text(json.dumps({"requests": [{"method": "getNsiRequest", "kwargs": {"base": "fz44", "token": "secret"}}]}), "utf-8")
    import pytest
    with pytest.raises(ValueError, match="secret field"): load_request_plan(p)


def test_soi_plan_accepts_documented_method_without_credentials(tmp_path: Path):
    from synergy_budget.eis_soi import load_request_plan
    p = tmp_path / "soi.json"; p.write_text(json.dumps({"requests": [{"method": "getNsiRequest", "kwargs": {"base": "fz44", "nsicode": "nsiDocumentTypes", "prefix": "nsi/fz44/doc-types"}}]}), "utf-8")
    rows = load_request_plan(p)
    assert rows[0]["method"] == "getNsiRequest" and "token" not in rows[0]["kwargs"]


def test_warehouse_streaming_deduplicates(tmp_path: Path):
    from synergy_budget.warehouse import connect, ingest_jsonl, stats
    rows = tmp_path / "r.jsonl"
    record = {"record_type":"PROCUREMENT_CONTRACT","budget_year":2026,"amount_kopecks":10,"dimensions":{"registry_number":"R"}}; record["record_id"] = object_hash(record)
    rows.write_text(json.dumps(record)+"\n"+json.dumps(record)+"\n", "utf-8")
    db = connect(tmp_path / "w.sqlite3")
    try:
        result = ingest_jsonl(db, [rows])
        assert result["seen"] == 2 and result["inserted"] == 1 and result["duplicates"] == 1
        assert stats(db)["records"] == 1
    finally: db.close()


def test_filter_contexts_preserve_requested_year(monkeypatch):
    import synergy_budget.bulk as bulk
    html = '<select name="filter_type"><option value="43">годовой</option></select>'
    monkeypatch.setattr(bulk, "_fetch_html", lambda url, timeout=60: (html, url))
    source = {"url":"https://example.test/reports","allowed_domains":["example.test"],"archive_year_param":"filter_year"}
    contexts = bulk.discover_filter_contexts(source, range(2025, 2027))
    assert [x["requested_year"] for x in contexts] == [2025, 2026]
    assert all("filter_type=43" in x["page_url"] for x in contexts)


def test_federal_cash_traceability_uses_payment_values_not_contract_prices():
    payment = {"record_type":"PROCUREMENT_PAYMENT","budget_year":2026,"amount_kopecks":2000,"dimensions":{"payment_id":"P"}}; payment["record_id"] = object_hash(payment)
    cash = {"record_type":"FEDERAL_BUDGET_CASH_EXECUTION","budget_year":2026,"amount_kopecks":10000,"dimensions":{"kbk":"02004112010490019241"}}; cash["record_id"] = object_hash(cash)
    trace = {"budget_year":2026,"trace_id":"t","registry_number":"R","contract_number":"C","ikz":"I","contract_amount_kopecks":9000,"status":"TRACEABLE","kbk":"02004112010490019241","kbk_resolution":{"status":"RESOLVED"},"ambiguous_payment_links":[],"stages":{"PAYMENT":[payment["record_id"]]}}
    m = compute_coverage([trace], source_records=[payment,cash])
    assert m["traceable_rub_pct"] == 100.0
    assert m["federal_cash_traceability_pct"] == 20.0


def test_soi_executes_only_allowlisted_method(monkeypatch):
    import sys, types
    calls=[]
    class FakeClient:
        def getNsiRequest(self, **kwargs): calls.append(kwargs); return ["ok"]
    fake=types.SimpleNamespace(client=lambda sender: FakeClient()); monkeypatch.setitem(sys.modules,"dars",fake)
    from synergy_budget.eis_soi import execute_request_plan
    out=execute_request_plan([{"method":"getNsiRequest","kwargs":{"base":"fz44","nsicode":"nsiDocumentTypes","prefix":"x"}}])
    assert calls[0]["base"]=="fz44" and out[0]["result"]==["ok"]
