from __future__ import annotations

from app.audit.redaction import REDACTED, SecretRedactor


def test_redacts_sensitive_mapping_keys_recursively() -> None:
    redactor = SecretRedactor()

    result = redactor.redact(
        {
            "api_key": "sk-proj-abcdef1234567890",
            "nested": {
                "PASSWORD": "secret-password",
                "safe": "visible",
            },
            "items": [{"access_token": "token-value"}],
        }
    )

    assert result == {
        "api_key": REDACTED,
        "nested": {
            "PASSWORD": REDACTED,
            "safe": "visible",
        },
        "items": [{"access_token": REDACTED}],
    }


def test_redacts_bearer_token_inside_free_text() -> None:
    result = SecretRedactor().redact(
        "Authorization: Bearer abc.def.ghi"
    )

    assert result == "Authorization: Bearer [REDACTED]"


def test_redacts_assignment_style_secrets_inside_text() -> None:
    text = (
        "OPENAI_API_KEY=sk-proj-1234567890 "
        "password='very-secret' "
        "TELEGRAM_BOT_TOKEN=123456789:AAExampleTokenValue"
    )

    result = SecretRedactor().redact(text)

    assert "sk-proj-1234567890" not in result
    assert "very-secret" not in result
    assert "AAExampleTokenValue" not in result
    assert result.count(REDACTED) == 3


def test_redacts_sensitive_url_query_parameters() -> None:
    result = SecretRedactor().redact(
        "https://example.test/callback?"
        "token=abc123&next=/home&api_key=xyz789"
    )

    assert "abc123" not in result
    assert "xyz789" not in result
    assert "next=/home" in result


def test_redacts_common_provider_key_shapes() -> None:
    redactor = SecretRedactor()
    samples = (
        "sk-proj-1234567890abcdef",
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
        "xoxb-1234567890-abcdefghijklmnop",
        "123456789:AAExampleTelegramBotTokenValue",
    )

    for sample in samples:
        assert redactor.redact(sample) == REDACTED


def test_does_not_redact_normal_business_text() -> None:
    text = (
        "The token budget is 12000 and the password policy "
        "requires 16 characters."
    )

    assert SecretRedactor().redact(text) == text


def test_preserves_non_secret_scalar_types() -> None:
    payload = {
        "count": 3,
        "enabled": True,
        "ratio": 0.5,
        "nothing": None,
    }

    assert SecretRedactor().redact(payload) == payload


def test_redacted_value_is_idempotent() -> None:
    redactor = SecretRedactor()

    assert redactor.redact(REDACTED) == REDACTED
