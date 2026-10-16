#!/usr/bin/env bash
set -uo pipefail
fail=0
check() { if "${@:2}"; then printf 'PASS  %s\n' "$1"; else printf 'FAIL  %s\n' "$1"; fail=1; fi; }
export DEBIAN_FRONTEND=noninteractive
echo "== a focal server with PostgreSQL 12 on 5432 and another service on 5433"
apt-get update -qq >/dev/null
apt-get install -y -qq --no-install-recommends postgresql-12 curl rsync xz-utils certbot logrotate ca-certificates iproute2 procps nginx >/dev/null 2>&1
systemctl enable --now postgresql >/dev/null 2>&1
for _ in $(seq 1 30); do runuser -u postgres -- psql -tAc 'select 1' >/dev/null 2>&1 && break; sleep 1; done
runuser -u postgres -- psql -q -c "create database shopdb; " -c "create role shopuser login password 'x'"
runuser -u postgres -- psql -d shopdb -q -c "create table t(i int); insert into t values (42);"
(python3 -m http.server 5433 --bind 127.0.0.1 >/dev/null 2>&1 &); sleep 1
snap12() { find /etc/postgresql/12 -type f | sort | xargs md5sum; pg_lsclusters --no-header | grep '^12' | awk '{print $1,$2,$3,$4,$5,$6}'; head -1 /var/lib/postgresql/12/main/postmaster.pid
           runuser -u postgres -- psql -tAc "select datname from pg_database order by 1" | tr '\n' ' '; runuser -u postgres -- psql -d shopdb -tAc 'select i from t'; }
snap12 > /tmp/pg12.before
cat /tmp/pg12.before | tail -4

echo "== real installer steps: inspect, python (uv), node, postgres (new cluster), release, env"
export ZIIRA_OPERATOR_PASSWORD='focal-test-password'
bash /src/deploy/install.sh --yes --root-domain focal.test --email ops@focal.test --admin-email a@focal.test --from-dir /src \
  --self-signed --skip-dns-check --agree-tos --registration-mode closed --postgres-new-cluster \
  --only inspect,preflight,packages,python,node,user,postgres,release,env,summary > /tmp/install.log 2>&1; rc=$?
grep -E "PGDG|apt-archive|cluster|PostgreSQL|Python|Node|Stopped|role|database" /tmp/install.log | head -30
tail -5 /tmp/install.log
check "install exits 0" test "$rc" -eq 0

echo "== PostgreSQL 16 side by side"
pg_lsclusters
check "the PGDG archive host was used for focal and said so" grep -q "apt-archive.postgresql.org" /tmp/install.log
check "the signing key fingerprint was verified" grep -q "key fingerprint verified" /tmp/install.log
check "postgresql-16 is installed" bash -c "dpkg -s postgresql-16 | grep -q 'Status: install ok installed'"
check "no 16/main cluster is left (the package's automatic one was dropped)" bash -c "! pg_lsclusters --no-header | grep -q '^16 *main'"
port="$(pg_lsclusters --no-header | awk '$1==16 && $2=="ziira" {print $3}')"
echo "ziira cluster port: $port"
check "16/ziira exists, online, on a port other than 5432/5433" bash -c "[ -n '$port' ] && [ '$port' != 5432 ] && [ '$port' != 5433 ] && pg_lsclusters --no-header | grep -q '^16 *ziira.*online'"
check "its data directory is /var/lib/postgresql/16/ziira" test -d /var/lib/postgresql/16/ziira
check "its systemd unit is postgresql@16-ziira" bash -c "systemctl is-enabled postgresql@16-ziira | grep -q enabled"
listeners="$(ss -ltnH "sport = :$port" | awk '{print $4}')"; echo "listeners: $listeners"
check "it is configured to listen on localhost only" bash -c "runuser -u postgres -- psql -p $port -tAc \"show listen_addresses\" | grep -qx localhost"
check "the 5433 service is untouched" curl -sf http://127.0.0.1:5433/ -o /dev/null
pw="$(grep ZIIRA_MASTER_DATABASE_URL /etc/ziira/ziira.env | sed -E "s#.*://ziira:([^@]*)@.*#\\1#")"
check "the app role logs in over TCP 127.0.0.1 and CREATEDB works" bash -c "PGPASSWORD='$pw' psql -h 127.0.0.1 -p $port -U ziira -d postgres -v ON_ERROR_STOP=1 -c 'create database zprobe' -c 'drop database zprobe' >/dev/null"
check "the app role can create a role (tenant logins)" bash -c "PGPASSWORD='$pw' psql -h 127.0.0.1 -p $port -U ziira -d postgres -v ON_ERROR_STOP=1 -c 'create role zt_probe login' -c 'drop role zt_probe' >/dev/null"
check "ziira_master exists on the NEW cluster only" bash -c "runuser -u postgres -- psql -p $port -tAc \"select count(*) from pg_database where datname='ziira_master'\" | grep -q 1 && ! runuser -u postgres -- psql -p 5432 -tAc \"select datname from pg_database\" | grep -q ziira"
snap12 > /tmp/pg12.after
check "PostgreSQL 12: config files, running state, postmaster, databases and data are unchanged" diff /tmp/pg12.before /tmp/pg12.after

echo "== private Python 3.12 and Node on glibc $(ldd --version | head -1 | awk '{print $NF}')"
check "private Python 3.12 runs" /opt/ziira/python/current/bin/python3 -c "import sys, ssl, sqlite3, venv; assert sys.version_info >= (3, 12)"
check "the release virtualenv imports the application" bash -c "cd /tmp && /opt/ziira/current/venv/bin/python -c 'from ziira.kernel.registry import discover; assert len(discover()) > 5'"
check "system python3 is still 3.8 and unchanged" bash -c "python3 --version | grep -q '3.8' && ! ls /usr/bin/python3.12 2>/dev/null"
check "private Node runs" bash -c "/opt/ziira/tools/node/current/bin/node --version && /opt/ziira/tools/node/current/bin/node -e 'console.log(process.versions.v8)'"
check "the system has no node installed by us" bash -c "! command -v node"

echo "== certbot 0.40 accepts our command line"
certbot --version 2>&1 | head -1
mkdir -p /tmp/w
out="$(certbot certonly --webroot -w /tmp/w --cert-name ziira-focal.invalid --non-interactive --agree-tos -m ops@focal.test --no-eff-email --expand --deploy-hook 'systemctl reload nginx' -d focal.invalid --dry-run 2>&1)"
echo "$out" | tail -4
check "no 'unrecognized arguments' (every flag we use exists in this certbot)" bash -c "! echo \"\$1\" | grep -qi 'unrecognized arguments' " _ "$out"

echo "== uninstall"
bash /src/deploy/uninstall.sh --yes > /tmp/uninstall1.log 2>&1; rc=$?
tail -6 /tmp/uninstall1.log
check "uninstall without --purge-data exits 0" test "$rc" -eq 0
check "...keeps the PostgreSQL 16 cluster running with its data and says so" bash -c "pg_lsclusters --no-header | grep -q '^16 *ziira.*online' && grep -q 'Kept the PostgreSQL cluster' /tmp/uninstall1.log"
bash /src/deploy/uninstall.sh --yes --purge-data --confirm-purge "delete all data of focal.test" > /tmp/uninstall2.log 2>&1; rc=$?
tail -6 /tmp/uninstall2.log
check "uninstall --purge-data exits 0" test "$rc" -eq 0
check "...drops the cluster we created and nothing else" bash -c "! pg_lsclusters --no-header | grep -q '^16' && pg_lsclusters --no-header | grep -q '^12 *main.*online'"
snap12 > /tmp/pg12.final
check "PostgreSQL 12 is still byte-identical and answering after uninstall" diff /tmp/pg12.before /tmp/pg12.final
check "our directories are gone" bash -c "! ls -d /opt/ziira /etc/ziira /var/lib/ziira 2>/dev/null | grep -q ."
[ "$fail" -eq 0 ] && echo "ALL PASSED" || echo "SOME CHECKS FAILED"
exit "$fail"
