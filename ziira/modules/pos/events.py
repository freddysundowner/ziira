"""Events published and handled by the Point of Sale and Sales module.

Publishes: sale.posted, sale.voided, sale.returned, discount.override, till.opened, till.closed, pos.synced
Subscribes: approval.decided (kernel): posts or rejects a return that waited for approval
"""

from ziira.modules.pos.services import returns
from ziira.sdk import Event, Session, subscribe


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Post or reject the return whose approval was just decided."""
    if event.aggregate_type == returns.DOC_TYPE:
        returns.apply_decision(session, event.aggregate_id, approved=event.payload["status"] == "approved",
                               decided_by=event.payload.get("decided_by"))
