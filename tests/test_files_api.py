"""Files and photos through the API with real sign-ins: upload and type spoofing, limits, the permission matrix, tenant
isolation, signed and public links (expiry, revocation, logging), delete, privacy, retention and `ziira verify`."""

import os
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests import files_helpers as fx
from tests.stock_helpers import make_stock_shop, system
from ziira.kernel.files import checks, service, tokens
from ziira.kernel.files.privacy import FileData
from ziira.kernel.files.store import forget_store
from ziira.kernel.personal_data import Subject

F, ET = "/api/v1/files", "products.product"


@pytest.fixture(scope="module", autouse=True)
def files_folder(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    from ziira.kernel.config import get_settings

    folder = tmp_path_factory.mktemp("files")
    before = os.environ.get("ZIIRA_FILES_DIR")
    os.environ["ZIIRA_FILES_DIR"] = str(folder)
    get_settings.cache_clear()
    forget_store()
    yield folder
    if before is None:
        os.environ.pop("ZIIRA_FILES_DIR", None)
    else:
        os.environ["ZIIRA_FILES_DIR"] = before
    get_settings.cache_clear()
    forget_store()


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_stock_shop(client, registry, "Files Shop")


@pytest.fixture(scope="module")
def other(client, registry):  # type: ignore[no-untyped-def]
    return make_stock_shop(client, registry, "Files Other")


def put(client, shop, data: bytes, *, who="owner", entity=None, name="front.jpg", ctype="image/jpeg", params="",  # type: ignore[no-untyped-def]
        caption="", key=None, headers=None):
    h = {**shop[who], "Content-Type": ctype, "X-File-Name": quote(name)}
    if caption:
        h["X-File-Caption"] = quote(caption)
    if key:
        h["Idempotency-Key"] = key
    h.update(headers or {})
    return client.post(f"{F}?entity_type={ET}&entity_id={entity or shop['cement']}{params}", headers=h, content=data)


def stored_files(folder: Path, shop) -> list[Path]:  # type: ignore[no-untyped-def]
    return [p for p in (folder / str(shop["tenant_id"])).rglob("*") if p.is_file()] if (
        folder / str(shop["tenant_id"])).exists() else []


def settings(client, shop, **values):  # type: ignore[no-untyped-def]
    r = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"], json=values)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- upload and download
def test_a_photo_is_stored_with_copies_and_opened_through_signed_addresses(client, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    r = put(client, shop, fx.jpeg((3000, 2000), gps=True), params="&category=damage", caption="Front left dent")
    assert r.status_code == 201, r.text
    f = r.json()
    assert (f["kind"], f["content_type"], f["name"], f["category"], f["visibility"], f["caption"]) == (
        "image", "image/jpeg", "front.jpg", "damage", "staff", "Front left dent")
    assert f["location_stripped"] is True and f["created_by_name"] == "Files Shop Owner"
    assert len(stored_files(files_folder, shop)) >= 3                                  # original, web copy, thumbnail
    thumb = client.get(f["thumb_url"])                                                  # no sign-in: the address is the proof
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert thumb.headers["x-content-type-options"] == "nosniff"
    stored = client.get(f"{F}/{f['id']}/content?variant=original", headers=shop["owner"])
    assert stored.status_code == 200 and not fx.exif_of(stored.content)["gps"]          # the position was removed
    assert client.get(f"{F}/{f['id']}/content?variant=original").status_code == 401     # the path itself needs a token


def test_a_picture_uploaded_without_a_name_or_with_a_lying_type_is_judged_by_its_bytes(client, shop) -> None:  # type: ignore[no-untyped-def]
    pdf = put(client, shop, fx.pdf(), name="photo.jpg", ctype="image/jpeg")
    assert pdf.status_code == 201 and (pdf.json()["kind"], pdf.json()["name"]) == ("pdf", "photo.pdf")
    assert pdf.json()["thumb_url"] is None
    png = put(client, shop, fx.png(), name="x.pdf", ctype="application/pdf")
    assert (png.json()["content_type"], png.json()["name"]) == ("image/png", "x.png")
    for fake, ctype in ((b"MZ" + b"\x00" * 300, "image/jpeg"), (b"<script>1</script>", "image/png"),
                        (b"", "image/jpeg"), (fx.gif_animated(), "image/gif"), (b"%PDF-1.4 nope", "application/pdf")):
        bad = put(client, shop, fake, name="evil.jpg", ctype=ctype)
        assert bad.status_code == 422, (fake[:10], bad.text)


def test_names_and_captions_travel_in_headers_as_utf8_and_stay_out_of_the_url(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = put(client, shop, fx.jpeg(), name="gari ya mteja – mbele.jpg", caption="Bumper ya mbele ✓")
    assert r.status_code == 201 and r.json()["caption"] == "Bumper ya mbele ✓"
    assert r.json()["name"].startswith("gari ya mteja")
    assert put(client, shop, fx.jpeg(), headers={"X-File-Caption": "%ff%fe"}).status_code == 422     # not valid UTF-8
    assert put(client, shop, fx.jpeg(), caption="x" * 301).status_code == 422


def test_a_retry_with_the_same_key_stores_one_file(client, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    key = str(uuid4())
    first = put(client, shop, fx.jpeg(colour=(1, 2, 3)), key=key, entity=shop["paint"])
    again = put(client, shop, fx.jpeg(colour=(9, 9, 9)), key=key, entity=shop["paint"])
    assert first.status_code == 201 and again.status_code == 201 and first.json()["id"] == again.json()["id"]
    assert len(client.get(f"{F}?entity_type={ET}&entity_id={shop['paint']}", headers=shop["owner"]).json()) == 1
    assert put(client, shop, fx.jpeg(), key="not-a-uuid", entity=shop["paint"]).status_code == 201     # any text works


def test_the_listing_config_and_unknown_records(client, shop) -> None:  # type: ignore[no-untyped-def]
    entity = shop["delivery"]
    put(client, shop, fx.jpeg(), entity=entity, params="&category=photo")
    put(client, shop, fx.pdf(), entity=entity, params="&category=document")
    listed = client.get(f"{F}?entity_type={ET}&entity_id={entity}", headers=shop["owner"]).json()
    assert [f["category"] for f in listed] == ["photo", "document"]
    only = client.get(f"{F}?entity_type={ET}&entity_id={entity}&category=document", headers=shop["owner"]).json()
    assert [f["kind"] for f in only] == ["pdf"]
    cfg = client.get(f"{F}/config?entity_type={ET}&entity_id={entity}", headers=shop["owner"]).json()
    assert (cfg["can_add"], cfg["count"], cfg["max_per_record"]) == (True, 2, 60)
    assert [c["key"] for c in cfg["categories"]] == ["photo", "document"] and "image/jpeg" in cfg["accepted"]
    assert client.get(f"{F}?entity_type={ET}&entity_id={uuid4()}", headers=shop["owner"]).status_code == 404
    assert client.get(f"{F}?entity_type=nothing.here&entity_id={entity}", headers=shop["owner"]).status_code == 404
    assert put(client, shop, fx.jpeg(), entity=str(uuid4())).status_code == 404
    assert put(client, shop, fx.jpeg(), params="&category=Bad%20Kind").status_code == 422
    assert put(client, shop, fx.jpeg(), params="&visibility=public").status_code == 422


# --------------------------------------------------------------------------- limits
def test_the_size_of_a_file_is_a_company_setting(client, shop) -> None:  # type: ignore[no-untyped-def]
    settings(client, shop, files_max_file_mb=1)
    try:
        too_big = put(client, shop, fx.noise_png(700), entity=shop["cement"])
        assert too_big.status_code == 422 and "1 MB" in too_big.json()["message"]
        assert put(client, shop, fx.noise_png(100)).status_code == 201
    finally:
        settings(client, shop, files_max_file_mb=10)
    assert put(client, shop, fx.noise_png(700)).status_code == 201


def test_the_number_of_files_per_record_is_a_company_setting(client, shop) -> None:  # type: ignore[no-untyped-def]
    entity = shop["paint"]
    first = put(client, shop, fx.jpeg(colour=(8, 8, 8)), entity=entity)
    held = len(client.get(f"{F}?entity_type={ET}&entity_id={entity}", headers=shop["owner"]).json())
    assert first.status_code == 201
    settings(client, shop, files_max_per_record=held)
    try:
        r = put(client, shop, fx.jpeg(colour=(9, 8, 8)), entity=entity)
        assert r.status_code == 422 and "already has" in r.json()["message"]
    finally:
        settings(client, shop, files_max_per_record=60)
    assert put(client, shop, fx.jpeg(colour=(9, 8, 8)), entity=entity).status_code == 201


def test_the_space_of_a_company_is_a_setting_and_the_plan_can_cap_the_business(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    used = client.get(f"{F}/usage", headers=shop["owner"]).json()
    assert used["files"] >= 1 and used["bytes"] > 0 and used["plan_limit_bytes"] is None and used["company_limit_bytes"] == 0
    settings(client, shop, files_storage_limit_mb=1)
    try:
        refused = put(client, shop, fx.noise_png(900), entity=shop["delivery"])
        assert refused.status_code == 422 and "limit" in refused.json()["message"]
    finally:
        settings(client, shop, files_storage_limit_mb=0)
    monkeypatch.setattr(service, "_plan_storage_mb", lambda: 0)
    blocked = put(client, shop, fx.jpeg(), entity=shop["delivery"])
    assert blocked.status_code == 402 and blocked.json()["error"] == "plan_limit_reached"
    assert client.get(f"{F}/usage", headers=shop["owner"]).json()["plan_limit_bytes"] == 0
    monkeypatch.setattr(service, "_plan_storage_mb", lambda: None)
    assert put(client, shop, fx.jpeg(colour=(77, 7, 7)), entity=shop["delivery"]).status_code == 201


def test_the_settings_page_exposes_the_file_settings(client, shop) -> None:  # type: ignore[no-untyped-def]
    now = settings(client, shop, files_strip_location=True, retention_file_access_days=365)
    assert now["files_max_file_mb"] == 10 and now["files_max_per_record"] == 60 and now["retention_files_years"] == 0
    bad = client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=shop["owner"],
                       json={"files_max_file_mb": 100})
    assert bad.status_code == 422


def test_location_is_kept_in_the_original_only_when_the_business_chooses(client, shop) -> None:  # type: ignore[no-untyped-def]
    settings(client, shop, files_strip_location=False)
    try:
        r = put(client, shop, fx.jpeg(gps=True), entity=shop["delivery"])
    finally:
        settings(client, shop, files_strip_location=True)
    assert r.status_code == 201 and r.json()["location_stripped"] is False
    original = client.get(f"{F}/{r.json()['id']}/content?variant=original", headers=shop["owner"]).content
    assert fx.exif_of(original)["gps"]
    assert not fx.exif_of(client.get(f"{F}/{r.json()['id']}/content?variant=web", headers=shop["owner"]).content)["gps"]


# --------------------------------------------------------------------------- permissions and isolation
def test_the_permission_matrix(client, shop) -> None:  # type: ignore[no-untyped-def]
    f = put(client, shop, fx.jpeg(), entity=shop["cement"]).json()
    reading = {"owner": 200, "boss": 200, "manager": 200, "cashier": 200, "storekeeper": 200}
    for who, status in reading.items():
        assert client.get(f"{F}?entity_type={ET}&entity_id={shop['cement']}", headers=shop[who]).status_code == status, who
        assert client.get(f"{F}/{f['id']}", headers=shop[who]).status_code == status, who
        assert client.post(f"{F}/{f['id']}/link", headers=shop[who], json={"variant": "web"}).status_code == status, who
    editing = {"owner": 201, "boss": 201, "manager": 403, "cashier": 403, "storekeeper": 403, "juja_keeper": 403}
    for who, status in editing.items():
        assert put(client, shop, fx.jpeg(colour=(len(who), 1, 1)), who=who).status_code == status, who
    for who in ("cashier", "storekeeper", "manager"):
        assert client.patch(f"{F}/{f['id']}", headers=shop[who], json={"caption": "x"}).status_code == 403
        assert client.post(f"{F}/{f['id']}/delete", headers=shop[who], json={"reason": "no right"}).status_code == 403
        assert client.post(f"{F}/{f['id']}/revoke-links", headers=shop[who]).status_code == 403
    cfg = client.get(f"{F}/config?entity_type={ET}&entity_id={shop['cement']}", headers=shop["cashier"]).json()
    assert cfg["can_add"] is False
    assert client.get(f"{F}/{f['id']}/access", headers=shop["boss"]).status_code == 403          # files.audit is the owner's
    assert client.get(f"{F}/{f['id']}/access", headers=shop["owner"]).status_code == 200
    assert client.get(f"{F}/usage", headers=shop["cashier"]).status_code == 403
    for method, path in (("get", f"{F}?entity_type={ET}&entity_id={shop['cement']}"), ("get", f"{F}/{f['id']}"),
                         ("post", f"{F}/{f['id']}/link"), ("get", f"{F}/config?entity_type={ET}&entity_id={shop['cement']}")):
        assert getattr(client, method)(path).status_code == 401                                   # nobody signed in


def test_a_person_with_no_role_sees_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import sign_in

    email = "norole@files-shop.test"
    made = client.post("/api/v1/users", headers=shop["owner"],
                       json={"full_name": "No Role", "email": email, "password": "norole-pass-1"})
    assert made.status_code == 201, made.text
    headers = sign_in(client, shop["code"], email, "norole-pass-1").headers
    assert client.get(f"{F}?entity_type={ET}&entity_id={shop['cement']}", headers=headers).status_code == 403
    upload = client.post(f"{F}?entity_type={ET}&entity_id={shop['cement']}", headers={**headers, "Content-Type": "image/jpeg"},
                         content=fx.jpeg())
    assert upload.status_code == 403


def test_one_business_never_sees_anothers_files(client, shop, other) -> None:  # type: ignore[no-untyped-def]
    mine = put(client, shop, fx.jpeg()).json()
    theirs = put(client, other, fx.jpeg(colour=(0, 0, 9)), entity=other["cement"]).json()
    for call in (lambda: client.get(f"{F}/{mine['id']}", headers=other["owner"]),
                 lambda: client.get(f"{F}/{mine['id']}/content", headers=other["owner"]),
                 lambda: client.patch(f"{F}/{mine['id']}", headers=other["owner"], json={"caption": "mine now"}),
                 lambda: client.post(f"{F}/{mine['id']}/delete", headers=other["owner"], json={"reason": "tidy up"}),
                 lambda: client.post(f"{F}/{mine['id']}/link", headers=other["owner"], json={}),
                 lambda: client.get(f"{F}?entity_type={ET}&entity_id={shop['cement']}", headers=other["owner"]),
                 lambda: put(client, other, fx.jpeg(), entity=shop["cement"])):
        assert call().status_code == 404
    assert client.get(f"{F}/{theirs['id']}", headers=shop["owner"]).status_code == 404
    with system(other) as s:                                                              # even in the database
        assert s.execute(text("select count(*) from kernel.attachment where id = :i"), {"i": mine["id"]}).scalar_one() == 0


def test_a_link_made_for_one_business_opens_only_its_own_file(client, shop, other) -> None:  # type: ignore[no-untyped-def]
    mine = put(client, shop, fx.jpeg()).json()
    claims = tokens.read(client.post(f"{F}/{mine['id']}/link", headers=shop["owner"], json={}).json()["path"].split("/")[-1])
    forged = tokens.make(tokens.LinkClaims(other["tenant_id"], claims.file_id, "web", claims.expires, claims.epoch, "staff"))
    assert client.get(f"{F}/dl/{forged}").status_code == 404                              # the file is not in that business


# --------------------------------------------------------------------------- links: expiry, revocation, logging
def public(shop, entity, **kw):  # type: ignore[no-untyped-def]
    from ziira.sdk import files

    with system(shop) as s:
        return files.public_links(s, ET, entity, label=kw.pop("label", "insurer response CLM-1"), **kw)


def test_public_pages_get_only_shareable_files_with_logged_addresses(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    entity = shop["paint"]
    shared = put(client, shop, fx.jpeg(colour=(11, 22, 33)), entity=entity, params="&visibility=shareable").json()
    staff = put(client, shop, fx.jpeg(colour=(33, 22, 11)), entity=entity).json()
    shown = public(shop, entity)
    assert {p.id for p in shown} == {UUID(shared["id"])} and UUID(staff["id"]) not in {p.id for p in shown}
    page = next(p for p in shown if str(p.id) == shared["id"])
    assert page.thumb and page.web and page.original and page.original.expires_at > page.thumb.expires_at.replace(year=2000)
    assert client.get(page.thumb.path).status_code == 200
    web = client.get(page.web.path)
    assert web.status_code == 200 and web.headers["cache-control"] == "private, max-age=300"
    full = client.get(page.original.path)
    assert full.status_code == 200 and full.headers["cache-control"] == "no-store"
    log = client.get(f"{F}/{shared['id']}/access", headers=shop["owner"]).json()
    rows = [r for r in log if r["via"] == "link"]
    assert {r["variant"] for r in rows} == {"web", "original"}                        # thumbnails are not logged
    assert all(r["purpose"] == "public" and r["label"] == "insurer response CLM-1" for r in rows)
    from ziira.kernel.config import get_settings
    monkeypatch.setattr(get_settings(), "trust_forwarded_for", True)
    assert client.get(page.original.path, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 200
    newest = client.get(f"{F}/{shared['id']}/access", headers=shop["owner"]).json()[0]
    assert (newest["via"], newest["ip"]) == ("link", "203.0.113.9")                  # the visitor's address is kept


def test_a_link_stops_when_revoked_when_made_staff_only_when_deleted_or_when_it_ends(client, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    entity = shop["delivery"]
    one = put(client, shop, fx.jpeg(colour=(1, 1, 1)), entity=entity, params="&visibility=shareable").json()
    two = put(client, shop, fx.jpeg(colour=(2, 2, 2)), entity=entity, params="&visibility=shareable").json()
    three = put(client, shop, fx.jpeg(colour=(3, 3, 3)), entity=entity, params="&visibility=shareable").json()
    by_id = {str(p.id): p for p in public(shop, entity)}
    assert all(client.get(by_id[i["id"]].original.path).status_code == 200 for i in (one, two, three))
    # revoke one file's links
    assert client.post(f"{F}/{one['id']}/revoke-links", headers=shop["owner"]).status_code == 204
    assert client.get(by_id[one["id"]].original.path).status_code == 404
    assert client.get(by_id[two["id"]].original.path).status_code == 200
    # making a file staff-only ends its links at once
    assert client.patch(f"{F}/{two['id']}", headers=shop["owner"], json={"visibility": "staff"}).status_code == 200
    assert client.get(by_id[two["id"]].original.path).status_code == 404
    # a file made shareable again does not revive old addresses, new ones work
    client.patch(f"{F}/{two['id']}", headers=shop["owner"], json={"visibility": "shareable"})
    assert client.get(by_id[two["id"]].original.path).status_code == 404
    assert client.get(next(p for p in public(shop, entity) if str(p.id) == two["id"]).original.path).status_code == 200
    # delete: links stop, bytes go, nothing is left
    before = len(stored_files(files_folder, shop))
    assert client.post(f"{F}/{three['id']}/delete", headers=shop["owner"], json={"reason": "wrong job"}).status_code == 204
    assert client.get(by_id[three["id"]].original.path).status_code == 404
    assert len(stored_files(files_folder, shop)) == before - 3
    # revoke everything for the record
    from ziira.sdk import files
    with system(shop) as s:
        assert files.revoke_links_for_entity(s, ET, entity) >= 1
    assert all(client.get(p.original.path).status_code == 404 for p in by_id.values())


def test_a_link_that_has_ended_or_was_tampered_with_gets_the_same_answer(client, shop) -> None:  # type: ignore[no-untyped-def]
    f = put(client, shop, fx.jpeg(), entity=shop["cement"], params="&visibility=shareable").json()
    claims = tokens.read(client.post(f"{F}/{f['id']}/link", headers=shop["owner"], json={}).json()["path"].split("/")[-1])
    ended = tokens.make(tokens.LinkClaims(claims.tenant_id, claims.file_id, "web", int(time.time()) - 5, claims.epoch, "public"))
    live = tokens.make(tokens.LinkClaims(claims.tenant_id, claims.file_id, "web", int(time.time()) + 60, claims.epoch, "public"))
    assert client.get(f"{F}/dl/{live}").status_code == 200
    answers = {client.get(f"{F}/dl/{t}").json()["message"] for t in (ended, live[:-3] + "abc", "garbage", live.split(".")[0])}
    assert answers == {"This link is not valid"} and client.get(f"{F}/dl/{ended}").status_code == 404
    staff_only = tokens.make(tokens.LinkClaims(claims.tenant_id, claims.file_id, "web", int(time.time()) + 60, claims.epoch, "public"))
    client.patch(f"{F}/{f['id']}", headers=shop["owner"], json={"visibility": "staff"})
    assert client.get(f"{F}/dl/{staff_only}").status_code == 404                      # a public link needs a shareable file


def test_who_opened_a_file_is_recorded(client, shop) -> None:  # type: ignore[no-untyped-def]
    f = put(client, shop, fx.jpeg(), entity=shop["cement"]).json()
    client.get(f"{F}/{f['id']}/content?variant=original", headers=shop["cashier"])
    client.get(f"{F}/{f['id']}/content?variant=thumb", headers=shop["cashier"])               # not logged
    link = client.post(f"{F}/{f['id']}/link", headers=shop["boss"], json={"variant": "original"}).json()["path"]
    client.get(link)
    log = client.get(f"{F}/{f['id']}/access", headers=shop["owner"]).json()
    assert [(r["via"], r["variant"], r["user_name"]) for r in log].count(("staff", "original", "cashier")) == 1
    assert any(r["via"] == "link" and r["purpose"] == "staff" and r["user_name"] == "boss" for r in log)
    assert not any(r["variant"] == "thumb" for r in log)


# --------------------------------------------------------------------------- change and delete
def test_a_file_is_changed_and_deleted_with_a_reason(client, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    f = put(client, shop, fx.jpeg(colour=(50, 60, 70)), entity=shop["paint"], caption="Old part").json()
    p = client.patch(f"{F}/{f['id']}", headers=shop["owner"], json={"caption": "Old part, rusted", "category": "parts",
                                                                      "visibility": "shareable"})
    assert p.status_code == 200 and (p.json()["caption"], p.json()["category"], p.json()["visibility"]) == (
        "Old part, rusted", "parts", "shareable")
    assert client.patch(f"{F}/{f['id']}", headers=shop["owner"], json={"category": "Bad Kind"}).status_code == 422
    assert client.patch(f"{F}/{f['id']}", headers=shop["owner"], json={"nope": 1}).status_code == 422
    before = len(stored_files(files_folder, shop))
    assert client.post(f"{F}/{f['id']}/delete", headers=shop["owner"], json={}).status_code == 422
    assert client.post(f"{F}/{f['id']}/delete", headers=shop["owner"], json={"reason": "  "}).status_code == 422
    assert client.post(f"{F}/{f['id']}/delete", headers=shop["owner"], json={"reason": "taken twice"}).status_code == 204
    assert len(stored_files(files_folder, shop)) == before - 3
    for call in (lambda: client.get(f"{F}/{f['id']}", headers=shop["owner"]),
                 lambda: client.get(f"{F}/{f['id']}/content", headers=shop["owner"]),
                 lambda: client.post(f"{F}/{f['id']}/delete", headers=shop["owner"], json={"reason": "again"})):
        assert call().status_code == 404
    with system(shop) as s:
        row = s.execute(text("select status, caption, original_name, delete_reason, blobs_removed from kernel.attachment "
                             "where id = :i"), {"i": f["id"]}).one()
        audit = s.execute(text("select changes from kernel.audit_log where entity_type = 'kernel.attachment' and "
                               "entity_id = :i and action = 'delete'"), {"i": f["id"]}).scalar_one()
    assert (row.status, row.caption, row.original_name, row.delete_reason) == ("deleted", "", "", "taken twice")
    assert audit["reason"] == "taken twice"


def test_the_work_of_a_rolled_back_transaction_leaves_no_bytes(client, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import files

    before = set(stored_files(files_folder, shop))
    with pytest.raises(RuntimeError), system(shop) as s:
        files.attach(s, entity_type=ET, entity_id=shop["cement"], data=fx.jpeg(colour=(99, 98, 97)), name="x.jpg")
        assert len(stored_files(files_folder, shop)) == len(before) + 3
        raise RuntimeError("the rest of the operation failed")
    assert set(stored_files(files_folder, shop)) == before
    with system(shop) as s:
        assert s.execute(text("select count(*) from kernel.attachment where checksum is null")).scalar_one() == 0


def test_removing_a_record_removes_its_files(client, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import files

    entity = shop["paint"]
    put(client, shop, fx.jpeg(colour=(4, 4, 4)), entity=entity)
    with system(shop) as s:
        gone = files.remove_for_entity(s, ET, entity, "product removed")
        assert gone >= 1 and files.list_files(s, ET, entity) == []
        assert files.counts(s, ET, [entity]) == {}


# --------------------------------------------------------------------------- privacy, retention, verify
def test_the_privacy_provider_finds_exports_and_removes_files(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import PersonalRecord

    entity = shop["delivery"]
    f = put(client, shop, fx.jpeg(colour=(60, 61, 62)), entity=entity, caption="Photo of jane.doe@example.com at pickup").json()
    plain = put(client, shop, fx.jpeg(colour=(70, 71, 72)), entity=entity, caption="Tyres").json()
    provider = FileData()
    with system(shop) as s:
        found = provider.find(s, shop["company_id"], Subject(raw="jane.doe@example.com", email="jane.doe@example.com"))
        assert [str(r.record_id) for r in found] == [f["id"]] and found[0].match == "exact"
        loose = provider.find(s, shop["company_id"], Subject(raw="Jane Doe", name="jane"))
        assert f["id"] in {str(r.record_id) for r in loose} and all(r.match == "possible" for r in loose)
        hanging = provider.linked(s, shop["company_id"], [PersonalRecord("crm", "customer", UUID(entity), "A customer", "exact")])
        assert {str(r.record_id) for r in hanging} >= {f["id"], plain["id"]}
        exported = provider.export(s, found[0])
        assert exported["caption"].startswith("Photo of jane") and exported["download_path"].endswith("variant=original")
        assert "bytes" not in exported
        outcome = provider.anonymise(s, found[0], "erasure request")
        assert outcome.status == "anonymised" and outcome.kept
    assert client.get(f"{F}/{f['id']}", headers=shop["owner"]).status_code == 404
    assert client.get(f"{F}/{plain['id']}", headers=shop["owner"]).status_code == 200
    with system(shop) as s:
        assert provider.find(s, shop["company_id"], Subject(raw="jane.doe@example.com", email="jane.doe@example.com")) == []


def test_whoever_handles_a_privacy_request_may_open_the_files_it_found(client, shop) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import sign_in

    f = put(client, shop, fx.jpeg(colour=(80, 81, 82)), entity=shop["cement"]).json()
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=shop["owner"]).json()}
    made = client.post("/api/v1/roles", headers=shop["owner"], json={"name": "Privacy officer", "permissions": ["privacy.manage"]})
    assert made.status_code in (200, 201), made.text
    role_id = made.json()["id"]
    assert role_id not in roles.values()
    user = client.post("/api/v1/users", headers=shop["owner"],
                       json={"full_name": "Pia Privacy", "email": "pia@files-shop.test", "password": "pia-pass-12345"}).json()
    given = client.post(f"/api/v1/users/{user['id']}/roles", headers=shop["owner"],
                        json={"role_id": role_id, "scope": "company", "company_id": str(shop["company_id"]), "branch_id": None})
    assert given.status_code == 201, given.text
    pia = sign_in(client, shop["code"], "pia@files-shop.test", "pia-pass-12345").headers
    assert client.get(f"{F}?entity_type={ET}&entity_id={shop['cement']}", headers=pia).status_code == 403    # no say over the record
    assert client.get(f"{F}/{f['id']}/content?variant=original", headers=pia).status_code == 200          # but may open what a request found
    assert client.post(f"{F}/{f['id']}/delete", headers=pia, json={"reason": "not hers to do"}).status_code == 403
    assert client.patch(f"{F}/{f['id']}", headers=pia, json={"caption": "x"}).status_code == 403


def test_retention_puts_old_files_in_front_of_a_person_and_deletes_nothing(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import privacy

    f = put(client, shop, fx.jpeg(colour=(90, 91, 92)), entity=shop["cement"]).json()
    provider = FileData()
    with system(shop) as s:
        assert provider.retention(s, shop["company_id"])[0].eligible == 0
        s.execute(text("update kernel.attachment set created_at = now() - interval '3 years' where id = :i"), {"i": f["id"]})
    settings(client, shop, retention_files_years=1)
    try:
        with system(shop) as s:
            rule = provider.retention(s, shop["company_id"])[0]
            assert rule.eligible >= 1 and rule.setting == "retention_files_years" and rule.at_end == "review"
            assert privacy.apply_retention(s)["review_items"] >= 1
    finally:
        settings(client, shop, retention_files_years=0)
    assert client.get(f"{F}/{f['id']}", headers=shop["owner"]).status_code == 200


def test_verify_reports_and_fixes_what_does_not_match(client, shop, files_folder) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import files

    check = checks.FilesCheck()
    f = put(client, shop, fx.jpeg(colour=(120, 121, 122)), entity=shop["cement"]).json()
    gone = put(client, shop, fx.jpeg(colour=(130, 131, 132)), entity=shop["cement"]).json()
    with system(shop) as s:
        before = check.run(s)
    assert not [p for p in before if f["id"] in p or gone["id"] in p]

    def blob(file_id: str, variant: str) -> Path:
        return next(p for p in stored_files(files_folder, shop) if p.name == f"{file_id}.{variant}")

    blob(f["id"], "web").unlink()                                                         # a copy went missing
    original = blob(gone["id"], "original")
    original.write_bytes(original.read_bytes()[:-1] + bytes([original.read_bytes()[-1] ^ 1]))   # one damaged byte
    stray = files_folder / str(shop["tenant_id"]) / "ab" / f"{uuid4()}.original"          # bytes no row mentions
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"left behind")
    with system(shop) as s:
        problems = check.run(s)
    text_ = "\n".join(problems)
    assert f"file {f['id']}: the web copy is missing" in text_
    assert f"file {gone['id']}: the original does not match its checksum" in text_
    assert f"stored file {stray.relative_to(files_folder).as_posix()} has no row" in text_
    assert stray.exists()                                                                 # a fresh stray may be an upload in flight
    old = time.time() - 2 * 3600
    os.utime(stray, (old, old))
    with system(shop) as s:
        check.run(s, fix=True)
    assert not stray.exists()
    # a deleted file whose bytes could not be removed
    with system(shop) as s:
        files.delete_file(s, UUID(f["id"]), "cleanup test")
    leftover = files_folder / str(shop["tenant_id"]) / f["id"][:2]
    leftover.mkdir(parents=True, exist_ok=True)
    (leftover / f"{f['id']}.original").write_bytes(b"still here")
    with system(shop) as s:
        assert any("deleted, but" in p for p in check.run(s))
        check.run(s, fix=True)
        assert not any("deleted, but" in p for p in check.run(s))
    with system(shop) as s:
        files.delete_file(s, UUID(gone["id"]), "cleanup test")


def test_a_record_that_vanished_is_reported(client, shop) -> None:  # type: ignore[no-untyped-def]
    ghost = uuid4()
    with system(shop) as s:
        s.execute(text(
            "insert into kernel.attachment (tenant_id, company_id, entity_type, entity_id, kind, content_type, size_bytes, "
            "checksum, storage_key) values (kernel.current_tenant(), :c, :t, :e, 'pdf', 'application/pdf', 0, :h, :k)"),
            {"c": str(shop["company_id"]), "t": ET, "e": str(ghost), "h": "0" * 64,
             "k": f"{shop['tenant_id']}/aa/{uuid4()}.original"})
        problems = checks.FilesCheck().run(s)
        assert any(f"belong to a {ET} ({ghost}) that no longer exists" in p for p in problems)
        s.execute(text("delete from kernel.attachment where entity_id = :e"), {"e": str(ghost)})


def test_the_folder_must_exist_in_production(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import get_settings
    from ziira.kernel.errors import Unavailable
    from ziira.kernel.files import store

    monkeypatch.setenv("ZIIRA_FILES_DIR", "")
    monkeypatch.setenv("ZIIRA_ENV", "production")
    get_settings.cache_clear()
    forget_store()
    try:
        with pytest.raises(Unavailable, match="ZIIRA_FILES_DIR"):
            store.get_store()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        forget_store()


# --------------------------------------------------------------------------- the privacy request flow, size cap, consent
def test_a_data_subject_request_finds_exports_and_erases_files_end_to_end(client, shop) -> None:  # type: ignore[no-untyped-def]
    settings(client, shop, privacy_erasure_needs_approval=False)
    try:
        entity = shop["delivery"]
        f = put(client, shop, fx.jpeg(colour=(140, 141, 142)), entity=entity, caption="Mama Mboga jane.roe@example.com collecting").json()
        req = client.post("/api/v1/privacy/requests", headers=shop["owner"], json={
            "company_id": str(shop["company_id"]), "request_type": "erasure", "subject": "jane.roe@example.com"}).json()
        found = client.post(f"/api/v1/privacy/requests/{req['id']}/search", headers=shop["owner"]).json()
        assert [(x["source"], x["kind"]) for x in found["found"]] == [("kernel.files", "file")]
        exported = client.post(f"/api/v1/privacy/requests/{req['id']}/export", headers=shop["owner"]).json()
        data = exported["records"][0]["data"]
        assert data["caption"].startswith("Mama Mboga") and data["download_path"] == f"/api/v1/files/{f['id']}/content?variant=original"
        done = client.post(f"/api/v1/privacy/requests/{req['id']}/erase", headers=shop["owner"], json={
            "confirm_subject": "jane.roe@example.com", "reason": "She asked us to erase her photos"})
        assert done.status_code == 200 and done.json()["status"] == "completed", done.text
        assert client.get(f"{F}/{f['id']}", headers=shop["owner"]).status_code == 404
        with system(shop) as s:
            row = s.execute(text("select status, caption, delete_reason from kernel.attachment where id = :i"), {"i": f["id"]}).one()
        assert (row.status, row.caption) == ("deleted", "") and "data subject request" in row.delete_reason
    finally:
        settings(client, shop, privacy_erasure_needs_approval=True)


def test_a_body_over_the_hard_cap_is_refused_before_it_is_read(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.config import get_settings

    monkeypatch.setattr(get_settings(), "files_max_upload_bytes", 50_000)
    r = put(client, shop, os.urandom(60_000))
    assert r.status_code in (413, 422)
    assert put(client, shop, fx.jpeg((20, 20))).status_code == 201


def test_nobody_signed_out_can_upload(client, shop) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{F}?entity_type={ET}&entity_id={shop['cement']}", headers={"Content-Type": "image/jpeg"}, content=fx.jpeg())
    assert r.status_code == 401


def test_the_consent_note_is_kept_only_where_the_record_asks_for_it(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.products.hooks import ProductFiles

    plain = put(client, shop, fx.jpeg(colour=(150, 1, 1)), entity=shop["cement"], headers={"X-File-Consent": quote("Jane agreed")})
    assert plain.status_code == 201 and plain.json()["consent_note"] == ""
    monkeypatch.setattr(ProductFiles, "photo_consent", True)
    asked = put(client, shop, fx.jpeg(colour=(151, 1, 1)), entity=shop["cement"], headers={"X-File-Consent": quote("Jane agreed")})
    assert asked.json()["consent_note"] == "Jane agreed"
    cfg = client.get(f"{F}/config?entity_type={ET}&entity_id={shop['cement']}", headers=shop["owner"]).json()
    assert cfg["photo_consent"] is True
    changed = client.patch(f"{F}/{asked.json()['id']}", headers=shop["owner"], json={"consent_note": "Jane agreed, in person"})
    assert changed.json()["consent_note"] == "Jane agreed, in person"
    with system(shop) as s:                                                          # the audit trail never holds the words
        entries = s.execute(text("select changes from kernel.audit_log where entity_type = 'kernel.attachment' "
                                 "and entity_id = :i"), {"i": asked.json()["id"]}).scalars().all()
    assert entries and "Jane" not in str(entries)


def test_ziira_verify_runs_the_files_check_for_a_business(client, shop, files_folder, capsys) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import cli

    assert cli.main(["verify", shop["code"], "--unit", "kernel"]) == 0
    out = capsys.readouterr().out
    assert "kernel: files: ok" in out
    f = put(client, shop, fx.jpeg(colour=(160, 1, 1)), entity=shop["cement"]).json()
    next(p for p in stored_files(files_folder, shop) if p.name == f"{f['id']}.thumb").unlink()
    assert cli.main(["verify", shop["code"], "--unit", "kernel"]) == 1
    assert f"file {f['id']}: the thumbnail is missing from the store" in capsys.readouterr().out
    client.post(f"{F}/{f['id']}/delete", headers=shop["owner"], json={"reason": "cleanup test"})
