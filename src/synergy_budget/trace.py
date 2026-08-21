from __future__ import annotations
from collections import defaultdict
from datetime import date
from typing import Iterable
from .canonical import canonical_json_bytes, object_hash
from .merkle import merkle_root

PLAN_TYPES={"FEDERAL_BUDGET_APPROPRIATION":"APPROPRIATION","FEDERAL_BUDGET_LIMIT":"LIMIT","FEDERAL_BUDGET_COMMITMENT":"OBLIGATION","FEDERAL_BUDGET_MONETARY_OBLIGATION":"MONETARY_OBLIGATION","FEDERAL_BUDGET_CASH_EXECUTION":"CASH_EXECUTION"}
CONTRACT_TYPES={"PROCUREMENT_CONTRACT"}
PAYMENT_TYPES={"PROCUREMENT_PAYMENT","TREASURY_PAYMENT","CONTRACT_PAYMENT"}
LAW_TYPES={"FEDERAL_BUDGET_EXPENDITURE_PLAN","FEDERAL_BUDGET_REVENUE_PLAN","FEDERAL_BUDGET_DEFICIT_PLAN","BUDGET_LAW"}

def record_ref(record: dict)->str: return str(record.get("record_id") or object_hash(record))
def _dims(r): return r.get("dimensions") or {}
def _norm_inn(v): return "".join(c for c in str(v or "") if c.isdigit())
def _norm(v): return str(v or "").strip().upper()
def _dateish(v):
    text=str(v or "").strip()
    if not text: return None
    for n in (10,7,4):
        try:
            if n==10: return date.fromisoformat(text[:10])
            if n==7: return date.fromisoformat(text[:7]+"-01")
            if n==4: return date(int(text[:4]),1,1)
        except ValueError: pass
    return None

def _period_close(a,b,days=62):
    da,db=_dateish(a),_dateish(b)
    return bool(da and db and abs((da-db).days)<=days)

def _evidence(field, left, right, matched, weight, strong=False):
    return {"field":field,"left":left or "","right":right or "","matched":bool(matched),"weight":int(weight),"strong":bool(strong)}

def score_contract_payment(contract: dict, payment: dict) -> dict:
    cd,pd=_dims(contract),_dims(payment)
    if int(contract.get("budget_year") or 0)!=int(payment.get("budget_year") or 0):
        return {"eligible":False,"score_bps":0,"strong":False,"evidence":[_evidence("budget_year",contract.get("budget_year"),payment.get("budget_year"),False,1000)]}
    evidence=[_evidence("budget_year",contract.get("budget_year"),payment.get("budget_year"),True,1000)]
    score=1000; strong=False
    fields=[
        ("registry_number",7000,True,_norm),
        ("contract_number",6000,True,_norm),
        ("ikz",3000,True,_norm),
        ("customer_inn",1000,False,_norm_inn),
        ("supplier_inn",1000,False,_norm_inn),
        ("kbk",1000,False,_norm),
    ]
    for field,weight,is_strong,norm in fields:
        a,b=norm(cd.get(field)),norm(pd.get(field))
        if a and b:
            matched=a==b
            evidence.append(_evidence(field,a,b,matched,weight,is_strong))
            if not matched and is_strong:
                return {"eligible":False,"score_bps":0,"strong":False,"evidence":evidence,"reason":f"STRONG_ID_MISMATCH:{field}"}
            if matched:
                score+=weight; strong=strong or is_strong
    ca,pa=contract.get("amount_kopecks"),payment.get("amount_kopecks")
    if ca is not None and pa is not None:
        matched=int(ca)==int(pa); evidence.append(_evidence("amount_kopecks",ca,pa,matched,500)); score+=500 if matched else 0
    cp=cd.get("contract_date") or cd.get("period")
    pp=pd.get("payment_date") or pd.get("period")
    if cp and pp:
        matched=_period_close(cp,pp); evidence.append(_evidence("period",cp,pp,matched,500)); score+=500 if matched else 0
    return {"eligible":True,"score_bps":min(score,10000),"strong":strong,"evidence":evidence}

def link_payments(contracts: list[dict], payments: list[dict], auto_threshold_bps: int=8000) -> list[dict]:
    out=[]
    for p in payments:
        candidates=[]
        for c in contracts:
            s=score_contract_payment(c,p)
            if s.get("eligible"):
                candidates.append((s["score_bps"],record_ref(c),c,s))
        candidates.sort(key=lambda x:(-x[0],x[1]))
        if not candidates:
            out.append({"payment_ref":record_ref(p),"status":"UNMATCHED","contract_ref":None,"score_bps":0,"evidence":[]}); continue
        top=candidates[0]; tied=len(candidates)>1 and candidates[1][0]==top[0]
        tied_refs=[x[1] for x in candidates if x[0]==top[0]]
        status="AUTO_LINKED" if top[0]>=auto_threshold_bps and top[3].get("strong") and not tied else ("AMBIGUOUS" if tied else "REVIEW_REQUIRED")
        out.append({"payment_ref":record_ref(p),"status":status,"contract_ref":top[1] if status!="AMBIGUOUS" else None,"candidate_refs":tied_refs if tied else [top[1]],"score_bps":top[0],"evidence":top[3]["evidence"],"candidate_count":len(candidates)})
    return out

def _source_root(records: Iterable[dict]) -> str:
    ordered=sorted(records,key=record_ref)
    return merkle_root(canonical_json_bytes(r) for r in ordered)

def build_traces(records: list[dict], registry=None, as_of: str | None=None, auto_threshold_bps: int=8000) -> list[dict]:
    by_ref={record_ref(r):r for r in records}
    contracts=[r for r in records if r.get("record_type") in CONTRACT_TYPES]
    payments=[r for r in records if r.get("record_type") in PAYMENT_TYPES]
    links=link_payments(contracts,payments,auto_threshold_bps)
    links_by_contract=defaultdict(list)
    ambiguous_by_contract=defaultdict(list)
    for link in links:
        if link.get("contract_ref"):
            links_by_contract[link["contract_ref"]].append(link)
        elif link.get("status")=="AMBIGUOUS":
            for candidate_ref in link.get("candidate_refs") or []:
                ambiguous_by_contract[candidate_ref].append(link)
    laws=defaultdict(list)
    lines=defaultdict(list)
    for r in records:
        year=int(r.get("budget_year") or 0); rt=r.get("record_type")
        if rt in LAW_TYPES: laws[year].append(r)
        if rt in PLAN_TYPES:
            kbk=_norm(_dims(r).get("kbk"))
            if kbk: lines[(year,kbk)].append(r)
    traces=[]
    for c in sorted(contracts,key=record_ref):
        year=int(c.get("budget_year") or 0); cd=_dims(c); kbk=_norm(cd.get("kbk")); cref=record_ref(c)
        line_records=sorted(lines.get((year,kbk),[]),key=record_ref)
        stage_refs=defaultdict(list)
        for r in laws.get(year,[]): stage_refs["LAW"].append(record_ref(r))
        for r in line_records: stage_refs[PLAN_TYPES[r.get("record_type")]].append(record_ref(r))
        stage_refs["CONTRACT"].append(cref)
        if cd.get("supplier_inn"): stage_refs["SUPPLIER"]=[_norm_inn(cd.get("supplier_inn"))]
        linked=links_by_contract.get(cref,[])
        ambiguous=ambiguous_by_contract.get(cref,[])
        for link in linked:
            if link.get("status")=="AUTO_LINKED":
                stage_refs["PAYMENT"].append(link["payment_ref"])
        source_records=list(laws.get(year,[]))+line_records+[c]+[by_ref[x["payment_ref"]] for x in linked+ambiguous if x["payment_ref"] in by_ref]
        kbk_resolution=None
        if registry is not None and kbk:
            kbk_resolution=registry.resolve(year,kbk,as_of=as_of)
        if not kbk or not line_records:
            status="PARTIAL_NO_BUDGET_LINE"
        elif kbk_resolution and kbk_resolution.get("status")!="RESOLVED":
            status="PARTIAL_KBK_UNRESOLVED"
        elif ambiguous or any(x["status"]=="REVIEW_REQUIRED" for x in linked):
            status="REVIEW_REQUIRED"
        elif any(x["status"]=="AUTO_LINKED" for x in linked):
            status="TRACEABLE"
        else:
            status="TRACEABLE_TO_CONTRACT"
        body={
            "schema_version":"sinergy.budget.trace/v1",
            "budget_year":year,
            "kbk":kbk,
            "customer_inn":_norm_inn(cd.get("customer_inn")),
            "supplier_inn":_norm_inn(cd.get("supplier_inn")),
            "ikz":_norm(cd.get("ikz")),
            "registry_number":_norm(cd.get("registry_number")),
            "contract_number":_norm(cd.get("contract_number")),
            "contract_amount_kopecks":c.get("amount_kopecks"),
            "status":status,
            "stages":dict(stage_refs),
            "payment_links":sorted(linked,key=lambda x:x["payment_ref"]),
            "ambiguous_payment_links":sorted(ambiguous,key=lambda x:x["payment_ref"]),
            "kbk_resolution":kbk_resolution,
            "source_record_root":_source_root(source_records),
            "source_record_refs":sorted(record_ref(r) for r in source_records),
        }
        body["evidence_hash"]=object_hash({"payment_links":body["payment_links"],"ambiguous_payment_links":body["ambiguous_payment_links"],"kbk_resolution":kbk_resolution,"source_record_refs":body["source_record_refs"]})
        body["trace_id"]=object_hash(body)
        traces.append(body)
    return traces

def traces_as_records(traces: list[dict]) -> list[dict]:
    out=[]
    for t in traces:
        record={
            "record_type":"BUDGET_TRACE_COMMITMENT",
            "budget_year":t["budget_year"],
            "amount_kopecks":t.get("contract_amount_kopecks"),
            "currency":"RUB",
            "dimensions":{"trace_id":t["trace_id"],"kbk":t.get("kbk","") ,"registry_number":t.get("registry_number","") ,"contract_number":t.get("contract_number","") ,"customer_inn":t.get("customer_inn","") ,"supplier_inn":t.get("supplier_inn","") ,"source_record_root":t["source_record_root"],"evidence_hash":t["evidence_hash"],"trace_status":t["status"]},
            "source":{"source_id":"sinergy_trace_engine","trace_schema":t["schema_version"]},
            "visibility":"PUBLIC","schema_version":"sinergy.budget.record/v3",
        }
        record["record_id"]=object_hash(record)
        out.append(record)
    return out
