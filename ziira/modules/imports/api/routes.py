"""HTTP endpoints for Data Import: the kinds of file, uploading and mapping, the dry run, the commit, the report."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from ziira.modules.imports.api.schemas import (
    BatchOut,
    ColumnOut,
    CountsOut,
    FileCheckOut,
    KindOut,
    MappingIn,
    OptionsOut,
    ReportOut,
    ReverseIn,
    RowOut,
    RowsOut,
    TotalOut,
)
from ziira.modules.imports.domain.files import MAX_BYTES
from ziira.modules.imports.permissions import IMPORTS_MANAGE
from ziira.modules.imports.public import Importer
from ziira.modules.imports.services import batches
from ziira.sdk import DB_SESSION, Session, ValidationFailed, page_limit, page_offset, require_permission

router = APIRouter()
MANAGE = [Depends(require_permission(IMPORTS_MANAGE))]
Status = Literal["pending", "valid", "invalid", "imported", "skipped", "failed", "reverted"]


def _columns(importer: Importer) -> list[ColumnOut]:
    return [ColumnOut(name=c.name, required=c.required, description=c.description, example=c.example, total=c.total)
            for c in importer.columns]


def _kind(importer: Importer) -> KindOut:
    return KindOut(kind=importer.kind, title=importer.title, description=importer.description,
                   permission=importer.permission, reversible=importer.reversible,
                   reversal_note=importer.reversal_note, needs_go_live=importer.needs_go_live,
                   whole_file=importer.whole_file, columns=_columns(importer))


def _batch(detail: batches.BatchDetail) -> BatchOut:
    b = detail.batch
    return BatchOut(
        id=b.id, company_id=b.company_id, kind=b.kind, kind_title=detail.importer.title, filename=b.filename,
        status=b.status, delimiter=b.delimiter, headers=list(b.headers), mapping=dict(b.mapping),
        options=OptionsOut(**b.options), file_check=FileCheckOut(**(b.file_check or {})), warnings=list(b.warnings),
        columns=_columns(detail.importer), counts=CountsOut(**detail.counts), total_rows=sum(detail.counts.values()),
        reversible=detail.importer.reversible, needs_go_live=detail.importer.needs_go_live,
        whole_file=detail.importer.whole_file, created_at=b.created_at, committed_at=b.committed_at,
        finished_at=b.finished_at, reverted_at=b.reverted_at, revert_reason=b.revert_reason,
        source_kind=b.source_kind, source_id=b.source_id)


async def upload_body(request: Request) -> bytes:
    """The raw bytes of the uploaded file (the request body), refused as soon as they pass the size limit."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise ValidationFailed(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB. Split it into smaller files.")
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > MAX_BYTES:
            raise ValidationFailed(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB. "
                                   "Split it into smaller files.")
    return bytes(received)


def _csv(text: str, name: str) -> Response:
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.get("/kinds", response_model=list[KindOut], dependencies=MANAGE)
def get_kinds(session: Session = DB_SESSION) -> object:
    """What can be imported here: one kind per unit that supplies an importer and is switched on for the business."""
    return [_kind(i) for i in batches.usable_importers(session)]


@router.get("/kinds/{kind}/template", response_class=Response, dependencies=MANAGE,
            responses={200: {"content": {"text/csv": {}}}})
def get_template(kind: str, session: Session = DB_SESSION) -> Response:
    """A sample file for this kind: the column names and one example row."""
    importer = batches.get_importer(session, kind)
    return _csv(batches.template_csv(importer), f"import-{importer.kind}-template")


@router.post("/batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE,
             openapi_extra={"requestBody": {"required": True, "content": {
                 "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
def post_batch(kind: str, company_id: UUID, filename: str = "import.csv",
               decimal_separator: Literal[".", ","] = ".", date_format: Literal["iso", "dmy", "mdy"] = "iso",
               as_of: date | None = Query(default=None, description="The go-live date, for opening balances"),
               tolerance: Decimal = Query(default=Decimal(0), ge=0, description="How far a trial balance may be out"),
               body: bytes = Depends(upload_body), session: Session = DB_SESSION) -> object:
    """Upload a CSV file (the request body) to import as `kind` into a company. UTF-8 (with or without a BOM), comma,
    semicolon or tab separated. The reply has the column mapping we suggest; nothing is imported yet. Kinds that bring
    in opening balances need `as_of`, the go-live date."""
    return _batch(batches.create_batch(session, kind=kind, company_id=company_id, filename=filename, data=body,
                                       decimal_separator=decimal_separator, date_format=date_format, as_of=as_of,
                                       tolerance=tolerance))


@router.get("/batches", response_model=list[BatchOut], dependencies=MANAGE)
def get_batches(limit: int = page_limit(), offset: int = page_offset(),
                session: Session = DB_SESSION) -> object:
    """Earlier imports, newest first."""
    return [_batch(batches.get_batch(session, b.id)) for b in batches.list_batches(session, limit=limit, offset=offset)]


@router.get("/batches/{batch_id}", response_model=BatchOut, dependencies=MANAGE)
def get_one_batch(batch_id: UUID, session: Session = DB_SESSION) -> object:
    """One import with its progress (counts of rows by state)."""
    return _batch(batches.get_batch(session, batch_id))


@router.put("/batches/{batch_id}/mapping", response_model=BatchOut, dependencies=MANAGE)
def put_mapping(batch_id: UUID, body: MappingIn, session: Session = DB_SESSION) -> object:
    """Choose the column for each field, and how the file writes numbers and dates. Rows must be checked again."""
    return _batch(batches.set_mapping(session, batch_id, columns=body.columns,
                                      decimal_separator=body.decimal_separator, date_format=body.date_format))


@router.post("/batches/{batch_id}/validate", response_model=BatchOut, dependencies=MANAGE)
def post_validate(batch_id: UUID, session: Session = DB_SESSION) -> object:
    """The dry run: every row is checked and nothing is written. Problems are listed per row."""
    return _batch(batches.validate_batch(session, batch_id))


@router.post("/batches/{batch_id}/commit", response_model=BatchOut, status_code=status.HTTP_202_ACCEPTED,
             dependencies=MANAGE)
def post_commit(batch_id: UUID, confirm: bool = Query(default=False, description="Accept the file's warning"),
                session: Session = DB_SESSION) -> object:
    """Import the valid rows in the background (poll the batch for progress). Safe to ask twice. A trial balance that
    does not balance is imported only with `confirm=true`: the difference goes to opening balance equity."""
    return _batch(batches.commit_batch(session, batch_id, confirm=confirm))


@router.post("/batches/{batch_id}/reverse", response_model=BatchOut, dependencies=MANAGE)
def post_reverse(batch_id: UUID, body: ReverseIn, session: Session = DB_SESSION) -> object:
    """Undo a finished import of opening balances: everything it created is reversed, or nothing (with the reason)."""
    return _batch(batches.reverse_batch(session, batch_id, reason=body.reason))


@router.get("/batches/{batch_id}/rows", response_model=RowsOut, dependencies=MANAGE)
def get_rows(batch_id: UUID, row_status: Status | None = Query(default=None, alias="status"),
             only_errors: bool = False, limit: int = page_limit(50), offset: int = page_offset(),
             session: Session = DB_SESSION) -> object:
    """The rows of the file with what became of each; `only_errors` shows the rejected and failed ones."""
    total, rows = batches.list_rows(session, batch_id, status=row_status, only_errors=only_errors, limit=limit,
                                    offset=offset)
    return RowsOut(total=total, rows=[RowOut(row_no=r.row_no, status=r.status,  # type: ignore[arg-type]
                                             errors=r.errors, raw=r.raw, values=r.values, record_id=r.record_id)
                                      for r in rows])


@router.get("/batches/{batch_id}/report", response_model=ReportOut, dependencies=MANAGE)
def get_report(batch_id: UUID, session: Session = DB_SESSION) -> object:
    """Reconciliation: rows imported, skipped and failed, and the file's sums against what Ziira now holds."""
    r = batches.report(session, batch_id)
    return ReportOut(
        batch=_batch(batches.get_batch(session, batch_id)), rows_in_file=r.rows_in_file,
        totals=[TotalOut(label=t.label, in_file=t.in_file, expected=t.expected, in_ziira=t.in_ziira,
                         not_imported=t.not_imported, difference=t.difference, matches=t.matches,
                         money=t.label in r.importer.money_totals) for t in r.totals],
        problems=r.problems, reconciled=not r.problems)


@router.get("/batches/{batch_id}/rejected.csv", response_class=Response, dependencies=MANAGE,
            responses={200: {"content": {"text/csv": {}}}})
def get_rejected(batch_id: UUID, session: Session = DB_SESSION) -> Response:
    """The rejected and failed rows with an `error` column. Fix them and upload the file again."""
    return _csv(batches.rejected_csv(session, batch_id), f"rejected-rows-{batch_id}")


@router.delete("/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=MANAGE)
def delete_batch(batch_id: UUID, session: Session = DB_SESSION) -> Response:
    """Discard an import that created nothing. Only the staged file goes; no business record is touched."""
    batches.discard_batch(session, batch_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
