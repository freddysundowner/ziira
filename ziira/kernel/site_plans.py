"""The plans the public website shows, taken from the platform's own price list.

A small adapter, so the website content does not depend on how plans are stored: it asks `platform.plans.public_plans()`
and, if that is missing or fails, answers with no plans (the site then shows its "get in touch" state instead of an
error or an invented price).
"""

import importlib
import logging
from typing import Any

log = logging.getLogger("ziira.site_plans")


def public_plans() -> dict[str, Any]:
    """`{"plans": [...], "addons": [...], "updated_at": ...}` as the plans service publishes them, or empty lists."""
    empty: dict[str, Any] = {"plans": [], "addons": [], "updated_at": None}
    try:
        module = importlib.import_module("ziira.kernel.platform.plans")
    except ModuleNotFoundError:
        return empty
    function = getattr(module, "public_plans", None)
    if not callable(function):
        return empty
    try:
        value = function()
    except Exception:
        log.warning("The public plan list could not be read; the website payload carries no plans", exc_info=True)
        return empty
    return {"plans": list(value.get("plans") or []), "addons": list(value.get("addons") or []),
            "updated_at": value.get("updated_at")}
