#!/bin/zsh
set -euo pipefail

ROOT="/Users/kuihe/Documents/Art"
LOG_FILE="$ROOT/.claude/sync-after-round.log"
LOCK_DIR="$ROOT/.claude/sync-after-round.lock"
REMOTE_URL="https://github.com/Daniel622/Art.git"
REMOTE_HOST="root@95.181.191.155"
REMOTE_DIR="/opt/obscura-studio"
SERVICE_NAME="obscura-studio"
HEALTH_URL="https://art.cba.pp.ua/api/config"
APP_JS_URL="https://art.cba.pp.ua/app.js"

mkdir -p "$ROOT/.claude/hooks"
mkdir -p "$ROOT/.claude"

exec >>"$LOG_FILE" 2>&1
printf '\n[%s] sync hook start\n' "$(date '+%Y-%m-%d %H:%M:%S')"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  printf 'sync already running, skip\n'
  exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

cd "$ROOT"

branch="$(git branch --show-current)"
if [[ "$branch" != "main" ]]; then
  printf 'skip: branch is %s, not main\n' "$branch"
  exit 0
fi

origin_url="$(git remote get-url origin)"
if [[ "$origin_url" != "$REMOTE_URL" ]]; then
  printf 'abort: unexpected origin %s\n' "$origin_url"
  exit 1
fi

for state_path in .git/MERGE_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD .git/rebase-merge .git/rebase-apply; do
  if [[ -e "$state_path" ]]; then
    printf 'abort: git state in progress (%s)\n' "$state_path"
    exit 1
  fi
done

if ! gh auth status >/dev/null 2>&1; then
  printf 'abort: gh auth status failed\n'
  exit 1
fi

if ! ssh -o BatchMode=yes "$REMOTE_HOST" 'true' >/dev/null 2>&1; then
  printf 'abort: ssh connectivity check failed\n'
  exit 1
fi

printf 'running tests\n'
make test

printf 'running secret scan\n'
if git ls-files --others --modified --exclude-standard | grep -E '(^|/)(\.env|\.env\.|.*\.pem$|id_rsa$|id_ed25519$|.*secret.*|.*token.*)' >/dev/null; then
  printf 'abort: suspicious file names detected among changed/untracked files\n'
  exit 1
fi
if git diff -- . ':(exclude).claude/settings.local.json' | grep -E 'ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ANTHROPIC_API_KEY|sk-[A-Za-z0-9]+' >/dev/null; then
  printf 'abort: secret-like content detected in diff\n'
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  printf 'staging safe files\n'
  git add server.py static tests README.md Makefile deploy docs .gitignore .claude/hooks/sync-after-round.sh
else
  printf 'no working tree changes, skip\n'
  exit 0
fi

if git diff --cached --quiet; then
  printf 'no safe staged changes after filtering, skip\n'
  exit 0
fi

commit_message="$(cat <<'EOF'
Auto-sync completed round of changes.
EOF
)"

printf 'creating commit\n'
git commit -m "$commit_message"

printf 'pulling latest main with ff-only\n'
git pull --ff-only origin main

printf 'pushing to GitHub\n'
git push origin HEAD:main

printf 'deploying to VPS\n'
tar --exclude='.git' \
  --exclude='.claude' \
  --exclude='data' \
  --exclude='__pycache__' \
  --exclude='friend-image-gen' \
  --exclude='pixelforge-source-20260527-083452.tar.gz' \
  --exclude='*.tar.gz' \
  --exclude='.env' \
  --exclude='.env.*' \
  -czf - . \
| ssh -o BatchMode=yes "$REMOTE_HOST" "tar -xzf - -C '$REMOTE_DIR' && systemctl restart '$SERVICE_NAME' && sleep 1 && systemctl is-active '$SERVICE_NAME'"

printf 'running health checks\n'
curl -fsS "$HEALTH_URL" >/dev/null
curl -fsS "$APP_JS_URL" >/dev/null

printf '[%s] sync hook success\n' "$(date '+%Y-%m-%d %H:%M:%S')"
