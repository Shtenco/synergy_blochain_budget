# SINERGY Blockchain Budget — reproducible public-budget provenance

## Original scientific and civic value

The repository tackles a demanding information problem: connect budget classifications, legal appropriations, treasury records, procurement contracts and payments **without pretending that approximate name or amount matches prove an actual transaction link**. Source documents, classification revisions and entity identities matter as much as amounts.

The implementation has a versioned KBK registry, public EIS and Treasury normalizers, trace construction, Merkle commitments, source hashes, bulk ingestion, coverage evaluation and systematic test fixtures. This is a substantial executable data-engineering project, not just an infographic of public finance.

## Evidence-scored contract/payment linkage

[trace.py](../src/synergy_budget/trace.py) compares contract and payment records for the same budget year. It assigns match contributions for registry number (7000), contract number (6000), IKZ (3000), customer/supplier identifiers and KBK (1000 each), equal amount (500), near period (500), with baseline 1000 and cap 10000.

An incompatible **strong identifier rejects** a candidate instead of merely reducing its score. A strong ID and threshold 8000 are both required for automatic linking. Tied top-ranked candidates receive AMBIGUOUS. A matching amount alone cannot generate AUTO_LINKED.

For evidence matches $I_j\in\{0,1\}$ and weights $w_j$, the heuristic score is

$$
S=\min\left(10000,1000+\sum_jw_j I_j\right).
$$

This is an **engineering evidence score, not calibrated probability**. The hard rejection, strong-identifier requirement and tie handling are more important than the scalar score itself.

## Temporal and cryptographic provenance

The KBK registry is partitioned by financial year and revision date. A 2026 classification must not silently reinterpret a 2015 record. Canonical JSON is hashed and sorted to derive a reproducible source-set Merkle root. The trace combines law, appropriations, limits, obligations, contract, supplier, linked payment and cash execution into independently inspectable provenance.

## Scientific evaluation

Measure linking precision and recall on a manually verified sample, stratified by strong ID availability, fiscal year and contract type. Stress the model with common vendor names, same-amount orders, duplicate export rows, KBK revisions and missing documents. Verify Merkle inclusion proof against exact serialized bytes. A meaningful metric is **verified trace coverage**, not number of guessed links.

## Application

Public-spending observatories, investigative data journalism and contract compliance teams can use a transparent provenance chain to separate observed records from inferred relationships. The value is a **falsifiable, tamper-evident trace**, not the unsupported claim that every budget payment is already resolved.

[Trace engine](../src/synergy_budget/trace.py) · [KBK registry](../src/synergy_budget/kbk_registry.py) · [Tests](../tests/test_v03.py)
