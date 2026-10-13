"""Sockets the Inventory module plugs into (declared under [extends] in manifest.toml)."""

from ziira.modules.inventory.services.verify import verify_stock
from ziira.sdk import IntegrityCheck, Session, provides


@provides("kernel.integrity_check")
class StockLedgerCheck(IntegrityCheck):
    """Stock balances and cost figures must equal what the movements add up to."""

    name = "stock ledger"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        return verify_stock(session, fix=fix)
