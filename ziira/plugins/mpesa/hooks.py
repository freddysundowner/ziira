"""Sockets the M-Pesa plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.mpesa.daraja import DarajaProvider, SimulatedDarajaProvider
from ziira.plugins.mpesa.statement import MpesaStatement
from ziira.sdk import provides

provides("payments.provider")(DarajaProvider)
provides("payments.provider")(SimulatedDarajaProvider)
provides("payments.statement_format")(MpesaStatement)
