"""The sync engine and the Connectors API, run on fake in-memory systems: cursors, resuming after a failure, partial
pages, bad records, branch mapping, problems in the exceptions inbox, idempotent re-reads, secrets that never leave,
permissions, tenant isolation, disconnecting and deleting data."""

from datetime import timedelta
from decimal import Decimal as D  # noqa: N817
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.connect_helpers import (
    CONNECT,
    TODAY,
    FakeErp,
    at,
    make_connect_shop,
    new_connection,
    register_fakes,
    rows,
    scalar,
)
from tests.stock_helpers import system
from ziira.kernel import jobs
from ziira.modules.connect.public import Branch, CanonicalBatch, ConnectorError, Payment, Sale, User
from ziira.modules.connect.services import sync


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    undo = register_fakes()
    yield make_connect_shop(client, registry, "Sync Co")
    undo()


@pytest.fixture(autouse=True)
def reset() -> None:
    FakeErp.SCRIPT = {}
    FakeErp.CALLS = []
    FakeErp.CHECK_OK = True
    FakeErp.ROTATE = None
    FakeErp.NOTES = []


def sale(ref: str, day: int = 13, total: str = "100.00", branch: str | None = "B1", **kw) -> Sale:  # type: ignore[no-untyped-def]
    return Sale(ref=ref, occurred_at=at(TODAY.replace(day=day)), total=D(total), branch_ref=branch,
                number=f"R-{ref}", **kw)


def run(shop, connection_id: str, **kw):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return sync.sync_connection(s, UUID(connection_id), **kw)


def connection(client, shop, name: str, **extra):  # type: ignore[no-untyped-def]
    return new_connection(client, shop, "fake_erp", name, **extra)


def count(shop, table: str, connection_id: str) -> int:  # type: ignore[no-untyped-def]
    return int(scalar(shop, f"select count(*) from connect.{table} where connection_id = :c", c=connection_id))


# --------------------------------------------------------------------------- catalogue and secrets
def test_the_catalogue_groups_erps_and_file_kinds_with_plain_how_to_text(client, shop) -> None:  # type: ignore[no-untyped-def]
    kinds = {k["kind"]: k for k in client.get(f"{CONNECT}/kinds", headers=shop["owner"]).json()}
    assert kinds["fake_erp"]["group"] == "Your ERP" and kinds["fake_erp"]["how_to"] == "Create a read-only API key."
    assert kinds["fake_erp"]["freshness"] == "daily" and kinds["fake_live"]["freshness"] == "live"
    for file_kind in ("csv_sales", "csv_invoices", "csv_stock", "csv_expenses", "bank_statement",
                      "mobile_money_statement"):
        assert kinds[file_kind]["group"] == "Statements and exports" and kinds[file_kind]["freshness"] == "on_upload"
        assert kinds[file_kind]["how_to"] and kinds[file_kind]["file_fields"]
    secret = next(f for f in kinds["fake_erp"]["config_fields"] if f["name"] == "api_key")
    assert secret["secret"] is True and secret["required"] is True


def test_secrets_are_encrypted_at_rest_and_never_returned_by_any_endpoint(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = connection(client, shop, "Secret Co")
    cid = made["id"]
    assert made["secrets_set"] == ["api_key"] and made["config"] == {"url": "https://erp.example"}
    seen = [made]
    for path in ("", "/runs", "/counts", "/branches"):
        r = client.get(f"{CONNECT}/connections/{cid}{path}", headers=shop["owner"])
        assert r.status_code == 200, r.text
        seen.append(r.json())
    seen.append(client.get(f"{CONNECT}/connections", headers=shop["owner"]).json())
    seen.append(client.get(f"{CONNECT}/kinds", headers=shop["owner"]).json())
    seen.append(client.post(f"{CONNECT}/connections/{cid}/test", headers=shop["owner"]).json())
    seen.append(client.patch(f"{CONNECT}/connections/{cid}", headers=shop["owner"], json={"name": "Secret Co 2"}).json())
    assert "key-1" not in str(seen)
    stored = rows(shop, "select c.config::text as config, k.secret_ciphertext from connect.connection c "
                        "join kernel.integration_credential k on k.id = c.credential_id where c.id = :i", i=cid)[0]
    assert "key-1" not in stored.config and b"key-1" not in bytes(stored.secret_ciphertext)
    audit = scalar(shop, "select coalesce(string_agg(changes::text, ' '), '') from kernel.audit_log")
    assert "key-1" not in audit


def test_a_blank_secret_on_change_keeps_the_one_stored(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Keep Co")["id"]
    r = client.patch(f"{CONNECT}/connections/{cid}", headers=shop["owner"], json={"config": {"api_key": "", "url": "https://other"}})
    assert r.status_code == 200 and r.json()["config"]["url"] == "https://other"
    assert client.post(f"{CONNECT}/connections/{cid}/test", headers=shop["owner"]).json()["ok"] is True
    client.patch(f"{CONNECT}/connections/{cid}", headers=shop["owner"], json={"config": {"api_key": "wrong"}})
    bad = client.post(f"{CONNECT}/connections/{cid}/test", headers=shop["owner"]).json()
    assert bad["ok"] is False and "refused" in bad["message"] and "wrong" not in str(bad)


def test_unknown_or_missing_settings_are_refused(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "kind": "fake_erp", "name": "Nope"}
    assert client.post(f"{CONNECT}/connections", headers=shop["owner"],
                       json={**body, "config": {"url": "https://x"}}).status_code == 422       # api_key is required
    assert client.post(f"{CONNECT}/connections", headers=shop["owner"],
                       json={**body, "config": {"url": "https://x", "api_key": "k", "evil": "1"}}).status_code == 422
    assert client.post(f"{CONNECT}/connections", headers=shop["owner"],
                       json={**body, "kind": "no_such_kind"}).status_code == 404
    made = connection(client, shop, "Dup Co")
    assert made["status"] == "active"
    assert client.post(f"{CONNECT}/connections", headers=shop["owner"], json={
        **body, "name": "dup co", "config": {"url": "https://x", "api_key": "k"}}).status_code == 409


# --------------------------------------------------------------------------- the engine
def test_a_sync_stores_pages_counts_them_and_moves_the_cursor_only_after_a_complete_entity(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Pages Co")["id"]
    FakeErp.SCRIPT = {"sales": [
        CanonicalBatch("sales", (sale("s1"), sale("s2")), cursor="c1", complete=False),
        CanonicalBatch("sales", (sale("s3"),), cursor="c2", complete=True)]}
    result = run(shop, cid)
    assert result.status == "ok" and (result.counts["sales"].read, result.counts["sales"].new) == (3, 3)
    assert count(shop, "src_sale", cid) == 3
    assert scalar(shop, "select cursor from connect.cursor where connection_id = :c and entity = 'sales'", c=cid) == "c2"
    again = run(shop, cid)                                   # the next read starts where the last complete one ended
    assert ("sales", "c2") in FakeErp.CALLS and again.counts["sales"].new == 0
    detail = client.get(f"{CONNECT}/connections/{cid}", headers=shop["owner"]).json()
    assert detail["status"] == "active" and detail["last_success_at"] and detail["counts"]["sales"] == 3
    runs = client.get(f"{CONNECT}/connections/{cid}/runs", headers=shop["owner"]).json()
    assert {r["entity"] for r in runs} >= {"sales"} and runs[0]["status"] == "ok"


def test_re_reading_the_same_records_changes_nothing_and_a_changed_record_is_counted_as_changed(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Idem Co")["id"]
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("a1"), sale("a2")), cursor="x")]}
    first = run(shop, cid)
    second = run(shop, cid)
    assert (first.counts["sales"].new, second.counts["sales"].new, second.counts["sales"].changed) == (2, 0, 0)
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("a1", total="150.00"), sale("a2")), cursor="y")]}
    third = run(shop, cid)
    assert (third.counts["sales"].new, third.counts["sales"].changed) == (0, 1)
    assert count(shop, "src_sale", cid) == 2
    assert scalar(shop, "select total from connect.src_sale where connection_id = :c and ref = 'a1'", c=cid) == D("150")


def test_a_failure_in_the_middle_keeps_what_was_read_and_resumes_from_the_last_good_cursor(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Resume Co")["id"]
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("r1"), sale("r2")), cursor="p1", complete=False),
                                ConnectorError("The system is busy", retryable=True)]}
    failed = run(shop, cid)
    assert failed.status == "failed" and "busy" in (failed.error or "")
    assert count(shop, "src_sale", cid) == 2                                      # page one was kept
    assert scalar(shop, "select count(*) from connect.cursor where connection_id = :c and entity = 'sales'", c=cid) == 0
    c = rows(shop, "select status, failures, last_error, next_sync_at > now() as later from connect.connection where id = :i", i=cid)[0]
    assert (c.status, c.failures, c.later) == ("active", 1, True) and "busy" in c.last_error
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("r1"), sale("r2"), sale("r3")), cursor="p2")]}
    FakeErp.CALLS = []
    ok = run(shop, cid)
    assert ok.status == "ok" and ("sales", None) in FakeErp.CALLS                 # resumed from before the failure
    assert count(shop, "src_sale", cid) == 3
    c = rows(shop, "select failures, last_error from connect.connection where id = :i", i=cid)[0]
    assert c.failures == 0 and c.last_error is None


def test_a_system_that_stops_before_the_end_does_not_advance_the_cursor(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Partial Co")["id"]
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("q1"),), cursor="half", complete=False)]}
    assert run(shop, cid).status == "failed"
    assert scalar(shop, "select count(*) from connect.cursor where connection_id = :c and entity = 'sales'", c=cid) == 0
    assert count(shop, "src_sale", cid) == 1


def test_one_bad_record_is_skipped_and_counted_and_never_stops_the_page(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Bad Co")["id"]
    naive = Sale(ref="bad1", occurred_at=at(TODAY).replace(tzinfo=None), total=D("5"))          # no time zone
    wrong = Sale(ref="bad2", occurred_at=at(TODAY), total=D("5"), status="exploded")             # type: ignore[arg-type]
    nan = Sale(ref="bad3", occurred_at=at(TODAY), total=D("NaN"))
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("good1"), naive, wrong, nan, sale("good2")), cursor="z")]}
    result = run(shop, cid)
    counts = result.counts["sales"]
    assert (counts.read, counts.new, counts.skipped) == (5, 2, 3) and result.status == "partial"
    assert {r.ref for r in rows(shop, "select ref from connect.src_sale where connection_id = :c", c=cid)} == {"good1", "good2"}
    run1 = next(r for r in client.get(f"{CONNECT}/connections/{cid}/runs", headers=shop["owner"]).json() if r["entity"] == "sales")
    assert run1["status"] == "partial" and run1["records_skipped"] == 3 and any("bad1" in n for n in run1["notes"])
    flagged = rows(shop, "select message from kernel.exception_item where unit_name = 'connect' and kind = 'records_skipped'")
    assert any("3 record(s)" in f.message for f in flagged)
    assert scalar(shop, "select count(*) from connect.cursor where connection_id = :c and entity = 'sales'", c=cid) == 1


# --------------------------------------------------------------------------- branches
def test_branches_are_created_automatically_when_the_business_chose_that(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Auto Co", auto_create_branches=True)["id"]
    FakeErp.SCRIPT = {"branches": [CanonicalBatch("branches", (Branch("B7", "Thika Road"),))],
                      "sales": [CanonicalBatch("sales", (sale("t1", branch="B7"), sale("t2", branch="B8")))]}
    run(shop, cid)
    maps = client.get(f"{CONNECT}/connections/{cid}/branches", headers=shop["owner"]).json()
    assert {m["external_ref"]: m["branch_name"] for m in maps} == {"B7": "Thika Road", "B8": "B8"}
    branch_id = scalar(shop, "select branch_id from connect.src_sale where connection_id = :c and ref = 't1'", c=cid)
    assert str(branch_id) == next(m["branch_id"] for m in maps if m["external_ref"] == "B7")
    assert scalar(shop, "select code from kernel.branch where id = :b", b=branch_id) == "THIKAR"
    assert run(shop, cid).counts["sales"].new == 0
    assert scalar(shop, "select count(*) from kernel.branch where name in ('Thika Road', 'B8')") == 2


def test_unmapped_branches_stay_at_company_level_until_mapped_and_ignored_ones_are_not_read(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Map Co")["id"]
    FakeErp.SCRIPT = {"branches": [CanonicalBatch("branches", (Branch("N1", "North"), Branch("S1", "South")))],
                      "sales": [CanonicalBatch("sales", (sale("m1", branch="N1"), sale("m2", branch="S1")))]}
    run(shop, cid)
    assert scalar(shop, "select count(*) from kernel.branch where name in ('North', 'South')") == 0
    detail = client.get(f"{CONNECT}/connections/{cid}", headers=shop["owner"]).json()
    assert detail["unmapped_branches"] == 2
    assert scalar(shop, "select count(*) from connect.src_sale where connection_id = :c and branch_id is null", c=cid) == 2
    r = client.put(f"{CONNECT}/connections/{cid}/branches", headers=shop["owner"],
                   json={"external_ref": "N1", "branch_id": str(shop["juja"])})
    assert r.status_code == 200, r.text
    assert str(scalar(shop, "select branch_id from connect.src_sale where connection_id = :c and ref = 'm1'", c=cid)) == str(shop["juja"])
    assert client.put(f"{CONNECT}/connections/{cid}/branches", headers=shop["owner"],
                      json={"external_ref": "S1", "ignored": True}).status_code == 200
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("m3", branch="S1"), sale("m4", branch="N1")))]}
    result = run(shop, cid)
    assert (result.counts["sales"].new, result.counts["sales"].skipped) == (1, 1)
    assert client.put(f"{CONNECT}/connections/{cid}/branches", headers=shop["owner"],
                      json={"external_ref": "N1", "branch_id": str(shop["juja"]), "ignored": True}).status_code == 422
    foreign = client.put(f"{CONNECT}/connections/{cid}/branches", headers=shop["owner"],
                         json={"external_ref": "N1", "branch_id": "00000000-0000-0000-0000-000000000001"})
    assert foreign.status_code == 422
    made = client.put(f"{CONNECT}/connections/{cid}/branches", headers=shop["owner"],
                      json={"external_ref": "N1", "create_branch": True})
    assert made.status_code == 200 and next(m for m in made.json() if m["external_ref"] == "N1")["branch_name"] == "North"


# --------------------------------------------------------------------------- problems
def test_a_refused_key_stops_the_connection_and_puts_it_in_the_inbox(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Refused Co")["id"]
    FakeErp.SCRIPT = {"sales": [ConnectorError("The key was refused", retryable=False)]}
    result = run(shop, cid)
    assert result.status == "failed"
    c = client.get(f"{CONNECT}/connections/{cid}", headers=shop["owner"]).json()
    assert c["status"] == "error" and c["next_sync_at"] is None and "refused" in c["last_error"]
    flagged = rows(shop, "select severity, message from kernel.exception_item where kind = 'sync_failed' and message like 'Refused Co%'")
    assert flagged and flagged[0].severity == "high"
    assert client.post(f"{CONNECT}/connections/{cid}/resume", headers=shop["owner"]).json()["status"] == "active"


def test_three_failures_in_a_row_mark_the_connection_but_keep_retrying_with_a_delay(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Retry Co")["id"]
    FakeErp.SCRIPT = {"sales": [ConnectorError("Down", retryable=True)]}
    for _ in range(3):
        run(shop, cid)
    c = rows(shop, "select status, failures, next_sync_at - now() as wait from connect.connection where id = :i", i=cid)[0]
    assert (c.status, c.failures) == ("error", 3) and c.wait > timedelta(minutes=10)
    assert sync.retry_delay(1) == timedelta(minutes=5) and sync.retry_delay(2) == timedelta(minutes=10)
    assert sync.retry_delay(20) == timedelta(hours=6)


def test_an_unexpected_error_in_a_connector_becomes_a_plain_failure_not_a_crash(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Crash Co")["id"]
    FakeErp.SCRIPT = {"sales": [KeyError("boom")]}
    result = run(shop, cid)
    assert result.status == "failed" and "KeyError" in (result.error or "") and "boom" not in (result.error or "")


# --------------------------------------------------------------------------- background work
def test_sync_now_is_queued_for_the_worker_and_a_double_click_is_one_run(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Queue Co")["id"]
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("w1"),), cursor="w")]}
    first = client.post(f"{CONNECT}/connections/{cid}/sync", headers=shop["owner"], json={})
    second = client.post(f"{CONNECT}/connections/{cid}/sync", headers=shop["owner"], json={})
    assert (first.status_code, first.json()["queued"], second.json()["queued"]) == (202, True, False)
    assert count(shop, "src_sale", cid) == 0                                      # nothing was read in the request
    jobs.run_due(shop["tenant_id"])
    assert count(shop, "src_sale", cid) == 1
    assert client.post(f"{CONNECT}/connections/{cid}/sync", headers=shop["owner"], json={}).json()["queued"] is True


def test_the_recurring_task_queues_only_connections_whose_window_has_passed(client, shop) -> None:  # type: ignore[no-untyped-def]
    due = connection(client, shop, "Due Co")["id"]
    later = connection(client, shop, "Later Co")["id"]
    paused = connection(client, shop, "Paused Co")["id"]
    client.post(f"{CONNECT}/connections/{paused}/pause", headers=shop["owner"])
    with system(shop) as s:
        s.execute(text("update connect.connection set next_sync_at = now() + interval '3 hours' where id = :i"), {"i": later})
        s.execute(text("update connect.connection set next_sync_at = now() - interval '1 minute' where id = :i"), {"i": due})
        queued = sync.queue_due(s)
        waiting = {r.payload["connection_id"] for r in s.execute(text("select payload from kernel.job where job_type = 'connect.sync' and status = 'queued'"))}
    assert due in waiting and later not in waiting and paused not in waiting and queued >= 1
    jobs.run_due(shop["tenant_id"])
    assert scalar(shop, "select next_sync_at > now() from connect.connection where id = :i", i=due)


def test_file_connections_are_never_synced_on_a_schedule(client, shop) -> None:  # type: ignore[no-untyped-def]
    made = new_connection(client, shop, "csv_sales", "Files Co")
    assert made["next_sync_at"] is None and made["freshness"] == "on_upload"
    assert client.post(f"{CONNECT}/connections/{made['id']}/sync", headers=shop["owner"], json={}).status_code == 422


# --------------------------------------------------------------------------- pause, disconnect, privacy
def test_pausing_stops_scheduled_reads_and_disconnecting_forgets_the_key_and_can_delete_the_data(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Bye Co")["id"]
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("d1"), sale("d2")), cursor="d")],
                      "users": [CanonicalBatch("users", (User("u1", "Ann Wanjiku"),))]}
    run(shop, cid)
    assert client.post(f"{CONNECT}/connections/{cid}/pause", headers=shop["owner"]).json()["status"] == "paused"
    assert run(shop, cid).status == "skipped"
    credential = scalar(shop, "select credential_id from connect.connection where id = :i", i=cid)
    kept = client.post(f"{CONNECT}/connections/{cid}/disconnect", headers=shop["owner"], json={"delete_data": False})
    assert kept.status_code == 200 and kept.json()["removed"] == {}
    assert count(shop, "src_sale", cid) == 2                                       # kept for history
    assert scalar(shop, "select status from connect.connection where id = :i", i=cid) == "disconnected"
    from ziira.kernel.security import decrypt
    cipher = scalar(shop, "select secret_ciphertext from kernel.integration_credential where id = :i", i=credential)
    assert "key-1" not in decrypt(bytes(cipher).decode()) and "revoked" in decrypt(bytes(cipher).decode())
    gone = client.post(f"{CONNECT}/connections/{cid}/disconnect", headers=shop["owner"], json={"delete_data": True})
    assert gone.json()["removed"]["sales"] == 2 and gone.json()["removed"]["users"] == 1
    assert count(shop, "src_sale", cid) == 0 and count(shop, "src_user", cid) == 0
    assert scalar(shop, "select count(*) from connect.cursor where connection_id = :c", c=cid) == 0
    assert client.post(f"{CONNECT}/connections/{cid}/sync", headers=shop["owner"], json={}).status_code == 422


def test_disconnected_data_leaves_the_coverage_and_the_checks(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Cover Co")["id"]
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("c1"),), cursor="c")]}
    run(shop, cid)
    cov = client.get(f"{CONNECT}/coverage", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    assert cov["connected"].get("sales", 0) >= 1
    client.post(f"{CONNECT}/connections/{cid}/disconnect", headers=shop["owner"], json={"delete_data": True})
    from ziira.modules.connect.services import coverage

    with system(shop) as s:
        supply = coverage.supplied(s, shop["company_id"])
    assert str(cid) not in supply.ids("sales")


def test_personal_data_of_parties_and_users_is_found_exported_and_erased_and_stays_erased(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.connect.public import Party

    cid = connection(client, shop, "Privacy Co")["id"]
    FakeErp.SCRIPT = {
        "payments": [CanonicalBatch("payments", (Payment("pay1", at(TODAY), "in", D("500"), party_ref="P1", party_name="Wanjiru Kamau"),))],
        "users": [CanonicalBatch("users", (User("U1", "Peter Otieno", email="peter@privacy.test"),))]}
    from tests.connect_helpers import Planter
    Planter(shop, UUID(cid)).put("parties", [Party("P1", "customer", "Wanjiru Kamau", "+254 700 111 222",
                                                   "wanjiru@privacy.test", "A001")])
    run(shop, cid)
    from ziira.kernel import extensions
    from ziira.kernel.personal_data import parse_subject

    provider = next(impl for unit, impl in extensions._points["kernel.personal_data"].implementations if unit == "connect")()
    with system(shop) as s:
        found = provider.find(s, shop["company_id"], parse_subject("wanjiru@privacy.test", "254"))
        assert [(f.source, f.kind) for f in found] == [("connect", "party")]
        assert provider.find(s, shop["company_id"], parse_subject("+254 700 111 222", "254"))[0].kind == "party"
        assert provider.find(s, shop["company_id"], parse_subject("peter@privacy.test", "254"))[0].kind == "user"
        exported = provider.export(s, found[0])
        assert exported["party"]["email"] == "wanjiru@privacy.test" and "content_hash" not in exported["party"]
        outcome = provider.anonymise(s, found[0], "request")
        assert outcome.status == "anonymised" and any("other system" in k.what for k in outcome.kept)
    row = rows(shop, "select name, phone, email, tax_id, erased from connect.src_party where connection_id = :c", c=cid)[0]
    assert row.name.startswith("[erased]") and (row.phone, row.email, row.tax_id, row.erased) == (None, None, None, True)
    assert scalar(shop, "select party_name from connect.src_payment where connection_id = :c", c=cid) == "[erased]"
    Planter(shop, UUID(cid)).put("parties", [Party("P1", "customer", "Wanjiru Kamau", "+254 700 111 222",
                                                   "wanjiru@privacy.test", "A001")])      # the source still has her
    row = rows(shop, "select name, email from connect.src_party where connection_id = :c", c=cid)[0]
    assert row.name.startswith("[erased]") and row.email is None
    with system(shop) as s:
        assert provider.find(s, shop["company_id"], parse_subject("wanjiru@privacy.test", "254")) == []


# --------------------------------------------------------------------------- access
def test_permissions_isolation_and_every_endpoint_checks_access(client, registry, shop) -> None:  # type: ignore[no-untyped-def]
    cid = connection(client, shop, "Access Co")["id"]
    other = make_connect_shop(client, registry, "Other Sync Co")
    anon = client.get(f"{CONNECT}/connections")
    assert anon.status_code in (401, 403)
    # a view-only role reads but cannot change
    acc = shop["accountant"]
    assert client.get(f"{CONNECT}/connections/{cid}", headers=acc).status_code == 200
    assert client.get(f"{CONNECT}/kinds", headers=acc).status_code == 200
    body = {"company_id": str(shop["company_id"]), "kind": "csv_sales", "name": "Nope Co"}
    for call in (lambda: client.post(f"{CONNECT}/connections", headers=acc, json=body),
                 lambda: client.patch(f"{CONNECT}/connections/{cid}", headers=acc, json={"name": "x1"}),
                 lambda: client.post(f"{CONNECT}/connections/{cid}/test", headers=acc),
                 lambda: client.post(f"{CONNECT}/connections/{cid}/sync", headers=acc, json={}),
                 lambda: client.post(f"{CONNECT}/connections/{cid}/pause", headers=acc),
                 lambda: client.post(f"{CONNECT}/connections/{cid}/disconnect", headers=acc, json={}),
                 lambda: client.put(f"{CONNECT}/connections/{cid}/branches", headers=acc, json={"external_ref": "x"}),
                 lambda: client.post(f"{CONNECT}/connections/{cid}/upload", headers=acc, content=b"a,b\n1,2\n")):
        assert call().status_code == 403
    # another business sees nothing of this one
    assert client.get(f"{CONNECT}/connections", headers=other["owner"]).json() == []
    assert client.get(f"{CONNECT}/connections/{cid}", headers=other["owner"]).status_code == 404
    assert client.post(f"{CONNECT}/connections/{cid}/disconnect", headers=other["owner"], json={}).status_code == 404
    assert client.get(f"{CONNECT}/coverage", headers=other["owner"], params={"company_id": str(shop["company_id"])}).status_code in (403, 404, 422)
    # the connection is never created in a company the caller does not have
    foreign = client.post(f"{CONNECT}/connections", headers=other["owner"], json={**body, "company_id": str(shop["company_id"])})
    assert foreign.status_code in (403, 404, 422)
    assert scalar(shop, "select count(*) from connect.connection where name = 'Nope Co'") == 0


def test_rotated_secrets_are_saved_even_when_the_read_fails_and_notes_reach_the_history(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.connect.services import connections as conns

    cid = connection(client, shop, "Rotate Co")["id"]
    FakeErp.ROTATE = {"api_key": "key-2"}
    FakeErp.NOTES = ["Skipped orders: not installed."]
    FakeErp.SCRIPT = {"sales": [ConnectorError("Down", retryable=True)]}
    assert run(shop, cid).status == "failed"
    with system(shop) as s:
        row = conns.get(s, UUID(cid))
        assert conns.load_secrets(s, row)["api_key"] == "key-2"
    FakeErp.SCRIPT = {"sales": [CanonicalBatch("sales", (sale("rot1"),), cursor="r")]}
    assert run(shop, cid).status == "ok"
    notes = [n for r in client.get(f"{CONNECT}/connections/{cid}/runs", headers=shop["owner"]).json() for n in r["notes"]]
    assert "Skipped orders: not installed." in notes
