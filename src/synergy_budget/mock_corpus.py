from __future__ import annotations
import csv,json,shutil,zipfile
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import Element,SubElement,tostring
from .canonical import object_hash
from .coverage import compute_coverage
from .kbk_registry import RegistryEntry,VersionedKBKRegistry
from .proofs import build_record_proof_bundle
from .trace import build_traces,traces_as_records

MOCK_MARKER="SINERGY_BUDGET_MOCK_ONLY_DO_NOT_ANCHOR_AS_REAL"
PUBLIC_CORPORA=("pravo_budget_law","treasury_federal_budget","treasury_consolidated_budget",
"treasury_extra_budgetary_funds","treasury_federal_institutions","treasury_government_finance_statistics",
"treasury_open_data","electronic_budget_portal","eis_procurement",
"treasury_electronic_budget_exchange_formats","kbk_registry","kbk_legal_publications","bus_gov_institutions")
TRACEABLE="TRACEABLE"; TO_CONTRACT="TRACEABLE_TO_CONTRACT"; AMBIGUOUS="AMBIGUOUS"
UNRESOLVED="UNRESOLVED_KBK"; NO_LINE="NO_BUDGET_LINE"

@dataclass(frozen=True)
class MockCorpusConfig:
    start_year:int=2013; end_year:int=2026; contracts_per_year:int=100
    kbk_per_year:int=24; institutions_per_year:int=24; seed:int=20260821
    traceable_pct:int=65; to_contract_pct:int=15; ambiguous_pct:int=5
    unresolved_kbk_pct:int=10; no_budget_line_pct:int=5; emit_raw:bool=True
    def validate(self):
        if self.start_year>self.end_year or min(self.contracts_per_year,self.institutions_per_year)<1 or self.kbk_per_year<4: raise ValueError("invalid mock scale")
        if sum((self.traceable_pct,self.to_contract_pct,self.ambiguous_pct,self.unresolved_kbk_pct,self.no_budget_line_pct))!=100: raise ValueError("status percentages must sum to 100")

def _rec(rt,year,amount,dims,source,seed):
    r={"record_type":rt,"budget_year":year,"amount_kopecks":amount,"currency":"RUB","dimensions":dims,
       "source":{"source_id":source,"mock":True,"mock_seed":seed,"notice":MOCK_MARKER},
       "visibility":"PUBLIC","schema_version":"sinergy.budget.record/mock-v1"}
    r["record_id"]=object_hash(r); return r
def is_mock_record(r): return bool((r.get("source") or {}).get("mock")) and (r.get("source") or {}).get("notice")==MOCK_MARKER
def assert_mock_only(rows):
    bad=[r for r in rows if not is_mock_record(r)]
    if bad: raise ValueError(f"mock corpus contains {len(bad)} non-mock records")
def _kbk(y,i,s=0):
    return f"{1+(i+s)%240:03d}{1+(3*i+y+s)%31:02d}{1+(7*i+y+s)%99:02d}{((y%100)*10**8+i+1+s*1000)%10**10:010d}{100+(11*i+s)%899:03d}"
def _inn(prefix,y,i): return f"{prefix:02d}{y%100:02d}{i%1_000_000:06d}"[:10]
def _ikz(y,i): return f"{y:04d}{i:032d}"[-36:]
def _status(i,c):
    b=i%100
    if b<c.traceable_pct:return TRACEABLE
    if b<c.traceable_pct+c.to_contract_pct:return TO_CONTRACT
    if b<c.traceable_pct+c.to_contract_pct+c.ambiguous_pct:return AMBIGUOUS
    if b<c.traceable_pct+c.to_contract_pct+c.ambiguous_pct+c.unresolved_kbk_pct:return UNRESOLVED
    return NO_LINE
def _jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("".join(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n" for r in rows),"utf-8")
def _load(path): return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]
def _rub(v): v=int(v); return f"{'-' if v<0 else ''}{abs(v)//100}.{abs(v)%100:02d}"
def _x(parent,name,value):
    e=SubElement(parent,name); e.text=str(value)
def _contract_xml(r):
    d=r["dimensions"]; root=Element("contract")
    for k,n in (("registry_number","regNum"),("contract_number","contractNumber"),("ikz","purchaseCode")):
        if d.get(k):_x(root,n,d[k])
    c=SubElement(root,"customer");_x(c,"inn",d["customer_inn"]);s=SubElement(root,"supplier");_x(s,"inn",d["supplier_inn"])
    for n,v in (("price",_rub(r["amount_kopecks"])),("kbk",d["kbk"]),("contractDate",d["contract_date"]),("executionEndDate",d["execution_end_date"])):_x(root,n,v)
    return tostring(root,encoding="utf-8",xml_declaration=True)
def _payment_xml(r):
    d=r["dimensions"]; root=Element("payment")
    for k,n in (("registry_number","regNum"),("contract_number","contractNumber"),("ikz","purchaseCode")):
        if d.get(k):_x(root,n,d[k])
    p=SubElement(root,"payer");_x(p,"inn",d["customer_inn"]);q=SubElement(root,"payee");_x(q,"inn",d["supplier_inn"])
    for n,v in (("paymentAmount",_rub(r["amount_kopecks"])),("kbk",d["kbk"]),("paymentId",d["payment_id"]),("paymentDate",d["payment_date"])):_x(root,n,v)
    return tostring(root,encoding="utf-8",xml_declaration=True)
def _raw_treasury(path,rows):
    from io import StringIO
    m={}
    for r in rows:
        k=r["dimensions"]["kbk"];v=m.setdefault(k,{x:0 for x in "alomc"});a=r["amount_kopecks"];t=r["record_type"]
        key={"FEDERAL_BUDGET_APPROPRIATION":"a","FEDERAL_BUDGET_LIMIT":"l","FEDERAL_BUDGET_COMMITMENT":"o","FEDERAL_BUDGET_MONETARY_OBLIGATION":"m","FEDERAL_BUDGET_CASH_EXECUTION":"c"}[t];v[key]+=a
    s=StringIO();w=csv.writer(s,delimiter=";");w.writerow(["Наименование показателя","КБК","Бюджетные ассигнования","Лимиты бюджетных обязательств","Бюджетные обязательства","Денежные обязательства","Кассовое исполнение"])
    for k,v in sorted(m.items()):w.writerow(["MOCK "+k,k,*[_rub(v[x]) for x in "alomc"]])
    path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:z.writestr(path.stem+".csv",s.getvalue().encode("utf-8-sig"))
def _raw_eis(path,contracts,payments):
    path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED,allowZip64=True) as z:
        for i,r in enumerate(contracts):z.writestr(f"contracts/contract-{i:08d}.xml",_contract_xml(r))
        for i,r in enumerate(payments):z.writestr(f"payments/payment-{i:08d}.xml",_payment_xml(r))
def _registry_entry(y,code,name,rev,date,seed):
    return RegistryEntry(y,code,name,rev,date,f"mock://kbk/{y}/{rev}",object_hash([y,rev,seed]),object_hash(["import",y,rev,seed]),f"MOCK KBK act {y}/{rev}").payload()

def _aux(y,c,expense,cash):
    inst=[];statements=[]
    for i in range(c.institutions_per_year):
        iid=f"MOCK-BUS-{y}-{i:05d}";inst+=[_rec("FEDERAL_INSTITUTION",y,None,{"institution_id":iid,"inn":_inn(77,y,i),"name":f"MOCK institution {i}"},"bus-gov-institutions",c.seed),
        _rec("STATE_ASSIGNMENT",y,expense//max(1,c.institutions_per_year*20),{"institution_id":iid,"assignment_id":f"SA-{y}-{i:05d}"},"bus-gov-institutions",c.seed)]
        statements.append(_rec("FEDERAL_INSTITUTION_FINANCIAL_STATEMENT",y,expense//max(1,c.institutions_per_year*15),{"institution_id":iid,"period":f"{y}-12-31"},"treasury-federal-institutions",c.seed))
    progs=[_rec("GOVERNMENT_PROGRAMME",y,expense//max(4,c.kbk_per_year//3),{"programme_id":f"GP-{y}-{i:03d}","national_project":f"NP-{i%5:02d}"},"electronic-budget-portal",c.seed) for i in range(max(4,c.kbk_per_year//3))]
    progs += [_rec("FEDERAL_PUBLIC_DEBT",y,int(expense*.68),{"measure":"mock_debt"},"electronic-budget-portal",c.seed),
              _rec("FEDERAL_BUDGET_TRANSFER",y,int(expense*.12),{"measure":"mock_transfer"},"electronic-budget-portal",c.seed)]
    return {"bus_gov_institutions":inst,"treasury_federal_institutions":statements,"electronic_budget_portal":progs,
    "treasury_consolidated_budget":[_rec("CONSOLIDATED_BUDGET_EXECUTION",y,int(cash*1.85),{"period":f"{y}-12-31"},"treasury-consolidated-budget",c.seed)],
    "treasury_extra_budgetary_funds":[_rec("EXTRA_BUDGETARY_FUND_EXECUTION",y,int(cash*.3),{"fund":"SFR"},"treasury-extra-budgetary-funds",c.seed),_rec("EXTRA_BUDGETARY_FUND_EXECUTION",y,int(cash*.12),{"fund":"FFOMS"},"treasury-extra-budgetary-funds",c.seed)],
    "treasury_government_finance_statistics":[_rec("GOVERNMENT_FINANCE_STATISTIC",y,cash,{"measure":"cash_expenditure"},"treasury-government-finance-statistics",c.seed)],
    "treasury_open_data":[_rec("TREASURY_OPEN_DATA_ITEM",y,None,{"dataset_id":f"MOCK-OD-{y}"},"treasury-open-data",c.seed)],
    "treasury_electronic_budget_exchange_formats":[_rec("BUDGET_EXCHANGE_SCHEMA",y,None,{"schema_id":f"MOCK-XSD-{y}"},"treasury-electronic-budget-exchange-formats",c.seed)]}

def generate_mock_corpus(output:Path,config:MockCorpusConfig|None=None,*,overwrite=False):
    c=config or MockCorpusConfig();c.validate();output=Path(output)
    if output.exists():
        if not overwrite:raise FileExistsError(output)
        shutil.rmtree(output)
    output.mkdir(parents=True);(output/"MOCK_ONLY").write_text(MOCK_MARKER+"\n","utf-8")
    files={k:[] for k in PUBLIC_CORPORA};all_records=[];truth={}
    for y in range(c.start_year,c.end_year+1):
        base=[_kbk(y,i) for i in range(c.kbk_per_year)];unresolved=_kbk(y,c.kbk_per_year+1,7);orphan=_kbk(y,c.kbk_per_year+2,9)
        entries=[];legal=[]
        for i,code in enumerate(base+[orphan]):
            entries.append(_registry_entry(y,code,f"MOCK KBK {i}","base",f"{y}-01-01",c.seed))
            if i%4==0:entries.append(_registry_entry(y,code,f"MOCK KBK revised {i}","midyear",f"{y}-07-01",c.seed))
        for rev in ("base","midyear"):
            rr=[e for e in entries if e["revision_id"]==rev]
            if rr:
                p=output/"kbk_registry"/str(y)/(rev+".jsonl");_jsonl(p,rr);files["kbk_registry"].append(p.as_posix())
        legal=[_rec("KBK_LEGAL_PUBLICATION",y,None,{"revision_id":r,"effective_from":f"{y}-{'01-01' if r=='base' else '07-01'}"},"kbk-rules-82n",c.seed) for r in ("base","midyear")]
        p=output/"canonical"/"kbk_legal_publications"/f"{y}.jsonl";_jsonl(p,legal);files["kbk_legal_publications"].append(p.as_posix());all_records+=legal
        contracts=[];payments=[];counts={k:0 for k in (TRACEABLE,TO_CONTRACT,AMBIGUOUS,UNRESOLVED,NO_LINE)}
        contract_sum={k:0 for k in base+[unresolved]};pay_sum={k:0 for k in base+[unresolved]}
        ak=base[-1];ac=_inn(77,y,999991);asu=_inn(78,y,999992);aa=12_345_600
        for i in range(c.contracts_per_year):
            st=_status(i,c);counts[st]+=1
            code=unresolved if st==UNRESOLVED else orphan if st==NO_LINE else ak if st==AMBIGUOUS else base[i%max(1,len(base)-1)]
            if st==AMBIGUOUS: amount=aa;cust=ac;sup=asu;reg=cn=ikz="";date=f"{y}-03-15"
            else:
                amount=2_500_000+((i*7919+y*37)%95_000_000);cust=_inn(77,y,i%max(1,c.institutions_per_year));sup=_inn(78,y,i+100000)
                reg=f"MOCK-{y}-{i:09d}";cn=f"C-{y}-{i:08d}";ikz=_ikz(y,i);date=f"{y}-{1+i%11:02d}-{1+i%27:02d}"
            con=_rec("PROCUREMENT_CONTRACT",y,amount,{"registry_number":reg,"contract_number":cn,"ikz":ikz,"customer_inn":cust,"supplier_inn":sup,"kbk":code,"contract_date":date,"execution_end_date":f"{y}-12-25","mock_truth_status":st,"mock_contract_seq":i},"eis-procurement",c.seed);contracts.append(con)
            if code in contract_sum:contract_sum[code]+=amount
            if st in (TRACEABLE,UNRESOLVED,NO_LINE):
                paid=amount*(80+i%21)//100
                pay=_rec("PROCUREMENT_PAYMENT",y,paid,{"registry_number":reg,"contract_number":cn,"ikz":ikz,"customer_inn":cust,"supplier_inn":sup,"kbk":code,"payment_id":f"P-{y}-{i:09d}","payment_date":f"{y}-{1+i%11:02d}-{min(28,2+i%27):02d}"},"eis-procurement",c.seed);payments.append(pay)
                if code in pay_sum:pay_sum[code]+=paid
        if counts[AMBIGUOUS]:
            pay=_rec("PROCUREMENT_PAYMENT",y,aa,{"registry_number":"","contract_number":"","ikz":"","customer_inn":ac,"supplier_inn":asu,"kbk":ak,"payment_id":f"P-{y}-AMBIG","payment_date":f"{y}-03-20"},"eis-procurement",c.seed);payments.append(pay);pay_sum[ak]+=aa
        treasury=[]
        for j,code in enumerate(base+[unresolved]):
            a=500_000_000+j*25_000_000+contract_sum[code];l=a*94//100;o=min(l,contract_sum[code]*104//100+5_000_000);m=min(o,contract_sum[code]*96//100+3_000_000);cash=min(l,pay_sum[code]+25_000_000+j*1_000_000)
            for rt,val in (("FEDERAL_BUDGET_APPROPRIATION",a),("FEDERAL_BUDGET_LIMIT",l),("FEDERAL_BUDGET_COMMITMENT",o),("FEDERAL_BUDGET_MONETARY_OBLIGATION",m),("FEDERAL_BUDGET_CASH_EXECUTION",cash)):
                treasury.append(_rec(rt,y,val,{"kbk":code,"period":f"{y}-12-31","mock_line":j},"treasury-federal-budget",c.seed))
        expense=sum(r["amount_kopecks"] for r in treasury if r["record_type"]=="FEDERAL_BUDGET_APPROPRIATION");cash=sum(r["amount_kopecks"] for r in treasury if r["record_type"]=="FEDERAL_BUDGET_CASH_EXECUTION");revenue=expense*91//100
        laws=[_rec("BUDGET_LAW",y,None,{"law_id":f"MOCK-FZ-{y}"},"pravo-federal-budget-law-426-fz",c.seed),_rec("FEDERAL_BUDGET_REVENUE_PLAN",y,revenue,{"scope":"federal_budget"},"pravo-federal-budget-law-426-fz",c.seed),_rec("FEDERAL_BUDGET_EXPENDITURE_PLAN",y,expense,{"scope":"federal_budget"},"pravo-federal-budget-law-426-fz",c.seed),_rec("FEDERAL_BUDGET_DEFICIT_PLAN",y,expense-revenue,{"scope":"federal_budget"},"pravo-federal-budget-law-426-fz",c.seed),_rec("CLASSIFIED_ANNEX_REFERENCE",y,None,{"policy":"metadata_only_no_content"},"pravo-federal-budget-law-426-fz",c.seed)]
        aux=_aux(y,c,expense,cash);corpora={"pravo_budget_law":laws,"treasury_federal_budget":treasury,"eis_procurement":contracts+payments,**aux}
        for name,rows in corpora.items():
            p=output/"canonical"/name/f"{y}.jsonl";_jsonl(p,rows);files[name].append(p.as_posix());all_records+=rows
        if c.emit_raw:
            _raw_treasury(output/"raw"/"treasury_federal_budget"/str(y)/f"federal-budget-{y}.zip",treasury)
            _raw_eis(output/"raw"/"eis_procurement"/str(y)/f"eis-{y}.zip",contracts,payments)
            p=output/"raw"/"kbk"/str(y)/f"kbk-{y}.csv";p.parent.mkdir(parents=True,exist_ok=True)
            with p.open("w",encoding="utf-8-sig",newline="") as f:
                w=csv.writer(f,delimiter=";");w.writerow(["КБК","Наименование","revision_id","effective_from"]);w.writerows((e["code"],e["name"],e["revision_id"],e["effective_from"]) for e in entries)
        truth[str(y)]=counts
    assert_mock_only(all_records);_jsonl(output/"canonical"/"all_records.jsonl",all_records)
    traces=build_traces(all_records,registry=VersionedKBKRegistry(output/"kbk_registry"),as_of=None);trace_records=traces_as_records(traces);proofs=build_record_proof_bundle(trace_records);metrics=compute_coverage(traces,trace_records,proofs,all_records)
    _jsonl(output/"traces"/"trace-records.jsonl",trace_records);(output/"traces"/"traces.json").write_text(json.dumps({"traces":traces},ensure_ascii=False,sort_keys=True),"utf-8")
    (output/"proofs").mkdir(parents=True,exist_ok=True);(output/"proofs"/"record-proofs.json").write_text(json.dumps(proofs,ensure_ascii=False,sort_keys=True),"utf-8")
    gt={"schema_version":"sinergy.budget.mock-ground-truth/v1","marker":MOCK_MARKER,"config":asdict(c),"category_truth_by_year":truth,"coverage_metrics":metrics}
    (output/"ground_truth").mkdir(parents=True,exist_ok=True);(output/"ground_truth"/"ground_truth.json").write_text(json.dumps(gt,ensure_ascii=False,indent=2,sort_keys=True),"utf-8")
    manifest={"schema_version":"sinergy.budget.mock-corpus/v1","marker":MOCK_MARKER,"warning":"SYNTHETIC DATA ONLY. NEVER REPRESENT AS REAL BUDGET DATA.","config":asdict(c),"public_corpora":list(PUBLIC_CORPORA),"record_count":len(all_records),"trace_count":len(traces),"trace_record_count":len(trace_records),"record_merkle_root":proofs["record_merkle_root"],"files":files,"coverage_metrics":metrics}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True),"utf-8");return manifest

def validate_mock_corpus(root:Path):
    root=Path(root)
    if (root/"MOCK_ONLY").read_text("utf-8").strip()!=MOCK_MARKER:raise ValueError("invalid MOCK_ONLY marker")
    records=_load(root/"canonical"/"all_records.jsonl");assert_mock_only(records)
    traces=build_traces(records,registry=VersionedKBKRegistry(root/"kbk_registry"),as_of=None);tr=traces_as_records(traces);pb=build_record_proof_bundle(tr);metrics=compute_coverage(traces,tr,pb,records)
    gt=json.loads((root/"ground_truth"/"ground_truth.json").read_text("utf-8"));manifest=json.loads((root/"manifest.json").read_text("utf-8"))
    ok=metrics==gt["coverage_metrics"] and pb["record_merkle_root"]==manifest["record_merkle_root"]
    return {"schema_version":"sinergy.budget.mock-validation/v1","ok":ok,"record_count":len(records),"trace_count":len(traces),"record_merkle_root":pb["record_merkle_root"],"coverage_metrics":metrics}
