"""Command-line side of the plugin kit (`ziira plugin ...`)."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from ziira.kernel import plugin_trust
from ziira.kernel.config import get_settings
from ziira.kernel.errors import ZiiraError
from ziira.kernel.plugin_kit import check, pack, scaffold


def run(action: str, a: argparse.Namespace) -> int:
    """Run one `ziira plugin` action; returns the exit code."""
    if action == "new":
        return _new(a)
    if action == "check":
        report = check.check_plugin(Path(a.path), roundtrip=not a.no_db)
        print(report.render())
        return 0 if report.ok else 1
    if action == "test":
        return _test(Path(a.path))
    if action == "pack":
        try:
            archive, archive_sha, digest = pack.pack(Path(a.path), Path(a.out))
        except pack.PackError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(
            f"Packed {archive}\narchive sha256 = {archive_sha}   (give this to whoever installs it: --expect-sha256)\n"
            f"plugin checksum = {digest}   (the reviewer pins this in ZIIRA_ALLOWED_PLUGINS as name={digest})"
        )
        return 0
    if action == "install-archive":
        try:
            folder, digest = pack.install_archive(Path(a.file), expect_sha256=a.expect_sha256, replace=a.replace)
        except pack.PackError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(
            f"Unpacked into {folder}\nNext: review it (docs/plugin-review.md), add {folder.name}={digest} to "
            f"ZIIRA_ALLOWED_PLUGINS, restart, then `ziira install {folder.name}`."
        )
        return 0
    return _list()


def _new(a: argparse.Namespace) -> int:
    countries = [c.strip().upper() for c in a.countries.split(",") if c.strip()]
    try:
        folder = scaffold.new_plugin(a.name, a.category, countries, Path(a.dir) if a.dir else None)
    except ValueError as exc:
        raise ZiiraError(str(exc)) from None
    print(f"Created {folder}")
    if a.dir and str(Path(a.dir).resolve()) not in [
        str(Path(p).resolve()) for p in get_settings().extra_unit_path_list()
    ]:
        print(
            f"Add the folder to your settings so the platform finds it: ZIIRA_EXTRA_UNIT_PATHS={Path(a.dir).resolve()}"
        )
    print(f"Next: ziira plugin check {folder}  then  ziira plugin test {folder}")
    return 0


def _test(folder: Path) -> int:
    """Run the plugin's tests in a separate process (its folder joins the extra plugin path unless built in)."""
    folder = folder.resolve()
    if not (folder / "tests").is_dir():
        print(f"Error: {folder}/tests does not exist", file=sys.stderr)
        return 1
    env = dict(os.environ)
    builtin = (scaffold.ZIIRA_ROOT / "plugins").resolve()
    if folder.parent != builtin:
        env["ZIIRA_EXTRA_UNIT_PATHS"] = ":".join([str(folder.parent), *get_settings().extra_unit_path_list()])
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(folder / "tests"),
        "-q",
        "-p",
        "no:cacheprovider",
        "--import-mode=importlib",
        "--rootdir",
        str(folder),
    ]
    return subprocess.run(command, env=env, check=False).returncode


def _list() -> int:
    from ziira.kernel.registry import discover

    roots = get_settings().extra_unit_path_list()
    if not roots:
        print("No extra plugin folder is set (ZIIRA_EXTRA_UNIT_PATHS).")
        return 0
    found = discover()
    for root in roots:
        for manifest_file in sorted(Path(root).glob("*/manifest.toml")):
            name = manifest_file.parent.name
            m = found.get(name)
            digest = plugin_trust.tree_digest(manifest_file.parent)
            state = f"loaded v{m.version}" if m else f"REFUSED: {plugin_trust.refused.get(name, 'not loaded')}"
            print(f"{name:<24} {state}\n    checksum {digest}")
    return 0
