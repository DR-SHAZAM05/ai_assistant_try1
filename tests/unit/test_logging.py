from src.app.core.logging import _redact


def test_redact_removes_bot_api_path_token_from_http_log_message():
    raw = "HTTP Request: POST https://api.telegram.org/botnot-a-real-token/setMyCommands"

    sanitized = _redact(raw)

    assert "not-a-real-token" not in sanitized
    assert "[REDACTED_BOT_TOKEN]" in sanitized
