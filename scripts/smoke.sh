#!/bin/sh
# Post-deploy smoke check for the Inventory Manager.
#
#   ./scripts/smoke.sh http://192.168.1.10:5001
#
# Read-only: it never creates an account, adds an item, or changes data.
# Exits 0 if the deployment looks healthy, 1 otherwise. Safe to run against a
# live classroom instance between periods.
set -u

BASE="${1:-http://127.0.0.1:5001}"
BASE="${BASE%/}"
fails=0

# curl prints 000 on a connection failure and exits non-zero; stdout is what we
# want, so don't append a fallback on top of it.
code() { curl -s -o /dev/null -m 5 -w '%{http_code}' "$@" 2>/dev/null; }
ok()   { printf '  PASS  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }

expect() { # label url expected-codes...
  label="$1"; shift
  url="$1"; shift
  got=$(code "$url")
  for want in "$@"; do
    if [ "$got" = "$want" ]; then ok "$label ($got)"; return; fi
  done
  bad "$label (got $got, wanted one of: $*)"
}

echo "Inventory Manager smoke check — $BASE"

if [ "$(code "$BASE/")" = "000" ]; then
  bad "cannot reach $BASE at all (connection refused or DNS)"
  echo
  echo "$fails failure(s) — nothing else can be checked"
  exit 1
fi

# "/" is the dashboard (login required) or the first-run redirect to /setup.
expect "app answers"               "$BASE/"          200 302
# These two touch the session. A blank or placeholder INVENTORY_SECRET_KEY used
# to make them 500 while other pages still loaded — the exact failure this check
# exists to catch.
expect "login page reachable"      "$BASE/login"     200 302
expect "setup page reachable"      "$BASE/setup"     200 302
# Auth must actually be enforced on the scan station and the API.
expect "scan station needs a login" "$BASE/scan"     302
expect "badge API needs a login"    "$BASE/api/badge" 302 405 400

# A server error anywhere above is the thing worth alarming on.
for path in / /login /setup /scan; do
  got=$(code "$BASE$path")
  case "$got" in
    5*) bad "$path returned $got — check 'docker compose logs' for the reason" ;;
  esac
done

echo
if [ "$fails" -eq 0 ]; then
  echo "All checks passed."
  exit 0
fi
echo "$fails failure(s) — see docs/RUNBOOK.md for the symptom table."
exit 1
