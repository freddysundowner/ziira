"""Rendered nginx configuration: golden files, and rules every host must satisfy."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from installer import config, nginxconf, units
from installer.nginxconf import NginxOptions

GOLDEN = Path(__file__).parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def cfg_for(*extra: str) -> config.Config:
    cfg, _ = config.load(["--root-domain", "ziira.io", "--email", "ops@ziira.io", "--admin-email", "me@ziira.io", *extra], {})
    cfg.resolve_defaults()
    return cfg


def certs(cfg: config.Config) -> dict[str, tuple[str, str, str]]:
    out = {}
    for lineage, hosts in cfg.lineages().items():
        for h in hosts:
            out[h] = (f"/etc/letsencrypt/live/{lineage}/fullchain.pem", f"/etc/letsencrypt/live/{lineage}/privkey.pem",
                      f"/etc/letsencrypt/live/{lineage}/chain.pem")
    return out


def options(cfg: config.Config, **kw) -> NginxOptions:  # type: ignore[no-untyped-def]
    base = dict(version=(1, 24, 0), certs=certs(cfg), https=True, hsts="on", ocsp=False, brotli=False,
                csp_hashes=["eQtQGoyst61TlDOMudw6dpdpY/pD+ZrRP8eLAxmDq78="], catch_all=True, hook_token="TOKEN123")
    base.update(kw)
    return NginxOptions(**base)


def check_golden(name: str, content: str) -> None:
    path = GOLDEN / name
    if UPDATE or not path.exists():
        path.write_text(content)
    assert content == path.read_text(), f"{name} changed; run with UPDATE_GOLDEN=1 if intended"


FILES = ["etc/nginx/conf.d/ziira-common.conf", "etc/nginx/sites-available/ziira-site.conf", "etc/nginx/sites-available/ziira-app.conf",
         "etc/nginx/sites-available/ziira-admin.conf", "etc/nginx/sites-available/ziira-default.conf",
         "etc/nginx/snippets/ziira-headers-app.conf", "etc/nginx/snippets/ziira-headers-site.conf",
         "etc/nginx/snippets/ziira-proxy.conf", "etc/nginx/snippets/ziira-tls.conf"]


@pytest.mark.parametrize("path", FILES)
def test_golden_https_stage(path: str) -> None:
    cfg = cfg_for()
    rendered = nginxconf.all_files(cfg, options(cfg))["/" + path]
    check_golden(path.replace("/", "__"), rendered)


def test_golden_http_only_first_stage() -> None:
    cfg = cfg_for()
    files = nginxconf.all_files(cfg, options(cfg, https=False, certs={}))
    check_golden("stage1__app.conf", files["/etc/nginx/sites-available/ziira-app.conf"])


def test_golden_admin_with_allowed_networks_and_old_nginx() -> None:
    cfg = cfg_for("--operator-networks", "203.0.113.0/24,2001:db8::/32")
    files = nginxconf.all_files(cfg, options(cfg, version=(1, 18, 0), ocsp=True, hsts="include-subdomains"))
    check_golden("admin__restricted_nginx118.conf", files["/etc/nginx/sites-available/ziira-admin.conf"])
    check_golden("snippet__admin_allow.conf", files["/etc/nginx/snippets/ziira-admin-allow.conf"])
    check_golden("snippet__headers_site_hsts_sub.conf", files["/etc/nginx/snippets/ziira-headers-site.conf"])


def test_redirects_conf_golden() -> None:
    rows = [{"from": "/sw/bei/", "to": "/pricing/"}, {"from": "/old", "to": "/new/"}, {"from": "/bad path", "to": "/x/"},
            {"from": "/x/", "to": "/x/"}, {"from": "/sw/bei/", "to": "/pricing/"}]
    text = nginxconf.redirects_conf(rows)
    check_golden("redirects.conf", text)
    assert "bad path" not in text and text.count("= /sw/bei/") == 1


# --------------------------------------------------------------------------- rules
def blocks(conf: str) -> list[str]:
    """Top-level server blocks."""
    return re.findall(r"^server \{.*?^\}", conf, re.S | re.M)


def server_names(conf: str) -> list[str]:
    return [n for b in blocks(conf) for m in re.findall(r"server_name ([^;]+);", b) for n in m.split()]


def test_braces_balance_in_every_file() -> None:
    cfg = cfg_for("--operator-networks", "203.0.113.0/24")
    for stage in (options(cfg), options(cfg, https=False, certs={})):
        for path, text in nginxconf.all_files(cfg, stage).items():
            body = re.sub(r'"[^"]*"', '""', text)
            assert body.count("{") == body.count("}"), path
            for line in body.splitlines():
                s = line.strip()
                if s and not s.startswith("#") and not s.endswith(("{", "}", ";", ",", "'")) and not s.startswith("'"):
                    pytest.fail(f"{path}: line without terminator: {line}")


def test_every_host_redirects_http_to_https_and_serves_the_acme_challenge() -> None:
    cfg = cfg_for()
    files = nginxconf.all_files(cfg, options(cfg))
    for name, host in (("site", "ziira.io"), ("app", "app.ziira.io"), ("admin", "admin.ziira.io")):
        conf = files[f"/etc/nginx/sites-available/ziira-{name}.conf"]
        first = blocks(conf)[0]
        assert "listen 80;" in first and f"return 301 https://{host}$request_uri" in first
        assert "include snippets/ziira-acme.conf" in first
    assert "www.ziira.io" in files["/etc/nginx/sites-available/ziira-site.conf"]
    assert "return 301 https://ziira.io$request_uri" in blocks(files["/etc/nginx/sites-available/ziira-site.conf"])[1]


def test_first_stage_has_no_tls_and_does_not_redirect() -> None:
    cfg = cfg_for()
    conf = nginxconf.all_files(cfg, options(cfg, https=False, certs={}))["/etc/nginx/sites-available/ziira-app.conf"]
    assert "ssl" not in conf and "return 301" not in conf and "return 503" in conf and "acme-challenge" in "".join(
        nginxconf.acme_snippet())


def test_app_host_never_serves_staff_screens_or_routes() -> None:
    cfg = cfg_for()
    app = nginxconf.all_files(cfg, options(cfg))["/etc/nginx/sites-available/ziira-app.conf"]
    assert "location ^~ /api/v1/operator { return 404; }" in app
    assert "location = /operator { return 404; }" in app and "location ^~ /operator/ { return 404; }" in app
    # the operator rule must come before the general /api/ rule and the upload rule
    operator = app.index("/api/v1/operator")
    assert operator < app.index("location /api/") and operator < app.index("(upload|files/detect)")


def test_app_host_blocks_probes_metrics_and_docs_from_outside() -> None:
    cfg = cfg_for()
    app = nginxconf.all_files(cfg, options(cfg))["/etc/nginx/sites-available/ziira-app.conf"]
    assert "(healthz|readyz|health|metrics)" in app and "$ziira_local = 0" in app
    assert "(docs|redoc|openapi" in app
    assert "$ziira_local" in nginxconf.common_conf(cfg, options(cfg)) and "127.0.0.1 1;" in nginxconf.common_conf(cfg, options(cfg))


def test_upload_limit_is_raised_only_for_uploads_and_matches_the_api() -> None:
    cfg = cfg_for()
    app = nginxconf.all_files(cfg, options(cfg))["/etc/nginx/sites-available/ziira-app.conf"]
    assert app.count("client_max_body_size 11m;") == 1 and "client_max_body_size 2m;" in app
    assert "include snippets/ziira-proxy-long.conf;" in app and "proxy_read_timeout 180s;" in nginxconf.proxy_snippet(180)
    assert re.search(nginxconf.UPLOAD_LOCATION, "/api/v1/connect/abc/upload")
    assert re.search(nginxconf.UPLOAD_LOCATION, "/api/v1/connect/files/detect")
    assert not re.search(nginxconf.UPLOAD_LOCATION, "/api/v1/products/upload")
    assert 10_500_000 < 11 * 1024 * 1024 and 2_000_000 < 2 * 1024 * 1024


@given(st.from_regex(r"/api/v1/[a-z/]{0,30}(upload|files/detect|x)?", fullmatch=True))
def test_upload_rule_agrees_with_the_api_for_any_path(path: str) -> None:
    from ziira.kernel.http_middleware import _is_file_upload
    assert bool(re.search(nginxconf.UPLOAD_LOCATION, path)) == _is_file_upload("POST", path)


def test_no_directive_is_set_twice_inside_one_snippet_or_location() -> None:
    cfg = cfg_for()
    for path, text in nginxconf.all_files(cfg, options(cfg)).items():
        for block in re.split(r"(?=\nserver \{)|(?=\n\s*location )", text):
            names = re.findall(r"^\s*(proxy_[a-z_]+|client_max_body_size|limit_req|ssl_[a-z_]+)\s", block, re.M)
            single = [n for n in names if n not in ("proxy_set_header", "limit_req")]
            assert len(single) == len(set(single)), (path, single)


def test_directives_the_distribution_already_sets_are_not_repeated() -> None:
    cfg = cfg_for()
    stock = "http {\n    sendfile on;\n    gzip on;\n    # gzip_vary on;\n    server_tokens off;\n    gzip_types text/css;\n}\n"
    already = nginxconf.directives_in(stock)
    assert {"gzip", "server_tokens", "gzip_types", "sendfile"} <= already and "gzip_vary" not in already
    common = nginxconf.common_conf(cfg, options(cfg, already_set=already))
    assert "\ngzip on;" not in common and "server_tokens" not in common and "gzip_types" not in common
    assert "gzip_vary on;" in common and "gzip_comp_level 5;" in common
    assert "\ngzip on;" in nginxconf.common_conf(cfg, options(cfg))


def test_proxy_headers_overwrite_the_forwarded_for_header() -> None:
    snippet = nginxconf.proxy_snippet()
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in snippet            # never $proxy_add_x_forwarded_for
    for needed in ("Host $host", "X-Forwarded-Proto $scheme", "X-Request-ID $request_id", "proxy_read_timeout 60s"):
        assert needed in snippet


def test_service_worker_and_index_are_never_cached_hashed_assets_forever() -> None:
    cfg = cfg_for()
    app = nginxconf.all_files(cfg, options(cfg))["/etc/nginx/sites-available/ziira-app.conf"]
    assert re.search(r"location = /sw\.js \{ add_header Cache-Control \"no-cache\"", app)
    assert re.search(r"location = /index\.html \{ add_header Cache-Control \"no-cache\"", app)
    assert re.search(r"location \^~ /assets/ \{ add_header Cache-Control \"public, max-age=31536000, immutable\"", app)
    assert "try_files $uri /index.html;" in app


def test_admin_host_serves_only_staff_paths() -> None:
    cfg = cfg_for("--operator-networks", "203.0.113.0/24")
    admin = nginxconf.all_files(cfg, options(cfg))["/etc/nginx/sites-available/ziira-admin.conf"]
    assert "location = / {" in admin and "return 302 /operator;" in admin
    assert "/api/v1/operator" in admin and "/api/v1/public/" in admin and "= /api/v1/editions" in admin
    assert "location / { return 404; }" in admin
    assert "location /api/ " not in admin                                       # no business API on the staff host
    assert "X-Robots-Tag" in nginxconf.app_headers(cfg, options(cfg), admin=True)
    assert "ziira_operator_auth" in admin and "sign-in|mfa/verify|password" in admin
    assert "include snippets/ziira-admin-allow.conf;" in admin
    assert "allow 203.0.113.0/24;\ndeny all;" in nginxconf.admin_allow_snippet(cfg)
    assert "any address" in nginxconf.admin_allow_snippet(cfg_for())


def test_the_rebuild_hook_is_reachable_without_the_network_allowlist_but_only_at_the_secret_path() -> None:
    cfg = cfg_for("--operator-networks", "203.0.113.0/24")
    admin = nginxconf.all_files(cfg, options(cfg))["/etc/nginx/sites-available/ziira-admin.conf"]
    hook = re.search(r"location = /_hooks/site-rebuild/TOKEN123 \{.*?\n    \}", admin, re.S)
    assert hook and "allow" not in hook.group(0) and "proxy_pass http://127.0.0.1:9001/rebuild;" in hook.group(0)
    assert "_hooks" not in nginxconf.all_files(cfg, options(cfg, hook_token=""))["/etc/nginx/sites-available/ziira-admin.conf"]
    app = nginxconf.all_files(cfg, options(cfg))["/etc/nginx/sites-available/ziira-app.conf"]
    assert "_hooks" not in app


def test_tls_profile() -> None:
    tls = nginxconf.tls_snippet(options(cfg_for()))
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in tls and "ssl_session_tickets off;" in tls
    assert "RC4" not in tls and "CBC" not in tls and "DHE-RSA" not in tls.replace("ECDHE-RSA", "")
    cfg = cfg_for()
    with_ocsp = nginxconf.all_files(cfg, options(cfg, ocsp=True))["/etc/nginx/sites-available/ziira-app.conf"]
    assert "ssl_stapling on;" in with_ocsp and "ssl_trusted_certificate /etc/letsencrypt/live/app.ziira.io/chain.pem;" in with_ocsp
    assert "ssl_stapling" not in nginxconf.all_files(cfg, options(cfg, ocsp=False))["/etc/nginx/sites-available/ziira-app.conf"]


def test_hsts_only_when_asked() -> None:
    cfg = cfg_for()
    assert "Strict-Transport-Security" not in nginxconf.site_headers(options(cfg, hsts="off"))
    assert 'max-age=31536000"' in nginxconf.site_headers(options(cfg, hsts="on"))
    assert "includeSubDomains" in nginxconf.site_headers(options(cfg, hsts="include-subdomains"))
    assert "includeSubDomains" not in nginxconf.site_headers(options(cfg, hsts="on"))


def test_csp_modes_and_inline_script_hashes() -> None:
    cfg = cfg_for()
    o = options(cfg)
    assert "Content-Security-Policy-Report-Only" in nginxconf.app_headers(cfg, o)
    enforce = nginxconf.app_headers(cfg_for("--csp", "enforce"), o)
    assert "Content-Security-Policy-Report-Only" not in enforce and "add_header Content-Security-Policy " in enforce
    assert "Content-Security-Policy" not in nginxconf.app_headers(cfg_for("--csp", "off"), o)
    assert "'sha256-eQtQGoyst61TlDOMudw6dpdpY/pD+ZrRP8eLAxmDq78='" in nginxconf.app_csp(o)
    assert "'unsafe-inline'" not in nginxconf.app_csp(o).split("style-src-attr")[0]


def test_default_server_refuses_unknown_hosts_on_old_and_new_nginx() -> None:
    cfg = cfg_for()
    new = nginxconf.default_vhost(options(cfg))
    assert "return 444;" in new and "ssl_reject_handshake on;" in new and "default_server" in new
    old = nginxconf.default_vhost(options(cfg, version=(1, 18, 0), default_cert=("/etc/ziira/tls/d.crt", "/etc/ziira/tls/d.key")))
    assert "ssl_reject_handshake" not in old and "ssl_certificate /etc/ziira/tls/d.crt;" in old
    assert "ziira-default.conf" not in "".join(nginxconf.all_files(cfg, options(cfg, catch_all=False)))


def test_old_and_new_http2_syntax() -> None:
    cfg = cfg_for()
    assert "http2 on;" in nginxconf.app_vhost(cfg, options(cfg, version=(1, 26, 0)))
    assert "listen 443 ssl http2;" in nginxconf.app_vhost(cfg, options(cfg, version=(1, 22, 1)))
    assert nginxconf.parse_version("nginx version: nginx/1.24.0 (Ubuntu)") == (1, 24, 0)


def test_no_server_name_is_claimed_twice_and_logs_are_per_host() -> None:
    cfg = cfg_for()
    files = nginxconf.all_files(cfg, options(cfg))
    seen = []
    for name in ("site", "app", "admin"):
        conf = files[f"/etc/nginx/sites-available/ziira-{name}.conf"]
        assert f"{nginxconf.LOG_DIR}/{name}.access.log ziira;" in conf
        for b in blocks(conf):
            port = b.split("listen ")[1].split(";")[0]
            seen += [(port, n) for m in re.findall(r"server_name ([^;]+);", b) for n in m.split()]
    assert len(seen) == len(set(seen)), seen


def test_site_headers_equal_the_static_hosts_header_file() -> None:
    repo = Path(__file__).resolve().parents[2]
    headers = (repo / "site" / "public" / "_headers").read_text()
    csp = re.search(r"Content-Security-Policy: (.+)", headers)
    assert csp and csp.group(1).strip() == nginxconf.SITE_CSP
    for name in ("X-Content-Type-Options: nosniff", "X-Frame-Options: DENY", "Referrer-Policy: strict-origin-when-cross-origin",
                 "Cross-Origin-Opener-Policy: same-origin"):
        assert name in headers
    assert "camera=(), microphone=(), geolocation=(), payment=(), interest-cohort=()" in headers


def test_site_cache_rules_follow_the_static_host_file() -> None:
    cfg = cfg_for()
    site = nginxconf.all_files(cfg, options(cfg))["/etc/nginx/sites-available/ziira-site.conf"]
    assert "location ^~ /_astro/ { add_header Cache-Control \"public, max-age=31536000, immutable\"" in site
    assert "public, max-age=0, must-revalidate" in site and "(_headers|_redirects)" in site
    assert f"include {nginxconf.REDIRECTS_FILE};" in site


def test_units_golden() -> None:
    cfg = cfg_for()
    check_golden("unit__ziira-api.service", units.api_service(cfg, 3))
    check_golden("unit__ziira-worker.service", units.worker_service(cfg))
    check_golden("unit__ziira-site-rebuild.service", units.rebuild_service(cfg))
    check_golden("unit__ziira-backup.service", units.job_service(cfg, units.JOBS[0]))
    check_golden("unit__ziira-backup.timer", units.job_timer(units.JOBS[0]))
    check_golden("unit__nginx-reload.path", units.nginx_reload_path(cfg))
    check_golden("script__nginx-safe-reload.sh", units.nginx_safe_reload_script(cfg))
    check_golden("logrotate.conf", units.logrotate_conf())


def test_units_are_hardened_and_run_unprivileged() -> None:
    cfg = cfg_for()
    for text in (units.api_service(cfg, 2), units.worker_service(cfg), units.rebuild_service(cfg), units.job_service(cfg, units.JOBS[0])):
        for needed in ("NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true", "PrivateTmp=true", "User=ziira",
                       "CapabilityBoundingSet=", "ReadWritePaths="):
            assert needed in text
    assert "Restart=on-failure" in units.api_service(cfg, 2)
    assert "--workers 2" in units.api_service(cfg, 2) and "--proxy-headers" in units.api_service(cfg, 2)
    assert "127.0.0.1" in units.api_service(cfg, 2) and "0.0.0.0" not in units.api_service(cfg, 2)
    assert "EnvironmentFile=/etc/ziira/site-rebuild.env" in units.rebuild_service(cfg)
    assert "ziira.env" not in units.rebuild_service(cfg)         # the rebuild receiver never sees database credentials


def test_worker_count_follows_cpu_and_memory() -> None:
    assert units.worker_count(1, 1024) == 1 and units.worker_count(8, 16384) == 4
    assert units.worker_count(4, 1536) == 2 and units.worker_count(2, 0) == 1


def test_timers_cover_backup_restore_test_and_verification() -> None:
    names = {j.name for j in units.JOBS}
    assert names == {"backup", "restore-test", "stock-verify", "verify"}
    cfg = cfg_for()
    backup = units.job_service(cfg, units.JOBS[0])
    assert "backup --dir /var/backups/ziira --keep-daily 35 --keep-monthly 12" in backup
    assert "Persistent=true" in units.job_timer(units.JOBS[0])
