"""DailyOwnerDigest: the accepted result of the daily pilot process (TZ 6.2).

Aggregates the outputs of every daily-graph node into one owner-facing
summary: watermark, available cash, day flows, receivables aging, top
non-payment risks with explanations and recommended actions, and anomaly
counts. Fully deterministic, decimal-exact, no LLM.

The numbers are owned by the domain agents: cash flows and anomaly counts
come from the accountant's snapshot output, receivables aging and risks
from the receivable_risk output. The fallback paths below exist only for
standalone use and delegate to AccountantAgent — the digest never
recomputes domain logic itself.
"""

from datetime import date
from decimal import Decimal

from app.accounting.provider import AccountingProvider
from app.models.accounting import AccountingResult
from app.models.digest import DailyOwnerDigest, NonpaymentRisk
from app.models.enums import AgentType

DIGEST_VERSION = "daily_owner_digest_v1"

_EMPTY_RISKS: list[NonpaymentRisk] = []


def build_daily_digest(
    provider: AccountingProvider,
    *,
    as_of: date,
    snapshot: AccountingResult | None = None,
    cash: AccountingResult | None = None,
    receivables: AccountingResult | None = None,
) -> DailyOwnerDigest:
    """Aggregate confirmed node outputs into the owner summary.

    ``snapshot``, ``cash`` and ``receivables`` are the executed node outputs
    (accounting_snapshot / cash_control / receivable_risk). Absent outputs
    are computed through AccountantAgent — the single owner of the logic.
    """

    from app.agents.accountant import AccountantAgent

    watermark = provider.get_sync_watermark()
    balances = provider.list_accounts()
    cash_available = sum((b.amount for b in balances), Decimal("0"))

    agent = AccountantAgent(provider)
    invoices = [i for i in provider.list_invoices() if i.issued_on <= as_of]
    invoice_count = len(invoices)

    # Cash flows: cash_control output first, then the snapshot, then the agent.
    flows = cash or snapshot
    if flows is not None:
        cash_in = flows.cash_in
        cash_out = flows.cash_out
        net_cash_flow = flows.net_cash_flow
    else:
        aggregated = agent.execute(invoice_id=None, as_of=as_of)
        cash_in = aggregated.cash_in
        cash_out = aggregated.cash_out
        net_cash_flow = aggregated.net_cash_flow

    # Anomalies: the snapshot node owns dataset-level anomaly counting.
    if snapshot is not None:
        anomaly_count = snapshot.anomaly_count
    else:
        anomaly_count = agent.execute(invoice_id=None, as_of=as_of).anomaly_count

    # Receivables: the receivable_risk output owns aging and risks.
    if receivables is not None:
        expected_receipts = receivables.expected_receipts
        receivable_total = receivables.receivable_total
        receivable_aging = dict(receivables.receivable_aging)
        top_risks = list(receivables.nonpayment_risks)
    else:
        report = agent.analyze_receivables(as_of=as_of)
        expected_receipts = report.expected_receipts
        receivable_total = report.receivable_total
        receivable_aging = dict(report.receivable_aging)
        top_risks = list(report.nonpayment_risks)

    return DailyOwnerDigest(
        agent=AgentType.ORCHESTRATOR,
        status="daily_digest",
        summary="Ежедневная сводка: деньги, дебиторка, обязательства и риски неплатежей.",
        warnings=[
            "SYNTHETIC_DATA_ONLY: не данные реальной компании.",
        ],
        digest_date=as_of,
        watermark=f"{watermark.dataset_version} @ {watermark.generated_at.isoformat()}",
        cash_available=str(cash_available),
        cash_in=str(cash_in),
        cash_out=str(cash_out),
        net_cash_flow=str(net_cash_flow),
        expected_receipts=expected_receipts,
        receivable_total=str(receivable_total),
        receivable_aging={k: str(v) for k, v in sorted(receivable_aging.items())},
        top_nonpayment_risks=top_risks,
        anomaly_count=anomaly_count,
        invoice_count=invoice_count,
    )
