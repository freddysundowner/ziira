"""Sockets the Purchasing module plugs into (declared under [extends] in manifest.toml)."""

from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.imports.public import IMPORTS_IMPORTER
from ziira.modules.intel.public import INTEL_CHECK
from ziira.modules.purchasing.importers import SupplierImporter
from ziira.modules.purchasing.intel_checks import (
    BillMismatchWaiting,
    DuplicateSupplierBill,
    DuplicateSupplierPayment,
    MarginSqueeze,
    OrderAboveUsualPrice,
    OverdueSupplierBills,
    PaidWithoutReceipt,
    SupplierBankChanged,
    SupplierPriceRise,
)
from ziira.modules.purchasing.pulse import PurchasingPulse
from ziira.sdk import provides

for _check in (SupplierPriceRise, OrderAboveUsualPrice, MarginSqueeze, DuplicateSupplierBill, DuplicateSupplierPayment,
               SupplierBankChanged, PaidWithoutReceipt, OverdueSupplierBills, BillMismatchWaiting):
    provides(INTEL_CHECK)(_check)
provides(COMMAND_PULSE_SOURCE)(PurchasingPulse)
provides(IMPORTS_IMPORTER)(SupplierImporter)

from ziira.modules.purchasing import privacy as _privacy  # noqa: E402, F401, I001 - registers personal-data provider
