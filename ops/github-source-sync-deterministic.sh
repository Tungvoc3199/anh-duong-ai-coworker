#!/usr/bin/env bash
set -Eeuo pipefail

# Deterministic one-shot source sync. No LLM/Codex calls.
# Handles a moved local HEAD by replaying the exact already-verified workflow-fix
# patch onto the CURRENT committed local lineage in a clean clone, then verifies
# that clean tree before publishing it to GitHub.

SOURCE_REPO="/home/thadc/AIOS/anh-duong-core"
REMOTE_URL="https://github.com/Tungvoc3199/anh-duong-ai-coworker.git"
FIX_SHA="9c03450c9fee5a819573915680c05045b0c38f79"
EXPECTED_FIX_FILES=15
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d /tmp/anh-duong-source-sync.XXXXXX)"
LOCAL_STAGE="$WORK/local-stage"
INTEGRATION="$WORK/integration"
PATCH="$WORK/verified-fix.patch"
REPORT="$WORK/result.txt"
SYNC_BRANCH="sync/source-${STAMP}"
BACKUP_BRANCH="backup/pre-source-sync-${STAMP}"

log(){ printf '[source-sync] %s\n' "$*" | tee -a "$REPORT"; }
die(){ printf '[source-sync] ERROR: %s\n' "$*" | tee -a "$REPORT" >&2; exit 1; }

[[ -d "$SOURCE_REPO/.git" ]] || die "missing local repo: $SOURCE_REPO"
command -v git >/dev/null 2>&1 || die "git not found"
command -v curl >/dev/null 2>&1 || die "curl not found"

LOCAL_HEAD="$(git -C "$SOURCE_REPO" rev-parse HEAD)"
BEFORE_STATUS="$WORK/production-status.before"
AFTER_STATUS="$WORK/production-status.after"
git -C "$SOURCE_REPO" status --porcelain=v1 -uall >"$BEFORE_STATUS"
log "local_head=$LOCAL_HEAD"
log "work=$WORK"

# Production is source-of-truth runtime; this script never restarts or modifies it.
curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null || die "production /health failed before sync"
curl -fsS --max-time 5 http://127.0.0.1:8790/ready  >/dev/null || die "production /ready failed before sync"
log "production_precheck=PASS"

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
[[ -n "$FIX_REPO" ]] || die "verified commit $FIX_SHA not found locally; refusing to reconstruct from dirty production"
FIX_PARENT="$(git -C "$FIX_REPO" rev-parse "$FIX_SHA^")"
log "verified_fix_repo=$FIX_REPO"
log "verified_fix_parent=$FIX_PARENT"

# Prove the verified commit is exactly the scoped workflow fix we expect.
mapfile -t FIX_FILES < <(git -C "$FIX_REPO" diff-tree --no-commit-id --name-only -r "$FIX_SHA" | sed '/^$/d')
[[ "${#FIX_FILES[@]}" -eq "$EXPECTED_FIX_FILES" ]] || die "verified fix file count changed: expected $EXPECTED_FIX_FILES, got ${#FIX_FILES[@]}"
for p in "${FIX_FILES[@]}"; do
  case "$p" in
    app/*|tests/*|integrations/openclaw-anh-duong-core/*) ;;
    *) die "verified fix contains out-of-scope path: $p" ;;
  esac
done
log "verified_fix_scope=PASS files=${#FIX_FILES[@]}"

git -C "$FIX_REPO" diff --binary "$FIX_PARENT" "$FIX_SHA" -- "${FIX_FILES[@]}" >"$PATCH"
[[ -s "$PATCH" ]] || die "verified fix patch is empty"

# Build a clean candidate from CURRENT committed local HEAD. Dirty production files
# are never read into this candidate.
git clone --no-hardlinks --no-tags "$SOURCE_REPO" "$LOCAL_STAGE" >>"$REPORT" 2>&1 || die "clean local clone failed"
git -C "$LOCAL_STAGE" checkout --detach "$LOCAL_HEAD" >>"$REPORT" 2>&1 || die "cannot checkout current local HEAD in clean clone"

# Configure identity only inside disposable clone if missing.
git -C "$LOCAL_STAGE" config user.name  >/dev/null 2>&1 || git -C "$LOCAL_STAGE" config user.name "Anh Duong Source Sync"
git -C "$LOCAL_STAGE" config user.email >/dev/null 2>&1 || git -C "$LOCAL_STAGE" config user.email "source-sync@localhost"

# Replay the EXACT verified fix onto the moved current lineage. If it is already
# present, accept only when the patch can be cleanly reversed; otherwise fail closed.
set +e
git -C "$LOCAL_STAGE" apply --3way --index "$PATCH" >>"$REPORT" 2>&1
APPLY_RC=$?
set -e
if (( APPLY_RC == 0 )); then
  git -C "$LOCAL_STAGE" diff --cached --check || die "replayed fix failed diff --check"
  git -C "$LOCAL_STAGE" commit -m "Fix Telegram workflow completion contract" >>"$REPORT" 2>&1 || die "cannot commit replayed verified fix"
  CANDIDATE_SHA="$(git -C "$LOCAL_STAGE" rev-parse HEAD)"
  log "verified_fix_replay=APPLIED candidate_sha=$CANDIDATE_SHA"
else
  git -C "$LOCAL_STAGE" reset --hard "$LOCAL_HEAD" >/dev/null 2>&1
  if git -C "$LOCAL_STAGE" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    CANDIDATE_SHA="$LOCAL_HEAD"
    log "verified_fix_replay=ALREADY_PRESENT candidate_sha=$CANDIDATE_SHA"
  else
    die "verified fix does not apply cleanly to current HEAD and is not already present; manual semantic conflict review required"
  fi
fi

# Exact fix paths in candidate must at minimum contain the verified change. A reverse
# check proves the complete verified patch is represented even if later committed edits
# exist around it.
if ! git -C "$LOCAL_STAGE" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
  die "candidate does not contain the complete verified workflow fix"
fi
log "candidate_contains_verified_fix=PASS"

# Optional GitHub CLI credential helper setup when already authenticated.
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh auth setup-git >/dev/null 2>&1 || true
  log "github_auth=gh-authenticated"
else
  log "github_auth=using-existing-git-credential-helper"
fi

# Clone existing GitHub history and fetch the clean current-source candidate.
git clone --no-tags "$REMOTE_URL" "$INTEGRATION" >>"$REPORT" 2>&1 || die "GitHub clone failed; check credentials/network"
git -C "$INTEGRATION" fetch origin main >>"$REPORT" 2>&1 || die "cannot fetch origin/main"
REMOTE_MAIN_SHA="$(git -C "$INTEGRATION" rev-parse origin/main)"
log "github_main_before=$REMOTE_MAIN_SHA"

git -C "$INTEGRATION" remote add local-source "$LOCAL_STAGE"
git -C "$INTEGRATION" fetch --no-tags local-source "$CANDIDATE_SHA" >>"$REPORT" 2>&1 || die "cannot fetch clean current-source candidate"
git -C "$INTEGRATION" switch -c "$SYNC_BRANCH" origin/main >>"$REPORT" 2>&1

# Unify unrelated histories deterministically: preserve GitHub docs on docs/* conflicts;
# clean verified local source wins everywhere else.
set +e
git -C "$INTEGRATION" merge --allow-unrelated-histories --no-ff "$CANDIDATE_SHA" -m "chore: sync canonical Ánh Dương source" >>"$REPORT" 2>&1
MERGE_RC=$?
set -e
if (( MERGE_RC != 0 )); then
  mapfile -t CONFLICTS < <(git -C "$INTEGRATION" diff --name-only --diff-filter=U)
  ((${#CONFLICTS[@]} > 0)) || die "merge failed without resolvable file conflicts"
  log "merge_conflicts=${#CONFLICTS[@]}"
  for p in "${CONFLICTS[@]}"; do
    if [[ "$p" == docs/* ]]; then
      git -C "$INTEGRATION" checkout --ours -- "$p" 2>/dev/null || git -C "$INTEGRATION" rm -f --ignore-unmatch -- "$p" >/dev/null
      log "conflict $p -> preserve GitHub docs"
    else
      git -C "$INTEGRATION" checkout --theirs -- "$p" 2>/dev/null || git -C "$INTEGRATION" rm -f --ignore-unmatch -- "$p" >/dev/null
      log "conflict $p -> clean local source"
    fi
    git -C "$INTEGRATION" add -A -- "$p"
  done
  [[ -z "$(git -C "$INTEGRATION" diff --name-only --diff-filter=U)" ]] || die "unresolved merge conflicts remain"
  git -C "$INTEGRATION" commit --no-edit >>"$REPORT" 2>&1 || die "merge commit failed"
fi
SYNC_SHA="$(git -C "$INTEGRATION" rev-parse HEAD)"
log "integration_sha=$SYNC_SHA"

# Integration source must match the clean current-source candidate byte-for-byte.
SOURCE_PATHS=(app tests integrations scripts alembic alembic.ini pyproject.toml README.md)
EXISTING_SOURCE_PATHS=()
for p in "${SOURCE_PATHS[@]}"; do
  if git -C "$LOCAL_STAGE" cat-file -e "$CANDIDATE_SHA:$p" 2>/dev/null; then
    EXISTING_SOURCE_PATHS+=("$p")
  fi
done
if ((${#EXISTING_SOURCE_PATHS[@]})); then
  git -C "$INTEGRATION" diff --quiet "$CANDIDATE_SHA" HEAD -- "${EXISTING_SOURCE_PATHS[@]}" || die "integration changed clean local source paths"
fi
log "clean_source_tree=PASS"

# Reject secrets/runtime/checkpoints. .env.example is explicitly allowed.
TRACKED="$WORK/tracked.txt"
BAD_TRACKED="$WORK/bad-tracked.txt"
git -C "$INTEGRATION" ls-files >"$TRACKED"
{
  grep -E '(^|/)\.env($|\.)' "$TRACKED" | grep -vE '(^|/)\.env\.example$' || true
  grep -E '(^|/)(auth\.json|\.venv/|__pycache__/|.*\.pyc$|anh_duong\.db$)' "$TRACKED" || true
  grep -E '(^|/)(anh-duong-checkpoints|checkpoints?)/' "$TRACKED" || true
} | sort -u >"$BAD_TRACKED"
[[ ! -s "$BAD_TRACKED" ]] || { cat "$BAD_TRACKED" >&2; die "secret/runtime/checkpoint-like files would be published"; }
log "tracked_secret_runtime_guard=PASS"

git -C "$INTEGRATION" diff --check || die "git diff --check failed"
log "git_diff_check=PASS"

# Deterministic verification in clean integration tree, using existing local venv.
PY="$SOURCE_REPO/.venv/bin/python"
[[ -x "$PY" ]] || die "missing production venv python: $PY"
(
  cd "$INTEGRATION"
  "$PY" -m pytest -q
) >>"$REPORT" 2>&1 || die "full pytest failed"
log "pytest=PASS"
(
  cd "$INTEGRATION"
  "$PY" -m ruff check app tests
) >>"$REPORT" 2>&1 || die "Ruff failed"
log "ruff=PASS"
(
  cd "$INTEGRATION"
  "$PY" -m mypy app
) >>"$REPORT" 2>&1 || die "Mypy failed"
log "mypy=PASS"
(
  cd "$INTEGRATION"
  PYTHONPYCACHEPREFIX="$WORK/pycache" "$PY" -m compileall -q app
) || die "Compileall failed"
log "compileall=PASS"
if [[ -f "$INTEGRATION/integrations/openclaw-anh-duong-core/package.json" ]]; then
  (cd "$INTEGRATION/integrations/openclaw-anh-duong-core" && npm test) >>"$REPORT" 2>&1 || die "plugin tests failed"
  log "plugin_tests=PASS"
fi

# Ensure GitHub main did not move during verification, then publish safely.
git -C "$INTEGRATION" fetch origin main >>"$REPORT" 2>&1
[[ "$(git -C "$INTEGRATION" rev-parse origin/main)" == "$REMOTE_MAIN_SHA" ]] || die "GitHub main changed during verification; refusing concurrent update"

git -C "$INTEGRATION" branch "$BACKUP_BRANCH" "$REMOTE_MAIN_SHA"
git -C "$INTEGRATION" push origin "$BACKUP_BRANCH:refs/heads/$BACKUP_BRANCH" >>"$REPORT" 2>&1 || die "backup branch push failed"
[[ "$(git -C "$INTEGRATION" ls-remote origin "refs/heads/$BACKUP_BRANCH" | awk '{print $1}')" == "$REMOTE_MAIN_SHA" ]] || die "backup branch remote verification failed"
log "backup_branch=$BACKUP_BRANCH"

git -C "$INTEGRATION" push origin "$SYNC_SHA:refs/heads/$SYNC_BRANCH" >>"$REPORT" 2>&1 || die "sync branch push failed"
[[ "$(git -C "$INTEGRATION" ls-remote origin "refs/heads/$SYNC_BRANCH" | awk '{print $1}')" == "$SYNC_SHA" ]] || die "sync branch remote verification failed"
log "sync_branch=$SYNC_BRANCH"

git -C "$INTEGRATION" merge-base --is-ancestor "$REMOTE_MAIN_SHA" "$SYNC_SHA" || die "sync commit is not descendant of prior GitHub main"
git -C "$INTEGRATION" push origin "$SYNC_SHA:refs/heads/main" >>"$REPORT" 2>&1 || die "main fast-forward push failed"
REMOTE_FINAL_SHA="$(git -C "$INTEGRATION" ls-remote origin refs/heads/main | awk '{print $1}')"
[[ "$REMOTE_FINAL_SHA" == "$SYNC_SHA" ]] || die "remote main SHA mismatch after push"
log "github_main_after=$REMOTE_FINAL_SHA"

git -C "$INTEGRATION" fetch origin main >>"$REPORT" 2>&1
for p in app tests integrations/openclaw-anh-duong-core docs; do
  git -C "$INTEGRATION" cat-file -e "origin/main:$p" 2>/dev/null || die "remote main missing required path: $p"
done
log "remote_tree_required_paths=PASS"

# Point local repo at canonical GitHub without touching working files.
OLD_ORIGIN="$(git -C "$SOURCE_REPO" remote get-url origin 2>/dev/null || true)"
if git -C "$SOURCE_REPO" remote get-url origin >/dev/null 2>&1; then
  git -C "$SOURCE_REPO" remote set-url origin "$REMOTE_URL"
else
  git -C "$SOURCE_REPO" remote add origin "$REMOTE_URL"
fi
git -C "$SOURCE_REPO" fetch origin main >>"$REPORT" 2>&1 || die "local origin fetch failed after publish"
log "local_origin_before=${OLD_ORIGIN:-NONE}"
log "local_origin_after=$REMOTE_URL"

# Final production invariants: dirty tree identical, runtime still healthy.
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
