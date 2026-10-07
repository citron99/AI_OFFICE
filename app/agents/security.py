from app.core.security import detections
from app.models.accounting import AccountingResult
from app.models.agent import Finding
from app.models.enums import AgentType, RiskLevel
from app.models.legal import LegalResult
from app.models.office import SecurityResult


class SecurityAgent:
    def execute(self, texts: list[str]) -> SecurityResult:
        counts: dict[str, int] = {}
        for text in texts:
            for kind, count in detections(text).items():
                counts[kind] = counts.get(kind, 0) + count
        result = SecurityResult(
            agent=AgentType.SECURITY,
            status="security_report",
            summary="Проверка признаков секретов и чувствительных данных.",
            detections=counts,
            warnings=[
                "RULE_BASED_PILOT: отсутствие совпадений не гарантирует отсутствие утечки.",
                "Внешняя передача и реальные платежи этим агентом не выполняются.",
            ],
        )
        result.findings = [
            Finding(
                code=f"SENSITIVE_{kind}",
                title=f"Обнаружен тип данных: {kind}",
                description=f"Совпадений: {count}. Значения не включены в отчёт.",
                risk_level=RiskLevel.CRITICAL
                if kind in {"PRIVATE_KEY", "API_KEY", "PASSWORD"}
                else RiskLevel.HIGH,
            )
            for kind, count in counts.items()
        ]
        return result

    def postflight(
        self,
        *,
        preflight: SecurityResult,
        accounting: AccountingResult | None,
        legal: LegalResult | None,
        requested_action: str,
    ) -> SecurityResult:
        """Re-check safe structured outputs before policy evaluation.

        Raw documents and model prose are deliberately excluded.  This check only
        receives control-relevant fields, so its persisted result cannot become a
        second disclosure channel for accounting or legal material.
        """
        control_flags: list[str] = []
        structured_values = [requested_action]
        if accounting:
            structured_values.extend(
                [
                    accounting.invoice.id if accounting.invoice else "",
                    accounting.counterparty.id if accounting.counterparty else "",
                    accounting.counterparty.relationship_status if accounting.counterparty else "",
                    *(finding.code for finding in accounting.findings),
                ]
            )
            if any(finding.code == "BANK_DETAILS_CHANGED" for finding in accounting.findings):
                control_flags.append("BANK_DETAILS_CHANGED")
            if accounting.counterparty and accounting.counterparty.relationship_status == "blocked":
                control_flags.append("COUNTERPARTY_BLOCKED")
        if legal:
            structured_values.extend([legal.status, *(finding.code for finding in legal.findings)])
            if legal.status in {"analysis_rejected", "analysis_unavailable", "analysis_blocked"}:
                control_flags.append("LEGAL_RESULT_UNAVAILABLE")

        scanned = self.execute(structured_values)
        counts = dict(preflight.detections)
        for kind, count in scanned.detections.items():
            counts[kind] = counts.get(kind, 0) + count
        result = SecurityResult(
            agent=AgentType.SECURITY,
            status="security_postflight_report",
            summary="Postflight validation of structured accounting and legal results.",
            detections=counts,
            control_flags=control_flags,
            warnings=[
                *preflight.warnings,
                "POSTFLIGHT_RULE_BASED: structured control fields were checked before policy.",
            ],
        )
        result.findings = [*preflight.findings, *scanned.findings]
        return result
