#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-check}"
case "$MODE" in check|deploy) ;; *) echo "usage: $0 [check|deploy]"; exit 2;; esac

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="/root/mama_deploy_backups/$STAMP"
FRONTEND_WEB="/var/www/mama-miniapp"

die(){ echo "BLOCKED: $*" >&2; exit 1; }
run(){ echo "+ $*" >&2; "$@"; }

cd "$REPO"
git fetch origin main >/dev/null
[[ "$(git branch --show-current)" == "main" ]] || die "deploy checkout must be main"
[[ -z "$(git status --porcelain)" ]] || die "deploy checkout is dirty"
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || die "local main != origin/main"

if git ls-files | grep -Eq '(^|/)(\.env($|\.)|.*\.db($|-)|google_credentials\.json$|.*\.(pem|key)$|node_modules/|dist/|uploads/|.*\.bak|.*\.backup)'; then
  die "forbidden runtime/secret/backup path is tracked"
fi

mismatch=0
same_file(){
  local a="$1" b="$2"
  if [[ ! -f "$b" ]] || ! cmp -s "$a" "$b"; then
    echo "MISMATCH $a -> $b"
    mismatch=$((mismatch+1))
  fi
}
same_file "$REPO/mama_bot.py" "/root/mama_bot.py"
same_file "$REPO/mama_max_bot.py" "/root/mama_max_bot.py"

if ! diff -qr \
  --exclude='*.bak*' --exclude='*.backup*' --exclude='__pycache__' --exclude='*.pyc' \
  "$REPO/miniapp_frontend" "$FRONTEND_WEB" >/tmp/mama_deploy_diff.$$ 2>&1; then
  echo "MISMATCH_TREE miniapp_frontend"
  sed -n '1,40p' /tmp/mama_deploy_diff.$$
  mismatch=$((mismatch+1))
fi
rm -f /tmp/mama_deploy_diff.$$

if [[ "$MODE" == "check" ]]; then
  if (( mismatch == 0 )); then echo "SOURCE_PARITY=PASS"; exit 0; fi
  echo "SOURCE_PARITY=FAIL mismatches=$mismatch"
  exit 1
fi

mkdir -p "$BACKUP_ROOT"
changed_tg=0
changed_max=0
changed_frontend=0

if ! cmp -s "$REPO/mama_bot.py" /root/mama_bot.py; then
  cp -p /root/mama_bot.py "$BACKUP_ROOT/mama_bot.py"
  cp -p "$REPO/mama_bot.py" /root/mama_bot.py
  changed_tg=1
fi
if ! cmp -s "$REPO/mama_max_bot.py" /root/mama_max_bot.py; then
  cp -p /root/mama_max_bot.py "$BACKUP_ROOT/mama_max_bot.py"
  cp -p "$REPO/mama_max_bot.py" /root/mama_max_bot.py
  changed_max=1
fi
if ! diff -qr --exclude='*.bak*' --exclude='*.backup*' --exclude='__pycache__' --exclude='*.pyc' \
  "$REPO/miniapp_frontend" "$FRONTEND_WEB" >/dev/null 2>&1; then
  tar -C /var/www -czf "$BACKUP_ROOT/mama-miniapp-web.tar.gz" mama-miniapp
  rsync -a "$REPO/miniapp_frontend/" "$FRONTEND_WEB/"
  changed_frontend=1
fi

python3 - <<'PY'
from pathlib import Path
for p in (Path('mama_bot.py'), Path('mama_max_bot.py')):
    compile(p.read_text(encoding='utf-8'), str(p), 'exec')
PY
node --check "$REPO/miniapp_frontend/assets/app.js" >/dev/null

if (( changed_tg )); then run systemctl restart mambot.service; fi
if (( changed_max )); then run systemctl restart mama-max.service; fi

run systemctl is-active --quiet mambot.service
run systemctl is-active --quiet mama-max.service
run curl -fsS http://127.0.0.1:8082/health >/dev/null
run curl -fsS http://127.0.0.1:8082/api/miniapp/health >/dev/null
run curl -fsSI https://maminpomoshnik.ru/app/ >/dev/null

echo "DEPLOY=PASS"
echo "changed_tg=$changed_tg changed_max=$changed_max changed_frontend=$changed_frontend"
