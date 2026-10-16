"""The plugin kit: scaffold, static checks (good and deliberately bad plugins), pack and install-archive, trust."""

import contextlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from ziira.kernel import cli, plugin_trust
from ziira.kernel.config import get_settings
from ziira.kernel.plugin_kit import check, pack, scaffold
from ziira.kernel.registry import discover


@pytest.fixture
def ext(tmp_path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    """An empty extra plugin folder, registered with the platform for the length of the test."""
    folder = tmp_path / "ext"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "extra_unit_paths", str(folder))
    return folder


def new(ext: Path, name: str = "shop_notes") -> Path:
    return scaffold.new_plugin(name, "data", ["KE"], ext)


def codes(report: check.Report, level: str = "error") -> set[str]:
    return {f.code for f in report.findings if f.level == level}


def edit(path: Path, old: str, new_text: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new_text, 1))


# --------------------------------------------------------------------------- scaffold
def test_the_scaffold_is_complete_and_passes_every_check(ext, registry) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    names = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    assert {"manifest.toml", "README.md", "hooks.py", "public.py", "migrations/0001_init.up.sql",
            "migrations/0001_init.down.sql", "api/routes.py", "services/create_item.py", "domain/rules.py",
            "repository/items_repo.py", "tests/conftest.py", "tests/test_api.py", "tests/test_domain.py"} <= names
    report = check.check_plugin(folder)                              # includes the migration round trip on a scratch database
    assert report.ok and not report.findings, report.render()
    assert "migration-roundtrip" in report.checked
    manifest = discover()["shop_notes"]                              # and the platform finds it in the extra folder
    assert (manifest.category, manifest.countries, manifest.package) == ("data", ("KE",), "ziira_ext.shop_notes")


def test_scaffold_refuses_bad_input(ext) -> None:  # type: ignore[no-untyped-def]
    new(ext)
    for name, category, countries in (("shop_notes", "data", []), ("Bad Name", "data", []), ("ab", "data", []),
                                      ("fine_name", "nonsense", []), ("fine_name", "data", ["kenya"])):
        with pytest.raises(ValueError):
            scaffold.new_plugin(name, category, countries, ext)


def test_the_cli_scaffolds_and_checks(ext, capsys) -> None:  # type: ignore[no-untyped-def]
    assert cli.main(["plugin", "new", "cli_made", "--category", "tax", "--dir", str(ext)]) == 0
    assert cli.main(["plugin", "check", str(ext / "cli_made"), "--no-db"]) == 0
    assert "RESULT: PASS" in capsys.readouterr().out
    assert cli.main(["plugin", "new", "cli_made", "--category", "tax", "--dir", str(ext)]) == 1      # exists


# --------------------------------------------------------------------------- deliberately bad plugins
def test_a_table_without_rls_or_tenant_id_fails(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    up = folder / "migrations" / "0001_init.up.sql"
    up.write_text(up.read_text().replace("alter table plg_shop_notes.item force row level security;\n", ""))
    report = check.check_plugin(folder, roundtrip=False)
    assert "migration-rls" in codes(report) and "never forces row-level security" in report.render()
    assert "fix: add: alter table" in report.render() and "RESULT: FAIL" in report.render()
    up.write_text(up.read_text().replace("  tenant_id  uuid not null references kernel.tenant(id),\n", ""))
    assert any("no tenant_id" in f.message for f in check.check_plugin(folder, roundtrip=False).errors)


def test_the_round_trip_catches_a_table_that_slips_through_the_text_checks(ext, registry) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    up = folder / "migrations" / "0001_init.up.sql"
    up.write_text(up.read_text() + "\nalter table plg_shop_notes.item no force row level security;\n")
    report = check.check_plugin(folder)
    assert "migration-rls" in codes(report) and "forced row-level security" in report.render()
    (folder / "migrations" / "0001_init.down.sql").write_text("select 1;\n")
    assert "migration-down" in codes(check.check_plugin(folder))


def test_missing_down_migration_and_foreign_keys_to_other_units(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    up = folder / "migrations" / "0001_init.up.sql"
    up.write_text(up.read_text().replace("quantity   numeric(18,4) not null default 0",
                                         "quantity   numeric(18,4) not null default 0,\n  product_id uuid references products.product(id)"))
    report = check.check_plugin(folder, roundtrip=False)
    assert "migration-fk" in codes(report) and "soft reference" in report.render()
    (folder / "migrations" / "0001_init.down.sql").unlink()
    assert "migration-down" in codes(check.check_plugin(folder, roundtrip=False))
    edit(folder / "manifest.toml", "requires = []", 'requires = ["products"]')
    up.write_text(up.read_text().replace("references products.product(id)", "references products.product(id)"))
    assert "migration-fk" not in codes(check.check_plugin(folder, roundtrip=False))              # allowed once required


def test_float_money_is_refused_in_code_and_in_sql(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    edit(folder / "domain" / "rules.py", "def clean_name", "def vat(amount: float) -> float:\n    return amount * 0.16\n\n\ndef clean_name")
    assert "money" in codes(check.check_plugin(folder, roundtrip=False))
    shutil.rmtree(ext / "shop_notes")
    folder = new(ext)
    edit(folder / "migrations" / "0001_init.up.sql", "numeric(18,4)", "double precision")
    assert "money" in codes(check.check_plugin(folder, roundtrip=False))


def test_a_float_that_is_not_money_is_only_a_warning(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    edit(folder / "domain" / "rules.py", "def clean_name", "def wait(timeout: float = 1.5) -> float:\n    return timeout\n\n\ndef clean_name")
    report = check.check_plugin(folder, roundtrip=False)
    assert report.ok and "money" in codes(report, "warning")


def test_imports_outside_the_sdk_are_refused(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    edit(folder / "services" / "create_item.py", "from ..domain import rules",
         "from ziira.kernel.audit import record\nfrom ziira.modules.finance.services.posting import post_entry\n"
         "from ziira.modules.crm.public import something\nfrom ziira_ext.other_plugin.repository import x\n"
         "from ..domain import rules")
    report = check.check_plugin(folder, roundtrip=False)
    messages = " ".join(f.message for f in report.errors if f.code == "import")
    assert "ziira.kernel.audit" in messages and "ziira.modules.finance.services.posting" in messages
    assert "ziira_ext.other_plugin.repository" in messages and "crm.public" not in messages      # public.py is allowed
    assert "import from ziira.sdk" in report.render()


def test_an_unguarded_route_is_refused(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    edit(
        folder / "api" / "routes.py",
        '@router.get("/items/{item_id}", response_model=schemas.ItemOut,\n'
        '            dependencies=[Depends(require_permission("shop_notes.view"))])',
        '@router.get("/items/{item_id}", response_model=schemas.ItemOut)',
    )
    report = check.check_plugin(folder, roundtrip=False)
    assert [f.message for f in report.errors if f.code == "endpoints"] == [
        "endpoint get_item (GET) has no require_permission"]
    edit(folder / "api" / "routes.py", "router = APIRouter()", 'router = APIRouter(dependencies=[Depends(require_permission("shop_notes.view"))])')
    assert "endpoints" not in codes(check.check_plugin(folder, roundtrip=False))              # a guarded router covers all


def test_permissions_events_sql_and_network_rules(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    edit(folder / "services" / "create_item.py", '"shop_notes.manage"', '"shop_notes.admin"')
    report = check.check_plugin(folder, roundtrip=False)
    assert any("shop_notes.admin" in f.message for f in report.errors if f.code == "permissions")
    folder = new(ext, "second_one")
    edit(folder / "public.py", "second_one.item_created", "second_one.item_made")
    assert any("second_one.item_made" in f.message for f in check.check_plugin(folder, roundtrip=False).errors)
    folder = new(ext, "third_one")
    edit(folder / "repository" / "items_repo.py", '"select ', '"select 1 from finance.journal_entry j, products.product p where false union select ')
    edit(folder / "repository" / "items_repo.py", "return session.execute(text(\n        \"insert into plg_third_one.item",
         "session.execute(text(\"update kernel.app_user set status = 'x'\"))\n    return session.execute(text(\n        \"insert into plg_third_one.item")
    report = check.check_plugin(folder, roundtrip=False)
    sql = " ".join(f.message for f in report.errors if f.code == "sql")
    assert "writes a kernel table" in sql
    folder = new(ext, "fourth_one")
    (folder / "services" / "fetch.py").write_text("import httpx\n\nDATA = httpx.get('https://example.com').text\n\n\n"
                                                  "def later() -> str:\n    return httpx.get('https://example.com').text\n")
    report = check.check_plugin(folder, roundtrip=False)
    assert [f.where for f in report.errors if f.code == "network-at-import"] == ["services/fetch.py:3"]
    assert any(f.code == "review" and "network call" in f.message for f in report.findings)   # the one in a function: for the reviewer


def test_other_units_schemas_in_raw_sql_are_refused(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    (folder / "repository" / "peek.py").write_text(
        'SQL = "select * from products.product join pos.sale on true"\nOK = "select 1 from plg_shop_notes.item"\n')
    report = check.check_plugin(folder, roundtrip=False)
    assert {f.message for f in report.errors if f.code == "sql"} == {
        "raw SQL on schema 'products', which is not this plugin's", "raw SQL on schema 'pos', which is not this plugin's"}


def test_a_broken_manifest_and_syntax_errors_are_reported_plainly(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    (folder / "services" / "broken.py").write_text("def oops(:\n")
    assert "syntax" in codes(check.check_plugin(folder, roundtrip=False))
    edit(folder / "manifest.toml", 'category = "data"', 'category = "weird"')
    report = check.check_plugin(folder, roundtrip=False)
    assert codes(report) == {"manifest"} and "category" in report.render()
    (folder / "manifest.toml").unlink()
    assert "no manifest.toml" in check.check_plugin(folder).render()


# --------------------------------------------------------------------------- pack and install
def packed(ext: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    folder = new(ext)
    return pack.pack(folder, tmp_path / "dist")


def test_pack_then_install_verifies_and_unpacks(ext, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    archive, archive_sha, digest = packed(ext, tmp_path)
    assert archive.name == "shop_notes-0.1.0.zplugin" and len(archive_sha) == 64 and len(digest) == 64
    with zipfile.ZipFile(archive) as z:
        info = json.loads(z.read("shop_notes/ziira-pack.json"))
        assert info["sha256"] == digest and "manifest.toml" in info["files"]
        assert f'checksum = "{digest}"' in z.read("shop_notes/manifest.toml").decode()
    target_root = tmp_path / "installed"
    monkeypatch.setattr(get_settings(), "extra_unit_paths", str(target_root))
    folder, installed_digest = pack.install_archive(archive, expect_sha256=archive_sha)
    assert folder == (target_root / "shop_notes").resolve() and installed_digest == digest
    assert plugin_trust.tree_digest(folder) == digest                  # what is on disk is what was packed
    assert check.check_plugin(folder, roundtrip=False).ok
    with pytest.raises(pack.PackError, match="already exists"):
        pack.install_archive(archive, expect_sha256=archive_sha)
    pack.install_archive(archive, expect_sha256=archive_sha, replace=True)


def test_a_wrong_hash_or_tampered_archive_installs_nothing(ext, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    archive, archive_sha, _ = packed(ext, tmp_path)
    target_root = tmp_path / "installed"
    monkeypatch.setattr(get_settings(), "extra_unit_paths", str(target_root))
    with pytest.raises(pack.PackError, match="sha256 is not the one expected"):
        pack.install_archive(archive, expect_sha256="0" * 64)
    # change one file inside the archive and fix nothing else: the pack file's checksums no longer match
    evil = tmp_path / "evil.zplugin"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(evil, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.endswith("domain/rules.py"):
                data += b"\nimport os\nos.system('echo owned')\n"
            dst.writestr(item, data)
    with pytest.raises(pack.PackError, match="altered"):
        pack.install_archive(evil, expect_sha256=pack.sha256_file(evil))        # even with the attacker's own hash
    assert not target_root.exists() or not (target_root / "shop_notes").exists()


def test_unsafe_archives_are_refused(ext, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    archive, _, _ = packed(ext, tmp_path)
    monkeypatch.setattr(get_settings(), "extra_unit_paths", str(tmp_path / "installed"))

    def rebuilt(name: str, extra: dict[str, bytes], drop: str | None = None) -> Path:
        out = tmp_path / name
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(out, "w") as dst:
            for item in src.infolist():
                if item.filename != drop:
                    dst.writestr(item, src.read(item.filename))
            for filename, data in extra.items():
                dst.writestr(filename, data)
        return out

    cases = {"climb": rebuilt("climb.zplugin", {"shop_notes/../../escape.py": b"x"}),
             "absolute": rebuilt("abs.zplugin", {"/etc/escape": b"x"}),
             "second folder": rebuilt("two.zplugin", {"other/x.py": b"x"}),
             "extra file": rebuilt("extra.zplugin", {"shop_notes/extra.py": b"x"}),
             "missing file": rebuilt("missing.zplugin", {}, drop="shop_notes/public.py"),
             "no pack file": rebuilt("nopack.zplugin", {}, drop="shop_notes/ziira-pack.json")}
    for label, path in cases.items():
        with pytest.raises(pack.PackError):
            pack.install_archive(path, expect_sha256=pack.sha256_file(path))
        assert label
    notzip = tmp_path / "notzip.zplugin"
    notzip.write_bytes(b"not a zip")
    with pytest.raises(pack.PackError, match="not a plugin archive"):
        pack.install_archive(notzip, expect_sha256=pack.sha256_file(notzip))
    monkeypatch.setattr(get_settings(), "extra_unit_paths", "")
    with pytest.raises(pack.PackError, match="ZIIRA_EXTRA_UNIT_PATHS"):
        pack.install_archive(archive, expect_sha256=pack.sha256_file(archive))


def test_pack_refuses_a_plugin_that_fails_its_checks(ext, tmp_path) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    edit(folder / "domain" / "rules.py", "def clean_name", "amount: float = 1.0\n\n\ndef clean_name")
    with pytest.raises(pack.PackError, match="does not pass"):
        pack.pack(folder, tmp_path / "dist")


def test_the_cli_packs_and_installs(ext, tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    assert cli.main(["plugin", "pack", str(folder), "--out", str(tmp_path / "dist")]) == 0
    out = capsys.readouterr().out
    archive_sha = next(line.split("= ")[1].split()[0] for line in out.splitlines() if line.startswith("archive sha256"))
    monkeypatch.setattr(get_settings(), "extra_unit_paths", str(tmp_path / "into"))
    archive = str(tmp_path / "dist" / "shop_notes-0.1.0.zplugin")
    assert cli.main(["plugin", "install-archive", archive, "--expect-sha256", "f" * 64]) == 1
    assert cli.main(["plugin", "install-archive", archive, "--expect-sha256", archive_sha]) == 0
    assert "ZIIRA_ALLOWED_PLUGINS" in capsys.readouterr().out


# --------------------------------------------------------------------------- trust
def test_production_loads_only_reviewed_unmodified_plugins(ext, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    assert "shop_notes" in discover()                                            # development: loads
    monkeypatch.setattr(get_settings(), "env", "production")
    assert "shop_notes" not in discover()
    assert "ZIIRA_ALLOWED_PLUGINS" in plugin_trust.refused["shop_notes"]
    digest = plugin_trust.tree_digest(folder)
    monkeypatch.setattr(get_settings(), "allowed_plugins", "shop_notes")         # a name alone, with no checksum anywhere
    assert "shop_notes" not in discover() and "checksum" in plugin_trust.refused["shop_notes"]
    monkeypatch.setattr(get_settings(), "allowed_plugins", f"shop_notes={digest}")
    assert "shop_notes" in discover()                                            # reviewed and pinned
    (folder / "domain" / "rules.py").write_text((folder / "domain" / "rules.py").read_text() + "\n# changed after review\n")
    assert "shop_notes" not in discover() and "reviewed checksum" in plugin_trust.refused["shop_notes"]
    monkeypatch.setattr(get_settings(), "allowed_plugins", "other_plugin=" + digest)
    assert "shop_notes" not in discover()


def test_a_manifest_checksum_that_no_longer_matches_is_refused_even_in_development(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    edit(folder / "manifest.toml", "[unit]\n", f'[unit]\nchecksum = "{"0" * 64}"\n')
    assert "shop_notes" not in discover() and "manifest" in plugin_trust.refused["shop_notes"]


def test_extra_plugins_cannot_shadow_or_pose_as_other_units(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext, "products_copy")
    edit(folder / "manifest.toml", 'name = "products_copy"', 'name = "products"')
    assert discover()["products"].kind == "module" and "products_copy" in plugin_trust.refused
    module = new(ext, "plain_mod")
    edit(module / "manifest.toml", 'kind = "plugin"', 'kind = "module"')
    assert "plain_mod" in plugin_trust.refused or "plain_mod" not in discover()


def test_the_checksum_ignores_caches_and_the_manifest_checksum_line(ext) -> None:  # type: ignore[no-untyped-def]
    folder = new(ext)
    before = plugin_trust.tree_digest(folder)
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "x.pyc").write_bytes(b"junk")
    edit(folder / "manifest.toml", "[unit]\n", f'[unit]\nchecksum = "{before}"\n')
    assert plugin_trust.tree_digest(folder) == before
    (folder / "README.md").write_text("changed")
    assert plugin_trust.tree_digest(folder) != before
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["plugin", "list"]) == 0
