"""Sockets the Payments module offers and plugs into (declared in manifest.toml)."""

from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.intel.public import INTEL_BASELINE_METRIC, INTEL_CHECK
from ziira.modules.payments import intel_checks
from ziira.modules.payments.providers import DarajaProvider, FakeProvider
from ziira.modules.payments.public import PROVIDER_EXTENSION, PaymentProvider
from ziira.modules.payments.pulse import PaymentsPulse
from ziira.sdk import define_extension_point, provides

define_extension_point(PROVIDER_EXTENSION, PaymentProvider,
                       "A way to ask customers for money (an STK push); Daraja and a fake one are built in.")

provides(PROVIDER_EXTENSION)(DarajaProvider)
provides(PROVIDER_EXTENSION)(FakeProvider)

for _check in (intel_checks.UnlinkedReceipts, intel_checks.UnmatchedTransactions, intel_checks.CloseVariance,
               intel_checks.MissingClose, intel_checks.SettlementMismatch, intel_checks.PossibleDuplicatePayments,
               intel_checks.FailingPaymentPrompts, intel_checks.ReversedAfterMatch,
               intel_checks.ManualPaymentWithoutEvidence):
    provides(INTEL_CHECK)(_check)

provides(INTEL_BASELINE_METRIC)(intel_checks.PromptFailureRate)
provides(COMMAND_PULSE_SOURCE)(PaymentsPulse)
