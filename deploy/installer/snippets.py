"""Ready-to-adopt configuration for the proxy that already owns ports 80/443 ("behind" mode).

Our own nginx listens on 127.0.0.1:<port> and serves all three hosts by their Host header. The other proxy only has to
terminate TLS for the three names and forward everything to that port, keeping the Host header and adding the client address
to X-Forwarded-For. Nothing here is installed: copy what you need.
"""
from __future__ import annotations

from installer.config import Config
from installer.context import Ctx


def render(cfg: Config) -> dict[str, str]:
    hosts = cfg.hosts()
    port = cfg.ports
    names = " ".join(hosts)
    cert = "/etc/letsencrypt/live/<your-certificate>"
    files = {
        "README.txt": f"""Ziira behind your existing proxy
=================================
Ziira's own nginx listens on 127.0.0.1:{port} (plain HTTP) and serves these names by Host header:
  {chr(10).join('  ' + h for h in hosts)}
Your proxy must: terminate TLS for those names (its own certificates), forward every request to http://127.0.0.1:{port}
UNCHANGED (keep the Host header), set X-Forwarded-For to include the client address (the LAST entry must be the client as
your proxy saw it), and allow request bodies up to 11 MB. Do not cache. Timeouts of at least 60 s (180 s for statement uploads).
Static files: {cfg.web_root}/site/current (landing page), {cfg.web_root}/app/current (web app). API: 127.0.0.1:{cfg.api_port}.
The files in this folder are examples for common proxies. None is installed for you.
""",
        "nginx-frontend.conf": f"""# Another nginx in front of Ziira's own nginx. Add a server block per name in its own TLS setup.
upstream ziira_behind {{ server 127.0.0.1:{port}; keepalive 8; }}
server {{
    listen 443 ssl;
    server_name {names};
    ssl_certificate     {cert}/fullchain.pem;
    ssl_certificate_key {cert}/privkey.pem;
    client_max_body_size 11m;
    location / {{
        proxy_pass http://ziira_behind;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 180s;
    }}
}}
""",
        "Caddyfile": f"""{", ".join(hosts)} {{
    request_body {{
        max_size 11MB
    }}
    reverse_proxy 127.0.0.1:{port} {{
        transport http {{
            response_header_timeout 180s
        }}
    }}
}}
""",
        "apache-ziira.conf": f"""# a2enmod proxy proxy_http headers ssl
<VirtualHost *:443>
    ServerName {hosts[0]}
{chr(10).join('    ServerAlias ' + h for h in hosts[1:])}
    SSLEngine on
    SSLCertificateFile {cert}/fullchain.pem
    SSLCertificateKeyFile {cert}/privkey.pem
    ProxyPreserveHost On
    LimitRequestBody 11534336
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass / http://127.0.0.1:{port}/ timeout=180
    ProxyPassReverse / http://127.0.0.1:{port}/
</VirtualHost>
""",
        "haproxy-ziira.cfg": f"""# Add to your HAProxy configuration (TLS bind/certificates are yours).
frontend https_in
    acl is_ziira hdr(host) -i {names}
    use_backend ziira if is_ziira
backend ziira
    option forwardfor
    http-request set-header X-Forwarded-Proto https
    timeout server 180s
    server ziira 127.0.0.1:{port}
""",
        "traefik-ziira.yml": f"""# Traefik dynamic configuration (file provider)
http:
  routers:
    ziira:
      rule: "{' || '.join(f'Host(`{h}`)' for h in hosts)}"
      service: ziira
      tls: {{}}
  services:
    ziira:
      loadBalancer:
        passHostHeader: true
        servers:
          - url: "http://127.0.0.1:{port}"
""",
    }
    return files


def write(ctx: Ctx) -> None:
    cfg = ctx.cfg
    target = cfg.snippet_dir or f"{cfg.install_dir}/proxy-snippets"
    changed = False
    for name, text in render(cfg).items():
        changed |= ctx.sys.write_text(f"{target}/{name}", text)
    if changed:
        ctx.ui.ok(f"proxy snippets for nginx, Caddy, Apache, HAProxy and Traefik written to {target}")
    else:
        ctx.ui.already(f"proxy snippets in {target}")
