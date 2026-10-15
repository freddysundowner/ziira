"""Does a statement's running balance add up? Each line should move the balance by exactly its amount.

A line whose balance does not follow from the one before it was probably misread (a digit of an amount, or of the
balance itself, read wrongly from a picture), or a line is missing. The statement may list oldest first or newest
first; the order that fits more lines is used.
"""

from decimal import Decimal

MIN_FIT = 0.4        # below this share of lines fitting, the balance column means something else: flag nothing


def fit(entries: list[tuple[int, Decimal, Decimal]]) -> tuple[float, list[int]]:
    """(share of lines that fit, line numbers that do not) for lines listed oldest first.
    Each entry is (line number, signed amount, balance after the line)."""
    if len(entries) < 2:
        return 1.0, []
    bad = [entries[i][0] for i in range(1, len(entries))
           if entries[i][2] - entries[i - 1][2] != entries[i][1]]
    return 1 - len(bad) / (len(entries) - 1), bad


def suspects(entries: list[tuple[int, Decimal, Decimal]]) -> list[int]:
    """Line numbers whose balance does not follow from their neighbour's, in the better-fitting order."""
    up, bad_up = fit(entries)
    down, bad_down = fit(entries[::-1])
    best, bad = (up, bad_up) if up >= down else (down, bad_down)
    return bad if best >= MIN_FIT else []
