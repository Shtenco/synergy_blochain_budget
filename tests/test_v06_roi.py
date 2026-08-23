from pathlib import Path
from synergy_budget.roi_sim import StateROIConfig,build_geography,expected_benefit_by_category,simulate_state_roi,write_simulation

def test_topology_and_spend_sums():
    c=StateROIConfig(monte_carlo_runs=10);g=build_geography(c)
    assert len(g)==1+89+89*20
    assert abs(sum(x['annual_budget_rub'] for x in g)-c.annual_total_budget_rub)<2
    assert abs(sum(x['annual_procurement_rub'] for x in g)-c.annual_procurement_rub)<2
    assert all(x['annual_procurement_rub']<=x['annual_budget_rub'] for x in g)

def test_benefit_does_not_exceed_latent():
    for r in expected_benefit_by_category(StateROIConfig(monte_carlo_runs=10)): assert 0<=r['incremental_benefit_rub']<=r['latent_loss_rub']

def test_deterministic():
    c=StateROIConfig(monte_carlo_runs=25,seed=123);a=simulate_state_roi(c);b=simulate_state_roi(c)
    assert a['mode']==b['mode'] and a['monte_carlo']==b['monte_carlo']

def test_positive_mode_case_and_mc_probability():
    r=simulate_state_roi(StateROIConfig(monte_carlo_runs=30))
    assert r['mode']['annual_full_adoption_benefit_rub']>0 and r['mode']['benefit_cost_ratio']>1
    assert 0<=r['monte_carlo']['probability_positive_npv']<=1

def test_break_even_is_small_share():
    r=simulate_state_roi(StateROIConfig(monte_carlo_runs=5));assert 0<r['break_even']['npv_zero_share_of_annual_total_budget']<.001

def test_region_count_without_real_region_names():
    r=simulate_state_roi(StateROIConfig(monte_carlo_runs=5));assert len(r['regions'])==89 and all(x['region_id'].startswith('REGION_') and x['units']==21 for x in r['regions'])

def test_write(tmp_path:Path):
    r=simulate_state_roi(StateROIConfig(monte_carlo_runs=5));write_simulation(tmp_path,r)
    for name in ('STATE_ROI_RESULT.json','annual_cashflows.csv','benefit_by_category.csv','benefit_by_layer.csv','regions.csv','sensitivity.csv'): assert (tmp_path/name).exists()

def test_sensitivity_monotonic():
    r=simulate_state_roi(StateROIConfig(monte_carlo_runs=5));base=[x for x in r['sensitivity'] if x['cost_scale']==1]
    assert [x['npv_rub'] for x in base]==sorted(x['npv_rub'] for x in base)
    assert r['break_even']['npv_zero_full_adoption_benefit_rub']>r['break_even']['annual_full_adoption_benefit_rub_excluding_capex_recovery']
