# AI provider: Anthropic Messages API (plugin)

Lets the AI assistant of Ziira Intelligence (`docs/ai.md`) talk to Anthropic's Messages API: it implements the `intel.llm`
extension point (`provider.py`, class `AnthropicMessages`). It has no tables, no routes and needs no per-business enabling: the
platform chooses the provider (`ZIIRA_AI_PROVIDER=anthropic`) and holds the key (`ZIIRA_AI_API_KEY`, model `ZIIRA_AI_MODEL`,
default `claude-sonnet-5-5`).

> The request and response shapes were written from Anthropic's public documentation and **have not been run against the real
> service**. Run `.venv/bin/python scripts/live_check.py ai --dry-run`, then without `--dry-run` with a real key
> (`ZIIRA_LIVE_AI_API_KEY`), before relying on it (`docs/live-checks.md` section 4).

What it does: one POST to `/v1/messages` per call with `x-api-key` and `anthropic-version`; maps the neutral messages, tool
definitions and tool results to `tool_use` / `tool_result` blocks and back; retries 429, 529 and 5xx after growing pauses
(`Retry-After` respected), refuses other 4xx at once; counts cached input tokens against the budget; never logs a prompt or a
key. Another provider is a class implementing `LlmProvider` with `@provides("intel.llm")` in its own plugin.
