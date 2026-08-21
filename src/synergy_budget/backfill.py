from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .source_crawler import discover_files, fetch_bytes

_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


@dataclass(frozen=True)
class HistoricalArtifact:
    source_id: str
    requested_year: int
    report_year: int | None
    year_evidence: str
    url: str
    final_url: str
    sha256: str
    byte_size: int
    retrieved_at: str
    relative_path: str


def build_year_url(source: dict, year: int) -> str:
    template = source.get("archive_url_template")
    if template:
        return template.format(year=year)
    base = source["url"]
    parts = urllib.parse.urlsplit(base)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query[source.get("archive_year_param", "filter_year")] = str(year)
    for key, value in (source.get("archive_fixed_params") or {}).items():
        query[str(key)] = str(value)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))


def infer_report_year(requested_year: int, *texts: str) -> tuple[int | None, str]:
    years: set[int] = set()
    for text in texts:
        years.update(int(x) for x in _YEAR_RE.findall(text or ""))
    if requested_year in years:
        return requested_year, "url_or_filename"
    if len(years) == 1:
        return next(iter(years)), "url_or_filename_override"
    return None, "unverified"


def collect_history(source: dict, years: range, output_dir: Path, max_files_per_year: int | None = None) -> list[HistoricalArtifact]:
    source_id = source["id"]
    allowed = set(source.get("allowed_domains") or [])
    if not allowed:
        allowed.add((urllib.parse.urlsplit(source["url"]).hostname or "").lower())
    out: list[HistoricalArtifact] = []
    seen: set[str] = set()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    for requested_year in years:
        page = build_year_url(source, requested_year)
        urls = discover_files(page, allowed)
        if max_files_per_year is not None:
            urls = urls[:max_files_per_year]
        for idx, url in enumerate(urls, 1):
            data, final_url, _ = fetch_bytes(url)
            digest = hashlib.sha256(data).hexdigest()
            identity = f"{digest}:{final_url}"
            if identity in seen:
                continue
            seen.add(identity)
            name = Path(urllib.parse.urlsplit(final_url).path).name or f"artifact-{idx}"
            report_year, evidence = infer_report_year(requested_year, url, final_url, name)
            bucket = str(report_year) if report_year else f"unverified-{requested_year}"
            target = output_dir / source_id / bucket
            target.mkdir(parents=True, exist_ok=True)
            stored = target / f"{digest[:16]}--{name}"
            stored.write_bytes(data)
            out.append(HistoricalArtifact(source_id, requested_year, report_year, evidence, url, final_url, digest, len(data), retrieved_at, stored.as_posix()))
    return out


def write_history_manifest(path: Path, artifacts: list[HistoricalArtifact], source: dict, years: range) -> None:
    payload = {
        "schema_version": "sinergy.budget.history-manifest/v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "requested_years": [years.start, years.stop - 1],
        "safety": "report_year is null unless supported by URL/filename evidence; do not normalize unverified artifacts under a guessed year",
        "artifacts": [asdict(a) for a in artifacts],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
