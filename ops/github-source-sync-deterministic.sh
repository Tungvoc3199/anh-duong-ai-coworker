#!/usr/bin/env bash
set -Eeuo pipefail

# Deterministic one-shot source sync. No LLM/Codex calls.
# Goal: publish the already-verified local Ánh Dương source lineage to
# Tungvoc3199/anh-duong-ai-coworker while preserving the existing GitHub docs history.

SOURCE_REPO="/home/thadc/AIOS/anh-duong-core"
REMOTE_URL="https://github.com/Tungvoc3199/anh-duong-ai-coworker.git"
FIX_SHA="9c03450c9fee5a819573915680c05045b0c38f79"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d /tmp/anh-duong-source-sync.XXXXXX)"
INTEGRATION="$WORK/repo"
REPORT="$WORK/result.txt"
SYNC_BRANCH="sync/source-${STAMP}"
BACKUP_BRANCH="backup/pre-source-sync-${STAMP}"

log(){ printf '[source-sync] %s\n' "$*" | tee -a "$REPORT"; }
die(){ printf '[source-sync] ERROR: %s\n' "$*" | tee -a "$REPORT" >&2; exit 1; }
cleanup(){ :; }
trap cleanup EXIT

[[ -d "$SOURCE_REPO/.git" ]] || die "missing local repo: $SOURCE_REPO"
command -v git >/dev/null 2>&1 || die "git not found"
command -v curl >/dev/null 2>&1 || die "curl not found"

LOCAL_HEAD="$(git -C "$SOURCE_REPO" rev-parse HEAD)"
BEFORE_STATUS="$WORK/production-status.before"
AFTER_STATUS="$WORK/production-status.after"
git -C "$SOURCE_REPO" status --porcelain=v1 -uall >"$BEFORE_STATUS"

log "local_head=$LOCAL_HEAD"
log "work=$WORK"

# Production runtime must already be healthy; this script never restarts it.
curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null || die "production /health failed before sync"
curl -fsS --max-time 5 http://127.0.0.1:8790/ready  >/dev/null || die "production /ready failed before sync"
log "production precheck=PASS"

# Find the exact clean, previously verified workflow-fix commit. Never reconstruct
# from the dirty production tree and never ask a model to guess the scope.
find_fix_repo(){
  local d
  for d in \
    /tmp/anh-duong-sync.*/repo \
    /tmp/anh-duong-core-* \
    /tmp/anh-duong-* \
    "$SOURCE_REPO"; do
    [[ -d "$d/.git" ]] || continue
    if git -C "$d" cat-file -e "$FIX_SHA^{commit}" 2>/dev/null; then
      printf '%s\n' "$d"
      return 0
    fi
  done
  return 1
}

FIX_REPO="$(find_fix_repo || true)"
[[ -n "$FIX_REPO" ]] || die "verified commit $FIX_SHA not found locally; refusing to guess/rebuild its scope"
log "verified_fix_repo=$FIX_REPO"

# The clean verified fix should be a descendant of the current committed local lineage.
# If local HEAD moved, fail instead of silently publishing the wrong history.
if ! git -C "$FIX_REPO" merge-base --is-ancestor "$LOCAL_HEAD" "$FIX_SHA" 2>/dev/null; then
  die "local HEAD $LOCAL_HEAD is not an ancestor of verified fix $FIX_SHA; source lineage changed"
fi
log "verified_fix_lineage=PASS"

# Optional GitHub CLI credential helper setup when already authenticated.
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh auth setup-git >/dev/null 2>&1 || true
  log "github_auth=gh-authenticated"
else
  log "github_auth=using-existing-git-credential-helper"
fi

# Clone the current GitHub main history into a disposable integration repo.
git clone --no-tags "$REMOTE_URL" "$INTEGRATION" >>"$REPORT" 2>&1 || die "GitHub clone failed; check GitHub credentials/network"
cd "$INTEGRATION"
git fetch origin main >>"$REPORT" 2>&1 || die "cannot fetch origin/main"
REMOTE_MAIN_SHA="$(git rev-parse origin/main)"
log "github_main_before=$REMOTE_MAIN_SHA"

# Fetch the exact verified source commit from its local clean repo.
git remote add verified-fix "$FIX_REPO"
git fetch --no-tags verified-fix "$FIX_SHA" >>"$REPORT" 2>&1 || die "cannot fetch verified fix commit"
git cat-file -e "$FIX_SHA^{commit}" || die "verified fix object unavailable after fetch"

git switch -c "$SYNC_BRANCH" origin/main >>"$REPORT" 2>&1

# Merge unrelated histories. Existing GitHub docs win only on docs/* conflicts;
# verified local source wins everywhere else. No model is involved.
set +e
git merge --allow-unrelated-histories --no-ff "$FIX_SHA" -m "chore: sync canonical Ánh Dương source" >>"$REPORT" 2>&1
MERGE_RC=$?
set -e

if (( MERGE_RC != 0 )); then
  mapfile -t CONFLICTS < <(git diff --name-only --diff-filter=U)
  ((${#CONFLICTS[@]} > 0)) || die "merge failed without resolvable file conflicts"
  log "merge_conflicts=${#CONFLICTS[@]} (resolving deterministically)"
  for p in "${CONFLICTS[@]}"; do
    if [[ "$p" == docs/* ]]; then
      git checkout --ours -- "$p" 2>/dev/null || git rm -f --ignore-unmatch -- "$p" >/dev/null
      log "conflict $p -> preserve GitHub docs side"
    else
      git checkout --theirs -- "$p" 2>/dev/null || git rm -f --ignore-unmatch -- "$p" >/dev/null
      log "conflict $p -> verified local source side"
    fi
    git add -A -- "$p"
  done
  [[ -z "$(git diff --name-only --diff-filter=U)" ]] || die "unresolved merge conflicts remain"
  git commit --no-edit >>"$REPORT" 2>&1 || die "merge commit failed"
fi

SYNC_SHA="$(git rev-parse HEAD)"
log "integration_sha=$SYNC_SHA"

# Source paths must remain byte-for-byte equivalent to the verified fix after merge.
SOURCE_PATHS=(app tests integrations scripts alembic alembic.ini pyproject.toml README.md)
EXISTING_SOURCE_PATHS=()
for p in "${SOURCE_PATHS[@]}"; do
  if git cat-file -e "$FIX_SHA:$p" 2>/dev/null || [[ -e "$p" ]]; then
    EXISTING_SOURCE_PATHS+=("$p")
  fi
done
if ((${#EXISTING_SOURCE_PATHS[@]})); then
  git diff --quiet "$FIX_SHA" HEAD -- "${EXISTING_SOURCE_PATHS[@]}" || die "integration changed verified source paths"
fi
log "verified_source_tree=PASS"

# Reject common secret/runtime/checkpoint material. .env.example is explicitly allowed.
TRACKED="$WORK/tracked.txt"
git ls-files >"$TRACKED"
BAD_TRACKED="$WORK/bad-tracked.txt"
{
  grep -E '(^|/)\.env($|\.)' "$TRACKED" | grep -vE '(^|/)\.env\.example$' || true
  grep -E '(^|/)(auth\.json|\.venv/|__pycache__/|.*\.pyc$|anh_duong\.db$)' "$TRACKED" || true
  grep -E '(^|/)(anh-duong-checkpoints|checkpoints?)/' "$TRACKED" || true
} | sort -u >"$BAD_TRACKED"
[[ ! -s "$BAD_TRACKED" ]] || { cat "$BAD_TRACKED" >&2; die "secret/runtime/checkpoint-like files would be published"; }
log "tracked_secret_runtime_guard=PASS"

git diff --check || die "git diff --check failed"
log "git_diff_check=PASS"

# Verification is local and deterministic; no API/model calls.
PY="$SOURCE_REPO/.venv/bin/python"
[[ -x "$PY" ]] || die "missing production venv python: $PY"

"$PY" -m pytest -q >>"$REPORT" 2>&1 || die "full pytest failed"
log "pytest=PASS"
"$PY" -m ruff check app tests >>"$REPORT" 2>&1 || die "Ruff failed"
log "ruff=PASS"
"$PY" -m mypy app >>"$REPORT" 2>&1 || die "Mypy failed"
log "mypy=PASS"
PYTHONPYCACHEPREFIX="$WORK/pycache" "$PY" -m compileall -q app || die "Compileall failed"
log "compileall=PASS"
if [[ -f integrations/openclaw-anh-duong-core/package.json ]]; then
  (cd integrations/openclaw-anh-duong-core && npm test) >>"$REPORT" 2>&1 || die "plugin tests failed"
  log "plugin_tests=PASS"
fi

# Create remote backup first. If main changed concurrently, stop safely.
git fetch origin main >>"$REPORT" 2>&1
[[ "$(git rev-parse origin/main)" == "$REMOTE_MAIN_SHA" ]] || die "GitHub main changed during verification; refusing concurrent update"
git branch "$BACKUP_BRANCH" "$REMOTE_MAIN_SHA"
git push origin "$BACKUP_BRANCH:refs/heads/$BACKUP_BRANCH" >>"$REPORT" 2>&1 || die "backup branch push failed"
[[ "$(git ls-remote origin "refs/heads/$BACKUP_BRANCH" | awk '{print $1}')" == "$REMOTE_MAIN_SHA" ]] || die "backup branch remote verification failed"
log "backup_branch=$BACKUP_BRANCH"

# Publish sync branch and verify exact SHA.
git push origin "HEAD:refs/heads/$SYNC_BRANCH" >>"$REPORT" 2>&1 || die "sync branch push failed"
[[ "$(git ls-remote origin "refs/heads/$SYNC_BRANCH" | awk '{print $1}')" == "$SYNC_SHA" ]] || die "sync branch remote verification failed"
log "sync_branch=$SYNC_BRANCH"

# Main update is non-force and must be a fast-forward because origin/main is a parent
# of the merge commit. Any concurrent change makes this fail safely.
git merge-base --is-ancestor "$REMOTE_MAIN_SHA" "$SYNC_SHA" || die "sync commit is not descendant of prior GitHub main"
git push origin "HEAD:refs/heads/main" >>"$REPORT" 2>&1 || die "main fast-forward push failed"
REMOTE_FINAL_SHA="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
[[ "$REMOTE_FINAL_SHA" == "$SYNC_SHA" ]] || die "remote main SHA mismatch after push"
log "github_main_after=$REMOTE_FINAL_SHA"

# Remote tree proof: source + prior docs must all exist.
git fetch origin main >>"$REPORT" 2>&1
for p in app tests integrations/openclaw-anh-duong-core docs; do
  git cat-file -e "origin/main:$p" 2>/dev/null || die "remote main missing required path: $p"
done
log "remote_tree_required_paths=PASS"

# Connect production repo to canonical GitHub remote without touching working files.
OLD_ORIGIN="$(git -C "$SOURCE_REPO" remote get-url origin 2>/dev/null || true)"
if git -C "$SOURCE_REPO" remote get-url origin >/dev/null 2>&1; then
  git -C "$SOURCE_REPO" remote set-url origin "$REMOTE_URL"
else
  git -C "$SOURCE_REPO" remote add origin "$REMOTE_URL"
fi
git -C "$SOURCE_REPO" fetch origin main >>"$REPORT" 2>&1 || die "local origin fetch failed after remote publish"
log "local_origin_before=${OLD_ORIGIN:-NONE}"
log "local_origin_after=$REMOTE_URL"

# Prove production working tree and runtime were not disturbed.
git -C "$SOURCE_REPO" status --porcelain=v1 -uall >"$AFTER_STATUS"
cmp -s "$BEFORE_STATUS" "$AFTER_STATUS" || die "production working tree changed during source sync"
curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null || die "production /health failed after sync"
curl -fsS --max-time 5 http://127.0.0.1:8790/ready  >/dev/null || die "production /ready failed after sync"
log "production_unchanged_and_healthy=PASS"

log "DONE"
log "GITHUB_MAIN_SHA=$REMOTE_FINAL_SHA"
log "BACKUP_BRANCH=$BACKUP_BRANCH"
log "SYNC_BRANCH=$SYNC_BRANCH"
log "REPORT=$REPORT"
