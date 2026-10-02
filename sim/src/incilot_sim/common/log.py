"""Logs estructurados en JSON a stdout, con el request_id propagado entre servicios."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_LOGGING_KWARGS = {"exc_info", "stack_info", "stacklevel", "extra"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if rid := request_id.get():
            entry["request_id"] = rid
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class FieldsLogger(logging.LoggerAdapter):
    """Permite `log.info("order confirmed", order_id=..., amount_cents=...)`."""

    def process(self, msg, kwargs):
        fields = {k: kwargs.pop(k) for k in list(kwargs) if k not in _LOGGING_KWARGS}
        kwargs["extra"] = {"fields": fields}
        return msg, kwargs


def get_logger(name: str) -> FieldsLogger:
    return FieldsLogger(logging.getLogger(name))


def configure_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn instala sus propios handlers en texto plano: los mandamos al root.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # Ruido: el middleware ya loguea cada request y las métricas cubren las llamadas salientes.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
