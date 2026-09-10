import pytest
from src.app.services.audit_service import AuditService
from src.app.core.retry import retry_async


@pytest.mark.asyncio
async def test_audit_service_logging_and_sanitization():
    service = AuditService()

    raw_prompt = "User prompt with api_key=unit-test-value and password=secret_password123"
    sanitized = service.sanitize_text(raw_prompt)
    assert "unit-test-value" not in sanitized
    assert "api_key=[REDACTED]" in sanitized
    assert "secret_password123" not in sanitized

    log = await service.log_event(
        user_request=raw_prompt,
        selected_tool="practice_query",
        model_used="gpt-4o-mini",
        status="success",
        execution_duration_ms=45.5,
    )

    assert log is not None
    assert log.user_request is None
    assert log.selected_tool == "practice_query"
    assert log.execution_duration_ms == 45.5


@pytest.mark.asyncio
async def test_audit_service_recent_logs():
    service = AuditService()
    await service.log_event(user_request="Test prompt 1", selected_tool="calendar_search")
    await service.log_event(user_request="Test prompt 2", selected_tool="email_search")

    recent = await service.get_recent_logs(limit=5)
    assert len(recent) >= 2


@pytest.mark.asyncio
async def test_retry_async_success_on_retry():
    attempts = 0

    async def flaky_operation():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise RuntimeError("temporary failure")
        return "success"

    result = await retry_async(flaky_operation, attempts=3, base_delay_seconds=0.01)
    assert result == "success"
    assert attempts == 2
