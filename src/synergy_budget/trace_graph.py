from __future__ import annotations
import hashlib, json


def _id(kind, value):
    raw=json.dumps([kind,value],ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return f"{kind}:{hashlib.sha256(raw).hexdigest()[:24]}"


def build_trace_graph(traces: list[dict], snapshot_root: str | None=None) -> dict:
    nodes={}; edges=[]
    def node(kind,key,**attrs):
        nid=_id(kind,key); nodes.setdefault(nid,{"id":nid,"kind":kind,"key":key,**attrs}); return nid
    def edge(a,b,kind,**attrs): edges.append({"from":a,"to":b,"kind":kind,**attrs})
    for t in traces:
        tid=t["trace_id"]; stages=t.get("stages") or {}
        law=[node("LAW",x) for x in stages.get("LAW") or []]
        app=[node("APPROPRIATION",x) for x in stages.get("APPROPRIATION") or []]
        limit=[node("LIMIT",x) for x in stages.get("LIMIT") or []]
        obligation=[node("OBLIGATION",x) for x in (stages.get("OBLIGATION") or []) + (stages.get("MONETARY_OBLIGATION") or [])]
        contract=[node("CONTRACT",x) for x in stages.get("CONTRACT") or []]
        supplier=[node("SUPPLIER",x) for x in stages.get("SUPPLIER") or []]
        payment=[node("PAYMENT",x) for x in stages.get("PAYMENT") or []]
        cash=[node("CASH_EXECUTION",x, aggregate=True) for x in stages.get("CASH_EXECUTION") or []]

        def connect(srcs,dsts,kind):
            for a in srcs:
                for b in dsts: edge(a,b,kind,trace_id=tid)
        if law and app: connect(law,app,"LEGAL_CONTEXT")
        if app and limit: connect(app,limit,"CONTROLLED_BY_LIMIT")
        base=limit or app
        if base and obligation: connect(base,obligation,"OBLIGATION_RECORDED")
        funding=obligation or base
        if funding and contract: connect(funding,contract,"CLASSIFICATION_ASSOCIATION")
        if contract and supplier: connect(contract,supplier,"AWARDED_TO")
        if contract and payment: connect(contract,payment,"SETTLED_BY_PUBLIC_PAYMENT_RECORD")
        if payment and cash: connect(payment,cash,"RECONCILES_AGAINST_AGGREGATE_CASH_EXECUTION")
        elif funding and cash: connect(funding,cash,"AGGREGATE_CASH_EXECUTION")

        commit=node("TRACE_COMMITMENT",tid,status=t.get("status"),source_record_root=t.get("source_record_root"))
        terminal=payment or contract or obligation or limit or app or law
        for a in terminal: edge(a,commit,"COMMITS_TO",trace_id=tid)
        for a in cash: edge(a,commit,"AGGREGATE_EVIDENCE",trace_id=tid)
        if snapshot_root:
            root=node("SINERGY_BUDGET_ROOT",snapshot_root)
            edge(commit,root,"MERKLE_INCLUDED_IN",trace_id=tid)
    return {"schema_version":"sinergy.budget.trace-graph/v1","nodes":sorted(nodes.values(),key=lambda x:x["id"]),"edges":sorted(edges,key=lambda x:(x["from"],x["to"],x["kind"],x.get("trace_id",'')))}
