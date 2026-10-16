"""A pretend AI provider API for the plugin tests: plays back replies, keeps the requests, records the pauses."""

from typing import Any

import httpx

from ziira.modules.intel.public import HttpLlmProvider, LlmMessage, LlmReply, ToolSpec

TOOL = ToolSpec("pos_sales_summary", "Sales between two dates",
                {"type": "object", "properties": {"date_from": {"type": "string"},
                                                  "limit": {"type": "integer", "minimum": 1, "maximum": 30}},
                 "required": ["date_from"], "additionalProperties": False})


class Pretend:
    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []
        self.pauses: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(item, Exception):
            raise item
        return item

    def provider(self, cls: type[HttpLlmProvider], key: str, **kw: Any) -> Any:
        net = self

        class P(cls):                                           # type: ignore[valid-type, misc]
            client_factory = staticmethod(lambda timeout: httpx.Client(transport=httpx.MockTransport(net.handler)))
            sleep = staticmethod(net.pauses.append)

        return P(api_key=key, base_url="https://api.example.test/", **kw)


def reply(status: int, body: Any = None, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=body if body is not None else {}, headers=headers)


def ask(provider: Any, tools: list[ToolSpec] | None = None) -> LlmReply:
    reply_: LlmReply = provider.complete([LlmMessage("user", "How were sales?")], tools or [], "Be brief.", 300)
    return reply_
