import json
from pathlib import Path
from synergy_budget.kbk_registry import VersionedKBKRegistry, import_rows, write_entries
from synergy_budget.trace import score_contract_payment, link_payments, build_traces, traces_as_records
from synergy_budget.proofs import build_record_proof_bundle, verify_record_in_bundle
from synergy_budget.trace_graph import build_trace_graph
from synergy_budget.merkle import merkle_root

KBK="02004112010490019241"

def _r(rt, amount=100000, **dims):
    d={"kbk":KBK,"grbs":"020","section":"04","subsection":"11","target_article":"2010490019","expense_type":"241"}; d.update(dims)
    return {"record_type":rt,"budget_year":2026,"amount_kopecks":amount,"currency":"RUB","dimensions":d,"source":{"source_id":"test"},"visibility":"PUBLIC"}

def test_registry_is_strictly_year_partitioned(tmp_path: Path):
    rows=[{"code":KBK,"name":"Связь"}]
    e25=import_rows(rows,budget_year=2025,revision_id="85n",effective_from="2025-01-01",source_url="official://2025")
    e26=import_rows(rows,budget_year=2026,revision_id="70n",effective_from="2026-01-01",source_url="official://2026")
    write_entries(tmp_path,e25+e26)
    reg=VersionedKBKRegistry(tmp_path)
    assert reg.resolve(2025,KBK)["entry"]["revision_id"]=="85n"
    assert reg.resolve(2026,KBK)["entry"]["revision_id"]=="70n"
    assert reg.resolve(2024,KBK)["status"]=="UNRESOLVED"

def test_registry_revision_as_of(tmp_path: Path):
    rows=[{"code":KBK,"name":"old"}]
    a=import_rows(rows,budget_year=2026,revision_id="70n",effective_from="2026-01-01",source_url="x")
    b=import_rows([{"code":KBK,"name":"new"}],budget_year=2026,revision_id="171n",effective_from="2026-01-21",source_url="y")
    write_entries(tmp_path,a+b); reg=VersionedKBKRegistry(tmp_path)
    assert reg.resolve(2026,KBK,"2026-01-10")["entry"]["name"]=="old"
    assert reg.resolve(2026,KBK,"2026-02-01")["entry"]["name"]=="new"

def test_strong_contract_payment_link():
    c=_r("PROCUREMENT_CONTRACT",123456,registry_number="012345",contract_number="A-1",customer_inn="7700000000",supplier_inn="7800000000",ikz="0126X")
    p=_r("PROCUREMENT_PAYMENT",123456,registry_number="012345",payment_id="P-1",customer_inn="7700000000",supplier_inn="7800000000",payment_date="2026-06-01")
    s=score_contract_payment(c,p); assert s["eligible"] and s["strong"] and s["score_bps"]>=8000
    link=link_payments([c],[p])[0]; assert link["status"]=="AUTO_LINKED"

def test_strong_identifier_mismatch_rejects():
    c=_r("PROCUREMENT_CONTRACT",registry_number="111")
    p=_r("PROCUREMENT_PAYMENT",registry_number="222")
    s=score_contract_payment(c,p); assert not s["eligible"]

def test_ambiguous_link_does_not_auto_attach():
    c1=_r("PROCUREMENT_CONTRACT",registry_number="111",contract_number="A")
    c2=_r("PROCUREMENT_CONTRACT",registry_number="111",contract_number="A"); c2["source"]={"source_id":"other"}
    p=_r("PROCUREMENT_PAYMENT",registry_number="111",contract_number="A")
    assert link_payments([c1,c2],[p])[0]["status"]=="AMBIGUOUS"

def test_trace_registry_and_merkle_proof(tmp_path: Path):
    entries=import_rows([{"code":KBK,"name":"Связь"}],budget_year=2026,revision_id="70n",effective_from="2026-01-01",source_url="official")
    write_entries(tmp_path,entries); reg=VersionedKBKRegistry(tmp_path)
    records=[
        {"record_type":"BUDGET_LAW","budget_year":2026,"amount_kopecks":None,"dimensions":{},"source":{"law":"426-FZ"}},
        _r("FEDERAL_BUDGET_APPROPRIATION",100000), _r("FEDERAL_BUDGET_LIMIT",90000), _r("FEDERAL_BUDGET_COMMITMENT",85000), _r("FEDERAL_BUDGET_CASH_EXECUTION",80000),
        _r("PROCUREMENT_CONTRACT",80000,registry_number="012345",contract_number="A-1",customer_inn="7700000000",supplier_inn="7800000000"),
        _r("PROCUREMENT_PAYMENT",80000,registry_number="012345",payment_id="P-1",customer_inn="7700000000",supplier_inn="7800000000"),
    ]
    traces=build_traces(records,registry=reg,as_of="2026-02-01")
    assert len(traces)==1 and traces[0]["status"]=="TRACEABLE"
    assert traces[0]["kbk_resolution"]["status"]=="RESOLVED"
    assert traces[0]["stages"]["PAYMENT"]
    trace_records=traces_as_records(traces)
    bundle=build_record_proof_bundle(trace_records)
    assert verify_record_in_bundle(trace_records[0],bundle["proofs"][0],bundle["record_merkle_root"])
    graph=build_trace_graph(traces,bundle["record_merkle_root"])
    assert any(n["kind"]=="SINERGY_BUDGET_ROOT" for n in graph["nodes"])
    assert any(e["kind"]=="MERKLE_INCLUDED_IN" for e in graph["edges"])

def test_eis_payment_and_ikz():
    from synergy_budget.eis import parse_contract_xml, parse_payment_xml
    cxml=b'''<contract><regNum>012345</regNum><contractNumber>A-1</contractNumber><purchaseCode>0126IKZ</purchaseCode><signDate>2026-05-01</signDate><customer><inn>7700000000</inn></customer><supplier><inn>7800000000</inn></supplier><price>100.00</price><kbk>02004112010490019241</kbk></contract>'''
    pxml=b'''<paymentInfo><paymentId>P-1</paymentId><regNum>012345</regNum><purchaseCode>0126IKZ</purchaseCode><paymentDate>2026-05-15</paymentDate><customer><inn>7700000000</inn></customer><supplier><inn>7800000000</inn></supplier><paymentAmount>100.00</paymentAmount><kbk>02004112010490019241</kbk></paymentInfo>'''
    c=parse_contract_xml(cxml,"c.xml",2026)[0]; p=parse_payment_xml(pxml,"p.xml",2026)[0]
    assert c["dimensions"]["ikz"]=="0126IKZ"
    assert p["record_type"]=="PROCUREMENT_PAYMENT" and p["dimensions"]["payment_id"]=="P-1"
    assert link_payments([c],[p])[0]["status"]=="AUTO_LINKED"

def test_merkle_root_backward_compatible():
    from synergy_budget.merkle import merkle_root, ZERO_ROOT
    assert merkle_root([])==ZERO_ROOT
    assert merkle_root([b"a",b"b",b"c"])==merkle_root([b"a",b"b",b"c"])

def test_v02_contract_parser_compatibility():
    from synergy_budget.eis import parse_contract_xml
    xml=b'''<contract><regNum>012345</regNum><contractNumber>A-1</contractNumber><customer><inn>7700000000</inn></customer><suppliers><supplier><inn>7800000000</inn></supplier></suppliers><price>1234.56</price><kbk>02004112010490019241</kbk></contract>'''
    rows=parse_contract_xml(xml,"contract.xml",2026)
    assert rows[0]["amount_kopecks"]==123456
    assert rows[0]["dimensions"]["contract_number"]=="A-1"
    assert rows[0]["dimensions"]["supplier_inn"]=="7800000000"

def test_registry_xlsx_import(tmp_path: Path):
    import openpyxl
    from synergy_budget.kbk_registry import load_rows
    p=tmp_path/"kbk.xlsx"; wb=openpyxl.Workbook(); ws=wb.active
    ws.append(["Код","Наименование"]); ws.append([KBK,"Связь"]); wb.save(p)
    rows=load_rows(p); assert rows[0]["Код"]==KBK and rows[0]["Наименование"]=="Связь"

def test_ambiguous_payment_marks_candidate_trace_review(tmp_path: Path):
    entries=import_rows([{"code":KBK,"name":"Связь"}],budget_year=2026,revision_id="70n",effective_from="2026-01-01",source_url="official")
    write_entries(tmp_path,entries); reg=VersionedKBKRegistry(tmp_path)
    c1=_r("PROCUREMENT_CONTRACT",registry_number="111",contract_number="A",supplier_inn="7800000000")
    c2=_r("PROCUREMENT_CONTRACT",registry_number="111",contract_number="A",supplier_inn="7800000000"); c2["source"]={"source_id":"second"}
    p=_r("PROCUREMENT_PAYMENT",registry_number="111",contract_number="A",supplier_inn="7800000000")
    records=[_r("FEDERAL_BUDGET_APPROPRIATION"),c1,c2,p]
    traces=build_traces(records,registry=reg)
    assert len(traces)==2 and all(t["status"]=="REVIEW_REQUIRED" for t in traces)
    assert all(t["ambiguous_payment_links"] for t in traces)
