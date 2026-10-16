"""Telling the people who can decide that a suggestion is waiting, on the channel they chose for approvals.

Each person who holds the provider's `needs_permission` where the finding is (so a branch manager hears about their
branch only) is messaged through the channel layer: their own choice for "approvals", else a channel the business has
that offers reply buttons and whose address they have verified. On such a channel the message carries Approve / Reject
/ Why? buttons; the reply is handled in `inbound.py`. Nobody is messaged when no channel applies (the suggestion waits
in the app), and the same suggestion is never sent to a person twice.
"""

import logging
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import ActionProvider, FindingInfo
from ziira.sdk import Session, notify_user_templated, recipients_with_permission

log = logging.getLogger("ziira.intel")
MAX_DESCRIPTION = 300


def tell_approvers(session: Session, provider: ActionProvider, info: FindingInfo, proposal_id: UUID,
                   description: str) -> int:
    """Message the approvers of one new suggestion. Never raises: a message that cannot be queued must not stop the
    suggestion being made. Returns how many people were messaged."""
    told = 0
    business = session.execute(text("select name from kernel.company where id = :c"),
                               {"c": str(info.company_id)}).scalar_one()
    for person in recipients_with_permission(session, provider.needs_permission):
        if not person.covers(provider.needs_permission, info.company_id, info.branch_id):
            continue
        try:
            with session.begin_nested():
                queued = notify_user_templated(
                    session, company_id=info.company_id, user_id=person.user_id, kind="approvals",
                    template="action_proposal", variables={"business": business,
                                                           "description": description[:MAX_DESCRIPTION]},
                    button_suffix=str(proposal_id), capability="buttons",
                    ref_type="intel.action_proposal", ref_id=proposal_id,
                    dedupe_key=f"intel-approval:{proposal_id}:{person.user_id}")
            told += 1 if queued else 0
        except Exception:
            log.exception("Could not message %s about suggestion %s", person.user_id, proposal_id)
    return told
