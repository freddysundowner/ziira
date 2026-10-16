"""Where the data behind a finding lives. A check that reads the copy of a system the business keeps (the Connectors
module's standalone checks) has a code starting `standalone.`; every other check reads Ziira's own records. People see
the difference as "From your connected system" and "From Ziira", and can filter by it."""

CONNECTED_PREFIX = "standalone."


def is_connected_check(check_code: str | None) -> bool:
    """True when the check reads a connected system's copy, not Ziira's own records."""
    return bool(check_code) and str(check_code).startswith(CONNECTED_PREFIX)
