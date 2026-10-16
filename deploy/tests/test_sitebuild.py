"""The website rebuild receiver: signature check, replay window, one build at a time, redirects."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from installer import sitebuild

SECRET = "s3cret-for-tests"


def sign(body: bytes, ts: int | None = None, secret: str = SECRET) -> dict[str, str]:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"Ziira-Timestamp": str(ts), "Ziira-Signature": f"v1={mac}"}


def test_the_signature_is_the_one_the_platform_makes() -> None:
    """Same recipe as ziira/kernel/site_hook.py `sign`: hex HMAC-SHA256 of '{timestamp}.{body}'."""
    from ziira.kernel.site_hook import sign as platform_sign
    body = b'{"event":"site.published","publish_id":7}'
    assert sitebuild.expected_signature(SECRET, "1700000000", body) == platform_sign(SECRET, "1700000000", body)


def test_verify_accepts_genuine_and_refuses_everything_else() -> None:
    body = b"{}"
    h = sign(body)
    assert sitebuild.verify(SECRET, h["Ziira-Timestamp"], h["Ziira-Signature"], body) is None
    assert sitebuild.verify(SECRET, h["Ziira-Timestamp"], h["Ziira-Signature"], b"{ }") == "bad signature"
    assert sitebuild.verify("other", h["Ziira-Timestamp"], h["Ziira-Signature"], body) == "bad signature"
    assert sitebuild.verify(SECRET, h["Ziira-Timestamp"], "", body) == "bad signature"
    assert "timestamp" in (sitebuild.verify(SECRET, "abc", h["Ziira-Signature"], body) or "")
    old = sign(body, int(time.time()) - 3600)
    assert "window" in (sitebuild.verify(SECRET, old["Ziira-Timestamp"], old["Ziira-Signature"], body) or "")
    future = sign(body, int(time.time()) + 3600)
    assert "window" in (sitebuild.verify(SECRET, future["Ziira-Timestamp"], future["Ziira-Signature"], body) or "")
    assert sitebuild.verify("", h["Ziira-Timestamp"], h["Ziira-Signature"], body) == "no signing secret is configured"


@pytest.fixture
def server(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    builds: list[float] = []
    release = threading.Event()

    def fake_build(env):  # type: ignore[no-untyped-def]
        builds.append(time.time())
        release.wait(2)
        return {"ok": True}

    monkeypatch.setattr(sitebuild, "build_site", fake_build)
    env = {"ZIIRA_REBUILD_SECRET": SECRET, "ZIIRA_STATE_DIR": str(tmp_path)}
    receiver = sitebuild.Receiver(env)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), sitebuild.make_handler(env, receiver))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", builds, release, receiver
    release.set()
    httpd.shutdown()


def post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_unsigned_and_badly_signed_requests_start_nothing(server) -> None:  # type: ignore[no-untyped-def]
    url, builds, release, _ = server
    assert post(url + "/rebuild", b"{}", {})[0] == 401
    assert post(url + "/rebuild", b"{}", {**sign(b"{}"), "Ziira-Signature": "v1=00"})[0] == 401
    assert post(url + "/rebuild", b"{}", sign(b"{}", secret="wrong"))[0] == 401
    assert post(url + "/elsewhere", b"{}", sign(b"{}"))[0] == 404
    time.sleep(0.1)
    assert builds == []


def test_a_signed_request_starts_one_build_and_extra_requests_coalesce(server) -> None:  # type: ignore[no-untyped-def]
    url, builds, release, receiver = server
    body = json.dumps({"event": "site.published", "publish_id": 1}).encode()
    status, reply = post(url + "/rebuild", body, sign(body))
    assert status == 202 and reply["status"] == "build started"
    time.sleep(0.2)
    for _ in range(5):                                   # five more while the first is still running
        status, reply = post(url + "/rebuild", body, sign(body))
        assert status == 202 and "queued" in str(reply["status"])
    release.set()
    deadline = time.time() + 5
    while time.time() < deadline and receiver.running:
        time.sleep(0.05)
    assert len(builds) == 2                              # the first build and exactly one more, not six


def test_oversized_bodies_are_refused(server) -> None:  # type: ignore[no-untyped-def]
    url, builds, *_ = server
    big = b"x" * (sitebuild.MAX_BODY + 1)
    assert post(url + "/rebuild", big, sign(big))[0] == 413


def test_parse_redirects_reads_the_astro_file() -> None:
    text = "# generated\n/sw/bei/ /pricing/ 301\n\n/a /b 301\nbroken\n"
    assert sitebuild.parse_redirects(text) == [{"from": "/sw/bei/", "to": "/pricing/"}, {"from": "/a", "to": "/b"}]


def test_redirects_file_is_written_once_and_the_previous_one_kept(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "_redirects").write_text("/old/ /new/ 301\n")
    sitebuild._write_redirects(str(dist), str(tmp_path))
    path = tmp_path / "nginx" / "site-redirects.conf"
    first = path.read_text()
    assert "location = /old/ { return 301 /new/; }" in first
    mtime = path.stat().st_mtime_ns
    sitebuild._write_redirects(str(dist), str(tmp_path))
    assert path.stat().st_mtime_ns == mtime                      # unchanged content: file untouched, nginx not reloaded
    (dist / "_redirects").write_text("/x/ /y/ 301\n")
    sitebuild._write_redirects(str(dist), str(tmp_path))
    assert (tmp_path / "nginx" / "site-redirects.conf.prev").read_text() == first


def test_prune_keeps_the_newest_and_the_live_release(tmp_path) -> None:  # type: ignore[no-untyped-def]
    for name in ("20260101000000", "20260102000000", "20260103000000", "20260104000000", "20260105000000"):
        (tmp_path / name).mkdir()
    sitebuild._prune(str(tmp_path), keep=2, live="20260101000000")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["20260101000000", "20260104000000", "20260105000000"]


def build_env(tmp_path: Path) -> dict[str, str]:
    return {"ZIIRA_INSTALL_DIR": str(tmp_path / "opt"), "ZIIRA_WEB_ROOT": str(tmp_path / "www"), "ZIIRA_STATE_DIR": str(tmp_path / "state"),
            "PUBLIC_SITE_URL": "https://ziira.io"}


def test_a_failed_build_leaves_the_previous_site_serving(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    env = build_env(tmp_path)
    live = tmp_path / "www" / "site" / "releases" / "20260101000000"
    live.mkdir(parents=True)
    (live / "index.html").write_text("old site")
    (tmp_path / "www" / "site" / "current").symlink_to(live)
    (tmp_path / "state" / "site-build").mkdir(parents=True)
    (tmp_path / "opt" / "current" / "site").mkdir(parents=True)

    def failing(argv, **kw):  # type: ignore[no-untyped-def]
        import subprocess
        code = 1 if argv[0] == "rsync" else 0
        return subprocess.CompletedProcess(argv, code, "", "rsync: boom")

    monkeypatch.setattr(sitebuild, "run", failing)
    result = sitebuild.build_site(env)
    assert result["ok"] is False and "boom" in str(result["error"])
    assert (tmp_path / "www" / "site" / "current").resolve() == live.resolve()
    assert json.loads((tmp_path / "state" / "site-build" / "last.json").read_text())["ok"] is False
