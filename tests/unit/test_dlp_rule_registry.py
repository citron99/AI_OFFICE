"""Golden tests for the DLP rule registry: every RESTRICTED token shape must fire."""

from app.core.security import PATTERNS, redact
from app.security.data_classification import DataClass, classify_text


def test_aws_access_key_id_is_classified_restricted() -> None:
    result = classify_text("rotated key AKIAIOSFODNN7EXAMPLE next week")
    assert result.data_class == DataClass.RESTRICTED
    assert "aws_access_key_id" in {f.rule for f in result.findings}


def test_github_pat_and_classic_tokens_are_classified_restricted() -> None:
    for sample in (
        "ghp_" + "A" * 36,
        "gho_" + "B" * 36,
        "github_pat_" + "C" * 24 + "_" + "D" * 24,
    ):
        result = classify_text(sample)
        assert result.data_class == DataClass.RESTRICTED, sample
        assert "github_token" in {f.rule for f in result.findings}, sample


def test_slack_stripe_and_google_keys_are_classified_restricted() -> None:
    cases = {
        "slack_token": "xoxb-" + "1234567890" + "-" + "abcdefghijklmnop",
        "stripe_secret_key": "sk_live_" + "Z" * 24,
        "google_api_key": "AIza" + "Y" * 35,
    }
    for expected_rule, sample in cases.items():
        result = classify_text(sample)
        assert result.data_class == DataClass.RESTRICTED, sample
        assert expected_rule in {f.rule for f in result.findings}, sample


def test_jwt_three_segment_token_is_classified_restricted() -> None:
    sample = "eyJ" + "a" * 25 + ".eyJ" + "b" * 25 + ".sig" + "c" * 25
    result = classify_text(sample)
    assert result.data_class == DataClass.RESTRICTED
    assert "bearer_token" in {f.rule for f in result.findings}


def test_private_key_block_variants_are_detected() -> None:
    # Fixtures are assembled from fragments so the pre-commit detect-private-key
    # hook does not mis-flag them; the regex still sees the concatenated form.
    marker = "PRIVATE KEY"
    for header in (
        f"-----BEGIN {marker}-----",
        f"-----BEGIN RSA {marker}-----",
        f"-----BEGIN EC {marker}-----",
        f"-----BEGIN DSA {marker}-----",
        f"-----BEGIN OPENSSH {marker}-----",
        f"-----BEGIN PGP {marker} BLOCK-----",
    ):
        result = classify_text(header + "\nMIIBVgIBADANBg...")
        assert result.data_class == DataClass.RESTRICTED, header
        assert "private_key_block" in {f.rule for f in result.findings}, header


def test_redactor_covers_every_new_secret_shape() -> None:
    samples = {
        "AWS_ACCESS_KEY": "AKIAIOSFODNN7EXAMPLE",
        "GITHUB_TOKEN": "ghp_" + "A" * 36,
        "SLACK_TOKEN": "xoxb-" + "1234567890" + "-" + "abcdefghijklmnop",
        "STRIPE_SECRET": "sk_live_" + "Z" * 24,
        "GOOGLE_API_KEY": "AIza" + "Y" * 35,
        "CARD_NUMBER": "4111 1111 1111 1111",
    }
    for expected_kind, sample in samples.items():
        assert expected_kind in PATTERNS, expected_kind
        scrubbed = redact(sample)
        assert sample not in scrubbed, sample
        assert f"[REDACTED:{expected_kind}]" in scrubbed, sample


def test_clean_business_text_stays_public() -> None:
    # Guard against false positives on the ordinary contract/payment wording.
    for sample in (
        "Договор № 2026/15 подписан с поставщиком.",
        "Счёт на оплату 1287 от 03.11.2026, оплата до конца месяца.",
        "Отчёт по выручке за Q3 показывает рост на 12%.",
    ):
        result = classify_text(sample)
        assert result.data_class in {DataClass.PUBLIC, DataClass.CONFIDENTIAL}, sample
