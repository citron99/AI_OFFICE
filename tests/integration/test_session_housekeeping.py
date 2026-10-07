"""Session housekeeping: expired refresh tokens and accepted invitations."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.db.tables.sessions import InvitationRecord, RefreshTokenRecord
from app.services.sessions import cleanup_expired_sessions, issue_refresh_token


async def test_cleanup_removes_expired_rows(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    now = datetime.now(UTC)
    async with factory() as session:
        # Expired token, active token, expired accepted invitation.
        await issue_refresh_token(session, user_id="u1", role="owner", company_id="c")
        expired = RefreshTokenRecord(
            token_hash="expired-hash",
            user_id="u2",
            company_id="c",
            role="owner",
            issued_at=now - timedelta(days=30),
            expires_at=now - timedelta(days=1),
        )
        session.add(expired)
        invitation = InvitationRecord(
            company_id="c",
            email="staff@example.com",
            role="auditor",
            token_hash="expired-invitation-hash",
            invited_by="u1",
            expires_at=now - timedelta(days=1),
            accepted_at=now - timedelta(days=2),
        )
        session.add(invitation)
        await session.commit()

    async with factory() as session:
        removed = await cleanup_expired_sessions(session)

    assert removed == 2
    async with factory() as session:
        remaining_tokens = (await session.scalars(select(RefreshTokenRecord))).all()
        # The active token stays; the expired one is gone.
        assert len(remaining_tokens) == 1
        assert remaining_tokens[0].user_id == "u1"
        remaining_invitations = (await session.scalars(select(InvitationRecord))).all()
        assert remaining_invitations == []


async def test_cleanup_keeps_pending_invitations(engine: AsyncEngine) -> None:
    """An expired but unaccepted invitation stays until the owner decides."""
    factory = create_session_factory(engine)
    now = datetime.now(UTC)
    async with factory() as session:
        session.add(
            InvitationRecord(
                company_id="c",
                email="pending@example.com",
                role="auditor",
                token_hash="pending-hash",
                invited_by="u1",
                expires_at=now - timedelta(days=1),
                accepted_at=None,
            )
        )
        await session.commit()

    async with factory() as session:
        removed = await cleanup_expired_sessions(session)
    assert removed == 0
    async with factory() as session:
        pending = (await session.scalars(select(InvitationRecord))).all()
        assert len(pending) == 1
