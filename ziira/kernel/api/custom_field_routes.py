"""Custom fields: managing the fields (permission 'customfields.manage') and reading and saving a record's values
(the permissions of the record's own unit, checked for the record's company and branch). See docs/custom-fields.md."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import audit, custom_fields
from ziira.kernel.custom_fields import FieldDef
from ziira.sdk import DB_SESSION, Forbidden, NotFound, RequestContext, Session, request_context, require_permission

router = APIRouter(prefix="/api/v1/custom-fields", tags=["Custom fields"])
manage = Depends(require_permission(custom_fields.PERMISSION))
Kind = Annotated[str, Field(pattern="^(text|number|date|bool|choice)$")]


class CustomFieldEntityOut(BaseModel):
    entity_type: str
    label: str
    unit: str = Field(description="The unit that owns this kind of record")
    view_permission: str
    edit_permission: str


class CustomFieldOut(BaseModel):
    id: UUID
    company_id: UUID | None = Field(description="Null: the whole business")
    entity_type: str
    key: str
    label: str
    kind: str
    choices: list[str]
    required: bool
    searchable: bool
    sort_order: int
    active: bool
    source: str = Field(description="'business', or 'pack:<name>' for a field an industry pack supplied")
    from_pack: bool


class CustomFieldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str = Field(min_length=1, max_length=60)
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    kind: Kind
    choices: list[str] = Field(default_factory=list, max_length=50)
    required: bool = False
    searchable: bool = False
    company_id: UUID | None = None


class CustomFieldPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, min_length=1, max_length=80)
    choices: list[str] | None = Field(default=None, max_length=50)
    required: bool | None = None
    searchable: bool | None = None
    active: bool | None = None


class CustomFieldOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str = Field(min_length=1, max_length=60)
    ids: list[UUID] = Field(max_length=100)


class CustomFieldValuesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any] = Field(max_length=60, description="Field key to value; an empty value clears the field")


class CustomFieldValuesOut(BaseModel):
    fields: list[CustomFieldOut] = Field(description="The active fields that apply to this record, in order")
    values: dict[str, Any]


def _out(d: FieldDef) -> CustomFieldOut:
    return CustomFieldOut(id=d.id, company_id=d.company_id, entity_type=d.entity_type, key=d.key, label=d.label,
                          kind=d.kind,
                    choices=list(d.choices), required=d.required, searchable=d.searchable, sort_order=d.sort_order,
                    active=d.active, source=d.source, from_pack=d.from_pack)


@router.get("/entities", response_model=list[CustomFieldEntityOut], dependencies=[manage])
def list_entities(s: Session = DB_SESSION) -> object:
    """The kinds of record that can have custom fields in this business (from the units that are on)."""
    return [CustomFieldEntityOut(entity_type=e.entity_type, label=e.label, unit=e.entity_type.split(".")[0],
                      view_permission=e.view_permission, edit_permission=e.edit_permission)
            for e in sorted(custom_fields.entities(s).values(), key=lambda e: e.label)]


@router.get("", response_model=list[CustomFieldOut])
def list_fields(entity_type: str | None = Query(default=None, max_length=60), include_inactive: bool = False,
                company_id: UUID | None = None, ctx: RequestContext = Depends(request_context),
                s: Session = DB_SESSION) -> object:
    """The fields. Managers see all of them (`entity_type` optional). Anyone who may open a kind of record sees
    its active fields (`entity_type` required), which is what its form needs."""
    if ctx.has_anywhere(custom_fields.PERMISSION):
        found = (custom_fields.definitions_for(s, entity_type, company_id, include_inactive)
                 if entity_type and company_id else custom_fields.list_definitions(s, entity_type))
        return [_out(d) for d in found if include_inactive or d.active]
    if not entity_type:
        raise Forbidden(f"You do not have permission '{custom_fields.PERMISSION}'")
    kind = custom_fields.entity(s, entity_type)
    if not (ctx.has_anywhere(kind.view_permission) or ctx.has_anywhere(kind.edit_permission)):
        raise Forbidden("You cannot open this kind of record")
    return [_out(d) for d in custom_fields.definitions_for(s, entity_type, company_id)]


@router.post("", response_model=CustomFieldOut, status_code=201, dependencies=[manage])
def create_field(body: CustomFieldIn, s: Session = DB_SESSION) -> object:
    """Add a field to a kind of record."""
    made = custom_fields.create_definition(
        s, entity_type=body.entity_type, key=body.key, label=body.label, kind=body.kind, choices=body.choices,
        required=body.required, searchable=body.searchable, company_id=body.company_id)
    audit.record(s, "create", "kernel.custom_field_def", made.id,
                 {"entity_type": made.entity_type, "key": made.key, "kind": made.kind})
    return _out(made)


@router.put("/order", status_code=204, dependencies=[manage])
def put_order(body: CustomFieldOrderIn, s: Session = DB_SESSION) -> Response:
    """Arrange the fields of a kind of record."""
    custom_fields.reorder(s, body.entity_type, body.ids)
    audit.record(s, "reorder", "kernel.custom_field_def", None, {"entity_type": body.entity_type})
    return Response(status_code=204)


@router.patch("/{field_id}", response_model=CustomFieldOut, dependencies=[manage])
def patch_field(field_id: UUID, body: CustomFieldPatch, s: Session = DB_SESSION) -> object:
    """Rename, change the choices, make required or searchable, hide or show a field. The key and kind never change."""
    changes = body.model_dump(exclude_unset=True)
    made = custom_fields.update_definition(s, field_id, **changes)
    audit.record(s, "update", "kernel.custom_field_def", made.id, {"key": made.key, **changes})
    return _out(made)


@router.delete("/{field_id}", status_code=204, dependencies=[manage])
def delete_field(field_id: UUID, s: Session = DB_SESSION) -> Response:
    """Delete a field the business added (and its values). A pack's field can only be hidden."""
    gone = custom_fields.delete_definition(s, field_id)
    audit.record(s, "delete", "kernel.custom_field_def", gone.id, {"entity_type": gone.entity_type, "key": gone.key})
    return Response(status_code=204)


def _record_scope(s: Session, ctx: RequestContext, entity_type: str, entity_id: UUID, *, edit: bool) -> UUID | None:
    kind = custom_fields.entity(s, entity_type)
    scope = kind.scope(s, entity_id)
    if scope is None:
        raise NotFound("Record not found")
    company_id, branch_id = scope
    wanted = kind.edit_permission if edit else (kind.view_permission or kind.edit_permission)
    if edit or branch_id is not None:
        ctx.require(wanted, company_id=company_id, branch_id=branch_id)
    else:                          # reading a company-wide record: a grant at any level in that company is enough
        allowed = ctx.companies_with(wanted)
        if allowed is not None and company_id not in allowed:
            raise Forbidden(f"You do not have permission '{wanted}' here")
    return company_id


@router.get("/values/{entity_type}/{entity_id}", response_model=CustomFieldValuesOut)
def get_values(entity_type: str, entity_id: UUID, ctx: RequestContext = Depends(request_context),
               s: Session = DB_SESSION) -> object:
    """The custom fields that apply to a record and their values. Needs the permission that opens the record."""
    company_id = _record_scope(s, ctx, entity_type, entity_id, edit=False)
    return CustomFieldValuesOut(fields=[_out(d) for d in custom_fields.definitions_for(s, entity_type, company_id)],
                     values=custom_fields.read_values(s, entity_type, entity_id))


@router.put("/values/{entity_type}/{entity_id}", response_model=CustomFieldValuesOut)
def put_values(entity_type: str, entity_id: UUID, body: CustomFieldValuesIn,
               ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Save values for a record: the keys sent change, the others stay. Needs the permission that edits the record."""
    company_id = _record_scope(s, ctx, entity_type, entity_id, edit=True)
    saved = custom_fields.write_values(s, entity_type, entity_id, body.values, company_id=company_id)
    audit.record(s, "update", "kernel.custom_field_value", entity_id,       # keys only: values may be personal data
                 {"entity_type": entity_type, "keys": sorted(body.values)})
    return CustomFieldValuesOut(
        fields=[_out(d) for d in custom_fields.definitions_for(s, entity_type, company_id)], values=saved)
