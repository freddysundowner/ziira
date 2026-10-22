"""Industry packs for Purchasing: supplier templates an industry pack suggests (`data/purchasing.toml`).

    [[supplier]]        # code, name, payment_terms_days   (examples the business renames and fills in)

A supplier template carries no tax number, phone, email or bank details: those are the business's own. A code the
business already has is skipped, so running it again adds nothing. Switching the pack off offers to put the
templates nobody has bought from on hold (suppliers are never deleted: bills and orders name them).
"""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.purchasing.services import suppliers
from ziira.sdk import PackData, SeededItem, SeedReport, Session, audit_record, current_context


def seed(session: Session, pack: PackData, company_id: UUID) -> SeedReport:
    """Add the pack's supplier templates the company lacks."""
    report = SeedReport()
    for spec in pack.unit_data("purchasing").get("supplier", []):
        code = str(spec["code"])
        exists = session.execute(text("select 1 from purchasing.supplier where company_id = :c and code = upper(:k)"),
                                 {"c": str(company_id), "k": code.strip()}).first()
        if exists is not None:
            report.skipped += 1
            continue
        made = suppliers.create_supplier(session, company_id=company_id, code=code, name=str(spec["name"]),
                                         payment_terms_days=int(spec.get("payment_terms_days", 0)))
        report.added.append(SeededItem("supplier", made.id, made.name))
    if report.added:
        audit_record(session, "seed_suppliers", "purchasing.supplier", None,
                     {"pack": pack.name, "suppliers": [i.label for i in report.added]})
    return report


def untouched(session: Session, item_id: UUID) -> bool:
    """A template supplier nobody edited and nothing refers to: putting it on hold loses nothing."""
    row = session.execute(text(
        "select s.status, s.updated_at, "
        "(select count(*) from purchasing.purchase_order o where o.supplier_id = s.id) "
        "+ (select count(*) from purchasing.goods_receipt g where g.supplier_id = s.id) "
        "+ (select count(*) from purchasing.supplier_bill b where b.supplier_id = s.id) as used "
        "from purchasing.supplier s where s.id = :i"), {"i": str(item_id)}).first()
    return row is not None and row.status == "active" and row.updated_at is None and row.used == 0


def hide(session: Session, item_id: UUID) -> None:
    session.execute(text("update purchasing.supplier set status = 'inactive', updated_at = now(), updated_by = :u "
                         "where id = :i"), {"i": str(item_id), "u": str(current_context().user_id or "") or None})
    audit_record(session, "hide", "purchasing.supplier", item_id, {"reason": "industry pack switched off"})
