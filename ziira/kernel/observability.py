"""Request ids, structured logging with redaction, and in-process HTTP metrics.

- `request_state` holds the request id and tenant id of the request being served. It is a mutable dict in a
  contextvar, so a value set inside a worker thread (the tenant, once the caller is known) is visible to the access log.
- `redact` removes secrets from any text before it is written: authorization headers, our token formats
  (`zr_`, `zk_`, `zdk_`), values of password/secret/token fields, card numbers and long ID-like numbers.
- `configure_logging` installs one handler on the root logger: plain text or JSON lines (`ZIIRA_LOG_FORMAT`).
- `HttpMetrics` counts requests and times them per route template and status class (per process).
"""

import json
import logging
import re
import sys
import threading
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# --------------------------------------------------------------------------- request state
request_state: ContextVar[dict[str, str | None] | None] = ContextVar("ziira_request_state", default=None)


def get_state() -> dict[str, str | None]:
    """The state of the request being served (an empty dict outside a request)."""
    return request_state.get() or {}


def current_request_id() -> str | None:
    """The id of the request being served (None outside a request)."""
    return get_state().get("request_id")


def bind_tenant(tenant_id: UUID) -> None:
    """Remember which business the current request acts for (for the access log)."""
    state = get_state()
    if state:
        state["tenant_id"] = str(tenant_id)


# --------------------------------------------------------------------------- redaction
_KEY = (r"(?:[\w-]*(?:password|passwd|secret|token|api[_-]?key|authorization|credential|passcode|private[_-]?key|"
        r"card[_-]?number)[\w-]*|pin|pwd|otp|cvv|cvc)")
_SENSITIVE = re.compile(_KEY, re.I)
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    (re.compile(r"\bz(?:r|k|dk)_[A-Za-z0-9_-]{8,}"), "[redacted-token]"),
    # "password": "value"  /  password=value  /  password: value (the value runs to a quote, space, comma or &)
    (re.compile(rf"""(?i)(["']?\b{_KEY}["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,&;}}\]"']+)"""), r"\1[redacted]"),
]
_LONG_NUMBER = re.compile(r"(?<![\w.-])\d(?:[ -]?\d){8,18}(?![\w-])")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def _number(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return "[redacted-card]"
    return "[redacted-number]"


def redact(value: str) -> str:
    """Remove secrets and card or ID-like numbers (nine digits or more) from text that is about to be logged."""
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return _LONG_NUMBER.sub(_number, value)


def redact_value(value: Any) -> Any:
    """`redact` for any JSON-like value (strings inside lists and dicts are redacted, sensitive keys blanked)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: "[redacted]" if _SENSITIVE.fullmatch(str(k)) else redact_value(v)
                for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value


# --------------------------------------------------------------------------- logging
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


class _Base(logging.Formatter):
    def _parts(self, record: logging.LogRecord) -> tuple[str, str | None]:
        message = redact(record.getMessage())
        error = redact(self.formatException(record.exc_info)) if record.exc_info else None
        return message, error

    @staticmethod
    def _extras(record: logging.LogRecord) -> dict[str, Any]:
        return {k: "[redacted]" if _SENSITIVE.fullmatch(k) else redact_value(v)
                for k, v in record.__dict__.items() if k not in _STANDARD and not k.startswith("_")}


class JsonFormatter(_Base):
    """One JSON object per line: time, level, logger, message, request_id, tenant_id and any `extra` fields."""

    def format(self, record: logging.LogRecord) -> str:
        message, error = self._parts(record)
        state = get_state()
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname, "logger": record.name, "message": message,
            "request_id": state.get("request_id"), "tenant_id": state.get("tenant_id"), **self._extras(record)}
        if error:
            entry["exception"] = error
        return json.dumps({k: v for k, v in entry.items() if v is not None}, default=str)


class TextFormatter(_Base):
    """Readable lines: `time LEVEL logger [request id] message key=value ...`."""

    def format(self, record: logging.LogRecord) -> str:
        message, error = self._parts(record)
        state = get_state()
        rid = f" [{str(state.get('request_id'))[:8]}]" if state.get("request_id") else ""
        extras = "".join(f" {k}={v}" for k, v in self._extras(record).items())
        line = f"{datetime.fromtimestamp(record.created).strftime('%H:%M:%S')} {record.levelname:<7} " \
               f"{record.name}{rid} {message}{extras}"
        return f"{line}\n{error}" if error else line


_HANDLER_MARK = "_ziira_handler"


def configure_logging(fmt: str | None = None, level: str | None = None) -> None:
    """Install the Ziira log handler on the root logger (safe to call again). Values default to the settings."""
    from ziira.kernel.config import get_settings

    settings = get_settings()
    fmt = fmt or settings.log_format
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, _HANDLER_MARK, False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel((level or settings.log_level).upper())
    # uvicorn writes its own access line with the raw query string; we log one per request ourselves.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True


# --------------------------------------------------------------------------- HTTP metrics
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class HttpMetrics:
    """Request counts and latency histograms per (method, route template, status class), for this process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._count: dict[tuple[str, str, str], int] = {}
            self._hist: dict[tuple[str, str], list[int]] = {}
            self._sum: dict[tuple[str, str], float] = {}

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        status_class = f"{status // 100}xx"
        key = (method, route)
        with self._lock:
            self._count[(method, route, status_class)] = self._count.get((method, route, status_class), 0) + 1
            buckets = self._hist.setdefault(key, [0] * (len(BUCKETS) + 1))
            for i, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    buckets[i] += 1
            buckets[-1] += 1                                       # +Inf = total count
            self._sum[key] = self._sum.get(key, 0.0) + seconds

    def render(self) -> list[str]:
        """Prometheus text lines."""
        def label(**kv: str) -> str:
            return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in kv.items()) + "}"

        lines = ["# HELP ziira_http_requests_total Requests by route template and status class.",
                 "# TYPE ziira_http_requests_total counter"]
        with self._lock:
            for (method, route, sc), n in sorted(self._count.items()):
                lines.append(f"ziira_http_requests_total{label(method=method, route=route, status=sc)} {n}")
            lines += ["# HELP ziira_http_request_duration_seconds Request latency.",
                      "# TYPE ziira_http_request_duration_seconds histogram"]
            for (method, route), buckets in sorted(self._hist.items()):
                for bound, n in zip(BUCKETS, buckets, strict=False):
                    lines.append("ziira_http_request_duration_seconds_bucket"
                                 f"{label(method=method, route=route, le=str(bound))} {n}")
                lines.append("ziira_http_request_duration_seconds_bucket"
                             f"{label(method=method, route=route, le='+Inf')} {buckets[-1]}")
                lines.append(f"ziira_http_request_duration_seconds_sum{label(method=method, route=route)} "
                             f"{self._sum[(method, route)]:.6f}")
                lines.append(f"ziira_http_request_duration_seconds_count{label(method=method, route=route)} "
                             f"{buckets[-1]}")
        return lines


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


http_metrics = HttpMetrics()
