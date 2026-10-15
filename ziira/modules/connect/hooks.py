"""Sockets the Connectors module offers (declared in manifest.toml): where other systems plug in their readers. It also
plugs in its own file and statement connectors, its standalone checks and baselines for Intelligence, and its figures
for the Command Center."""

from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.connect import standalone_checks
from ziira.modules.connect.ocr.tesseract import TesseractEngine
from ziira.modules.connect.public import CONNECTOR, OCR_ENGINE, Connector, OcrEngine
from ziira.modules.intel.public import INTEL_BASELINE_METRIC, INTEL_CHECK
from ziira.sdk import define_extension_point, provides

define_extension_point(CONNECTOR, Connector, "A reader for another system: turns its data into the canonical model")
define_extension_point(OCR_ENGINE, OcrEngine,
                       "Reads the words out of a picture of a statement (default: Tesseract on this server)")
provides(OCR_ENGINE)(TesseractEngine)

from ziira.modules.connect.connectors import file_kinds as _file_kinds  # noqa: E402, F401, I001 - file and statement kinds
from ziira.modules.connect.connectors import registry as _api_kinds  # noqa: E402, F401, I001 - ERPNext, Odoo, Zoho, QuickBooks

for _check in standalone_checks.CHECKS:
    provides(INTEL_CHECK)(_check)
for _metric in standalone_checks.METRICS:
    provides(INTEL_BASELINE_METRIC)(_metric)

from ziira.modules.connect.pulse import ConnectPulse  # noqa: E402, I001

provides(COMMAND_PULSE_SOURCE)(ConnectPulse)

from ziira.modules.connect import privacy as _privacy  # noqa: E402, F401, I001 - registers the personal-data provider
