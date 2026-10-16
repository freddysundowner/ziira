"""Who to write to at a subscriber: the owner(s) of the business, read from the business's own database."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel.db import tenant_session


def owner_contacts(tenant_id: UUID) -> list[dict[str, Any]]:
    """Name and email of the active users holding the Owner role (an unreachable business gives an empty list)."""
    try:
        with tenant_session(tenant_id, admin=True) as s:
            rows = s.execute(
                text(
                    "select distinct u.full_name as name, u.email, u.phone from kernel.app_user u "
                    "join kernel.user_role ur on ur.user_id = u.id join kernel.role r on r.id = ur.role_id "
                    "where r.name = 'Owner' and u.status = 'active' and u.email is not null order by u.full_name"
                )
            )
            return [dict(r._mapping) for r in rows]
    except Exception:  # noqa: BLE001 - a broken business database must not stop billing for the others
        return []
