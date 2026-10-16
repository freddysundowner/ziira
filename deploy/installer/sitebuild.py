"""Building the marketing website, and the tiny receiver that starts a build when the Super Admin publishes.

    python3 -m installer.sitebuild build     # one build now (also used by the installer and update.sh)
    python3 -m installer.sitebuild serve     # the receiver: POST /rebuild on 127.0.0.1, signed like the platform's webhooks

Standard library only; runs as the service user, never as root. Settings come from /etc/ziira/site-rebuild.env (or the
file named by ZIIRA_REBUILD_ENV): values for the build (PUBLIC_SITE_URL, ...) and the receiver (port, signing secret).

Signature (docs/platform-admin-content.md): `Ziira-Signature: v1=<hex HMAC-SHA256 of "{timestamp}.{body}">` with the secret,
`Ziira-Timestamp` in unix seconds. A request older or newer than five minutes is refused (replay protection).
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from installer import envfile
from installer.nginxconf import redirects_conf

TOLERANCE_SECONDS = 300
KEEP = 3
MAX_BODY = 16 * 1024


def log(message: str) -> None:
    print(f"[site-rebuild] {message}", flush=True)


def load_env(path: str | None = None) -> dict[str, str]:
    path = path or os.environ.get("ZIIRA_REBUILD_ENV", "/etc/ziira/site-rebuild.env")
    with open(path) as handle:
        return envfile.parse(handle.read())


# --------------------------------------------------------------------------- signature
def expected_signature(secret: str, timestamp: str, body: bytes) -> str:
    return "v1=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, signature: str, body: bytes, now: float | None = None) -> str | None:
    """None when the request is genuine, otherwise the reason it is refused."""
    if not secret:
        return "no signing secret is configured"
    if not timestamp.isdigit():
        return "missing or invalid timestamp"
    if abs((now if now is not None else time.time()) - int(timestamp)) > TOLERANCE_SECONDS:
        return "timestamp outside the allowed window"
    if not hmac.compare_digest(expected_signature(secret, timestamp, body), signature or ""):
        return "bad signature"
    return None


# --------------------------------------------------------------------------- build
def parse_redirects(text: str) -> list[dict[str, str]]:
    """dist/_redirects lines '/from /to 301' -> rows."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("/") and not line.lstrip().startswith("#"):
            rows.append({"from": parts[0], "to": parts[1]})
    return rows


def run(argv: list[str], *, env: dict[str, str], cwd: str, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    if argv[0] in ("npm", "rsync"):
        argv = ["nice", "-n", "10", "ionice", "-c3", *argv]          # a shared server: do not starve the other software
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def build_site(env: dict[str, str]) -> dict[str, object]:
    """Build the site into a new release folder and switch to it. Returns a result record (also saved as last.json)."""
    install_dir, web_root, state = env["ZIIRA_INSTALL_DIR"], env["ZIIRA_WEB_ROOT"], env["ZIIRA_STATE_DIR"]
    work = f"{state}/site-build/work"
    os.makedirs(work, exist_ok=True)
    started = time.time()
    result: dict[str, object] = {"started": int(started), "ok": False, "release": "", "warning": ""}
    lock = open(f"{state}/site-build/lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)                  # builds never overlap, even a manual one and the receiver's
    try:
        node = env.get("ZIIRA_NODE_BIN") or ""
        build_env = {**os.environ, "HOME": state, "CI": "1", "npm_config_cache": f"{state}/.npm",
                     "npm_config_update_notifier": "false", "NODE_ENV": "production",
                     "PATH": (node + ":" if node else "") + os.environ.get("PATH", "/usr/bin:/bin")}
        for key in ("PUBLIC_SITE_URL", "PUBLIC_APP_URL", "PUBLIC_PLATFORM_API_URL", "SITE_STRICT"):
            if env.get(key):
                build_env[key] = env[key]
            else:
                build_env.pop(key, None)
        src = f"{install_dir}/current/site"
        p = run(["rsync", "-a", "--delete", "--exclude", "node_modules", "--exclude", "dist", f"{src}/", f"{work}/"],
                env=build_env, cwd=state)
        if p.returncode:
            raise RuntimeError("copying the site sources failed: " + p.stderr[-400:])
        lock_hash = hashlib.sha256(open(f"{work}/package-lock.json", "rb").read()).hexdigest()
        stamp = f"{work}/node_modules/.ziira-lock-hash"
        if not (os.path.exists(stamp) and open(stamp).read() == lock_hash):
            log("npm ci (dependencies changed)")
            p = run(["npm", "ci", "--no-audit", "--no-fund"], env=build_env, cwd=work)
            if p.returncode:
                raise RuntimeError("npm ci failed: " + (p.stderr or p.stdout)[-600:])
            with open(stamp, "w") as handle:
                handle.write(lock_hash)
        log("npm run build")
        p = run(["npm", "run", "build"], env=build_env, cwd=work)
        output = (p.stdout or "") + (p.stderr or "")
        if p.returncode:
            raise RuntimeError("the site build failed: " + output[-800:])
        if "DO NOT DEPLOY" in output:
            result["warning"] = ("the build says it is not on real published content (nothing published yet, or the API "
                                 "was unreachable): the site shows placeholder text until you publish in the Super Admin")
            log("WARNING: " + str(result["warning"]))
        dist = f"{work}/dist"
        if not os.path.exists(f"{dist}/index.html"):
            raise RuntimeError("the build produced no index.html")
        rel = time.strftime("%Y%m%d%H%M%S", time.gmtime())
        target = f"{web_root}/site/releases/{rel}"
        os.makedirs(f"{web_root}/site/releases", exist_ok=True)
        p = run(["rsync", "-a", "--delete", f"{dist}/", f"{target}/"], env=build_env, cwd=state)
        if p.returncode:
            raise RuntimeError("copying the built site failed: " + p.stderr[-400:])
        link, tmp = f"{web_root}/site/current", f"{web_root}/site/current.new"
        if os.path.lexists(tmp):
            os.remove(tmp)
        os.symlink(target, tmp)
        os.replace(tmp, link)                          # atomic: requests see the old site or the new one, never half
        _prune(f"{web_root}/site/releases", keep=KEEP, live=rel)
        _write_redirects(dist, state)
        result.update(ok=True, release=rel, seconds=round(time.time() - started, 1))
        log(f"published release {rel} in {result['seconds']} s")
    except Exception as error:  # noqa: BLE001 - recorded, and the previous site keeps serving
        result["error"] = str(error)
        log("BUILD FAILED, the previous site keeps serving: " + str(error))
    finally:
        with open(f"{state}/site-build/last.json", "w") as handle:
            json.dump(result, handle)
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return result


def _prune(base: str, keep: int, live: str) -> None:
    import shutil
    names = sorted(n for n in os.listdir(base) if re.match(r"^\d{14}$", n))
    for name in names[:-keep]:
        if name != live:
            shutil.rmtree(f"{base}/{name}", ignore_errors=True)


def _write_redirects(dist: str, state: str) -> None:
    """Write nginx 301 rules from dist/_redirects; the path unit reloads nginx (after `nginx -t`) when the file changes."""
    path = f"{state}/nginx/site-redirects.conf"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        rows = parse_redirects(open(f"{dist}/_redirects").read())
    except FileNotFoundError:
        rows = []
    text = redirects_conf(rows)
    current = open(path).read() if os.path.exists(path) else ""
    if text != current:
        if current:
            with open(path + ".prev", "w") as handle:
                handle.write(current)
        tmp = path + ".new"
        with open(tmp, "w") as handle:
            handle.write(text)
        os.replace(tmp, path)


# --------------------------------------------------------------------------- receiver
class Receiver:
    """Runs builds one at a time; a request that arrives during a build asks for exactly one more afterwards."""

    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.guard = threading.Lock()
        self.running = False
        self.pending = False

    def request(self) -> str:
        with self.guard:
            if self.running:
                self.pending = True
                return "queued behind the running build"
            self.running = True
        threading.Thread(target=self._loop, daemon=True).start()
        return "build started"

    def _loop(self) -> None:
        while True:
            build_site(self.env)
            with self.guard:
                if not self.pending:
                    self.running = False
                    return
                self.pending = False


def make_handler(env: dict[str, str], receiver: Receiver) -> type[BaseHTTPRequestHandler]:
    secret = env.get("ZIIRA_REBUILD_SECRET", "")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ziira-rebuild"
        sys_version = ""

        def log_message(self, fmt: str, *args: object) -> None:
            log(f"{self.address_string()} {fmt % args}")

        def _reply(self, status: int, body: dict[str, object]) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/status":
                try:
                    last = json.load(open(f"{env['ZIIRA_STATE_DIR']}/site-build/last.json"))
                except (OSError, ValueError):
                    last = {}
                self._reply(200, {"running": receiver.running, "last": last})
            else:
                self._reply(405, {"error": "use POST /rebuild"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/rebuild":
                self._reply(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._reply(413, {"error": "too large"})
                return
            body = self.rfile.read(length)
            problem = verify(secret, self.headers.get("Ziira-Timestamp", ""), self.headers.get("Ziira-Signature", ""), body)
            if problem:
                log(f"refused a rebuild request: {problem}")
                self._reply(401, {"error": problem})
                return
            self._reply(202, {"status": receiver.request()})

    return Handler


def serve(env: dict[str, str]) -> None:
    port = int(env["ZIIRA_REBUILD_PORT"])
    receiver = Receiver(env)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(env, receiver))
    log(f"listening on 127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("build", "serve"):
        print(__doc__)
        return 2
    env = load_env()
    if argv[1] == "serve":
        serve(env)
        return 0
    return 0 if build_site(env).get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
