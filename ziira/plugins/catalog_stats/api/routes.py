"""Read the statistics kept by this plugin."""

from fastapi import APIRouter, Depends
from sqlalchemy import text

from ziira.sdk import Session, db_session

router = APIRouter()


@router.get("")
def company_counts(session: Session = Depends(db_session)) -> list[dict[str, object]]:
    rows = session.execute(text(
        "select company_id, product_count, updated_at from plg_catalog_stats.company_count"))
    return [dict(r._mapping) for r in rows]
