from src.app.rag.document_registry import _utcnow_naive


def test_document_registry_uses_naive_utc_for_timestamp_columns():
    timestamp = _utcnow_naive()

    assert timestamp.tzinfo is None
