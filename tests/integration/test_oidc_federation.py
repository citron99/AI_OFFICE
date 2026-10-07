"""OIDC federation: IdP asserts identity, local session issued (TZ 10.1)."""

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import Settings
from app.db.session import create_session_factory
from app.main import create_app


class StubIssuer:
    """A minimal OIDC userinfo stub bound as an ASGI transport."""

    # Captured before any test patches httpx.AsyncClient, so building the
    # stub client never recurses into the patch.
    _real_client = httpx.AsyncClient

    def __init__(self, *, status: int = 200, claims: dict | None = None) -> None:
        self.status = status
        self.claims = claims or {
            "sub": "user-77",
            "email": "fed.owner@example.com",
            "email_verified": True,
            "office_role": "accountant",
            "office_company": "comp_fed",
        }
        self.app = FastAPI()

        @self.app.get("/userinfo")
        async def userinfo(request: Request) -> JSONResponse:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth == "Bearer wrong-token":
                return JSONResponse({"error": "invalid_token"}, status_code=401)
            return JSONResponse(self.claims, status_code=self.status)

    def client_factory(self):
        return self._real_client(
            transport=httpx.ASGITransport(app=self.app), base_url="https://idp.test"
        )


@pytest.fixture
async def oidc_app(engine: AsyncEngine, tmp_path):
    settings = Settings(
        app_env="test",
        auth_mode="oidc",
        session_secret="test-secret-only-for-pytest",
        oidc_issuer_url="https://idp.test",
        llm_provider="mock",
        embedding_provider="mock",
        upload_dir=tmp_path / "uploads",
    )
    application = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            yield client, application


async def test_oidc_assertion_exchanges_for_internal_session(
    oidc_app: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    from unittest.mock import patch

    from app.services.sessions import mint_oidc_session

    client, application = oidc_app
    issuer = StubIssuer()
    session_factory = create_session_factory(
        client._transport.app.state.engine  # noqa: SLF001
    )
    async with session_factory() as session:
        with patch("httpx.AsyncClient", side_effect=lambda **kw: issuer.client_factory()):
            minted = await mint_oidc_session(session, application.state.settings, "ok-token")
    assert minted["role"] == "accountant"  # server-side claim mapping
    assert minted["company_id"] == "comp_fed"
    assert minted["access_token"].startswith("v1.")

    # The internal access token carries the federated identity into the API.
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {minted['access_token']}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "accountant"

    # The refresh token rotates like any local session.
    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": minted["refresh_token"]},
        headers={"Authorization": f"Bearer {minted['access_token']}"},
    )
    assert refreshed.status_code == 200


async def test_oidc_rejected_token_fails_closed(
    oidc_app: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    from unittest.mock import patch

    from app.services.sessions import OidcIdentityError, mint_oidc_session

    client, application = oidc_app
    issuer = StubIssuer()
    session_factory = create_session_factory(
        client._transport.app.state.engine  # noqa: SLF001
    )
    async with session_factory() as session:
        with patch("httpx.AsyncClient", side_effect=lambda **kw: issuer.client_factory()):
            with pytest.raises(OidcIdentityError, match="rejected"):
                await mint_oidc_session(session, application.state.settings, "wrong-token")


async def test_oidc_unreachable_issuer_fails_closed(
    oidc_app: tuple[httpx.AsyncClient, FastAPI],
) -> None:

    from app.services.sessions import OidcIdentityError, mint_oidc_session

    client, application = oidc_app
    session_factory = create_session_factory(
        client._transport.app.state.engine  # noqa: SLF001
    )

    # Port 1 on loopback: connection refused, never a silent fallback.
    # A local settings copy pins the issuer to it so no real network name
    # (whose DNS can be hijacked on some machines) is involved.
    unreachable_settings = application.state.settings.model_copy(
        update={"oidc_issuer_url": "http://127.0.0.1:1"}
    )
    async with session_factory() as session:
        with pytest.raises(OidcIdentityError, match="unreachable"):
            await mint_oidc_session(session, unreachable_settings, "some-token")


async def test_oidc_subject_cannot_take_over_existing_email(
    oidc_app: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    from unittest.mock import patch

    from app.services.sessions import OidcIdentityError, mint_oidc_session

    client, application = oidc_app
    session_factory = create_session_factory(client._transport.app.state.engine)  # noqa: SLF001
    first_issuer = StubIssuer(
        claims={
            "sub": "subject-one",
            "email": "shared@example.com",
            "email_verified": True,
            "office_role": "accountant",
            "office_company": "comp_fed",
        }
    )
    second_issuer = StubIssuer(
        claims={
            "sub": "subject-two",
            "email": "shared@example.com",
            "email_verified": True,
            "office_role": "accountant",
            "office_company": "comp_fed",
        }
    )
    async with session_factory() as session:
        with patch("httpx.AsyncClient", side_effect=lambda **kw: first_issuer.client_factory()):
            first = await mint_oidc_session(session, application.state.settings, "ok-token")
    async with session_factory() as session:
        with patch("httpx.AsyncClient", side_effect=lambda **kw: second_issuer.client_factory()):
            with pytest.raises(OidcIdentityError, match="already bound"):
                await mint_oidc_session(session, application.state.settings, "ok-token")
    second_issuer.claims["email_verified"] = False
    async with session_factory() as session:
        with patch("httpx.AsyncClient", side_effect=lambda **kw: second_issuer.client_factory()):
            unverified = await mint_oidc_session(session, application.state.settings, "ok-token")
    assert unverified["user_id"] != first["user_id"]
    async with session_factory() as session:
        with patch("httpx.AsyncClient", side_effect=lambda **kw: first_issuer.client_factory()):
            repeated = await mint_oidc_session(session, application.state.settings, "ok-token")
    assert repeated["user_id"] == first["user_id"]
