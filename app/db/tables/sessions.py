"""Durable sessions: refresh tokens, invitations, revocation (TZ 10.1).

- Access credentials stay short-lived stateless tokens (HMAC-signed, with an
  expiry and a session binding) - no secret default anywhere.
- Refresh tokens are stored server-side, hashed, rotatable and revocable.
- Invitations: a user is created by invitation; role and company_id are
  assigned by the server, never self-service (TZ 10.1).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=14)
INVITATION_TTL = timedelta(days=7)


class RefreshTokenRecord(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rtk"))
    # SHA-256 of the bearer value; the raw token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(30))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Rotation chain: a reused rotated-out token revokes the whole chain.
    rotated_to: Mapped[str | None] = mapped_column(String(40), nullable=True)

    def expired(self, *, now: datetime) -> bool:
        moment = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        return moment <= now

    def active(self, *, now: datetime) -> bool:
        return self.revoked_at is None and not self.expired(now=now)


class InvitationRecord(Base):
    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("company_id", "email", name="uq_invitation_company_email"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("inv"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    # Server-assigned: the invite itself never lets the invitee pick a role.
    role: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
