"""The plain-language layer of Intelligence: every registered check has plain text (English and Swahili), sentences
only name limits the check has, nothing technical leaks into the plain fields, and grouping/ranking rules hold.

No database is needed: the registry is read the way scripts/export_check_catalog.py reads it."""

import importlib.util
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ziira.modules.intel.domain import plain
from ziira.modules.intel.domain.grouping import band_of, covers, group_findings, worse

ROOT = Path(__file__).resolve().parent.parent
BANNED = json.loads((ROOT / "frontend/src/modules/intel/bannedTerms.json").read_text())


def _checks() -> list[Any]:
    spec = importlib.util.spec_from_file_location("export_check_catalog", ROOT / "scripts" / "export_check_catalog.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks: list[Any] = module._registry()[0]
    return checks


@pytest.fixture(scope="module")
def checks() -> list[Any]:
    return _checks()


def _words(text: str, banned: list[str]) -> list[str]:
    return [w for w in banned if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", text, re.IGNORECASE)]


def test_every_registered_check_has_plain_text_in_both_languages(checks: list[Any]) -> None:
    assert len(checks) > 50
    for lang in plain.LANGS:
        for c in checks:
            p = plain.plain_check(c.code, lang, fallback_title=c.title, area=c.area, params=c.params)
            assert p.title and p.why and p.todo, f"{c.code} ({lang}) lacks plain text"
            assert p.topic in plain.TOPICS


def test_the_text_file_describes_no_check_that_does_not_exist(checks: list[Any]) -> None:
    assert plain.known_codes() == {c.code for c in checks}


def test_sentences_name_only_limits_the_check_has_and_every_limit_has_a_label(checks: list[Any]) -> None:
    labels = plain.param_labels("en")
    for c in checks:
        for lang in plain.LANGS:
            entry = plain.entry_of(c.code)
            sentence = plain.pick(entry.get("sentence"), lang)
            assert set(plain.PLACEHOLDER.findall(sentence)) <= set(c.params), f"{c.code} ({lang}) names a limit it lacks"
        for name in c.params:
            assert labels.get(name), f"limit {name} has no plain label"
        if c.params:
            assert plain.entry_of(c.code).get("sentence"), f"{c.code} has limits but no sentence"


def test_no_technical_word_appears_in_the_plain_fields() -> None:
    data = json.loads((ROOT / "ziira/modules/intel/domain/plain_checks.json").read_text())

    def texts(value: Any, lang: str) -> list[str]:
        if isinstance(value, dict):
            if lang in value and isinstance(value[lang], str):
                return [value[lang]]
            return [t for k, v in value.items() if k not in ("kind", "units", "topic", "like") for t in texts(v, lang)]
        return []

    for lang, banned in (("en", BANNED["words"]), ("sw", BANNED["swahili"])):
        for text in texts({k: v for k, v in data.items() if k != "_comment"}, lang):
            assert not _words(text, banned), f"{lang}: '{text}' uses a technical word {_words(text, banned)}"


def test_figures_have_labels_and_known_kinds() -> None:
    for key, meta in plain.figure_meta("en").items():
        assert meta["label"], key
        assert meta["kind"] in {"money", "count", "percent", "days", "date", "yesno", "number", "text"}, key


def test_a_check_may_declare_its_own_plain_text() -> None:
    p = plain.plain_check("x.unknown", "en", fallback_title="Odd thing", area="stock", params={},
                          declared=("Stock is odd", "It costs money.", "Count it."))
    assert (p.title, p.why, p.todo, p.topic) == ("Stock is odd", "It costs money.", "Count it.", "stock")
    bare = plain.plain_check("x.unknown", "en", fallback_title="Odd thing", area="controls", params={})
    assert bare.title == "Odd thing" and bare.topic == "staff"


# --------------------------------------------------------------------------- grouping and ranking
def row(check: str, branch: Any, day: int, severity: str, amount: str | None, seen: int = 1) -> Any:
    return SimpleNamespace(id=uuid4(), check_code=check, branch_id=branch, severity=severity,
                           amount=Decimal(amount) if amount else None,
                           first_seen_at=datetime(2026, 10, day, 8, tzinfo=UTC), last_seen_at=datetime(2026, 10, day, seen, tzinfo=UTC))


def test_similar_findings_form_one_group_and_groups_are_ranked() -> None:
    a, b = uuid4(), uuid4()
    rows = [row("pos.x", a, 14, "medium", "10"), row("pos.x", a, 14, "high", "5"), row("pos.x", b, 14, "medium", "900"),
            row("inv.y", a, 14, "medium", "20"), row("pos.x", a, 15, "low", None)]
    groups = group_findings(rows)
    assert [len(g.members) for g in groups] == [2, 1, 1, 1]
    assert groups[0].severity == "high" and groups[0].amount == Decimal("15")
    assert [g.members[0].severity for g in groups[:2]] == ["high", "medium"]
    assert groups[1].amount == Decimal("900")                        # same urgency: more money first
    assert groups[0].members[0].severity == "high"                    # inside a group, the most serious first


def test_bands_use_business_words() -> None:
    assert [band_of(s) for s in ("critical", "high", "medium", "low", "info")] == ["urgent", "urgent", "soon", "look", "look"]


def test_a_snoozed_finding_comes_back_when_it_gets_worse() -> None:
    assert worse("medium", "high", Decimal("10"), Decimal("10"))
    assert worse("medium", "medium", Decimal("100"), Decimal("150"))
    assert not worse("medium", "medium", Decimal("100"), Decimal("120"))


def test_an_ignore_rule_covers_only_what_it_names() -> None:
    from datetime import date

    branch, company, person = uuid4(), uuid4(), uuid4()
    rule = SimpleNamespace(check_code="pos.x", company_id=company, branch_id=branch, entity_type=None, entity_id=None,
                           until_date=date(2026, 10, 20))
    base: dict[str, Any] = dict(check_code="pos.x", branch_id=branch, entity_type=None, entity_id=None, company_id=company,
                                today=date(2026, 10, 14))
    assert covers(rule, **base)
    assert not covers(rule, **{**base, "branch_id": uuid4()})
    assert not covers(rule, **{**base, "check_code": "pos.y"})
    assert not covers(rule, **{**base, "today": date(2026, 10, 21)})
    who = SimpleNamespace(check_code="pos.x", company_id=company, branch_id=None, entity_type="kernel.app_user", entity_id=person,
                          until_date=None)
    assert covers(who, **{**base, "entity_type": "kernel.app_user", "entity_id": person, "branch_id": uuid4()})
    assert not covers(who, **base)
