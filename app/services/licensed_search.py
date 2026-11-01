"""The only path from an HTTP surface to a licensed legal provider (TZ 10.3).

Manual search and change-radar runs cross the perimeter without a task, so the
gateway verdict and the journal row are attached here instead of at each call
site: nothing above PUBLIC/INTERNAL reaches Consultant+, and every crossing or
refusal is recorded for the tenant that made it.
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables.consultant_plus import ConsultantPlusSearchEventRecord
from app.integrations.consultant_plus.exceptions import (
    ConsultantPlusUnavailableError,
    LicenseScopeExceededError,
)
from app.integrations.consultant_plus.factory import ConsultantPlusProviderLike
from app.integrations.consultant_plus.models import ConsultantPlusSearchResult
from app.security.egress_gateway import EgressRequest, EgressVerdict, evaluate_egress

LICENSED_ROUTE = "licensed_provider"


def licensed_egress_verdict(
    *, content: str, company_id: str, purpose: str, task_id: str | None = None
) -> EgressVerdict:
    """Run the gateway on text about to leave through the licensed channel."""
    return evaluate_egress(
        EgressRequest(
            company_id=company_id,
            task_id=task_id,
            route=LICENSED_ROUTE,
            purpose=purpose,
            content=content,
        )
    )


def _verdict_details(verdict: EgressVerdict, *, channel: str) -> dict[str, object]:
    """Decision evidence only: the query text is never copied into the journal."""
    return {
        "channel": channel,
        "decision": verdict.decision,
        "data_class": verdict.data_class.value,
        "reasons": verdict.reasons,
        "content_hash": verdict.content_hash,
        "policy_version": verdict.policy_version,
    }


async def guarded_licensed_search(
    session: AsyncSession,
    provider: ConsultantPlusProviderLike,
    *,
    query: str,
    jurisdiction: str,
    effective_on: date,
    company_id: str,
    owner_id: str,
    channel: str,
    limit: int = 5,
) -> list[ConsultantPlusSearchResult]:
    verdict = licensed_egress_verdict(
        content=query, company_id=company_id, purpose=f"licensed_search:{channel}"
    )
    if verdict.decision == "block":
        session.add(
            ConsultantPlusSearchEventRecord(
                company_id=company_id,
                owner_id=owner_id,
                outcome="egress_blocked",
                jurisdiction=jurisdiction,
                details=_verdict_details(verdict, channel=channel),
            )
        )
        await session.commit()
        raise HTTPException(403, f"EGRESS_BLOCKED: {','.join(verdict.reasons)}")

    try:
        results = provider.search(
            query=query, jurisdiction=jurisdiction, effective_on=effective_on, limit=limit
        )
    except ConsultantPlusUnavailableError as error:
        # Every permitted crossing (or attempt) must be journalled for LEG-008,
        # including provider failures: silently raising would erase the fact
        # that the query crossed the perimeter.
        session.add(
            ConsultantPlusSearchEventRecord(
                company_id=company_id,
                owner_id=owner_id,
                outcome="unavailable",
                jurisdiction=jurisdiction,
                details={**_verdict_details(verdict, channel=channel), "error": str(error)},
            )
        )
        await session.commit()
        raise HTTPException(503, str(error)) from None
    except LicenseScopeExceededError as error:
        session.add(
            ConsultantPlusSearchEventRecord(
                company_id=company_id,
                owner_id=owner_id,
                outcome="scope_exceeded",
                jurisdiction=jurisdiction,
                details={**_verdict_details(verdict, channel=channel), "error": str(error)},
            )
        )
        await session.commit()
        raise HTTPException(403, str(error)) from None

    if not results:
        # An allowed query with no hits still crossed the perimeter; recording
        # nothing would leave that crossing indistinguishable from no call.
        session.add(
            ConsultantPlusSearchEventRecord(
                company_id=company_id,
                owner_id=owner_id,
                outcome="not_found",
                jurisdiction=jurisdiction,
                details=_verdict_details(verdict, channel=channel),
            )
        )
    for item in results:
        session.add(
            ConsultantPlusSearchEventRecord(
                company_id=company_id,
                owner_id=owner_id,
                outcome="found",
                query_id=item.query_id,
                source_id=item.source_id,
                jurisdiction=item.jurisdiction,
                edition=item.edition,
                locator=item.locator,
                effective_from=item.effective_from,
                effective_to=item.effective_to,
                searched_at=item.retrieved_at,
                details={
                    "document_type": item.document_type,
                    "authority": item.authority,
                    **_verdict_details(verdict, channel=channel),
                },
            )
        )
    await session.commit()
    return results
