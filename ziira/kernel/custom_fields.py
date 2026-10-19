"""Custom fields: a business (or an industry pack) adds its own fields to a kind of record, such as a vehicle plate
on an asset or a hair type on a customer.

    definitions   kernel.custom_field_def     what fields exist for a kind of record ("entity type")
    values        kernel.custom_field_value   one row per record: its values, keyed by field key

* A unit makes a kind of record fieldable by implementing the extension point `kernel.custom_field_entity` (from its
  `hooks.py`): it names the record type, the permissions that view and edit it, and finds a record's company and branch,
  so the API checks the same scope the unit itself checks.
* Units call `definitions_for`, `validate_values`, `read_values` and `write_values` (through `ziira.sdk`) from their own
  services, after their own permission checks.
* Fields are text, number, date, yes/no or a choice from a list. There is no money kind and no stock kind: money and
  stock are never custom fields. Values hold personal data, so they plug into `kernel.personal_data` (below).
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.context import get_context
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.extensions import define_extension_point, implementations, provides
from ziira.kernel.personal_data import (
    PERSONAL_DATA,
    Kept,
    Outcome,
    PersonalDataProvider,
    PersonalRecord,
    Subject,
    like_pattern,
)

CUSTOM_FIELD_ENTITY = "kernel.custom_field_entity"
PERMISSION = "customfields.manage"
KINDS = ("text", "number", "date", "bool", "choice")
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_TEXT = 500
MAX_LABEL = 80
MAX_CHOICES = 50
MAX_FIELDS_PER_TYPE = 40
MAX_DIGITS = 18
ZERO = "00000000-0000-0000-0000-000000000000"
ERASED = "[erased]"

_COLUMNS = ("id, company_id, entity_type, key, label, kind, choices, required, searchable, sort_order, active, source")


class CustomFieldEntity(ABC):
    """Contract of the "kernel.custom_field_entity" extension point: one kind of record that can carry custom fields."""

    entity_type: str = ""            # stable id, "<unit>.<record>", e.g. "bookings.appointment"
    label: str = ""                  # plain words for the settings page: "Appointment"
    view_permission: str = ""        # who may read the values (the permission that opens the record)
    edit_permission: str = ""        # who may change them (the permission that edits the record)

    @abstractmethod
    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        """The record's (company_id, branch_id), or None when there is no such record in this business."""


define_extension_point(CUSTOM_FIELD_ENTITY, CustomFieldEntity,
                       "A kind of record that can carry custom fields: names the type, its permissions and its scope")


@dataclass(frozen=True)
class FieldDef:
    id: UUID
    company_id: UUID | None
    entity_type: str
    key: str
    label: str
    kind: str
    choices: tuple[str, ...]
    required: bool
    searchable: bool
    sort_order: int
    active: bool
    source: str

    @property
    def from_pack(self) -> bool:
        return self.source != "business"


def _def(row: Any) -> FieldDef:
    m = row._mapping
    return FieldDef(id=m["id"], company_id=m["company_id"], entity_type=m["entity_type"], key=m["key"],
                    label=m["label"], kind=m["kind"], choices=tuple(m["choices"] or ()), required=m["required"],
                    searchable=m["searchable"], sort_order=m["sort_order"], active=m["active"], source=m["source"])


# --------------------------------------------------------------------------- record types
def entities(session: Session) -> dict[str, CustomFieldEntity]:
    """The kinds of record that can have custom fields in this business (units that are on), by entity type."""
    found: dict[str, CustomFieldEntity] = {}
    for impl in implementations(session, CUSTOM_FIELD_ENTITY):
        if impl.entity_type:
            found[impl.entity_type] = impl
    return found


def entity(session: Session, entity_type: str) -> CustomFieldEntity:
    found = entities(session).get(entity_type)
    if found is None:
        raise NotFound(f"There is no kind of record '{entity_type}' that can have custom fields here")
    return found


# --------------------------------------------------------------------------- definitions
def definitions_for(session: Session, entity_type: str, company_id: UUID | None = None,
                    include_inactive: bool = False) -> list[FieldDef]:
    """The fields of a kind of record that apply to a company: those for the whole business and those for that company.
    With no company, only the whole-business fields. Ordered as the business arranged them."""
    rows = session.execute(text(
        f"select {_COLUMNS} from kernel.custom_field_def where entity_type = :t "
        "and (company_id is null or company_id = :c) and (active or :all) order by sort_order, label, key"),
        {"t": entity_type, "c": str(company_id) if company_id else ZERO, "all": include_inactive})
    return [_def(r) for r in rows]


def list_definitions(session: Session, entity_type: str | None = None) -> list[FieldDef]:
    """Every definition of the business (the settings page), grouped by the caller."""
    rows = session.execute(text(
        f"select {_COLUMNS} from kernel.custom_field_def where (cast(:t as text) is null or entity_type = :t) "
        "order by entity_type, sort_order, label, key"), {"t": entity_type})
    return [_def(r) for r in rows]


def get_definition(session: Session, definition_id: UUID) -> FieldDef:
    row = session.execute(text(f"select {_COLUMNS} from kernel.custom_field_def where id = :i"),
                          {"i": str(definition_id)}).first()
    if row is None:
        raise NotFound("Custom field not found")
    return _def(row)


def _clean_choices(kind: str, choices: list[str] | None) -> list[str]:
    if kind != "choice":
        return []
    cleaned = [c.strip() for c in (choices or []) if isinstance(c, str) and c.strip()]
    if not cleaned:
        raise ValidationFailed("A choice field needs at least one choice")
    if len(cleaned) > MAX_CHOICES or len(set(cleaned)) != len(cleaned) or any(len(c) > MAX_LABEL for c in cleaned):
        raise ValidationFailed(f"Choices must be different from each other, at most {MAX_CHOICES}, each under "
                               f"{MAX_LABEL} characters")
    return cleaned


def _clean_label(label: str) -> str:
    label = " ".join((label or "").split())
    if not 1 <= len(label) <= MAX_LABEL:
        raise ValidationFailed(f"Give the field a name of 1 to {MAX_LABEL} characters")
    return label


def create_definition(session: Session, *, entity_type: str, key: str, label: str, kind: str,
                      choices: list[str] | None = None, required: bool = False, searchable: bool = False,
                      sort_order: int | None = None, company_id: UUID | None = None,
                      source: str = "business") -> FieldDef:
    """Add a field. The record type must exist in this business; the key is fixed for life."""
    entity(session, entity_type)
    key = (key or "").strip().lower()
    if not KEY_PATTERN.match(key):
        raise ValidationFailed("The key is lowercase letters, digits and '_', starting with a letter (40 at most)")
    if kind not in KINDS:
        raise ValidationFailed(f"The kind is one of: {', '.join(KINDS)}")
    if company_id is not None and session.execute(
            text("select 1 from kernel.company where id = :c"), {"c": str(company_id)}).first() is None:
        raise ValidationFailed("Company not found")
    label = _clean_label(label)
    options = _clean_choices(kind, choices)
    taken = session.execute(text(
        "select count(*) from kernel.custom_field_def where entity_type = :t"), {"t": entity_type}).scalar_one()
    if taken >= MAX_FIELDS_PER_TYPE:
        raise ValidationFailed(f"A kind of record can have at most {MAX_FIELDS_PER_TYPE} custom fields")
    clash = session.execute(text(
        "select 1 from kernel.custom_field_def where entity_type = :t and key = :k "
        "and coalesce(company_id, cast(:z as uuid)) = coalesce(cast(:c as uuid), cast(:z as uuid))"),
        {"t": entity_type, "k": key, "c": str(company_id) if company_id else None, "z": ZERO}).first()
    if clash:
        raise Conflict(f"There is already a field with the key '{key}' on this kind of record")
    if sort_order is None:
        sort_order = int(session.execute(text(
            "select coalesce(max(sort_order), 0) + 10 from kernel.custom_field_def where entity_type = :t"),
            {"t": entity_type}).scalar_one())
    row = session.execute(text(
        "insert into kernel.custom_field_def (tenant_id, company_id, entity_type, key, label, kind, choices, required, "
        "searchable, sort_order, source) values (kernel.current_tenant(), :c, :t, :k, :l, :kind, "
        f"cast(:ch as jsonb), :r, :s, :o, :src) returning {_COLUMNS}"),
        {"c": str(company_id) if company_id else None, "t": entity_type, "k": key, "l": label, "kind": kind,
         "ch": json.dumps(options), "r": required, "s": searchable, "o": sort_order, "src": source}).one()
    return _def(row)


def seed_definition(session: Session, *, pack: str, entity_type: str, key: str, label: str, kind: str,
                    choices: list[str] | None = None, required: bool = False, searchable: bool = False,
                    company_id: UUID | None = None) -> tuple[FieldDef, bool]:
    """Add a pack's field unless the business already has that key (it may have edited or hidden it on purpose).
    Returns the field and whether it was added."""
    row = session.execute(text(
        f"select {_COLUMNS} from kernel.custom_field_def where entity_type = :t and key = :k "
        "and coalesce(company_id, cast(:z as uuid)) = coalesce(cast(:c as uuid), cast(:z as uuid))"),
        {"t": entity_type, "k": key, "c": str(company_id) if company_id else None, "z": ZERO}).first()
    if row is not None:
        return _def(row), False
    return create_definition(session, entity_type=entity_type, key=key, label=label, kind=kind, choices=choices,
                             required=required, searchable=searchable, company_id=company_id,
                             source=f"pack:{pack}"), True


def update_definition(session: Session, definition_id: UUID, *, label: str | None = None,
                      choices: list[str] | None = None, required: bool | None = None,
                      searchable: bool | None = None, sort_order: int | None = None,
                      active: bool | None = None) -> FieldDef:
    """Change what a business may change. The key, the kind, the record type and the source never change."""
    current = get_definition(session, definition_id)
    new_label = _clean_label(label) if label is not None else current.label
    new_choices = _clean_choices(current.kind, choices if choices is not None else list(current.choices))
    row = session.execute(text(
        "update kernel.custom_field_def set label = :l, choices = cast(:ch as jsonb), required = :r, searchable = :s, "
        f"sort_order = :o, active = :a, updated_at = now() where id = :i returning {_COLUMNS}"),
        {"l": new_label, "ch": json.dumps(new_choices), "r": current.required if required is None else required,
         "s": current.searchable if searchable is None else searchable,
         "o": current.sort_order if sort_order is None else sort_order,
         "a": current.active if active is None else active, "i": str(definition_id)}).one()
    return _def(row)


def delete_definition(session: Session, definition_id: UUID) -> FieldDef:
    """Remove a field the business added, and its values. A field a pack supplied is hidden instead, never deleted."""
    current = get_definition(session, definition_id)
    if current.from_pack:
        raise Conflict("This field came with an industry pack: hide it instead of deleting it")
    session.execute(text("delete from kernel.custom_field_def where id = :i"), {"i": str(definition_id)})
    session.execute(text(
        "update kernel.custom_field_value set data = data - cast(:k as text), updated_at = now() "
        "where entity_type = :t and data ? cast(:k as text)"), {"k": current.key, "t": current.entity_type})
    return current


def reorder(session: Session, entity_type: str, ordered_ids: list[UUID]) -> None:
    """Put the fields of a record type in the given order (ids not named keep their place after those named)."""
    for n, definition_id in enumerate(ordered_ids):
        done = session.execute(text(
            "update kernel.custom_field_def set sort_order = :o, updated_at = now() "
            "where id = :i and entity_type = :t returning id"),
            {"o": (n + 1) * 10, "i": str(definition_id), "t": entity_type}).first()
        if done is None:
            raise NotFound("Custom field not found")


# --------------------------------------------------------------------------- validating values
def _one(definition: FieldDef, value: Any) -> Any:
    """One value in its stored form, or raise ValidationFailed naming the field."""
    name = definition.label
    if definition.kind == "text":
        if not isinstance(value, str):
            raise ValidationFailed(f"{name}: type some text")
        cleaned = value.strip()
        if len(cleaned) > MAX_TEXT:
            raise ValidationFailed(f"{name}: at most {MAX_TEXT} characters")
        if any(ord(ch) < 32 and ch not in "\n\t" for ch in cleaned):
            raise ValidationFailed(f"{name}: contains characters that cannot be saved")
        return cleaned
    if definition.kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValidationFailed(f"{name}: enter a number")
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            raise ValidationFailed(f"{name}: enter a number") from None
        if not number.is_finite() or len(number.as_tuple().digits) > MAX_DIGITS:
            raise ValidationFailed(f"{name}: enter a number of at most {MAX_DIGITS} digits")
        return format(number.normalize() if number != 0 else Decimal(0), "f")
    if definition.kind == "date":
        try:
            if not isinstance(value, str):
                raise ValueError
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            raise ValidationFailed(f"{name}: enter a date as YYYY-MM-DD") from None
    if definition.kind == "bool":
        if not isinstance(value, bool):
            raise ValidationFailed(f"{name}: choose yes or no")
        return value
    if definition.kind == "choice":
        if not isinstance(value, str) or value not in definition.choices:
            raise ValidationFailed(f"{name}: choose one of the listed options")
        return value
    raise ValidationFailed(f"{name}: unknown kind")


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_values(definitions: list[FieldDef], values: dict[str, Any], *, existing: dict[str, Any] | None = None,
                    check_required: bool = True) -> dict[str, Any]:
    """Check the values against the fields and return them in stored form (numbers as exact decimal text, dates as
    YYYY-MM-DD). Raises ValidationFailed for a value of the wrong kind, a choice not in the list, text that is too long,
    a key that is not an active field here. An empty value clears the field. `existing` are the values already saved:
    with `check_required`, a required field must have a value either way."""
    if not isinstance(values, dict):
        raise ValidationFailed("Custom field values are a set of key and value")
    by_key = {d.key: d for d in definitions if d.active}
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        definition = by_key.get(key)
        if definition is None:
            raise ValidationFailed(f"'{key}' is not a custom field here")
        cleaned[key] = None if _empty(value) else _one(definition, value)
    if check_required:
        have = {k: v for k, v in (existing or {}).items() if k in by_key and not _empty(v)}
        have.update({k: v for k, v in cleaned.items() if v is not None})
        for k in (k for k, v in cleaned.items() if v is None):
            have.pop(k, None)
        missing = [d.label for d in by_key.values() if d.required and d.key not in have]
        if missing:
            raise ValidationFailed(f"Fill in: {', '.join(missing)}")
    return cleaned


# --------------------------------------------------------------------------- values
def read_values(session: Session, entity_type: str, entity_id: UUID) -> dict[str, Any]:
    """The saved values of one record (an empty dict when it has none)."""
    row = session.execute(text(
        "select data from kernel.custom_field_value where entity_type = :t and entity_id = :e"),
        {"t": entity_type, "e": str(entity_id)}).scalar()
    return dict(row) if row else {}


def write_values(session: Session, entity_type: str, entity_id: UUID, values: dict[str, Any], *,
                 company_id: UUID | None = None, check_required: bool = True) -> dict[str, Any]:
    """Save values for one record: the keys given are changed (an empty value clears one), the others stay. Two people
    saving different fields at once both keep their change (the row is locked while it is merged). The caller has
    checked that the actor may edit the record. Returns all the record's values."""
    definitions = definitions_for(session, entity_type, company_id)
    session.execute(text(
        "insert into kernel.custom_field_value (tenant_id, company_id, entity_type, entity_id) "
        "values (kernel.current_tenant(), :c, :t, :e) on conflict (tenant_id, entity_type, entity_id) do nothing"),
        {"c": str(company_id) if company_id else None, "t": entity_type, "e": str(entity_id)})
    current = dict(session.execute(text(
        "select data from kernel.custom_field_value where entity_type = :t and entity_id = :e for update"),
        {"t": entity_type, "e": str(entity_id)}).scalar_one())
    cleaned = validate_values(definitions, values, existing=current, check_required=check_required)
    for key, value in cleaned.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    if len(json.dumps(current)) > 15000:
        raise ValidationFailed("There is too much in the custom fields of this record")
    session.execute(text(
        "update kernel.custom_field_value set data = cast(:d as jsonb), updated_at = now(), "
        "updated_by = :u where entity_type = :t and entity_id = :e"),
        {"d": json.dumps(current), "u": str(user) if (user := get_context().user_id) else None, "t": entity_type,
         "e": str(entity_id)})
    return current


def find_entity_ids(session: Session, entity_type: str, key: str, query: str, limit: int = 50) -> list[UUID]:
    """The records whose searchable text field `key` contains `query` (case-insensitive). For a unit's search box."""
    found = session.execute(text(
        "select v.entity_id from kernel.custom_field_value v join kernel.custom_field_def d "
        "on d.entity_type = v.entity_type and d.key = :k and d.searchable and d.active "
        "where v.entity_type = :t and v.data ->> :k ilike :q escape '\\' limit :n"),
        {"t": entity_type, "k": key, "q": like_pattern(query), "n": min(max(limit, 1), 500)})
    return [r.entity_id for r in found]


# --------------------------------------------------------------------------- personal data
def _keys_of(definitions: list[FieldDef], kind: str) -> set[str]:
    return {d.key for d in definitions if d.kind == kind}


@provides(PERSONAL_DATA)
class CustomFieldData(PersonalDataProvider):
    """Text and date custom fields can hold anything about a person: they are searched, exported and erased like any
    other personal data (an email, phone or id matches exactly; a name loosely)."""

    name = "kernel.custom_fields"

    def find(self, session: Session, company_id: UUID, subject: Subject) -> list[PersonalRecord]:
        values: list[tuple[str, str]] = [(v, "exact") for v in (subject.email, subject.phone, subject.identifier) if v]
        if subject.name:
            values.append((subject.name, "possible"))
        found: dict[UUID, PersonalRecord] = {}
        for value, match in values:
            rows = session.execute(text(
                "select distinct v.id, v.entity_type from kernel.custom_field_value v "
                "cross join lateral jsonb_each_text(v.data) kv(k, val) "
                "join kernel.custom_field_def d on d.entity_type = v.entity_type and d.key = kv.k and d.kind = 'text' "
                "where (v.company_id is null or v.company_id = :c) and "
                + ("lower(kv.val) = lower(:v)" if match == "exact" else "kv.val ilike :v escape '\\'")),
                {"c": str(company_id), "v": value if match == "exact" else like_pattern(value)})
            for r in rows:
                if r.id not in found or match == "exact":
                    found[r.id] = PersonalRecord(self.name, "custom_fields", r.id,
                                                 f"Custom fields of a {r.entity_type}", match, company_id)
        return list(found.values())

    def export(self, session: Session, record: PersonalRecord) -> dict[str, Any]:
        row = session.execute(text("select entity_type, entity_id, data from kernel.custom_field_value where id = :i"),
                              {"i": str(record.record_id)}).first()
        if row is None:
            return {}
        labels = {d.key: d.label for d in list_definitions(session, row.entity_type)}
        return {"entity_type": row.entity_type, "entity_id": str(row.entity_id),
                "fields": {labels.get(k, k): v for k, v in row.data.items()}}

    def anonymise(self, session: Session, record: PersonalRecord, reason: str) -> Outcome:
        row = session.execute(text("select entity_type, data from kernel.custom_field_value where id = :i for update"),
                              {"i": str(record.record_id)}).first()
        if row is None:
            return Outcome("refused", message="Those custom field values no longer exist")
        definitions = list_definitions(session, row.entity_type)
        texts, dates = _keys_of(definitions, "text"), _keys_of(definitions, "date")
        keys = texts | dates
        data = {k: (ERASED if k in texts else v) for k, v in row.data.items() if k not in dates}
        session.execute(text("update kernel.custom_field_value set data = cast(:d as jsonb), updated_at = now() "
                             "where id = :i"), {"d": json.dumps(data), "i": str(record.record_id)})
        return Outcome("anonymised", changed=sorted(k for k in keys if k in row.data),
                       kept=[Kept("number, yes/no and choice fields", "they hold no text that identifies a person")]
                       if any(k not in keys for k in row.data) else [])
