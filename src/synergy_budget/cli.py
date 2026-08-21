from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .backfill import collect_history, write_history_manifest
from .canonical import object_hash
from .chain import build_anchor
from .eis import parse_eis_artifact
from .graph import build_flow_graph
from .ledger import append_block, build_snapshot, verify_chain
from .reconcile import reconcile
from .seed import load_seed
from .source_crawler import collect_source, load_catalog, write_manifest
from .treasury import parse_artifact


def _read_manifest(path: Path) -> tuple[list[dict], dict]:
    if not path.exists():
        return [], {"artifacts": []}
    payload = json.loads(path.read_text("utf-8"))
    return payload.get("artifacts", []), payload


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _write_jsonl(path: Path, rows: list[dict], append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def cmd_collect(args) -> None:
    catalog = load_catalog(Path(args.catalog))
    enabled = [s for s in catalog["sources"] if s.get("enabled", True)]
    all_artifacts = []
    for source in enabled:
        print(f"[{source['id']}] {source['fetch_mode']} {source['url']}")
        try:
            all_artifacts.extend(collect_source(source, Path(args.output), args.max_files))
        except Exception as exc:
            if args.strict:
                raise
            print(f"  WARNING: {type(exc).__name__}: {exc}")
    write_manifest(Path(args.manifest), all_artifacts, enabled)
    print(f"manifest: {args.manifest}; artifacts={len(all_artifacts)}")


def cmd_backfill(args) -> None:
    catalog = load_catalog(Path(args.catalog))
    source = next((s for s in catalog["sources"] if s["id"] == args.source), None)
    if source is None:
        raise SystemExit(f"source not found: {args.source}")
    years = range(args.from_year, args.to_year + 1)
    artifacts = collect_history(source, years, Path(args.output), args.max_files_per_year)
    write_history_manifest(Path(args.manifest), artifacts, source, years)
    verified = sum(a.report_year is not None for a in artifacts)
    print(json.dumps({"artifacts": len(artifacts), "year_verified": verified, "manifest": args.manifest}, ensure_ascii=False))


def cmd_normalize(args) -> None:
    rows: list[dict] = []
    for name in args.files:
        path = Path(name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        parsed = parse_artifact(path, args.year, args.source, digest)
        rows.extend(parsed)
        print(f"[{path}] records={len(parsed)}")
    _write_jsonl(Path(args.output), rows, append=args.append)
    print(json.dumps({"records": len(rows), "output": args.output}, ensure_ascii=False))


def cmd_eis(args) -> None:
    rows: list[dict] = []
    for name in args.files:
        parsed = parse_eis_artifact(Path(name), args.year)
        rows.extend(parsed)
        print(f"[{name}] contracts={len(parsed)}")
    _write_jsonl(Path(args.output), rows, append=args.append)
    print(json.dumps({"contracts": len(rows), "output": args.output}, ensure_ascii=False))


def cmd_reconcile(args) -> None:
    rows = reconcile(_read_jsonl(Path(args.input)), tolerance_kopecks=args.tolerance_kopecks)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(json.dumps({"rows": len(rows), "status": counts, "output": args.output}, ensure_ascii=False))


def cmd_graph(args) -> None:
    graph = build_flow_graph(_read_jsonl(Path(args.input)))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    print(json.dumps({"nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "output": args.output}, ensure_ascii=False))


def cmd_snapshot(args) -> None:
    records = load_seed(Path(args.seed))
    if args.records:
        records.extend(_read_jsonl(Path(args.records)))
    artifacts, manifest = _read_manifest(Path(args.manifest))
    snapshot = build_snapshot(records, artifacts, as_of=args.as_of)
    Path(args.snapshot).parent.mkdir(parents=True, exist_ok=True)
    Path(args.snapshot).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    block = append_block(Path(args.ledger), snapshot, metadata={"manifest_hash": object_hash(manifest)})
    anchor = build_anchor(snapshot, object_hash(manifest), args.uri)
    Path(args.anchor).parent.mkdir(parents=True, exist_ok=True)
    Path(args.anchor).write_text(json.dumps(anchor, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    print(json.dumps({"block_hash": block["block_hash"], "snapshot_id": snapshot["snapshot_id"], "anchor": args.anchor}, ensure_ascii=False))


def cmd_verify(args) -> None:
    ok, message = verify_chain(Path(args.ledger))
    print(message)
    raise SystemExit(0 if ok else 2)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="synergy-budget", description="SINERGY public federal-budget ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="collect current public source artifacts")
    c.add_argument("--catalog", default="config/official_sources.json")
    c.add_argument("--output", default="data/raw")
    c.add_argument("--manifest", default="data/manifests/latest.json")
    c.add_argument("--max-files", type=int, default=None)
    c.add_argument("--strict", action="store_true")
    c.set_defaults(func=cmd_collect)

    b = sub.add_parser("backfill", help="collect historical Treasury artifacts by year")
    b.add_argument("--catalog", default="config/official_sources.json")
    b.add_argument("--source", default="treasury-federal-budget")
    b.add_argument("--from-year", type=int, default=2013)
    b.add_argument("--to-year", type=int, default=2026)
    b.add_argument("--output", default="data/raw-history")
    b.add_argument("--manifest", default="data/manifests/history.json")
    b.add_argument("--max-files-per-year", type=int, default=None)
    b.set_defaults(func=cmd_backfill)

    n = sub.add_parser("normalize", help="normalize Treasury ZIP/XLS/XLSX/CSV into canonical JSONL")
    n.add_argument("files", nargs="+")
    n.add_argument("--year", type=int, required=True)
    n.add_argument("--source", default="treasury-federal-budget")
    n.add_argument("--output", default="data/normalized/treasury.jsonl")
    n.add_argument("--append", action="store_true")
    n.set_defaults(func=cmd_normalize)

    e = sub.add_parser("eis", help="normalize public EIS contract XML/ZIP exports")
    e.add_argument("files", nargs="+")
    e.add_argument("--year", type=int, required=True)
    e.add_argument("--output", default="data/normalized/eis-contracts.jsonl")
    e.add_argument("--append", action="store_true")
    e.set_defaults(func=cmd_eis)

    r = sub.add_parser("reconcile", help="compare appropriations/limits/commitments/cash execution by KBK")
    r.add_argument("--input", default="data/normalized/treasury.jsonl")
    r.add_argument("--output", default="data/reconciliation/federal.json")
    r.add_argument("--tolerance-kopecks", type=int, default=1)
    r.set_defaults(func=cmd_reconcile)

    g = sub.add_parser("graph", help="build budget flow graph")
    g.add_argument("--input", default="data/normalized/treasury.jsonl")
    g.add_argument("--output", default="data/graph/budget-flow.json")
    g.set_defaults(func=cmd_graph)

    s = sub.add_parser("snapshot")
    s.add_argument("--seed", default="data/seed/federal_budget_2026_core.json")
    s.add_argument("--records", default=None, help="optional normalized JSONL to include in the snapshot")
    s.add_argument("--manifest", default="data/manifests/latest.json")
    s.add_argument("--snapshot", default="data/manifests/snapshot.json")
    s.add_argument("--ledger", default="data/ledger/blocks.jsonl")
    s.add_argument("--anchor", default="data/manifests/anchor.json")
    s.add_argument("--uri", default="git+https://github.com/Shtenco/blochain_budget")
    s.add_argument("--as-of", default=None)
    s.set_defaults(func=cmd_snapshot)

    v = sub.add_parser("verify")
    v.add_argument("--ledger", default="data/ledger/blocks.jsonl")
    v.set_defaults(func=cmd_verify)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
