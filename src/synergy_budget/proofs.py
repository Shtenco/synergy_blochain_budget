from __future__ import annotations
from .canonical import canonical_json_bytes, object_hash
from .merkle import merkle_proof, merkle_root, verify_merkle_proof

def build_record_proof_bundle(records: list[dict]) -> dict:
    ordered=sorted(records,key=object_hash)
    payloads=[canonical_json_bytes(r) for r in ordered]
    root=merkle_root(payloads)
    proofs=[]
    for i,r in enumerate(ordered):
        proofs.append({"record_id":r.get("record_id") or object_hash(r),"record_hash":object_hash(r),"leaf_index":i,"proof":merkle_proof(payloads,i)})
    return {"schema_version":"sinergy.budget.record-proof-bundle/v1","record_merkle_root":root,"record_count":len(ordered),"proofs":proofs}

def verify_record_in_bundle(record: dict, proof_entry: dict, root: str) -> bool:
    return object_hash(record)==proof_entry.get("record_hash") and verify_merkle_proof(canonical_json_bytes(record),proof_entry.get("proof") or [],root)
