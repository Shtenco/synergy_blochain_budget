from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from .models import Artifact

FILE_EXTENSIONS = {".csv", ".json", ".xml", ".xls", ".xlsx", ".zip", ".pdf", ".txt", ".ods"}
USER_AGENT = "SINERGY-Budget-Ledger/0.1 (+public-data-archiver)"


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def _safe_name(url: str, fallback: str) -> str:
    path = urllib.parse.urlsplit(url).path
    name = Path(urllib.parse.unquote(path)).name or fallback
    name = re.sub(r"[^0-9A-Za-zА-Яа-я._()-]+", "_", name).strip("._")
    return name[:180] or fallback


def _allowed(url: str, allowed_domains: set[str]) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in allowed_domains or any(host.endswith("." + d) for d in allowed_domains)


def fetch_bytes(url: str, timeout: int = 45) -> tuple[bytes, str, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        return data, r.geturl(), r.headers.get("Content-Type")


def discover_files(page_url: str, allowed_domains: set[str], timeout: int = 45) -> list[str]:
    data, final_url, _ = fetch_bytes(page_url, timeout=timeout)
    parser = _Links()
    parser.feed(data.decode("utf-8", errors="replace"))
    out: set[str] = set()
    for href in parser.hrefs:
        url = urllib.parse.urljoin(final_url, href)
        if not _allowed(url, allowed_domains):
            continue
        ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
        if ext in FILE_EXTENSIONS:
            out.add(url)
    return sorted(out)


def collect_source(source: dict, output_dir: Path, max_files: int | None = None) -> list[Artifact]:
    source_id = source["id"]
    allowed = set(source.get("allowed_domains") or [])
    if not allowed:
        allowed.add((urllib.parse.urlsplit(source["url"]).hostname or "").lower())
    urls: list[str] = []
    mode = source.get("fetch_mode", "html_discovery")
    if mode == "html_discovery":
        urls.extend(discover_files(source["url"], allowed))
    elif mode == "html_snapshot":
        urls.append(source["url"])
    elif mode in {"catalog_only", "external_api_pending"}:
        return []
    else:
        raise ValueError(f"unknown fetch_mode={mode!r} for {source_id}")
    urls.extend(source.get("extra_urls") or [])
    urls = list(dict.fromkeys(urls))
    if max_files is not None:
        urls = urls[:max_files]
    retrieved_at = datetime.now(timezone.utc).isoformat()
    artifacts: list[Artifact] = []
    target = output_dir / source_id
    target.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(urls, 1):
        data, final_url, content_type = fetch_bytes(url)
        digest = hashlib.sha256(data).hexdigest()
        ext = Path(urllib.parse.urlsplit(final_url).path).suffix
        name = _safe_name(final_url, f"artifact-{index}{ext}")
        stored = target / f"{digest[:16]}--{name}"
        stored.write_bytes(data)
        artifacts.append(Artifact(source_id, url, final_url, digest, len(data), content_type or mimetypes.guess_type(name)[0], retrieved_at, stored.as_posix()))
    return artifacts


def load_catalog(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def write_manifest(path: Path, artifacts: list[Artifact], sources: list[dict]) -> None:
    payload = {
        "schema_version": "sinergy.budget.artifact-manifest/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "artifacts": [asdict(a) for a in artifacts],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
