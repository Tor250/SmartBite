"""Request correlation and low-risk structured access logging."""
import json
import logging
import re
import time
from contextvars import ContextVar
from uuid import uuid4

logger = logging.getLogger("smartbite.http")
generator_logger = logging.getLogger("smartbite.generator")
request_id_context: ContextVar[str | None] = ContextVar("smartbite_request_id", default=None)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def configure_logging() -> None:
    # В стандартной конфигурации Uvicorn нет корневого обработчика. Направляем
    # события приложения в доступный журнал JSON-строк, не меняя уровень журналов библиотек.
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logger.setLevel(logging.INFO)
    generator_logger.setLevel(logging.INFO)


def request_id_from_header(value: str | None) -> str:
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return uuid4().hex


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied_id = request_headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = request_id_from_header(supplied_id)
        scope.setdefault("state", {})["request_id"] = request_id
        context_token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            record = {
                "event": "http_request_finished",
                "request_id": request_id,
                "method": scope.get("method", ""),
                "path": scope.get("path", ""),
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            logger.info(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            request_id_context.reset(context_token)
