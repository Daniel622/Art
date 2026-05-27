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
DEPLOYED_REVISION_FILE="$REMOTE_DIR/.deployed-revision"
ALLOWED_PATHS=(server.py README.md Makefile .gitignore .claude/hooks/sync-after-round.sh)
ALLOWED_PREFIXES=(static/ tests/ deploy/ docs/)

mkdir -p "$ROOT/.claude/hooks"
mkdir -p "$ROOT/.claude"

exec >>"$LOG_FILE" 2>&1
printf '\n[%s] sync hook start\n' "$(date '+%Y-%m-%d %H:%M:%S')"
trap 'printf "failed at line %s: %s\n" "$LINENO" "$BASH_COMMAND"' ERR

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

is_allowed_path() {
  local path="$1"
  local allowed
  for allowed in "${ALLOWED_PATHS[@]}"; do
    [[ "$path" == "$allowed" ]] && return 0
  done
  for allowed in "${ALLOWED_PREFIXES[@]}"; do
    [[ "$path" == "$allowed"* ]] && return 0
  done
  return 1
}

collect_changes() {
  git status --porcelain | while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local path="${line#?? }"
    if [[ "$path" == *" -> "* ]]; then
      path="${path##* -> }"
    fi
    printf '%s\n' "$path"
  done
}

mapfile -t changed_paths < <(collect_changes)
if (( ${#changed_paths[@]} == 0 )); then
  printf 'no working tree changes, skip\n'
  exit 0
fi

unsafe_paths=()
safe_paths=()
path_has_secret_name() {
  local path="$1"
  [[ "$path" == .env || "$path" == .env.* || "$path" == *.pem || "$path" == */id_rsa || "$path" == */id_ed25519 || "$path" == id_rsa || "$path" == id_ed25519 ]]
}

for path in "${changed_paths[@]}"; do
  if path_has_secret_name "$path"; then
    printf 'abort: suspicious path detected %s\n' "$path"
    exit 1
  fi
  if is_allowed_path "$path"; then
    safe_paths+=("$path")
  elif [[ "$path" == .claude/settings.local.json || "$path" == .claude/sync-after-round.log || "$path" == .claude/*.lock || "$path" == .DS_Store || "$path" == ._* ]]; then
    continue
  else
    unsafe_paths+=("$path")
  fi
done

if (( ${#unsafe_paths[@]} > 0 )); then
  printf 'abort: changed paths outside auto-sync allowlist:\n'
  printf '  %s\n' "${unsafe_paths[@]}"
  exit 1
fi

if (( ${#safe_paths[@]} == 0 )); then
  printf 'no relevant allowed changes, skip\n'
  exit 0
fi

printf 'fetching remote main\n'
git fetch origin main
local_head="$(git rev-parse HEAD)"
remote_head="$(git rev-parse origin/main)"
merge_base="$(git merge-base HEAD origin/main)"
if [[ "$local_head" != "$remote_head" ]]; then
  if [[ "$local_head" == "$merge_base" ]]; then
    printf 'abort: local main is behind origin/main, please sync manually first\n'
    exit 1
  fi
  if [[ "$remote_head" != "$merge_base" ]]; then
    printf 'abort: local main diverged from origin/main, please resolve manually first\n'
    exit 1
  fi
fi

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

printf 'staging safe files\n'
git add -- "${safe_paths[@]}"

if git diff --cached --quiet; then
  printf 'no safe staged changes after filtering, skip\n'
  exit 0
fi

printf 'running secret scan\n'
if git diff --cached -- . ':(exclude).claude/settings.local.json' | grep -E 'ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ANTHROPIC_API_KEY|sk-[A-Za-z0-9]+|AKIA[0-9A-Z]{16}' >/dev/null; then
  printf 'abort: secret-like content detected in staged diff\n'
  exit 1
fi

summary="$(printf '%s
' "${safe_paths[@]}" | sed 's#/$##' | cut -d/ -f1 | uniq | paste -sd ', ' -)"
summary="${summary:-project files}"
commit_message="$(cat <<EOF
Auto-sync: update ${summary}.
EOF
)"

printf 'creating commit\n'
git commit -m "$commit_message"
commit_sha="$(git rev-parse HEAD)"
commit_short="$(git rev-parse --short HEAD)"
printf 'created commit %s\n' "$commit_short"

printf 'pushing to GitHub\n'
git push origin HEAD:main

printf 'deploying to VPS\n'
COPYFILE_DISABLE=1 tar --exclude='.git' \
  --exclude='.claude' \
  --exclude='data' \
  --exclude='__pycache__' \
  --exclude='friend-image-gen' \
  --exclude='pixelforge-source-20260527-083452.tar.gz' \
  --exclude='*.tar.gz' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='._*' \
  --exclude='.DS_Store' \
  -czf - . \
| ssh -o BatchMode=yes "$REMOTE_HOST" "tar -xzf - -C '$REMOTE_DIR' && printf '%s\n' '$commit_sha' > '$DEPLOYED_REVISION_FILE' && systemctl restart '$SERVICE_NAME' && sleep 1 && systemctl is-active '$SERVICE_NAME'"

printf 'running health checks\n'
curl -fsS "$HEALTH_URL" >/dev/null
curl -fsS "$APP_JS_URL" >/dev/null
ssh -o BatchMode=yes "$REMOTE_HOST" "test \"\$(cat '$DEPLOYED_REVISION_FILE')\" = '$commit_sha' && systemctl is-active '$SERVICE_NAME' >/dev/null" >/dev/null

printf '[%s] sync hook success (%s)\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$commit_short"
