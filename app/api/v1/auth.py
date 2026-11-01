"""Authentication endpoints: refresh-token sessions and invitations (TZ 10.1)."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.auth import BusinessOwnerDependency
from app.api.dependencies import SessionDependency

# Local import of the session service keeps the module import graph flat.
router = APIRouter(prefix="/auth", tags=["authentication"])


def _sessions_service(settings: Any) -> Any:
    if not settings.session_secret:
        raise HTTPException(503, "SESSION_SECRET is not configured")
    return settings


class RefreshRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"refresh_token": "rt_01JZK4Q9T2XW8V5R3N6Y7B0CDEFGHIJKL"}]},
    )

    refresh_token: str = Field(
        min_length=16,
        max_length=200,
        description="Opaque token kept in memory by the SPA; never persisted to localStorage.",
    )


class LogoutRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"refresh_token": "rt_01JZK4Q9T2XW8V5R3N6Y7B0CDEFGHIJKL"}]},
    )

    refresh_token: str = Field(min_length=16, max_length=200)


class OidcSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "id_token": (
                        "eyJhbGciOiJSUzI1NiIsImtpZCI6ImdhdGV3YXksInR5cCI6IkpXVCJ9."
                        "…signature-omitted-in-docs…"
                    )
                }
            ]
        },
    )

    id_token: str = Field(
        min_length=8,
        max_length=8192,
        description="Verified OIDC assertion from the configured IdP.",
    )


@router.post("/oidc/session")
async def oidc_session(
    payload: OidcSessionRequest,
    session: SessionDependency,
    request: Request,
) -> dict[str, Any]:
    """Federated login: exchange a verified OIDC assertion for a session."""
    from app.services.sessions import mint_oidc_session

    return await mint_oidc_session(session, request.app.state.settings, payload.id_token)


class InvitationCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"email": "lawyer@office.example", "role": "lawyer"}]},
    )

    email: EmailStr
    role: str = Field(
        pattern=r"^(admin|auditor|accountant|lawyer|security)$",
        description="Server-assigned capability set for the invited principal.",
    )


class InvitationAccept(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"invitation_token": "inv_01JZK4Q9T2XW8V5R3N6Y7B0CDEFGH"}]},
    )

    invitation_token: str = Field(
        min_length=16,
        max_length=200,
        description="Single-use token returned by POST /api/v1/auth/invitations.",
    )


@router.post("/refresh")
async def refresh_session(
    payload: RefreshRequest,
    session: SessionDependency,
    request: Request,
) -> dict[str, Any]:
    """Rotate the refresh token and mint a fresh access credential."""
    from app.services.sessions import rotate_refresh_token

    access, new_refresh, user_id, role, refresh_expires_at = await rotate_refresh_token(
        session, settings=request.app.state.settings, raw=payload.refresh_token
    )
    return {
        "access_token": access,
        "refresh_token": new_refresh,
        "refresh_expires_at": refresh_expires_at.isoformat(),
        "user_id": user_id,
        "role": role,
    }


@router.post("/logout")
async def logout(
    payload: LogoutRequest,
    session: SessionDependency,
) -> dict[str, bool]:
    from app.services.sessions import revoke_refresh_token

    revoked = await revoke_refresh_token(session, raw=payload.refresh_token)
    return {"revoked": revoked}


@router.post("/invitations")
async def create_invitation(
    payload: InvitationCreate,
    principal: BusinessOwnerDependency,
    session: SessionDependency,
    request: Request,
) -> dict[str, Any]:
    """OWNER invites staff; role and company are server-assigned."""
    from app.services.sessions import create_invitation

    raw, expires_at = await create_invitation(
        session,
        company_id=principal.company_id,
        email=payload.email,
        role=payload.role,
        invited_by=principal.user_id,
    )
    await session.commit()
    return {"invitation_token": raw, "expires_at": expires_at.isoformat()}


@router.post("/invitations/accept")
async def accept_invitation(
    payload: InvitationAccept,
    session: SessionDependency,
    request: Request,
) -> dict[str, Any]:
    """Redeem the invitation; role and company come from the invitation itself.

    No prior access token is required: the invitation token IS the credential.
    """
    from app.services.sessions import accept_invitation as _accept

    return await _accept(
        session,
        settings=request.app.state.settings,
        raw=payload.invitation_token,
    )
