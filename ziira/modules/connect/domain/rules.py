"""Pure rules behind the standalone checks (no database): rates, drops, slow payers, round amounts, price rises."""

from decimal import Decimal

ZERO = Decimal(0)


def rate(part: Decimal, whole: Decimal) -> Decimal | None:
    """part / whole, or None when there is no whole to compare with."""
    return part / whole if whole > 0 else None


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


def is_round(amount: Decimal, step: Decimal, minimum: Decimal) -> bool:
    """True for a whole multiple of `step` (10,000, 50,000 ...) that is at least `minimum`: invented numbers are
    round, real ones rarely are."""
    amount = abs(amount)
    return step > 0 and amount >= minimum and amount % step == 0


def outside_hours(hour: int, open_hour: int, close_hour: int) -> bool:
    """True when the hour (0-23) is before opening or from closing time on."""
    return hour < open_hour or hour >= close_hour


def price_rise_percent(previous: Decimal, latest: Decimal) -> Decimal | None:
    """How much dearer `latest` is than `previous`, in percent (None when there is no earlier price)."""
    if previous <= 0:
        return None
    return (latest - previous) * 100 / previous


def money(amount: Decimal) -> str:
    """12345.5 -> '12,345.50'."""
    return f"{amount:,.2f}"


def percent(value: Decimal) -> str:
    return f"{value * 100:.0f}%"


def line_concession(quantity: Decimal, unit_price: Decimal, discount: Decimal, list_price: Decimal | None) -> Decimal:
    """Money given away on a line: its discount plus any price below the list price."""
    below = (list_price - unit_price) * quantity if list_price is not None and list_price > unit_price else ZERO
    return discount + below


def plain(value: Decimal) -> str:
    """12.5000 -> '12.5', 150.0000 -> '150' (quantities read from the database carry four decimals)."""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def signed(value: Decimal) -> str:
    """-120.0000 -> '-120', 150.0000 -> '+150'."""
    return ("+" if value > 0 else "") + plain(value)
