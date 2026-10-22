"""Sockets the Ziira Intelligence module offers (declared in manifest.toml): checks, baseline metrics, AI providers and
the tools Ask Ziira may call. It also plugs its own ask tools and the fake AI provider (development and tests) in."""

from uuid import UUID

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
from ziira.sdk import (
    INBOUND_COMMAND,
    INDUSTRY_SEEDER,
    IndustrySeeder,
    PackData,
    SeedReport,
    Session,
    define_extension_point,
    provides,
)

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


@provides(INDUSTRY_SEEDER)
class IntelCheckLimitsSeeder(IndustrySeeder):
    """Sets the limits an industry pack suggests for checks (`data/intel.toml`, one `[check."code"]` table of limits
    per check). A check the business has already tuned is left exactly as it is; unknown checks and limits are
    ignored."""

    name = "intel.check_limits"
    unit = "intel"

    def seed(self, session: Session, pack: PackData, company_id: UUID) -> SeedReport:
        from ziira.modules.intel.public import apply_check_defaults

        report = SeedReport()
        wanted = {code: dict(limits) for code, limits in pack.unit_data(self.unit).get("check", {}).items()}
        done = apply_check_defaults(session, wanted) if wanted else []
        report.skipped = len(wanted) - len(done)
        if done:
            report.notes.append("limits set for: " + ", ".join(sorted(done)))
        return report

from ziira.modules.intel import privacy as _privacy  # noqa: E402, F401, I001 - registers the personal-data provider

from ziira.modules.intel import platform_ai as _platform_ai  # noqa: E402, F401, I001 - answers the Super Admin
from ziira.modules.intel import site_assistant_llm as _site_assistant_llm  # noqa: E402, F401, I001 - the website assistant's model call
