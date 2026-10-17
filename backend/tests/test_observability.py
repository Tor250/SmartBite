import json
import logging

from app.observability import generator_logger, logger, request_id_from_header


def test_request_id_accepts_safe_client_value():
    assert request_id_from_header("demo-request_123.abc") == "demo-request_123.abc"


def test_application_structured_loggers_emit_info_records():
    assert logger.isEnabledFor(logging.INFO)
    assert generator_logger.isEnabledFor(logging.INFO)


def test_request_id_replaces_invalid_or_oversized_value():
    invalid = request_id_from_header("bad\nvalue")
    oversized = request_id_from_header("x" * 65)

    assert invalid != "bad\nvalue"
    assert len(invalid) == 32
    assert len(oversized) == 32


def test_request_logs_are_correlated_without_logging_request_data(api_client, caplog):
    caplog.set_level(logging.INFO, logger="smartbite.http")
    response = api_client.post(
        "/api/auth/register",
        headers={"X-Request-ID": "demo-123"},
        json={"email": "private@example.org", "password": "private-secret-123"},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == "demo-123"
    records = [json.loads(record.message) for record in caplog.records if record.name == "smartbite.http"]
    assert records
    record = records[-1]
    assert record["request_id"] == "demo-123"
    assert record["path"] == "/api/auth/register"
    assert "private@example.org" not in json.dumps(record)
    assert "private-secret-123" not in json.dumps(record)
