# SINERGY Blockchain Budget V0.4 — Bulk Ingest & Coverage

V0.4 is the first layer designed to move from a prototype-sized corpus to an archive/data node that can ingest the public federal-budget corpus at scale.

## What “download all budget data” means

The node downloads **all public machine-readable artifacts reachable from the configured official sources and the authorization legitimately available to the operator**. It does not try to obtain classified annexes, bypass access controls, or invent unavailable historical detail.

There are two transports:

1. **Federal Treasury / official publication portals** — public HTTP discovery and resumable downloads.
2. **EIS procurement data from 2025 onward** — the official Services for Information and Document Delivery (SOI). EIS registration/personal token is required. The token stays in the user-local `dars` configuration and never enters Git or SINERGY manifests.

## Install

```bash
python -m venv .venv
. .venv/bin/activate               # Windows: .venv\\Scripts\\activate
pip install -e '.[dev,eis]'
```

For EIS SOI, after registering as an open-data recipient in EIS:

```bash
dars config edit
```

## 1. Bulk Treasury archive

The crawler reads the report-type values published by each Treasury page instead of hard-coding `filter_type` IDs. It then enumerates years, discovers artifact links and performs resumable downloads.

```bash
synergy-budget-bulk download \
  --source treasury-federal-budget \
  --source treasury-consolidated-budget \
  --source treasury-extra-budgetary-funds \
  --source treasury-government-finance-statistics \
  --from-year 2013 \
  --to-year 2026 \
  --workers 6
```

Storage:

```text
data/archive/<source-id>/<sha-prefix>--<original-name>
data/manifests/bulk.json
data/manifests/bulk-failures.json
```

Properties:

- HTTP Range resume when supported;
- `.part` recovery;
- redirect/domain allowlist;
- streamed SHA-256;
- `fsync` before publish;
- content-addressed final names;
- ETag / Last-Modified provenance;
- discovery page + requested year + report-type provenance;
- retries with exponential backoff;
- deduplicated atomic manifest;
- failures are recorded instead of silently disappearing.

## 2. Fail-closed mass normalization

A requested filter year is not evidence that the server returned that year's file. V0.4 carries V0.2's rule forward: a file is normalized under a year only if its URL/filename independently contains year evidence.

```bash
synergy-budget-bulk normalize-treasury \
  --manifest data/manifests/bulk.json \
  --output data/normalized/bulk
```

Unverified files remain archived but are listed in `data/manifests/bulk-normalize.json` rather than being assigned a guessed year.

## 3. EIS SOI through Python

The optional adapter uses the current `dars` 2.x module API. It accepts only three documented public SOI methods:

- `getNsiRequest`;
- `getDocsByReestrNumberRequest`;
- `getDocsByOrgRegionRequest`.

Credentials are forbidden inside request-plan JSON.

First download the EIS document-type dictionary:

```bash
synergy-budget-bulk soi-nsi \
  --base fz44 \
  --nsicode nsiDocumentTypes \
  --prefix nsi/fz44/nsiDocumentType
```

Then build a request plan from the official dictionary and execute it:

```bash
cp config/eis_soi_requests.example.json config/eis_soi_requests.local.json
# populate only method + kwargs; NEVER paste token/password into this file
synergy-budget-bulk soi --requests config/eis_soi_requests.local.json
```

Normalize downloaded XML/ZIP files per verified year:

```bash
synergy-budget-bulk normalize-eis \
  --input /path/from/dars/fz44/downloads \
  --year 2026 \
  --output data/normalized/eis-2026.jsonl
```

## 4. Million-record local warehouse

JSONL remains the canonical interchange format, but a multi-year EIS/Treasury corpus needs indexed storage. V0.4 adds a standard-library SQLite warehouse with WAL and indexes for the keys used by V0.3 matching.

```bash
synergy-budget-bulk warehouse-load \
  --input data/normalized/bulk \
  --input data/normalized/eis-2026.jsonl \
  --database data/warehouse/budget.sqlite3

synergy-budget-bulk warehouse-stats
```

Indexes cover year/type, KBK, registry number, contract number, IKZ, customer/supplier INN and payment ID. Loading is streamed in batches; duplicate `record_id` values do not inflate the warehouse.

## 5. KBK revision inventory

`config/kbk_revision_sources.json` is deliberately stricter than a normal reference list:

- each budget year is isolated;
- incomplete historical years are marked `DISCOVERY_REQUIRED` / `PARTIAL_*`;
- a revision is not resolvable merely because its order number is known;
- the official artifact must be archived and hashed, then its rows imported into the corresponding V0.3 year/revision partition;
- pending acts are never applied automatically.

For 2026 the effective base is order 70n; the current effective redaction lists amendments 171n, 14n and 55n. Order 100n dated 2026-07-27 is inventoried as pending registration as of 2026-08-21 and therefore `auto_apply=false`.

## 6. Coverage metrics

```bash
synergy-budget-bulk metrics \
  --traces data/traces/traces.json \
  --trace-records data/traces/trace-records.jsonl \
  --proof-bundle data/proofs/record-proofs.json \
  --source-records data/normalized/treasury-ASOF.jsonl \
  --source-records data/normalized/eis-ASOF.jsonl
```

V0.4 reports:

- `traceable_rub_pct` — **contract-value coverage**, `TRACEABLE contract value / public contract value`;
- `traceable_contracts_pct` — traceable public contracts / all public contracts represented by traces;
- `ambiguity_rate_pct` — contracts with ambiguous payment linkage / public contracts;
- `unresolved_kbk_rate_pct` — unresolved KBK / contracts whose KBK can be evaluated;
- `public_proof_coverage_pct` — cryptographically verified Merkle proofs / trace commitment records;
- `federal_cash_traceability_pct` — proven linked payment value / leaf-KBK federal cash execution for **one reconciled non-overlapping as-of snapshot**.

The final metric is intentionally separate from contract-value coverage. Contract price is not cash execution.

## 7. Full pipeline

```text
Official Treasury pages ────────┐
Official legal publications ────┼─► resumable content-addressed archive
EIS SOI (registered token) ─────┘            │
                                             ▼
                                   year-verified normalization
                                             │
                                             ▼
                                    SQLite / canonical JSONL
                                             │
                           ┌─────────────────┴──────────────────┐
                           ▼                                    ▼
                    versioned KBK registry               V0.3 trace engine
                           │                                    │
                           └──────────────► traces ◄────────────┘
                                                │
                                                ▼
                                      BUDGET_TRACE_COMMITMENT
                                                │
                                                ▼
                                         Merkle proofs
                                                │
                                                ▼
                                         SINERGY:BUDGET
                                                │
                                                ▼
                                      V0.4 coverage metrics
```

## Important limitations

- The code cannot create public data that government sources do not publish.
- Secret/restricted budget annexes are never fetched or reconstructed.
- EIS SOI requires legitimate registration and a personal token.
- A bulk historical crawl must run on a networked node that can resolve/reach the official Russian domains.
- Current ChatGPT execution infrastructure may be unable to resolve those domains directly; that is an environment limitation, not a claim that the official files were downloaded here.
