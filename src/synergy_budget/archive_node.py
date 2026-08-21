from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

USER_AGENT = "SINERGY-Budget-ArchiveNode/0.4 (+public-official-data)"
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class DownloadResult:
    source_id: str
    requested_url: str
    final_url: str
    sha256: str
    byte_size: int
    etag: str | None
    last_modified: str | None
    retrieved_at: str
    relative_path: str
    discovery: list[dict] | None = None
    status: str = "downloaded"

    def payload(self) -> dict:
        return asdict(self)


def _host_allowed(url: str, allowed_domains: Iterable[str]) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    domains = {d.lower().strip(".") for d in allowed_domains if d}
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)


def _safe_filename(url: str, fallback: str = "artifact.bin") -> str:
    raw = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name or fallback
    cleaned = "".join(c if c.isalnum() or c in "._-()" else "_" for c in raw).strip("._")
    return (cleaned or fallback)[:180]


def _sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def download_resumable(
    url: str,
    target_dir: Path,
    source_id: str,
    allowed_domains: Iterable[str],
    *,
    timeout: int = 60,
    retries: int = 4,
    resume: bool = True,
    expected_sha256: str | None = None,
    backoff_seconds: float = 1.0,
    discovery: list[dict] | None = None,
) -> DownloadResult:
    if not _host_allowed(url, allowed_domains):
        raise ValueError(f"refusing download outside allowlist: {url}")
    target_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_filename(url)
    part = target_dir / (name + ".part")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        existing = part.stat().st_size if resume and part.exists() else 0
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                final_url = response.geturl()
                if not _host_allowed(final_url, allowed_domains):
                    raise ValueError(f"redirect escaped allowlist: {final_url}")
                status = getattr(response, "status", 200)
                mode = "ab" if existing and status == 206 else "wb"
                if mode == "wb":
                    existing = 0
                with part.open(mode) as fh:
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        fh.write(chunk)
                    fh.flush()
                    os.fsync(fh.fileno())
                digest, size = _sha256_file(part)
                if expected_sha256 and digest.lower() != expected_sha256.lower():
                    raise ValueError(f"sha256 mismatch for {url}: {digest} != {expected_sha256}")
                final_name = f"{digest[:16]}--{name}"
                final_path = target_dir / final_name
                if final_path.exists():
                    existing_digest, existing_size = _sha256_file(final_path)
                    if existing_digest != digest or existing_size != size:
                        raise ValueError(f"content-address collision: {final_path}")
                    part.unlink(missing_ok=True)
                else:
                    part.replace(final_path)
                return DownloadResult(
                    source_id=source_id,
                    requested_url=url,
                    final_url=final_url,
                    sha256=digest,
                    byte_size=size,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    relative_path=final_path.as_posix(),
                    discovery=discovery,
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and part.exists():
                digest, size = _sha256_file(part)
                if expected_sha256 and digest.lower() != expected_sha256.lower():
                    part.unlink(missing_ok=True)
                else:
                    final_path = target_dir / f"{digest[:16]}--{name}"
                    part.replace(final_path)
                    return DownloadResult(source_id, url, url, digest, size, None, None, datetime.now(timezone.utc).isoformat(), final_path.as_posix(), discovery)
            last_error = exc
        except Exception as exc:
            if isinstance(exc, ValueError) and ("allowlist" in str(exc) or "sha256 mismatch" in str(exc) or "collision" in str(exc)):
                raise
            last_error = exc
        if attempt < retries:
            time.sleep(backoff_seconds * (2**attempt))
    assert last_error is not None
    raise last_error


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": "sinergy.budget.bulk-manifest/v1", "artifacts": []}
    return json.loads(path.read_text("utf-8"))


def append_manifest(path: Path, results: Iterable[DownloadResult], metadata: dict | None = None) -> dict:
    old = load_manifest(path)
    by_identity = {(x.get("sha256"), x.get("final_url")): x for x in old.get("artifacts", [])}
    for result in results:
        payload = result.payload()
        by_identity[(payload["sha256"], payload["final_url"])] = payload
    out = {
        "schema_version": "sinergy.budget.bulk-manifest/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or old.get("metadata", {}),
        "artifacts": sorted(by_identity.values(), key=lambda x: (x.get("source_id", ""), x.get("final_url", ""), x.get("sha256", ""))),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    tmp.replace(path)
    return out
