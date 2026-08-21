from __future__ import annotations

import argparse
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path

from .archive_node import DownloadResult, append_manifest, download_resumable
from .backfill import infer_report_year
from .coverage import compute_coverage
from .eis import parse_eis_artifact
from .eis_soi import download_nsi, execute_request_plan, load_request_plan
from .treasury import parse_artifact
from .warehouse import connect as warehouse_connect, ingest_jsonl, stats as warehouse_stats

FILE_EXTENSIONS = {".zip", ".xls", ".xlsx", ".csv", ".xml", ".json", ".pdf", ".txt", ".ods"}


class _DiscoveryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.select_name: str | None = None
        self.options: dict[str, list[tuple[str, str]]] = {}
        self._option_value: str | None = None
        self._option_label: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        a = dict(attrs)
        if tag.lower() == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag.lower() == "select":
            self.select_name = a.get("name")
        elif tag.lower() == "option" and self.select_name:
            self._option_value = a.get("value", ""); self._option_label = []

    def handle_data(self, data: str):
        if self._option_value is not None:
            self._option_label.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() == "option" and self.select_name and self._option_value is not None:
            self.options.setdefault(self.select_name, []).append((self._option_value, " ".join(self._option_label).strip()))
            self._option_value = None; self._option_label = []
        elif tag.lower() == "select":
            self.select_name = None


def _fetch_html(url: str, timeout: int = 60) -> tuple[str, str]:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "SINERGY-Budget-ArchiveNode/0.4", "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace"), r.geturl()


def _allowed(url: str, domains: list[str]) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains if d)


def discover_artifact_urls(page_url: str, allowed_domains: list[str], timeout: int = 60) -> list[str]:
    html, final_url = _fetch_html(page_url, timeout)
    parser = _DiscoveryParser(); parser.feed(html)
    out = set()
    for href in parser.links:
        url = urllib.parse.urljoin(final_url, href)
        if _allowed(url, allowed_domains) and Path(urllib.parse.urlsplit(url).path).suffix.lower() in FILE_EXTENSIONS:
            out.add(url)
    return sorted(out)


def discover_filter_contexts(source: dict, years: range) -> list[dict]:
    base = source["url"]
    domains = source.get("allowed_domains") or [urllib.parse.urlsplit(base).hostname]
    html, final_url = _fetch_html(base)
    parser = _DiscoveryParser(); parser.feed(html)
    bulk = source.get("bulk") or {}
    type_param = bulk.get("report_type_param", "filter_type")
    year_param = bulk.get("year_param", source.get("archive_year_param", "filter_year"))
    type_options = [(v, label) for v, label in parser.options.get(type_param, []) if v] or [("", "")]
    out: list[dict] = []
    for year in years:
        for report_type, label in type_options:
            parts = urllib.parse.urlsplit(final_url)
            q = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True)); q[year_param] = str(year)
            if report_type: q[type_param] = report_type
            page = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(q), parts.fragment))
            if _allowed(page, domains):
                out.append({"page_url": page, "requested_year": int(year), "report_type": report_type, "report_type_label": label})
    return sorted(out, key=lambda x: (x["requested_year"], x["report_type"], x["page_url"]))


def discover_filter_pages(source: dict, years: range) -> list[str]:
    return [x["page_url"] for x in discover_filter_contexts(source, years)]


def collect_source_bulk(source: dict, years: range, output_root: Path, workers: int = 4, max_files: int | None = None, failures: list[dict] | None = None) -> list[DownloadResult]:
    domains = source.get("allowed_domains") or [urllib.parse.urlsplit(source["url"]).hostname]
    bulk = source.get("bulk") or {}
    default_filter_discovery = bool(source.get("archive_year_param")) or "/ispolnenie-byudzhetov/" in str(source.get("url") or "")
    discover_filters = bulk.get("discover_filters", default_filter_discovery)
    contexts = discover_filter_contexts(source, years) if discover_filters else [{"page_url": source["url"], "requested_year": None, "report_type": "", "report_type_label": ""}]
    url_contexts: dict[str, list[dict]] = {}
    failures = failures if failures is not None else []
    for ctx in contexts:
        try:
            for url in discover_artifact_urls(ctx["page_url"], domains):
                url_contexts.setdefault(url, []).append(ctx)
        except Exception as exc:
            failures.append({"stage": "discovery", "source_id": source["id"], "page_url": ctx["page_url"], "error_type": type(exc).__name__, "error": str(exc)})
    for extra in source.get("extra_urls") or []:
        if _allowed(extra, domains): url_contexts.setdefault(extra, []).append({"page_url": source["url"], "requested_year": None, "report_type": "extra", "report_type_label": "extra_url"})
    ordered = sorted(url_contexts)
    if max_files is not None: ordered = ordered[:max_files]
    results: list[DownloadResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(download_resumable, url, output_root / source["id"], source["id"], domains, discovery=url_contexts[url]): url for url in ordered}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:
                failures.append({"stage": "download", "source_id": source["id"], "url": futures[fut], "error_type": type(exc).__name__, "error": str(exc)})
    return sorted(results, key=lambda x: (x.source_id, x.final_url, x.sha256))


def _load_json_or_jsonl(path: Path):
    if not path.exists(): return []
    if path.suffix.lower() == ".jsonl": return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]
    return json.loads(path.read_text("utf-8"))


def _write_jsonl(path: Path, rows: list[dict], append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as fh:
        for row in rows: fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def cmd_download(args):
    catalog = json.loads(Path(args.catalog).read_text("utf-8")); wanted = set(args.source or [])
    sources = [s for s in catalog["sources"] if s.get("enabled", True) and (not wanted or s["id"] in wanted) and s.get("fetch_mode") != "external_api_pending"]
    all_results: list[DownloadResult] = []; failures: list[dict] = []
    for source in sources:
        print(f"[{source['id']}] bulk discover/download")
        all_results.extend(collect_source_bulk(source, range(args.from_year, args.to_year + 1), Path(args.output), args.workers, args.max_files, failures))
    manifest = append_manifest(Path(args.manifest), all_results, {"from_year": args.from_year, "to_year": args.to_year, "sources": [s["id"] for s in sources], "failures": len(failures)})
    failure_path = Path(args.failures); failure_path.parent.mkdir(parents=True, exist_ok=True); failure_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    print(json.dumps({"downloaded": len(all_results), "manifest_artifacts": len(manifest["artifacts"]), "failures": len(failures), "manifest": args.manifest, "failure_log": args.failures}, ensure_ascii=False))


def _verified_artifact_year(artifact: dict) -> tuple[int | None, str]:
    requested = sorted({int(c["requested_year"]) for c in artifact.get("discovery") or [] if c.get("requested_year")})
    requested_year = requested[0] if len(requested) == 1 else 0
    return infer_report_year(requested_year, artifact.get("requested_url", ""), artifact.get("final_url", ""), Path(artifact.get("relative_path", "")).name)


def cmd_normalize_treasury(args):
    manifest = json.loads(Path(args.manifest).read_text("utf-8")); by_year: dict[int, list[dict]] = {}; skipped = []
    for artifact in manifest.get("artifacts", []):
        source_id = str(artifact.get("source_id") or "")
        if not source_id.startswith("treasury-"): continue
        year, evidence = _verified_artifact_year(artifact)
        path = Path(artifact.get("relative_path") or "")
        if year is None or not path.exists():
            skipped.append({"source_id": source_id, "path": path.as_posix(), "reason": "YEAR_UNVERIFIED" if year is None else "FILE_MISSING", "year_evidence": evidence}); continue
        try:
            rows = parse_artifact(path, year, source_id, artifact.get("sha256"))
            by_year.setdefault(year, []).extend(rows)
        except Exception as exc:
            skipped.append({"source_id": source_id, "path": path.as_posix(), "reason": type(exc).__name__, "error": str(exc)})
    outputs = {}
    root = Path(args.output)
    for year, rows in sorted(by_year.items()):
        out = root / f"treasury-{year}.jsonl"; _write_jsonl(out, rows); outputs[str(year)] = {"records": len(rows), "path": out.as_posix()}
    report = {"schema_version":"sinergy.budget.bulk-normalize-report/v1","outputs":outputs,"skipped":skipped}
    rp=Path(args.report); rp.parent.mkdir(parents=True, exist_ok=True); rp.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),"utf-8")
    print(json.dumps({"years": outputs, "skipped": len(skipped), "report": args.report}, ensure_ascii=False))


def cmd_normalize_eis(args):
    rows=[]; failures=[]; root=Path(args.input)
    for path in sorted([p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".zip",".xml"}]):
        try: rows.extend(parse_eis_artifact(path,args.year))
        except Exception as exc: failures.append({"path":path.as_posix(),"error_type":type(exc).__name__,"error":str(exc)})
    _write_jsonl(Path(args.output),rows)
    print(json.dumps({"records":len(rows),"failures":len(failures),"output":args.output},ensure_ascii=False))


def cmd_soi(args):
    requests=load_request_plan(Path(args.requests)); results=execute_request_plan(requests,sender=args.sender)
    target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps({"schema_version":"sinergy.budget.eis-soi-run/v1","results":results},ensure_ascii=False,indent=2,sort_keys=True,default=str),"utf-8")
    print(json.dumps({"requests":len(requests),"output":args.output},ensure_ascii=False))


def cmd_soi_nsi(args):
    result=download_nsi(base=args.base,nsicode=args.nsicode,prefix=args.prefix,sender=args.sender)
    print(json.dumps({"base":args.base,"nsicode":args.nsicode,"prefix":args.prefix,"result":result},ensure_ascii=False,default=str))


def cmd_warehouse_load(args):
    paths=[]
    for pattern in args.input:
        p=Path(pattern)
        paths.extend(sorted(p.rglob("*.jsonl")) if p.is_dir() else [p])
    db=warehouse_connect(Path(args.database))
    try: result=ingest_jsonl(db,paths,batch_size=args.batch_size); result["stats"]=warehouse_stats(db)
    finally: db.close()
    print(json.dumps(result,ensure_ascii=False))


def cmd_warehouse_stats(args):
    db=warehouse_connect(Path(args.database))
    try: result=warehouse_stats(db)
    finally: db.close()
    print(json.dumps(result,ensure_ascii=False))


def cmd_metrics(args):
    raw=_load_json_or_jsonl(Path(args.traces)); traces=raw.get("traces",raw) if isinstance(raw,dict) else raw
    records=_load_json_or_jsonl(Path(args.trace_records)) if args.trace_records else []; proof_bundle=_load_json_or_jsonl(Path(args.proof_bundle)) if args.proof_bundle else None
    source_records=[]
    for name in args.source_records or []:
        loaded=_load_json_or_jsonl(Path(name)); source_records.extend(loaded if isinstance(loaded,list) else [])
    metrics=compute_coverage(traces or [],records or [],proof_bundle if isinstance(proof_bundle,dict) else None,source_records)
    target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(metrics,ensure_ascii=False,indent=2,sort_keys=True),"utf-8")
    print(json.dumps(metrics,ensure_ascii=False))


def build_parser():
    p=argparse.ArgumentParser(prog="synergy-budget-bulk",description="Bulk public-budget archive/data node for SINERGY"); sub=p.add_subparsers(dest="cmd",required=True)
    d=sub.add_parser("download",help="discover and resumably download public official budget artifacts"); d.add_argument("--catalog",default="config/official_sources.json"); d.add_argument("--source",action="append",default=[]); d.add_argument("--from-year",type=int,default=2013); d.add_argument("--to-year",type=int,default=2026); d.add_argument("--output",default="data/archive"); d.add_argument("--manifest",default="data/manifests/bulk.json"); d.add_argument("--failures",default="data/manifests/bulk-failures.json"); d.add_argument("--workers",type=int,default=4); d.add_argument("--max-files",type=int); d.set_defaults(func=cmd_download)
    nt=sub.add_parser("normalize-treasury",help="normalize all year-verified Treasury artifacts from a bulk manifest"); nt.add_argument("--manifest",default="data/manifests/bulk.json"); nt.add_argument("--output",default="data/normalized/bulk"); nt.add_argument("--report",default="data/manifests/bulk-normalize.json"); nt.set_defaults(func=cmd_normalize_treasury)
    soi=sub.add_parser("soi",help="execute a registered EIS SOI request plan via dars; credentials remain in dars user config"); soi.add_argument("--requests",default="config/eis_soi_requests.example.json"); soi.add_argument("--sender",default="sinergy-budget"); soi.add_argument("--output",default="data/eis_soi/run.json"); soi.set_defaults(func=cmd_soi)
    nsi=sub.add_parser("soi-nsi",help="download an EIS SOI NSI dictionary using documented getNsiRequest"); nsi.add_argument("--base",default="fz44"); nsi.add_argument("--nsicode",default="nsiDocumentTypes"); nsi.add_argument("--prefix",default="nsi/fz44/nsiDocumentType"); nsi.add_argument("--sender",default="sinergy-budget"); nsi.set_defaults(func=cmd_soi_nsi)
    ne=sub.add_parser("normalize-eis",help="normalize all downloaded EIS XML/ZIP files under a directory"); ne.add_argument("--input",required=True); ne.add_argument("--year",type=int,required=True); ne.add_argument("--output",default="data/normalized/eis.jsonl"); ne.set_defaults(func=cmd_normalize_eis)
    wl=sub.add_parser("warehouse-load",help="stream JSONL into indexed SQLite warehouse for million-record corpora"); wl.add_argument("--input",action="append",required=True); wl.add_argument("--database",default="data/warehouse/budget.sqlite3"); wl.add_argument("--batch-size",type=int,default=5000); wl.set_defaults(func=cmd_warehouse_load)
    ws=sub.add_parser("warehouse-stats",help="show indexed warehouse counts by year/type"); ws.add_argument("--database",default="data/warehouse/budget.sqlite3"); ws.set_defaults(func=cmd_warehouse_stats)
    m=sub.add_parser("metrics",help="calculate traceability/proof coverage metrics"); m.add_argument("--traces",default="data/traces/traces.json"); m.add_argument("--trace-records",default="data/traces/trace-records.jsonl"); m.add_argument("--proof-bundle",default="data/proofs/record-proofs.json"); m.add_argument("--source-records",action="append",default=[],help="one reconciled as-of Treasury/EIS JSONL corpus for FederalCashTraceability"); m.add_argument("--output",default="data/metrics/coverage.json"); m.set_defaults(func=cmd_metrics)
    return p


def main():
    args=build_parser().parse_args(); args.func(args)


if __name__=="__main__": main()
