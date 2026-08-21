from __future__ import annotations

import argparse
import json
from pathlib import Path

from .canonical import object_hash
from .chain import build_anchor
from .ledger import append_block, build_snapshot, verify_chain
from .seed import load_seed
from .source_crawler import collect_source, load_catalog, write_manifest


def _read_manifest(path: Path) -> tuple[list[dict], dict]:
    if not path.exists():
        return [], {"artifacts": []}
    payload = json.loads(path.read_text("utf-8"))
    return payload.get("artifacts", []), payload


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


def cmd_snapshot(args) -> None:
    records = load_seed(Path(args.seed))
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
    c = sub.add_parser("collect")
    c.add_argument("--catalog", default="config/official_sources.json")
    c.add_argument("--output", default="data/raw")
    c.add_argument("--manifest", default="data/manifests/latest.json")
    c.add_argument("--max-files", type=int, default=None)
    c.add_argument("--strict", action="store_true")
    c.set_defaults(func=cmd_collect)
    s = sub.add_parser("snapshot")
    s.add_argument("--seed", default="data/seed/federal_budget_2026_core.json")
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
