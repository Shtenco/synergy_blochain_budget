from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mock_corpus import MockCorpusConfig, generate_mock_corpus, validate_mock_corpus

PROFILES = {
    "demo": {"contracts_per_year": 100, "kbk_per_year": 24, "institutions_per_year": 24},
    "standard": {"contracts_per_year": 1_000, "kbk_per_year": 64, "institutions_per_year": 120},
    "large": {"contracts_per_year": 10_000, "kbk_per_year": 256, "institutions_per_year": 1_000},
    "stress": {"contracts_per_year": 100_000, "kbk_per_year": 1_024, "institutions_per_year": 10_000},
}

def _config(args) -> MockCorpusConfig:
    profile = PROFILES[args.profile]
    return MockCorpusConfig(
        start_year=args.from_year,
        end_year=args.to_year,
        contracts_per_year=args.contracts_per_year or profile["contracts_per_year"],
        kbk_per_year=args.kbk_per_year or profile["kbk_per_year"],
        institutions_per_year=args.institutions_per_year or profile["institutions_per_year"],
        seed=args.seed,
        emit_raw=not args.no_raw,
    )

def cmd_generate(args) -> None:
    manifest = generate_mock_corpus(Path(args.output), _config(args), overwrite=args.overwrite)
    print(json.dumps({
        "output": args.output,
        "record_count": manifest["record_count"],
        "trace_count": manifest["trace_count"],
        "record_merkle_root": manifest["record_merkle_root"],
        "coverage_metrics": manifest["coverage_metrics"],
        "warning": manifest["warning"],
    }, ensure_ascii=False, indent=2, sort_keys=True))

def cmd_validate(args) -> None:
    result = validate_mock_corpus(Path(args.root))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 2)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synergy-budget-mock", description="Deterministic synthetic public-budget corpus for SINERGY end-to-end testing")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="generate all logical public corpora as clearly marked MOCK data")
    g.add_argument("--output", default="data/mock/v0.5")
    g.add_argument("--profile", choices=sorted(PROFILES), default="demo")
    g.add_argument("--from-year", type=int, default=2013)
    g.add_argument("--to-year", type=int, default=2026)
    g.add_argument("--contracts-per-year", type=int)
    g.add_argument("--kbk-per-year", type=int)
    g.add_argument("--institutions-per-year", type=int)
    g.add_argument("--seed", type=int, default=20260821)
    g.add_argument("--no-raw", action="store_true")
    g.add_argument("--overwrite", action="store_true")
    g.set_defaults(func=cmd_generate)
    v = sub.add_parser("validate", help="rebuild traces/proofs/metrics and compare with mock ground truth")
    v.add_argument("--root", default="data/mock/v0.5")
    v.set_defaults(func=cmd_validate)
    return parser

def main() -> None:
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
