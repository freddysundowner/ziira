import pytest

from tests.claims_helpers import estimate, line, make_claims_shop, new_claim, submit


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_claims_shop(client, registry, "Claims Smoke")


def test_smoke(client, shop) -> None:  # type: ignore[no-untyped-def]
    claim = new_claim(client, shop)
    assert claim["number"].startswith("CLM-")
    est = estimate(client, shop, claim, [line("labour", "Fit bumper", "2", None, work_type="body"),
                                         line("parts", "Bumper", "1", "10000.00", part_class="genuine")])
    assert est["total"] == "10300.00"
    done = submit(client, shop, est)
    assert done["link_path"].startswith("/claim-response/")
