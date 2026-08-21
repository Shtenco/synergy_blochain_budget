from __future__ import annotations
import csv, json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable
from .canonical import object_hash
from .kbk import ExpenseKBK

SCHEMA = "sinergy.budget.kbk-registry-entry/v1"

@dataclass(frozen=True)
class RegistryEntry:
    budget_year: int
    code: str
    name: str
    revision_id: str
    effective_from: str
    source_url: str
    source_sha256: str | None = None
    import_artifact_sha256: str | None = None
    source_document: str | None = None
    schema_version: str = SCHEMA
    def payload(self) -> dict:
        value={
            "schema_version": self.schema_version,
            "budget_year": self.budget_year,
            "code": self.code,
            "name": self.name,
            "revision_id": self.revision_id,
            "effective_from": self.effective_from,
            "source_url": self.source_url,
            "source_sha256": self.source_sha256,
            "import_artifact_sha256": self.import_artifact_sha256,
            "source_document": self.source_document,
        }
        value["entry_id"]=object_hash(value)
        return value

def load_registry_catalog(path: Path) -> dict:
    data=json.loads(path.read_text("utf-8"))
    years=data.get("years",{})
    for year in range(int(data.get("min_year",2013)), int(data.get("max_year",2026))+1):
        if str(year) not in years:
            raise ValueError(f"registry catalog missing explicit year partition {year}")
    return data

def _date(value: str) -> date:
    return date.fromisoformat(value[:10])

def import_rows(rows: Iterable[dict], *, budget_year: int, revision_id: str, effective_from: str,
                source_url: str, source_sha256: str | None=None, import_artifact_sha256: str | None=None, source_document: str | None=None) -> list[dict]:
    _date(effective_from)
    out=[]
    for row in rows:
        raw=row.get("kbk") or row.get("code") or row.get("КБК") or row.get("Код") or row.get("код")
        if not raw: continue
        code=ExpenseKBK.parse(raw).raw
        name=str(row.get("name") or row.get("title") or row.get("Наименование") or row.get("наименование") or "").strip()
        if not name: continue
        out.append(RegistryEntry(int(budget_year),code,name,str(revision_id),effective_from,source_url,source_sha256,import_artifact_sha256,source_document).payload())
    return sorted(out,key=lambda x:(x["code"],x["effective_from"],x["revision_id"],x["entry_id"]))

def load_rows(path: Path) -> list[dict]:
    suffix=path.suffix.lower()
    if suffix==".jsonl":
        return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]
    if suffix==".json":
        value=json.loads(path.read_text("utf-8")); return value if isinstance(value,list) else value.get("rows") or value.get("records") or []
    if suffix in {".csv",".txt"}:
        text=path.read_text("utf-8-sig")
        sample=text[:4096]
        try: dialect=csv.Sniffer().sniff(sample,delimiters=";,\t,")
        except csv.Error: dialect=csv.excel
        return list(csv.DictReader(text.splitlines(),dialect=dialect))
    if suffix==".xlsx":
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("XLSX registry import requires openpyxl; install .[excel]") from exc
        wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
        out=[]
        for ws in wb.worksheets:
            rows=ws.iter_rows(values_only=True)
            header=None
            for values in rows:
                cells=[str(v).strip() if v is not None else "" for v in values]
                if not any(cells):
                    continue
                if header is None:
                    header=cells
                    continue
                out.append({header[i]: values[i] for i in range(min(len(header),len(values))) if header[i]})
        return out
    raise ValueError(f"unsupported registry import: {path}")

def write_entries(root: Path, entries: list[dict]) -> list[Path]:
    by_partition={}
    for e in entries:
        key=(int(e["budget_year"]),str(e["revision_id"]))
        by_partition.setdefault(key,[]).append(e)
    paths=[]
    for (year,rev), rows in by_partition.items():
        safe="".join(c if c.isalnum() or c in "-_." else "_" for c in rev)
        path=root/str(year)/f"{safe}.jsonl"; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in rows),"utf-8")
        paths.append(path)
    return paths

class VersionedKBKRegistry:
    def __init__(self, root: Path): self.root=Path(root)
    def _entries(self, year: int, code: str) -> list[dict]:
        partition=self.root/str(int(year))
        if not partition.exists(): return []
        out=[]
        for path in sorted(partition.glob("*.jsonl")):
            for line in path.read_text("utf-8").splitlines():
                if not line.strip(): continue
                e=json.loads(line)
                if int(e.get("budget_year",-1)) != int(year):
                    raise ValueError(f"cross-year registry contamination in {path}")
                if e.get("code")==code: out.append(e)
        return out
    def resolve(self, budget_year: int, code: object, as_of: str | None=None) -> dict:
        normalized=ExpenseKBK.parse(code).raw
        candidates=self._entries(int(budget_year),normalized)
        if not candidates:
            return {"status":"UNRESOLVED","budget_year":int(budget_year),"code":normalized,"entry":None}
        cutoff=_date(as_of) if as_of else date(int(budget_year),12,31)
        active=[e for e in candidates if _date(e["effective_from"])<=cutoff]
        if not active:
            return {"status":"NOT_YET_EFFECTIVE","budget_year":int(budget_year),"code":normalized,"entry":None}
        active.sort(key=lambda e:(_date(e["effective_from"]),str(e["revision_id"]),str(e["entry_id"])))
        return {"status":"RESOLVED","budget_year":int(budget_year),"code":normalized,"entry":active[-1]}
