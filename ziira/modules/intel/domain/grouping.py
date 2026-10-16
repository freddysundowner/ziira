"""Less noise: similar findings shown as one card, ranked by how urgent they are, how much money is involved
and how recent
they are. Pure rules; the stored findings are never changed."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.intel.domain.rules import severity_rank

URGENT_SEVERITIES = ("critical", "high")


def band_of(severity: str) -> str:
    """The word a business sees: urgent (critical, high), soon (medium) or look (low, info)."""
    if severity in URGENT_SEVERITIES:
        return "urgent"
    return "soon" if severity == "medium" else "look"


def group_key(check_code: str | None, branch_id: UUID | None, first_seen_at: datetime) -> str:
    """Findings of one kind, at one branch, first noticed on the same day, belong together."""
    return f"{check_code or 'general'}|{branch_id or '-'}|{first_seen_at.date().isoformat()}"


@dataclass
class Group:
    key: str
    members: list[Any]

    @property
    def severity(self) -> str:
        severity: str = max((m.severity for m in self.members), key=severity_rank)
        return severity

    @property
    def amount(self) -> Decimal:
        return sum((Decimal(m.amount) for m in self.members if m.amount is not None), Decimal(0))

    @property
    def last_seen_at(self) -> datetime:
        latest: datetime = max(m.last_seen_at for m in self.members)
        return latest


def group_findings(rows: Sequence[Any]) -> list[Group]:
    """Groups of the rows (each has check_code, branch_id, first_seen_at, severity, amount, last_seen_at), most pressing
    first: urgency, then money at stake, then the most recent. Members keep the same order inside a group."""
    groups: dict[str, Group] = {}
    for r in rows:
        key = group_key(r.check_code, r.branch_id, r.first_seen_at)
        groups.setdefault(key, Group(key, [])).members.append(r)
    for g in groups.values():
        g.members.sort(
            key=lambda m: (
                -severity_rank(m.severity),
                -(Decimal(m.amount) if m.amount is not None else Decimal(0)),
                -m.last_seen_at.timestamp(),
            )
        )
    return sorted(
        groups.values(), key=lambda g: (-severity_rank(g.severity), -g.amount, -g.last_seen_at.timestamp(), g.key)
    )


def worse(old_severity: str, new_severity: str, old_amount: Decimal | None, new_amount: Decimal | None) -> bool:
    """A snoozed finding comes back when it gets more serious, or when the money involved grows by half or more."""
    if severity_rank(new_severity) > severity_rank(old_severity):
        return True
    return bool(old_amount and new_amount and old_amount > 0 and new_amount >= old_amount * Decimal("1.5"))


def covers(
    rule: Any,
    *,
    check_code: str | None,
    branch_id: UUID | None,
    entity_type: str | None,
    entity_id: UUID | None,
    company_id: UUID | None,
    today: Any,
) -> bool:
    """Whether an ignore rule (check_code, company_id, branch_id, entity_type, entity_id, until_date) covers a
    finding."""
    if rule.check_code != check_code or (rule.company_id and rule.company_id != company_id):
        return False
    if rule.until_date is not None and today > rule.until_date:
        return False
    if rule.branch_id is not None and rule.branch_id != branch_id:
        return False
    return rule.entity_id is None or (rule.entity_type == entity_type and rule.entity_id == entity_id)
