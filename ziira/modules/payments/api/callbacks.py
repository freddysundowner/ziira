"""Running the work for a callback from a payment provider: no user is signed in, so the address itself proves who is
calling.

C2B callbacks carry the account's callback token (`<tenant hex>.<secret>`); STK callbacks carry a signature of the
prompt's id that only this platform can make. A wrong token or signature is answered with "not found", the same as an
unknown address.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from ziira.modules.payments.repository import payments_repo
from ziira.modules.payments.repository.models import PaymentAccount
from ziira.modules.payments.services import intents
from ziira.sdk import NotFound, Session, hash_secret, system_session


def _enabled(session: Session) -> bool:
    from sqlalchemy import text

    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'payments' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first() is not None


def with_account(token: str, work: Callable[[Session, PaymentAccount], Any]) -> Any:
    """Run `work` for the payment account whose callback token this is."""
    try:
        tenant_hex, _, _ = token.partition(".")
        tenant_id = UUID(hex=tenant_hex)
    except ValueError:
        raise NotFound("Not found") from None
    with system_session(tenant_id) as session:
        account = payments_repo.account_by_callback_hash(session, hash_secret(token)) if _enabled(session) else None
        if account is None or not account.is_active:
            raise NotFound("Not found")
        return work(session, account)


def with_intent(tenant_id: UUID, intent_id: UUID, signature: str, work: Callable[[Session], Any]) -> Any:
    """Run `work` for the payment prompt this signed address belongs to."""
    if not intents.check_callback(tenant_id, intent_id, signature):
        raise NotFound("Not found")
    with system_session(tenant_id) as session:
        if not _enabled(session):
            raise NotFound("Not found")
        return work(session)
