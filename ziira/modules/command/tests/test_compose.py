"""Command Center rules that need no database: how a brief reads and when it is due."""

from datetime import date, datetime, time
from decimal import Decimal

from ziira.modules.command.domain.compose import FindingLine, PulseLine, change, compose, fmt
from ziira.modules.command.domain.schedule import is_due

D = Decimal


def test_numbers_are_shown_the_way_people_read_them() -> None:
    assert fmt(D("1234567.5"), "money", "EUR") == "EUR 1,234,567.50"
    assert fmt(D("12"), "count", "EUR") == "12" and fmt(D("12.34"), "percent", "EUR") == "12.3%"
    assert fmt(D("5"), "money", "") == "5.00"


def test_change_against_the_period_before() -> None:
    assert change(D(112), D(100)) == " (up 12%)" and change(D(80), D(100)) == " (down 20%)"
    assert change(D(100), D(100)) == " (flat)" and change(D(100), D("99.8")) == " (flat)"
    assert change(D(5), None) == "" and change(D(5), D(0)) == ""


def test_a_brief_with_figures_and_findings() -> None:
    brief = compose(
        business="Demo Hardware", day=date(2026, 10, 14), kind="daily", currency="KES",
        pulse=[PulseLine("Sales", "money", D("12000"), D("10000")), PulseLine("Voids", "count", D(3), D(3)),
               PulseLine("Sales", "money", D(5000), None, "Thika")],
        findings=[FindingLine("high", "Two cash sales have no money received.", "Ask the cashier to explain."),
                  FindingLine("low", "Stock of Cement is low.", None)], more_findings=3)
    assert brief.subject == "Demo Hardware: daily summary, 14 Oct 2026"
    assert "- Sales: KES 12,000.00 (up 20%)" in brief.body and "- Sales [Thika]: KES 5,000.00" in brief.body
    assert "1. [Urgent] Two cash sales have no money received. Next: Ask the cashier to explain." in brief.body
    assert "2. [Worth a look] Stock of Cement is low." in brief.body and "...and 3 more" in brief.body
    assert brief.short.startswith("Demo Hardware yesterday:") and "Attention: Two cash sales" in brief.short
    assert "(+4 more)" in brief.short and len(brief.short) <= 900


def test_a_quiet_day_says_so_and_a_weekly_one_says_the_period() -> None:
    quiet = compose(business="B", day=date(2026, 10, 14), kind="weekly", currency="USD",
                    pulse=[PulseLine("Sales", "money", D(1), None)], findings=[])
    assert "Nothing needs you." in quiet.body and "Last 7 days" in quiet.body and "weekly summary" in quiet.subject
    assert quiet.short.endswith("Nothing needs attention.")


def due(now: datetime, kind: str = "daily", weekday: int | None = None, sent: bool = False, active: bool = True) -> bool:
    return is_due(now_local=now, send_time=time(7, 30), kind=kind, weekday=weekday, already_sent=sent, is_active=active)


def test_when_a_brief_is_due() -> None:
    morning = datetime(2026, 10, 14, 8, 0)             # a Wednesday
    assert due(morning)
    assert not due(datetime(2026, 10, 14, 7, 29))      # not yet
    assert not due(morning, sent=True)                 # once a day
    assert not due(morning, active=False)
    assert due(morning, "weekly", 3)                   # Wednesday
    assert not due(morning, "weekly", 4)
    assert not due(morning, "weekly")                  # weekly needs a weekday
    assert due(datetime(2026, 10, 14, 23, 50))         # late, same day: still sent
