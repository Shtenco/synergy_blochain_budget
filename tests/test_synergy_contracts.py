from synergy_budget.models import BudgetRecord
from synergy_budget.synergy_contracts import CONTRACT_ID, budget_proof_payload

def test_budget_proof_is_provenance_not_accounting():
    r=BudgetRecord(
        record_type="appropriation",budget_year=2026,amount_kopecks=10000,currency="RUB",
        dimensions={"program":"demo"},source={"url":"fixture:test"}
    ).payload()
    p=budget_proof_payload(dataset_id="RU-DEMO",snapshot_id="s1",records=[r],as_of="2026-09-29")
    assert CONTRACT_ID=="synergy.economy.budget-proof/v1"
    assert p["record_count"]==1
    assert p["canonical_accounting_authority"] is False
