"""Sockets the Ziira Intelligence module offers (declared in manifest.toml): checks and baseline metrics."""

from ziira.modules.intel import kernel_checks  # noqa: F401 - registers Intelligence's own checks
from ziira.modules.intel.public import INTEL_BASELINE_METRIC, INTEL_CHECK, BaselineMetric, IntelCheck
from ziira.sdk import define_extension_point

define_extension_point(INTEL_CHECK, IntelCheck, "A check over a unit's data that raises findings")
define_extension_point(INTEL_BASELINE_METRIC, BaselineMetric, "Observations of a metric, to learn what is normal")
