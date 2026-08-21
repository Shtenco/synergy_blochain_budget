from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zipfile import ZipFile, is_zipfile


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(root: ET.Element, names: tuple[str, ...]) -> str | None:
    wanted = {n.lower() for n in names}
    for elem in root.iter():
        if _local(elem.tag).lower() in wanted and elem.text and elem.text.strip():
            return elem.text.strip()
    return None


def _nested_text(root: ET.Element, parent_names: tuple[str, ...], child_names: tuple[str, ...]) -> str | None:
    parents = {n.lower() for n in parent_names}
    for elem in root.iter():
        if _local(elem.tag).lower() in parents:
            value = _text(elem, child_names)
            if value:
                return value
    return None


def _money(value: str | None) -> int | None:
    if not value:
        return None
    text = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return int((Decimal(text) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def _dims_common(root: ET.Element) -> dict[str, str]:
    registry_number = _text(root, ("regNum", "registryNum", "registryNumber", "contractRegistryNumber"))
    contract_number = _text(root, ("contractNumber", "contractRegNumber"))
    customer_inn = _nested_text(root, ("customer", "customerInfo", "customerData", "payer"), ("inn", "customerINN", "payerINN"))
    supplier_inn = _nested_text(root, ("supplier", "suppliers", "executor", "vendor", "participant", "payee"), ("inn", "supplierINN", "payeeINN"))
    ikz = _text(root, ("purchaseCode", "ikz", "purchaseIdentificationCode", "identificationCode"))
    kbk = _text(root, ("kbk", "budgetClassificationCode", "budgetCode"))
    dims = {
        "registry_number": registry_number or "",
        "contract_number": contract_number or "",
        "customer_inn": customer_inn or "",
        "supplier_inn": supplier_inn or "",
        "ikz": re.sub(r"\s+", "", ikz or ""),
    }
    if kbk:
        dims["kbk"] = re.sub(r"\s+", "", kbk)
    return dims


def parse_contract_xml(data: bytes, source_name: str, budget_year: int | None = None) -> list[dict]:
    root = ET.fromstring(data)
    root_kind = _local(root.tag).lower()
    if "payment" in root_kind and "contract" not in root_kind:
        return []
    if "contract" not in root_kind and not any("contract" in _local(e.tag).lower() for e in root.iter()):
        return []

    dims = _dims_common(root)
    dims["contract_date"] = _text(root, ("signDate", "contractDate", "conclusionDate")) or ""
    dims["execution_end_date"] = _text(root, ("executionEndDate", "endDate", "completionDate")) or ""
    price = _money(_text(root, ("price", "contractPrice", "contractSum")))

    return [{
        "record_type": "PROCUREMENT_CONTRACT",
        "budget_year": int(budget_year or 0),
        "amount_kopecks": price,
        "currency": "RUB",
        "dimensions": dims,
        "source": {"source_id": "eis_zakupki", "artifact": source_name},
        "visibility": "PUBLIC",
        "schema_version": "sinergy.budget.record/v3",
    }]


def parse_payment_xml(data: bytes, source_name: str, budget_year: int | None = None) -> list[dict]:
    root = ET.fromstring(data)
    root_kind = _local(root.tag).lower()
    if "payment" not in root_kind and "execution" not in root_kind:
        return []
    dims = _dims_common(root)
    dims["payment_id"] = _text(root, ("paymentId", "paymentNumber", "documentNumber", "paymentDocumentNumber")) or ""
    dims["payment_date"] = _text(root, ("paymentDate", "documentDate", "date")) or ""
    amount = _money(_text(root, ("paymentAmount", "paidAmount", "amount", "sum")))
    return [{
        "record_type": "PROCUREMENT_PAYMENT",
        "budget_year": int(budget_year or 0),
        "amount_kopecks": amount,
        "currency": "RUB",
        "dimensions": dims,
        "source": {"source_id": "eis_zakupki", "artifact": source_name},
        "visibility": "PUBLIC",
        "schema_version": "sinergy.budget.record/v3",
    }]


def parse_eis_xml(data: bytes, source_name: str, budget_year: int | None = None) -> list[dict]:
    root = ET.fromstring(data)
    kind = _local(root.tag).lower()
    if "payment" in kind or "execution" in kind:
        rows = parse_payment_xml(data, source_name, budget_year)
        if rows:
            return rows
    return parse_contract_xml(data, source_name, budget_year)


def parse_eis_artifact(path: Path, budget_year: int | None = None) -> list[dict]:
    data = path.read_bytes()
    if is_zipfile(io.BytesIO(data)):
        out: list[dict] = []
        with ZipFile(io.BytesIO(data)) as zf:
            total = 0
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or name.startswith("/") or "../" in name or name.startswith("../"):
                    continue
                total += int(info.file_size)
                if total > 512 * 1024 * 1024:
                    raise ValueError("EIS archive expands beyond 512 MiB safety limit")
                if name.lower().endswith(".xml"):
                    out.extend(parse_eis_xml(zf.read(info), f"{path.name}!{name}", budget_year))
        return out
    if path.suffix.lower() == ".xml":
        return parse_eis_xml(data, path.name, budget_year)
    return []
