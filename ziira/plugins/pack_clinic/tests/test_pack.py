"""The pack's files are valid (the same check runs when the pack is installed)."""

from ziira.sdk import check_pack


def test_the_pack_files_are_valid() -> None:
    assert check_pack("pack_clinic") == []
