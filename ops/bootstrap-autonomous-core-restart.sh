#!/usr/bin/env bash
set -Eeuo pipefail

# One-time bootstrap for autonomous, least-privilege restart of Ánh Dương Core.
# After installation, an unprivileged Codex session can request ONLY a restart
# of anh-duong-core.service by creating /tmp/anh-duong-core-restart.request
# containing exactly: restart

TARGET_USER="thadc"
TARGET_SERVICE="anh-duong-core.service"
WATCH_UNIT="anh-duong-core-autorestart.path"
RUN_UNIT="anh-duong-core-autorestart.service"
HELPER_PATH="/usr/local/libexec/anh-duong-core-restart-helper"
WATCH_PATH="/etc/systemd/system/${WATCH_UNIT}"
RUN_PATH="/etc/systemd/system/${RUN_UNIT}"
REQUEST_PATH="/tmp/anh-duong-core-restart.request"
STATUS_PATH="/run/anh-duong-core-restart.status"
HEALTH_URL="http://127.0.0.1:8790/health"
READY_URL="http://127.0.0.1:8790/ready"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="/var/backups/anh-duong-core-autorestart-${STAMP}"
SMOKE_TEST="${AUTORESTART_SMOKE:-1}"
BOOTSTRAP_COMMITTED=0

log() { printf '[autonomous-core-restart] %s\n' "$*"; }
die() { printf '[autonomous-core-restart] ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || die "run once as root"
id "$TARGET_USER" >/dev/null 2>&1 || die "user '$TARGET_USER' does not exist"
systemctl cat "$TARGET_SERVICE" >/dev/null 2>&1 || die "$TARGET_SERVICE not found"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v flock >/dev/null 2>&1 || die "flock is required"
command -v runuser >/dev/null 2>&1 || die "runuser is required"

# Refuse to bootstrap while production is already unhealthy.
curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null || die "precheck /health failed"
curl -fsS --max-time 5 "$READY_URL" >/dev/null || die "precheck /ready failed"

mkdir -p "$BACKUP_DIR"
for p in "$HELPER_PATH" "$WATCH_PATH" "$RUN_PATH"; do
  if [[ -e "$p" ]]; then
    cp -a -- "$p" "$BACKUP_DIR/$(basename "$p")"
  fi
done

TMPDIR_BOOT="$(mktemp -d /tmp/anh-duong-core-autorestart-bootstrap.XXXXXX)"
cleanup() { rm -rf -- "$TMPDIR_BOOT"; }
rollback_on_error() {
  local rc="$1"
  if (( rc != 0 )) && (( BOOTSTRAP_COMMITTED == 0 )); then
    log "bootstrap failed; restoring previous helper/unit state"
    systemctl disable --now "$WATCH_UNIT" >/dev/null 2>&1 || true
    for target in "$HELPER_PATH" "$WATCH_PATH" "$RUN_PATH"; do
      base="$(basename "$target")"
      if [[ -e "$BACKUP_DIR/$base" ]]; then
        cp -a -- "$BACKUP_DIR/$base" "$target"
      else
        rm -f -- "$target"
      fi
    done
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi
  cleanup
}
trap 'rc=$?; rollback_on_error "$rc"; exit "$rc"' EXIT

cat >"$TMPDIR_BOOT/anh-duong-core-restart-helper" <<'HELPER'
#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE="anh-duong-core.service"
REQUEST="/tmp/anh-duong-core-restart.request"
STATUS="/run/anh-duong-core-restart.status"
LOCK="/run/lock/anh-duong-core-restart.lock"
LAST="/run/anh-duong-core-restart.last"
EXPECTED_OWNER="thadc"
HEALTH_URL="http://127.0.0.1:8790/health"
READY_URL="http://127.0.0.1:8790/ready"
COOLDOWN_SECONDS=60
VERIFY_SECONDS=30

log() { logger -t anh-duong-core-restart-helper -- "$*"; }
write_status() {
  local outcome="$1" reason="$2" old_pid="$3" new_pid="$4"
  local tmp="${STATUS}.tmp.$$"
  umask 022
  printf '{"outcome":"%s","reason":"%s","old_pid":%s,"new_pid":%s,"timestamp":"%s"}\n' \
    "$outcome" "$reason" "${old_pid:-0}" "${new_pid:-0}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$tmp"
  chmod 0644 "$tmp"
  mv -f -- "$tmp" "$STATUS"
  log "outcome=$outcome reason=$reason old_pid=${old_pid:-0} new_pid=${new_pid:-0}"
}

exec 9>"$LOCK"
if ! flock -n 9; then
  write_status "blocked" "restart_already_in_progress" 0 0
  exit 0
fi

[[ -e "$REQUEST" ]] || exit 0

# Reject symlinks/non-regular files. This prevents the root helper from
# following attacker-controlled paths even though /tmp is writable.
if [[ -L "$REQUEST" || ! -f "$REQUEST" ]]; then
  rm -f -- "$REQUEST"
  write_status "blocked" "invalid_request_type" 0 0
  exit 0
fi

owner="$(stat -c '%U' -- "$REQUEST" 2>/dev/null || true)"
content="$(cat -- "$REQUEST" 2>/dev/null || true)"
rm -f -- "$REQUEST"

if [[ "$owner" != "$EXPECTED_OWNER" ]]; then
  write_status "blocked" "invalid_request_owner" 0 0
  exit 0
fi
if [[ "$content" != "restart" ]]; then
  write_status "blocked" "invalid_request_content" 0 0
  exit 0
fi

now="$(date +%s)"
if [[ -r "$LAST" ]]; then
  last="$(cat "$LAST" 2>/dev/null || echo 0)"
  if [[ "$last" =~ ^[0-9]+$ ]] && (( now - last < COOLDOWN_SECONDS )); then
    write_status "blocked" "cooldown_active" 0 0
    exit 0
  fi
fi
printf '%s\n' "$now" >"$LAST"
chmod 0644 "$LAST"

old_pid="$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null || echo 0)"
[[ "$old_pid" =~ ^[0-9]+$ ]] || old_pid=0

if ! systemctl restart "$SERVICE"; then
  write_status "failed" "systemctl_restart_failed" "$old_pid" 0
  exit 1
fi

for _ in $(seq 1 "$VERIFY_SECONDS"); do
  if [[ "$(systemctl is-active "$SERVICE" 2>/dev/null || true)" == "active" ]] \
     && curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null \
     && curl -fsS --max-time 2 "$READY_URL" >/dev/null; then
    new_pid="$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null || echo 0)"
    [[ "$new_pid" =~ ^[0-9]+$ ]] || new_pid=0
    write_status "completed" "restart_and_verify_passed" "$old_pid" "$new_pid"
    exit 0
  fi
  sleep 1
done

new_pid="$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null || echo 0)"
[[ "$new_pid" =~ ^[0-9]+$ ]] || new_pid=0
write_status "failed" "post_restart_health_ready_failed" "$old_pid" "$new_pid"
exit 1
HELPER

cat >"$TMPDIR_BOOT/$RUN_UNIT" <<EOF_SERVICE
[Unit]
Description=Autonomous fixed restart of Ánh Dương Core
Documentation=man:systemd.service(5)

[Service]
Type=oneshot
User=root
Group=root
ExecStart=${HELPER_PATH}
NoNewPrivileges=yes
PrivateTmp=no
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
EOF_SERVICE

cat >"$TMPDIR_BOOT/$WATCH_UNIT" <<EOF_PATH
[Unit]
Description=Watch for an Ánh Dương Core restart request
Documentation=man:systemd.path(5)

[Path]
PathExists=${REQUEST_PATH}
Unit=${RUN_UNIT}

[Install]
WantedBy=multi-user.target
EOF_PATH

chmod 0755 "$TMPDIR_BOOT/anh-duong-core-restart-helper"
chmod 0644 "$TMPDIR_BOOT/$RUN_UNIT" "$TMPDIR_BOOT/$WATCH_UNIT"

# Static verification before activating anything. The helper is installed first
# so systemd-analyze can validate the real ExecStart target; no unit is active yet.
bash -n "$TMPDIR_BOOT/anh-duong-core-restart-helper"
install -D -o root -g root -m 0755 "$TMPDIR_BOOT/anh-duong-core-restart-helper" "$HELPER_PATH"
systemd-analyze verify "$TMPDIR_BOOT/$RUN_UNIT" "$TMPDIR_BOOT/$WATCH_UNIT" >/dev/null

install -o root -g root -m 0644 "$TMPDIR_BOOT/$RUN_UNIT" "$RUN_PATH"
install -o root -g root -m 0644 "$TMPDIR_BOOT/$WATCH_UNIT" "$WATCH_PATH"
rm -f -- "$REQUEST_PATH" "$STATUS_PATH" /run/anh-duong-core-restart.last /run/lock/anh-duong-core-restart.lock

systemctl daemon-reload
systemctl enable --now "$WATCH_UNIT"
systemctl is-active --quiet "$WATCH_UNIT" || die "$WATCH_UNIT failed to activate"

if [[ "$SMOKE_TEST" == "1" ]]; then
  log "running one controlled restart smoke test"
  before_pid="$(systemctl show -p MainPID --value "$TARGET_SERVICE")"
  runuser -u "$TARGET_USER" -- bash -c "umask 077; printf 'restart\\n' > '$REQUEST_PATH'"

  deadline=$(( $(date +%s) + 45 ))
  while (( $(date +%s) < deadline )); do
    if [[ -r "$STATUS_PATH" ]] && grep -q '"outcome":"completed"' "$STATUS_PATH"; then
      break
    fi
    sleep 1
  done

  [[ -r "$STATUS_PATH" ]] || die "smoke test produced no status"
  grep -q '"outcome":"completed"' "$STATUS_PATH" || {
    cat "$STATUS_PATH" >&2 || true
    die "smoke restart failed"
  }
  curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null || die "post-smoke /health failed"
  curl -fsS --max-time 5 "$READY_URL" >/dev/null || die "post-smoke /ready failed"
  after_pid="$(systemctl show -p MainPID --value "$TARGET_SERVICE")"
  [[ "$before_pid" != "$after_pid" ]] || die "smoke restart did not change MainPID"
fi

BOOTSTRAP_COMMITTED=1

cat <<EOF_DONE
AUTONOMOUS_CORE_RESTART=READY
watch_unit=${WATCH_UNIT}
request_path=${REQUEST_PATH}
status_path=${STATUS_PATH}
backup_dir=${BACKUP_DIR}

After this one-time bootstrap, an unprivileged Codex session can request the
fixed restart without sudo or an approval model by writing exactly:
  restart
into ${REQUEST_PATH} as user ${TARGET_USER}.

The helper can restart ONLY ${TARGET_SERVICE}; it accepts no service name or
arbitrary command, applies a ${TARGET_USER}-owner check, lock, 60s cooldown,
and post-restart /health + /ready verification.
EOF_DONE
