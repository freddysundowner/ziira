"""The "kernel.personal_data" socket: how units answer a person's request about the data held on them.

Every unit that stores data about people (customers, employees, suppliers, payers, users, message recipients) plugs
a provider into this socket from its own `hooks.py`:

    @provides("kernel.personal_data")
    class CustomerData(PersonalDataProvider):
        name = "crm"
        def find(self, session, company_id, subject) -> list[PersonalRecord]: ...
        def export(self, session, record) -> dict[str, Any]: ...
        def anonymise(self, session, record, reason) -> Outcome: ...

The kernel's privacy service (`privacy.py`) calls the providers of the units enabled for the business. A provider:

- `find` returns the records that match the subject. An email, a phone number or an identifier matches exactly
  ("exact"); a name matches loosely and is flagged "possible", so a person decides before anything is exported or
  erased.
- `linked` (optional) returns this unit's records that hang from what other units found: the sales of a customer
  that CRM found, the payments of a supplier. The privacy service calls it once, after every `find`.
- `export` returns everything held about one record as JSON-able fields (what the person is entitled to see).
- `anonymise` replaces the identifying fields of one record with placeholders and keeps what the business must keep
  (amounts, document numbers, dates), saying what it kept and why. It never deletes a record that a posted document
  points to, and never touches the immutable tables (journal, stock movements, audit log). A provider that may not
  anonymise yet (a record the business must keep) returns a refused outcome with the reason.
- `retention` describes what the unit keeps and for how long, for the retention view and the retention job.

The rules are the business's, never the platform's: retention periods are company settings, and which records must be
kept is the business's own decision recorded in those settings. See docs/privacy.md.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.errors import ValidationFailed
from ziira.kernel.extensions import define_extension_point
from ziira.kernel.phone import normalise_phone

PERSONAL_DATA = "kernel.personal_data"
PLACEHOLDER = "[erased]"
MIN_SUBJECT_LENGTH = 3


@dataclass(frozen=True)
class Subject:
    """What a data subject request names, read into the forms providers can match on.

    A string of digits may be both a phone number and an identifier, so both are filled and a provider matches on
    either. `name` is set only for text with no digits, and is matched loosely."""

    raw: str
    email: str | None = None
    phone: str | None = None            # international digits, read with the company's calling code
    identifier: str | None = None       # a tax or national id, spaces and dashes removed, upper case
    name: str | None = None

    @property
    def kind(self) -> str:
        if self.email:
            return "email"
        if self.name:
            return "name"
        return "phone" if self.phone and not self.identifier else "identifier"

    @property
    def masked(self) -> str:
        """The subject written so a person can recognise it but it identifies nobody (kept after erasure)."""
        return mask_text(self.raw)


def mask_text(value: str) -> str:
    """'jane.doe@example.com' -> 'j***@example.com'; '447911123456' -> '4479****456'; 'Jane Doe' -> 'J*** D**'."""
    value = value.strip()
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 8 and len(digits) >= len(re.sub(r"\s", "", value)) - 1:
        return f"{digits[:4]}****{digits[-3:]}"
    return " ".join(f"{word[:1]}{'*' * min(max(len(word) - 1, 0), 3)}" for word in value.split()) or "****"


def parse_subject(raw: str, calling_code: str | None) -> Subject:
    """Read what was typed (an email, a phone number, an id or a name) into a Subject. Raises ValidationFailed if it
    is too short to search for safely: a one-letter search would match half the business."""
    value = (raw or "").strip()
    if len(value) < MIN_SUBJECT_LENGTH:
        raise ValidationFailed(f"Name the person with at least {MIN_SUBJECT_LENGTH} characters: an email, a phone "
                               "number, an id number or a full name")
    if "@" in value:
        if value.count("@") != 1 or " " in value or not value.partition("@")[2]:
            raise ValidationFailed("That does not look like an email address")
        return Subject(raw=value, email=value.lower())
    compact = re.sub(r"[\s\-().]", "", value)
    if re.search(r"\d", compact):
        phone: str | None = None
        if re.fullmatch(r"\+?\d+", compact):
            try:
                phone = normalise_phone(value, calling_code)
            except ValidationFailed:
                phone = None
        identifier = compact.upper() if len(compact) >= 4 and re.fullmatch(r"[A-Za-z0-9/]+", compact) else None
        if phone is None and identifier is None:
            raise ValidationFailed("That does not look like a phone number, an id number or a name")
        return Subject(raw=value, phone=phone, identifier=identifier)
    return Subject(raw=value, name=" ".join(value.split()))


def like_pattern(value: str) -> str:
    """A `%value%` pattern for loose name matching with `ilike`, with the wildcards in `value` escaped."""
    return "%" + re.sub(r"([\\%_])", r"\\\1", value) + "%"


def sql_digits(column: str) -> str:
    """SQL for a column's digits only (so '+44 7911-123-456' and '447911123456' compare equal)."""
    return f"regexp_replace({column}, '[^0-9]', '', 'g')"


def sql_phone_matches(column: str, param: str) -> str:
    """SQL that is true when the column holds the phone number in `:param` (international digits), however it was typed:
    '+44 7911 123 456', '447911123456' or the national form '07911 123 456' (matched by its last digits, 7 or more)."""
    d = sql_digits(column)
    return (f"({column} is not null and ({d} = :{param} or (length(ltrim({d}, '0')) >= 7 "
            f"and :{param} like '%' || ltrim({d}, '0'))))")


def sql_identifier(column: str) -> str:
    """SQL for an identifier column without spaces, dashes or case (compare it with Subject.identifier)."""
    return f"upper(regexp_replace({column}, '[\\s/-]', '', 'g'))"


def json_rows(session: Session, sql: str, **params: Any) -> list[dict[str, Any]]:
    """Run a query whose single column is a JSON object (`to_jsonb(t)`, `jsonb_build_object(...)`) and return the
    objects: the quickest way for a provider to export a table's rows."""
    return [dict(row[0]) for row in session.execute(text(sql), params)]


def json_one(session: Session, sql: str, **params: Any) -> dict[str, Any] | None:
    """Like `json_rows`, for a query that returns at most one row (None when there is none)."""
    rows = json_rows(session, sql, **params)
    return rows[0] if rows else None


@dataclass(frozen=True)
class PersonalRecord:
    """One record that holds data about the subject. `source` is the provider's name, `kind` what the record is."""

    source: str
    kind: str
    record_id: UUID
    label: str                                 # how a person recognises it (shown to the one handling the request)
    match: str = "exact"             # "exact" or "possible"
    company_id: UUID | None = None
    ref: str = ""                              # the provider's own pointer when an id is not enough


@dataclass(frozen=True)
class Kept:
    """Something an anonymisation left in place, and why."""

    what: str
    why: str


@dataclass
class Outcome:
    """What `anonymise` did with one record. `status`: anonymised (all identifying fields replaced), partial (some were
    replaced, `kept` says what stayed and why) or refused (nothing changed; `message` says why)."""

    status: Literal["anonymised", "partial", "refused"]
    changed: list[str] = field(default_factory=list)
    kept: list[Kept] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class RetentionRule:
    """What a unit keeps about people, for how long, and what happens at the end of that time."""

    unit: str
    code: str
    what: str                                  # the data kept
    basis: str                                 # why it is kept (the business's lawful reason, in plain words)
    setting: str | None = None                 # the company setting that controls the period, if any
    period: str = "kept until the subject asks"   # e.g. "365 days", "7 years", "indefinitely"
    at_end: str = "review"                     # 'mask' (the job masks it), 'review' (a person decides), 'keep'
    eligible: int = 0                          # how many records are past the period right now


class PersonalDataProvider(ABC):
    """Contract of the "kernel.personal_data" extension point."""

    name: str = "provider"

    @abstractmethod
    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        """The records of this company that match the subject (exact for an email, phone or id; possible for a name)."""

    def linked(self, session: Session, company_id: UUID, found: list[PersonalRecord]) -> list[PersonalRecord]:
        """Records of this unit that belong to records other units already found (sales of a customer, payments of a
        supplier). `found` is what every unit's `find` returned; a linked record is as certain as the one it hangs
        from. Look at a record's `source` and `kind` (text), never at the other unit's tables."""
        return []

    @abstractmethod
    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        """Everything held about this record, as JSON-able fields. Never secrets (password hashes, keys)."""

    @abstractmethod
    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        """Replace the record's identifying fields with placeholders, keeping what must be kept. Irreversible."""

    def retention(self, session: Session, company_id: UUID) -> list[RetentionRule]:
        """What this unit keeps and for how long (shown in the retention view)."""
        return []


define_extension_point(PERSONAL_DATA, PersonalDataProvider,
                       "Finds, exports and anonymises the personal data a unit holds, for data subject requests "
                       "(access, correction, erasure) and retention.")
