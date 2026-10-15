"""Branches of the other system: which Ziira branch each one is (or that it is ignored), and creating branches
automatically when the business chose that. Records of an unmapped branch are kept at company level."""

import re
from uuid import UUID, uuid4

from sqlalchemy import text

from ziira.modules.connect.repository import connect_repo as repo
from ziira.sdk import (
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
)

CODE_MAX = 10


class BranchResolver:
    """Maps a source branch reference to a Ziira branch for one connection. New references are noted (so the business
    sees them in the UI); with `auto_create` each gets a branch of its own."""

    def __init__(self, session: Session, connection_id: UUID, company_id: UUID, auto_create: bool) -> None:
        self.session = session
        self.connection_id = connection_id
        self.company_id = company_id
        self.auto_create = auto_create
        self.mapping = repo.get_branch_map(session, connection_id)
        self.names: dict[str, str] = {}

    def note_name(self, ref: str, name: str) -> None:
        """A branch record told us its name: remember it, and make sure it has a map row."""
        self.names[ref] = name
        self._ensure(ref)
        repo.add_branch_map(self.session, self.connection_id, ref, name, None)

    def resolve(self, ref: str | None) -> tuple[UUID | None, bool]:
        """(Ziira branch or None, ignored) for a source branch reference."""
        if not ref or not ref.strip():
            return None, False
        ref = ref.strip()
        self._ensure(ref)
        return self.mapping[ref]

    def _ensure(self, ref: str) -> None:
        if ref in self.mapping:
            if self.mapping[ref][0] is None and not self.mapping[ref][1] and self.auto_create:
                self._create(ref)
            return
        self.mapping[ref] = (None, False)
        repo.add_branch_map(self.session, self.connection_id, ref, self.names.get(ref), None)
        if self.auto_create:
            self._create(ref)

    def _create(self, ref: str) -> None:
        name = self.names.get(ref) or ref
        branch_id = create_branch_for(self.session, self.company_id, name)
        repo.set_branch_map(self.session, self.connection_id, ref, branch_id, False)
        self.mapping[ref] = (branch_id, False)


def create_branch_for(session: Session, company_id: UUID, name: str) -> UUID:
    """A new Ziira branch named like the source's, with a code made from the name (made unique with a number)."""
    base = re.sub(r"[^A-Z0-9]", "", name.upper())[:6] or "BR"
    taken = {r.code for r in session.execute(text("select code from kernel.branch where company_id = :c"),
                                             {"c": str(company_id)})}
    code, n = base, 1
    while code in taken:
        n += 1
        code = f"{base[:CODE_MAX - len(str(n))]}{n}"
    branch_id = uuid4()
    session.execute(text(
        "insert into kernel.branch (id, tenant_id, company_id, code, name) values "
        "(:i, kernel.current_tenant(), :c, :k, :n)"),
        {"i": str(branch_id), "c": str(company_id), "k": code, "n": name[:200]})
    audit_record(session, "create", "kernel.branch", branch_id,
                 {"company_id": str(company_id), "code": code, "name": name[:200], "source": "connect"})
    return branch_id


def set_mapping(session: Session, connection_id: UUID, ref: str, *, branch_id: UUID | None, ignored: bool) -> None:
    """Map a source branch to a Ziira branch, or ignore it (or leave it unmapped: both None/False)."""
    from ziira.modules.connect.permissions import CONNECT_MANAGE

    connection = repo.get_connection(session, connection_id)
    if connection is None:
        raise NotFound("Connection not found")
    current_context().require(CONNECT_MANAGE, company_id=connection.company_id)
    if ignored and branch_id is not None:
        raise ValidationFailed("A branch is either mapped or ignored, not both")
    if branch_id is not None:
        check_company(session, connection.company_id, branch_id)
    if repo.set_branch_map(session, connection_id, ref, branch_id, ignored) == 0:
        raise NotFound("That branch of the other system is not known yet")
    repo.apply_branch_to_records(session, connection_id, ref, branch_id)
    audit_record(session, "update", "connect.branch_map", connection_id,
                 {"ref": ref, "branch_id": str(branch_id) if branch_id else None, "ignored": ignored})
