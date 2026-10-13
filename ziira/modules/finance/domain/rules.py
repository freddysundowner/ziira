"""Choosing the account for a line role from the company's posting rules. Pure Python."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ziira.sdk import ValidationFailed


@dataclass(frozen=True)
class PostingRule:
    """Maps (document type, line role) to an account, optionally only when the conditions match."""

    doc_type: str
    line_role: str
    account_id: UUID
    conditions: dict[str, Any]
    priority: int = 100


def resolve_account(rules: list[PostingRule], doc_type: str, role: str, context: dict[str, Any]) -> UUID:
    """The account for a role. A rule applies when every one of its conditions equals the value in `context`
    (e.g. {"movement_type": "write_off"}); the most specific rule wins, then the lowest priority number.
    Raises ValidationFailed when no rule applies, naming what is missing."""
    matching = [r for r in rules if r.doc_type == doc_type and r.line_role == role
                and all(context.get(k) == v for k, v in r.conditions.items())]
    if not matching:
        raise ValidationFailed(f"No posting rule for '{role}' on '{doc_type}': add one under Finance settings")
    return min(matching, key=lambda r: (-len(r.conditions), r.priority)).account_id
