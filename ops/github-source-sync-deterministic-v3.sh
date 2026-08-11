#!/usr/bin/env bash
set -Eeuo pipefail

# Deterministic GitHub Source Sync v3. No Codex/LLM/model calls.
# Publishes only committed local lineage + the exact previously E2E-verified 15-file fix.
# Never reads dirty production file contents into the candidate and never restarts production.

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
die(){ log "ERROR: $*"; exit 1; }
on_exit(){
  rc=$?
  if (( rc != 0 )); then
    printf '\n[source-sync] FAILED rc=%s report=%s\n' "$rc" "$REPORT" >&2
    if [[ -s "$REPORT" ]]; then
      printf '%s\n' '--- last report lines ---' >&2
      tail -n 40 "$REPORT" >&2 || true
    fi
  fi
}
trap on_exit EXIT

[[ -d "$SOURCE_REPO/.git" ]] || die "missing local repo: $SOURCE_REPO"
for c in git curl; do command -v "$c" >/dev/null 2>&1 || die "$c not found"; done

LOCAL_HEAD="$(git -C "$SOURCE_REPO" rev-parse HEAD)"
BEFORE_STATUS="$WORK/production-status.before"
AFTER_STATUS="$WORK/production-status.after"
git -C "$SOURCE_REPO" status --porcelain=v1 -uall >"$BEFORE_STATUS"
log "local_head=$LOCAL_HEAD"
log "work=$WORK"

curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null || die "production /health failed before sync"
curl -fsS --max-time 5 http://127.0.0.1:8790/ready  >/dev/null || die "production /ready failed before sync"
log "production_precheck=PASS"

find_fix_repo(){
  local d
  for d in /tmp/anh-duong-sync.*/repo /tmp/anh-duong-core-* /tmp/anh-duong-* "$SOURCE_REPO"; do
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

# Clean clone from CURRENT committed local HEAD only. Dirty working-tree content is excluded.
git clone --no-hardlinks --no-tags "$SOURCE_REPO" "$LOCAL_STAGE" >>"$REPORT" 2>&1 || die "clean local clone failed"
git -C "$LOCAL_STAGE" checkout --detach "$LOCAL_HEAD" >>"$REPORT" 2>&1 || die "cannot checkout current local HEAD"

# Replay exact verified patch. Use commit-tree instead of `git commit` so local hooks,
# signing config, or inherited commit policy cannot block this mechanical candidate commit.
set +e
git -C "$LOCAL_STAGE" apply --3way --index "$PATCH" >>"$REPORT" 2>&1
APPLY_RC=$?
set -e

if (( APPLY_RC == 0 )); then
  if git -C "$LOCAL_STAGE" diff --cached --quiet; then
    if git -C "$LOCAL_STAGE" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
      CANDIDATE_SHA="$LOCAL_HEAD"
      log "verified_fix_replay=ALREADY_PRESENT candidate_sha=$CANDIDATE_SHA"
    else
      die "patch apply returned success but produced no staged change and verified fix is not detectable"
    fi
  else
    git -C "$LOCAL_STAGE" diff --cached --check || die "replayed fix failed diff --check"
    CANDIDATE_TREE="$(git -C "$LOCAL_STAGE" write-tree)"
    CANDIDATE_SHA="$(
      printf '%s\n' 'Fix Telegram workflow completion contract' |
      GIT_AUTHOR_NAME='Anh Duong Source Sync' \
      GIT_AUTHOR_EMAIL='source-sync@localhost' \
      GIT_COMMITTER_NAME='Anh Duong Source Sync' \
      GIT_COMMITTER_EMAIL='source-sync@localhost' \
      git -C "$LOCAL_STAGE" commit-tree "$CANDIDATE_TREE" -p "$LOCAL_HEAD"
    )" || die "commit-tree failed for replayed verified fix"
    git -C "$LOCAL_STAGE" update-ref refs/heads/source-sync-candidate "$CANDIDATE_SHA"
    log "verified_fix_replay=APPLIED candidate_sha=$CANDIDATE_SHA"
  fi
else
  git -C "$LOCAL_STAGE" reset --hard "$LOCAL_HEAD" >/dev/null 2>&1
  if git -C "$LOCAL_STAGE" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    CANDIDATE_SHA="$LOCAL_HEAD"
    log "verified_fix_replay=ALREADY_PRESENT candidate_sha=$CANDIDATE_SHA"
  else
    die "verified fix neither applies cleanly nor is already represented on current HEAD"
  fi
fi

# Ensure candidate object is referenced and contains the complete verified patch.
git -C "$LOCAL_STAGE" update-ref refs/heads/source-sync-candidate "$CANDIDATE_SHA"
git -C "$LOCAL_STAGE" checkout -f source-sync-candidate >>"$REPORT" 2>&1 || die "cannot checkout candidate"
if ! git -C "$LOCAL_STAGE" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
  die "candidate does not contain the complete verified workflow fix"
fi
log "candidate_contains_verified_fix=PASS"

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh auth setup-git >/dev/null 2>&1 || true
  log "github_auth=gh-authenticated"
else
  log "github_auth=using-existing-git-credential-helper"
fi

# Integrate existing GitHub docs history with clean local source lineage.
git clone --no-tags "$REMOTE_URL" "$INTEGRATION" >>"$REPORT" 2>&1 || die "GitHub clone failed; check credentials/network"
git -C "$INTEGRATION" fetch origin main >>"$REPORT" 2>&1 || die "cannot fetch origin/main"
REMOTE_MAIN_SHA="$(git -C "$INTEGRATION" rev-parse origin/main)"
log "github_main_before=$REMOTE_MAIN_SHA"

git -C "$INTEGRATION" remote add local-source "$LOCAL_STAGE"
git -C "$INTEGRATION" fetch --no-tags local-source refs/heads/source-sync-candidate:refs/remotes/local-source/source-sync-candidate >>"$REPORT" 2>&1 || die "cannot fetch clean candidate"
FETCHED_CANDIDATE="$(git -C "$INTEGRATION" rev-parse refs/remotes/local-source/source-sync-candidate)"
[[ "$FETCHED_CANDIDATE" == "$CANDIDATE_SHA" ]] || die "candidate SHA mismatch after local fetch"
git -C "$INTEGRATION" switch -c "$SYNC_BRANCH" origin/main >>"$REPORT" 2>&1 || die "cannot create sync branch"

# Disable signing/hooks only in disposable integration repo.
git -C "$INTEGRATION" config user.name 'Anh Duong Source Sync'
git -C "$INTEGRATION" config user.email 'source-sync@localhost'
git -C "$INTEGRATION" config commit.gpgsign false
git -C "$INTEGRATION" config core.hooksPath /dev/null

set +e
git -C "$INTEGRATION" merge --allow-unrelated-histories --no-ff --no-commit "$CANDIDATE_SHA" >>"$REPORT" 2>&1
MERGE_RC=$?
set -e
if (( MERGE_RC != 0 )); then
  mapfile -t CONFLICTS < <(git -C "$INTEGRATION" diff --name-only --diff-filter=U)
  ((${#CONFLICTS[@]} > 0)) || die "merge failed without file conflicts"
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
fi

# Whether merge was conflict-free or resolved, create one deterministic merge commit.
git -C "$INTEGRATION" diff --cached --check || die "integration staged diff failed diff --check"
git -C "$INTEGRATION" -c commit.gpgsign=false -c core.hooksPath=/dev/null commit --no-verify -m 'chore: sync canonical Ánh Dương source' >>"$REPORT" 2>&1 || die "integration merge commit failed"
SYNC_SHA="$(git -C "$INTEGRATION" rev-parse HEAD)"
log "integration_sha=$SYNC_SHA"

# Source paths in merged tree must equal clean candidate; GitHub-only docs are preserved.
SOURCE_PATHS=(app tests integrations scripts alembic alembic.ini pyproject.toml README.md)
EXISTING_SOURCE_PATHS=()
for p in "${SOURCE_PATHS[@]}"; do
  if git -C "$LOCAL_STAGE" cat-file -e "$CANDIDATE_SHA:$p" 2>/dev/null; then
    EXISTING_SOURCE_PATHS+=("$p")
  fi
done
if ((${#EXISTING_SOURCE_PATHS[@]})); then
  git -C "$INTEGRATION" diff --quiet "$CANDIDATE_SHA" "$SYNC_SHA" -- "${EXISTING_SOURCE_PATHS[@]}" || die "integration changed clean local source paths"
fi
log "clean_source_tree=PASS"

# Guard secrets/runtime/checkpoint material.
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

PY="$SOURCE_REPO/.venv/bin/python"
[[ -x "$PY" ]] || die "missing production venv python: $PY"
(cd "$INTEGRATION" && "$PY" -m pytest -q) >>"$REPORT" 2>&1 || die "full pytest failed"
log "pytest=PASS"
(cd "$INTEGRATION" && "$PY" -m ruff check app tests) >>"$REPORT" 2>&1 || die "Ruff failed"
log "ruff=PASS"
(cd "$INTEGRATION" && "$PY" -m mypy app) >>"$REPORT" 2>&1 || die "Mypy failed"
log "mypy=PASS"
(cd "$INTEGRATION" && PYTHONPYCACHEPREFIX="$WORK/pycache" "$PY" -m compileall -q app) || die "Compileall failed"
log "compileall=PASS"
if [[ -f "$INTEGRATION/integrations/openclaw-anh-duong-core/package.json" ]]; then
  (cd "$INTEGRATION/integrations/openclaw-anh-duong-core" && npm test) >>"$REPORT" 2>&1 || die "plugin tests failed"
  log "plugin_tests=PASS"
fi

# Publish only after all gates pass; no force push.
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

# Point local repo at canonical GitHub without checkout/reset/stash/clean.
OLD_ORIGIN="$(git -C "$SOURCE_REPO" remote get-url origin 2>/dev/null || true)"
if git -C "$SOURCE_REPO" remote get-url origin >/dev/null 2>&1; then
  git -C "$SOURCE_REPO" remote set-url origin "$REMOTE_URL"
else
  git -C "$SOURCE_REPO" remote add origin "$REMOTE_URL"
fi
git -C "$SOURCE_REPO" fetch origin main >>"$REPORT" 2>&1 || die "local origin fetch failed after publish"
log "local_origin_before=${OLD_ORIGIN:-NONE}"
log "local_origin_after=$REMOTE_URL"

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
