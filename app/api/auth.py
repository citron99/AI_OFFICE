import hashlib
import hmac
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.config import Settings

# TZ V2.1 section 10.5 RBAC: OWNER decides business actions; ADMIN operates the
# system; AUDITOR is read-only; domain roles stay inside their contour.
PrincipalRole = Literal["owner", "admin", "auditor", "accountant", "lawyer", "security", "service"]

_BUSINESS_WRITER_ROLES = frozenset({"owner", "admin", "accountant", "lawyer", "security"})


class Principal(BaseModel):
    user_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    role: PrincipalRole
    # TZ 10.1: role and company_id are assigned by the server, never by the user.
    company_id: str = Field(default="comp_demo", pattern=r"^[A-Za-z0-9_-]{1,40}$")
    # Bound to the refresh session; set by signed access tokens only.
    session_id: str | None = None


bearer = HTTPBearer(auto_error=False)


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    settings: Settings = request.app.state.settings
    if settings.auth_mode == "demo":
        return Principal(user_id="usr_demo_owner", role="owner")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    # Both local-token and OIDC modes use the same short-lived, locally
    # signed access credential after the initial identity exchange.
    if settings.auth_mode in {"token", "oidc"}:
        from app.db.tables.sessions import RefreshTokenRecord
        from app.services.sessions import session_identity_is_active, verify_access_token

        verified = verify_access_token(settings, credentials.credentials)
        if verified is None:
            raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
        principal = Principal.model_validate(verified)
        if principal.session_id is None:
            raise HTTPException(401, "Invalid session", headers={"WWW-Authenticate": "Bearer"})
        async with request.app.state.session_factory() as session:
            record = await session.get(RefreshTokenRecord, principal.session_id)
            active = (
                record is not None
                and record.active(now=datetime.now(UTC))
                and record.user_id == principal.user_id
                and record.role == principal.role
                and record.company_id == principal.company_id
                and await session_identity_is_active(
                    session,
                    user_id=principal.user_id,
                    role=principal.role,
                    company_id=principal.company_id,
                )
            )
        if not active:
            raise HTTPException(
                401, "Session no longer active", headers={"WWW-Authenticate": "Bearer"}
            )
        return principal
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    for expected, configured_principal in settings.auth_token_hashes.items():
        if hmac.compare_digest(digest, expected):
            # Server-assigned company boundary: default to comp_demo if not specified
            data = dict(configured_principal)
            data.setdefault("company_id", "comp_demo")
            return Principal.model_validate(data)
    raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})


PrincipalDependency = Annotated[Principal, Depends(current_principal)]


def require_writer(principal: PrincipalDependency) -> Principal:
    if principal.role not in _BUSINESS_WRITER_ROLES:
        raise HTTPException(403, "Read-only role")
    return principal


def require_system_admin(principal: PrincipalDependency) -> Principal:
    if principal.role != "admin":
        raise HTTPException(403, "System administrator role required")
    return principal


def require_business_owner(principal: PrincipalDependency) -> Principal:
    # APR-006: only the OWNER confirms monetary or legally significant actions.
    # A technical administrator never substitutes for the business owner.
    if principal.role != "owner":
        raise HTTPException(403, "Owner approval required")
    return principal


def require_reviewer(principal: PrincipalDependency) -> Principal:
    if principal.role not in {"owner", "admin", "accountant", "lawyer", "security"}:
        raise HTTPException(403, "Reviewer role required")
    return principal


def require_auditor(principal: PrincipalDependency) -> Principal:
    if principal.role not in {"owner", "admin", "auditor"}:
        raise HTTPException(403, "Auditor role required")
    return principal


WriterDependency = Annotated[Principal, Depends(require_writer)]
SystemAdminDependency = Annotated[Principal, Depends(require_system_admin)]
BusinessOwnerDependency = Annotated[Principal, Depends(require_business_owner)]
ReviewerDependency = Annotated[Principal, Depends(require_reviewer)]
AuditorDependency = Annotated[Principal, Depends(require_auditor)]

# Backwards-compatible alias used by older call sites.
OwnerDependency = BusinessOwnerDependency
