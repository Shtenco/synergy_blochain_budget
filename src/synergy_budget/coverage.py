from __future__ import annotations

from dataclasses import asdict, dataclass

from .canonical import object_hash


def _pct(num: int, den: int) -> float | None:
    return None if den == 0 else round(num * 100.0 / den, 6)


def _identity(trace: dict) -> tuple:
    year = int(trace.get("budget_year") or 0)
    strong = (
        str(trace.get("registry_number") or "").strip(),
        str(trace.get("contract_number") or "").strip(),
        str(trace.get("ikz") or "").strip(),
    )
    if any(strong):
        return (year, *strong)
    return (year, "TRACE_ID", str(trace.get("trace_id") or ""))


@dataclass(frozen=True)
class CoverageMetrics:
    public_contracts: int
    public_contract_rub_kopecks: int
    traceable_contracts: int
    traceable_rub_kopecks: int
    ambiguous_contracts: int
    kbk_evaluable_contracts: int
    unresolved_kbk_contracts: int
    trace_commitments: int
    verified_public_proofs: int
    federal_cash_execution_rub_kopecks: int
    traceable_payment_rub_kopecks: int
    federal_cash_traceability_pct: float | None
    traceable_rub_pct: float | None
    traceable_contracts_pct: float | None
    ambiguity_rate_pct: float | None
    unresolved_kbk_rate_pct: float | None
    public_proof_coverage_pct: float | None

    def payload(self) -> dict:
        return asdict(self)


def compute_coverage(traces: list[dict], trace_records: list[dict] | None = None, proof_bundle: dict | None = None, source_records: list[dict] | None = None) -> dict:
    unique: dict[tuple, dict] = {}
    for trace in traces:
        key = _identity(trace)
        old = unique.get(key)
        if old is None or str(trace.get("trace_id", "")) > str(old.get("trace_id", "")):
            unique[key] = trace
    rows = list(unique.values())

    public_contracts = len(rows)
    public_rub = sum(max(0, int(t.get("contract_amount_kopecks") or 0)) for t in rows)
    traceable = [t for t in rows if t.get("status") == "TRACEABLE"]
    traceable_rub = sum(max(0, int(t.get("contract_amount_kopecks") or 0)) for t in traceable)
    ambiguous = [t for t in rows if t.get("ambiguous_payment_links")]
    kbk_eval = [t for t in rows if str(t.get("kbk") or "").strip()]
    unresolved = [t for t in kbk_eval if (t.get("kbk_resolution") or {}).get("status") != "RESOLVED"]

    records = trace_records or []
    commitment_ids = {str(r.get("record_id") or "") for r in records if r.get("record_type") == "BUDGET_TRACE_COMMITMENT" and r.get("record_id")}
    proof_ids: set[str] = set()
    if proof_bundle:
        from .proofs import verify_record_in_bundle
        root = proof_bundle.get("record_merkle_root")
        records_by_id = {str(r.get("record_id")): r for r in records if r.get("record_id")}
        for proof_entry in proof_bundle.get("proofs", []):
            record_id = str(proof_entry.get("record_id") or "")
            record = records_by_id.get(record_id)
            if root and record_id in commitment_ids and record and verify_record_in_bundle(record, proof_entry, root):
                proof_ids.add(record_id)

    source = source_records or []
    source_by_ref = {str(r.get("record_id") or object_hash(r)): r for r in source}
    payment_refs = {str(ref) for t in traceable for ref in ((t.get("stages") or {}).get("PAYMENT") or [])}
    traceable_payment_rub = sum(max(0, int((source_by_ref.get(ref) or {}).get("amount_kopecks") or 0)) for ref in payment_refs)
    cash_records = [r for r in source if r.get("record_type") == "FEDERAL_BUDGET_CASH_EXECUTION" and str((r.get("dimensions") or {}).get("kbk") or "").strip()]
    cash_unique = {str(r.get("record_id") or object_hash(r)): r for r in cash_records}
    federal_cash = sum(max(0, int(r.get("amount_kopecks") or 0)) for r in cash_unique.values())

    metrics = CoverageMetrics(
        public_contracts=public_contracts,
        public_contract_rub_kopecks=public_rub,
        traceable_contracts=len(traceable),
        traceable_rub_kopecks=traceable_rub,
        ambiguous_contracts=len(ambiguous),
        kbk_evaluable_contracts=len(kbk_eval),
        unresolved_kbk_contracts=len(unresolved),
        trace_commitments=len(commitment_ids),
        verified_public_proofs=len(proof_ids),
        federal_cash_execution_rub_kopecks=federal_cash,
        traceable_payment_rub_kopecks=traceable_payment_rub,
        federal_cash_traceability_pct=_pct(traceable_payment_rub, federal_cash),
        traceable_rub_pct=_pct(traceable_rub, public_rub),
        traceable_contracts_pct=_pct(len(traceable), public_contracts),
        ambiguity_rate_pct=_pct(len(ambiguous), public_contracts),
        unresolved_kbk_rate_pct=_pct(len(unresolved), len(kbk_eval)),
        public_proof_coverage_pct=_pct(len(proof_ids), len(commitment_ids)),
    )
    return {
        "schema_version": "sinergy.budget.coverage/v1",
        "scope": {
            "traceable_rub_denominator": "sum of non-negative values of public contracts represented by traces; this is contract-value coverage, not total federal expenditure",
            "federal_cash_traceability_denominator": "sum of leaf-KBK FEDERAL_BUDGET_CASH_EXECUTION records from ONE non-overlapping reconciled as-of Treasury snapshot supplied as source_records",
            "federal_cash_traceability_numerator": "unique public payment records referenced by TRACEABLE traces and present in the same supplied source record corpus",
            "traceable_contracts_denominator": "unique public contracts represented by traces",
            "ambiguity_denominator": "unique public contracts represented by traces",
            "unresolved_kbk_denominator": "unique public contracts with a non-empty KBK",
            "public_proof_denominator": "BUDGET_TRACE_COMMITMENT records supplied to the metric engine",
        },
        **metrics.payload(),
    }
