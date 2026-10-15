"""Standalone mode end to end: a business that registers only to have Ziira watch its existing system gets exactly the
units for that, can reach the Command Center and findings, connect a system by uploading a file and see its figures."""

import contextlib
import io
import os
from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text

from tests.connect_helpers import CONNECT
from tests.stock_helpers import system
from ziira.kernel import cli
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session

REGISTER, VERIFY = "/api/v1/register", "/api/v1/register/verify"


def register(client, mode: str = "standalone", name: str = "Watched Traders"):  # type: ignore[no-untyped-def]
    with master_session() as s:
        s.execute(text("delete from master.registration"))
    body = {"business_name": name, "owner_name": "Wanjiru Owner", "email": f"owner-{uuid4().hex[:8]}@watch.test",
            "password": "a-good-password-1", "currency": "kes", "phone_country_code": "254", "country": "ke",
            "timezone": "Africa/Nairobi", "mode": mode}
    asked = client.post(REGISTER, json=body)
    assert asked.status_code == 202, asked.text
    done = client.post(VERIFY, json={"token": asked.json()["dev_token"], "device_id": "dev-1"})
    assert done.status_code == 200, done.text
    out = done.json()
    return out, {"Authorization": f"Bearer {out['access_token']}"}


def enabled_units(tenant_id) -> set[str]:  # type: ignore[no-untyped-def]
    with system({"tenant_id": tenant_id}) as s:
        return {r.unit_name for r in s.execute(text("select unit_name from kernel.tenant_unit where status = 'enabled'"))}


def test_the_default_units_for_a_standalone_business_are_only_what_watching_needs() -> None:
    assert get_settings().standalone_units == "connect,intel,command,imports"
    assert "connect" not in get_settings().registration_units


def test_a_standalone_registration_enables_exactly_the_watching_units(client, registry) -> None:  # type: ignore[no-untyped-def]
    out, headers = register(client)
    units = enabled_units(out["tenant_id"]) - {"kernel"}
    assert units == {"connect", "intel", "command", "imports"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    # the Command Center, findings and the connected systems are reachable; the business units are not there
    assert client.get("/api/v1/command/overview", headers=headers).status_code == 200
    assert client.get("/api/v1/intel/findings", headers=headers).status_code == 200
    assert client.get(f"{CONNECT}/connections", headers=headers).json() == []
    kinds = {k["kind"] for k in client.get(f"{CONNECT}/kinds", headers=headers).json()}
    assert {"csv_sales", "bank_statement", "mobile_money_statement"} <= kinds
    for path in ("/api/v1/pos/tills", "/api/v1/finance/accounts", "/api/v1/crm/customers"):
        assert client.get(path, headers=headers).status_code != 200, path


def test_a_core_registration_is_unchanged_and_a_bad_mode_is_refused(client, registry) -> None:  # type: ignore[no-untyped-def]
    out, headers = register(client, "core", "Core Traders")
    units = enabled_units(out["tenant_id"])
    assert {"pos", "finance", "intel", "command"} <= units and "connect" not in units
    assert client.get("/api/v1/pos/tills", headers=headers).status_code == 200
    bad = client.post(REGISTER, json={"business_name": "Nope Ltd", "owner_name": "A B", "email": "x@y.test",
                                      "password": "a-good-password-1", "currency": "usd", "mode": "other"})
    assert bad.status_code == 422


def test_connect_a_file_and_see_figures_and_coverage_without_any_business_unit(client, registry) -> None:  # type: ignore[no-untyped-def]
    _, headers = register(client, name="Figures Traders")
    company = client.get("/api/v1/companies", headers=headers).json()[0]
    made = client.post(f"{CONNECT}/connections", headers=headers, json={
        "company_id": company["id"], "kind": "csv_sales", "name": "Till export"})
    assert made.status_code == 201, made.text
    day = date.today() - timedelta(days=1)
    data = (f"Receipt,Date,Total,Cashier\nR1,{day.isoformat()},500.00,Ann\nR2,{day.isoformat()},250.50,Ben\n").encode()
    up = client.post(f"{CONNECT}/connections/{made.json()['id']}/upload", headers=headers, content=data,
                     params={"mode": "commit", "filename": "sales.csv"})
    assert up.status_code == 200 and up.json()["new"] == 2, up.text
    coverage = client.get(f"{CONNECT}/coverage", headers=headers, params={"company_id": company["id"]}).json()
    assert coverage["connected"] == {"sales": 1}
    cash = next(a for a in coverage["areas"] if a["area"] == "cash_sales")
    assert 0 < cash["active"] < cash["total"]
    ran = client.post("/api/v1/intel/run", headers=headers, json={"company_id": company["id"]})
    assert ran.status_code == 200 and ran.json()["failed"] == [], ran.text
    overview = client.get("/api/v1/command/overview", headers=headers, params={"company_id": company["id"]})
    assert overview.status_code == 200


def test_create_tenant_in_standalone_mode_and_upload_from_the_command_line(client, registry, tmp_path) -> None:  # type: ignore[no-untyped-def]
    os.environ["ZIIRA_OWNER_PASSWORD"] = "owner-pass-123"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["create-tenant", "Cli Watch", "--code", "cli-watch", "--company", "Cli Watch Ltd", "--branch-code", "HQ",
                         "--branch-name", "Head office", "--currency", "KES", "--phone-country-code", "254",
                         "--owner-name", "Cli Owner", "--owner-email", "owner@cli-watch.test", "--mode", "standalone"]) == 0
    ids = {k.strip(): v.strip() for k, v in (line.split(" = ") for line in out.getvalue().strip().splitlines())}
    tenant_id = UUID(ids["tenant_id"])
    assert enabled_units(tenant_id) - {"kernel"} == {"connect", "intel", "command", "imports"}
    owner = client.post("/api/v1/auth/sign-in", json={"workspace": "cli-watch", "login": "owner@cli-watch.test",
                                                      "password": "owner-pass-123", "device_id": "d"}).json()
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    company = client.get("/api/v1/companies", headers=headers).json()[0]
    assert client.post(f"{CONNECT}/connections", headers=headers, json={
        "company_id": company["id"], "kind": "bank_statement", "name": "Main bank"}).status_code == 201
    file = tmp_path / "bank.csv"
    file.write_text("Date,Narration,Ref,Money in,Money out\n2026-10-01,CASH DEPOSIT,D1,500.00,\n2026-10-02,RENT,T2,,200.00\n")
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        assert cli.main(["connect", "upload", "cli-watch", "Main bank", str(file), "--check"]) == 0
    assert "2 row(s): 2 readable, 0 with problems" in shown.getvalue() and "Nothing was stored" in shown.getvalue()
    with system({"tenant_id": tenant_id}) as s:
        assert s.execute(text("select count(*) from connect.src_payment")).scalar_one() == 0
    stored = io.StringIO()
    with contextlib.redirect_stdout(stored):
        assert cli.main(["connect", "upload", "cli-watch", "Main bank", str(file)]) == 0
    assert "payments: 2 new" in stored.getvalue()
    with contextlib.redirect_stdout(io.StringIO()) as sync_out:
        assert cli.main(["connect", "sync", "cli-watch"]) == 0
    assert "reads uploaded files" not in sync_out.getvalue()
