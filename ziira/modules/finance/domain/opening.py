"""Rules for opening balances: what a business starts with on its go-live date. Pure Python.

The opening trial balance lists balance-sheet accounts. Three kinds of account are *control accounts* whose balances are
made up from records kept elsewhere, and those records are brought in by their own imports (customers' opening invoices,
suppliers' opening bills, opening stock), each of which posts against **opening balance equity**:

    customers owe us    Dr accounts receivable (per customer)        Cr opening balance equity
    we owe suppliers    Dr opening balance equity                    Cr accounts payable (per supplier)
    opening stock       Dr inventory                                 Cr opening balance equity

The trial balance entry therefore posts every other account, and puts the opposite of the control balances on opening
balance equity so that it cancels the three entries above. Afterwards each account shows exactly the file's balance, and
opening balance equity shows only what the file itself is out by (zero when it balances).
"""

from dataclasses import dataclass
from decimal import Decimal

from ziira.sdk import ValidationFailed

ZERO = Decimal("0")
BALANCE_SHEET = ("asset", "liability", "equity")

# Control accounts that can take an opening balance, and what each is kept per. Other control accounts (mobile money
# clearing, goods received not invoiced, transfers, net pay payable) have no records to bring in.
PLAIN, RECEIVABLE, PAYABLE, INVENTORY = "plain", "receivable", "payable", "inventory"
PARTY_OF = {RECEIVABLE: "customer", PAYABLE: "supplier", INVENTORY: None}


def classify(account_type: str, subtype: str | None, is_control: bool) -> str:
    """How an account takes part in an opening trial balance: plain, receivable, payable or inventory. Raises
    ValidationFailed for an account that cannot take an opening balance."""
    if account_type not in BALANCE_SHEET:
        raise ValidationFailed("Opening balances are for balance sheet accounts (assets, liabilities, equity); profit "
                               "earned before go-live belongs in an equity account")
    if not is_control:
        return PLAIN
    if subtype in (RECEIVABLE, PAYABLE, INVENTORY):
        return str(subtype)
    raise ValidationFailed("This account is kept by its own records and takes no opening balance: put the balance "
                           "in an ordinary account (bank, cash, equity) instead")


@dataclass(frozen=True)
class Position:
    """The effect of a file on the entry: debits less credits of the whole file (`difference`, zero when it
    balances) and of its control-account lines (`controlled`); the rest (`plain`) is what the entry posts itself."""

    difference: Decimal
    controlled: Decimal
    plain: Decimal


def position(plain: Decimal, controlled: Decimal) -> Position:
    return Position(difference=plain + controlled, controlled=controlled, plain=plain)


def equity_lines(pos: Position) -> list[tuple[str, Decimal, str]]:
    """The lines for opening balance equity that make the entry balance: (side, amount, why). One cancels the control
    balances posted by their own records; one carries the file's difference (when it was accepted)."""
    lines: list[tuple[str, Decimal, str]] = []
    if pos.controlled != 0:
        lines.append(("debit" if pos.controlled > 0 else "credit", abs(pos.controlled),
                      "Offsets the customer, supplier and stock balances posted from their own records"))
    if pos.difference != 0:
        lines.append(("credit" if pos.difference > 0 else "debit", abs(pos.difference),
                      "The opening balances do not balance: the difference was accepted"))
    return lines


def mismatches[K](file_net: dict[K, Decimal], ledger_net: dict[K, Decimal]) -> list[tuple[K, Decimal, Decimal]]:
    """Parties (or the single key None) whose balance in the file differs from the books: (key, file, books)."""
    keys = sorted({*file_net, *ledger_net}, key=str)
    return [(k, file_net.get(k, ZERO), ledger_net.get(k, ZERO)) for k in keys
            if file_net.get(k, ZERO) != ledger_net.get(k, ZERO)]
