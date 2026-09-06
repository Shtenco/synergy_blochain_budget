import pytest

from synergy_budget.federation_contracts import BudgetContractError, BudgetPaymentAuthorization


def test_budget_payment_requires_appropriation():
    with pytest.raises(BudgetContractError):
        BudgetPaymentAuthorization(
            authorization_id="a1",
            budget_entity="region:1",
            contract_ref="procurement:1",
            beneficiary="supplier:1",
            asset="KZT",
            amount=1000,
            purpose="equipment",
            appropriation_ref="",
        )


def test_budget_payment_payload_preserves_evidence_refs():
    auth = BudgetPaymentAuthorization(
        authorization_id="a1",
        budget_entity="region:1",
        contract_ref="procurement:1",
        beneficiary="supplier:1",
        asset="KZT",
        amount=1000,
        purpose="equipment delivered",
        appropriation_ref="appropriation:1",
        delivery_evidence_refs=("delivery:hash",),
    )
    assert auth.as_payload()["delivery_evidence_refs"] == ["delivery:hash"]
