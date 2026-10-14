"""Pure rules behind POS's Intelligence checks: when a day's sales are far too low, when a customer pays slower."""

from decimal import Decimal


def unusually_low(value: Decimal, mean: Decimal, stddev: Decimal, sample_size: int, *, drop_percent: int = 50,
                  deviations: Decimal = Decimal(2), min_history: int = 6) -> bool:
    """True when `value` is at least `drop_percent` below the usual `mean` and also more than `deviations` standard
    deviations under it. Needs `min_history` past observations and a usual level above zero."""
    if sample_size < min_history or mean <= 0:
        return False
    return value <= mean * (Decimal(100) - drop_percent) / 100 and value < mean - deviations * stddev


def paying_slower(recent_days: Decimal, prior_days: Decimal, recent_count: int, prior_count: int, *,
                  increase_percent: int = 50, min_increase_days: int = 5, min_invoices: int = 3) -> bool:
    """True when the average days to pay rose by more than `increase_percent` and by at least `min_increase_days`,
    judged on at least `min_invoices` paid invoices in each period."""
    if recent_count < min_invoices or prior_count < min_invoices:
        return False
    rise = recent_days - prior_days
    return rise >= min_increase_days and rise * 100 > prior_days * increase_percent


def rate(part: Decimal, whole: Decimal) -> Decimal | None:
    """part / whole, or None when there is no whole to compare with."""
    return part / whole if whole > 0 else None
