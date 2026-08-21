from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from .canonical import object_hash


@dataclass(frozen=True)
class AnchorEnvelope:
    domain: str
    dataset_id: str
    snapshot_id: str
    record_merkle_root: str
    artifact_merkle_root: str
    manifest_hash: str
    as_of: str
    uri: str
    schema_version: str = "sinergy.budget.anchor/v1"

    def payload(self) -> dict:
        value = asdict(self)
        value["envelope_hash"] = object_hash(value)
        return value


def build_anchor(snapshot: dict, manifest_hash: str, uri: str, dataset_id: str = "RU-FEDERAL-BUDGET") -> dict:
    env = AnchorEnvelope(
        domain="SINERGY:BUDGET",
        dataset_id=dataset_id,
        snapshot_id=snapshot["snapshot_id"],
        record_merkle_root=snapshot["record_merkle_root"],
        artifact_merkle_root=snapshot["artifact_merkle_root"],
        manifest_hash=manifest_hash,
        as_of=snapshot.get("as_of") or datetime.now(timezone.utc).isoformat(),
        uri=uri,
    )
    return env.payload()
