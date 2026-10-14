"""Domain events.

`publish` does two things inside the caller's transaction:
1. Calls in-transaction subscribers of units enabled for the tenant
   (e.g. Finance posting a journal when a sale is posted). If a subscriber
   fails, the whole operation rolls back.
2. Writes the event to kernel.event_outbox, so after-commit consumers
   (notifications, webhooks, plugins, Ziira Intelligence) receive it only
   once the transaction has committed. Register them with @subscribe_after;
   kernel/outbox.py delivers them (run `ziira outbox-run`).
"""

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.context import get_context


@dataclass(frozen=True)
class Event:
    """Something that happened, e.g. `sale.posted`."""

    type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Session, Event], None]
_subscribers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)
_after_commit: dict[str, list[tuple[str, Handler]]] = defaultdict(list)


_unit_packages: dict[str, str] = {}


def register_unit_package(package: str, unit_name: str) -> None:
    """Record which unit a Python package belongs to (called by the registry before loading events)."""
    _unit_packages[package] = unit_name


def unit_of(module_name: str) -> str:
    """Unit name of a Python module, e.g. ziira.modules.finance.events -> finance.

    Third-party plugins are found through the package the registry recorded for them.
    """
    for package, unit_name in _unit_packages.items():
        if module_name == package or module_name.startswith(package + "."):
            return unit_name
    parts = module_name.split(".")
    if len(parts) >= 3 and parts[0] == "ziira" and parts[1] in ("modules", "plugins"):
        return parts[2]
    if parts[:2] == ["ziira", "kernel"]:
        return "kernel"
    return parts[0]


def _unit_of(handler: Handler) -> str:
    return unit_of(handler.__module__)


def subscribe(event_type: str) -> Callable[[Handler], Handler]:
    """Decorator: run this function inside the transaction whenever `event_type` is published."""

    def register(handler: Handler) -> Handler:
        _subscribers[event_type].append((_unit_of(handler), handler))
        return handler

    return register


def subscribe_after(event_type: str) -> Callable[[Handler], Handler]:
    """Decorator: run this function after the publishing transaction has committed.

    Delivery is at least once, so the handler must be safe to run twice for the same
    event (for example, check whether it has already done its work). If it raises, the
    event is retried later.
    """

    def register(handler: Handler) -> Handler:
        _after_commit[event_type].append((_unit_of(handler), handler))
        return handler

    return register


def after_commit_handlers(event_type: str) -> list[tuple[str, Handler]]:
    """Unit name and handler of every after-commit subscriber of `event_type`."""
    return list(_after_commit.get(event_type, []))


def _enabled_units(session: Session) -> set[str]:
    """The units enabled for the tenant. Looked up once per transaction: an operation publishes many events."""
    found: set[str] | None = session.info.get("enabled_units")
    if found is None:
        found = {"kernel", *session.execute(text(
            "select unit_name from kernel.tenant_unit "
            "where status = 'enabled' and tenant_id = kernel.current_tenant()")).scalars()}
        session.info["enabled_units"] = found
    return found


def publish(session: Session, event: Event) -> None:
    """Dispatch to enabled in-transaction subscribers, then write to the outbox."""
    publish_many(session, [event])


def publish_many(session: Session, events: list[Event]) -> None:
    """`publish` for a batch (a check that finds thousands of things): each event goes to the subscribers in order,
    then all are written to the outbox with one statement."""
    if not events:
        return
    ctx = get_context()
    enabled = _enabled_units(session)
    for event in events:
        for unit, handler in _subscribers.get(event.type, []):
            if unit in enabled:
                handler(session, event)
    session.execute(
        text("insert into kernel.event_outbox (tenant_id, event_type, aggregate_type, aggregate_id, payload) "
             "values (:t, :e, :a, :i, cast(:p as jsonb))"),
        [{"t": str(ctx.tenant_id), "e": event.type, "a": event.aggregate_type, "i": str(event.aggregate_id),
          "p": json.dumps(event.payload, default=str)} for event in events])


def clear_subscribers() -> None:
    """For tests only."""
    _subscribers.clear()
    _after_commit.clear()
