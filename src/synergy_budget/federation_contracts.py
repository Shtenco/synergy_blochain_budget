from __future__ import annotations

from dataclasses import asdict, dataclass, field


class BudgetContractError(ValueError):
    pass


@dataclass(frozen=True)
class BudgetPaymentAuthorization:
    authorization_id: str
    budget_entity: str
    contract_ref: str
    beneficiary: str
    asset: str
    amount: float
    purpose: str
    appropriation_ref: str
    delivery_evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise BudgetContractError("amount must be positive")
        if not self.appropriation_ref:
            raise BudgetContractError("appropriation_ref is required")
        if not self.contract_ref or not self.beneficiary:
            raise BudgetContractError("contract_ref and beneficiary are required")
        if not self.purpose:
            raise BudgetContractError("purpose is required")

    def as_payload(self) -> dict:
        payload = asdict(self)
        payload["delivery_evidence_refs"] = list(self.delivery_evidence_refs)
        return payload
