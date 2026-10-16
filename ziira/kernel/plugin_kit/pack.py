"""`ziira plugin pack` and `ziira plugin install-archive`: a distributable plugin and its safe installation.

An archive (`<name>-<version>.zplugin`, a zip) holds the plugin folder and `ziira-pack.json`, which lists the sha256
of every file and one checksum over all of them (`plugin_trust.tree_digest`). The manifest inside also carries that
checksum. `install-archive` is for the operator at the command line, never a web request: it checks the archive file
against the hash the operator got from the publisher (`--expect-sha256`), checks every file against the pack file,
refuses odd entries (paths that climb out, links, too many or too large files), runs the static checks, and only then
unpacks into the first extra plugin folder (`ZIIRA_EXTRA_UNIT_PATHS`). Installing is not enabling: in production the
plugin still loads only when listed in `ZIIRA_ALLOWED_PLUGINS` after review (docs/plugin-review.md).
"""

import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from ziira.kernel.config import get_settings
from ziira.kernel.manifest import load_manifest
from ziira.kernel.plugin_kit.check import check_plugin
from ziira.kernel.plugin_trust import PACK_FILE, file_digests, plugin_files, tree_digest

MAX_FILES = 2000
MAX_BYTES = 50_000_000
_CHECKSUM_LINE = re.compile(r"^\s*checksum\s*=.*$\n?", re.MULTILINE)


class PackError(Exception):
    """The archive cannot be made or trusted; the message says why."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _with_checksum(manifest_text: str, digest: str) -> str:
    """The manifest with `checksum = "<digest>"` as the first line under [unit] (an old checksum line is replaced)."""
    text = _CHECKSUM_LINE.sub("", manifest_text)
    return re.sub(r"^\[unit\]\s*$", f'[unit]\nchecksum = "{digest}"', text, count=1, flags=re.MULTILINE)


def pack(folder: Path, out_dir: Path) -> tuple[Path, str, str]:
    """Check the plugin and write its archive. Returns the archive, its sha256 and the plugin's checksum."""
    folder = folder.resolve()
    report = check_plugin(folder, roundtrip=False)
    if not report.ok:
        raise PackError("The plugin does not pass `ziira plugin check`; fix that first.\n" + report.render())
    manifest = load_manifest(folder / "manifest.toml", f"ziira_ext.{folder.name}")
    digest = tree_digest(folder)
    digests = file_digests(folder)
    if len(digests) > MAX_FILES:
        raise PackError(f"Too many files ({len(digests)}; at most {MAX_FILES})")
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{manifest.name}-{manifest.version}.zplugin"
    pack_info = {
        "format": 1,
        "name": manifest.name,
        "version": manifest.version,
        "sdk": manifest.sdk,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sha256": digest,
        "files": digests,
    }
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in plugin_files(folder):
            rel = path.relative_to(folder).as_posix()
            content = _with_checksum(path.read_text(), digest).encode() if rel == "manifest.toml" else path.read_bytes()
            z.writestr(
                zipfile.ZipInfo(f"{manifest.name}/{rel}", (2020, 1, 1, 0, 0, 0)),
                content,
                compress_type=zipfile.ZIP_DEFLATED,
            )
        z.writestr(f"{manifest.name}/{PACK_FILE}", json.dumps(pack_info, indent=2, sort_keys=True))
    return archive, sha256_file(archive), digest


def install_archive(archive: Path, *, expect_sha256: str, replace: bool = False) -> tuple[Path, str]:
    """Verify an archive and unpack it into the first extra plugin folder. Returns the folder and the checksum."""
    roots = get_settings().extra_unit_path_list()
    if not roots:
        raise PackError("Set ZIIRA_EXTRA_UNIT_PATHS to the folder third-party plugins live in first")
    if not archive.is_file():
        raise PackError(f"{archive} is not a file")
    if sha256_file(archive) != expect_sha256.strip().lower():
        raise PackError(
            "The archive's sha256 is not the one expected: it was changed or is not the one you were told "
            "to install. Nothing was unpacked."
        )
    with tempfile.TemporaryDirectory() as scratch_name:
        scratch = Path(scratch_name)
        name, digest = _unpack_verified(archive, scratch)
        report = check_plugin(scratch / name, roundtrip=False)
        if not report.ok:
            raise PackError("The plugin does not pass the static checks:\n" + report.render())
        target = Path(roots[0]).resolve() / name
        if target.exists():
            if not replace:
                raise PackError(f"{target} already exists (use --replace to upgrade it)")
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(scratch / name, target)
    return target, digest


def _unpack_verified(archive: Path, scratch: Path) -> tuple[str, str]:
    try:
        z = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        raise PackError("That is not a plugin archive") from None
    with z:
        infos = z.infolist()
        if not infos or len(infos) > MAX_FILES + 1:
            raise PackError("The archive is empty or has too many files")
        if sum(i.file_size for i in infos) > MAX_BYTES:
            raise PackError("The archive unpacks to more than 50 MB")
        top = {PurePosixPath(i.filename).parts[0] for i in infos if i.filename}
        if len(top) != 1:
            raise PackError("The archive must hold exactly one folder")
        name = top.pop()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,30}", name):
            raise PackError(f"'{name}' is not a valid plugin name")
        for i in infos:
            parts = PurePosixPath(i.filename).parts
            mode = i.external_attr >> 16
            if i.filename.startswith("/") or ".." in parts or "\\" in i.filename or (mode and stat.S_ISLNK(mode)):
                raise PackError(f"The archive has an unsafe entry: {i.filename}")
        try:
            info = json.loads(z.read(f"{name}/{PACK_FILE}"))
        except (KeyError, ValueError):
            raise PackError(f"The archive has no readable {PACK_FILE}") from None
        listed = {f"{name}/{rel}": sha for rel, sha in info.get("files", {}).items()}
        present = {i.filename for i in infos if not i.filename.endswith("/")} - {f"{name}/{PACK_FILE}"}
        if present != set(listed):
            raise PackError("The files in the archive are not the files its pack file lists")
        z.extractall(scratch, members=[i for i in infos if not i.filename.endswith("/")])
    folder = scratch / name
    actual = file_digests(folder)
    if actual != info.get("files") or tree_digest(folder) != info.get("sha256"):
        raise PackError("A file's content differs from its recorded checksum: the archive was altered.")
    if info.get("name") != name:
        raise PackError("The pack file names a different plugin than the folder")
    declared = load_manifest(folder / "manifest.toml", f"ziira_ext.{name}")
    if declared.checksum and declared.checksum != info["sha256"]:
        raise PackError("The manifest's checksum is not the archive's checksum")
    return name, str(info["sha256"])
