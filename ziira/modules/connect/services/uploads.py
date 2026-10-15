"""Uploading a file to a file-kind connection: drop the file, we work out the layout, show what we found, and the person
confirms. The file may be CSV, Excel, a PDF (text, or a picture read by OCR) or a photo. The layout (header row, which
column is which, how dates and numbers are written) is detected; what the person confirmed is remembered per
connection, so the next upload needs nothing. Records are keyed by their reference, so uploading overlapping files
twice adds nothing twice."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row

from ziira.modules.connect.connectors.files import (
    MOBILE_WORDS,
    FileConnector,
    FileSettings,
    ParsedRow,
    RowIssue,
    RowReader,
    _has_word,
)
from ziira.modules.connect.domain import csvfile, layout, tabular
from ziira.modules.connect.domain.values import DATE_FORMATS, DECIMAL_SEPARATORS
from ziira.modules.connect.public import ENTITIES, Payment, Record
from ziira.modules.connect.repository import connect_repo as repo
from ziira.modules.connect.repository import scan_repo, store
from ziira.modules.connect.services import connections, connectors, scans
from ziira.modules.connect.services.branches import BranchResolver
from ziira.sdk import Session, ValidationFailed, audit_record, company_setting

SAMPLE_ROWS = 8
MAX_ISSUES = 2000
REVIEW_ROWS = 200
MIN_CONFIDENCE = 0.8
MIN_VALID_SHARE = 0.9
MOBILE_SHARE = 0.2                 # how many detail lines must mention mobile money for a statement to be called one


@dataclass
class Preview:
    filename: str
    state: str = "ready"                       # ready | reading | failed | password_required | wrong_password
    message: str = ""
    source: str = "csv"                        # csv | excel | pdf | scan
    delimiter: str = ","
    headers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mapping: dict[str, str | None] = field(default_factory=dict)
    suggested: dict[str, str | None] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    sample: list[dict[str, str]] = field(default_factory=list)
    total_rows: int = 0
    valid_rows: int = 0
    issues: list[RowIssue] = field(default_factory=list)
    issue_count: int = 0
    missing: list[str] = field(default_factory=list)
    records: dict[str, int] = field(default_factory=dict)
    first_moment: datetime | None = None
    last_moment: datetime | None = None
    confidence: float = 0.0
    needs_check: bool = True
    check_reasons: list[str] = field(default_factory=list)
    date_ambiguous: bool = False
    date_examples: list[str] = field(default_factory=list)
    money_in: Decimal | None = None
    money_out: Decimal | None = None
    total: Decimal | None = None
    wrong_kind: dict[str, str] | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    review_rows: list[dict[str, Any]] = field(default_factory=list)
    scan: dict[str, Any] | None = None


@dataclass
class Committed:
    preview: Preview
    counts: dict[str, store.Counts] = field(default_factory=dict)


@dataclass
class Detected:
    kind: str | None
    title: str
    confidence: float
    picture: bool = False
    alternatives: list[dict[str, str]] = field(default_factory=list)
    state: str = "ready"                       # ready | password_required | wrong_password
    message: str = ""


def _file_connector(session: Session, row: Row[Any]) -> FileConnector:
    connector = connectors.connector_for(session, row.kind)
    if not isinstance(connector, FileConnector):
        raise ValidationFailed("This connection reads a live system, not uploaded files")
    return connector


def _file_connectors(session: Session) -> list[FileConnector]:
    return [c for c in connectors.all_connectors(session) if isinstance(c, FileConnector)]


def _vocabulary(session: Session) -> set[str]:
    """Every column name any file kind knows: finds the table in a spreadsheet or PDF before the kind is settled."""
    found: set[str] = set()
    for connector in _file_connectors(session):
        found |= connector.vocabulary()
    return found


def saved_settings(session: Session, row: Row[Any]) -> FileSettings:
    """What the business confirmed before; formats are 'auto' (detected from the file) until something was saved."""
    config = dict(row.config)
    saved = config.get("file")
    timezone = str(company_setting(session, row.company_id, "timezone"))
    if not saved:
        return FileSettings(decimal_separator="auto", date_format="auto", timezone=timezone)
    return FileSettings(
        mapping=dict(saved.get("mapping", {})), decimal_separator=saved.get("decimal_separator", "auto"),
        date_format=saved.get("date_format", "auto"), delimiter=saved.get("delimiter"), timezone=timezone,
        options=dict(saved.get("options", {})))


def save_settings(session: Session, connection_id: UUID, *, mapping: dict[str, str | None],
                  decimal_separator: str, date_format: str, delimiter: str | None, options: dict[str, Any]) -> None:
    """Remember how this connection's files are written, so the next upload needs no choosing."""
    row = connections.get(session, connection_id, manage=True)
    connector = _file_connector(session, row)
    if decimal_separator != "auto" and decimal_separator not in DECIMAL_SEPARATORS:
        raise ValidationFailed("The decimal separator must be '.' or ','")
    if date_format != "auto" and date_format not in DATE_FORMATS:
        raise ValidationFailed("The date format must be iso, dmy or mdy")
    if delimiter is not None and delimiter not in csvfile.DELIMITERS:
        raise ValidationFailed("The delimiter must be a comma, semicolon, tab or bar")
    known = {f.name for f in connector.fields}
    unknown = sorted(set(mapping) - known)
    if unknown:
        raise ValidationFailed(f"Unknown field(s): {', '.join(unknown)}")
    config = {**dict(row.config), "file": {
        "mapping": {k: (v or "") for k, v in mapping.items()}, "decimal_separator": decimal_separator,
        "date_format": date_format, "delimiter": delimiter, "options": options}}
    repo.update_connection(session, connection_id, {"config": config})
    audit_record(session, "update", "connect.connection", connection_id, {"file_settings": True})


# --------------------------------------------------------------------------- which kind of file is it
def _affinity(connector: FileConnector, mapping: dict[str, str | None]) -> int:
    """How well the columns found fit a kind: matched fields count (required ones double), missing needs cost."""
    score = sum(2 if f.required else 1 for f in connector.fields if mapping.get(f.name))
    score -= 3 * sum(1 for f in connector.fields if f.required and not mapping.get(f.name))
    score -= 3 * sum(1 for group in connector.needs_any if not any(mapping.get(n) for n in group))
    return score


def _wrong_kind(session: Session, target: FileConnector, target_mapping: dict[str, str | None],
                shaped: layout.Shaped) -> dict[str, str] | None:
    """The kind this file looks like, when it is not the kind of this connection."""
    if not shaped.header_found:
        return None
    mine = _affinity(target, target_mapping)
    best: tuple[int, FileConnector] | None = None
    for other in _file_connectors(session):
        if other.kind == target.kind or other.family == target.family:
            continue
        guessed = csvfile.suggest_mapping(shaped.headers, [(f.name, f.aliases) for f in other.fields])
        score = _affinity(other, guessed)
        if best is None or score > best[0]:
            best = (score, other)
    if best is None:
        return None
    if best[0] >= mine + 3:
        return {"kind": best[1].kind, "title": best[1].title}
    return None


def _statement_kind(table: tabular.RawTable, shaped: layout.Shaped, mapping: dict[str, str | None]) -> str:
    """bank_statement or mobile_money_statement. Mobile money when the title block or many detail lines name a
    service of that kind, or the file has the provider shape: a code for every line, a status, and money in/out."""
    title = " ".join(" ".join(r.cells) for r in table.rows[:12]).lower()
    if _has_word(title, MOBILE_WORDS):
        return "mobile_money_statement"
    column = mapping.get("description")
    if column and column in shaped.headers:
        index = shaped.headers.index(column)
        lines = [r.cells[index].lower() for r, k in zip(shaped.rows, shaped.kinds, strict=True) if k == "data"][:200]
        if lines and sum(_has_word(line, MOBILE_WORDS) for line in lines) / len(lines) >= MOBILE_SHARE:
            return "mobile_money_statement"
    provider_shape = all(mapping.get(n) for n in ("reference", "status", "money_in", "money_out"))
    return "mobile_money_statement" if provider_shape else "bank_statement"


def detect_kind(session: Session, data: bytes, password: str | None = None) -> Detected:
    """Which kind of file this is, for a person who just dropped it. Pictures are taken to be bank statements (they can
    be changed); a protected PDF needs its password first."""
    try:
        table = tabular.load(data, vocabulary=_vocabulary(session), password=password)
    except tabular.NeedsOcr:
        return Detected("bank_statement", "Bank statement", 0.3, picture=True)
    except tabular.PasswordNeeded as error:
        return Detected(None, "", 0.0, state="wrong_password" if error.wrong else "password_required",
                        message=str(error))
    except csvfile.FileProblem as error:
        raise ValidationFailed(str(error)) from None
    shaped = layout.shape(table, _vocabulary(session), lenient=True,
                          skip_phrases=("opening balance", "closing balance", "total "))
    scored: list[tuple[int, FileConnector, dict[str, str | None]]] = []
    for connector in _file_connectors(session):
        fields = [(f.name, f.aliases) for f in connector.fields]
        guess = layout.guess_mapping(shaped, fields) if connector.family == "statement" else None
        mapping = guess.mapping if guess else csvfile.suggest_mapping(shaped.headers, fields)
        scored.append((_affinity(connector, mapping), connector, mapping))
    scored.sort(key=lambda item: -item[0])
    best_score, best, best_map = scored[0]
    kind = best.kind
    if best.family == "statement":
        kind = _statement_kind(table, shaped, best_map)
    chosen = next((c for c in _file_connectors(session) if c.kind == kind), best)
    second = scored[1][0] if len(scored) > 1 else 0
    confidence = 0.0 if best_score <= 0 else round(min(1.0, 0.5 + (best_score - second) / max(best_score, 1) * 0.5), 2)
    return Detected(chosen.kind if best_score > 0 else None, chosen.title, confidence,
                    alternatives=[{"kind": c.kind, "title": c.title} for s, c, _ in scored[1:4] if s > 0])


# --------------------------------------------------------------------------- reading a file
def _examples(shaped: layout.Shaped, header: str | None, count: int = 3) -> list[str]:
    if not header or header not in shaped.headers:
        return []
    index = shaped.headers.index(header)
    seen: list[str] = []
    for row, kind in zip(shaped.rows, shaped.kinds, strict=True):
        value = row.cells[index].strip()
        if kind == "data" and value and value not in seen:
            seen.append(value[:60])
        if len(seen) >= count:
            break
    return seen


def _totals(records: dict[str, list[Record]]) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    money_in = money_out = total = None
    for recs in records.values():
        for record in recs:
            if isinstance(record, Payment):
                if record.direction == "in":
                    money_in = (money_in or Decimal(0)) + record.amount
                else:
                    money_out = (money_out or Decimal(0)) + record.amount
            else:
                amount = getattr(record, "total", None) if hasattr(record, "total") else getattr(record, "amount", None)
                if isinstance(amount, Decimal):
                    total = (total or Decimal(0)) + amount
    return money_in, money_out, total


def _pending(filename: str, state: str, message: str = "", scan: dict[str, Any] | None = None,
             source: str = "scan") -> Preview:
    return Preview(filename=filename, state=state, message=message, source=source, scan=scan)


def _scan_info(row: Row[Any]) -> dict[str, Any]:
    return {"id": str(row.id), "status": row.status, "pages": row.pages, "pages_done": row.pages_done,
            "error": row.error}


def _read(session: Session, row: Row[Any], connector: FileConnector, table: tabular.RawTable,
          filename: str) -> tuple[Preview, dict[str, list[Record]]]:
    settings = saved_settings(session, row)
    lenient = connector.lenient or table.source != "csv"
    shaped = layout.shape(table, _vocabulary(session), lenient=lenient, skip_phrases=connector.skip_phrases)
    fields = [(f.name, f.aliases) for f in connector.fields]
    separator = settings.decimal_separator if settings.decimal_separator != "auto" \
        else layout.detect_decimal(shaped, shaped.headers)
    guess = layout.guess_mapping(shaped, fields, separator)
    mapping: dict[str, str | None] = {}
    how = dict(guess.how)
    for f in connector.fields:
        chosen = settings.mapping.get(f.name)            # "" means: the business said this field is not in the file
        if chosen in shaped.headers:
            mapping[f.name], how[f.name] = chosen, 1.0
        elif chosen == "":
            mapping[f.name] = None
            how.pop(f.name, None)
        else:
            mapping[f.name] = guess.mapping.get(f.name)
    missing = connector.missing(mapping)
    found = layout.formats_for(shaped, mapping)
    effective = replace(
        settings, mapping=mapping,
        decimal_separator=(found.decimal_separator if settings.decimal_separator == "auto"
                           else settings.decimal_separator),
        date_format=found.date_format if settings.date_format == "auto" else settings.date_format,
        options={**settings.options, **({"ocr": True} if table.ocr else {})})
    if lenient:
        data_rows, joined, dropped = layout.merge_wrapped(shaped, mapping)
    else:
        data_rows, joined, dropped = shaped.rows, 0, 0
    notes = list(shaped.warnings)
    if dropped:
        notes.append(f"{dropped} line(s) that are not transactions (titles, totals, page footers) were skipped.")
    if joined:
        notes.append(f"{joined} wrapped line(s) were joined to the line above.")
    index = {h: i for i, h in enumerate(shaped.headers)}
    parsed = [ParsedRow(r.number, {name: r.cells[index[h]] for name, h in mapping.items() if h}, r.low_confidence)
              for r in data_rows]
    reader = RowReader(effective)
    records: dict[str, list[Record]] = {}
    if not missing:
        records = connector.records(parsed, reader, row.name)
    issues = reader.issues
    moments = [m for recs in records.values() for r in recs
               if isinstance(m := getattr(r, "occurred_at", None), datetime)]
    bad_rows = {i.row for i in issues}
    valid = len(parsed) - len(bad_rows)
    essential = [f.name for f in connector.fields if f.required] + \
                [n for group in connector.needs_any for n in group if mapping.get(n)][:2]
    confidence = 0.0 if missing else round(layout.confidence_of(layout.Guess(mapping, how), essential) *
                                           (valid / len(parsed) if parsed else 0.0), 2)
    ambiguous = found.ambiguous and settings.date_format == "auto"
    reasons: list[str] = []
    if missing:
        reasons.append("missing")
    if confidence < MIN_CONFIDENCE and not missing:
        reasons.append("unsure")
    if parsed and valid / len(parsed) < MIN_VALID_SHARE:
        reasons.append("problems")
    if ambiguous:
        reasons.append("dates")
    if table.ocr:
        reasons.append("picture")
    wrong = _wrong_kind(session, connector, mapping, shaped)
    if wrong:
        reasons.append("wrong_kind")
    by_number = {r.number: r for r in data_rows}
    review = []
    for issue in issues[:REVIEW_ROWS]:
        source_row = by_number.get(issue.row)
        if source_row is not None:
            review.append({"row": issue.row, "problem": issue.message, "cells": list(source_row.cells)})
    money_in, money_out, total = _totals(records)
    simple = connector.simple_fields or tuple(f.name for f in connector.fields if f.required)
    date_header = mapping.get("date") or mapping.get("issue_date")
    return Preview(
        filename=filename, source=table.source, delimiter=table.delimiter or ",", headers=shaped.headers,
        warnings=notes, mapping=mapping, suggested=guess.mapping,
        settings={"decimal_separator": effective.decimal_separator, "date_format": effective.date_format,
                  "delimiter": settings.delimiter, "options": settings.options, "timezone": settings.timezone,
                  "remembered": settings.decimal_separator != "auto" or settings.date_format != "auto"},
        sample=[dict(zip(shaped.headers, r.cells, strict=True)) for r in data_rows[:SAMPLE_ROWS]],
        total_rows=len(parsed), valid_rows=valid, issues=issues[:MAX_ISSUES], issue_count=len(issues), missing=missing,
        records={e: len(r) for e, r in records.items()}, first_moment=min(moments) if moments else None,
        last_moment=max(moments) if moments else None, confidence=confidence, needs_check=bool(reasons),
        check_reasons=reasons, date_ambiguous=ambiguous, date_examples=_examples(shaped, date_header),
        money_in=money_in, money_out=money_out, total=total, wrong_kind=wrong,
        fields=[{"name": f.name, "label": f.label, "required": f.required, "column": mapping.get(f.name),
                 "examples": _examples(shaped, mapping.get(f.name)), "simple": f.name in simple}
                for f in connector.fields],
        review_rows=review), records


def _load(session: Session, row: Row[Any], data: bytes, filename: str, password: str | None,
          scan_id: UUID | None) -> tabular.RawTable | Preview:
    """The file as a table, or a Preview that says what must happen first (password, waiting for the picture reader)."""
    if scan_id is not None:
        scan = scans.get(session, scan_id, row.id)
        if scan.status in ("queued", "reading"):
            return _pending(scan.filename, "reading", scan=_scan_info(scan))
        if scan.status == "failed":
            return _pending(scan.filename, "failed", str(scan.error or ""), _scan_info(scan))
        return scans.table_of(scan)
    settings = saved_settings(session, row)
    try:
        return tabular.load(data, vocabulary=_vocabulary(session), password=password, delimiter=settings.delimiter)
    except tabular.PasswordNeeded as error:
        return _pending("", "wrong_password" if error.wrong else "password_required", str(error), source="pdf")
    except tabular.NeedsOcr as error:
        new = scans.start(session, row.id, data=data, filename=filename, kind=error.kind, pages=error.pages)
        return _pending("", "reading", scan=_scan_info(scans.get(session, new, row.id)))
    except csvfile.FileProblem as error:
        raise ValidationFailed(str(error)) from None


def preview(session: Session, connection_id: UUID, data: bytes, filename: str, *, password: str | None = None,
            scan_id: UUID | None = None) -> Preview:
    """What the file would do: what was found, a sample, and every problem line. Nothing is stored (a picture is
    queued for reading, and shows as 'reading' until the reader has finished)."""
    row = connections.get(session, connection_id, manage=True)
    connector = _file_connector(session, row)
    table = _load(session, row, data, filename, password, scan_id)
    if isinstance(table, Preview):
        table.filename = table.filename or filename
        return table
    return _read(session, row, connector, table, filename)[0]


def _remember(session: Session, row: Row[Any], shown: Preview) -> None:
    """After the first confirmed upload, keep what was found, so the next drop of a file needs no checking."""
    if dict(row.config).get("file"):
        return
    save_settings(session, row.id, mapping=shown.mapping, decimal_separator=str(shown.settings["decimal_separator"]),
                  date_format=str(shown.settings["date_format"]), delimiter=None, options={})


def commit(session: Session, connection_id: UUID, data: bytes, filename: str, *, trigger: str = "upload",
           password: str | None = None, scan_id: UUID | None = None) -> Committed:
    """Store the valid rows of the file. Rows with problems are left out and reported. Safe to repeat."""
    row = connections.get(session, connection_id, manage=True)
    if row.status in ("disconnected", "paused"):
        raise ValidationFailed("This connection is not active")
    connector = _file_connector(session, row)
    table = _load(session, row, data, filename, password, scan_id)
    if isinstance(table, Preview):
        raise ValidationFailed(table.message or "The picture has not been read yet: wait for it to finish, then check "
                                                "what was found and confirm")
    shown, records = _read(session, row, connector, table, filename)
    if shown.missing:
        raise ValidationFailed("Choose the column for: " + ", ".join(shown.missing))
    resolver = BranchResolver(session, connection_id, row.company_id, row.auto_create_branches)
    target = store.Target(connection_id, row.company_id, resolver.resolve)
    done = Committed(shown)
    for entity in [e for e in ENTITIES if e in connector.entities]:
        run_id = repo.start_run(session, connection_id, entity, trigger)
        counts = store.store_records(session, target, entity, records.get(entity, []))
        first = entity == connector.entities[0]
        issue_notes = [f"row {i.row}: {i.message}" for i in shown.issues[:5]] if first else []
        problems = shown.issue_count if first else 0
        repo.finish_run(session, run_id, status="partial" if counts.skipped or problems else "ok", read=counts.read,
                        new=counts.new, changed=counts.changed, skipped=counts.skipped + problems, error=None,
                        notes=[f"File: {filename}", *issue_notes, *counts.notes])
        moments = [m for r in records.get(entity, []) if isinstance(m := getattr(r, "occurred_at", None), datetime)]
        repo.set_cursor(session, connection_id, entity, None, max(moments) if moments else None)
        done.counts[entity] = counts
    now = datetime.now(UTC)
    repo.update_connection(session, connection_id, {"last_sync_at": now, "last_success_at": now, "failures": 0,
                                                    "last_error": None})
    audit_record(session, "upload", "connect.connection", connection_id,
                 {"filename": filename, "rows": shown.total_rows, "problems": shown.issue_count,
                  "source": shown.source})
    _remember(session, row, shown)
    if scan_id is not None:
        scan_repo.delete_scan(session, scan_id)
    return done


__all__ = ["Committed", "Detected", "Preview", "commit", "detect_kind", "preview", "save_settings", "saved_settings"]
