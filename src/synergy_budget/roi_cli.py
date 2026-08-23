from __future__ import annotations
import argparse,json
from pathlib import Path
from .roi_sim import StateROIConfig,simulate_state_roi,write_simulation

def build_parser():
    p=argparse.ArgumentParser(prog="synergy-budget-roi",description="Synthetic federal/regional/municipal blockchain-budget ROI simulator")
    p.add_argument("--output",default="data/mock/roi-v0.6");p.add_argument("--regions",type=int,default=89);p.add_argument("--municipalities-per-region",type=int,default=20)
    p.add_argument("--total-budget-rub",type=float,default=62_000_000_000_000.0);p.add_argument("--procurement-rub",type=float,default=13_600_000_000_000.0)
    p.add_argument("--horizon-years",type=int,default=10);p.add_argument("--runs",type=int,default=5000);p.add_argument("--seed",type=int,default=20260823);return p

def main():
    a=build_parser().parse_args();c=StateROIConfig(regions=a.regions,municipalities_per_region=a.municipalities_per_region,annual_total_budget_rub=a.total_budget_rub,annual_procurement_rub=a.procurement_rub,horizon_years=a.horizon_years,monte_carlo_runs=a.runs,seed=a.seed)
    r=simulate_state_roi(c);write_simulation(Path(a.output),r);print(json.dumps({"output":a.output,"mode":r["mode"],"monte_carlo":r["monte_carlo"],"break_even":r["break_even"]},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
