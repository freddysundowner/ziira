"""The date wording shared by findings and briefs: people read '13 Oct 2026', data keeps 2026-10-13."""

from datetime import date

from ziira.modules.command.domain.compose import compose
from ziira.sdk import format_day, humanise_dates


def test_a_day_reads_the_way_people_say_it() -> None:
    assert format_day(date(2026, 10, 13)) == "13 Oct 2026"
    assert format_day(date(2026, 1, 5)) == "5 Jan 2026"
    assert format_day(date(2026, 12, 31)) == "31 Dec 2026"


def test_every_iso_date_in_a_sentence_is_rewritten() -> None:
    text = "Thika sold KES 10.00 on 2026-10-13 (Tuesday); the close of 2026-09-26 was short. Invoice 2026-10-130."
    assert humanise_dates(text) == "Thika sold KES 10.00 on 13 Oct 2026 (Tuesday); the close of 26 Sep 2026 was short. Invoice 2026-10-130."


def test_things_that_only_look_like_dates_are_left_alone() -> None:
    assert humanise_dates("Order 2026-13-45 and ref 12026-10-13") == "Order 2026-13-45 and ref 12026-10-13"
    assert humanise_dates("nothing here") == "nothing here"


def test_a_brief_is_titled_with_the_readable_day() -> None:
    brief = compose(business="Demo", day=date(2026, 10, 16), kind="daily", currency="KES", pulse=[], findings=[])
    assert brief.subject == "Demo: daily brief, 16 Oct 2026"
