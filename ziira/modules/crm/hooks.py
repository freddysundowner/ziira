"""Sockets the CRM module plugs into (declared under [extends] in manifest.toml): Intelligence checks and the figures
it adds to the Command Center."""

from ziira.modules.crm import intel_checks, pulse  # noqa: F401 - importing registers the implementations
