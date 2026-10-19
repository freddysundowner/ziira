"""Photos on jobs: kinds of photo as data, the photos a kind of job needs before a stage (off, warn or block), a photo
counted against the rule, and only shareable photos on the customer's approval page."""

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest

from tests import files_helpers as fx
from tests.jobs_helpers import JOBS, make_jobs_shop, move, new_job
from ziira.kernel.files.store import forget_store

F = "/api/v1/files"


@pytest.fixture(scope="module", autouse=True)
def files_folder(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    from ziira.kernel.config import get_settings

    folder = tmp_path_factory.mktemp("job_files")
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
    return make_jobs_shop(client, registry, "Photo Garage")


def photo(client, shop, job, category="damage", visibility="staff", who="owner", name="front.jpg"):  # type: ignore[no-untyped-def]
    headers = {**shop[who], "Content-Type": "image/jpeg", "X-File-Name": quote(name)}
    r = client.post(f"{F}?entity_type=jobs.job&entity_id={job['id']}&category={category}&visibility={visibility}",
                    headers=headers, content=fx.jpeg())
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_the_kinds_of_photo_are_the_workshops_own_data(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    job = new_job(client, shop, title="Photos")
    config = client.get(f"{F}/config", headers=shop["owner"], params={"entity_type": "jobs.job",
                                                                       "entity_id": job["id"]}).json()
    assert {"intake", "damage", "odometer", "fuel"} <= {c["key"] for c in config["categories"]}      # the usual ones
    made = client.post(f"{JOBS}/photo-categories", headers=shop["owner"], json={"company_id": co, "name": "Paint colour"})
    assert made.status_code == 201 and made.json()["code"] == "paint-colour"
    again = client.get(f"{F}/config", headers=shop["owner"], params={"entity_type": "jobs.job", "entity_id": job["id"]}).json()
    assert [c["key"] for c in again["categories"]] == ["paint-colour"]               # once the business has its own list
    assert client.post(f"{JOBS}/photo-categories", headers=shop["owner"], json={
        "company_id": co, "name": "paint colour"}).status_code == 409
    assert client.post(f"{JOBS}/photo-categories", headers=shop["tech"], json={
        "company_id": co, "name": "Nope"}).status_code == 403
    for name in ("Intake", "Damage", "After"):
        assert client.post(f"{JOBS}/photo-categories", headers=shop["owner"], json={
            "company_id": co, "name": name}).status_code == 201


def test_a_job_type_asks_for_photos_before_a_stage(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    made = client.post(f"{JOBS}/job-types", headers=shop["owner"], json={
        "company_id": co, "name": "Body repair", "required_photos": [
            {"category": "damage", "min": 2, "before": "quoted"}, {"category": "after", "min": 1, "before": "ready"}]})
    assert made.status_code == 201, made.text
    assert made.json()["required_photos"][0] == {"category": "damage", "min": 2, "before": "quoted"}
    bad = client.post(f"{JOBS}/job-types", headers=shop["owner"], json={
        "company_id": co, "name": "Odd", "required_photos": [{"category": "nonsense", "min": 1, "before": "ready"}]})
    assert bad.status_code == 422
    job = new_job(client, shop, title="Dented door", job_type_code="body-repair")
    shop["job"] = job
    assert [(p["category"], p["have"], p["ok"]) for p in job["photos"]] == [("damage", 0, False), ("after", 0, False)]
    assert job["photo_count"] == 0


def test_moving_on_without_the_photos_warns_and_a_business_can_block_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    job = shop["job"]
    r = move(client, shop, job, "diagnosing")
    assert r.status_code == 200
    # warn (the default): the move happens and the timeline says what was missing
    moved = move(client, shop, job, "quoted")
    assert moved.status_code == 200 and any("without the photos" in (e["note"] or "") for e in moved.json()["events"])
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={"required_photos": "block"})
    other = new_job(client, shop, title="Wing", job_type_code="body-repair")
    move(client, shop, other, "diagnosing")
    refused = move(client, shop, other, "quoted")
    assert refused.status_code == 422 and "Damage (0 of 2)" in refused.text
    photo(client, shop, other)
    still = move(client, shop, other, "quoted")
    assert still.status_code == 422 and "Damage (1 of 2)" in still.text
    seen = client.get(f"{JOBS}/jobs/{other['id']}", headers=shop["owner"]).json()
    assert seen["photo_count"] == 1 and seen["photos"][0]["have"] == 1 and seen["photos"][0]["ok"] is False
    photo(client, shop, other, name="side.jpg")
    assert move(client, shop, other, "quoted").status_code == 200
    client.patch(f"{JOBS}/settings", params={"company_id": co}, headers=shop["owner"], json={"required_photos": "off"})
    free = new_job(client, shop, title="Mirror", job_type_code="body-repair")
    move(client, shop, free, "diagnosing")
    assert move(client, shop, free, "quoted").status_code == 200
    shop["photo_job"] = other


def test_only_shareable_photos_reach_the_customers_approval_page(client, shop) -> None:  # type: ignore[no-untyped-def]
    job = shop["photo_job"]
    staff_only = photo(client, shop, job, name="inside.jpg")
    shared = photo(client, shop, job, visibility="shareable", name="outside.jpg")
    client.post(f"{JOBS}/jobs/{job['id']}/labour", headers=shop["owner"], json={"hours": "1"})
    made = client.post(f"{JOBS}/jobs/{job['id']}/estimates", headers=shop["owner"], json={"from_job": True}).json()
    sent = client.post(f"{JOBS}/estimates/{made['id']}/send", headers=shop["owner"], json={}).json()
    token = sent["link_path"].removeprefix("/job-approval/")
    page = client.get(f"{JOBS}/public/job-approval/{token}")
    assert page.status_code == 200, page.text
    shown = page.json()["photos"]
    assert [p["id"] for p in shown] == [shared["id"]] and staff_only["id"] not in [p["id"] for p in shown]
    image = client.get(shown[0]["web_path"])
    assert image.status_code == 200 and image.headers["content-type"].startswith("image/")
    answered = client.post(f"{JOBS}/public/job-approval/{token}", json={"approve": True, "name": "Wanjiku"})
    assert answered.status_code == 200
    assert client.get(shown[0]["web_path"]).status_code in (401, 403, 404, 410)       # the link is used: addresses stop
