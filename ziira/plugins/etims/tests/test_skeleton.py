"""The skeleton is well-formed: a tax plugin for Kenya whose contract imports and whose table is its own."""

import tomllib
from decimal import Decimal
from pathlib import Path

from ziira.plugins.etims import public


def test_the_manifest_and_contract_are_in_place() -> None:
    manifest = tomllib.loads((Path(public.__file__).parent / "manifest.toml").read_text())
    unit = manifest["unit"]
    assert (unit["kind"], unit["category"], unit["countries"]) == ("plugin", "tax", ["KE"])
    assert "extends" not in manifest and "provides" not in manifest          # no behaviour yet: it plugs into nothing
    assert public.SUBMISSION_STATUSES == ("pending", "submitted", "failed")
    doc = public.SaleDocument("sale", "S-1", [], Decimal("116.00"))
    assert doc.original_authority_ref is None
    assert public.SubmissionResult(False, message="down").permanent_failure is False
