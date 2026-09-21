#!/usr/bin/env bash
set -euo pipefail

SERVICE="${ANH_DUONG_RUNTIME_SERVICE:-anh-duong-core.service}"
ENV_FILE="${ANH_DUONG_RUNTIME_ENV_FILE:-/home/thadc/.config/anh-duong-core/.env}"
CHECKPOINT_ROOT="${ANH_DUONG_CHECKPOINT_ROOT:-/mnt/f/AIOS/anh-duong-checkpoints}"

prop() {
  systemctl show "${SERVICE}" --property="$1" --value 2>/dev/null || true
}

env_value() {
  local key="$1" value
  [[ -r "${ENV_FILE}" ]] || return 0
  value="$(awk -F= -v key="${key}" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "${ENV_FILE}")"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "${value}"
}

overall="PASS"
active="$(prop ActiveState)"
sub="$(prop SubState)"
main_pid="$(prop MainPID)"
working_dir="$(prop WorkingDirectory)"
exec_start="$(prop ExecStart)"
runtime_cwd=""
process_cmdline=""
if [[ "${main_pid}" =~ ^[1-9][0-9]*$ && -e "/proc/${main_pid}/cwd" ]]; then
  runtime_cwd="$(readlink -f "/proc/${main_pid}/cwd" 2>/dev/null || true)"
  if [[ -r "/proc/${main_pid}/cmdline" ]]; then
    process_cmdline="$(tr '\0' ' ' < "/proc/${main_pid}/cmdline" 2>/dev/null || true)"
  fi
fi

port="$(printf '%s\n' "${process_cmdline}" | sed -nE 's/.*--port[= ]+([0-9]+).*/\1/p' | head -n 1)"
port_source="process_cmdline"
if [[ -z "${port}" ]]; then
  port="$(printf '%s\n' "${exec_start}" | sed -nE 's/.*--port[= ]+([0-9]+).*/\1/p' | head -n 1)"
  port_source="systemd_execstart"
fi
base_url=""
if [[ -n "${port}" ]]; then
  base_url="http://127.0.0.1:${port}"
fi

data_root="$(env_value ANH_DUONG_DATA_ROOT)"
[[ -n "${data_root}" ]] || data_root="/mnt/f/AIOS/anh-duong-data"
database_url="$(env_value ANH_DUONG_DATABASE_URL)"
db_path=""
case "${database_url}" in
  sqlite+pysqlite:///*) db_path="${database_url#sqlite+pysqlite:///}" ;;
esac

release_binding="FAIL"
if [[ -n "${working_dir}" && -n "${runtime_cwd}" && "${working_dir}" == "${runtime_cwd}" ]]; then
  release_binding="PASS"
fi
health="FAIL"
ready="FAIL"
health_body=""
ready_body=""
if [[ -n "${base_url}" ]]; then
  if health_body="$(curl -fsS --max-time 5 "${base_url}/health" 2>/dev/null)"; then
    health="PASS"
  fi
  if ready_body="$(curl -fsS --max-time 5 "${base_url}/ready" 2>/dev/null)"; then
    ready="PASS"
  fi
fi

data_root_state="MISSING"
[[ -d "${data_root}" ]] && data_root_state="PRESENT"
db_state="UNKNOWN"
if [[ -n "${db_path}" ]]; then
  db_state="MISSING"
  [[ -f "${db_path}" ]] && db_state="PRESENT"
fi
checkpoint_state="MISSING"
[[ -d "${CHECKPOINT_ROOT}" ]] && checkpoint_state="PRESENT"

openclaw_name="ad-golden-openclaw-prod"
openclaw_state="NOT_FOUND"
openclaw_image=""
openclaw_health="FAIL"
if command -v docker >/dev/null 2>&1; then
  openclaw_line="$(docker ps --filter "name=^${openclaw_name}$" --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null | head -n 1 || true)"
  if [[ -n "${openclaw_line}" ]]; then
    IFS='|' read -r _ openclaw_state openclaw_image <<<"${openclaw_line}"
    case "${openclaw_state}" in
      *"(healthy)"*) openclaw_health="PASS" ;;
    esac
  fi
fi

for critical in   "${active}:active"   "${sub}:running"   "${release_binding}:PASS"   "${health}:PASS"   "${ready}:PASS"   "${data_root_state}:PRESENT"   "${db_state}:PRESENT"   "${checkpoint_state}:PRESENT"   "${openclaw_health}:PASS"
do
  [[ "${critical%%:*}" == "${critical##*:}" ]] || overall="FAIL"
done

printf 'RUNTIME_TRUTH=%s\n' "${overall}"
printf 'SERVICE=%s\n' "${SERVICE}"
printf 'SERVICE_STATE=%s/%s\n' "${active:-UNKNOWN}" "${sub:-UNKNOWN}"
printf 'MAIN_PID=%s\n' "${main_pid:-UNKNOWN}"
printf 'PRODUCTION_RELEASE=%s\n' "${runtime_cwd:-UNKNOWN}"
printf 'SYSTEMD_WORKING_DIRECTORY=%s\n' "${working_dir:-UNKNOWN}"
printf 'RELEASE_BINDING=%s\n' "${release_binding}"
printf 'CORE_BASE_URL=%s\n' "${base_url:-UNKNOWN}"
printf 'CORE_PORT_SOURCE=%s\n' "${port_source:-UNKNOWN}"
printf 'CORE_HEALTH=%s %s\n' "${health}" "${health_body}"
printf 'CORE_READY=%s %s\n' "${ready}" "${ready_body}"
printf 'DATA_ROOT=%s [%s]\n' "${data_root}" "${data_root_state}"
printf 'DATABASE_PATH=%s [%s]\n' "${db_path:-UNKNOWN}" "${db_state}"
printf 'CHECKPOINT_ROOT=%s [%s]\n' "${CHECKPOINT_ROOT}" "${checkpoint_state}"
printf 'OPENCLAW=%s [%s]\n' "${openclaw_name}" "${openclaw_state}"
printf 'OPENCLAW_HEALTH=%s\n' "${openclaw_health}"
printf 'OPENCLAW_IMAGE=%s\n' "${openclaw_image:-UNKNOWN}"
printf 'NOTE=Static README/AGENTS values never override this fresh runtime probe.\n'

[[ "${overall}" == "PASS" ]]
