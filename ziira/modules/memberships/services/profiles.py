"""Use cases: the member's profile (member number, card, photo, emergency contact, trial), households with one payer,
and blocking entry.

A profile is the gym or studio side of a Customers record: one per customer per company. The number is the member
number printed on the card and in the QR code. No health data is kept here, only what the front desk needs."""

import re
from datetime import date
from typing import Any
from uuid import UUID

from ziira.modules.crm.public import CustomerView, find_customer, search_customers
from ziira.modules.memberships.permissions import MANAGE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    next_document_number,
)

CARD = re.compile(r"^[A-Za-z0-9._:/-]{1,40}$")
LIFECYCLES = ("prospect", "trial", "member", "former")
EDITABLE = ("branch_id", "date_of_birth", "emergency_name", "emergency_phone", "emergency_relation", "photo_file_id",
            "source", "referred_by_customer_id", "tags", "notes")


def clean_card(value: str | None) -> str | None:
    """A card, tag or wristband number as typed by a reader: no spaces, upper case. Empty: none."""
    cleaned = "".join((value or "").split()).upper()
    if not cleaned:
        return None
    if not CARD.match(cleaned):
        raise ValidationFailed("A card number has up to 40 letters, digits or - . _ : /")
    return cleaned


def by_customer(session: Session, customer_id: UUID) -> repo.Row | None:
    return repo.one(session, "select * from memberships.profile where customer_id = :c", c=customer_id)


def ensure_profile(session: Session, company_id: UUID, customer_id: UUID, *, branch_id: UUID | None = None,
                   lifecycle: str | None = None, source: str | None = None) -> repo.Row:
    """The customer's profile, made (with the next member number) when there is none. The caller has checked access."""
    found = by_customer(session, customer_id)
    if found is not None:
        return found
    ctx = current_context()
    repo.scalar(session, "select cast(pg_advisory_xact_lock(hashtextextended(:k, 0)) as text)",
                k=f"profile:{company_id}:{customer_id}")
    found = by_customer(session, customer_id)
    if found is not None:
        return found
    return repo.insert(session, "profile", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "branch_id": branch_id,
        "customer_id": customer_id, "lifecycle": lifecycle or "member", "source": source,
        "number": next_document_number(session, company_id=company_id, branch_id=None, doc_type="member_profile",
                                       prefix="M")})


def get_profile(session: Session, profile_id: UUID) -> repo.Row:
    return common.get_row(session, "profile", profile_id, "Member")


def profile_of_customer(session: Session, customer_id: UUID) -> repo.Row:
    """The customer's profile; one is made if the person may manage members and there is none yet."""
    customer = common.customer_of_any(session, customer_id)
    common.check_visible(customer.company_id, None, "Member")
    found = by_customer(session, customer_id)
    if found is None:
        common.require_in_company(MANAGE, customer.company_id)
        found = ensure_profile(session, customer.company_id, customer_id)
    return found


def with_customer(session: Session, rows: list[repo.Row]) -> list[repo.Row]:
    names = common.customer_names(session, {r["customer_id"] for r in rows})
    out: list[repo.Row] = []
    for r in rows:
        c: CustomerView | None = names.get(r["customer_id"])
        out.append({**r, "customer_name": c.name if c else None, "customer_code": c.code if c else None,
                    "phone": c.phone if c else None, "email": c.email if c else None})
    return out


def list_profiles(session: Session, *, company_id: UUID, search: str | None = None, lifecycle: str | None = None,
                  group_id: UUID | None = None, limit: int = 50, offset: int = 0) -> list[repo.Row]:
    """Members of a company, by name, phone, member number or card number."""
    common.check_visible(company_id, None, "Company")
    clause, params = repo.scope_sql(common.view_scopes())
    ids: list[str] | None = None
    typed = (search or "").strip()
    if typed:
        found = {c.id for c in search_customers(session, company_id, typed, 50)}
        ids = [str(i) for i in found]
    rows = repo.many(
        session,
        f"select * from memberships.profile where {clause} and company_id = :c "
        "and (cast(:l as text) is null or lifecycle = :l) and (cast(:g as uuid) is null or group_id = :g) "
        "and (cast(:q as text) is null or number ilike :qp or card_number = upper(:q) "
        "     or customer_id = any(cast(:ids as uuid[]))) order by number limit :n offset :o",
        c=company_id, l=lifecycle, g=group_id, q=typed or None, qp=f"{typed}%", ids=ids or [], n=min(limit, 200),
        o=offset, **params)
    return with_customer(session, rows)


def update_profile(session: Session, customer_id: UUID, **changes: Any) -> repo.Row:
    """Change a member's details. A card number is unique in the company. Needs 'memberships.manage'."""
    profile = profile_of_customer(session, customer_id)
    company_id = profile["company_id"]
    common.require_in_company(MANAGE, company_id)
    values: repo.Row = {k: v for k, v in changes.items() if k in EDITABLE + ("card_number",)}
    if "card_number" in values:
        card = clean_card(values["card_number"])
        values["card_number"] = card
        if card is not None and repo.one(
                session, "select 1 as x from memberships.profile where company_id = :c and card_number = :n "
                         "and id <> :i", c=company_id, n=card, i=profile["id"]) is not None:
            raise Conflict("That card number belongs to another member")
    if values.get("photo_file_id"):
        from ziira.sdk import files

        info = files.get_file(session, values["photo_file_id"])
        if info.entity_type != "memberships.profile" or info.entity_id != profile["id"] or info.kind != "image":
            raise ValidationFailed("The photo must be a picture attached to this member")
    if values.get("branch_id"):
        check_company(session, company_id, values["branch_id"])
    if values.get("referred_by_customer_id") is not None:
        if values["referred_by_customer_id"] == customer_id:
            raise ValidationFailed("A member cannot refer themselves")
        common.customer_of_any(session, values["referred_by_customer_id"])
    for key in ("emergency_name", "emergency_phone", "emergency_relation", "source", "notes"):
        if key in values:
            values[key] = (str(values[key] or "")).strip()[:300 if key != "notes" else 1000] or None
    if "tags" in values:
        values["tags"] = sorted({str(t).strip()[:40] for t in (values["tags"] or []) if str(t).strip()})[:20]
    saved = repo.update(session, "profile", profile["id"], {**values, "updated_by": current_context().user_id})
    audit_record(session, "update", "memberships.profile", profile["id"],
                 {k: ("[photo]" if k == "photo_file_id" else str(v)[:80]) for k, v in values.items()
                  if k not in ("emergency_phone", "emergency_name", "notes")})
    return saved


def set_block(session: Session, customer_id: UUID, *, blocked: bool, reason: str | None) -> repo.Row:
    """Stop (or allow again) entry for a member whatever their plan says, with a reason. Needs 'memberships.manage'."""
    profile = profile_of_customer(session, customer_id)
    common.require_in_company(MANAGE, profile["company_id"])
    why = (reason or "").strip()
    if blocked and not why:
        raise ValidationFailed("Say why entry is stopped")
    saved = repo.update(session, "profile", profile["id"], {
        "access_blocked": blocked, "block_reason": why[:300] if blocked else None,
        "updated_by": current_context().user_id})
    audit_record(session, "block" if blocked else "unblock", "memberships.profile", profile["id"], {"reason": why})
    return saved


def set_lifecycle(session: Session, profile_id: UUID, lifecycle: str, *, trial_ends_on: date | None = None) -> None:
    """Move a profile along (the services call this; it checks nothing about the person)."""
    values: repo.Row = {"lifecycle": lifecycle}
    if lifecycle == "trial":
        values.update({"trial_started_on": common.today(session, repo.scalar(
            session, "select company_id from memberships.profile where id = :i", i=profile_id)),
            "trial_ends_on": trial_ends_on})
    repo.update(session, "profile", profile_id, values)


def refresh_lifecycle(session: Session, customer_id: UUID) -> None:
    """After a membership starts or ends: 'member' while any membership is live (a trial plan alone is 'trial'),
    'former' when the person has had one and none is live."""
    profile = by_customer(session, customer_id)
    if profile is None:
        return
    live = repo.many(session, "select is_trial from memberships.member where customer_id = :c "
                              "and status in ('active', 'paused', 'frozen')", c=customer_id)
    if live:
        value = "trial" if all(r["is_trial"] for r in live) else "member"
    elif profile["lifecycle"] in ("trial", "member"):
        value = "former"
    else:
        value = profile["lifecycle"]
    if value != profile["lifecycle"]:
        repo.update(session, "profile", profile["id"], {"lifecycle": value})


# --------------------------------------------------------------------------- households and companies
def list_groups(session: Session, company_id: UUID, limit: int = 100, offset: int = 0) -> list[repo.Row]:
    common.check_visible(company_id, None, "Company")
    rows = repo.many(session, "select g.*, (select count(*) from memberships.profile p where p.group_id = g.id) "
                              "as member_count from memberships.account_group g where g.company_id = :c "
                              "order by g.status, g.name limit :l offset :o", c=company_id, l=min(limit, 200), o=offset)
    names = common.customer_names(session, {r["payer_customer_id"] for r in rows})
    return [{**r, "payer_name": names[r["payer_customer_id"]].name if r["payer_customer_id"] in names else None}
            for r in rows]


def get_group(session: Session, group_id: UUID) -> repo.Row:
    group = common.get_row(session, "account_group", group_id, "Group")
    members = repo.many(session, "select * from memberships.profile where group_id = :g order by number", g=group_id)
    payer = find_customer(session, group["payer_customer_id"])
    return {**group, "payer_name": payer.name if payer else None, "members": with_customer(session, members),
            "member_count": len(members)}


def create_group(session: Session, *, company_id: UUID, name: str, kind: str, payer_customer_id: UUID,
                 notes: str | None = None) -> repo.Row:
    """A family or company paid for by one customer. Needs 'memberships.manage'."""
    common.require_in_company(MANAGE, company_id)
    check_company(session, company_id)
    if kind not in ("household", "corporate"):
        raise ValidationFailed("A group is a household or a corporate account")
    cleaned = " ".join(name.split())[:200]
    if not cleaned:
        raise ValidationFailed("Name the group")
    common.customer_of(session, company_id, payer_customer_id)
    ctx = current_context()
    group = repo.insert(session, "account_group", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "name": cleaned,
        "kind": kind, "payer_customer_id": payer_customer_id, "notes": (notes or "").strip()[:500] or None})
    audit_record(session, "create", "memberships.account_group", group["id"], {"name": cleaned, "kind": kind})
    return group


def update_group(session: Session, group_id: UUID, *, name: str | None = None, payer_customer_id: UUID | None = None,
                 notes: str | None = None, status: str | None = None) -> repo.Row:
    """Rename a group, change who pays (from the next invoice), or close it. Needs 'memberships.manage'."""
    group = repo.get(session, "account_group", group_id, lock=True)
    if group is None:
        raise NotFound("Group not found")
    common.check_visible(group["company_id"], None, "Group")
    common.require_in_company(MANAGE, group["company_id"])
    values: repo.Row = {}
    if name is not None:
        values["name"] = " ".join(name.split())[:200] or group["name"]
    if payer_customer_id is not None:
        common.customer_of(session, group["company_id"], payer_customer_id)
        values["payer_customer_id"] = payer_customer_id
    if notes is not None:
        values["notes"] = notes.strip()[:500] or None
    if status is not None:
        if status not in ("active", "closed"):
            raise ValidationFailed("A group is active or closed")
        values["status"] = status
    saved = repo.update(session, "account_group", group_id, {**values, "updated_by": current_context().user_id})
    if payer_customer_id is not None:
        # memberships that follow the group's payer are re-pointed; invoices already issued stay as they are
        repo.run(session, "update memberships.member m set billing_customer_id = :p, updated_at = now() "
                          "from memberships.profile pr where pr.customer_id = m.customer_id and pr.group_id = :g "
                          "and m.status in ('active', 'paused', 'frozen') and m.customer_id <> :p",
                 p=payer_customer_id, g=group_id)
    audit_record(session, "update", "memberships.account_group", group_id, {k: str(v) for k, v in values.items()})
    return saved


def set_group(session: Session, customer_id: UUID, group_id: UUID | None) -> repo.Row:
    """Put a member in a household or company (or take them out). Their live memberships are billed to the group's
    payer from the next invoice. Needs 'memberships.manage'."""
    profile = profile_of_customer(session, customer_id)
    common.require_in_company(MANAGE, profile["company_id"])
    payer: UUID | None = None
    if group_id is not None:
        group = common.get_row(session, "account_group", group_id, "Group")
        if group["company_id"] != profile["company_id"]:
            raise ValidationFailed("That group belongs to another company")
        if group["status"] != "active":
            raise ValidationFailed("That group is closed")
        payer = group["payer_customer_id"]
    saved = repo.update(session, "profile", profile["id"], {"group_id": group_id,
                                                            "updated_by": current_context().user_id})
    repo.run(session, "update memberships.member set billing_customer_id = :p, updated_at = now() "
                      "where customer_id = :c and status in ('active', 'paused', 'frozen')",
             p=payer if payer != customer_id else None, c=customer_id)
    audit_record(session, "group", "memberships.profile", profile["id"], {"group": str(group_id)})
    return saved


def billing_customer_of(session: Session, customer_id: UUID) -> UUID | None:
    """Who is invoiced for this member: the payer of their household or company, or None (the member themselves)."""
    row = repo.one(session, "select g.payer_customer_id from memberships.profile p join memberships.account_group g "
                            "on g.id = p.group_id where p.customer_id = :c and g.status = 'active'", c=customer_id)
    if row is None or row["payer_customer_id"] == customer_id:
        return None
    payer: UUID = row["payer_customer_id"]
    return payer
