"""Sockets the Payments module offers and plugs into (declared in manifest.toml)."""

from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.intel.public import INTEL_BASELINE_METRIC, INTEL_CHECK
from ziira.modules.payments import intel_checks
from ziira.modules.payments.public import PROVIDER_EXTENSION, STATEMENT_EXTENSION, PaymentProvider, StatementReader
from ziira.modules.payments.pulse import PaymentsPulse
from ziira.sdk import define_extension_point, provides

define_extension_point(PROVIDER_EXTENSION, PaymentProvider,
                       "A way to ask customers for money and to read what the provider reports; a plugin per provider "
                       "(the module knows none).")
define_extension_point(STATEMENT_EXTENSION, StatementReader,
                       "A statement format people upload (a provider's business statement); the bank CSV is built in.")

for _check in (intel_checks.UnlinkedReceipts, intel_checks.UnmatchedTransactions, intel_checks.CloseVariance,
               intel_checks.MissingClose, intel_checks.SettlementMismatch, intel_checks.PossibleDuplicatePayments,
               intel_checks.FailingPaymentPrompts, intel_checks.ReversedAfterMatch,
               intel_checks.ManualPaymentWithoutEvidence):
    provides(INTEL_CHECK)(_check)

provides(INTEL_BASELINE_METRIC)(intel_checks.PromptFailureRate)
provides(COMMAND_PULSE_SOURCE)(PaymentsPulse)

from ziira.modules.payments import privacy as _privacy  # noqa: E402, F401, I001 - registers personal-data provider

from ziira.modules.connect.public import CORE_COVERAGE  # noqa: E402, I001
from ziira.modules.payments.core_coverage import PaymentsCoverage  # noqa: E402, I001

provides(CORE_COVERAGE)(PaymentsCoverage)  # tells Connectors what Core covers
