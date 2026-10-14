"""Rules of Intelligence that need no database: severity, the life of a finding, ranking, what is unusual."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from ziira.modules.intel.domain.messages import alert_text
from ziira.modules.intel.domain.model import Baseline
from ziira.modules.intel.domain.rules import (
    TRANSITIONS,
    at_least,
    can_move,
    fingerprint,
    is_unusual,
    mean_std_p95,
    rank_score,
    severity_rank,
)

D = Decimal


def test_severity_order() -> None:
    assert severity_rank("info") < severity_rank("low") < severity_rank("medium") < severity_rank("high") < severity_rank("critical")
    assert at_least("high", "medium") and at_least("high", "high") and not at_least("low", "high")


def test_a_closed_finding_goes_nowhere_and_open_ones_can_be_closed() -> None:
    for closed in ("resolved", "dismissed"):
        assert TRANSITIONS[closed] == ()
        assert not can_move(closed, "new")
    for open_status in ("new", "sent", "acknowledged", "explained"):
        assert can_move(open_status, "resolved") and can_move(open_status, "dismissed")
    assert not can_move("explained", "new")


def test_fingerprint_is_stable_and_tells_problems_apart() -> None:
    assert fingerprint("void", "abc", "2026-10-01") == fingerprint("void", "abc", "2026-10-01")
    assert fingerprint("void", "abc", "2026-10-01") != fingerprint("void", "abc", "2026-10-02")
    assert fingerprint("a", None) != fingerprint("a", "None-") and len(fingerprint("x")) == 32


def test_ranking_severity_first_then_money_then_age() -> None:
    small_critical = rank_score("critical", D("10"), 0)
    huge_high = rank_score("high", D("100000000"), 30)
    assert small_critical > huge_high                                   # severity decides the band
    assert rank_score("high", D("100000"), 0) > rank_score("high", D("100"), 0)
    assert rank_score("high", D("100"), 10) > rank_score("high", D("100"), 0)
    assert rank_score("low", None, 0) < rank_score("low", D("5"), 0)


def test_baseline_statistics_by_hand() -> None:
    stats = mean_std_p95([D(v) for v in (2, 4, 4, 4, 5, 5, 7, 9)])
    assert stats is not None and stats.mean == 5 and stats.stddev == 2 and stats.sample_size == 8 and stats.p95 == 9
    assert mean_std_p95([]) is None
    flat = mean_std_p95([D(3)] * 20)
    assert flat is not None and flat.stddev == 0 and flat.p95 == 3


def test_unusual_needs_history_and_a_clear_excess() -> None:
    normal = Baseline(mean=D(10), stddev=D(2), p95=D(13), sample_size=30)
    assert not is_unusual(D(15), normal)                                # 2.5 deviations: not enough
    assert is_unusual(D(17), normal)                                    # beyond 3 deviations and p95
    assert not is_unusual(D(100), Baseline(D(10), D(2), D(13), 5))      # too little history to say
    assert not is_unusual(D(100), None)
    assert is_unusual(D(1), Baseline(D(0), D(0), D(0), 30))             # flat history: anything above it stands out


@given(st.lists(st.decimals(min_value=0, max_value=10**6, places=2), min_size=1, max_size=60))
def test_baseline_properties(values: list[Decimal]) -> None:
    stats = mean_std_p95(values)
    assert stats is not None
    assert min(values) <= stats.mean <= max(values) or abs(stats.mean - max(values)) < D("0.000001")
    assert stats.stddev >= 0 and stats.p95 in values and stats.p95 <= max(values)


def test_alert_text_is_short_and_carries_what_to_do() -> None:
    text = alert_text("high", "Two cash sales have no money received.", "Ask the cashier to explain.", D("4400"), "KES")
    assert text.startswith("[HIGH]") and "4,400.00" in text and "Next: Ask the cashier" in text
    assert len(alert_text("low", "x" * 2000, "y" * 2000)) <= 900
