"""Sockets the Ziira Intelligence module offers (declared in manifest.toml): checks, baseline metrics, AI providers and
the tools Ask Ziira may call. It also plugs its own ask tools and the fake AI provider (development and tests) in."""

from ziira.modules.intel import kernel_checks  # noqa: F401 - registers Intelligence's own checks
from ziira.modules.intel.action_providers import NudgeExceptionsReviewers
from ziira.modules.intel.ask_tools import FindingDetail, ListFindings
from ziira.modules.intel.fake_llm import FakeLlm
from ziira.modules.intel.inbound import ProposalReplies
from ziira.modules.intel.public import (
    INTEL_ACTION,
    INTEL_ASK_TOOL,
    INTEL_BASELINE_METRIC,
    INTEL_CHECK,
    INTEL_LLM,
    ActionProvider,
    AskTool,
    BaselineMetric,
    IntelCheck,
    LlmProvider,
)
from ziira.sdk import INBOUND_COMMAND, define_extension_point, provides

define_extension_point(INTEL_CHECK, IntelCheck, "A check over a unit's data that raises findings")
define_extension_point(INTEL_BASELINE_METRIC, BaselineMetric, "Observations of a metric, to learn what is normal")
define_extension_point(INTEL_LLM, LlmProvider, "An AI provider that answers the assistant's requests")
define_extension_point(INTEL_ASK_TOOL, AskTool,
                       "A question Ask Ziira may put to a unit's data, within the asker's access")

define_extension_point(INTEL_ACTION, ActionProvider,
                       "Something Intelligence may propose for a finding, done once a person or an owner's rule allows")

provides(INTEL_LLM)(FakeLlm)
provides(INTEL_ACTION)(NudgeExceptionsReviewers)
provides(INTEL_ASK_TOOL)(ListFindings)
provides(INTEL_ASK_TOOL)(FindingDetail)
provides(INBOUND_COMMAND)(ProposalReplies)

from ziira.modules.intel import privacy as _privacy  # noqa: E402, F401, I001 - registers the personal-data provider
