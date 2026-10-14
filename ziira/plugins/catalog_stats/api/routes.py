"""Read the statistics kept by this plugin."""

from fastapi import APIRouter, Depends
from sqlalchemy import text

from ziira.sdk import DB_SESSION, Session, require_permission

router = APIRouter()


@router.get("", dependencies=[Depends(require_permission("catalog_stats.view"))])
def company_counts(session: Session = DB_SESSION) -> list[dict[str, object]]:
    rows = session.execute(text(
        "select company_id, product_count, updated_at from plg_catalog_stats.company_count"))
    return [dict(r._mapping) for r in rows]
