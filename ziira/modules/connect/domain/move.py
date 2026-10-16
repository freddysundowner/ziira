"""Pure rules for moving a connected system's data into Ziira Core (no database): what is brought over in which order,
the codes given to customers and suppliers, turning amounts into the text the importers read, and summarising why
records were left out."""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# Kinds in the order they are brought in. The second group refers to records of the first (a stock line names a
# product, a balance names a customer), so it is staged only once the first has been imported.
PHASE_ONE = ("products", "customers", "suppliers")
PHASE_TWO = ("opening_stock", "customer_balances", "supplier_balances")
KINDS = PHASE_ONE + PHASE_TWO

# The units whose switching on a kind needs (the first is the one that owns the importer). Names, not titles.
NEEDS = {
    "products": ("products",), "customers": ("crm",), "suppliers": ("purchasing",),
    "opening_stock": ("inventory", "products"), "customer_balances": ("pos", "crm", "finance"),
    "supplier_balances": ("purchasing", "finance"),
}
# Which kinds refer to records that are looked up by code in the first group
LOOKUP_WORDS = {"sku": "product", "customer_code": "customer", "supplier_code": "supplier"}
CODE_PREFIX = {"customer": "C", "supplier": "S"}
CODE_DIGITS = 4
EXAMPLES = 3
CENT = Decimal("0.01")
_NO_SUCH = re.compile(r"no (?P<word>product|customer|supplier) with code (?P<code>.+?)(?:\. |\.$|$)")


def money_text(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def number_text(value: Decimal) -> str:
    """A quantity or cost as plain text without an exponent (4 decimals at most, trailing zeros dropped)."""
    text = format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def sku_of(sku: str | None) -> str:
    return (sku or "").strip().upper()


def code_for(kind: str, number: int) -> str:
    """The Ziira code of the n-th customer or supplier brought over: C-0001, S-0001."""
    return f"{CODE_PREFIX[kind]}-{number:0{CODE_DIGITS}d}"


def next_codes(kind: str, taken: Iterable[str], in_ziira: Callable[[str], bool], how_many: int) -> list[str]:
    """`how_many` unused codes, counting up from 1 and passing codes already given or already in Ziira."""
    used = set(taken)
    found: list[str] = []
    number = 0
    while len(found) < how_many:
        number += 1
        code = code_for(kind, number)
        if code in used or in_ziira(code):
            continue
        used.add(code)
        found.append(code)
    return found


def outstanding(total: Decimal, paid: Decimal) -> Decimal:
    """What is still owed on an invoice."""
    return total - paid


def forgive_lookup(messages: list[str], planned: Mapping[str, set[str]]) -> list[str]:
    """Messages without the "no such record" ones for codes that this same move is about to create. A stock line
    refers to a product the move will make a moment earlier; that is not a problem."""
    kept: list[str] = []
    for message in messages:
        field_name = message.split(":", 1)[0]
        word = LOOKUP_WORDS.get(field_name)
        found = _NO_SUCH.search(message) if word else None
        if word and found and found["word"] == word and found["code"].upper() in planned.get(word, set()):
            continue
        kept.append(message)
    return kept


@dataclass
class Reason:
    """Why some records were left out: the words, how many, and a few examples by name."""

    status: str                          # "exists" (already in Ziira) or "skipped" (cannot be brought over)
    reason: str
    count: int = 0
    examples: list[str] = field(default_factory=list)


def tally(entries: Iterable[tuple[str, str, str]]) -> list[Reason]:
    """Group (status, reason, label) entries into reasons with counts, most frequent first."""
    found: dict[tuple[str, str], Reason] = {}
    for status, reason, label in entries:
        item = found.setdefault((status, reason), Reason(status, reason))
        item.count += 1
        if len(item.examples) < EXAMPLES and label:
            item.examples.append(label)
    return sorted(found.values(), key=lambda r: (-r.count, r.reason))
