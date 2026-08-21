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


def parse_contract_xml(data: bytes, source_name: str, budget_year: int | None = None) -> list[dict]:
    root = ET.fromstring(data)
    if "contract" not in _local(root.tag).lower() and not any("contract" in _local(e.tag).lower() for e in root.iter()):
        return []

    registry_number = _text(root, ("regNum", "registryNum", "registryNumber"))
    contract_number = _text(root, ("contractNumber", "contractRegNumber")) or registry_number
    customer_inn = _nested_text(root, ("customer", "customerInfo", "customerData"), ("inn", "customerINN"))
    supplier_inn = _nested_text(root, ("supplier", "suppliers", "executor", "vendor", "participant"), ("inn", "supplierINN"))
    price = _money(_text(root, ("price", "contractPrice", "contractSum")))
    kbk = _text(root, ("kbk", "budgetClassificationCode", "budgetCode"))

    dims = {
        "registry_number": registry_number or "",
        "contract_number": contract_number or "",
        "customer_inn": customer_inn or "",
        "supplier_inn": supplier_inn or "",
    }
    if kbk:
        dims["kbk"] = re.sub(r"\s+", "", kbk)

    return [{
        "record_type": "PROCUREMENT_CONTRACT",
        "budget_year": int(budget_year or 0),
        "amount_kopecks": price,
        "currency": "RUB",
        "dimensions": dims,
        "source": {"source_id": "eis_zakupki", "artifact": source_name},
        "visibility": "PUBLIC",
        "schema_version": "sinergy.budget.record/v2",
    }]


def parse_eis_artifact(path: Path, budget_year: int | None = None) -> list[dict]:
    data = path.read_bytes()
    if is_zipfile(io.BytesIO(data)):
        out: list[dict] = []
        with ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or name.startswith("/") or "../" in name or name.startswith("../"):
                    continue
                if name.lower().endswith(".xml"):
                    out.extend(parse_contract_xml(zf.read(info), f"{path.name}!{name}", budget_year))
        return out
    if path.suffix.lower() == ".xml":
        return parse_contract_xml(data, path.name, budget_year)
    return []
