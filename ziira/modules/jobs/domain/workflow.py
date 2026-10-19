"""The stages a job moves through. Pure Python: no database, no HTTP.

Stages and the moves between them are data a business owns (and an industry pack can seed). Each stage has a *kind*
(open: work is going on; waiting: it waits for the customer or for parts; done: the work is finished; closed: the job
is over) and optionally a *role*: the one stage the platform itself moves a job into when something happens (a job is
born in 'initial', an approved estimate moves it to 'approved', collection moves it to 'collected'). Names and codes
are free, so a tailor can call the first stage "Measured" and still get everything below.
"""

from dataclasses import dataclass, field

from ziira.sdk import ValidationFailed

KINDS = ("open", "waiting", "done", "closed")
ROLES = ("initial", "quoted", "approved", "ready", "collected", "closed", "cancelled")
MAX_STATUSES = 40


@dataclass(frozen=True)
class StatusDef:
    code: str
    name: str
    kind: str
    role: str | None = None


@dataclass(frozen=True)
class Definition:
    """Stages (in order) and allowed moves as (from code, to code)."""

    statuses: list[StatusDef]
    moves: list[tuple[str, str]] = field(default_factory=list)


DEFAULT = Definition(
    statuses=[
        StatusDef("received", "Received", "open", "initial"),
        StatusDef("diagnosing", "Diagnosing", "open"),
        StatusDef("quoted", "Quoted", "waiting", "quoted"),
        StatusDef("approved", "Approved", "open", "approved"),
        StatusDef("in_progress", "In progress", "open"),
        StatusDef("waiting_for_parts", "Waiting for parts", "waiting"),
        StatusDef("ready", "Ready", "done", "ready"),
        StatusDef("collected", "Collected", "done", "collected"),
        StatusDef("closed", "Closed", "closed", "closed"),
        StatusDef("cancelled", "Cancelled", "closed", "cancelled"),
    ],
    moves=[
        ("received", "diagnosing"), ("received", "quoted"), ("received", "approved"), ("received", "in_progress"),
        ("received", "cancelled"),
        ("diagnosing", "quoted"), ("diagnosing", "in_progress"), ("diagnosing", "waiting_for_parts"),
        ("diagnosing", "ready"), ("diagnosing", "cancelled"),
        ("quoted", "approved"), ("quoted", "diagnosing"), ("quoted", "cancelled"),
        ("approved", "in_progress"), ("approved", "waiting_for_parts"), ("approved", "cancelled"),
        ("in_progress", "waiting_for_parts"), ("in_progress", "ready"), ("in_progress", "diagnosing"),
        ("in_progress", "quoted"),
        ("waiting_for_parts", "in_progress"), ("waiting_for_parts", "diagnosing"), ("waiting_for_parts", "cancelled"),
        ("ready", "collected"), ("ready", "in_progress"),
        ("collected", "closed"),
    ],
)


def check_code(code: str) -> str:
    """A stage code: lower case letters, digits and underscores."""
    clean = code.strip().lower()
    if not clean or len(clean) > 40 or not all(c.isalnum() or c == "_" for c in clean) or not clean[0].isalpha():
        raise ValidationFailed("A stage code uses letters, digits and underscores, and starts with a letter")
    return clean


def check_statuses(stages: list[StatusDef]) -> set[str]:
    """Raise ValidationFailed unless every stage is well formed and no code or role repeats. Returns the codes."""
    if not stages or len(stages) > MAX_STATUSES:
        raise ValidationFailed(f"A workflow has between 1 and {MAX_STATUSES} stages")
    codes: set[str] = set()
    roles: set[str] = set()
    for s in stages:
        check_code(s.code)
        if not s.name.strip():
            raise ValidationFailed("Every stage needs a name")
        if s.kind not in KINDS:
            raise ValidationFailed(f"Stage kind must be one of: {', '.join(KINDS)}")
        if s.role is not None and s.role not in ROLES:
            raise ValidationFailed(f"Stage role must be one of: {', '.join(ROLES)}")
        if s.code in codes:
            raise ValidationFailed(f"Stage {s.code} appears twice")
        codes.add(s.code)
        if s.role is not None:
            if s.role in roles:
                raise ValidationFailed(f"Only one stage can have the role {s.role}")
            roles.add(s.role)
    return codes


def check_definition(definition: Definition) -> None:
    """Raise ValidationFailed unless the stages and moves make sense together."""
    codes = check_statuses(definition.statuses)
    for a, b in definition.moves:
        if a not in codes or b not in codes:
            raise ValidationFailed(f"The move {a} to {b} names a stage that does not exist")
        if a == b:
            raise ValidationFailed("A move goes from one stage to a different one")


def can_move(moves: set[tuple[str, str]], from_id: str, to_id: str) -> bool:
    """True when the workflow allows going from one stage to the other."""
    return (from_id, to_id) in moves


def closes_job(kind: str) -> bool:
    return kind == "closed"
