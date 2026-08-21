from __future__ import annotations

import hashlib
from collections.abc import Iterable

ZERO_ROOT = "0" * 64


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_hash(payload: bytes) -> bytes:
    return _h(b"\x00" + payload)


def branch_hash(left: bytes, right: bytes) -> bytes:
    return _h(b"\x01" + left + right)


def merkle_root(payloads: Iterable[bytes]) -> str:
    level = [leaf_hash(p) for p in payloads]
    if not level:
        return ZERO_ROOT
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [branch_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()
