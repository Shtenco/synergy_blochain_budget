from __future__ import annotations
from typing import Any

from .canonical import object_hash
from .proofs import build_record_proof_bundle, verify_record_in_bundle

CONTRACT_ID = "synergy.economy.budget-proof/v1"
AUTHORITY = "public_budget_provenance"


def budget_proof_payload(
    *,
    dataset_id: str,
    snapshot_id: str,
    records: list[dict[str, Any]],
    as_of: str,
) -> dict[str, Any]:
    if not dataset_id.strip() or not snapshot_id.strip():
        raise ValueError("dataset_id and snapshot_id are required")
    if not records:
        raise ValueError("records required")
    bundle = build_record_proof_bundle(records)
    for record, proof in zip(sorted(records, key=object_hash), bundle["proofs"]):
        if not verify_record_in_bundle(record, proof, bundle["record_merkle_root"]):
            raise ValueError("record proof self-check failed")
    return {
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "as_of": as_of,
        "record_merkle_root": bundle["record_merkle_root"],
        "record_count": bundle["record_count"],
        "proof_bundle_schema": bundle["schema_version"],
        "canonical_accounting_authority": False,
    }
