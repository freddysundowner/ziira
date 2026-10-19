"""nginx configuration, rendered from data (no template engine, so the output is plain and testable).

Joining an existing nginx ("join" mode): only files named ziira-* are added, nothing existing is edited or deleted, and no
global http{} setting changes:
  conf.d/ziira-common.conf        log format, rate-limit zones and map/upstream, ALL named ziira_* (nothing else global)
  snippets/ziira-*.conf           TLS, proxy headers, per-host security headers, per-server gzip/server_tokens
  sites-available/ziira-*.conf    one file per host (+ symlinks in sites-enabled)

"Behind" mode (another proxy owns ports 80/443): the same files under /etc/ziira/nginx, served by our own nginx process on
127.0.0.1:<port>, plain HTTP, TLS being the other proxy's job.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from installer.config import Config

CIPHERS = ("ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:"
           "ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305")
ACME_ROOT = "/var/www/letsencrypt"
LOG_DIR = "/var/log/ziira/nginx"
REDIRECTS_FILE = "/var/lib/ziira/nginx/site-redirects.conf"
# Content-Security-Policy of the static site: copied from site/public/_headers. connect-src allows https so the floating
# assistant can reach the app host's public API; scripts, styles and images still come only from the site itself.
SITE_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self' https:; form-action 'self' https:; frame-ancestors 'none'; base-uri 'self'; "
            "object-src 'none'")
PERMISSIONS = "camera=(), microphone=(), geolocation=(), payment=(), interest-cohort=()"
UPLOAD_LOCATION = r"^/api/v1/connect(/.*)?/(upload|files/detect)$"
FILES_LOCATION = r"^/api/v1/files$"             # a photo or PDF attached to a record (ZIIRA_FILES_MAX_UPLOAD_BYTES)
OPERATOR_AUTH_PATHS = r"^/api/v1/operator/(sign-in|mfa/verify|password)$"


@dataclass
class NginxOptions:
    version: tuple[int, int, int] = (1, 24, 0)
    certs: dict[str, tuple[str, str, str]] = field(default_factory=dict)    # host -> (fullchain, key, chain)
    https: bool = True              # False: first stage, port 80 only (certificates are being requested)
    hsts: str = "off"               # off | on | include-subdomains (already decided: only true after certs work)
    ocsp: bool = False
    csp_hashes: list[str] = field(default_factory=list)
    catch_all: bool = True
    default_cert: tuple[str, str] | None = None     # for nginx older than 1.19.4 (no ssl_reject_handshake)
    hook_token: str = ""
    public_ip: str = ""
    behind_port: int = 0            # >0: "behind" mode, own nginx on 127.0.0.1:<port>, plain HTTP, no certificates
    base: str = "/etc/nginx"        # where our files go
    sites: str = "sites-available"  # folder (under base) of the per-host files


def paths(o: NginxOptions) -> dict[str, str]:
    """Locations of our files for this mode."""
    return {"common": f"{o.base}/conf.d/ziira-common.conf", "snippets": f"{o.base}/snippets",
            "sites": f"{o.base}/{o.sites}"}


def parse_version(text: str) -> tuple[int, int, int]:
    """'nginx version: nginx/1.24.0 (Ubuntu)' -> (1, 24, 0)."""
    m = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (1, 18, 0)


def _listen_443(o: NginxOptions) -> str:
    if o.behind_port:
        return f"    listen 127.0.0.1:{o.behind_port};\n"
    if o.version >= (1, 25, 1):
        return "    listen 443 ssl;\n    listen [::]:443 ssl;\n    http2 on;\n"
    return "    listen 443 ssl http2;\n    listen [::]:443 ssl http2;\n"


def hsts_value(mode: str) -> str:
    return "max-age=31536000; includeSubDomains" if mode == "include-subdomains" else "max-age=31536000"


# --------------------------------------------------------------------------- shared files
def common_conf(cfg: Config, o: NginxOptions) -> str:
    """The only http-level things we add: all names start with ziira, so they cannot clash with anything already there."""
    return f"""# Managed by the Ziira installer. Edits are overwritten on the next install run.
log_format ziira '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent '
                 '"$http_referer" "$http_user_agent" host=$host rt=$request_time urt=$upstream_response_time rid=$request_id';

# 50 requests a second per address on /api/, and 6 a minute on Super Admin sign-in (the application also counts
# wrong passwords and locks out: this is the outer layer).
limit_req_zone $binary_remote_addr zone=ziira_api:10m rate=50r/s;
limit_req_zone $binary_remote_addr zone=ziira_operator_auth:10m rate=6r/m;
limit_req_zone $binary_remote_addr zone=ziira_hook:1m rate=6r/m;

# Only the server itself may read probes and metrics.
map $remote_addr $ziira_local {{
    default 0;
    127.0.0.1 1;
    ::1 1;
}}

upstream ziira_api {{
    server 127.0.0.1:{cfg.api_port};
    keepalive 16;
}}
"""


GZIP_TYPES = ("text/plain text/css text/xml application/xml application/javascript text/javascript application/json "
              "image/svg+xml application/manifest+json")


def server_snippet() -> str:
    """Settings that would be global elsewhere, applied inside our own servers only."""
    return f"""server_tokens off;
limit_req_status 429;
gzip on;
gzip_vary on;
gzip_comp_level 5;
gzip_min_length 1024;
gzip_proxied any;
gzip_types {GZIP_TYPES};
"""


def tls_snippet(o: NginxOptions) -> str:
    return f"""# Mozilla "intermediate" profile: TLS 1.2 and 1.3, ECDHE with AEAD ciphers only.
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers {CIPHERS};
ssl_prefer_server_ciphers off;
ssl_session_timeout 1d;
ssl_session_cache shared:ZiiraSSL:10m;
ssl_session_tickets off;
"""


def proxy_snippet(timeout: int = 60, behind: bool = False) -> str:
    xff, proto = ("$http_x_forwarded_for", "https") if behind else ("$remote_addr", "$scheme")
    return f"""# Headers for requests handed to the API. X-Forwarded-For is OVERWRITTEN with the connecting address (the API is
# started with ZIIRA_TRUST_FORWARDED_FOR=true and reads the last entry), so a client cannot forge its address.
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For {xff};
proxy_set_header X-Forwarded-Proto {proto};
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Request-ID $request_id;
proxy_connect_timeout 5s;
proxy_send_timeout {timeout}s;
proxy_read_timeout {timeout}s;
proxy_redirect off;
"""


def acme_snippet() -> str:
    return f"""location ^~ /.well-known/acme-challenge/ {{
    root {ACME_ROOT};
    default_type text/plain;
    try_files $uri =404;
}}
"""


def _hsts_line(o: NginxOptions) -> str:
    return f'add_header Strict-Transport-Security "{hsts_value(o.hsts)}" always;\n' if o.hsts != "off" else ""


def site_headers(o: NginxOptions) -> str:
    return (f'add_header X-Content-Type-Options "nosniff" always;\nadd_header X-Frame-Options "DENY" always;\n'
            f'add_header Referrer-Policy "strict-origin-when-cross-origin" always;\n'
            f'add_header Permissions-Policy "{PERMISSIONS}" always;\n'
            f'add_header Cross-Origin-Opener-Policy "same-origin" always;\n'
            f'add_header Content-Security-Policy "{SITE_CSP}" always;\n') + _hsts_line(o)


def app_csp(o: NginxOptions) -> str:
    hashes = "".join(f" 'sha256-{h}'" for h in o.csp_hashes)
    return (f"default-src 'self'; script-src 'self'{hashes}; style-src 'self'; style-src-attr 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'; object-src 'none'")


def app_headers(cfg: Config, o: NginxOptions, *, admin: bool = False) -> str:
    out = ('add_header X-Content-Type-Options "nosniff" always;\nadd_header X-Frame-Options "DENY" always;\n'
           'add_header Referrer-Policy "no-referrer" always;\n'
           'add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()" always;\n'
           'add_header Cross-Origin-Opener-Policy "same-origin" always;\n')
    if cfg.csp != "off":
        name = "Content-Security-Policy-Report-Only" if cfg.csp == "report-only" else "Content-Security-Policy"
        out += f'add_header {name} "{app_csp(o)}" always;\n'
    if admin:
        out += 'add_header X-Robots-Tag "noindex, nofollow, noarchive" always;\n'
    return out + _hsts_line(o)


def admin_allow_snippet(cfg: Config) -> str:
    from installer import util
    cidrs = util.parse_cidrs(cfg.operator_networks)
    if not cidrs:
        return "# ZIIRA_OPERATOR_ALLOWED_NETWORKS is empty: the Super Admin is reachable from any address.\n"
    return "".join(f"allow {c};\n" for c in cidrs) + "deny all;\n"


# --------------------------------------------------------------------------- redirects
SAFE_PATH = re.compile(r"^/[A-Za-z0-9/_.~%-]*$")


def redirects_conf(rows: list[dict[str, str]]) -> str:
    """site/redirects.json rows -> exact-match 301 locations (with and without the trailing slash)."""
    out = ["# Generated from site/redirects.json by the Ziira installer; do not edit."]
    seen: set[str] = set()
    for row in rows:
        src, dst = row.get("from", ""), row.get("to", "")
        if not (SAFE_PATH.match(src) and SAFE_PATH.match(dst)) or src == dst:
            continue                                  # a bad row is skipped, never written into the config
        for variant in ([src, src.rstrip("/")] if src.endswith("/") and src != "/" else [src]):     # ordered: stable output
            if variant in seen:
                continue
            seen.add(variant)
            out.append(f"location = {variant} {{ return 301 {dst}; }}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- server blocks
def _ssl(cfg: Config, o: NginxOptions, host: str) -> str:
    if o.behind_port:
        return ""
    cert, key, chain = o.certs[host]
    block = f"    ssl_certificate {cert};\n    ssl_certificate_key {key};\n    include snippets/ziira-tls.conf;\n"
    if o.ocsp:
        block += (f"    ssl_stapling on;\n    ssl_stapling_verify on;\n    ssl_trusted_certificate {chain};\n"
                  "    resolver 1.1.1.1 9.9.9.9 valid=300s ipv6=off;\n    resolver_timeout 5s;\n")
    return block


def _logs(name: str) -> str:
    return (f"    access_log {LOG_DIR}/{name}.access.log ziira;\n    error_log {LOG_DIR}/{name}.error.log warn;\n"
            "    include snippets/ziira-server.conf;\n")


def _port80(names: list[str], target_host: str, o: NginxOptions, label: str) -> str:
    if o.behind_port:
        return ""
    body = ("    location / { return 301 https://" + target_host + "$request_uri; }\n") if o.https else \
           ('    location / { default_type text/plain; return 503 "This server is being set up. Try again in a few minutes."; }\n')
    return (f"server {{\n    listen 80;\n    listen [::]:80;\n    server_name {' '.join(names)};\n{_logs(label)}"
            f"    include snippets/ziira-acme.conf;\n{body}}}\n")


def _cache(value: str) -> str:
    return f'add_header Cache-Control "{value}" always;'


def site_vhost(cfg: Config, o: NginxOptions) -> str:
    names = [cfg.root_domain] + ([cfg.www_host] if cfg.www else [])
    out = _port80(names, cfg.root_domain, o, "site")
    if not o.https:
        return out
    if cfg.www:
        out += (f"\nserver {{\n{_listen_443(o)}    server_name {cfg.www_host};\n{_ssl(cfg, o, cfg.www_host)}{_logs('site')}"
                f"    return 301 https://{cfg.root_domain}$request_uri;\n}}\n")
    hdr = "include snippets/ziira-headers-site.conf;"
    out += f"""
server {{
{_listen_443(o)}    server_name {cfg.root_domain};
{_ssl(cfg, o, cfg.root_domain)}{_logs('site')}
    root {cfg.web_root}/site/current;
    index index.html;
    error_page 404 /404.html;

    {hdr}

    # 301 map from site/redirects.json (rewritten by the site build; nginx reloads itself when it changes).
    include {REDIRECTS_FILE};

    location = /404.html {{ internal; {hdr} }}
    # Netlify-style files that only mean something to a static host.
    location ~ ^/(_headers|_redirects)$ {{ return 404; }}
    location ~ /\\.(?!well-known) {{ return 404; }}

    location ^~ /_astro/ {{ {_cache('public, max-age=31536000, immutable')} {hdr} try_files $uri =404; }}
    location ^~ /fonts/ {{ {_cache('public, max-age=2592000')} {hdr} try_files $uri =404; }}
    location ^~ /og/ {{ {_cache('public, max-age=86400')} {hdr} try_files $uri =404; }}
    location ^~ /media/ {{ {_cache('public, max-age=86400')} {hdr} try_files $uri =404; }}
    location = /sitemap.xml {{ {_cache('public, max-age=3600')} {hdr} }}

    location / {{
        {_cache('public, max-age=0, must-revalidate')}
        {hdr}
        try_files $uri $uri/ =404;
    }}
}}
"""
    return out


def _api_locations(cfg: Config, *, with_business: bool) -> str:
    """Locations that hand requests to the API."""
    out = ""
    if with_business:
        out += f"""
    # Probes and metrics: the server itself only (404 for everyone else).
    location ~ ^/(healthz|readyz|health|metrics)$ {{
        if ($ziira_local = 0) {{ return 404; }}
        include snippets/ziira-proxy.conf;
        proxy_pass http://ziira_api;
    }}
    # Interactive API docs are off on the internet.
    location ~ ^/(docs|redoc|openapi\\.json)(/|$) {{ return 404; }}

    # Staff routes are not served on this host (the API refuses them here too: ZIIRA_OPERATOR_HOST).
    location ^~ /api/v1/operator {{ return 404; }}

    # Statement and export uploads: a file is the request body (ZIIRA_MAX_UPLOAD_BYTES is 10,500,000).
    location ~ {UPLOAD_LOCATION} {{
        client_max_body_size 11m;
        include snippets/ziira-proxy-long.conf;
        proxy_pass http://ziira_api;
    }}

    # Photos and PDFs attached to records: the file is the request body (ZIIRA_FILES_MAX_UPLOAD_BYTES is 26,500,000).
    location ~ {FILES_LOCATION} {{
        client_max_body_size 27m;
        limit_req zone=ziira_api burst=200 nodelay;
        include snippets/ziira-proxy-long.conf;
        proxy_pass http://ziira_api;
    }}

    # The API: business routes, public plans/site content, payment and webhook callbacks, OAuth callbacks.
    location /api/ {{
        limit_req zone=ziira_api burst=200 nodelay;
        include snippets/ziira-proxy.conf;
        proxy_pass http://ziira_api;
    }}
"""
    return out


def app_vhost(cfg: Config, o: NginxOptions) -> str:
    out = _port80([cfg.app_host], cfg.app_host, o, "app")
    if not o.https:
        return out
    hdr = "include snippets/ziira-headers-app.conf;"
    return out + f"""
server {{
{_listen_443(o)}    server_name {cfg.app_host};
{_ssl(cfg, o, cfg.app_host)}{_logs('app')}
    root {cfg.web_root}/app/current;
    index index.html;
    client_max_body_size 2m;

    {hdr}
{_api_locations(cfg, with_business=True)}
    # The business web app. Staff screens are not served on this host.
    location = /operator {{ return 404; }}
    location ^~ /operator/ {{ return 404; }}

    location ^~ /assets/ {{ {_cache('public, max-age=31536000, immutable')} {hdr} try_files $uri =404; }}
    location = /sw.js {{ {_cache('no-cache')} {hdr} try_files $uri =404; }}
    location = /index.html {{ {_cache('no-cache')} {hdr} }}

    location / {{
        {_cache('no-cache')}
        {hdr}
        try_files $uri /index.html;
    }}
}}
"""


def admin_vhost(cfg: Config, o: NginxOptions) -> str:
    out = _port80([cfg.admin_host], cfg.admin_host, o, "admin")
    if not o.https:
        return out
    hdr = "include snippets/ziira-headers-admin.conf;"
    allow = "include snippets/ziira-admin-allow.conf;"
    hook = ""
    if o.hook_token:
        hook = f"""
    # The Super Admin's "Publish website" calls this (signed with ZIIRA_SITE_BUILD_HOOK_SECRET); it only starts a build.
    # Not network-restricted: the API calls it from this server's own public address. The signature is what protects it.
    location = /_hooks/site-rebuild/{o.hook_token} {{
        limit_req zone=ziira_hook burst=3 nodelay;
        client_max_body_size 16k;
        proxy_pass http://127.0.0.1:{cfg.rebuild_port}/rebuild;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
        proxy_read_timeout 15s;
    }}
"""
    return out + f"""
server {{
{_listen_443(o)}    server_name {cfg.admin_host};
{_ssl(cfg, o, cfg.admin_host)}{_logs('admin')}
    root {cfg.web_root}/app/current;
    index index.html;
    client_max_body_size 2m;

    {hdr}
{hook}
    location = /robots.txt {{ default_type text/plain; return 200 "User-agent: *\\nDisallow: /\\n"; }}

    location = / {{ {allow} return 302 /operator; }}

    # The Super Admin screens (the same web app build; only the staff routes are reachable on this host).
    location ~ ^/operator(/|$) {{
        {allow}
        {_cache('no-cache')}
        {hdr}
        try_files /index.html =404;
    }}
    location ^~ /assets/ {{ {allow} {_cache('public, max-age=31536000, immutable')} {hdr} try_files $uri =404; }}

    # Staff API, public plans/site content, edition list. Everything else is not served on this host.
    location /api/v1/operator {{
        {allow}
        limit_req zone=ziira_api burst=100 nodelay;
        include snippets/ziira-proxy.conf;
        proxy_pass http://ziira_api;
    }}
    location ~ {OPERATOR_AUTH_PATHS} {{
        {allow}
        limit_req zone=ziira_operator_auth burst=5 nodelay;
        include snippets/ziira-proxy.conf;
        proxy_pass http://ziira_api;
    }}
    location ^~ /api/v1/public/ {{
        {allow}
        limit_req zone=ziira_api burst=100 nodelay;
        include snippets/ziira-proxy.conf;
        proxy_pass http://ziira_api;
    }}
    location = /api/v1/editions {{
        {allow}
        limit_req zone=ziira_api burst=100 nodelay;
        include snippets/ziira-proxy.conf;
        proxy_pass http://ziira_api;
    }}

    location / {{ return 404; }}
}}
"""


def default_vhost(o: NginxOptions) -> str:
    """Refuse any request whose Host header is not one of ours (444: close without an answer)."""
    out = ("server {\n    listen 80 default_server;\n    listen [::]:80 default_server;\n    server_name _;\n"
           "    return 444;\n}\n")
    if not o.https:
        return out
    if o.version >= (1, 19, 4):
        tls = "    ssl_reject_handshake on;\n"
    else:
        cert, key = o.default_cert or ("/etc/ziira/tls/default.crt", "/etc/ziira/tls/default.key")
        tls = f"    ssl_certificate {cert};\n    ssl_certificate_key {key};\n    return 444;\n"
    if o.version >= (1, 25, 1):
        listen = "    listen 443 ssl default_server;\n    listen [::]:443 ssl default_server;\n"
    else:        # the http2 option must be the same on every server of an address, or nginx warns
        listen = "    listen 443 ssl http2 default_server;\n    listen [::]:443 ssl http2 default_server;\n"
    return out + f"\nserver {{\n{listen}    server_name _;\n{tls}}}\n"


def standalone_conf(cfg: Config) -> str:
    """Main configuration of OUR OWN nginx process in "behind" mode (the system nginx, if any, is not involved)."""
    tmp = f"{cfg.state_dir}/nginx-tmp"
    return f"""# Managed by the Ziira installer. Our own nginx, listening on 127.0.0.1 only; another proxy fronts it.
user {cfg.service_user};
worker_processes 2;
pid /run/ziira-nginx.pid;
error_log {LOG_DIR}/main.error.log warn;
events {{ worker_connections 1024; }}
http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    access_log off;
    client_body_temp_path {tmp}/body;
    proxy_temp_path {tmp}/proxy;
    fastcgi_temp_path {tmp}/fastcgi;
    uwsgi_temp_path {tmp}/uwsgi;
    scgi_temp_path {tmp}/scgi;
    include conf.d/ziira-common.conf;
    include sites/ziira-*.conf;
}}
"""


def all_files(cfg: Config, o: NginxOptions) -> dict[str, str]:
    """Every nginx file the installer owns, path -> content."""
    p = paths(o)
    snip, sites = p["snippets"], p["sites"]
    files = {
        p["common"]: common_conf(cfg, o),
        f"{snip}/ziira-server.conf": server_snippet(),
        f"{snip}/ziira-proxy.conf": proxy_snippet(60, bool(o.behind_port)),
        f"{snip}/ziira-proxy-long.conf": proxy_snippet(180, bool(o.behind_port)),
        f"{snip}/ziira-headers-site.conf": site_headers(o),
        f"{snip}/ziira-headers-app.conf": app_headers(cfg, o),
        f"{snip}/ziira-headers-admin.conf": app_headers(cfg, o, admin=True),
        f"{snip}/ziira-admin-allow.conf": admin_allow_snippet(cfg),
        f"{sites}/ziira-site.conf": site_vhost(cfg, o),
        f"{sites}/ziira-app.conf": app_vhost(cfg, o),
        f"{sites}/ziira-admin.conf": admin_vhost(cfg, o),
    }
    if o.behind_port:
        files[f"{o.base}/nginx.conf"] = standalone_conf(cfg)
        return files
    files[f"{snip}/ziira-tls.conf"] = tls_snippet(o)
    files[f"{snip}/ziira-acme.conf"] = acme_snippet()
    if o.catch_all:
        files[f"{sites}/ziira-default.conf"] = default_vhost(o)
    return files
