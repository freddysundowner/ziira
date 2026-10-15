"""Shared plumbing for the connectors that talk to another system over HTTPS.

Everything here is about doing reads safely: friendly, secret-free error messages; a retry hint for the sync engine;
polite pacing; resumable cursors; and tolerant parsing of the dates and amounts other systems send.
"""

import ipaddress
import json
import logging
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from ziira.modules.connect.public import CanonicalBatch, ConnectorError, Record
from ziira.sdk import is_production

log = logging.getLogger("ziira.connect")

MovementKind = Literal["sale", "purchase", "adjustment", "transfer_in", "transfer_out", "count", "return", "other"]

# A pull restarts this long before the newest record it saw, so a record saved late (a clock a little behind, a long
# transaction) is never missed. Records are upserted by `ref`, so reading one twice is harmless.
OVERLAP = timedelta(minutes=5)


# --------------------------------------------------------------------------- errors
class RetryAfterError(ConnectorError):
    """The system asked us to slow down or is unavailable: try again, not before `retry_after` seconds if given."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message, retryable=True)
        self.retry_after = retry_after


class ReadOnlyViolation(ConnectorError):
    """A connector tried to do something that is not a read. This is a bug in the connector, never retried."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


def scrub(text: str, secrets: Iterable[object] = (), limit: int = 240) -> str:
    """Remove every secret value from `text` and shorten it: vendor error bodies are echoed to the owner."""
    out = text
    for value in secrets:
        raw = str(value) if value is not None else ""
        if len(raw) >= 4:
            out = out.replace(raw, "***")
    out = " ".join(out.split())
    return out if len(out) <= limit else out[: limit - 1] + "…"


def retry_after_seconds(response: httpx.Response) -> float | None:
    """The `Retry-After` header as seconds (numbers or an HTTP date), capped at an hour."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(max(float(value), 0.0), 3600.0)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        return min(max((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds(), 0.0), 3600.0)
    except (TypeError, ValueError):
        return None


def raise_for_status(response: httpx.Response, *, system: str, secrets: Iterable[object] = (),
                     what: str = "the data") -> None:
    """Turn an HTTP failure into a `ConnectorError` with plain words. Credentials problems are not retryable;
    throttling and outages are."""
    status = response.status_code
    if status < 400:
        return
    secrets = tuple(secrets)
    detail = scrub(_error_text(response), secrets)
    suffix = f" ({detail})" if detail else ""
    if status == 401:
        raise ConnectorError(f"{system} did not accept the access key or login. Check it was copied completely and "
                             f"has not been withdrawn.{suffix}", retryable=False)
    if status == 403:
        raise ConnectorError(f"{system} accepted the key but the user it belongs to is not allowed to read {what}. "
                             f"Give that user read permission and try again.{suffix}", retryable=False)
    if status == 404:
        raise ConnectorError(f"{system} did not find that address. Check the web address you entered.{suffix}",
                             retryable=False)
    if status == 429:
        raise RetryAfterError(f"{system} asked us to slow down (too many requests). We will try again later.",
                              retry_after=retry_after_seconds(response))
    if status >= 500:
        raise RetryAfterError(f"{system} is not available right now (error {status}). We will try again later.",
                              retry_after=retry_after_seconds(response))
    raise ConnectorError(f"{system} refused the request (error {status}).{suffix}", retryable=False)


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        fault = body.get("Fault") or body.get("fault")
        if isinstance(fault, dict):                       # QuickBooks: {"Fault": {"Error": [{"Message", "Detail"}]}}
            errors = fault.get("Error") or fault.get("error") or []
            first = errors[0] if errors and isinstance(errors[0], dict) else {}
            return " ".join(str(first.get(k) or first.get(k.lower()) or "") for k in ("Message", "Detail")).strip()
        for key in ("message", "_server_messages", "exc_type", "error", "error_description"):
            value = body.get(key)
            if isinstance(value, str):
                return value
    return ""


def transport_error(exc: Exception, *, system: str) -> ConnectorError:
    """A friendly error for a failure before any reply arrived."""
    if isinstance(exc, httpx.TimeoutException):
        return RetryAfterError(f"{system} did not answer in time. We will try again later.")
    if isinstance(exc, httpx.UnsupportedProtocol | httpx.InvalidURL):
        return ConnectorError(f"The web address for {system} is not valid. It must start with https://",
                              retryable=False)
    if isinstance(exc, httpx.ConnectError):
        return RetryAfterError(f"Could not reach {system}. Check the web address, or whether the system is down.")
    return RetryAfterError(f"The connection to {system} failed. We will try again later.")


def json_body(response: httpx.Response, *, system: str) -> Any:
    """The JSON body, or a clear error when the reply is something else (a login page, an error page)."""
    try:
        return response.json()
    except ValueError:
        raise ConnectorError(
            f"{system} replied with something that is not data (often a login page: the address may be wrong, or "
            "access from outside may be switched off).", retryable=True) from None


# --------------------------------------------------------------------------- the web address
def normalise_base_url(raw: object, *, system: str, allow_private: bool | None = None) -> str:
    """A clean `https://host[:port][/path]` without a trailing slash.

    A business gives us this address, so we refuse addresses that point inside our own network (loopback, private and
    link-local ranges) in production; otherwise someone could use a connection to probe the platform's neighbours.
    `allow_private=None` means: allowed outside production only.
    """
    text = str(raw or "").strip()
    if not text:
        raise ConnectorError(f"The web address of {system} is missing.", retryable=False)
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ConnectorError(f"The web address for {system} is not valid. It must look like https://example.com",
                             retryable=False)
    if parts.username or parts.password:
        raise ConnectorError("Do not put a login in the web address; use the key fields instead.", retryable=False)
    private_ok = (not is_production()) if allow_private is None else allow_private
    if not private_ok:
        if parts.scheme != "https":
            raise ConnectorError(f"The web address for {system} must start with https://", retryable=False)
        if _is_internal(parts.hostname):
            raise ConnectorError(f"The web address for {system} points to a private network, which Ziira cannot "
                                 "reach. Use the public address.", retryable=False)
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def _is_internal(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
        return True
    try:
        ip = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        return "." not in lowered                       # a bare name like "erp" only resolves inside a network
    return not ip.is_global


# --------------------------------------------------------------------------- pacing
class Pacer:
    """Keeps requests under a per-minute allowance (a sliding window) and counts them against a per-run budget.

    `sleep` and `clock` are injectable so tests do not wait.
    """

    def __init__(self, per_minute: int = 60, *, budget: int | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute = max(1, per_minute)
        self.budget = budget
        self.used = 0
        self._sleep = sleep
        self._clock = clock
        self._times: list[float] = []

    @property
    def exhausted(self) -> bool:
        return self.budget is not None and self.used >= self.budget

    def wait(self) -> None:
        """Block until one more request is allowed, and count it."""
        now = self._clock()
        self._times = [t for t in self._times if now - t < 60.0]
        if len(self._times) >= self.per_minute:
            pause = 60.0 - (now - self._times[0])
            if pause > 0:
                self._sleep(pause)
            now = self._clock()
            self._times = [t for t in self._times if now - t < 60.0]
        self._times.append(self._clock())
        self.used += 1

    def back_off(self, seconds: float | None) -> None:
        """The system said wait: do (up to a limit; longer waits are left to the next scheduled run)."""
        self._sleep(min(max(seconds or 5.0, 1.0), 60.0))


# --------------------------------------------------------------------------- cursors
def decode_cursor(since: str | None) -> dict[str, str]:
    """A cursor is a small JSON object {source: ISO-8601 UTC time}; one entry per kind of record read for an entity.
    A plain timestamp (older style) is accepted as the entry for the empty source."""
    if not since:
        return {}
    try:
        value = json.loads(since)
    except ValueError:
        return {"": since}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {"": since}


def encode_cursor(cursor: dict[str, str]) -> str:
    return json.dumps(cursor, sort_keys=True, separators=(",", ":"))


def cursor_time(moment: datetime) -> str:
    """The cursor entry for 'we have seen everything modified up to `moment`': a little earlier, for the overlap."""
    return (as_utc(moment) - OVERLAP).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def parse_cursor_time(value: str | None) -> datetime | None:
    return parse_dt(value) if value else None


# --------------------------------------------------------------------------- values
def as_utc(moment: datetime, default_tz: str | None = None) -> datetime:
    """Timezone-aware UTC. A naive time is read in `default_tz` (a system's own clock) or UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone(default_tz))
    return moment.astimezone(UTC)


def zone(name: str | None) -> tzinfo:
    """The named IANA zone, or UTC when none is given or the name is unknown (`validate_timezone` reports bad names)."""
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except Exception:
        return UTC


def to_zone(moment: datetime, name: str | None) -> datetime:
    """`moment` expressed on the wall clock of the named zone."""
    return moment.astimezone(zone(name))


def validate_timezone(name: object) -> str | None:
    """None for 'not given'; the name if it is a real IANA zone; ConnectorError otherwise."""
    if name in (None, ""):
        return None
    try:
        ZoneInfo(str(name))
    except Exception:
        raise ConnectorError(f"'{name}' is not a time zone name. Use a name such as Africa/Nairobi or Europe/London.",
                             retryable=False) from None
    return str(name)


def parse_dt(value: object, default_tz: str | None = None) -> datetime | None:
    """Parse the date-time formats other systems send ('2024-05-03 14:22:10.123', '2024-05-03T14:22:10+0300', ...).
    Returns an aware UTC datetime, or None when there is no usable value."""
    if value in (None, "", False):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return as_utc(moment, default_tz)


def parse_date(value: object) -> date | None:
    if value in (None, "", False):
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def at_midnight(day: date, tz: str | None = None) -> datetime:
    """A calendar date as an aware instant (start of that day in the system's own zone, as UTC)."""
    return as_utc(datetime(day.year, day.month, day.day), tz)


def dec(value: object, default: Decimal | None = Decimal(0)) -> Decimal:
    """Money or quantity from a JSON value (numbers arrive as float or text). Bad or missing values become `default`."""
    if value is None or value is False or value == "":
        return default if default is not None else Decimal(0)
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return default if default is not None else Decimal(0)
    return result if result.is_finite() else (default if default is not None else Decimal(0))


def dec_or_none(value: object) -> Decimal | None:
    """Like `dec` but None stays None, and zero means 'not recorded' (costs and prices that are blank in the source)."""
    if value is None or value is False or value == "":
        return None
    result = dec(value)
    return result if result != 0 else None


def text_or_none(value: object) -> str | None:
    if value is None or value is False:
        return None
    cleaned = str(value).strip()
    return cleaned or None


# Names a business gave its payment methods. Matching on words is a heuristic: the method list is the business's own,
# so unknown names fall back to "other".
_MOBILE_HINTS = ("mpesa", "m-pesa", "momo", "mobile", "wallet", "airtel", "orange money")
_CARD_HINTS = ("card", "visa", "mastercard", "pos terminal", "credit card", "debit card")
_BANK_HINTS = ("bank", "cheque", "check", "transfer", "eft", "wire")


def payment_method(name: object, kind: object = None) -> str:
    """Map a payment method's name (and its type, where the system has one) to Ziira's short list."""
    label = f"{name or ''} {kind or ''}".lower()
    if any(h in label for h in _MOBILE_HINTS) or str(kind or "").lower() in ("phone", "mobile"):
        return "mobile_money"
    if any(h in label for h in _CARD_HINTS):
        return "card"
    if any(h in label for h in _BANK_HINTS) or str(kind or "").lower() == "bank":
        return "bank"
    if "cash" in label:
        return "cash"
    return "other"


@dataclass
class Progress:
    """Counts records for a pull so `limit` is honoured and the newest modification time is remembered."""

    limit: int | None
    count: int = 0
    newest: datetime | None = None

    def see(self, modified: datetime | None) -> None:
        self.count += 1
        if modified is not None and (self.newest is None or modified > self.newest):
            self.newest = modified

    @property
    def full(self) -> bool:
        return self.limit is not None and self.count >= self.limit


def seal(entity: str, parts: Iterator[tuple[tuple[Record, ...], str | None]], since: str | None,
         truncated: Callable[[], bool] = lambda: False) -> Iterator[CanonicalBatch]:
    """Turn (records, cursor) pieces into batches, marking only the very last one `complete` (unless the read stopped
    early because of a `limit` or a request budget: then the last batch says more remain). Always yields at least one
    batch, so the sync engine hears 'nothing new' as well as news."""
    held: tuple[tuple[Record, ...], str | None] | None = None
    last_cursor = since
    for part in parts:
        if held is not None:
            yield CanonicalBatch(entity, held[0], held[1], complete=False)
        held = part
        last_cursor = part[1] or last_cursor
    if held is None:
        yield CanonicalBatch(entity, (), last_cursor, complete=not truncated())
    else:
        yield CanonicalBatch(entity, held[0], held[1], complete=not truncated())


@dataclass(frozen=True)
class OAuthResult:
    """What a finished authorisation gives back: secrets to store encrypted, and non-secret settings."""

    secrets: dict[str, Any]
    config: dict[str, Any]
