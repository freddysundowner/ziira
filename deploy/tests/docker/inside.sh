#!/usr/bin/env bash
# Runs inside the test container (the repository is mounted read-only at /src).
set -uo pipefail
fail=0
check() { if "${@:2}"; then printf 'PASS  %s\n' "$1"; else printf 'FAIL  %s\n' "$1"; fail=1; fi; }

cd /src/deploy
export ZIIRA_OPERATOR_PASSWORD='container-test-password'
ARGS=(--yes --root-domain example.test --email ops@example.test --admin-email admin@example.test --from-dir /src
      --no-services --skip-dns-check --staging --self-signed --agree-tos --registration-mode closed)

echo "== 1. dry run (changes nothing)"
before="$(find /etc /opt /var/www -xdev -type f 2>/dev/null | sort | md5sum)"
python3 -m installer "${ARGS[@]}" --dry-run --no-services > /tmp/dry.log 2>&1; rc=$?
tail -5 /tmp/dry.log
check "dry run exits 0" test "$rc" -eq 0
after="$(find /etc /opt /var/www -xdev -type f 2>/dev/null | sort | md5sum)"
check "dry run changed no file" test "$before" = "$after"
check "dry run printed a plan" grep -q "would" /tmp/dry.log

echo "== 2. config-only install"
python3 -m installer "${ARGS[@]}" > /tmp/install.log 2>&1; rc=$?
tail -15 /tmp/install.log
check "installer exits 0" test "$rc" -eq 0
check "nginx -t accepts the rendered configuration" nginx -t
check "env file is 0640 root:ziira" test "$(stat -c '%a %U:%G' /etc/ziira/ziira.env)" = "640 root:ziira"
check "check_env.py reports no ERROR" bash -c "! python3 /src/scripts/check_env.py /etc/ziira/ziira.env | grep -q '^ERROR'"
check "three sites are enabled" test "$(ls /etc/nginx/sites-enabled | grep -c '^ziira-')" -ge 3
check "the staff host has the rebuild hook and the app host does not" bash -c \
  "grep -q '_hooks/site-rebuild' /etc/nginx/sites-available/ziira-admin.conf && ! grep -q '_hooks' /etc/nginx/sites-available/ziira-app.conf"

echo "== 3. re-run changes nothing"
snapshot() { find /etc/nginx /etc/ziira /etc/systemd -type f -not -name 'install-summary.txt' -not -name '*.ziira-new' -print0 | sort -z | xargs -0 md5sum; }
snapshot > /tmp/snap1
cp /etc/ziira/install.json /tmp/install1.json
sum1="$(md5sum < /tmp/snap1)"
python3 -m installer "${ARGS[@]}" > /tmp/rerun.log 2>&1; rc=$?
check "second run exits 0" test "$rc" -eq 0
snapshot > /tmp/snap2
sum2="$(md5sum < /tmp/snap2)"
diff /tmp/snap1 /tmp/snap2 | head
diff /tmp/install1.json /etc/ziira/install.json | head
check "second run changed no configuration file" test "$sum1" = "$sum2"
check "nginx -t still passes" nginx -t

echo "== 4. served for real: start nginx and fetch each host (self-signed, so -k)"
mkdir -p /var/www/ziira/app/releases/t && echo '<html><script>var a=1</script><body>app</body></html>' > /var/www/ziira/app/releases/t/index.html
ln -sfn /var/www/ziira/app/releases/t /var/www/ziira/app/current
echo '<html><body>site</body></html>' > /var/www/ziira/site/releases/initial/index.html 2>/dev/null || true
nginx
sleep 1
body() { curl -sk --resolve "$1:443:127.0.0.1" "https://$1$2"; }
code() { curl -sk -o /dev/null -w '%{http_code}' --resolve "$1:443:127.0.0.1" "https://$1$2"; }
export -f body code
check "http redirects to https" test "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: app.example.test' http://127.0.0.1/)" = "301"
check "unknown Host header gets no answer" bash -c "! curl -s -m 3 -o /dev/null -H 'Host: evil.test' http://127.0.0.1/"
check "app host serves the web app" bash -c "body app.example.test / | grep -q app"
check "app host: staff screen is 404" test "$(code app.example.test /operator)" = "404"
check "app host: staff API is 404" test "$(code app.example.test /api/v1/operator/sign-in)" = "404"
check "app host: interactive API docs are 404" test "$(code app.example.test /docs)" = "404"
check "admin host: / redirects to /operator" test "$(code admin.example.test /)" = "302"
check "admin host: business API is 404" test "$(code admin.example.test /api/v1/pos/sales)" = "404"
check "admin host: robots disallow" bash -c "body admin.example.test /robots.txt | grep -q Disallow"
nginx -s quit
[ "$fail" -eq 0 ] && echo "ALL PASSED" || echo "SOME CHECKS FAILED"
exit "$fail"
