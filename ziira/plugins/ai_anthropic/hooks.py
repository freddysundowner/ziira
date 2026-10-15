"""Sockets the Anthropic plugin plugs into (declared under [extends] in manifest.toml): it is an AI provider."""

from ziira.modules.intel.public import INTEL_LLM
from ziira.plugins.ai_anthropic.provider import AnthropicMessages
from ziira.sdk import provides

provides(INTEL_LLM)(AnthropicMessages)
