# SINERGY Blockchain Budget · Федеральный бюджет РФ в проверяемом распределенном реестре

`blochain_budget` — бюджетный домен блокчейна **СИНЕРГИЯ**. Цель проекта — превращать официально опубликованные данные федерального бюджета России в воспроизводимый append-only ledger, где каждая нормализованная запись связана с первичным государственным источником и криптографическим доказательством его целостности.

## Статус: V0.2 Data Engine

V0.1 заложила provenance, Merkle roots, локальную hash-chain и EVM-якорь. V0.2 добавляет реальный слой машинного разбора и сверки:

- ZIP → вложенные XLS/XLSX/CSV/TXT;
- XLSX через `openpyxl`, legacy XLS через `xlrd`;
- защита от path traversal/zip-bomb по количеству и суммарному размеру элементов;
- денежные величины через `Decimal` → целые копейки, без `float`;
- разбор 20-значного КБК расходов: `ГРБС / Рз / Пр / ЦСР / ВР`;
- автоматическое формирование records ассигнований, ЛБО, обязательств и кассового исполнения;
- исторический backfill по годам с fail-closed проверкой атрибуции года;
- reconciliation по полному КБК;
- XML/ZIP normalizer публичных выгрузок реестра контрактов ЕИС;
- граф `год → ГРБС → бюджетная строка → контракт → получатель → платеж`;
- возможность включать нормализованный JSONL прямо в Merkle snapshot СИНЕРГИИ.

## Базовые параметры бюджета 2026

Seed V0.1 сохраняется без изменений и содержит основные публичные параметры Федерального закона от 28.11.2025 № 426-ФЗ:

- доходы: **40 283 269 170 500 ₽**;
- расходы: **44 069 704 164 500 ₽**;
- дефицит: **3 786 434 994 000 ₽**;
- прогноз ВВП: **235 067 млрд ₽**;
- верхний предел внутреннего госдолга на 01.01.2027: **37 436 192 859 500 ₽**.

## Установка

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\\Scripts\\activate
pip install -e '.[dev]'
pytest -q
```

## 1. Текущий сбор официальных артефактов

```bash
synergy-budget collect
```

Результат:

```text
data/raw/<source-id>/<sha-prefix>--<original-name>
data/manifests/latest.json
```

Raw-объекты не должны тихо перезаписываться. Идентичность файла задается SHA-256.

## 2. Исторический backfill Казначейства

```bash
synergy-budget backfill \\
  --source treasury-federal-budget \\
  --from-year 2013 \\
  --to-year 2026
```

Критическое правило V0.2: запрошенный `filter_year=2018` **не считается доказательством**, что сервер реально вернул данные 2018 года. `report_year` фиксируется только при наличии подтверждения в URL/имени файла; иначе артефакт попадает в `unverified-<year>` и автоматически не маркируется guessed-year.

## 3. Нормализация ZIP/XLS/XLSX Казначейства

```bash
synergy-budget normalize data/raw/report.zip \\
  --year 2026 \\
  --source treasury-federal-budget \\
  --output data/normalized/treasury-2026.jsonl
```

Каждая запись содержит:

```text
record_type
budget_year
amount_kopecks
currency
dimensions:
  kbk
  grbs
  section
  subsection
  target_article
  expense_type
  program_article
  expense_direction
source:
  source_id
  artifact
  artifact_sha256
  sheet
  row
  amount_column
```

## 4. Онтология КБК расходов

Код расходов содержит двадцать знаков:

```text
1–3    ГРБС
4–5    Раздел
6–7    Подраздел
8–17   Целевая статья
18–20  Вид расходов
```

ЦСР дополнительно декомпозируется на программную/непрограммную статью (5 знаков) и направление расходов (5 знаков). Поддерживаются буквенно-цифровые символы, применяемые в целевых статьях федерального бюджета.

## 5. Reconciliation

```bash
synergy-budget reconcile \\
  --input data/normalized/treasury-2026.jsonl \\
  --output data/reconciliation/federal-2026.json
```

По каждой бюджетной строке отдельно считаются:

- ассигнования;
- лимиты бюджетных обязательств;
- бюджетные/денежные обязательства;
- кассовое исполнение;
- отклонение;
- исполнение в basis points;
- статус сверки.

Контрольный план = **ЛБО, если опубликованы; иначе ассигнования**. Ассигнования и ЛБО никогда не суммируются как будто это два независимых источника денег.

## 6. ЕИС закупок

Транспорт получения данных отделен от normalizer. Если публичная выгрузка ЕИС уже скачана как XML/ZIP:

```bash
synergy-budget eis contracts.zip \\
  --year 2026 \\
  --output data/normalized/eis-contracts-2026.jsonl
```

Normalizer извлекает, когда поля присутствуют в публичном XML:

- реестровый номер;
- номер контракта;
- ИНН заказчика;
- ИНН поставщика;
- цену;
- КБК.

Это дает следующий мост:

```text
КБК Казначейства
      │
      ▼
БЮДЖЕТНАЯ СТРОКА
      │
      ▼
КОНТРАКТ ЕИС
      │
      ▼
ПОСТАВЩИК / ПОЛУЧАТЕЛЬ
      │
      ▼
ПЛАТЕЖ / КАССОВОЕ ИСПОЛНЕНИЕ
```

## 7. Граф движения бюджетного рубля

```bash
synergy-budget graph \\
  --input data/normalized/treasury-2026.jsonl \\
  --output data/graph/budget-flow-2026.json
```

Типы узлов: `BUDGET_YEAR`, `GRBS`, `BUDGET_LINE`, `CONTRACT`, `RECIPIENT`, `PAYMENT`.

Основные связи: `APPROPRIATES`, `CLASSIFIES`, `FUNDS`, `AWARDED_TO`, `SETTLED_BY`.

## 8. Merkle snapshot и SINERGY:BUDGET

Нормализованные записи можно включить в тот же snapshot, что и seed закона:

```bash
synergy-budget snapshot \\
  --records data/normalized/treasury-2026.jsonl \\
  --as-of 2026-08-21T00:00:00+00:00
```

Создаются `recordMerkleRoot`, `artifactMerkleRoot`, snapshot ID и anchor envelope. Контракт `contracts/SynergyBudgetAnchorRegistry.sol` хранит последовательные публичные anchors для EVM-совместимого слоя СИНЕРГИИ.

## Архитектура хранения

```text
Официальный источник
       │
       ▼
RAW / Data Availability nodes
       │  SHA-256
       ▼
Normalizer
       │
       ▼
Canonical budget records
       │
       ├── Reconciliation
       ├── Budget Flow Graph
       └── Merkle Forest
                 │
                 ▼
           SINERGY:BUDGET
```

Большие PDF/ZIP/XLS не надо складывать целиком в Solidity storage. Полные байты реплицируются content-addressed archive nodes; consensus layer хранит commitments, provenance и нормализованные события.

## Официальные источники

Каталог `config/official_sources.json` включает:

- `publication.pravo.gov.ru` — федеральный закон и публичные приложения;
- `roskazna.gov.ru` — федеральный бюджет, консолидированный бюджет, внебюджетные фонды, государственная финансовая статистика и открытые данные;
- форматы информационного взаимодействия ГИИС «Электронный бюджет»;
- `budget.gov.ru` — отдельный будущий API-adapter;
- `zakupki.gov.ru` — контракты/закупки;
- `bus.gov.ru` — учреждения.

## Граница публичности

Проект обрабатывает только официально опубликованный публичный контур. Секретные/совершенно секретные приложения не извлекаются и не реконструируются. Для них допускается только `RESTRICTED_REFERENCE` — юридический факт существования без содержания.

## Следующий строгий этап

V0.3 должен закрыть уже не парсинг, а **сопоставление**:

1. загрузить реальный исторический корпус Казначейства на networked data-node;
2. построить versioned справочник ГРБС/КБК/ЦСР по годам;
3. сопоставить ЕИС ↔ Казначейство по КБК + заказчику + периоду + сумме;
4. подключить публичные идентификаторы казначейских платежей там, где они официально доступны;
5. выдавать Merkle proof от конкретного контракта/платежа до snapshot root;
6. добавить независимые validator manifests и quorum anchoring.

Подробности V0.2: [`docs/V0_2_DATA_ENGINE.md`](docs/V0_2_DATA_ENGINE.md).
