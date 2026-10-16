"""The shared part of an AI provider that talks JSON over HTTPS: the client, retries with growing pauses, error mapping
and the list-models call. A provider plugin subclasses `HttpLlmProvider` and says only what is particular to its API
(URL, headers, request body, how to read the reply). Nothing here names a provider.

A rate limit (429), an overload (529) or a server error (5xx) is retried after a growing pause (`Retry-After` is
respected up to a limit); any other refusal (a wrong key, a bad request) fails at once. Only status, request id, tokens
and time are logged: never a key, never a prompt.
"""

import contextlib
import logging
import random
import time
from abc import abstractmethod
from collections.abc import Sequence
from typing import Any, ClassVar

import httpx

from ziira.modules.intel.domain.ai_rules import hide_secrets
from ziira.modules.intel.domain.llm import LiveModel, LlmError, LlmMessage, LlmProvider, LlmReply, ToolSpec

MAX_PAUSE_SECONDS = 20.0
RETRYABLE_STATUSES = (408, 409, 429, 529)


class HttpLlmProvider(LlmProvider):
    """Settings are given by the platform (the gateway reads them from the Super Admin's settings); `client_factory` and
    `sleep` let tests and the live check replace the network and the waiting."""

    client_factory: ClassVar[Any] = None                       # tests: a function(timeout) returning an httpx.Client
    sleep: ClassVar[Any] = staticmethod(time.sleep)
    log: ClassVar[logging.Logger] = logging.getLogger("ziira.ai")

    def __init__(self, *, api_key: str = "", model: str | None = None, base_url: str | None = None,
                 timeout: float = 30.0, max_retries: int = 2, options: dict[str, Any] | None = None) -> None:
        catalog = self.catalog()
        self.api_key = api_key
        self.model = model or (catalog.default_model() if catalog else "")
        self.base_url = (base_url or (catalog.base_url if catalog else "")).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.options = options or {}                           # per-model request options from the catalog

    @classmethod
    def from_settings(cls, *, api_key: str, model: str, base_url: str | None, timeout: float, max_retries: int,
                      options: dict[str, Any]) -> "HttpLlmProvider":
        return cls(api_key=api_key, model=model, base_url=base_url, timeout=timeout, max_retries=max_retries,
                   options=options)

    def configured(self) -> bool:
        return bool(self.api_key)

    def model_id(self) -> str:
        return self.model

    # ------------------------------------------------------------------------- what a provider says about its API
    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Authentication and content headers."""

    @abstractmethod
    def completion_url(self) -> str:
        """Where one request is POSTed."""

    @abstractmethod
    def build_request(self, messages: Sequence[LlmMessage], tools: Sequence[ToolSpec], system: str,
                      max_tokens: int) -> dict[str, Any]:
        """The JSON body of the POST."""

    @abstractmethod
    def parse_response(self, data: Any) -> LlmReply:
        """A `LlmReply` from the response JSON; LlmError if it is not shaped like one."""

    def error_message(self, body: Any) -> str:
        """The provider's own words from an error body (override for its error shape)."""
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            return f"{error.get('type') or error.get('status') or ''}: {error.get('message', '')}".strip(": ")
        return error if isinstance(error, str) else ""

    def models_url(self) -> str:
        raise LlmError("This provider cannot list its models")

    def parse_models(self, data: Any) -> tuple[list[LiveModel], str | None]:
        """The models on one page of the list, and the address of the next page (or None)."""
        raise LlmError("This provider cannot list its models")

    # ------------------------------------------------------------------------- failures
    def failure(self, response: httpx.Response) -> LlmError:
        """What went wrong, in words safe to store (the provider's message with any key removed)."""
        message = ""
        with contextlib.suppress(ValueError):
            message = self.error_message(response.json())
        code = response.status_code
        retryable = code in RETRYABLE_STATUSES or code >= 500
        detail = hide_secrets(message[:300], [self.api_key]) or "no details"
        if code in (401, 403):
            detail = f"the key was refused; {detail}"
        return LlmError(f"The AI provider answered {code} ({detail})", retryable=retryable, status=code)

    @staticmethod
    def retry_after(response: httpx.Response) -> float | None:
        try:
            return min(max(float(response.headers.get("retry-after", "")), 0.0), MAX_PAUSE_SECONDS)
        except ValueError:
            return None

    def _client(self) -> httpx.Client:
        return (self.client_factory(self.timeout) if self.client_factory
                else httpx.Client(timeout=httpx.Timeout(self.timeout, connect=5.0)))

    # ------------------------------------------------------------------------- calls
    def _send(self, method: str, url: str, body: dict[str, Any] | None = None) -> Any:
        """One request with retries; returns the parsed JSON of a 200 answer."""
        last: LlmError | None = None
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            pause: float | None = None
            try:
                with self._client() as client:
                    response = (client.post(url, json=body, headers=self.headers()) if method == "POST"
                                else client.get(url, headers=self.headers()))
            except httpx.HTTPError as error:
                last = LlmError(f"The AI provider could not be reached ({type(error).__name__})", retryable=True)
            else:
                self.log.info("%s status=%s ms=%s", self.name, response.status_code,
                              int((time.monotonic() - started) * 1000))
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise LlmError("The AI provider's reply was not valid JSON") from None
                last = self.failure(response)
                pause = self.retry_after(response)
            if not last.retryable or attempt >= self.max_retries:
                break
            self.sleep(pause if pause is not None else min(2.0 ** attempt + random.random() * 0.5, MAX_PAUSE_SECONDS))
        assert last is not None
        raise last

    def complete(self, messages: Sequence[LlmMessage], tools: Sequence[ToolSpec], system: str,
                 max_tokens: int) -> LlmReply:
        data = self._send("POST", self.completion_url(), self.build_request(messages, tools, system, max_tokens))
        return self.parse_response(data)

    def list_models(self) -> list[LiveModel]:
        found: list[LiveModel] = []
        url: str | None = self.models_url()
        for _ in range(20):                                    # a bounded number of pages
            if not url:
                break
            page, url = self.parse_models(self._send("GET", url))
            found += page
        return found
