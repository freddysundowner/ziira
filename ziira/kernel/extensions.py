"""Extension points and validation hooks: the standard sockets units plug into.

Two kinds of socket, both owned by a unit and declared in its manifest:

1. Extension points: a named contract (an abstract base class) that other units implement,
   e.g. "payments.provider" implemented by an Airtel Money plugin.

       # owner, in hooks.py:     PROVIDERS = define_extension_point("payments.provider", PaymentProvider)
       # implementer, hooks.py:  @provides("payments.provider")
       #                         class AirtelMoney(PaymentProvider): ...
       # owner, in a service:    for provider in implementations(session, "payments.provider"): ...

2. Validation hooks: a named moment before an action, where other units may block it by raising
   ValidationFailed, e.g. "products.product.before_create".

       # owner, in hooks.py:     define_validation_hook("products.product.before_create", "...")
       # validator, hooks.py:    @validate("products.product.before_create")
       #                         def no_banned_words(session, draft): ...
       # owner, in a service:    run_validators(session, "products.product.before_create", draft)

Only units enabled for the tenant take part. Implementations are checked against the contract
when they are registered, so a broken plugin fails at start-up, not in front of a user.

Rules (specification section 02):
- Only validation hooks may block an operation; they run inside the transaction, before saving.
- A validator that crashes (anything other than ValidationFailed) also blocks, naming its unit:
  failing closed is safer than letting an unchecked operation through. Keep validators fast;
  slow ones are logged.
- Work that may fail or take time belongs in @subscribe_after handlers, never in validators.
"""

import inspect
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.errors import ValidationFailed
from ziira.kernel.events import unit_of

log = logging.getLogger("ziira.extensions")
SLOW_VALIDATOR_SECONDS = 0.2

Validator = Callable[[Session, Any], None]


@dataclass
class ExtensionPoint:
    """A named contract that units may implement."""

    name: str
    contract: type
    description: str
    owner: str
    implementations: list[tuple[str, type]] = field(default_factory=list)


@dataclass
class ValidationHook:
    """A named moment before an action where units may block it."""

    name: str
    description: str
    owner: str
    validators: list[tuple[str, Validator]] = field(default_factory=list)


_points: dict[str, ExtensionPoint] = {}
_hooks: dict[str, ValidationHook] = {}
# Registrations made before the owner defined the socket (import order is not guaranteed).
_pending_implementations: list[tuple[str, str, type]] = []
_pending_validators: list[tuple[str, str, Validator]] = []


def _caller_unit() -> str:
    frame = inspect.stack()[2]
    module = inspect.getmodule(frame.frame)
    return unit_of(module.__name__ if module else "")


# --------------------------------------------------------------------------- declaring sockets
def define_extension_point(name: str, contract: type, description: str = "") -> ExtensionPoint:
    """Declare an extension point owned by the calling unit. `contract` is an abstract base class."""
    if not inspect.isabstract(contract):
        raise TypeError(f"Extension point '{name}': the contract must be an abstract base class")
    point = _points.get(name)
    if point is None:
        point = _points[name] = ExtensionPoint(name, contract, description, _caller_unit())
    for pending in [p for p in _pending_implementations if p[0] == name]:
        _pending_implementations.remove(pending)
        _add_implementation(point, pending[1], pending[2])
    return point


def define_validation_hook(name: str, description: str = "") -> ValidationHook:
    """Declare a validation hook owned by the calling unit."""
    hook = _hooks.get(name)
    if hook is None:
        hook = _hooks[name] = ValidationHook(name, description, _caller_unit())
    for pending in [p for p in _pending_validators if p[0] == name]:
        _pending_validators.remove(pending)
        hook.validators.append((pending[1], pending[2]))
    return hook


# --------------------------------------------------------------------------- plugging in
def _add_implementation(point: ExtensionPoint, unit: str, implementation: type) -> None:
    if not (inspect.isclass(implementation) and issubclass(implementation, point.contract)):
        raise TypeError(f"{implementation!r} from '{unit}' must subclass {point.contract.__name__} "
                        f"to implement '{point.name}'")
    if inspect.isabstract(implementation):
        missing = ", ".join(sorted(getattr(implementation, "__abstractmethods__", ())))
        raise TypeError(f"{implementation.__name__} from '{unit}' does not implement: {missing}")
    if (unit, implementation) not in point.implementations:
        point.implementations.append((unit, implementation))


def provides(name: str) -> Callable[[type], type]:
    """Class decorator: this class implements extension point `name`."""

    def register(implementation: type) -> type:
        unit = unit_of(implementation.__module__)
        if name in _points:
            _add_implementation(_points[name], unit, implementation)
        else:
            _pending_implementations.append((name, unit, implementation))
        return implementation

    return register


def validate(name: str) -> Callable[[Validator], Validator]:
    """Function decorator: run this before the action `name`; raise ValidationFailed to block it."""

    def register(validator: Validator) -> Validator:
        unit = unit_of(validator.__module__)
        if name in _hooks:
            _hooks[name].validators.append((unit, validator))
        else:
            _pending_validators.append((name, unit, validator))
        return validator

    return register


# --------------------------------------------------------------------------- using sockets
def _enabled_units(session: Session) -> set[str]:
    return {"kernel", *session.execute(text(
        "select unit_name from kernel.tenant_unit "
        "where status = 'enabled' and tenant_id = kernel.current_tenant()")).scalars()}


def implementations(session: Session, name: str) -> list[Any]:
    """Instances of every implementation of `name` from units enabled for this tenant."""
    if name not in _points:
        raise KeyError(f"Unknown extension point '{name}'")
    enabled = _enabled_units(session)
    return [impl() for unit, impl in _points[name].implementations if unit in enabled]


def provider_named(point: str, name: str) -> type | None:
    """The implementation of an extension point with this `name` attribute, from any unit (platform-level code, with no
    business to look at, uses this: a tenant's enabled units do not apply)."""
    found = _points.get(point)
    if found is None:
        return None
    return next((impl for _, impl in found.implementations if getattr(impl, "name", None) == name), None)


def run_validators(session: Session, name: str, subject: Any) -> None:
    """Run every validator of `name` from units enabled for this tenant. Raises ValidationFailed to block."""
    if name not in _hooks:
        raise KeyError(f"Unknown validation hook '{name}'")
    enabled = _enabled_units(session)
    for unit, validator in _hooks[name].validators:
        if unit not in enabled:
            continue
        started = time.monotonic()
        try:
            validator(session, subject)
        except ValidationFailed:
            raise
        except Exception as exc:
            log.exception("Validator %s from '%s' failed on %s", validator.__name__, unit, name)
            raise ValidationFailed(f"A check from '{unit}' failed, so this was not saved: {exc}") from exc
        finally:
            elapsed = time.monotonic() - started
            if elapsed > SLOW_VALIDATOR_SECONDS:
                log.warning("Slow validator %s from '%s' on %s: %.2fs", validator.__name__, unit, name, elapsed)


# --------------------------------------------------------------------------- inspection
def extension_points() -> dict[str, ExtensionPoint]:
    """Every declared extension point (for documentation, the API and tests)."""
    return dict(_points)


def validation_hooks() -> dict[str, ValidationHook]:
    """Every declared validation hook."""
    return dict(_hooks)


def undefined_registrations() -> list[str]:
    """Implementations and validators for sockets nobody declared (a mistake to report)."""
    return ([f"{unit} implements unknown '{name}'" for name, unit, _ in _pending_implementations]
            + [f"{unit} validates unknown '{name}'" for name, unit, _ in _pending_validators])


def clear_extensions() -> None:
    """For tests only."""
    _points.clear()
    _hooks.clear()
    _pending_implementations.clear()
    _pending_validators.clear()
