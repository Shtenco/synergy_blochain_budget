from __future__ import annotations
import csv,json,math,random
from dataclasses import asdict,dataclass
from pathlib import Path
from statistics import mean

SCHEMA="sinergy.budget.state-roi/v1"; NOTICE="SYNTHETIC_POLICY_SIMULATION_NOT_REAL_BUDGET_DATA"
# key,label,exposure, loss(lo,mode,hi), preventable, baseline prevention, blockchain prevention, layer bias(F,R,M)
RISKS=(
("overpricing","Завышение закупочной цены","procurement",(.004,.007,.012),(.45,.65,.80),(.10,.20,.32),(.35,.52,.68),(.85,1.05,1.15)),
("cartel","Картельные/координированные паттерны","procurement",(.002,.004,.0075),(.35,.55,.72),(.06,.14,.24),(.28,.46,.62),(.85,1.05,1.20)),
("splitting","Дробление закупок/обход конкуренции","procurement",(.0006,.0012,.0025),(.50,.68,.82),(.10,.22,.35),(.42,.62,.78),(.70,1,1.35)),
("false_acceptance","Оплата неподтвержденной/неполной поставки","procurement",(.0005,.001,.0022),(.50,.68,.82),(.14,.28,.42),(.40,.58,.74),(.85,1.05,1.15)),
("fraud_diversion","Перенаправление/фиктивный получатель","procurement",(.00035,.0008,.0016),(.45,.62,.78),(.14,.28,.42),(.42,.60,.76),(.80,1.05,1.20)),
("duplicate_payment","Дубли/ошибочные/неподдержанные платежи","total_budget",(.00025,.00055,.001),(.70,.85,.95),(.30,.48,.62),(.70,.86,.95),(.90,1,1.15)),
("classification_transfer","Ошибки КБК/трансфертов/сверки","total_budget",(.0002,.00045,.0009),(.55,.72,.88),(.34,.50,.66),(.68,.83,.93),(.75,1.10,1.25)),
("late_payment","Стоимость задержек оплаты","procurement",(.0007,.0015,.0028),(.55,.70,.85),(.08,.18,.30),(.32,.48,.64),(.85,1.05,1.15)),
("reconciliation_admin","Ручная сверка и административные издержки","total_budget",(.00015,.0003,.00055),(.55,.72,.85),(.02,.08,.16),(.42,.58,.72),(.70,1.10,1.25)),)

@dataclass(frozen=True)
class StateROIConfig:
    regions:int=89; municipalities_per_region:int=20
    annual_total_budget_rub:float=62e12; annual_procurement_rub:float=13.6e12
    budget_shares:tuple[float,float,float]=(.55,.32,.13); procurement_shares:tuple[float,float,float]=(.47,.35,.18)
    horizon_years:int=10; real_discount_rate:float=.08; real_budget_growth:float=.01
    upfront_platform_cost_rub:float=55e9; integration_rollout_cost_rub:float=65e9
    annual_opex_rub:float=24e9; annual_security_audit_rub:float=4e9; capex_year0_share:float=.72
    adoption_ramp:tuple[float,...]=(.22,.45,.68,.84,.94,1.0); monte_carlo_runs:int=5000; seed:int=20260823
    geography_sigma:float=.65; max_incremental_benefit_share_of_budget:float=.015
    def validate(self):
        if self.regions<1 or self.municipalities_per_region<0 or self.horizon_years<2 or self.monte_carlo_runs<1: raise ValueError("invalid scale")
        if self.annual_procurement_rub>self.annual_total_budget_rub: raise ValueError("procurement > budget")
        if abs(sum(self.budget_shares)-1)>1e-9 or abs(sum(self.procurement_shares)-1)>1e-9: raise ValueError("shares != 1")

def _weights(r,n,s):
    a=[r.lognormvariate(0,s) for _ in range(n)];z=sum(a);return [x/z for x in a]
def _q(a,q):
    a=sorted(a);p=(len(a)-1)*q;i=int(p);j=min(i+1,len(a)-1);return a[i]+(a[j]-a[i])*(p-i)
def _npv(cf,d):return sum(x/(1+d)**i for i,x in enumerate(cf))
def _irr(cf):
    if not any(x<0 for x in cf) or not any(x>0 for x in cf):return None
    lo,hi=-.99,10.;flo=_npv(cf,lo)
    if flo*_npv(cf,hi)>0:return None
    for _ in range(100):
        m=(lo+hi)/2;fm=_npv(cf,m)
        if flo*fm<=0:hi=m
        else:lo=m;flo=fm
    return (lo+hi)/2
def _payback(cf):
    s=0
    for y,x in enumerate(cf):
        p=s;s+=x
        if y and s>=0:return y-1+(-p/x if x else 0)
    return None

def build_geography(c:StateROIConfig):
    c.validate();r=random.Random(c.seed);rows=[];bs,ps=c.budget_shares,c.procurement_shares
    rows.append(dict(unit_id="FEDERAL",layer="federal",region_id=None,annual_budget_rub=c.annual_total_budget_rub*bs[0],annual_procurement_rub=c.annual_procurement_rub*ps[0],risk_multiplier=.92))
    bw=_weights(r,c.regions,c.geography_sigma);pr=[w*r.uniform(.72,1.32) for w in bw];z=sum(pr);pw=[x/z for x in pr]
    for i in range(c.regions):
        rid=f"REGION_{i+1:02d}";rm=max(.55,min(1.65,r.lognormvariate(-.5*.18**2,.18)))
        rows.append(dict(unit_id=rid,layer="regional",region_id=rid,annual_budget_rub=c.annual_total_budget_rub*bs[1]*bw[i],annual_procurement_rub=c.annual_procurement_rub*ps[1]*pw[i],risk_multiplier=rm))
        mw=_weights(r,c.municipalities_per_region,c.geography_sigma+.15);mp=[w*r.uniform(.68,1.38) for w in mw];zz=sum(mp);mp=[x/zz for x in mp]
        for j in range(c.municipalities_per_region):
            rows.append(dict(unit_id=f"{rid}_MUNI_{j+1:03d}",layer="municipal",region_id=rid,annual_budget_rub=c.annual_total_budget_rub*bs[2]*bw[i]*mw[j],annual_procurement_rub=c.annual_procurement_rub*ps[2]*pw[i]*mp[j],risk_multiplier=max(.5,min(1.9,r.lognormvariate(-.5*.25**2,.25)))))
    return rows

def _calc(c,geo,sampled=False,rng=None):
    vals=[];li={"federal":0,"regional":1,"municipal":2}
    for key,label,expo,loss,prev,base,bc,bias in RISKS:
        if sampled:
            L=rng.triangular(loss[0],loss[2],loss[1]);P=rng.triangular(prev[0],prev[2],prev[1]);B=rng.triangular(base[0],base[2],base[1]);C=max(B,rng.triangular(bc[0],bc[2],bc[1]))
        else:L,P,B,C=loss[1],prev[1],base[1],bc[1]
        latent=bl=cl=0.
        for u in geo:
            e=u["annual_procurement_rub"] if expo=="procurement" else u["annual_budget_rub"]
            raw=e*L*u["risk_multiplier"]*bias[li[u["layer"]]];latent+=raw;bl+=raw*P*B;cl+=raw*P*C
        vals.append(dict(key=key,label=label,exposure=expo,latent_loss_rub=latent,baseline_prevented_rub=bl,blockchain_prevented_rub=cl,incremental_benefit_rub=max(0,cl-bl)))
    cap=c.annual_total_budget_rub*c.max_incremental_benefit_share_of_budget;tot=sum(x["incremental_benefit_rub"] for x in vals);s=min(1,cap/tot) if tot else 1
    for x in vals:x["incremental_benefit_rub"]*=s
    return vals

def expected_benefit_by_category(c:StateROIConfig,geography=None):
    return _calc(c,geography or build_geography(c))

def _cash(c,benefit,cost_scale=1.,benefit_scale=1.):
    out=[];cap=(c.upfront_platform_cost_rub+c.integration_rollout_cost_rub)*cost_scale
    for y in range(c.horizon_years+1):
        if y==0:b=0;cost=cap*c.capex_year0_share
        else:
            ad=c.adoption_ramp[min(y-1,len(c.adoption_ramp)-1)];b=benefit*benefit_scale*ad*(1+c.real_budget_growth)**(y-1)
            cost=(cap*(1-c.capex_year0_share) if y==1 else 0)+(c.annual_opex_rub+c.annual_security_audit_rub)*cost_scale
        out.append(dict(year=y,benefit_rub=b,cost_rub=cost,net_cashflow_rub=b-cost))
    return out

def _financial(c,benefit,cost_scale=1.,benefit_scale=1.):
    rows=_cash(c,benefit,cost_scale,benefit_scale);cf=[x["net_cashflow_rub"] for x in rows];pvb=_npv([x["benefit_rub"] for x in rows],c.real_discount_rate);pvc=_npv([x["cost_rub"] for x in rows],c.real_discount_rate)
    return dict(npv_rub=_npv(cf,c.real_discount_rate),benefit_cost_ratio=pvb/pvc if pvc else None,payback_year=_payback(cf),irr=_irr(cf),cashflows=rows)

def simulate_state_roi(c:StateROIConfig|None=None):
    c=c or StateROIConfig();geo=build_geography(c);cats=_calc(c,geo);benefit=sum(x["incremental_benefit_rub"] for x in cats);mode={"annual_full_adoption_benefit_rub":benefit,**_financial(c,benefit)}
    rng=random.Random(c.seed+991);runs=[];cat_samples={x[0]:[] for x in RISKS}
    for _ in range(c.monte_carlo_runs):
        cs=_calc(c,geo,True,rng);b=sum(x["incremental_benefit_rub"] for x in cs)*rng.triangular(.78,1.05,.94);cost=rng.triangular(.85,1.30,1.0);f=_financial(c,b,cost);runs.append((b,f))
        for x in cs:cat_samples[x["key"]].append(x["incremental_benefit_rub"])
    def S(values):return dict(p10=_q(values,.1),p50=_q(values,.5),p90=_q(values,.9),mean=mean(values))
    npvs=[x[1]["npv_rub"] for x in runs];mcs=dict(runs=len(runs),npv_rub=S(npvs),annual_full_adoption_benefit_rub=S([x[0] for x in runs]),benefit_cost_ratio=S([x[1]["benefit_cost_ratio"] for x in runs]),payback_year=S([x[1]["payback_year"] for x in runs if x[1]["payback_year"] is not None]),irr=S([x[1]["irr"] for x in runs if x[1]["irr"] is not None]),probability_positive_npv=sum(x>0 for x in npvs)/len(npvs),benefit_by_category={k:S(v) for k,v in cat_samples.items()})
    layers=[];regs={};raw=[];idx={"federal":0,"regional":1,"municipal":2}
    for u in geo:
        b=0
        for _,_,expo,loss,prev,base,bc,bias in RISKS:
            e=u["annual_procurement_rub"] if expo=="procurement" else u["annual_budget_rub"];b+=e*loss[1]*u["risk_multiplier"]*bias[idx[u["layer"]]]*prev[1]*max(0,bc[1]-base[1])
        raw.append((u,b))
    sc=benefit/sum(b for _,b in raw)
    for layer in ("federal","regional","municipal"):
        us=[x for x in raw if x[0]["layer"]==layer];bud=sum(x[0]["annual_budget_rub"] for x in us);proc=sum(x[0]["annual_procurement_rub"] for x in us);bb=sum(x[1]*sc for x in us);layers.append(dict(layer=layer,annual_budget_rub=bud,annual_procurement_rub=proc,incremental_benefit_rub=bb,incremental_benefit_pct_of_budget=100*bb/bud))
    for u,b in raw:
        rid=u["region_id"]
        if rid:
            x=regs.setdefault(rid,dict(region_id=rid,annual_budget_rub=0.,annual_procurement_rub=0.,incremental_benefit_rub=0.,units=0));x["annual_budget_rub"]+=u["annual_budget_rub"];x["annual_procurement_rub"]+=u["annual_procurement_rub"];x["incremental_benefit_rub"]+=b*sc;x["units"]+=1
    regions=sorted(regs.values(),key=lambda x:(-x["incremental_benefit_rub"],x["region_id"]))
    for x in regions:x["benefit_pct_of_budget"]=100*x["incremental_benefit_rub"]/x["annual_budget_rub"]
    sensitivity=[]
    for bs in (.5,.75,1,1.25,1.5,2):
        for cs in (.75,1,1.25,1.5):sensitivity.append(dict(benefit_scale=bs,cost_scale=cs,**{k:v for k,v in _financial(c,benefit,cs,bs).items() if k!="cashflows"}))
    unit=_cash(c,1);pvfactor=_npv([x["benefit_rub"] for x in unit],c.real_discount_rate);pvcost=_npv([x["cost_rub"] for x in unit],c.real_discount_rate);be=pvcost/pvfactor
    return dict(schema_version=SCHEMA,notice=NOTICE,assumption_type="synthetic scenario; not an empirical estimate of actual Russian losses or savings",config=asdict(c),topology=dict(federal_units=1,regional_contours=c.regions,municipal_units=c.regions*c.municipalities_per_region,total_units=len(geo)),mode=mode,benefit_by_category=cats,benefit_by_layer=layers,regions=regions,sensitivity=sensitivity,monte_carlo=mcs,break_even=dict(npv_zero_full_adoption_benefit_rub=be,npv_zero_share_of_annual_total_budget=be/c.annual_total_budget_rub,npv_zero_share_of_annual_procurement=be/c.annual_procurement_rub,annual_opex_floor_rub=c.annual_opex_rub+c.annual_security_audit_rub,annual_full_adoption_benefit_rub_excluding_capex_recovery=c.annual_opex_rub+c.annual_security_audit_rub))

def write_simulation(output:Path,result:dict):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);(output/"STATE_ROI_RESULT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True),"utf-8")
    specs=(("annual_cashflows.csv",result["mode"]["cashflows"]),("benefit_by_category.csv",result["benefit_by_category"]),("benefit_by_layer.csv",result["benefit_by_layer"]),("regions.csv",result["regions"]),("sensitivity.csv",result["sensitivity"]))
    for name,rows in specs:
        if not rows:continue
        with (output/name).open("w",newline="",encoding="utf-8-sig") as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return {"output":output.as_posix(),"files":6}
