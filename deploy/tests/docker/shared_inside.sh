#!/usr/bin/env bash
# Runs inside the systemd container of shared.sh.
set -uo pipefail
fail=0
check() { if "${@:2}"; then printf 'PASS  %s\n' "$1"; else printf 'FAIL  %s\n' "$1"; fail=1; fi; }
export DEBIAN_FRONTEND=noninteractive

echo "== preparing a server that already runs other things"
apt-get update -qq >/dev/null
# Everything the installer would otherwise install is installed first, so its own package step has nothing to add.
apt-get install -y -qq --no-install-recommends nginx postgresql curl rsync xz-utils certbot python3-venv logrotate ca-certificates \
  iproute2 procps sudo >/dev/null 2>&1
for site in blog shop; do
  mkdir -p /var/www/$site && echo "<h1>$site (not ours)</h1>" > /var/www/$site/index.html
  cat > /etc/nginx/sites-available/$site <<CONF
server { listen 80; server_name $site.other.test; root /var/www/$site; }
CONF
  ln -sf /etc/nginx/sites-available/$site /etc/nginx/sites-enabled/$site
done
systemctl enable --now nginx postgresql >/dev/null 2>&1; nginx -t 2>/dev/null && systemctl reload nginx
for _ in $(seq 1 30); do runuser -u postgres -- psql -tAc 'select 1' >/dev/null 2>&1 && break; sleep 1; done
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q <<'SQL'
create role shopuser login password 'their-secret';
create database shopdb owner shopuser;
SQL
runuser -u postgres -- psql -d shopdb -q -c "create table orders(id int primary key, note text); insert into orders values (1,'keep me');"

watched=(/etc/nginx /etc/systemd/system /etc/logrotate.d /usr/local /var/www /etc/letsencrypt /etc/cron.d /etc/fail2ban /opt /var/backups /var/log/nginx)
state() {   # path + content hash (or link target) of everything in the watched folders, minus logs that grow by themselves
  find "${watched[@]}" -xdev \( -type f -o -type l \) 2>/dev/null | grep -v -E '^/var/log/nginx/' | sort | while read -r p; do
    if [ -L "$p" ]; then echo "L $p -> $(readlink "$p")"; else echo "F $p $(md5sum < "$p" | cut -c1-32)"; fi; done
  find "${watched[@]}" -xdev -type d 2>/dev/null | grep -v -E '^/var/log/nginx' | sort | sed 's/^/D /'
}
dbstate() { runuser -u postgres -- psql -tAc "select datname from pg_database order by 1" | tr '\n' ' '
            runuser -u postgres -- psql -tAc "select rolname from pg_roles where rolname !~ '^pg_' order by 1" | tr '\n' ' '
            runuser -u postgres -- pg_dump shopdb | grep -v -E '^(--|SET|SELECT pg_catalog|\\\\)' | md5sum; }
answers() { for s in blog shop; do curl -s -H "Host: $s.other.test" http://127.0.0.1/; done; curl -s -H 'Host: unknown.test' http://127.0.0.1/ | head -3; }
export -f state dbstate answers
state > /tmp/state.before; dbstate > /tmp/db.before; answers > /tmp/answers.before
nginx_pid="$(cat /run/nginx.pid)"; pg_pid="$(head -1 /var/lib/postgresql/*/main/postmaster.pid)"
check "the unrelated sites answer before the install" grep -q "blog (not ours)" /tmp/answers.before

echo "== inspect, then install (self-signed; port 8000 pre-occupied by another app)"
(python3 -m http.server 8000 --bind 127.0.0.1 >/dev/null 2>&1 &) ; sleep 1
bash /src/deploy/install.sh --inspect > /tmp/inspect.log 2>&1
check "inspect lists the other sites" bash -c "grep -q 'blog.other.test' /tmp/inspect.log && grep -q 'shopdb' /tmp/inspect.log && grep -q 'mode: join' /tmp/inspect.log"
check "inspect changed nothing" bash -c "state > /tmp/state.inspect; diff -q /tmp/state.before /tmp/state.inspect >/dev/null"
export ZIIRA_OPERATOR_PASSWORD='shared-test-password'
bash /src/deploy/install.sh --yes --root-domain shared.test --email ops@shared.test --admin-email admin@shared.test --from-dir /src \
  --prebuilt --self-signed --skip-dns-check --agree-tos --registration-mode closed > /tmp/install.log 2>&1; rc=$?
tail -25 /tmp/install.log
check "install exits 0" test "$rc" -eq 0

echo "== nothing of the neighbours changed"
state > /tmp/state.after
check "every pre-existing file and link is byte-for-byte unchanged" bash -c \
  "diff <(grep -E '^(F|L) ' /tmp/state.before) <(grep -E '^(F|L) ' /tmp/state.after | grep -F -f <(grep -E '^(F|L) ' /tmp/state.before)) >/dev/null"
check "the unrelated sites answer exactly as before" bash -c "answers > /tmp/answers.after; diff -q /tmp/answers.before /tmp/answers.after >/dev/null"
check "nginx was reloaded, never restarted (same master process)" test "$(cat /run/nginx.pid)" = "$nginx_pid"
check "PostgreSQL was never restarted (same postmaster)" test "$(head -1 /var/lib/postgresql/*/main/postmaster.pid)" = "$pg_pid"
check "the other app on port 8000 still runs" curl -sf http://127.0.0.1:8000/ -o /dev/null
check "the API took another local port" grep -q -- "--port 8001" /etc/systemd/system/ziira-api.service
check "the other database is intact" bash -c "runuser -u postgres -- psql -d shopdb -tAc 'select note from orders' | grep -q 'keep me'"
check "the other role is intact" bash -c "runuser -u postgres -- psql -tAc \"select 1 from pg_roles where rolname='shopuser'\" | grep -q 1"
check "our own role and databases exist" bash -c "runuser -u postgres -- psql -tAc \"select count(*) from pg_database where datname in ('ziira_master')\" | grep -q 1"
check "the shared nginx.conf is untouched" bash -c "grep -q 'ziira' /etc/nginx/nginx.conf && exit 1 || exit 0"
check "only ziira-* files were added under /etc/nginx" bash -c \
  "diff <(grep -E '^F /etc/nginx' /tmp/state.after | awk '{print \$2}' | grep -v -E '/ziira-' | sort) <(grep -E '^F /etc/nginx' /tmp/state.before | awk '{print \$2}' | sort) >/dev/null"
check "our API is up" bash -c "curl -sf http://127.0.0.1:8001/readyz >/dev/null"
check "our app host answers over TLS (self-signed)" bash -c "curl -sk --resolve app.shared.test:443:127.0.0.1 https://app.shared.test/ | grep -qi '<script'"
check "our admin host redirects to the Super Admin" bash -c "[ \"\$(curl -sk -o /dev/null -w '%{http_code}' --resolve admin.shared.test:443:127.0.0.1 https://admin.shared.test/)\" = 302 ]"
check "the staff API is 404 on the app host" bash -c "[ \"\$(curl -sk -o /dev/null -w '%{http_code}' --resolve app.shared.test:443:127.0.0.1 https://app.shared.test/api/v1/operator/businesses)\" = 404 ]"
check "ziira-doctor runs" bash -c "ziira-doctor >/tmp/doctor.log 2>&1; [ \$? -le 2 ]"
test -f /var/lib/ziira/install-manifest.json && check "the manifest exists" true

echo "== uninstall with --purge-data"
bash /src/deploy/uninstall.sh --yes --purge-data --confirm-purge "delete all data of shared.test" > /tmp/uninstall.log 2>&1; rc=$?
tail -12 /tmp/uninstall.log
check "uninstall exits 0" test "$rc" -eq 0
state > /tmp/state.final; dbstate > /tmp/db.final
check "the file system is back to the original state" bash -c "diff /tmp/state.before /tmp/state.final"
check "databases and roles are back to the original state" diff /tmp/db.before /tmp/db.final
check "the unrelated sites still answer exactly as before" bash -c "answers > /tmp/answers.final; diff -q /tmp/answers.before /tmp/answers.final >/dev/null"
check "nginx is still the same process" test "$(cat /run/nginx.pid)" = "$nginx_pid"
check "no ziira units are left" bash -c "! systemctl list-unit-files 'ziira-*' | grep -q ziira"
check "our directories are gone" bash -c "! ls -d /opt/ziira /etc/ziira /var/lib/ziira /var/log/ziira /var/www/ziira 2>/dev/null | grep -q ."
[ "$fail" -eq 0 ] && echo "ALL PASSED" || echo "SOME CHECKS FAILED"
exit "$fail"
