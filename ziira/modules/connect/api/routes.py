"""HTTP endpoints for Connectors: the catalogue of systems that can be connected, connections and their history, branch
mapping, file uploads, and what Intelligence can see (coverage). Reading another system never happens in a request:
'sync' queues a background job."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from ziira.modules.connect.api.oauth_routes import public_router as oauth_public_router
from ziira.modules.connect.api.oauth_routes import router as oauth_router
from ziira.modules.connect.api.schemas import (
    BranchMapIn,
    BranchMapOut,
    ConnectionDetailOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionPatch,
    ConnectorKindOut,
    CoverageOut,
    DetectOut,
    DisconnectIn,
    DisconnectOut,
    FileSettingsIn,
    FileUploadOut,
    OcrStatusOut,
    PreviewOut,
    RowIssueOut,
    ScanFixIn,
    ScanOut,
    SyncIn,
    SyncOut,
    SyncRunOut,
    TestOut,
)
from ziira.modules.connect.domain.csvfile import MAX_BYTES
from ziira.modules.connect.permissions import CONNECT_MANAGE, CONNECT_VIEW
from ziira.modules.connect.repository import connect_repo as repo
from ziira.modules.connect.services import branches, connections, connectors, coverage, scans, sync, uploads, views
from ziira.sdk import (
    DB_SESSION,
    Session,
    ValidationFailed,
    check_company,
    current_context,
    page_limit,
    page_offset,
    require_permission,
)

router = APIRouter()
router.include_router(oauth_router)
# the vendor's redirect carries no bearer token: its signed state is the proof
public_router = oauth_public_router
VIEW = [Depends(require_permission(CONNECT_VIEW))]
MANAGE = [Depends(require_permission(CONNECT_MANAGE))]


def _kind(k: connectors.Kind) -> ConnectorKindOut:
    return ConnectorKindOut(
        kind=k.kind, title=k.title, description=k.description, group=k.group, entities=list(k.entities),
        config_fields=[{"name": f.name, "label": f.label, "secret": f.secret, "required": f.required, "help": f.help,
                        "example": f.example} for f in k.config_fields],  # type: ignore[misc]
        needs_oauth=k.needs_oauth, freshness=k.freshness,  # type: ignore[arg-type]
        how_to=k.how_to, file_fields=list(k.file_fields))  # type: ignore[arg-type]


def _preview(p: uploads.Preview) -> PreviewOut:
    return PreviewOut(
        filename=p.filename, state=p.state, message=p.message, source=p.source,  # type: ignore[arg-type]
        delimiter=p.delimiter, headers=p.headers, warnings=p.warnings, mapping=p.mapping,
        suggested=p.suggested, settings=p.settings, sample=p.sample, total_rows=p.total_rows, valid_rows=p.valid_rows,
        issues=[RowIssueOut(row=i.row, message=i.message) for i in p.issues], issue_count=p.issue_count,
        missing=p.missing, records=p.records, first_moment=p.first_moment, last_moment=p.last_moment,
        confidence=p.confidence, needs_check=p.needs_check, check_reasons=p.check_reasons,
        date_ambiguous=p.date_ambiguous, date_examples=p.date_examples, money_in=p.money_in, money_out=p.money_out,
        total=p.total, wrong_kind=p.wrong_kind, fields=p.fields,  # type: ignore[arg-type]
        review_rows=p.review_rows, scan=p.scan)  # type: ignore[arg-type]


async def upload_body(request: Request) -> bytes:
    """The raw bytes of the uploaded file (the request body), refused as soon as they pass the size limit."""
    too_big = f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB. Split it into smaller files."
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise ValidationFailed(too_big)
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > MAX_BYTES:
            raise ValidationFailed(too_big)
    return bytes(received)


@router.get("/kinds", response_model=list[ConnectorKindOut], dependencies=VIEW)
def get_kinds(session: Session = DB_SESSION) -> object:
    """The systems that can be connected: ERPs, and statements and exports (grouped), with what each needs and gives."""
    return [_kind(k) for k in connectors.catalogue(session)]


@router.get("/connections", response_model=list[ConnectionOut], dependencies=VIEW)
def get_connections(session: Session = DB_SESSION) -> object:
    """The connections the user may see, oldest first."""
    scope = current_context().companies_with(CONNECT_VIEW)
    return [views.connection_out(session, r) for r in repo.list_connections(session, scope)]


@router.post("/connections", response_model=ConnectionDetailOut, status_code=status.HTTP_201_CREATED,
             dependencies=MANAGE)
def post_connection(body: ConnectionIn, session: Session = DB_SESSION) -> object:
    """Connect a system. Secrets in `config` are stored encrypted and never shown again."""
    connection_id = connections.create(
        session, company_id=body.company_id, kind=body.kind, name=body.name, fields=body.config,
        auto_create_branches=body.auto_create_branches, sync_every_minutes=body.sync_every_minutes)
    return views.connection_detail(session, connections.get(session, connection_id))


@router.get("/coverage", response_model=CoverageOut, dependencies=VIEW)
def get_coverage(company_id: UUID, session: Session = DB_SESSION) -> object:
    """What Intelligence can check with what is connected today, by area, and what to connect to check more."""
    current_context().require(CONNECT_VIEW, company_id=company_id)
    check_company(session, company_id)
    return coverage.coverage(session, company_id)


@router.get("/connections/{connection_id}", response_model=ConnectionDetailOut, dependencies=VIEW)
def get_connection(connection_id: UUID, session: Session = DB_SESSION) -> object:
    return views.connection_detail(session, connections.get(session, connection_id))


@router.patch("/connections/{connection_id}", response_model=ConnectionDetailOut, dependencies=MANAGE)
def patch_connection(connection_id: UUID, body: ConnectionPatch, session: Session = DB_SESSION) -> object:
    """Rename, change settings (a blank secret keeps the one stored), the freshness window, or the branch choice."""
    connections.update(session, connection_id, name=body.name, fields=body.config,
                       auto_create_branches=body.auto_create_branches, sync_every_minutes=body.sync_every_minutes)
    return views.connection_detail(session, connections.get(session, connection_id))


@router.post("/connections/{connection_id}/test", response_model=TestOut, dependencies=MANAGE)
def post_test(connection_id: UUID, session: Session = DB_SESSION) -> object:
    """Try the credentials with the lightest read the system offers. Changes nothing anywhere."""
    result = connections.test(session, connection_id)
    return TestOut(ok=result.ok, message=result.message, details=result.details)


@router.post("/connections/{connection_id}/sync", response_model=SyncOut, status_code=status.HTTP_202_ACCEPTED,
             dependencies=MANAGE)
def post_sync(connection_id: UUID, body: SyncIn | None = None, session: Session = DB_SESSION) -> object:
    """Read the system now: queued for the background worker, so this reply is immediate."""
    row = connections.get(session, connection_id, manage=True)
    if row.status == "disconnected":
        raise ValidationFailed("This connection is disconnected")
    if connectors.is_file_kind(connectors.connector_for(session, row.kind)):
        raise ValidationFailed("This connection reads uploaded files: upload one instead")
    return SyncOut(queued=sync.queue_sync(session, connection_id, full=bool(body and body.full)))


@router.post("/connections/{connection_id}/pause", response_model=ConnectionDetailOut, dependencies=MANAGE)
def post_pause(connection_id: UUID, session: Session = DB_SESSION) -> object:
    connections.pause(session, connection_id)
    return views.connection_detail(session, connections.get(session, connection_id))


@router.post("/connections/{connection_id}/resume", response_model=ConnectionDetailOut, dependencies=MANAGE)
def post_resume(connection_id: UUID, session: Session = DB_SESSION) -> object:
    connections.resume(session, connection_id)
    return views.connection_detail(session, connections.get(session, connection_id))


@router.post("/connections/{connection_id}/disconnect", response_model=DisconnectOut, dependencies=MANAGE)
def post_disconnect(connection_id: UUID, body: DisconnectIn, session: Session = DB_SESSION) -> object:
    """Stop reading the system and forget its key. With `delete_data` everything read from it is deleted too."""
    return DisconnectOut(removed=connections.disconnect(session, connection_id, delete_data=body.delete_data))


@router.get("/connections/{connection_id}/runs", response_model=list[SyncRunOut], dependencies=VIEW)
def get_runs(connection_id: UUID, limit: int = page_limit(), offset: int = page_offset(),
             session: Session = DB_SESSION) -> object:
    """The history of reads: what was read, how much was new or changed, what was skipped and why."""
    connections.get(session, connection_id)
    return [SyncRunOut(id=r.id, entity=r.entity, trigger=r.trigger, started_at=r.started_at, finished_at=r.finished_at,
                   status=r.status, records_read=r.records_read, records_new=r.records_new,
                   records_changed=r.records_changed, records_skipped=r.records_skipped, error=r.error,
                   notes=list(r.notes)) for r in repo.list_runs(session, connection_id, limit, offset)]


@router.get("/connections/{connection_id}/counts", response_model=dict[str, int], dependencies=VIEW)
def get_counts(connection_id: UUID, session: Session = DB_SESSION) -> object:
    """How many records of each kind have been read from the system."""
    connections.get(session, connection_id)
    return repo.entity_counts(session, connection_id)


@router.get("/connections/{connection_id}/branches", response_model=list[BranchMapOut], dependencies=VIEW)
def get_branches(connection_id: UUID, session: Session = DB_SESSION) -> object:
    """Which Ziira branch each branch (store, till) of the other system is. Unmapped ones are company level."""
    connections.get(session, connection_id)
    return [BranchMapOut(external_ref=m.external_ref, external_name=m.external_name, branch_id=m.branch_id,
                         branch_name=m.branch_name, ignored=m.ignored)
            for m in repo.list_branch_map(session, connection_id)]


@router.put("/connections/{connection_id}/branches", response_model=list[BranchMapOut], dependencies=MANAGE)
def put_branch(connection_id: UUID, body: BranchMapIn, session: Session = DB_SESSION) -> object:
    """Map a branch of the other system to a Ziira branch, ignore it, or have a Ziira branch made for it."""
    row = connections.get(session, connection_id, manage=True)
    target = body.branch_id
    if body.create_branch:
        if body.branch_id is not None or body.ignored:
            raise ValidationFailed("Choose one: map to a branch, ignore it, or create a branch")
        current_context().require("organisation.manage", company_id=row.company_id)
        known = {m.external_ref: m for m in repo.list_branch_map(session, connection_id)}
        if body.external_ref not in known:
            raise ValidationFailed("That branch of the other system is not known yet")
        theirs = known[body.external_ref]
        target = branches.create_branch_for(session, row.company_id, theirs.external_name or body.external_ref)
    branches.set_mapping(session, connection_id, body.external_ref, branch_id=target, ignored=body.ignored)
    return get_branches(connection_id, session)


@router.put("/connections/{connection_id}/file-settings", status_code=status.HTTP_204_NO_CONTENT, dependencies=MANAGE)
def put_file_settings(connection_id: UUID, body: FileSettingsIn, session: Session = DB_SESSION) -> Response:
    """Remember which column is which, and how this connection's files write numbers and dates."""
    uploads.save_settings(session, connection_id, mapping=body.mapping, decimal_separator=body.decimal_separator,
                          date_format=body.date_format, delimiter=body.delimiter, options=body.options)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/files/detect", response_model=DetectOut, dependencies=MANAGE,
             openapi_extra={"requestBody": {"required": True, "content": {
                 "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
def post_detect(body: bytes = Depends(upload_body), x_file_password: str | None = Header(default=None),
                session: Session = DB_SESSION) -> object:
    """Which kind of file this is (a bank statement, a mobile-money statement, a sales export ...), so a person can
    just drop it. Stores nothing. A protected PDF needs its password in the `X-File-Password` header."""
    found = uploads.detect_kind(session, body, x_file_password)
    return DetectOut(kind=found.kind, title=found.title, confidence=found.confidence, picture=found.picture,
                     alternatives=found.alternatives,  # type: ignore[arg-type]
                     state=found.state, message=found.message)  # type: ignore[arg-type]


@router.get("/ocr", response_model=OcrStatusOut, dependencies=VIEW)
def get_ocr(session: Session = DB_SESSION) -> object:
    """Whether pictures (scanned statements, photos) can be read on this server."""
    reason = scans.why_unavailable(session)
    return OcrStatusOut(available=reason is None, message=reason or "Pictures can be read.")


@router.get("/connections/{connection_id}/scans/{scan_id}", response_model=ScanOut, dependencies=MANAGE)
def get_scan(connection_id: UUID, scan_id: UUID, session: Session = DB_SESSION) -> object:
    """How far the reading of a picture has got (poll this while the preview says 'reading')."""
    connections.get(session, connection_id, manage=True)
    row = scans.get(session, scan_id, connection_id)
    return ScanOut(id=row.id, status=row.status, pages=row.pages, pages_done=row.pages_done, error=row.error)


@router.patch("/connections/{connection_id}/scans/{scan_id}", status_code=status.HTTP_204_NO_CONTENT,
              dependencies=MANAGE)
def patch_scan(connection_id: UUID, scan_id: UUID, body: ScanFixIn, session: Session = DB_SESSION) -> Response:
    """Correct cells of a picture that was read wrongly (before confirming it)."""
    connections.get(session, connection_id, manage=True)
    changes: dict[int, dict[int, str]] = {}
    for fix in body.fixes:
        changes.setdefault(fix.row, {})[fix.column] = fix.value
    scans.correct(session, scan_id, connection_id, changes)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connections/{connection_id}/upload", response_model=FileUploadOut, dependencies=MANAGE,
             openapi_extra={"requestBody": {"required": True, "content": {
                 "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
def post_upload(connection_id: UUID, filename: str = "upload.csv",
                mode: Literal["preview", "commit"] = Query(default="preview", description="preview stores nothing"),
                scan_id: UUID | None = Query(default=None, description="a picture already uploaded: send no body"),
                x_file_password: str | None = Header(default=None, description="opens a protected PDF; never stored"),
                body: bytes = Depends(upload_body), session: Session = DB_SESSION) -> object:
    """Upload a file (the request body): CSV, Excel, PDF or a photo. `preview` shows what was found (layout worked out
    automatically), a sample and every problem line, and stores nothing; `commit` stores the valid rows. Uploading
    overlapping files again adds nothing twice. A picture is read in the background: the preview says 'reading' with a
    `scan` to poll; then send the same request with `scan_id` and no body."""
    if mode == "preview":
        shown = uploads.preview(session, connection_id, body, filename, password=x_file_password, scan_id=scan_id)
        return FileUploadOut(preview=_preview(shown), committed=False, new=0, changed=0, skipped=0)
    done = uploads.commit(session, connection_id, body, filename, password=x_file_password, scan_id=scan_id)
    return FileUploadOut(preview=_preview(done.preview), committed=True,
                     new=sum(c.new for c in done.counts.values()), changed=sum(c.changed for c in done.counts.values()),
                     skipped=sum(c.skipped for c in done.counts.values()) + done.preview.issue_count)
