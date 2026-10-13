"""Sockets the Finance module plugs into (declared under [extends] in manifest.toml)."""

from ziira.modules.finance.services.verify import verify_books
from ziira.sdk import IntegrityCheck, Session, provides


@provides("kernel.integrity_check")
class BooksCheck(IntegrityCheck):
    """Every entry balances, the inventory accounts equal the stock ledger, and every stock movement is posted."""

    name = "books"

    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        return verify_books(session, fix=fix)
