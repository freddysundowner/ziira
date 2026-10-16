"""Background jobs of the Payments module (run by `ziira worker`)."""

from typing import Any
from uuid import UUID

from ziira.modules.payments.services import intents, matching
from ziira.sdk import Session, job


@job("payments.send_stk")
def send_stk(session: Session, payload: dict[str, Any]) -> None:
    """Ask the provider to put the payment prompt on the customer's phone."""
    intents.send(session, UUID(payload["intent_id"]), payload["phone"])


@job("payments.check_stk")
def check_stk(session: Session, payload: dict[str, Any]) -> None:
    """Ask the provider what became of a prompt whose callback has not arrived."""
    intents.check(session, UUID(payload["intent_id"]), int(payload.get("attempt", 0)))


@job("payments.match")
def match(session: Session, payload: dict[str, Any]) -> None:
    """Match what arrived to what was recorded."""
    matching.run_matching(session, UUID(payload["account_id"]) if payload.get("account_id") else None)
