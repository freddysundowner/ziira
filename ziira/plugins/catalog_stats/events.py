"""Keeps a product count per company, updated in the same transaction as the product."""

from sqlalchemy import text

from ziira.sdk import Event, Session, current_context, subscribe


@subscribe("product.created")
def count_new_product(session: Session, event: Event) -> None:
    session.execute(text(
        "insert into plg_catalog_stats.company_count (tenant_id, company_id, product_count) "
        "values (:t, :c, 1) on conflict (tenant_id, company_id) "
        "do update set product_count = plg_catalog_stats.company_count.product_count + 1, "
        "updated_at = now()"),
        {"t": str(current_context().tenant_id), "c": str(event.payload["company_id"])})
