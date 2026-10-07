"""Data Egress Gateway: classification, DLP redaction, route decisions (TZ 10.2-10.3)."""

from app.security.data_classification import DataClass, classify_text
from app.security.dlp import scan_and_redact
from app.security.egress_gateway import EgressRequest, evaluate_egress


def test_classifier_detects_restricted_secrets() -> None:
    result = classify_text("password=hunter2 and api_key: sk-live-123456")
    assert result.data_class == DataClass.RESTRICTED
    assert {f.rule for f in result.findings} >= {"password_assignment", "api_key_literal"}


def test_classifier_detects_personal_data() -> None:
    result = classify_text("Свяжитесь с ivanov@example.com или +7 912 345 67 89")
    assert result.data_class == DataClass.PERSONAL
    assert {f.rule for f in result.findings} >= {"email_address", "phone_number"}


def test_classifier_is_silent_on_public_text() -> None:
    result = classify_text("Оплата счета 5 от 12.05.2026 по основному договору поставки.")
    assert result.data_class == DataClass.PUBLIC
    assert result.findings == []


def test_gateway_blocks_restricted_and_confidential_to_external_llm() -> None:
    blocked = evaluate_egress(
        EgressRequest(
            company_id="comp_demo",
            route="external_llm",
            purpose="legal_analysis",
            content="password=top-secret-1",
        )
    )
    assert blocked.decision == "block"
    assert "RESTRICTED_DATA_EXTERNAL_LLM_FORBIDDEN" in blocked.reasons

    confidential = evaluate_egress(
        EgressRequest(
            company_id="comp_demo",
            route="external_llm",
            purpose="legal_analysis",
            content="Договор № 12/2026 и р/с 40702810500000012345",
        )
    )
    assert confidential.decision == "block"
    assert confidential.data_class in {DataClass.CONFIDENTIAL, DataClass.PERSONAL}


def test_gateway_allows_public_content_and_hashes_without_storing_it() -> None:
    verdict = evaluate_egress(
        EgressRequest(
            company_id="comp_demo",
            route="external_llm",
            purpose="legal_analysis",
            content="Simple public question about procedure.",
        )
    )
    assert verdict.decision == "allow"
    assert verdict.content_hash
    assert "password" not in verdict.model_dump_json()


def test_dlp_redaction_removes_secrets_and_keeps_public_text() -> None:
    scan = scan_and_redact("password=hunter2 must never leak")
    assert scan.redactions >= 1
    assert "hunter2" not in scan.redacted_text
    assert "[REDACTED]" in scan.redacted_text
    assert scan.classification.data_class == DataClass.RESTRICTED

    clean = scan_and_redact("Public summary without any secrets")
    assert clean.redactions == 0
    assert clean.redacted_text == "Public summary without any secrets"


async def test_real_provider_route_blocked_by_egress_gate(engine, tmp_path) -> None:
    """The egress gate runs before any real external provider call."""
    import httpx

    from app.config import Settings
    from app.db.session import create_session_factory
    from app.llm.base import LLMProvider, StructuredModel
    from app.main import create_app

    class NeverCalledProvider(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def healthcheck(self) -> bool:
            return True

        async def generate_structured(
            self, *, system_prompt: str, user_prompt: str, response_model: type[StructuredModel]
        ) -> StructuredModel:
            self.calls += 1
            raise AssertionError("provider must never be called through the gate")

    provider = NeverCalledProvider()

    # Inline use of the fixture body: run the app manually.
    settings = Settings(
        app_env="test",
        llm_provider="anthropic",
        anthropic_api_key="not-used-here",
        legal_analysis_enabled=True,
        upload_dir=tmp_path / "uploads",
        legal_analysis_timeout_seconds=0.1,
    )
    app = create_app(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        llm_provider=provider,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            uploaded = await c.post(
                "/api/v1/files",
                files={"file": ("synthetic.txt", b"Synthetic contract notice.", "text/plain")},
            )
            assert uploaded.status_code == 201, uploaded.text
            seeded = await c.post(
                "/api/v1/knowledge/sources",
                json={
                    "artifact_id": uploaded.json()["id"],
                    "title": "Synthetic rule",
                    "jurisdiction": "LV",
                    "document_type": "test_norm",
                    "authority": "Test only",
                    "version": "1",
                    "effective_from": "2026-01-01",
                    "status": "ACTIVE",
                },
            )
            assert seeded.status_code == 201, seeded.text
            response = await c.post(
                "/api/v1/tasks",
                json={
                    # A phone number is PERSONAL for the classifier but is not a
                    # security-secret detection, so only the egress gate stops it.
                    "message": "Клиент с телефоном +7 912 345 67 89 просит проверить договор",
                    "jurisdiction": "LV",
                    "effective_on": "2026-08-27",
                },
            )
            assert response.status_code == 201, response.text
            body = response.json()
            del body  # assertions below
    assert provider.calls == 0
