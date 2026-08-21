from __future__ import annotations

import hashlib
import json


def _id(kind: str, value: object) -> str:
    raw = json.dumps([kind, value], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return f"{kind}:{hashlib.sha256(raw).hexdigest()[:24]}"


def build_flow_graph(records: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str, str], dict] = {}

    def node(kind: str, key: object, **attrs) -> str:
        nid = _id(kind, key)
        nodes.setdefault(nid, {"id": nid, "kind": kind, "key": key, **attrs})
        return nid

    def edge(src: str, dst: str, kind: str, **attrs) -> None:
        ekey = (src, dst, kind)
        current = edges.setdefault(ekey, {"from": src, "to": dst, "kind": kind, "amount_kopecks": 0})
        if attrs.get("amount_kopecks") is not None:
            current["amount_kopecks"] += int(attrs["amount_kopecks"])

    for r in records:
        year = int(r.get("budget_year", 0))
        dims = r.get("dimensions") or {}
        amount = int(r.get("amount_kopecks") or 0)
        year_id = node("BUDGET_YEAR", year)
        grbs = dims.get("grbs")
        line_key = [year] + [dims.get(k, "") for k in ("kbk", "section", "subsection", "target_article", "expense_type")]
        line_id = node("BUDGET_LINE", line_key, kbk=dims.get("kbk", ""))
        if grbs:
            grbs_id = node("GRBS", grbs)
            edge(year_id, grbs_id, "APPROPRIATES")
            edge(grbs_id, line_id, "CLASSIFIES", amount_kopecks=amount if r.get("record_type") in {"FEDERAL_BUDGET_APPROPRIATION", "FEDERAL_BUDGET_LIMIT"} else 0)
        else:
            edge(year_id, line_id, "CONTAINS")

        contract = dims.get("contract_number") or dims.get("registry_number")
        supplier = dims.get("supplier_inn")
        payment = dims.get("payment_id")
        if contract:
            contract_id = node("CONTRACT", contract)
            edge(line_id, contract_id, "FUNDS", amount_kopecks=amount if "CONTRACT" in str(r.get("record_type")) else 0)
            if supplier:
                supplier_id = node("RECIPIENT", supplier)
                edge(contract_id, supplier_id, "AWARDED_TO")
            if payment:
                payment_id = node("PAYMENT", payment)
                edge(contract_id, payment_id, "SETTLED_BY", amount_kopecks=amount)

    return {
        "schema_version": "sinergy.budget.flow-graph/v1",
        "nodes": sorted(nodes.values(), key=lambda x: x["id"]),
        "edges": sorted(edges.values(), key=lambda x: (x["from"], x["to"], x["kind"])),
    }
