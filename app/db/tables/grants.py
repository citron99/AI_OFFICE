"""Short-lived capability grants issued to machine principals per step."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class CapabilityGrantRecord(Base):
    """One (principal × data scope) permission for one planned step.

    Written before the node runs and re-checked immediately before the agent
    touches the scope; expiry is enforced on read, never by deletion.
    """

    __tablename__ = "capability_grants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("gr"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    step_id: Mapped[str] = mapped_column(String(40), index=True)
    node_id: Mapped[str] = mapped_column(String(80))
    principal_id: Mapped[str] = mapped_column(String(40))
    data_scope: Mapped[str] = mapped_column(String(30))
    actions: Mapped[str] = mapped_column(String(400))  # comma-separated action ids
    policy_version: Mapped[str] = mapped_column(String(80))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
