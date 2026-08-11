#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_USER="thadc"
REPO="/home/thadc/AIOS/anh-duong-core"
WATCH_UNIT="anh-duong-core-git-commit.path"
RUN_UNIT="anh-duong-core-git-commit.service"
HELPER_PATH="/usr/local/libexec/anh-duong-core-git-commit-helper"
WATCH_PATH="/etc/systemd/system/${WATCH_UNIT}"
RUN_PATH="/etc/systemd/system/${RUN_UNIT}"
REQUEST_PATH="/tmp/anh-duong-core-git-commit.request.json"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="/var/backups/anh-duong-core-git-commit-${STAMP}"
BOOTSTRAP_COMMITTED=0

log() { printf '[autonomous-core-git-commit] %s\n' "$*"; }
die() { printf '[autonomous-core-git-commit] ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || die "run once as root"
id "$TARGET_USER" >/dev/null 2>&1 || die "user '$TARGET_USER' does not exist"
[[ -d "$REPO/.git" || -f "$REPO/.git" ]] || die "repo git metadata not found: $REPO"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v runuser >/dev/null 2>&1 || die "runuser is required"
command -v git >/dev/null 2>&1 || die "git is required"
runuser -u "$TARGET_USER" -- git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null || die "target user cannot access repository"

mkdir -p "$BACKUP_DIR"
for p in "$HELPER_PATH" "$WATCH_PATH" "$RUN_PATH"; do
  if [[ -e "$p" ]]; then cp -a -- "$p" "$BACKUP_DIR/$(basename "$p")"; fi
done

TMPDIR_BOOT="$(mktemp -d /tmp/anh-duong-core-git-commit-bootstrap.XXXXXX)"
cleanup() { rm -rf -- "$TMPDIR_BOOT"; }
rollback_on_error() {
  local rc="$1"
  if (( rc != 0 )) && (( BOOTSTRAP_COMMITTED == 0 )); then
    log "bootstrap failed; restoring previous helper/unit state"
    systemctl disable --now "$WATCH_UNIT" >/dev/null 2>&1 || true
    for target in "$HELPER_PATH" "$WATCH_PATH" "$RUN_PATH"; do
      base="$(basename "$target")"
      if [[ -e "$BACKUP_DIR/$base" ]]; then cp -a -- "$BACKUP_DIR/$base" "$target"; else rm -f -- "$target"; fi
    done
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi
  cleanup
}
trap 'rc=$?; rollback_on_error "$rc"; exit "$rc"' EXIT

cat >"$TMPDIR_BOOT/anh-duong-core-git-commit-helper" <<'HELPER'
#!/usr/bin/env bash
set -Eeuo pipefail
REPO="/home/thadc/AIOS/anh-duong-core"
REQUEST="/tmp/anh-duong-core-git-commit.request.json"
STATUS="/run/anh-duong-core-git-commit/status.json"
LOCK="/run/anh-duong-core-git-commit/lock"
EXPECTED_OWNER="thadc"

write_status() {
  local outcome="$1" reason="$2" commit="${3:-}"
  python3 - "$STATUS" "$outcome" "$reason" "$commit" <<'PY'
import json, sys
from datetime import datetime, timezone
path, outcome, reason, commit = sys.argv[1:]
payload = {"outcome": outcome, "reason": reason, "commit": commit or None,
           "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
with open(path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, separators=(",", ":")); f.write("\n")
PY
  chmod 0644 "$STATUS"
}

exec 9>"$LOCK"
if ! flock -n 9; then write_status "blocked" "commit_already_in_progress"; exit 0; fi
[[ -e "$REQUEST" ]] || exit 0
if [[ -L "$REQUEST" || ! -f "$REQUEST" ]]; then rm -f -- "$REQUEST"; write_status "blocked" "invalid_request_type"; exit 0; fi
owner="$(stat -c '%U' -- "$REQUEST" 2>/dev/null || true)"
if [[ "$owner" != "$EXPECTED_OWNER" ]]; then rm -f -- "$REQUEST"; write_status "blocked" "invalid_request_owner"; exit 0; fi

mapfile -d '' parsed < <(python3 - "$REQUEST" <<'PY'
import json, os, sys
p = sys.argv[1]
try: data = json.load(open(p, encoding="utf-8"))
except Exception as e:
    print(f"ERROR\0invalid_json:{type(e).__name__}\0", end=""); raise SystemExit
if not isinstance(data, dict): print("ERROR\0request_not_object\0", end=""); raise SystemExit
message, files = data.get("message"), data.get("files")
if not isinstance(message, str) or not (1 <= len(message.strip()) <= 120): print("ERROR\0invalid_commit_message\0", end=""); raise SystemExit
if any(c in message for c in ("\n", "\r", "\x00")): print("ERROR\0invalid_commit_message_chars\0", end=""); raise SystemExit
if not isinstance(files, list) or not (1 <= len(files) <= 64): print("ERROR\0invalid_files_list\0", end=""); raise SystemExit
allowed = ("app/", "tests/", "integrations/openclaw-anh-duong-core/")
seen, clean = set(), []
for item in files:
    if not isinstance(item, str): print("ERROR\0invalid_file_entry\0", end=""); raise SystemExit
    if item.startswith("/") or "\x00" in item or "\\" in item: print("ERROR\0invalid_file_path\0", end=""); raise SystemExit
    norm = os.path.normpath(item)
    if norm != item or norm.startswith("../") or norm == "..": print("ERROR\0path_traversal\0", end=""); raise SystemExit
    if not norm.startswith(allowed): print("ERROR\0path_outside_allowed_scope\0", end=""); raise SystemExit
    if norm not in seen: seen.add(norm); clean.append(norm)
print("OK\0" + message.strip() + "\0" + "\0".join(clean) + "\0", end="")
PY
)
rm -f -- "$REQUEST"
if [[ "${parsed[0]:-}" != "OK" ]]; then write_status "blocked" "${parsed[1]:-invalid_request}"; exit 0; fi
message="${parsed[1]}"; files=("${parsed[@]:2}")
cd "$REPO"
branch="$(git symbolic-ref --short -q HEAD || true)"
if [[ -z "$branch" ]]; then write_status "blocked" "detached_head"; exit 0; fi
for f in "${files[@]}"; do
  if [[ ! -e "$f" ]] && ! git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then write_status "blocked" "requested_path_missing:$f"; exit 0; fi
  if git diff --quiet -- "$f" && git diff --cached --quiet -- "$f"; then write_status "blocked" "requested_path_not_changed:$f"; exit 0; fi
done
mapfile -t staged_before < <(git diff --cached --name-only)
if ((${#staged_before[@]})); then
  for s in "${staged_before[@]}"; do
    found=0; for f in "${files[@]}"; do [[ "$s" == "$f" ]] && { found=1; break; }; done
    if (( found == 0 )); then write_status "blocked" "unrelated_preexisting_staged:$s"; exit 0; fi
  done
fi
git add -- "${files[@]}"
mapfile -t staged_after < <(git diff --cached --name-only)
if ((${#staged_after[@]} == 0)); then write_status "blocked" "nothing_staged"; exit 0; fi
for s in "${staged_after[@]}"; do
  found=0; for f in "${files[@]}"; do [[ "$s" == "$f" ]] && { found=1; break; }; done
  if (( found == 0 )); then write_status "blocked" "unrelated_staged_after_add:$s"; exit 0; fi
done
if ! git diff --cached --check; then write_status "failed" "git_diff_cached_check_failed"; exit 1; fi
if ! git commit -m "$message"; then write_status "failed" "git_commit_failed"; exit 1; fi
commit="$(git rev-parse HEAD)"
write_status "completed" "local_commit_created" "$commit"
HELPER

cat >"$TMPDIR_BOOT/$RUN_UNIT" <<EOF_SERVICE
[Unit]
Description=Scoped autonomous local commit for Ánh Dương Core

[Service]
Type=oneshot
User=${TARGET_USER}
Group=${TARGET_USER}
WorkingDirectory=${REPO}
ExecStart=${HELPER_PATH}
NoNewPrivileges=yes
PrivateTmp=no
PrivateNetwork=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${REPO} /tmp /run/anh-duong-core-git-commit
RuntimeDirectory=anh-duong-core-git-commit
RuntimeDirectoryMode=0755
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictAddressFamilies=AF_UNIX
EOF_SERVICE

cat >"$TMPDIR_BOOT/$WATCH_UNIT" <<EOF_PATH
[Unit]
Description=Watch for scoped Ánh Dương Core local-commit requests

[Path]
PathExists=${REQUEST_PATH}
Unit=${RUN_UNIT}

[Install]
WantedBy=multi-user.target
EOF_PATH

chmod 0755 "$TMPDIR_BOOT/anh-duong-core-git-commit-helper"
chmod 0644 "$TMPDIR_BOOT/$RUN_UNIT" "$TMPDIR_BOOT/$WATCH_UNIT"
bash -n "$TMPDIR_BOOT/anh-duong-core-git-commit-helper"
install -D -o root -g root -m 0755 "$TMPDIR_BOOT/anh-duong-core-git-commit-helper" "$HELPER_PATH"
systemd-analyze verify "$TMPDIR_BOOT/$RUN_UNIT" "$TMPDIR_BOOT/$WATCH_UNIT" >/dev/null
install -o root -g root -m 0644 "$TMPDIR_BOOT/$RUN_UNIT" "$RUN_PATH"
install -o root -g root -m 0644 "$TMPDIR_BOOT/$WATCH_UNIT" "$WATCH_PATH"
rm -f -- "$REQUEST_PATH"
systemctl daemon-reload
systemctl enable --now "$WATCH_UNIT"
systemctl is-active --quiet "$WATCH_UNIT" || die "$WATCH_UNIT failed to activate"
BOOTSTRAP_COMMITTED=1
cat <<EOF_DONE
AUTONOMOUS_CORE_GIT_COMMIT=READY
watch_unit=${WATCH_UNIT}
request_path=${REQUEST_PATH}
status_path=/run/anh-duong-core-git-commit/status.json
backup_dir=${BACKUP_DIR}
EOF_DONE
