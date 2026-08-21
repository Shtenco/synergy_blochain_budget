from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .canonical import canonical_json_bytes, object_hash
from .merkle import merkle_root

GENESIS_PREV = "0" * 64


def _sorted_payloads(items: Iterable[dict]) -> list[dict]:
    return sorted(items, key=object_hash)


def build_snapshot(records: list[dict], artifacts: list[dict], as_of: str | None = None) -> dict:
    records = _sorted_payloads(records)
    artifacts = _sorted_payloads(artifacts)
    record_root = merkle_root(canonical_json_bytes(x) for x in records)
    artifact_root = merkle_root(canonical_json_bytes(x) for x in artifacts)
    body = {
        "schema_version": "sinergy.budget.snapshot/v1",
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "artifact_count": len(artifacts),
        "record_merkle_root": record_root,
        "artifact_merkle_root": artifact_root,
    }
    body["snapshot_id"] = object_hash(body)
    return body


def read_blocks(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def append_block(path: Path, snapshot: dict, metadata: dict | None = None) -> dict:
    blocks = read_blocks(path)
    prev = blocks[-1]["block_hash"] if blocks else GENESIS_PREV
    block = {
        "schema_version": "sinergy.budget.block/v1",
        "height": len(blocks),
        "previous_block_hash": prev,
        "snapshot": snapshot,
        "metadata": metadata or {},
    }
    block["block_hash"] = object_hash(block)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(block, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return block


def verify_chain(path: Path) -> tuple[bool, str]:
    blocks = read_blocks(path)
    prev = GENESIS_PREV
    for expected_height, block in enumerate(blocks):
        if block.get("height") != expected_height:
            return False, f"height mismatch at {expected_height}"
        if block.get("previous_block_hash") != prev:
            return False, f"previous hash mismatch at {expected_height}"
        claimed = block.get("block_hash")
        body = dict(block)
        body.pop("block_hash", None)
        actual = object_hash(body)
        if claimed != actual:
            return False, f"block hash mismatch at {expected_height}"
        prev = claimed
    return True, f"ok: {len(blocks)} blocks"
