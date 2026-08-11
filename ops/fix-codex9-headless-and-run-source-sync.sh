#!/usr/bin/env bash
set -Eeuo pipefail

WRAPPER="$HOME/bin/codex9"
REPO="/home/thadc/AIOS/anh-duong-core"
PROMPT_URL="https://raw.githubusercontent.com/Tungvoc3199/anh-duong-ai-coworker/5a864310dcc3e4dea4dab6439eee3710a4d96ca0/ops/github-source-sync-one-shot.txt"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${WRAPPER}.bak-${STAMP}"

log(){ printf '[codex9-headless-fix] %s\n' "$*"; }
die(){ printf '[codex9-headless-fix] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -f "$WRAPPER" ]] || die "missing wrapper: $WRAPPER"
[[ -x "$WRAPPER" ]] || die "wrapper is not executable: $WRAPPER"
[[ -d "$REPO/.git" ]] || die "local repo not found: $REPO"
command -v codex >/dev/null 2>&1 || die "codex not found on PATH"
command -v curl >/dev/null 2>&1 || die "curl not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"

cp -a -- "$WRAPPER" "$BACKUP"

python3 - "$WRAPPER" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = 'exec codex -p router9\n'
new = 'exec codex -p router9 "$@"\n'
if new in s:
    pass
elif old in s:
    s = s.replace(old, new, 1)
else:
    raise SystemExit("expected wrapper launch line not found")
p.write_text(s)
PY

chmod +x "$WRAPPER"
if ! bash -n "$WRAPPER"; then
  cp -a -- "$BACKUP" "$WRAPPER"
  die "wrapper syntax check failed; restored backup"
fi
if ! grep -Fq 'exec codex -p router9 "$@"' "$WRAPPER"; then
  cp -a -- "$BACKUP" "$WRAPPER"
  die "argument forwarding not installed; restored backup"
fi

# Prove that the wrapper now forwards the exec subcommand instead of opening TUI.
HELP_OUT="/tmp/codex9-exec-help-${STAMP}.txt"
if ! timeout 15 "$WRAPPER" exec --help >"$HELP_OUT" 2>&1; then
  cp -a -- "$BACKUP" "$WRAPPER"
  die "codex9 exec --help failed; restored backup"
fi
if ! grep -qiE 'non-interactive|Usage:.*exec|codex exec' "$HELP_OUT"; then
  cp -a -- "$BACKUP" "$WRAPPER"
  die "wrapper still does not reach codex exec; restored backup"
fi
log "wrapper fixed and headless exec verified; backup=$BACKUP"

PROMPT="$(curl -fsSL "$PROMPT_URL")"
[[ -n "$PROMPT" ]] || die "source-sync prompt download was empty"

cd "$REPO"
log "starting one-shot GitHub Source Sync in non-interactive mode"
log "Codex permissions for this controlled one-shot: approval=never, sandbox=danger-full-access"

# -p router9 is injected by the wrapper. Global flags are forwarded before `exec`.
# Codex official CLI supports `codex exec` for non-interactive runs and explicit
# `--ask-for-approval never` + `--sandbox danger-full-access` for controlled automation.
"$WRAPPER" --ask-for-approval never --sandbox danger-full-access exec "$PROMPT"

log "SOURCE_SYNC_CODEX_RUN_EXITED_OK"
