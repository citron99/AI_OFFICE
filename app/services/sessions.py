"""Session service: issue, rotate, revoke; invitations accept (TZ 10.1)."""

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.ids import new_id
from app.db.tables.companies import CompanyMembershipRecord, CompanyRecord
from app.db.tables.sessions import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    InvitationRecord,
    RefreshTokenRecord,
)
from app.db.tables.users import UserRecord

_ALLOWED_ROLES = frozenset({"owner", "admin", "auditor", "accountant", "lawyer", "security"})


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _session_secret(settings: Settings) -> bytes:
    secret = settings.session_secret
    if not secret:
        raise HTTPException(503, "SESSION_SECRET is not configured for token auth")
    return secret.encode()


def issue_access_token(
    *, settings: Settings, user_id: str, role: str, company_id: str, session_id: str
) -> tuple[str, datetime]:
    """Stateless signed access credential; the secret has no default value."""
    expires_at = datetime.now(UTC) + ACCESS_TOKEN_TTL
    payload = f"{expires_at.timestamp():.0f}|{session_id}|{user_id}|{role}|{company_id}"
    signature = hmac.new(_session_secret(settings), payload.encode(), hashlib.sha256).hexdigest()
    return f"v1.{payload}.{signature}", expires_at


def verify_access_token(settings: Settings, token: str) -> dict[str, str] | None:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        return None
    payload, signature = parts[1], parts[2]
    expected = hmac.new(_session_secret(settings), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        expires_ts, session_id, user_id, role, company_id = payload.split("|")
        expires_at = datetime.fromtimestamp(float(expires_ts), tz=UTC)
    except ValueError:
        return None
    if expires_at <= datetime.now(UTC):
        return None
    return {
        "user_id": user_id,
        "role": role,
        "company_id": company_id,
        "session_id": session_id,
    }


async def session_identity_is_active(
    session: AsyncSession, *, user_id: str, role: str, company_id: str
) -> bool:
    """The database, not a previously issued token, owns current access."""
    user = await session.get(UserRecord, user_id)
    company = await session.get(CompanyRecord, company_id)
    if user is None or user.status != "active" or company is None or company.status != "active":
        return False
    membership = await session.scalar(
        select(CompanyMembershipRecord).where(
            CompanyMembershipRecord.company_id == company_id,
            CompanyMembershipRecord.user_id == user_id,
        )
    )
    return membership is not None and membership.status == "active" and membership.role == role


async def issue_refresh_token(
    session: AsyncSession, *, user_id: str, role: str, company_id: str
) -> tuple[str, datetime]:
    raw = "rtk_" + secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + REFRESH_TOKEN_TTL
    session.add(
        RefreshTokenRecord(
            token_hash=_hash_token(raw),
            user_id=user_id,
            company_id=company_id,
            role=role,
            expires_at=expires_at,
        )
    )
    await session.flush()
    return raw, expires_at


async def rotate_refresh_token(
    session: AsyncSession, *, settings: Settings, raw: str
) -> tuple[str, str, str, str, datetime]:
    """Refresh-token rotation: the old token dies, a new pair is issued.

    Reuse of a rotated-out token revokes the whole chain (stolen-token
    detection) and fails closed.
    """
    now = datetime.now(UTC)
    record = await session.scalar(
        select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == _hash_token(raw))
    )
    if record is None:
        raise HTTPException(401, "Invalid refresh token")
    if record.rotated_to is not None:
        # Reuse after rotation: revoke the whole descendant chain. Chain links
        # store token hashes, so follow them by hash lookup, not by id.
        chain: str | None = record.rotated_to
        while chain:
            descendant = await session.scalar(
                select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == chain)
            )
            if descendant is None or descendant.revoked_at is not None:
                break
            descendant.revoked_at = now
            chain = descendant.rotated_to
        await session.commit()
        raise HTTPException(401, "Refresh token reuse detected; session revoked")
    if not record.active(now=now):
        raise HTTPException(401, "Refresh token expired or revoked")
    if not await session_identity_is_active(
        session, user_id=record.user_id, role=record.role, company_id=record.company_id
    ):
        raise HTTPException(401, "Session identity is no longer active")

    new_refresh, refresh_expires_at = await issue_refresh_token(
        session, user_id=record.user_id, role=record.role, company_id=record.company_id
    )
    new_record = await session.scalar(
        select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == _hash_token(new_refresh))
    )
    if new_record is None:
        raise RuntimeError("Rotated refresh session was not persisted")
    record.rotated_to = new_record.token_hash
    record.revoked_at = now
    access, _ = issue_access_token(
        settings=settings,
        user_id=record.user_id,
        role=record.role,
        company_id=record.company_id,
        session_id=new_record.id,
    )
    await session.commit()
    return access, new_refresh, record.user_id, record.role, refresh_expires_at


async def revoke_refresh_token(session: AsyncSession, *, raw: str) -> bool:
    record = await session.scalar(
        select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == _hash_token(raw))
    )
    if record is None or record.revoked_at is not None:
        return False
    record.revoked_at = datetime.now(UTC)
    await session.commit()
    return True


async def create_invitation(
    session: AsyncSession,
    *,
    company_id: str,
    email: str,
    role: str,
    invited_by: str,
) -> tuple[str, datetime]:
    """ROLE and company are fixed by the inviter; the invitee cannot choose."""
    if role not in _ALLOWED_ROLES or role == "owner":
        # OWNER is provisioned per company by deployment, never by invitation.
        raise HTTPException(422, "Invitation role must be a non-owner staff or admin role")
    raw = "inv_" + secrets.token_urlsafe(32)
    from app.db.tables.sessions import INVITATION_TTL

    expires_at = datetime.now(UTC) + INVITATION_TTL
    session.add(
        InvitationRecord(
            company_id=company_id,
            email=email.lower(),
            role=role,
            token_hash=_hash_token(raw),
            invited_by=invited_by,
            expires_at=expires_at,
        )
    )
    await session.flush()
    return raw, expires_at


async def accept_invitation(
    session: AsyncSession,
    *,
    settings: Settings,
    raw: str,
) -> dict[str, str]:
    """Exchange an invitation for an immediately usable session."""

    now = datetime.now(UTC)
    invitation = await session.scalar(
        select(InvitationRecord).where(InvitationRecord.token_hash == _hash_token(raw))
    )
    if invitation is None or invitation.accepted_at is not None:
        raise HTTPException(404, "Invitation not found")
    expires_at = (
        invitation.expires_at
        if invitation.expires_at.tzinfo
        else invitation.expires_at.replace(tzinfo=UTC)
    )
    if expires_at <= now:
        raise HTTPException(410, "Invitation expired")
    company = await session.get(CompanyRecord, invitation.company_id)
    if company is None or company.status != "active":
        raise HTTPException(403, "Invitation company is disabled")

    user = await session.scalar(select(UserRecord).where(UserRecord.email == invitation.email))
    if user is None:
        user = UserRecord(
            id=new_id("usr"),
            email=invitation.email,
            display_name=invitation.email.split("@")[0],
            role=invitation.role,
            status="active",
        )
        session.add(user)
        await session.flush()
    elif user.status != "active":
        raise HTTPException(403, "Invitation user is disabled")
    membership = await session.scalar(
        select(CompanyMembershipRecord).where(
            CompanyMembershipRecord.company_id == invitation.company_id,
            CompanyMembershipRecord.user_id == user.id,
        )
    )
    if membership is None:
        session.add(
            CompanyMembershipRecord(
                company_id=invitation.company_id,
                user_id=user.id,
                role=invitation.role,
            )
        )
    elif membership.status != "active":
        raise HTTPException(403, "Invitation membership is disabled")
    else:
        membership.role = invitation.role
    invitation.accepted_at = now
    refresh, refresh_expires_at = await issue_refresh_token(
        session, user_id=user.id, role=invitation.role, company_id=invitation.company_id
    )
    refresh_record = await session.scalar(
        select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == _hash_token(refresh))
    )
    if refresh_record is None:  # defensive: the row was flushed by issue_refresh_token
        raise RuntimeError("Refresh session was not persisted")
    access, access_expires_at = issue_access_token(
        settings=settings,
        user_id=user.id,
        role=invitation.role,
        company_id=invitation.company_id,
        session_id=refresh_record.id,
    )
    await session.commit()
    return {
        "access_token": access,
        "access_expires_at": access_expires_at.isoformat(),
        "refresh_token": refresh,
        "refresh_expires_at": refresh_expires_at.isoformat(),
        "user_id": user.id,
        "role": invitation.role,
        "company_id": invitation.company_id,
    }


async def cleanup_expired_sessions(session: AsyncSession, *, batch_limit: int = 200) -> int:
    """Bounded housekeeping: drop expired refresh tokens and invitations.

    Expired rows are inactive by rule (active()/expiry checks), so removal is
    a storage-hygiene operation, never an access change.
    """
    now = datetime.now(UTC)
    removed = 0
    expired_tokens: Sequence[RefreshTokenRecord] = (
        await session.scalars(
            select(RefreshTokenRecord)
            .where(RefreshTokenRecord.expires_at <= now)
            .limit(batch_limit)
        )
    ).all()
    for record in expired_tokens:
        await session.delete(record)
        removed += 1
    expired_invitations: Sequence[InvitationRecord] = (
        await session.scalars(
            select(InvitationRecord)
            .where(InvitationRecord.expires_at <= now, InvitationRecord.accepted_at.isnot(None))
            .limit(batch_limit)
        )
    ).all()
    for invitation in expired_invitations:
        await session.delete(invitation)
        removed += 1
    if removed:
        await session.commit()
    return removed


class OidcIdentityError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(401, detail)


def _user_info_client_factory(transport: Any) -> Callable[[], Any]:
    """Test seam: production uses a fresh httpx.AsyncClient per call."""

    def factory() -> Any:
        import httpx

        return httpx.AsyncClient(transport=transport) if transport else httpx.AsyncClient()

    return factory


async def verify_oidc_identity(
    settings: Settings,
    id_token: str,
    *,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, str]:
    """Assert identity via the issuer's userinfo endpoint (OIDC Core 5.3).

    The IdP answers the authorization question; this server only maps
    verified claims onto an internal session. No local password, no
    self-service roles: role/company come from server-side claim mapping.
    """
    if not settings.oidc_issuer_url:
        raise OidcIdentityError("OIDC_ISSUER_URL is not configured")
    factory = client_factory or _user_info_client_factory(None)
    userinfo_url = settings.oidc_issuer_url.rstrip("/") + "/userinfo"
    try:
        async with factory() as client:
            response = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {id_token}"},
                timeout=10,
            )
    except Exception as error:  # network/transport failures fail closed
        raise OidcIdentityError("OIDC issuer is unreachable") from error
    if response.status_code != 200:
        raise OidcIdentityError("OIDC token rejected by the issuer")
    claims: dict[str, Any] = response.json()
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise OidcIdentityError("OIDC claims lack a subject")
    role = claims.get(settings.oidc_role_claim) or settings.oidc_default_role
    allowed = {"owner", "admin", "auditor", "accountant", "lawyer", "security"}
    if role not in allowed:
        role = settings.oidc_default_role
    company = claims.get(settings.oidc_company_claim) or "comp_demo"
    if not isinstance(company, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", company):
        raise OidcIdentityError("OIDC company claim is invalid")
    email = claims.get("email", "")
    if not isinstance(email, str):
        raise OidcIdentityError("OIDC email claim is invalid")
    # Email is a contact field, never the identity key. Unverified addresses
    # are not persisted, so they cannot collide with a real local account.
    if claims.get("email_verified") is not True:
        email = ""
    subject_digest = hashlib.sha256(f"{settings.oidc_issuer_url}\0{sub}".encode()).hexdigest()[:32]
    return {
        "user_id": f"oidc_{subject_digest}",
        "email": email,
        "role": role,
        "company_id": company,
    }


async def mint_oidc_session(
    session: AsyncSession,
    settings: Settings,
    id_token: str,
    *,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, str]:
    """Federated login: verify the IdP assertion, then issue a local session."""
    identity = await verify_oidc_identity(settings, id_token, client_factory=client_factory)
    user = await session.get(UserRecord, identity["user_id"])
    email = identity["email"] or f"{identity['user_id']}@oidc.invalid"
    if user is None:
        if await session.scalar(select(UserRecord).where(UserRecord.email == email)) is not None:
            raise OidcIdentityError("OIDC email is already bound to another identity")
        user = UserRecord(
            id=identity["user_id"],
            email=email,
            display_name=identity["email"] or identity["user_id"],
            role=identity["role"],
            status="active",
        )
        session.add(user)
        await session.flush()
    elif user.status != "active":
        raise OidcIdentityError("OIDC user is disabled")
    elif identity["email"] and user.email != identity["email"]:
        if await session.scalar(select(UserRecord).where(UserRecord.email == email)) is not None:
            raise OidcIdentityError("OIDC email is already bound to another identity")
        user.email = email
        user.display_name = email
    company = await session.get(CompanyRecord, identity["company_id"])
    if company is None:
        session.add(CompanyRecord(id=identity["company_id"], name="OIDC Company"))
        await session.flush()
    elif company.status != "active":
        raise OidcIdentityError("OIDC company is disabled")
    membership = await session.scalar(
        select(CompanyMembershipRecord).where(
            CompanyMembershipRecord.company_id == identity["company_id"],
            CompanyMembershipRecord.user_id == user.id,
        )
    )
    if membership is None:
        session.add(
            CompanyMembershipRecord(
                company_id=identity["company_id"],
                user_id=user.id,
                role=identity["role"],
            )
        )
    elif membership.status != "active":
        raise OidcIdentityError("OIDC membership is disabled")
    else:
        # Claims are supplied by the configured IdP; update an active local
        # membership when its mapped role changes.
        membership.role = identity["role"]
    refresh, refresh_expires_at = await issue_refresh_token(
        session, user_id=user.id, role=identity["role"], company_id=identity["company_id"]
    )
    refresh_record = await session.scalar(
        select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == _hash_token(refresh))
    )
    if refresh_record is None:
        raise RuntimeError("OIDC refresh session was not persisted")
    access, _ = issue_access_token(
        settings=settings,
        user_id=user.id,
        role=identity["role"],
        company_id=identity["company_id"],
        session_id=refresh_record.id,
    )
    await session.commit()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "refresh_expires_at": refresh_expires_at.isoformat(),
        "user_id": user.id,
        "role": identity["role"],
        "company_id": identity["company_id"],
    }
