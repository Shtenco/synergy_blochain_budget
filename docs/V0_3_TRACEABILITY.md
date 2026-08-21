# V0.3 · Доказательная трассировка бюджетного рубля

## 1. Почему простой JOIN опасен

Одного `КБК + сумма` недостаточно. Один КБК финансирует множество контрактов, контракт может исполняться частями, а одинаковые суммы встречаются повторно. Поэтому V0.3 разделяет:

- **идентификаторы** — реестровый номер, номер контракта, ИКЗ;
- **участников** — ИНН заказчика/поставщика;
- **классификацию** — бюджетный год + КБК;
- **контекст** — период и сумма;
- **решение** — `AUTO_LINKED`, `REVIEW_REQUIRED`, `AMBIGUOUS`, `UNMATCHED`.

Сильный ID даёт право на автоматический link только если другие опубликованные сильные ID ему не противоречат.

## 2. Versioned KBK registry

Registry физически разделён по `budget_year`:

```text
data/kbk_registry/imported/
  2025/
    85n-base.jsonl
    48n.jsonl
  2026/
    70n-base.jsonl
    171n.jsonl
```

Каждая строка содержит:

```text
budget_year
code
name
revision_id
effective_from
source_url
source_sha256
import_artifact_sha256
source_document
entry_id
```

Resolver никогда не смотрит в соседний год. Среди редакций одного года выбирается последняя `effective_from <= as_of`.

## 3. Evidence scoring

Для `contract ↔ payment`:

- бюджетный год совпал — базовое условие;
- реестровый номер — сильный сигнал;
- номер контракта — сильный сигнал;
- ИКЗ — сильный сигнал;
- ИНН заказчика/поставщика — дополнительные сигналы;
- КБК — дополнительный сигнал;
- точное совпадение суммы — дополнительный сигнал;
- близость периода — дополнительный сигнал.

Если совместно присутствующий сильный ID не совпадает, candidate отбрасывается независимо от суммы.

`AUTO_LINKED` требует:

```text
score >= threshold
AND strong_identifier_match = true
AND no_strong_identifier_conflict
AND unique_best_candidate
```

## 4. Trace object

Trace строится вокруг публичного контракта и содержит ссылки на найденные стадии:

```text
LAW
APPROPRIATION
LIMIT
OBLIGATION
MONETARY_OBLIGATION
CONTRACT
SUPPLIER
PAYMENT
CASH_EXECUTION
```

`CASH_EXECUTION` по КБК — агрегатная бюджетная стадия. Она не притворяется доказательством того, что конкретный контракт получил всю кассовую сумму строки.

Trace содержит:

- `trace_id`;
- `evidence_hash`;
- `source_record_root`;
- `source_record_refs`;
- KBK resolution с точной year/revision provenance;
- evidence каждого contract-payment link.

## 5. Двухуровневая криптографическая проверка

### Уровень A: source records → trace

Все canonical records, использованные trace, дают `source_record_root`.

### Уровень B: trace → SINERGY snapshot

Trace конвертируется в `BUDGET_TRACE_COMMITMENT`. Для него строится Merkle inclusion proof в `record_merkle_root` snapshot.

Итого:

```text
SourceArtifact SHA256
      ↓
Canonical record hash
      ↓
source_record_root
      ↓
trace_id / evidence_hash
      ↓
BUDGET_TRACE_COMMITMENT
      ↓ Merkle proof
record_merkle_root
      ↓ on-chain anchor
SINERGY:BUDGET
```

## 6. Что ещё не является доказанным

V0.3 не утверждает причинность там, где государственный публичный контур публикует только агрегат:

- кассовое исполнение КБК ≠ автоматически конкретный платёж конкретному поставщику;
- совпавшая сумма ≠ контрактный платёж;
- современное название ЦСР ≠ историческое название того же символического кода;
- `filter_year` URL ≠ доказательство содержимого файла.

Такие связи остаются `REVIEW_REQUIRED`/`PARTIAL`, пока не появится более сильный публичный идентификатор.
