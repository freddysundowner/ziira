"""Sockets the People module plugs into (declared under [extends] in manifest.toml): Intelligence checks and baseline
metrics, and the figures it adds to the Command Center."""

from ziira.modules.people import intel_checks, pulse  # noqa: F401 - importing registers the implementations
