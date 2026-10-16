#!/bin/sh
# Reload nginx; if the new redirect list breaks the configuration, put the previous list back first.
set -u
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    exit 0
fi
if [ -f "/var/lib/ziira/nginx/site-redirects.conf.prev" ]; then
    cp "/var/lib/ziira/nginx/site-redirects.conf.prev" "/var/lib/ziira/nginx/site-redirects.conf"
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
        echo "ziira: the new redirect list was rejected by nginx -t; the previous one was restored" >&2
        exit 1
    fi
fi
echo "ziira: nginx -t fails; not reloading" >&2
exit 1
