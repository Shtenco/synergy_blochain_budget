# SINERGY Blockchain Budget V0.5 — MOCK Corpus Lab

V0.5 adds a deterministic **synthetic public-budget universe** for end-to-end testing when real federal datasets are unavailable, rate-limited, too large, or not yet downloaded.

## Safety boundary

Every generated record is marked:

```text
source.mock = true
source.notice = SINERGY_BUDGET_MOCK_ONLY_DO_NOT_ANCHOR_AS_REAL
```

The corpus root contains:

```text
MOCK_ONLY
```

No production anchor or production ledger is created. `assert_mock_only()` rejects a mixed real/mock corpus.

The generator never fabricates secret annex contents. It creates only a metadata-only `CLASSIFIED_ANNEX_REFERENCE`.

## Public logical corpora simulated

For every year in the configured range the generator emits synthetic analogues of:

1. federal budget law and legal parameters;
2. Federal Treasury federal-budget execution;
3. consolidated budget execution;
4. state extra-budgetary funds;
5. federal institution financial statements;
6. government finance statistics;
7. Treasury open-data catalog records;
8. Electronic Budget programmes, transfers, debt and financing;
9. EIS contracts;
10. EIS payments/execution;
11. year/revision KBK registry;
12. public KBK legal-publication metadata;
13. public budget exchange schemas;
14. bus.gov-like institution/state-assignment corpus.

The goal is structural coverage, not imitation of confidential or real personal/business data.

## Ground-truth status profile

Default demo profile uses 100 contracts per year:

```text
TRACEABLE                 65%
TRACEABLE_TO_CONTRACT     15%
AMBIGUOUS                  5%
UNRESOLVED_KBK            10%
NO_BUDGET_LINE             5%
```

The trace engine does **not** receive these percentages directly. It receives generated source records and must rediscover the statuses.

This gives a deterministic benchmark for:

```text
TraceableContracts
TraceableRUB
AmbiguityRate
UnresolvedKBKRate
PublicProofCoverage
FederalCashTraceability
```

Contract-value coverage is intentionally different from contract-count coverage because contract amounts are heterogeneous.

## Generate

```bash
synergy-budget-mock generate \
  --profile demo \
  --from-year 2013 \
  --to-year 2026 \
  --output data/mock/v0.5 \
  --overwrite
```

Profiles:

```text
demo       100 contracts/year
standard  1000 contracts/year
large    10000 contracts/year
stress  100000 contracts/year
```

You can override the scale:

```bash
synergy-budget-mock generate \
  --contracts-per-year 25000 \
  --kbk-per-year 512 \
  --institutions-per-year 3000 \
  --seed 20260821 \
  --output /srv/sinergy/mock-budget
```

## Output

```text
data/mock/v0.5/
├── MOCK_ONLY
├── manifest.json
├── ground_truth/
│   └── ground_truth.json
├── canonical/
│   ├── all_records.jsonl
│   ├── pravo_budget_law/
│   ├── treasury_federal_budget/
│   ├── treasury_consolidated_budget/
│   ├── treasury_extra_budgetary_funds/
│   ├── treasury_federal_institutions/
│   ├── treasury_government_finance_statistics/
│   ├── treasury_open_data/
│   ├── electronic_budget_portal/
│   ├── eis_procurement/
│   ├── kbk_legal_publications/
│   ├── treasury_electronic_budget_exchange_formats/
│   └── bus_gov_institutions/
├── kbk_registry/
│   └── YYYY/
│       ├── base.jsonl
│       └── midyear.jsonl
├── raw/
│   ├── treasury_federal_budget/YYYY/federal-budget-YYYY.zip
│   ├── eis_procurement/YYYY/eis-YYYY.zip
│   └── kbk/YYYY/kbk-YYYY.csv
├── traces/
│   ├── traces.json
│   └── trace-records.jsonl
└── proofs/
    └── record-proofs.json
```

## Raw parser round-trip

The raw parser-fixture layer is deliberately limited to the formats already consumed by production parsers, while all logical public corpora are emitted canonically. It is compatible with existing parsers:

- Treasury ZIP contains a UTF-8 CSV with Russian headers recognized by `synergy_budget.treasury`;
- EIS ZIP contains contract/payment XML recognized by `synergy_budget.eis`;
- KBK CSV can be imported into the versioned registry.

Thus a test can compare:

```text
generated canonical truth
        vs
RAW → production parser → canonical
```

## Determinism

Given the same:

```text
seed
years
contracts_per_year
kbk_per_year
institutions_per_year
status profile
```

the generator produces the same canonical records, trace commitments and Merkle root.

This makes regression testing meaningful across releases.

## Validation

```bash
synergy-budget-mock validate --root data/mock/v0.5
```

Validation:

1. checks the root MOCK marker;
2. rejects any record missing the hard mock marker;
3. rebuilds V0.3 traces;
4. resolves the year-specific KBK registry;
5. rebuilds trace commitments;
6. rebuilds Merkle proofs;
7. recomputes V0.4 coverage metrics;
8. compares the result with `ground_truth/ground_truth.json`.

The command exits non-zero if the reconstructed result differs.

## Why the money percentages are not forced

The default profile has exactly 65% traceable contracts, but `traceable_rub_pct` is not forced to 65%.

Each contract has a different deterministic amount. Therefore:

```text
count coverage != value coverage
```

This is intentional.

`federal_cash_traceability_pct` is different again because its denominator is generated federal cash execution, including non-procurement cash.

## Scaling

The generator writes JSONL incrementally for corpus files and raw EIS data as ZIP members, but the current V0.5 trace build still materializes the generated canonical corpus in memory before trace construction.

For millions of contracts the intended next optimization is:

```text
MOCK generator
  → SQLite/WAL warehouse
  → partitioned trace batches
  → external-sort Merkle forest
```

The `stress` profile is therefore intended for a sufficiently large machine and for profiling the next streaming trace layer.

## Rule

Mock data is for:

- parser tests;
- trace-engine tests;
- reconciliation tests;
- benchmark/load tests;
- UI/Explorer development;
- metric validation;
- blockchain proof demos.

It must never be presented as real federal-budget data.
