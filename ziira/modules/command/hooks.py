"""Sockets the Command Center offers (declared in manifest.toml): where units add their figures."""

from ziira.modules.command.public import COMMAND_PULSE_SOURCE, PulseSource
from ziira.sdk import define_extension_point

define_extension_point(COMMAND_PULSE_SOURCE, PulseSource, "Figures a unit adds to the Command Center")
