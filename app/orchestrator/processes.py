"""Built-in, server-owned process definitions for the local pilot."""

from decimal import Decimal
from typing import Any

from app.models.enums import AgentType, RiskLevel
from app.models.process import ProcessDefinition
from app.orchestrator.contracts import (
    ProcessDefinitionV2,
    ProcessNodeSpec,
    RunBudget,
)
from app.orchestrator.passport import ProcessDefinitionV3


def office_process_v2(owner_id: str) -> ProcessDefinitionV2:
    """The default money-and-risk review process; it never performs payments."""

    return ProcessDefinitionV2(
        id="office_review",
        title="Проверка задачи AI-офисом",
        result_owner_id=owner_id,
        acceptance_checks=(
            "Проверены основания и ограничения результата",
            "Расхождения и недостающие сведения явно указаны",
            "Принятие результата не разрешает финансовые действия",
        ),
        nodes=(
            ProcessNodeSpec(
                id="accounting_snapshot",
                agent=AgentType.ACCOUNTANT,
                action="accountant_pilot",
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="AccountingResult",
            ),
            ProcessNodeSpec(
                id="security_preflight",
                agent=AgentType.SECURITY,
                action="security_preflight",
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="SecurityResult",
            ),
            ProcessNodeSpec(
                id="legal_review",
                agent=AgentType.LAWYER,
                action="lawyer_pilot",
                depends_on=("security_preflight",),
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="LegalResult",
                estimated_llm_calls=1,
                estimated_cost_rub=Decimal("5.00"),
            ),
            ProcessNodeSpec(
                id="security_postflight",
                agent=AgentType.SECURITY,
                action="security_postflight",
                depends_on=("accounting_snapshot", "security_preflight", "legal_review"),
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="SecurityResult",
            ),
        ),
        run_budget=RunBudget(),
    )


def daily_cash_and_receivable_risk_process(owner_id: str) -> ProcessDefinitionV2:
    """The first repeatable owner process: cash and non-payment risk."""

    return ProcessDefinitionV2(
        id="daily_cash_and_receivable_risk",
        title="Ежедневный контроль денег и рисков неплатежей",
        result_owner_id=owner_id,
        acceptance_checks=(
            "Снимок бухгалтерских данных привязан к дате контроля",
            "Денежный поток и просроченная дебиторская задолженность проверены отдельно",
            "Результат не создаёт платёж и требует review владельца",
        ),
        nodes=(
            ProcessNodeSpec(
                id="accounting_snapshot",
                agent=AgentType.ACCOUNTANT,
                action="accounting_snapshot",
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="AccountingResult",
            ),
            ProcessNodeSpec(
                id="cash_control",
                agent=AgentType.ACCOUNTANT,
                action="cash_control",
                depends_on=("accounting_snapshot",),
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="AccountingResult",
            ),
            ProcessNodeSpec(
                id="receivable_risk",
                agent=AgentType.ACCOUNTANT,
                action="receivable_risk",
                depends_on=("accounting_snapshot",),
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="AccountingResult",
            ),
            ProcessNodeSpec(
                id="security_preflight",
                agent=AgentType.SECURITY,
                action="security_preflight",
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="SecurityResult",
            ),
            ProcessNodeSpec(
                id="security_postflight",
                agent=AgentType.SECURITY,
                action="security_postflight",
                depends_on=("cash_control", "receivable_risk", "security_preflight"),
                risk_level=RiskLevel.MEDIUM,
                expected_output_schema="SecurityResult",
            ),
        ),
        run_budget=RunBudget(max_steps=8, max_llm_calls=0, max_cost_rub=Decimal("0")),
    )


def process_for_task(process_id: str, owner_id: str) -> ProcessDefinitionV2 | ProcessDefinitionV3:
    """V3 passports are the executed contract; V2 remains the fallback graph."""
    from app.orchestrator.passport import passport_for

    passport = passport_for(process_id)
    if passport is not None:
        return passport.model_copy(update={"result_owner_id": owner_id})
    if process_id == "daily_cash_and_receivable_risk":
        return daily_cash_and_receivable_risk_process(owner_id)
    return office_process_v2(owner_id)


def process_from_snapshot(
    snapshot: dict[str, Any],
) -> ProcessDefinition | ProcessDefinitionV2 | ProcessDefinitionV3:
    """Load both historical V1 snapshots and the executable V2 contract."""

    if snapshot.get("version") == 3:
        return ProcessDefinitionV3.model_validate(snapshot)
    if snapshot.get("version") == 2:
        return ProcessDefinitionV2.model_validate(snapshot)
    return ProcessDefinition.model_validate(snapshot)
