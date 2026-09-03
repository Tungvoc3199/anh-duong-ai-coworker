#!/bin/bash -p
set -euo pipefail
PATH="/usr/bin:/bin"
export PATH
[[ "${EUID}" -eq 0 ]] || { echo "INSTALL=BLOCKED REASON=ROOT_REQUIRED"; exit 77; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
TARGET=/usr/local/libexec/anh-duong
unset CDPATH BASH_ENV ENV GCC_EXEC_PREFIX COMPILER_PATH GCC_SPECS LIBRARY_PATH CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH OBJC_INCLUDE_PATH TMPDIR TMP TEMP
TMP="$(/usr/bin/mktemp -d -p /tmp)"
trap 'rm -rf "$TMP"' EXIT
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C LANG=C /usr/bin/gcc -static -std=c11 -O2 -Wall -Wextra -Werror -o "$TMP/coding-preflight-controller" "$ROOT/scripts/agent/coding_preflight_controller.c"
file "$TMP/coding-preflight-controller" | grep -q 'statically linked'
install -d -o root -g root -m 0755 "$TARGET"
install -o root -g root -m 0755 "$TMP/coding-preflight-controller" "$TARGET/coding-preflight-controller"
install -o root -g root -m 0755 "$ROOT/scripts/coding_preflight.sh" "$TARGET/coding_preflight.sh"
cmp -s "$TMP/coding-preflight-controller" "$TARGET/coding-preflight-controller"
cmp -s "$ROOT/scripts/coding_preflight.sh" "$TARGET/coding_preflight.sh"
stat -c '%U:%G %a %n' "$TARGET/coding-preflight-controller" "$TARGET/coding_preflight.sh"
sha256sum "$TARGET/coding-preflight-controller" "$TARGET/coding_preflight.sh"
