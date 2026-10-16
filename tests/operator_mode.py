"""Pin how platform staff sign in for one test module (`ZIIRA_OPERATOR_MFA`), whatever the machine's own setting is.

    _mode = operator_mode("totp")        # at module level in a test file
"""

import os
from collections.abc import Iterator

import pytest

from ziira.kernel.config import get_settings


def operator_mode(mode: str, **env: str):  # type: ignore[no-untyped-def]
    """A module-wide autouse fixture that sets ZIIRA_OPERATOR_MFA (and any other ZIIRA_* given, e.g.
    OPERATOR_SESSION_HOURS="1") and puts everything back afterwards."""

    @pytest.fixture(scope="module", autouse=True)
    def pinned() -> Iterator[None]:
        wanted = {"ZIIRA_OPERATOR_MFA": mode, **{f"ZIIRA_{k.upper()}": v for k, v in env.items()}}
        before = {k: os.environ.get(k) for k in wanted}
        os.environ.update(wanted)
        get_settings.cache_clear()
        yield
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    return pinned
