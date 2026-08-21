# Архитектура SINERGY Blockchain Budget

## Цель

Система строит проверяемое публичное зеркало официально опубликованных бюджетных данных России и фиксирует происхождение и криптографическую целостность в домене блокчейна SINERGY.

```text
Официальные источники РФ
        │
        ▼
Source Collectors ──► immutable raw artifacts
        │                    └─ SHA-256 + URL + timestamp + MIME + byte size
        ▼
Normalizer / Budget Ontology
        ▼
Canonical JSON records (amounts = integer kopecks)
        ▼
recordMerkleRoot + artifactMerkleRoot
        ▼
SINERGY:BUDGET anchor / EVM registry
```

## Почему гигантские PDF/ZIP не надо класть целиком в Solidity storage

1. Исходные байты хранятся content-addressed и реплицируются архивными узлами SINERGY.
2. В consensus ledger входят криптографические commitments, provenance и нормализованные события.
3. Любой узел пересчитывает SHA-256 и Merkle root и проверяет историю.
4. Для собственной L1 можно добавить BudgetBlob/chunk storage + erasure coding/data availability без изменения модели записей.

## Онтология

`BudgetLaw`, `Revenue`, `Appropriation`, `Limit`, `Obligation`, `CashExecution`, `Debt`, `Financing`, `Transfer`, `Programme`, `Procurement`, `Contract`, `Institution`, `Classifier`, `SourceArtifact`.

Ключ записи: `record_type`, `budget_year`, `amount_kopecks`, `currency`, `dimensions`, `source`, `visibility`, `record_id`.

Версии не перезаписываются. Исправление создает новую запись/snapshot, старый остается доказуемым.

## Секретные приложения

Публичный текст 426-ФЗ ссылается на приложения с грифами «секретно» и «совершенно секретно». Их содержимое не является публичным входом системы. Реестр создает только `RESTRICTED_REFERENCE`. Никаких попыток обхода ограничений, реконструкции или догадок.

## Trust model

1. Origin authenticity — официальный домен + URL provenance.
2. Byte integrity — SHA-256 каждого файла.
3. Dataset integrity — deterministic record/artifact Merkle roots.
4. History integrity — append-only hash-chain + on-chain anchor.

## Production roadmap

- signed ingest manifests;
- 3+ independent publishers/validators and quorum anchoring;
- replicated IPFS/S3/MinIO content-addressed raw store;
- PostgreSQL/ClickHouse read index;
- ZIP/XLS/XLSX/XML parsers;
- КБК ontology + classifier history;
- reconciliation-инварианты;
- alerting при ретроспективном изменении файла по тому же URL.
