#!/bin/bash -p
set -u -o pipefail

STARTUP_ENV_UNTRUSTED=0
[[ "$-" == *p* ]] || STARTUP_ENV_UNTRUSTED=1
unset BASH_ENV ENV CDPATH GLOBIGNORE
for startup_var in "${!LD_@}"; do
    STARTUP_ENV_UNTRUSTED=1
    unset "$startup_var"
done
PATH="/usr/bin:/bin"
export PATH

unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE
unset GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_GRAFT_FILE
unset GIT_REPLACE_REF_BASE GIT_SHALLOW_FILE GIT_PREFIX GIT_CONFIG
unset GIT_CONFIG_PARAMETERS GIT_EXTERNAL_DIFF GIT_CEILING_DIRECTORIES
unset GIT_DISCOVERY_ACROSS_FILESYSTEM GIT_NAMESPACE GIT_IMPLICIT_WORK_TREE GIT_EXEC_PATH
unset GIT_NO_REPLACE_OBJECTS TAR_OPTIONS PYTHONPATH PYTHONHOME
while IFS= read -r trace_var; do
    unset "$trace_var"
done < <(compgen -A variable GIT_TRACE)
export GIT_NO_REPLACE_OBJECTS=1
export GIT_OPTIONAL_LOCKS=0
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_SYSTEM=/dev/null
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=core.fsmonitor
export GIT_CONFIG_VALUE_0=false

EXPECTED_WORKSPACE=""
REQUIRE_ISOLATION=0
REQUIRE_CLEAN=0
REQUIRE_UPSTREAM=0
ALLOW_DETACHED=0
EXPECTED_UPSTREAM=""
EXPECTED_PUSH_REMOTE=""
EXPECTED_PUSH_TARGET=""
EXPECTED_PUSH_URL=""
EXPECTED_GIT_NAME=""
EXPECTED_GIT_EMAIL=""
CLEANUP_TARGET=""
DESTRUCTIVE_CLEANUP=0
ARCHIVE_REF=""
BUNDLE_PATH=""
TRACKED_PATCH=""
UNTRACKED_ARCHIVE=""
CHECKSUM_EVIDENCE=""
COVERAGE_EVIDENCE=""
PROC_ROOT="/proc"
PROC_ROOT_OVERRIDE="${CODING_PREFLIGHT_PROC_ROOT:-}"
TEST_MODE="${CODING_PREFLIGHT_TEST_MODE:-0}"
WSL_EXE="/mnt/c/Windows/System32/wsl.exe"
WSL_EXE_OVERRIDE="${CODING_PREFLIGHT_WSL_EXE:-}"

PREFLIGHT="BLOCKED"
WORKSPACE="UNKNOWN"
EXPECTED_REALPATH="UNKNOWN"
HEAD="UNKNOWN"
BRANCH="UNKNOWN"
UPSTREAM="NONE"
PUSH_REMOTE="NONE"
PUSH_TARGET="NONE"
EFFECTIVE_PUSH_URL="NONE"
push_fields=""
DIVERGENCE_AHEAD="NA"
DIVERGENCE_BEHIND="NA"
DIRTY_TRACKED="0"
DIRTY_UNTRACKED="0"
UNMERGED="0"
WORKTREE_REGISTERED="0"
WORKTREE_PRUNABLE="0"
ISOLATED_WORKTREE="0"
BRANCH_OTHER_WORKTREE="NONE"
CLEANUP_TARGET_REALPATH="NONE"
CLEANUP_TARGET_REGISTERED="0"
CLEANUP_TARGET_PRUNABLE="0"
LIVE_PROCESS_COUNT="0"
LIVE_PROCESS_STATE="NOT_CHECKED"
ARCHIVE_REQUIREMENT_STATE="NOT_APPLICABLE"
TARGET_HEAD="NA"
TARGET_DIRTY_TRACKED="NA"
TARGET_DIRTY_UNTRACKED="NA"
TARGET_BRANCH="NA"
TARGET_GIT_DIR_REALPATH="NA"
INVALID_DETAIL="NONE"
reasons=()

add_reason() {
    local reason="$1" existing
    for existing in "${reasons[@]}"; do
        [[ "$existing" == "$reason" ]] && return 0
    done
    reasons+=("$reason")
}

if [[ "$STARTUP_ENV_UNTRUSTED" -eq 1 ]]; then
    add_reason "UNTRUSTED_STARTUP_ENV"
fi

join_reasons() {
    local IFS=,
    printf '%s' "${reasons[*]:-NONE}"
}

safe_value() {
    local value="$1" out="" ch encoded i ord
    local LC_ALL=C
    for ((i=0; i<${#value}; i++)); do
        ch="${value:i:1}"
        printf -v ord '%d' "'$ch"
        if [[ "$ch" == '%' || "$ch" == '=' || "$ord" -lt 32 || "$ord" -ge 127 ]]; then
            printf -v encoded '%%%02X' "$ord"
            out+="$encoded"
        else
            out+="$ch"
        fi
    done
    printf '%s' "$out"
}

emit_line() {
    printf '%s=%s\n' "$1" "$(safe_value "$2")"
}

emit_result() {
    emit_line PREFLIGHT "$PREFLIGHT"
    emit_line REASONS "$(join_reasons)"
    emit_line WORKSPACE "$WORKSPACE"
    emit_line EXPECTED_WORKSPACE "$EXPECTED_REALPATH"
    emit_line HEAD "$HEAD"
    emit_line BRANCH "$BRANCH"
    emit_line UPSTREAM "$UPSTREAM"
    emit_line PUSH_REMOTE "$PUSH_REMOTE"
    emit_line PUSH_TARGET "$PUSH_TARGET"
    emit_line DIVERGENCE_AHEAD "$DIVERGENCE_AHEAD"
    emit_line DIVERGENCE_BEHIND "$DIVERGENCE_BEHIND"
    emit_line DIRTY_TRACKED "$DIRTY_TRACKED"
    emit_line DIRTY_UNTRACKED "$DIRTY_UNTRACKED"
    emit_line UNMERGED "$UNMERGED"
    emit_line ISOLATED_WORKTREE "$ISOLATED_WORKTREE"
    emit_line WORKTREE_REGISTERED "$WORKTREE_REGISTERED"
    emit_line WORKTREE_PRUNABLE "$WORKTREE_PRUNABLE"
    emit_line BRANCH_OTHER_WORKTREE "$BRANCH_OTHER_WORKTREE"
    emit_line CLEANUP_TARGET "$CLEANUP_TARGET_REALPATH"
    emit_line CLEANUP_TARGET_REGISTERED "$CLEANUP_TARGET_REGISTERED"
    emit_line CLEANUP_TARGET_PRUNABLE "$CLEANUP_TARGET_PRUNABLE"
    emit_line LIVE_PROCESS_COUNT "$LIVE_PROCESS_COUNT"
    emit_line LIVE_PROCESS_STATE "$LIVE_PROCESS_STATE"
    emit_line ARCHIVE_REQUIREMENT_STATE "$ARCHIVE_REQUIREMENT_STATE"
    emit_line TARGET_HEAD "$TARGET_HEAD"
    emit_line TARGET_DIRTY_TRACKED "$TARGET_DIRTY_TRACKED"
    emit_line TARGET_DIRTY_UNTRACKED "$TARGET_DIRTY_UNTRACKED"
    emit_line INVALID_DETAIL "$INVALID_DETAIL"
}

invalid_invocation() {
    INVALID_DETAIL="$1"
    add_reason "INVALID_INVOCATION"
    PREFLIGHT="BLOCKED"
    emit_result
    exit 64
}

validate_git_operation() {
    [[ "${#GIT_EXEC_ARGS[@]}" -gt 0 ]] || return 0

    local -a git_args=("${GIT_EXEC_ARGS[@]:1}")
    local subcommand="" arg builtin
    local subcommand_index=-1 index builtin_ok=0

    for ((index=0; index<${#git_args[@]}; index++)); do
        arg="${git_args[index]}"
        if [[ "$arg" == "--" ]]; then
            (( index + 1 < ${#git_args[@]} )) || invalid_invocation "git_subcommand_required"
            subcommand_index=$((index + 1))
            subcommand="${git_args[subcommand_index]}"
            break
        fi
        if [[ "$arg" != -* || "$arg" == "-" ]]; then
            subcommand_index=$index
            subcommand="$arg"
            break
        fi
        case "$arg" in
            -C|-c|--git-dir|--work-tree|--namespace|--exec-path|--super-prefix|--config-env|--bare)
                invalid_invocation "git_retarget_option"
                ;;
            -C?*|-c?*|--git-dir=*|--work-tree=*|--namespace=*|--exec-path=*|--super-prefix=*|--config-env=*)
                invalid_invocation "git_retarget_option"
                ;;
        esac
    done

    [[ -n "$subcommand" ]] || invalid_invocation "git_subcommand_required"

    while IFS= read -r builtin; do
        if [[ "$builtin" == "$subcommand" ]]; then
            builtin_ok=1
            break
        fi
    done < <(/usr/bin/git --list-cmds=builtins 2>/dev/null)
    [[ "$builtin_ok" -eq 1 ]] || invalid_invocation "git_subcommand_not_builtin"

    if [[ "$subcommand" == "push" ]]; then
        for ((index=subcommand_index + 1; index<${#git_args[@]}; index++)); do
            arg="${git_args[index]}"
            if [[ "$arg" == --rep* ]]; then
                invalid_invocation "git_push_repository_override"
            fi
            if [[ "$arg" == "--" ]]; then
                (( index + 1 >= ${#git_args[@]} )) || invalid_invocation "git_push_repository_override"
                break
            fi
            if [[ "$arg" != -* || "$arg" == "-" ]]; then
                invalid_invocation "git_push_repository_override"
            fi
        done
    fi
}

usage() {
    cat <<'EOF'
Usage: coding_preflight.sh --expected-workspace PATH [policy flags] [-- git [git arguments]]

Coding policy flags:
  --require-isolation
  --require-clean
  --require-upstream
  --expected-upstream REF
  --expected-push-remote NAME
  --expected-push-target REMOTE:REF
  --expected-push-url URL
  --expected-git-name NAME
  --expected-git-email EMAIL
  --allow-detached

Cleanup safety flags:
  --cleanup-target PATH
  --destructive-cleanup
EOF
}
GIT_EXEC_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --expected-workspace|--expected-upstream|--expected-push-remote|--expected-push-target|--expected-push-url|--expected-git-name|--expected-git-email|--cleanup-target|--archive-ref|--bundle|--tracked-patch|--untracked-archive|--checksum-evidence|--coverage-evidence)
            [[ $# -ge 2 ]] || invalid_invocation "missing_value_for_$1"
            key="$1"
            value="$2"
            shift 2
            case "$key" in
                --expected-workspace) EXPECTED_WORKSPACE="$value" ;;
                --expected-upstream) EXPECTED_UPSTREAM="$value" ;;
                --expected-push-remote) EXPECTED_PUSH_REMOTE="$value" ;;
                --expected-push-target) EXPECTED_PUSH_TARGET="$value" ;;
                --expected-push-url) EXPECTED_PUSH_URL="$value" ;;
                --expected-git-name) EXPECTED_GIT_NAME="$value" ;;
                --expected-git-email) EXPECTED_GIT_EMAIL="$value" ;;
                --cleanup-target) CLEANUP_TARGET="$value" ;;
                --archive-ref) ARCHIVE_REF="$value" ;;
                --bundle) BUNDLE_PATH="$value" ;;
                --tracked-patch) TRACKED_PATCH="$value" ;;
                --untracked-archive) UNTRACKED_ARCHIVE="$value" ;;
                --checksum-evidence) CHECKSUM_EVIDENCE="$value" ;;
                --coverage-evidence) COVERAGE_EVIDENCE="$value" ;;
            esac
            ;;
        --require-isolation) REQUIRE_ISOLATION=1; shift ;;
        --require-clean) REQUIRE_CLEAN=1; shift ;;
        --require-upstream) REQUIRE_UPSTREAM=1; shift ;;
        --allow-detached) ALLOW_DETACHED=1; shift ;;
        --destructive-cleanup) DESTRUCTIVE_CLEANUP=1; shift ;;
        --)
            shift
            [[ $# -ge 2 && "$1" == "git" ]] || invalid_invocation "git_operation_required"
            GIT_EXEC_ARGS=("$@")
            break
            ;;
        --help|-h) usage; exit 0 ;;
        *) invalid_invocation "unknown_argument_$1" ;;
    esac
done
[[ -n "$EXPECTED_WORKSPACE" ]] || invalid_invocation "expected_workspace_required"
validate_git_operation
if [[ "$DESTRUCTIVE_CLEANUP" -eq 1 && -z "$CLEANUP_TARGET" ]]; then
    invalid_invocation "cleanup_target_required_for_destructive_cleanup"
fi
if [[ "$REQUIRE_UPSTREAM" -eq 1 || -n "$EXPECTED_PUSH_REMOTE" || -n "$EXPECTED_PUSH_TARGET" ]]; then
    [[ -n "$EXPECTED_GIT_NAME" && -n "$EXPECTED_GIT_EMAIL" ]] || add_reason "EXPECTED_GIT_IDENTITY_REQUIRED"
fi
if [[ -n "$EXPECTED_PUSH_REMOTE" || -n "$EXPECTED_PUSH_TARGET" ]]; then
    [[ -n "$EXPECTED_PUSH_URL" ]] || add_reason "EXPECTED_PUSH_URL_REQUIRED"
fi

repo_root_raw="$(git rev-parse --show-toplevel 2>/dev/null)" || invalid_invocation "not_a_git_worktree"
WORKSPACE="$(realpath -e "$repo_root_raw" 2>/dev/null)" || invalid_invocation "workspace_realpath_failed"
EXPECTED_REALPATH="$(realpath -e "$EXPECTED_WORKSPACE" 2>/dev/null || true)"
if [[ -z "$EXPECTED_REALPATH" ]]; then
    EXPECTED_REALPATH="$(realpath -m "$EXPECTED_WORKSPACE" 2>/dev/null || printf '%s' "$EXPECTED_WORKSPACE")"
    add_reason "EXPECTED_WORKSPACE_INVALID"
elif [[ "$WORKSPACE" != "$EXPECTED_REALPATH" ]]; then
    add_reason "WORKSPACE_MISMATCH"
fi

if [[ -n "$PROC_ROOT_OVERRIDE" ]]; then
    if [[ "$TEST_MODE" == "1" && "$WORKSPACE" == /tmp/* ]]; then
        PROC_ROOT="$PROC_ROOT_OVERRIDE"
        add_reason "TEST_PROC_OVERRIDE_NON_AUTHORIZING"
    else
        add_reason "PROC_ROOT_OVERRIDE_FORBIDDEN"
    fi
fi
if [[ -n "$WSL_EXE_OVERRIDE" ]]; then
    if [[ "$TEST_MODE" == "1" && "$WORKSPACE" == /tmp/* ]]; then
        WSL_EXE="$WSL_EXE_OVERRIDE"
        add_reason "TEST_WSL_ORACLE_OVERRIDE_NON_AUTHORIZING"
    else
        add_reason "WSL_ORACLE_OVERRIDE_FORBIDDEN"
    fi
fi

HEAD="$(git rev-parse HEAD 2>/dev/null)" || invalid_invocation "head_unavailable"
branch_value="$(git symbolic-ref --quiet --short HEAD 2>/dev/null)"
branch_rc=$?
if [[ "$branch_rc" -eq 0 && -n "$branch_value" ]]; then
    BRANCH="$branch_value"
elif [[ "$branch_rc" -eq 1 ]]; then
    BRANCH="DETACHED"
    [[ "$ALLOW_DETACHED" -eq 1 ]] || add_reason "DETACHED_HEAD"
else
    BRANCH="UNKNOWN"
    add_reason "BRANCH_PROBE_FAILED"
fi

identity_name="$(git config --get user.name 2>/dev/null)"
identity_name_rc=$?
identity_email="$(git config --get user.email 2>/dev/null)"
identity_email_rc=$?
if [[ "$identity_name_rc" -gt 1 || "$identity_email_rc" -gt 1 ]]; then
    add_reason "GIT_IDENTITY_PROBE_FAILED"
elif [[ "$identity_name_rc" -ne 0 || "$identity_email_rc" -ne 0 || -z "${identity_name//[[:space:]]/}" || ! "$identity_email" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]]; then
    add_reason "GIT_IDENTITY_INVALID"
fi
if [[ -n "$EXPECTED_GIT_NAME" && "$identity_name" != "$EXPECTED_GIT_NAME" ]] || [[ -n "$EXPECTED_GIT_EMAIL" && "$identity_email" != "$EXPECTED_GIT_EMAIL" ]]; then
    add_reason "GIT_IDENTITY_MISMATCH"
fi

git_dir="$(git rev-parse --path-format=absolute --git-dir 2>/dev/null)" || invalid_invocation "git_dir_unavailable"
git_common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || invalid_invocation "git_common_unavailable"
if [[ "$git_dir" != "$git_common" ]]; then
    ISOLATED_WORKTREE="1"
fi
if [[ "$REQUIRE_ISOLATION" -eq 1 && "$ISOLATED_WORKTREE" -ne 1 ]]; then
    add_reason "NOT_ISOLATED_WORKTREE"
fi
if [[ "$REQUIRE_ISOLATION" -eq 1 && "$BRANCH" == "main" ]]; then
    add_reason "MAIN_NOT_ISOLATED"
fi
if [[ "$BRANCH" != "DETACHED" && "$BRANCH" != "UNKNOWN" ]]; then
    upstream_value="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"
    upstream_rc=$?
    if [[ "$upstream_rc" -eq 0 && -n "$upstream_value" ]]; then
        UPSTREAM="$upstream_value"
        divergence_raw="$(git rev-list --left-right --count "HEAD...$UPSTREAM" 2>/dev/null)"
        divergence_rc=$?
        if [[ "$divergence_rc" -eq 0 ]] && read -r DIVERGENCE_AHEAD DIVERGENCE_BEHIND <<<"$divergence_raw" && \
            [[ "$DIVERGENCE_AHEAD" =~ ^[0-9]+$ && "$DIVERGENCE_BEHIND" =~ ^[0-9]+$ ]]; then
            :
        else
            UPSTREAM="INVALID"
            DIVERGENCE_AHEAD="NA"
            DIVERGENCE_BEHIND="NA"
            add_reason "DIVERGENCE_PROBE_FAILED"
        fi
    else
        configured_remote="$(git config --get "branch.$BRANCH.remote" 2>/dev/null)"
        configured_remote_rc=$?
        configured_merge="$(git config --get "branch.$BRANCH.merge" 2>/dev/null)"
        configured_merge_rc=$?
        if [[ "$configured_remote_rc" -gt 1 || "$configured_merge_rc" -gt 1 ]]; then
            UPSTREAM="INVALID"
            add_reason "UPSTREAM_CONFIG_PROBE_FAILED"
        elif [[ "$configured_remote_rc" -eq 0 || "$configured_merge_rc" -eq 0 ]]; then
            UPSTREAM="INVALID"
            add_reason "UPSTREAM_PROBE_FAILED"
        else
            UPSTREAM="NONE"
        fi
    fi

    push_fields="$(git for-each-ref --format='%(push:remotename)|%(push:short)|%(push:remoteref)' "refs/heads/$BRANCH" 2>/dev/null)"
    push_probe_rc=$?
    if [[ "$push_probe_rc" -ne 0 ]]; then
        add_reason "PUSH_PROBE_FAILED"
    elif [[ -n "$push_fields" ]]; then
        IFS='|' read -r push_remote push_short push_remote_ref <<<"$push_fields"
        if [[ -n "$push_remote" ]]; then
            PUSH_REMOTE="$push_remote"
            mirror_value="$(git config --bool --get "remote.$PUSH_REMOTE.mirror" 2>/dev/null)"
            mirror_rc=$?
            if [[ "$mirror_rc" -gt 1 ]]; then
                add_reason "PUSH_CONFIG_PROBE_FAILED"
            elif [[ "$mirror_rc" -eq 0 && "$mirror_value" == "true" ]]; then
                add_reason "MIRROR_PUSH_REMOTE"
            fi
            if [[ -n "$push_remote_ref" ]]; then
                PUSH_TARGET="$PUSH_REMOTE:$push_remote_ref"
            elif [[ -n "$push_short" && "$push_short" == "$PUSH_REMOTE/"* ]]; then
                PUSH_TARGET="$PUSH_REMOTE:refs/heads/${push_short#"$PUSH_REMOTE/"}"
            fi
            follow_tags_value="$(git config --bool --get push.followTags 2>/dev/null)"
            follow_tags_rc=$?
            if [[ "$follow_tags_rc" -gt 1 ]]; then
                add_reason "PUSH_CONFIG_PROBE_FAILED"
            elif [[ "$follow_tags_rc" -eq 0 && "$follow_tags_value" == "true" ]]; then
                add_reason "PUSH_FOLLOW_TAGS_ENABLED"
            fi
            effective_url_probe="$(git config -z --get-all "remote.$PUSH_REMOTE.pushurl" 2>/dev/null | awk -v RS='\0' 'BEGIN{count=0; empty=0} {count++; if(length($0)==0) empty=1} END{printf "%d|%d", count, empty}')"
            effective_url_rc=$?
            if [[ "$effective_url_rc" -eq 1 ]]; then
                effective_url_probe="$(git config -z --get-all "remote.$PUSH_REMOTE.url" 2>/dev/null | awk -v RS='\0' 'BEGIN{count=0; empty=0} {count++; if(length($0)==0) empty=1} END{printf "%d|%d", count, empty}')"
                effective_url_rc=$?
            fi
            if [[ "$effective_url_rc" -gt 1 ]]; then
                add_reason "PUSH_CONFIG_PROBE_FAILED"
            elif [[ "$effective_url_rc" -eq 1 ]]; then
                add_reason "PUSH_URL_MISSING"
            else
                IFS='|' read -r effective_url_count effective_url_empty <<<"$effective_url_probe"
                if [[ ! "$effective_url_count" =~ ^[0-9]+$ || ! "$effective_url_empty" =~ ^[01]$ ]]; then
                    add_reason "PUSH_CONFIG_PROBE_FAILED"
                else
                    [[ "$effective_url_count" -eq 0 ]] && add_reason "PUSH_URL_MISSING"
                    [[ "$effective_url_empty" -ne 0 ]] && add_reason "EMPTY_PUSH_URL"
                    [[ "$effective_url_count" -gt 1 ]] && add_reason "MULTIPLE_PUSH_URLS"
                    if [[ "$effective_url_count" -eq 1 && "$effective_url_empty" -eq 0 ]]; then
                        EFFECTIVE_PUSH_URL="$(git remote get-url --push "$PUSH_REMOTE" 2>/dev/null)"
                        effective_push_url_rc=$?
                        if [[ "$effective_push_url_rc" -ne 0 || -z "$EFFECTIVE_PUSH_URL" ]]; then
                            add_reason "PUSH_CONFIG_PROBE_FAILED"
                        elif [[ -n "$EXPECTED_PUSH_URL" && "$EFFECTIVE_PUSH_URL" != "$EXPECTED_PUSH_URL" ]]; then
                            add_reason "PUSH_URL_MISMATCH"
                        fi
                    fi
                fi
            fi
            push_spec_count=0
            push_spec_hazard=0
            push_spec_wildcard=0
            exec {push_spec_fd}< <(git config -z --get-all "remote.$PUSH_REMOTE.push" 2>/dev/null)
            push_spec_pid=$!
            while IFS= read -r -d '' push_spec <&"$push_spec_fd"; do
                push_spec_count=$((push_spec_count + 1))
                if [[ -z "$push_spec" || "$push_spec" == +* || "$push_spec" == :* || "$push_spec" == ^* ]]; then
                    push_spec_hazard=1
                fi
                [[ "$push_spec" == *'*'* ]] && push_spec_wildcard=1
                if [[ "$push_spec" == *:* ]]; then
                    push_spec_source="${push_spec%%:*}"
                    push_spec_destination="${push_spec#*:}"
                    if [[ -z "$push_spec_source" || -z "$push_spec_destination" ]]; then
                        push_spec_hazard=1
                    fi
                fi
            done
            exec {push_spec_fd}<&-
            wait "$push_spec_pid"
            push_config_rc=$?
            if [[ "$push_config_rc" -gt 1 ]]; then
                add_reason "PUSH_CONFIG_PROBE_FAILED"
            elif [[ "$push_config_rc" -eq 0 ]]; then
                [[ "$push_spec_hazard" -ne 0 ]] && add_reason "HAZARDOUS_PUSH_REFSPEC"
                if [[ "$push_spec_count" -ne 1 || "$push_spec_wildcard" -ne 0 ]]; then
                    add_reason "MULTIPLE_PUSH_TARGETS"
                fi
            else
                push_default="$(git config --get push.default 2>/dev/null)"
                push_default_rc=$?
                if [[ "$push_default_rc" -gt 1 ]]; then
                    add_reason "PUSH_CONFIG_PROBE_FAILED"
                elif [[ "$push_default" == "matching" ]]; then
                    add_reason "MULTIPLE_PUSH_TARGETS"
                fi
            fi
        fi
    fi
fi

CODING_POLICY_IDENTITY_NAME="$identity_name"
CODING_POLICY_IDENTITY_EMAIL="$identity_email"
CODING_POLICY_UPSTREAM="$UPSTREAM"
CODING_POLICY_AHEAD="$DIVERGENCE_AHEAD"
CODING_POLICY_BEHIND="$DIVERGENCE_BEHIND"
CODING_POLICY_PUSH_FIELDS="$push_fields"
CODING_POLICY_PUSH_URL="$EFFECTIVE_PUSH_URL"
snapshot_coding_config() {
    local local_sha local_rc worktree_enabled worktree_enabled_rc
    local worktree_sha="DISABLED" worktree_rc
    local_sha="$(git config --local -z --list 2>/dev/null | sha256sum | awk '{print $1}')"
    local_rc=$?
    [[ "$local_rc" -eq 0 && "$local_sha" =~ ^[0-9a-fA-F]{64}$ ]] || return 1
    worktree_enabled="$(git config --bool --get extensions.worktreeConfig 2>/dev/null)"
    worktree_enabled_rc=$?
    [[ "$worktree_enabled_rc" -le 1 ]] || return 1
    if [[ "$worktree_enabled_rc" -eq 0 && "$worktree_enabled" == "true" ]]; then
        worktree_sha="$(git config --worktree -z --list 2>/dev/null | sha256sum | awk '{print $1}')"
        worktree_rc=$?
        [[ "$worktree_rc" -eq 0 && "$worktree_sha" =~ ^[0-9a-fA-F]{64}$ ]] || return 1
    fi
    printf '%s|%s' "$local_sha" "$worktree_sha"
}
CODING_CONFIG_SHA="$(snapshot_coding_config)"
coding_config_rc=$?
if [[ "$coding_config_rc" -ne 0 ]]; then
    add_reason "CODING_POLICY_PROBE_FAILED"
fi

if [[ "$REQUIRE_UPSTREAM" -eq 1 && ( "$UPSTREAM" == "NONE" || "$UPSTREAM" == "INVALID" ) ]]; then
    add_reason "MISSING_OR_INVALID_UPSTREAM"
fi
if [[ "$REQUIRE_UPSTREAM" -eq 1 && "$DIVERGENCE_BEHIND" =~ ^[0-9]+$ && "$DIVERGENCE_BEHIND" -gt 0 ]]; then
    add_reason "UPSTREAM_BEHIND"
    if [[ "$DIVERGENCE_AHEAD" =~ ^[0-9]+$ && "$DIVERGENCE_AHEAD" -gt 0 ]]; then
        add_reason "UPSTREAM_DIVERGED"
    fi
fi
if [[ -n "$EXPECTED_UPSTREAM" && "$UPSTREAM" != "$EXPECTED_UPSTREAM" ]]; then
    add_reason "UPSTREAM_MISMATCH"
fi
if [[ -n "$EXPECTED_PUSH_REMOTE" && "$PUSH_REMOTE" != "$EXPECTED_PUSH_REMOTE" ]]; then
    add_reason "PUSH_REMOTE_MISMATCH"
fi
if [[ -n "$EXPECTED_PUSH_TARGET" && "$PUSH_TARGET" != "$EXPECTED_PUSH_TARGET" ]]; then
    add_reason "PUSH_TARGET_MISMATCH"
fi

probe_filter_configuration() {
    local repo="$1"
    git -C "$repo" config --get-regexp '^filter\.' >/dev/null 2>&1
    local rc=$?
    [[ "$rc" -eq 1 ]] && return 0
    [[ "$rc" -eq 0 ]] && return 1
    return 2
}

probe_index_visibility() {
    local repo="$1" entry tag index_fd index_pid index_rc hazard=0
    exec {index_fd}< <(git -C "$repo" ls-files -v -z 2>/dev/null)
    index_pid=$!
    while IFS= read -r -d '' entry <&"$index_fd"; do
        tag="${entry:0:1}"
        if [[ "$tag" == "S" || "$tag" =~ [a-z] ]]; then
            hazard=1
        fi
    done
    exec {index_fd}<&-
    wait "$index_pid"
    index_rc=$?
    [[ "$index_rc" -eq 0 ]] || return 2
    [[ "$hazard" -eq 0 ]] || return 1
    return 0
}

probe_index_visibility "$WORKSPACE"
index_visibility_rc=$?
if [[ "$index_visibility_rc" -eq 1 ]]; then
    add_reason "INDEX_VISIBILITY_FLAGS_PRESENT"
elif [[ "$index_visibility_rc" -ne 0 ]]; then
    add_reason "INDEX_VISIBILITY_PROBE_FAILED"
fi

CODING_FILTER_SAFE=0
probe_filter_configuration "$WORKSPACE"
coding_filter_rc=$?
if [[ "$coding_filter_rc" -eq 1 ]]; then
    add_reason "GIT_FILTER_CONFIGURATION_PRESENT"
elif [[ "$coding_filter_rc" -ne 0 ]]; then
    add_reason "GIT_FILTER_CONFIG_PROBE_FAILED"
else
    CODING_FILTER_SAFE=1
fi

CODING_STATUS_SHA=""
CODING_INDEX_PATH=""
CODING_INDEX_SHA=""
CODING_INDEX_META=""
if [[ "$CODING_FILTER_SAFE" -eq 1 ]]; then
    status_lines="$(git status --porcelain=v1 -uall --ignore-submodules=none 2>/dev/null)" || invalid_invocation "git_status_failed"
    DIRTY_TRACKED="$(printf '%s\n' "$status_lines" | awk 'NF && substr($0,1,2)!="??" {count++} END {print count+0}')"
    dirty_tracked_rc=$?
    DIRTY_UNTRACKED="$(printf '%s\n' "$status_lines" | awk 'NF && substr($0,1,2)=="??" {count++} END {print count+0}')"
    dirty_untracked_rc=$?
    if [[ "$dirty_tracked_rc" -ne 0 || "$dirty_untracked_rc" -ne 0 || ! "$DIRTY_TRACKED" =~ ^[0-9]+$ || ! "$DIRTY_UNTRACKED" =~ ^[0-9]+$ ]]; then
        DIRTY_TRACKED="UNKNOWN"; DIRTY_UNTRACKED="UNKNOWN"
        add_reason "DIRTY_COUNT_PROBE_FAILED"
    fi
    if CODING_STATUS_SHA="$(git status --porcelain=v1 -z -uall --ignore-submodules=none 2>/dev/null | sha256sum | awk '{print $1}')"; then
        [[ "$CODING_STATUS_SHA" =~ ^[0-9a-fA-F]{64}$ ]] || add_reason "CODING_STATUS_PROBE_FAILED"
    else
        CODING_STATUS_SHA=""; add_reason "CODING_STATUS_PROBE_FAILED"
    fi
    coding_index_raw="$(git rev-parse --git-path index 2>/dev/null)"
    coding_index_rc=$?
    if [[ "$coding_index_rc" -eq 0 && -n "$coding_index_raw" ]]; then
        if [[ "$coding_index_raw" == /* ]]; then
            CODING_INDEX_PATH="$(realpath -e "$coding_index_raw" 2>/dev/null || true)"
        else
            CODING_INDEX_PATH="$(realpath -e "$WORKSPACE/$coding_index_raw" 2>/dev/null || true)"
        fi
    fi
    if [[ -n "$CODING_INDEX_PATH" ]]; then
        CODING_INDEX_SHA="$(sha256sum "$CODING_INDEX_PATH" 2>/dev/null | awk '{print $1}')"
        coding_index_sha_rc=$?
        CODING_INDEX_META="$(stat -Lc '%d:%i:%s:%y' "$CODING_INDEX_PATH" 2>/dev/null)"
        coding_index_meta_rc=$?
    else
        coding_index_sha_rc=1; coding_index_meta_rc=1
    fi
    if [[ "$coding_index_sha_rc" -ne 0 || "$coding_index_meta_rc" -ne 0 || ! "$CODING_INDEX_SHA" =~ ^[0-9a-fA-F]{64}$ || -z "$CODING_INDEX_META" ]]; then
        add_reason "CODING_INDEX_PROBE_FAILED"
    fi
else
    DIRTY_TRACKED="UNKNOWN"
    DIRTY_UNTRACKED="UNKNOWN"
fi

declare -A unmerged_seen=()
unmerged_parse_failed=0
exec {unmerged_fd}< <(git ls-files --unmerged -z 2>/dev/null)
unmerged_pid=$!
while IFS= read -r -d '' unmerged_entry <&"$unmerged_fd"; do
    unmerged_path="${unmerged_entry#*$'\t'}"
    if [[ "$unmerged_path" == "$unmerged_entry" ]]; then
        unmerged_parse_failed=1
        continue
    fi
    unmerged_seen["$unmerged_path"]=1
done
exec {unmerged_fd}<&-
wait "$unmerged_pid"
unmerged_probe_rc=$?
if [[ "$unmerged_probe_rc" -ne 0 || "$unmerged_parse_failed" -ne 0 ]]; then
    UNMERGED="UNKNOWN"
    add_reason "UNMERGED_PROBE_FAILED"
else
    UNMERGED="${#unmerged_seen[@]}"
fi

if [[ "$REQUIRE_CLEAN" -eq 1 && "$DIRTY_TRACKED" =~ ^[0-9]+$ && "$DIRTY_TRACKED" -gt 0 ]]; then
    add_reason "DIRTY_TRACKED"
fi
if [[ "$REQUIRE_CLEAN" -eq 1 && "$DIRTY_UNTRACKED" =~ ^[0-9]+$ && "$DIRTY_UNTRACKED" -gt 0 ]]; then
    add_reason "DIRTY_UNTRACKED"
fi
if [[ "$UNMERGED" =~ ^[0-9]+$ && "$UNMERGED" -gt 0 ]]; then
    add_reason "UNMERGED_FILES"
fi

declare -a WT_PATHS=() WT_HEADS=() WT_BRANCHES=() WT_PRUNABLE_FLAGS=() WT_LOCKED_FLAGS=()
load_worktree_metadata() {
    WT_PATHS=(); WT_HEADS=(); WT_BRANCHES=(); WT_PRUNABLE_FLAGS=(); WT_LOCKED_FLAGS=()
    local field wt="" head="" branch="" prunable=0 locked=0 detached=0
    local wt_seen=0 head_seen=0 branch_seen=0 detached_seen=0 prunable_seen=0 locked_seen=0 malformed=0
    local wt_fd wt_pid
    declare -A seen_paths=()
    exec {wt_fd}< <(git worktree list --porcelain -z 2>/dev/null)
    wt_pid=$!
    while IFS= read -r -d '' field <&"$wt_fd"; do
        if [[ -z "$field" ]]; then
            if [[ -n "$wt" ]]; then
                if [[ "$wt_seen" -ne 1 || "$head_seen" -ne 1 || $((branch_seen + detached_seen)) -ne 1 || "$prunable_seen" -gt 1 || "$locked_seen" -gt 1 ]]; then malformed=1; fi
                if [[ -n "${seen_paths[$wt]:-}" ]]; then malformed=1; fi
                seen_paths["$wt"]=1
                WT_PATHS+=("$wt"); WT_HEADS+=("$head"); WT_BRANCHES+=("$branch")
                WT_PRUNABLE_FLAGS+=("$prunable"); WT_LOCKED_FLAGS+=("$locked")
            elif [[ "$head_seen" -ne 0 || "$branch_seen" -ne 0 || "$detached_seen" -ne 0 || "$prunable_seen" -ne 0 || "$locked_seen" -ne 0 ]]; then
                malformed=1
            fi
            wt=""; head=""; branch=""; prunable=0; locked=0; detached=0
            wt_seen=0; head_seen=0; branch_seen=0; detached_seen=0; prunable_seen=0; locked_seen=0
            continue
        fi
        case "$field" in
            worktree\ *) wt="${field#worktree }"; wt_seen=$((wt_seen + 1)) ;;
            HEAD\ *) head="${field#HEAD }"; head_seen=$((head_seen + 1)) ;;
            branch\ *)
                branch="${field#branch }"; branch_seen=$((branch_seen + 1))
                [[ -n "$branch" ]] || malformed=1
                ;;
            detached) detached=1; detached_seen=$((detached_seen + 1)) ;;
            prunable*) prunable=1; prunable_seen=$((prunable_seen + 1)) ;;
            locked*) locked=1; locked_seen=$((locked_seen + 1)) ;;
            *) malformed=1 ;;
        esac
    done
    exec {wt_fd}<&-
    if ! wait "$wt_pid"; then
        add_reason "WORKTREE_PROBE_FAILED"
        return 1
    fi
    if [[ -n "$wt" ]]; then
        if [[ "$wt_seen" -ne 1 || "$head_seen" -ne 1 || $((branch_seen + detached_seen)) -ne 1 || "$prunable_seen" -gt 1 || "$locked_seen" -gt 1 ]]; then malformed=1; fi
        if [[ -n "${seen_paths[$wt]:-}" ]]; then malformed=1; fi
        seen_paths["$wt"]=1
        WT_PATHS+=("$wt"); WT_HEADS+=("$head"); WT_BRANCHES+=("$branch")
        WT_PRUNABLE_FLAGS+=("$prunable"); WT_LOCKED_FLAGS+=("$locked")
    fi
    if [[ "$malformed" -ne 0 ]]; then
        add_reason "WORKTREE_METADATA_MALFORMED"
        return 1
    fi
    return 0
}

worktree_index() {
    local target="$1" i
    for i in "${!WT_PATHS[@]}"; do
        [[ "${WT_PATHS[$i]}" == "$target" ]] && { printf '%s' "$i"; return 0; }
    done
    return 1
}

validate_worktree_admin_binding() {
    local target="$1" effective_git_dir="$2" common_git_dir="$3"
    local effective_real common_real backlink_raw backlink_norm admin candidate_raw candidate_norm
    local matches=0
    effective_real="$(realpath -e "$effective_git_dir" 2>/dev/null || true)"
    common_real="$(realpath -e "$common_git_dir" 2>/dev/null || true)"
    if [[ -z "$effective_real" || -z "$common_real" ]]; then
        add_reason "WORKTREE_ADMIN_MISMATCH"
        return 1
    fi
    if [[ "$effective_real" == "$common_real" ]]; then
        if [[ "${WT_PATHS[0]:-}" != "$target" ]]; then
            add_reason "WORKTREE_ADMIN_MISMATCH"
            return 1
        fi
        return 0
    fi
    if [[ "$effective_real" != "$common_real"/worktrees/* || ! -r "$effective_real/gitdir" ]]; then
        add_reason "WORKTREE_ADMIN_MISMATCH"
        return 1
    fi
    backlink_raw="$(cat "$effective_real/gitdir" 2>/dev/null)" || backlink_raw=""
    if [[ "$backlink_raw" == /* ]]; then
        backlink_norm="$(realpath -m "$backlink_raw" 2>/dev/null || true)"
    else
        backlink_norm="$(realpath -m "$effective_real/$backlink_raw" 2>/dev/null || true)"
    fi
    [[ "$backlink_norm" == "$target/.git" ]] || { add_reason "WORKTREE_ADMIN_MISMATCH"; return 1; }
    for admin in "$common_real"/worktrees/*; do
        [[ -d "$admin" && -r "$admin/gitdir" ]] || continue
        candidate_raw="$(cat "$admin/gitdir" 2>/dev/null)" || continue
        if [[ "$candidate_raw" == /* ]]; then
            candidate_norm="$(realpath -m "$candidate_raw" 2>/dev/null || true)"
        else
            candidate_norm="$(realpath -m "$admin/$candidate_raw" 2>/dev/null || true)"
        fi
        [[ "$candidate_norm" == "$target/.git" ]] && matches=$((matches + 1))
    done
    [[ "$matches" -eq 1 ]] || { add_reason "WORKTREE_ADMIN_MISMATCH"; return 1; }
    return 0
}

load_worktree_metadata || true
current_idx="$(worktree_index "$WORKSPACE" || true)"
if [[ -n "$current_idx" ]]; then
    WORKTREE_REGISTERED="1"
    if [[ "${WT_HEADS[$current_idx]:-}" != "$HEAD" ]]; then
        add_reason "WORKTREE_METADATA_MISMATCH"
    fi
    if [[ "$BRANCH" == "DETACHED" ]]; then
        [[ -z "${WT_BRANCHES[$current_idx]:-}" ]] || add_reason "WORKTREE_METADATA_MISMATCH"
    elif [[ "$BRANCH" != "UNKNOWN" && "${WT_BRANCHES[$current_idx]:-}" != "refs/heads/$BRANCH" ]]; then
        add_reason "WORKTREE_METADATA_MISMATCH"
    fi
    if [[ "${WT_PRUNABLE_FLAGS[$current_idx]:-0}" -eq 1 ]]; then
        WORKTREE_PRUNABLE="1"
        add_reason "WORKTREE_PRUNABLE"
    fi
    if [[ "${WT_LOCKED_FLAGS[$current_idx]:-0}" -eq 1 ]]; then
        add_reason "WORKTREE_LOCKED"
    fi
else
    add_reason "WORKTREE_NOT_REGISTERED"
fi
validate_worktree_admin_binding "$WORKSPACE" "$git_dir" "$git_common" || true

if [[ "$BRANCH" != "DETACHED" ]]; then
    for i in "${!WT_PATHS[@]}"; do
        if [[ "${WT_BRANCHES[$i]}" == "refs/heads/$BRANCH" && "${WT_PATHS[$i]}" != "$WORKSPACE" ]]; then
            BRANCH_OTHER_WORKTREE="${WT_PATHS[$i]}"
            add_reason "BRANCH_CHECKED_OUT_ELSEWHERE"
            break
        fi
    done
fi
validate_proc_view() {
    local status_file="$PROC_ROOT/self/status" mounts_file="$PROC_ROOT/mounts"
    local pid1_status="$PROC_ROOT/1/status" pid1_comm_file="$PROC_ROOT/1/comm"
    local pid1_cgroup_file="$PROC_ROOT/1/cgroup" pid_ns_file="$PROC_ROOT/self/ns/pid"
    local nspid_fields pid1_nspid pid1_comm pid1_cgroup proc_opts opt
    local current_pid_ns host_pid_ns_raw host_pid_ns distro oracle_rc
    if [[ ! -r "$status_file" || ! -r "$mounts_file" || ! -r "$pid1_status" || ! -r "$pid1_comm_file" || ! -r "$pid1_cgroup_file" || ! -e "$pid_ns_file" ]]; then
        add_reason "PROC_VIEW_NOT_HOST_WIDE"
        return
    fi
    nspid_fields="$(awk '/^NSpid:/ {print NF; exit}' "$status_file" 2>/dev/null || true)"
    pid1_nspid="$(awk '/^NSpid:/ {print $2; exit}' "$pid1_status" 2>/dev/null || true)"
    pid1_comm="$(cat "$pid1_comm_file" 2>/dev/null || true)"
    pid1_cgroup="$(awk -F: '$1=="0" && $2=="" {print $3; exit}' "$pid1_cgroup_file" 2>/dev/null || true)"
    proc_opts="$(awk '$2=="/proc" && $3=="proc" {print $4; exit}' "$mounts_file" 2>/dev/null || true)"
    current_pid_ns="$(stat -Lc '%d:%i' "$pid_ns_file" 2>/dev/null || true)"
    distro="${WSL_DISTRO_NAME:-Ubuntu}"
    host_pid_ns_raw="$(timeout 5s "$WSL_EXE" -d "$distro" -- bash -lc "stat -Lc '%d:%i' /proc/self/ns/pid" 2>/dev/null)"
    oracle_rc=$?
    host_pid_ns="$(printf '%s\n' "$host_pid_ns_raw" | tr -d '\r' | tail -1)"
    if [[ "$nspid_fields" != "2" || "$pid1_nspid" != "1" || "$pid1_cgroup" != "/init.scope" || ( "$pid1_comm" != "systemd" && "$pid1_comm" != "init" ) || -z "$proc_opts" ]]; then
        add_reason "PROC_VIEW_NOT_HOST_WIDE"
        return
    fi
    if [[ "$oracle_rc" -ne 0 || -z "$current_pid_ns" || -z "$host_pid_ns" || "$current_pid_ns" != "$host_pid_ns" ]]; then
        add_reason "PROC_VIEW_NOT_HOST_WIDE"
        return
    fi
    for opt in ${proc_opts//,/ }; do
        case "$opt" in
            hidepid=0) ;;
            hidepid=*|subset=pid) add_reason "PROC_VIEW_NOT_HOST_WIDE" ;;
        esac
    done
}

proc_maps_escape() {
    local value="$1"
    printf '%s' "${value//$'\n'/\\012}"
}

scan_cleanup_processes() {
    LIVE_PROCESS_COUNT="0"
    LIVE_PROCESS_STATE="NONE"
    if [[ ! -d "$PROC_ROOT" || ! -r "$PROC_ROOT" ]]; then
        LIVE_PROCESS_STATE="UNKNOWN"
        add_reason "PROC_ROOT_INVALID"
        return
    fi
    local pid_dir status_file process_cwd process_state kthread fd_dir fd link_target
    local ref_kind ref_target maps_file map_line map_path maps_target_path
    local proc_scan_incomplete=0 pid_live=0 fd_live=0 ref_live=0
    maps_target_path="$(proc_maps_escape "$CLEANUP_TARGET_REALPATH")"
    for pid_dir in "$PROC_ROOT"/[0-9]*; do
        [[ -d "$pid_dir" ]] || continue
        status_file="$pid_dir/status"
        if [[ ! -r "$status_file" ]]; then
            [[ -d "$pid_dir" ]] && proc_scan_incomplete=1
            continue
        fi
        process_state="$(awk '/^State:/ {print $2; exit}' "$status_file" 2>/dev/null || true)"
        kthread="$(awk '/^Kthread:/ {print $2; exit}' "$status_file" 2>/dev/null || true)"
        [[ "$process_state" == "Z" || "$kthread" == "1" ]] && continue
        pid_live=0; fd_live=0; ref_live=0
        if process_cwd="$(readlink "$pid_dir/cwd" 2>/dev/null)"; then
            process_cwd="${process_cwd% (deleted)}"
            case "$process_cwd" in
                "$CLEANUP_TARGET_REALPATH"|"$CLEANUP_TARGET_REALPATH"/*) pid_live=1 ;;
            esac
        elif [[ -d "$pid_dir" ]]; then
            LIVE_PROCESS_STATE="UNKNOWN"
            add_reason "PROC_CWD_UNREADABLE"
        fi
        fd_dir="$pid_dir/fd"
        if [[ -d "$fd_dir" ]]; then
            if [[ -r "$fd_dir" ]]; then
                for fd in "$fd_dir"/*; do
                    [[ -e "$fd" || -L "$fd" ]] || continue
                    if link_target="$(readlink "$fd" 2>/dev/null)"; then
                        link_target="${link_target% (deleted)}"
                        case "$link_target" in
                            "$CLEANUP_TARGET_REALPATH"|"$CLEANUP_TARGET_REALPATH"/*) fd_live=1 ;;
                        esac
                    elif [[ -d "$pid_dir" ]]; then
                        LIVE_PROCESS_STATE="UNKNOWN"
                        add_reason "PROC_FD_UNREADABLE"
                    fi
                done
            else
                LIVE_PROCESS_STATE="UNKNOWN"
                add_reason "PROC_FD_UNREADABLE"
            fi
        fi
        for ref_kind in exe root; do
            if ref_target="$(readlink "$pid_dir/$ref_kind" 2>/dev/null)"; then
                ref_target="${ref_target% (deleted)}"
                case "$ref_target" in
                    "$CLEANUP_TARGET_REALPATH"|"$CLEANUP_TARGET_REALPATH"/*) ref_live=1 ;;
                esac
            elif [[ ( -e "$pid_dir/$ref_kind" || -L "$pid_dir/$ref_kind" ) && -d "$pid_dir" ]]; then
                LIVE_PROCESS_STATE="UNKNOWN"
                add_reason "PROC_REF_UNREADABLE"
            fi
        done
        maps_file="$pid_dir/maps"
        if [[ -r "$maps_file" ]]; then
            while IFS= read -r map_line; do
                if [[ "$map_line" =~ ^[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+(.*)$ ]]; then
                    map_path="${BASH_REMATCH[1]}"
                    map_path="${map_path% (deleted)}"
                    case "$map_path" in
                        "$CLEANUP_TARGET_REALPATH"|"$CLEANUP_TARGET_REALPATH"/*|                        "$maps_target_path"|"$maps_target_path"/*) ref_live=1 ;;
                    esac
                fi
            done < "$maps_file"
        elif [[ -e "$maps_file" && -d "$pid_dir" ]]; then
            LIVE_PROCESS_STATE="UNKNOWN"
            add_reason "PROC_REF_UNREADABLE"
        fi
        if [[ "$pid_live" -eq 1 || "$fd_live" -eq 1 || "$ref_live" -eq 1 ]]; then
            LIVE_PROCESS_COUNT=$((LIVE_PROCESS_COUNT + 1))
        fi
        [[ "$pid_live" -eq 1 ]] && add_reason "LIVE_PROCESS_PRESENT"
        [[ "$fd_live" -eq 1 ]] && add_reason "LIVE_FILE_DESCRIPTOR_PRESENT"
        [[ "$ref_live" -eq 1 ]] && add_reason "LIVE_PROCESS_REFERENCE_PRESENT"
    done
    if [[ "$proc_scan_incomplete" -ne 0 ]]; then
        LIVE_PROCESS_STATE="UNKNOWN"
        add_reason "PROC_SCAN_INCOMPLETE"
    elif [[ "$LIVE_PROCESS_COUNT" -gt 0 ]]; then
        LIVE_PROCESS_STATE="PRESENT"
    fi
}

if [[ -n "$CLEANUP_TARGET" ]]; then
    CLEANUP_TARGET_REALPATH="$(realpath -e "$CLEANUP_TARGET" 2>/dev/null || realpath -m "$CLEANUP_TARGET" 2>/dev/null || printf '%s' "$CLEANUP_TARGET")"
    PRIMARY_WORKTREE="${WT_PATHS[0]:-}"
    PRIMARY_WORKTREE_REALPATH="$(realpath -e "$PRIMARY_WORKTREE" 2>/dev/null || true)"
    GIT_COMMON_REALPATH="$(realpath -e "$git_common" 2>/dev/null || true)"
    if [[ "$DESTRUCTIVE_CLEANUP" -eq 1 && -n "$PRIMARY_WORKTREE_REALPATH" && "$CLEANUP_TARGET_REALPATH" == "$PRIMARY_WORKTREE_REALPATH" ]]; then
        add_reason "PRIMARY_WORKTREE_CLEANUP_FORBIDDEN"
    fi
    if [[ "$DESTRUCTIVE_CLEANUP" -eq 1 && -n "$GIT_COMMON_REALPATH" ]]; then
        case "$GIT_COMMON_REALPATH" in
            "$CLEANUP_TARGET_REALPATH"|"$CLEANUP_TARGET_REALPATH"/*) add_reason "COMMON_GIT_DIR_CLEANUP_FORBIDDEN" ;;
        esac
        case "$CLEANUP_TARGET_REALPATH" in
            "$GIT_COMMON_REALPATH"|"$GIT_COMMON_REALPATH"/*) add_reason "CLEANUP_TARGET_INSIDE_COMMON_GIT" ;;
        esac
    fi
    cleanup_idx="$(worktree_index "$CLEANUP_TARGET_REALPATH" || true)"
    if [[ -n "$cleanup_idx" ]]; then
        CLEANUP_TARGET_REGISTERED="1"
        TARGET_HEAD="${WT_HEADS[$cleanup_idx]:-UNKNOWN}"
        TARGET_BRANCH="${WT_BRANCHES[$cleanup_idx]:-DETACHED}"
        TARGET_GIT_DIR_RAW="$(git -C "$CLEANUP_TARGET_REALPATH" rev-parse --path-format=absolute --git-dir 2>/dev/null)"
        target_git_dir_rc=$?
        TARGET_GIT_DIR_REALPATH="$(realpath -e "$TARGET_GIT_DIR_RAW" 2>/dev/null || true)"
        if [[ "$target_git_dir_rc" -ne 0 || -z "$TARGET_GIT_DIR_REALPATH" ]]; then
            add_reason "TARGET_GIT_IDENTITY_UNAVAILABLE"
        fi
        if [[ "${WT_PRUNABLE_FLAGS[$cleanup_idx]}" -eq 1 ]]; then
            CLEANUP_TARGET_PRUNABLE="1"
            add_reason "WORKTREE_PRUNABLE"
        fi
        if [[ "${WT_LOCKED_FLAGS[$cleanup_idx]}" -eq 1 ]]; then
            add_reason "WORKTREE_LOCKED"
        fi
    else
        add_reason "CLEANUP_TARGET_NOT_REGISTERED"
    fi
    validate_proc_view
    scan_cleanup_processes
fi

EVIDENCE_RESOLVED=""
resolve_evidence_file() {
    local raw="$1" missing_reason="$2" resolved
    EVIDENCE_RESOLVED=""
    if [[ -z "$raw" ]]; then
        add_reason "$missing_reason"
        return 1
    fi
    resolved="$(realpath -e "$raw" 2>/dev/null || true)"
    if [[ -z "$resolved" || ! -f "$resolved" || ! -s "$resolved" ]]; then
        add_reason "$missing_reason"
        return 1
    fi
    case "$resolved" in
        "$CLEANUP_TARGET_REALPATH"|"$CLEANUP_TARGET_REALPATH"/*)
            add_reason "EVIDENCE_INSIDE_CLEANUP_TARGET"
            return 1
            ;;
    esac
    EVIDENCE_RESOLVED="$resolved"
    return 0
}

checksum_has_file() {
    local manifest="$1" path="$2" sha
    sha="$(sha256sum < "$path" 2>/dev/null | awk '{print $1}')" || return 1
    [[ "$sha" =~ ^[0-9a-fA-F]{64}$ ]] || return 1
    python3 -I - "$manifest" "$path" "$sha" <<'PY'
import sys
manifest, expected_path, expected_sha = sys.argv[1:4]
for raw in open(manifest, "r", encoding="utf-8", errors="surrogateescape"):
    line = raw.rstrip("\n")
    escaped = line.startswith("\\")
    if escaped:
        line = line[1:]
    if len(line) < 66 or line[64] != " " or line[65] not in (" ", "*"):
        continue
    digest, name = line[:64], line[66:]
    if escaped:
        out = []
        i = 0
        valid = True
        while i < len(name):
            if name[i] != "\\":
                out.append(name[i]); i += 1; continue
            i += 1
            if i >= len(name): valid = False; break
            esc = name[i]; i += 1
            if esc == "\\": out.append("\\")
            elif esc == "n": out.append("\n")
            elif esc == "r": out.append("\r")
            else: valid = False; break
        if not valid:
            continue
        name = "".join(out)
    if digest.lower() == expected_sha.lower() and name == expected_path:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

archive_missing=0
ARCHIVE_REF_COMMIT=""
BUNDLE_REALPATH=""
TRACKED_PATCH_REALPATH=""
UNTRACKED_ARCHIVE_REALPATH=""
CHECKSUM_REALPATH=""
COVERAGE_REALPATH=""
TARGET_STATUS_SNAPSHOT=""
CHECKSUM_MANIFEST_SHA=""
if [[ "$DESTRUCTIVE_CLEANUP" -eq 1 ]]; then
    ARCHIVE_REQUIREMENT_STATE="PASS"
    archive_head_ok=0
    TARGET_FILTER_SAFE=0
    probe_filter_configuration "$CLEANUP_TARGET_REALPATH"
    target_filter_rc=$?
    if [[ "$target_filter_rc" -eq 1 ]]; then
        add_reason "GIT_FILTER_CONFIGURATION_PRESENT"
        archive_missing=1
    elif [[ "$target_filter_rc" -ne 0 ]]; then
        add_reason "GIT_FILTER_CONFIG_PROBE_FAILED"
        archive_missing=1
    else
        TARGET_FILTER_SAFE=1
    fi

    if [[ -n "$ARCHIVE_REF" ]]; then
        if [[ "$ARCHIVE_REF" != refs/archive/* ]]; then
            add_reason "ARCHIVE_REF_NOT_DURABLE"
            archive_missing=1
            if git check-ref-format "$ARCHIVE_REF" >/dev/null 2>&1; then
                nonarchive_ref_commit="$(git show-ref --verify --hash "$ARCHIVE_REF" 2>/dev/null || true)"
                if [[ -n "$nonarchive_ref_commit" && "$nonarchive_ref_commit" != "$TARGET_HEAD" ]]; then
                    add_reason "ARCHIVE_HEAD_MISMATCH"
                fi
            fi
        elif ! git check-ref-format "$ARCHIVE_REF" >/dev/null 2>&1; then
            add_reason "ARCHIVE_REF_NOT_EXACT"
            archive_missing=1
        else
            ARCHIVE_REF_COMMIT="$(git show-ref --verify --hash "$ARCHIVE_REF" 2>/dev/null)"
            archive_ref_rc=$?
            if [[ "$archive_ref_rc" -ne 0 || -z "$ARCHIVE_REF_COMMIT" ]]; then
                add_reason "ARCHIVE_REF_MISSING"
                archive_missing=1
            elif [[ "$ARCHIVE_REF_COMMIT" != "$TARGET_HEAD" ]]; then
                add_reason "ARCHIVE_HEAD_MISMATCH"
                archive_missing=1
            else
                archive_head_ok=1
            fi
        fi
    fi

    if [[ -n "$BUNDLE_PATH" ]]; then
        if resolve_evidence_file "$BUNDLE_PATH" "BUNDLE_MISSING"; then
            BUNDLE_REALPATH="$EVIDENCE_RESOLVED"
            if git bundle verify "$BUNDLE_REALPATH" >/dev/null 2>&1 && \
                git bundle list-heads "$BUNDLE_REALPATH" 2>/dev/null | awk -v head="$TARGET_HEAD" '$1==head {found=1} END {exit(found ? 0 : 1)}'; then
                archive_head_ok=1
            else
                add_reason "BUNDLE_HEAD_MISMATCH"
                archive_missing=1
            fi
        else
            archive_missing=1
        fi
    fi

    if [[ "$archive_head_ok" -ne 1 ]]; then
        add_reason "ARCHIVE_HEAD_OR_BUNDLE_MISSING"
        archive_missing=1
    fi
    if [[ "$TARGET_FILTER_SAFE" -eq 1 && -d "$CLEANUP_TARGET_REALPATH" ]] && git -C "$CLEANUP_TARGET_REALPATH" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        if target_status="$(git -C "$CLEANUP_TARGET_REALPATH" status --porcelain=v1 -uall --ignore-submodules=none 2>/dev/null)"; then
            TARGET_STATUS_SNAPSHOT="$target_status"
            TARGET_DIRTY_TRACKED="$(printf '%s\n' "$target_status" | awk 'NF && substr($0,1,2)!="??" {count++} END {print count+0}')"
            target_tracked_rc=$?
            TARGET_DIRTY_UNTRACKED="$(printf '%s\n' "$target_status" | awk 'NF && substr($0,1,2)=="??" {count++} END {print count+0}')"
            target_untracked_rc=$?
            if [[ "$target_tracked_rc" -ne 0 || "$target_untracked_rc" -ne 0 || ! "$TARGET_DIRTY_TRACKED" =~ ^[0-9]+$ || ! "$TARGET_DIRTY_UNTRACKED" =~ ^[0-9]+$ ]]; then
                TARGET_DIRTY_TRACKED="UNKNOWN"
                TARGET_DIRTY_UNTRACKED="UNKNOWN"
                add_reason "TARGET_DIRTY_COUNT_PROBE_FAILED"
                archive_missing=1
            fi
        else
            TARGET_DIRTY_TRACKED="UNKNOWN"
            TARGET_DIRTY_UNTRACKED="UNKNOWN"
            add_reason "TARGET_STATUS_UNAVAILABLE"
            archive_missing=1
        fi
    else
        TARGET_DIRTY_TRACKED="UNKNOWN"
        TARGET_DIRTY_UNTRACKED="UNKNOWN"
        add_reason "TARGET_DIRTY_STATE_UNKNOWN"
        archive_missing=1
    fi

    probe_index_visibility "$CLEANUP_TARGET_REALPATH"
    target_index_visibility_rc=$?
    if [[ "$target_index_visibility_rc" -eq 1 ]]; then
        add_reason "INDEX_VISIBILITY_FLAGS_PRESENT"
        archive_missing=1
    elif [[ "$target_index_visibility_rc" -ne 0 ]]; then
        add_reason "INDEX_VISIBILITY_PROBE_FAILED"
        archive_missing=1
    fi

    target_unmerged_index="$(git -C "$CLEANUP_TARGET_REALPATH" ls-files -u 2>/dev/null)"
    target_unmerged_index_rc=$?
    if [[ "$target_unmerged_index_rc" -ne 0 ]]; then
        add_reason "INDEX_STATE_PROBE_FAILED"
        archive_missing=1
    elif [[ -n "$target_unmerged_index" ]]; then
        add_reason "UNMERGED_INDEX_STATE_PRESENT"
        archive_missing=1
    else
        git -C "$CLEANUP_TARGET_REALPATH" diff --no-ext-diff --no-textconv --cached --quiet --ignore-submodules -- 2>/dev/null
        target_staged_index_rc=$?
        if [[ "$target_staged_index_rc" -eq 1 ]]; then
            add_reason "STAGED_INDEX_STATE_PRESENT"
            archive_missing=1
        elif [[ "$target_staged_index_rc" -gt 1 ]]; then
            add_reason "INDEX_STATE_PROBE_FAILED"
            archive_missing=1
        fi
    fi

    ignored_files="$(git -C "$CLEANUP_TARGET_REALPATH" ls-files -o -i --exclude-standard 2>/dev/null)"
    ignored_rc=$?
    if [[ "$ignored_rc" -ne 0 ]]; then
        add_reason "IGNORED_PROBE_FAILED"
        archive_missing=1
    elif [[ -n "$ignored_files" ]]; then
        add_reason "IGNORED_CONTENT_PRESENT"
        archive_missing=1
    fi

    submodule_status="$(git -C "$CLEANUP_TARGET_REALPATH" submodule status --recursive 2>/dev/null)"
    submodule_status_rc=$?
    if [[ "$submodule_status_rc" -ne 0 ]]; then
        add_reason "SUBMODULE_PROBE_FAILED"
        archive_missing=1
    elif grep -q '^-' <<<"$submodule_status"; then
        add_reason "UNINITIALIZED_SUBMODULE_PRESENT"
        archive_missing=1
    elif [[ -n "$submodule_status" ]]; then
        add_reason "INITIALIZED_SUBMODULE_RECOVERY_REQUIRED"
        archive_missing=1
    fi

    dirty_submodules="$(git -C "$CLEANUP_TARGET_REALPATH" submodule foreach --quiet --recursive 'if git config --get-regexp "^filter\." >/dev/null 2>&1; then printf "__FILTER__:%s\n" "$displaypath"; elif test -n "$(git status --porcelain=v1 -uall --ignored=matching)"; then printf "%s\n" "$displaypath"; fi' 2>/dev/null)"
    submodule_rc=$?
    if [[ "$submodule_rc" -ne 0 ]]; then
        add_reason "SUBMODULE_PROBE_FAILED"
        archive_missing=1
    elif grep -q '^__FILTER__:' <<<"$dirty_submodules"; then
        add_reason "GIT_FILTER_CONFIGURATION_PRESENT"
        archive_missing=1
    elif [[ -n "$dirty_submodules" ]]; then
        add_reason "DIRTY_SUBMODULE_PRESENT"
        archive_missing=1
    fi

    if [[ "$TARGET_DIRTY_TRACKED" =~ ^[0-9]+$ && "$TARGET_DIRTY_TRACKED" -gt 0 ]]; then
        if resolve_evidence_file "$TRACKED_PATCH" "TRACKED_PATCH_MISSING"; then
            TRACKED_PATCH_REALPATH="$EVIDENCE_RESOLVED"
            if current_patch_sha="$(git -C "$CLEANUP_TARGET_REALPATH" diff --no-ext-diff --no-textconv --binary HEAD 2>/dev/null | sha256sum | awk '{print $1}')" && \
                provided_patch_sha="$(sha256sum "$TRACKED_PATCH_REALPATH" 2>/dev/null | awk '{print $1}')" && \
                [[ -n "$current_patch_sha" && "$current_patch_sha" == "$provided_patch_sha" ]]; then
                :
            else
                add_reason "TRACKED_PATCH_MISMATCH"
                archive_missing=1
            fi
        else
            archive_missing=1
        fi
    fi
    if [[ "$TARGET_DIRTY_UNTRACKED" =~ ^[0-9]+$ && "$TARGET_DIRTY_UNTRACKED" -gt 0 ]]; then
        if resolve_evidence_file "$UNTRACKED_ARCHIVE" "UNTRACKED_ARCHIVE_MISSING"; then
            UNTRACKED_ARCHIVE_REALPATH="$EVIDENCE_RESOLVED"
            python3 -I - "$CLEANUP_TARGET_REALPATH" "$UNTRACKED_ARCHIVE_REALPATH" <<'PY'
import os
import subprocess
import sys
import tarfile

target, archive = sys.argv[1:3]
cp = subprocess.run(
    ["git", "-C", target, "ls-files", "-o", "--exclude-standard", "-z"],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
)
if cp.returncode != 0:
    raise SystemExit(2)
current = [os.fsdecode(item) for item in cp.stdout.split(b"\0") if item]
try:
    with tarfile.open(archive, "r:gz") as tf:
        archived = [m.name[2:] if m.name.startswith("./") else m.name for m in tf.getmembers()]
except Exception:
    raise SystemExit(3)
raise SystemExit(0 if sorted(current) == sorted(archived) else 1)
PY
            untracked_compare_rc=$?
            if [[ "$untracked_compare_rc" -eq 2 ]]; then
                add_reason "UNTRACKED_PROBE_FAILED"; archive_missing=1
            elif [[ "$untracked_compare_rc" -ne 0 ]]; then
                add_reason "UNTRACKED_ARCHIVE_MISMATCH"; archive_missing=1
            elif ! tar -C "$CLEANUP_TARGET_REALPATH" --compare --gzip --file "$UNTRACKED_ARCHIVE_REALPATH" >/dev/null 2>&1; then
                add_reason "UNTRACKED_ARCHIVE_MISMATCH"; archive_missing=1
            fi
        else
            archive_missing=1
        fi
    fi

    if resolve_evidence_file "$COVERAGE_EVIDENCE" "COVERAGE_EVIDENCE_MISSING"; then
        COVERAGE_REALPATH="$EVIDENCE_RESOLVED"
        coverage_ok=1
        coverage_ambiguous=0
        declare -A coverage_values=()
        declare -A coverage_counts=()
        while IFS= read -r coverage_line || [[ -n "$coverage_line" ]]; do
            [[ -z "$coverage_line" ]] && continue
            if [[ "$coverage_line" != *=* ]]; then
                coverage_ambiguous=1
                continue
            fi
            coverage_key="${coverage_line%%=*}"
            coverage_value="${coverage_line#*=}"
            case "$coverage_key" in
                TARGET_HEAD|TARGET_PATH|DIRTY_TRACKED|DIRTY_UNTRACKED|ARCHIVE_REF|BUNDLE_PATH|COVERAGE_BAD) ;;
                *) coverage_ambiguous=1; continue ;;
            esac
            coverage_counts[$coverage_key]=$((${coverage_counts[$coverage_key]:-0} + 1))
            if [[ "${coverage_counts[$coverage_key]}" -ne 1 ]]; then
                coverage_ambiguous=1
            fi
            coverage_values[$coverage_key]="$coverage_value"
        done < "$COVERAGE_REALPATH"
        [[ "${coverage_values[TARGET_HEAD]:-}" == "$(safe_value "$TARGET_HEAD")" ]] || coverage_ok=0
        [[ "${coverage_values[TARGET_PATH]:-}" == "$(safe_value "$CLEANUP_TARGET_REALPATH")" ]] || coverage_ok=0
        [[ "${coverage_values[DIRTY_TRACKED]:-}" == "$(safe_value "$TARGET_DIRTY_TRACKED")" ]] || coverage_ok=0
        [[ "${coverage_values[DIRTY_UNTRACKED]:-}" == "$(safe_value "$TARGET_DIRTY_UNTRACKED")" ]] || coverage_ok=0
        [[ "${coverage_values[COVERAGE_BAD]:-}" == "0" ]] || coverage_ok=0
        if [[ -n "$ARCHIVE_REF" ]]; then
            [[ "${coverage_values[ARCHIVE_REF]:-}" == "$(safe_value "$ARCHIVE_REF")" ]] || coverage_ok=0
            [[ -z "${coverage_values[BUNDLE_PATH]:-}" ]] || coverage_ambiguous=1
        elif [[ -n "$BUNDLE_REALPATH" ]]; then
            [[ "${coverage_values[BUNDLE_PATH]:-}" == "$(safe_value "$BUNDLE_REALPATH")" ]] || coverage_ok=0
            [[ -z "${coverage_values[ARCHIVE_REF]:-}" ]] || coverage_ambiguous=1
        fi
        if [[ "$coverage_ambiguous" -ne 0 ]]; then
            add_reason "COVERAGE_EVIDENCE_AMBIGUOUS"
            archive_missing=1
        fi
        if [[ "$coverage_ok" -ne 1 ]]; then
            add_reason "COVERAGE_EVIDENCE_INVALID"
            archive_missing=1
        fi
    else
        archive_missing=1
    fi
    if resolve_evidence_file "$CHECKSUM_EVIDENCE" "CHECKSUM_EVIDENCE_MISSING"; then
        CHECKSUM_REALPATH="$EVIDENCE_RESOLVED"
        CHECKSUM_MANIFEST_SHA="$(sha256sum "$CHECKSUM_REALPATH" 2>/dev/null | awk '{print $1}')"
        checksum_manifest_rc=$?
        if [[ "$checksum_manifest_rc" -ne 0 || -z "$CHECKSUM_MANIFEST_SHA" || ! "$CHECKSUM_MANIFEST_SHA" =~ ^[0-9a-fA-F]{64}$ ]]; then
            add_reason "CHECKSUM_EVIDENCE_INVALID"
            archive_missing=1
        fi
        if ! sha256sum -c --strict --status "$CHECKSUM_REALPATH" >/dev/null 2>&1; then
            add_reason "CHECKSUM_EVIDENCE_INVALID"
            archive_missing=1
        fi
        if [[ -n "$COVERAGE_REALPATH" ]] && ! checksum_has_file "$CHECKSUM_REALPATH" "$COVERAGE_REALPATH"; then
            add_reason "CHECKSUM_COVERAGE_MISSING"
            archive_missing=1
        fi
        if [[ -n "$TRACKED_PATCH_REALPATH" ]] && ! checksum_has_file "$CHECKSUM_REALPATH" "$TRACKED_PATCH_REALPATH"; then
            add_reason "CHECKSUM_PATCH_MISSING"
            archive_missing=1
        fi
        if [[ -n "$UNTRACKED_ARCHIVE_REALPATH" ]] && ! checksum_has_file "$CHECKSUM_REALPATH" "$UNTRACKED_ARCHIVE_REALPATH"; then
            add_reason "CHECKSUM_UNTRACKED_MISSING"
            archive_missing=1
        fi
        if [[ -n "$BUNDLE_REALPATH" ]] && ! checksum_has_file "$CHECKSUM_REALPATH" "$BUNDLE_REALPATH"; then
            add_reason "CHECKSUM_BUNDLE_MISSING"
            archive_missing=1
        fi
    else
        archive_missing=1
    fi

    final_head="$(git -C "$CLEANUP_TARGET_REALPATH" rev-parse HEAD 2>/dev/null)"
    final_head_rc=$?
    if [[ "$final_head_rc" -ne 0 || -z "$final_head" ]]; then
        add_reason "FINAL_TARGET_HEAD_PROBE_FAILED"
        archive_missing=1
    elif [[ "$final_head" != "$TARGET_HEAD" ]]; then
        add_reason "TARGET_HEAD_CHANGED"
        archive_missing=1
    fi
    if [[ "$TARGET_FILTER_SAFE" -eq 1 ]] && final_status="$(git -C "$CLEANUP_TARGET_REALPATH" status --porcelain=v1 -uall --ignore-submodules=none 2>/dev/null)"; then
        if [[ "$final_status" != "$TARGET_STATUS_SNAPSHOT" ]]; then
            add_reason "TARGET_STATE_CHANGED"
            archive_missing=1
        fi
    else
        add_reason "TARGET_STATUS_UNAVAILABLE"
        archive_missing=1
    fi
    probe_index_visibility "$CLEANUP_TARGET_REALPATH"
    final_index_visibility_rc=$?
    if [[ "$final_index_visibility_rc" -eq 1 ]]; then
        add_reason "INDEX_VISIBILITY_FLAGS_PRESENT"
        archive_missing=1
    elif [[ "$final_index_visibility_rc" -ne 0 ]]; then
        add_reason "INDEX_VISIBILITY_PROBE_FAILED"
        archive_missing=1
    fi
    if [[ "$TARGET_DIRTY_TRACKED" =~ ^[0-9]+$ && "$TARGET_DIRTY_TRACKED" -gt 0 && -n "$TRACKED_PATCH_REALPATH" ]]; then
        final_patch_sha="$(git -C "$CLEANUP_TARGET_REALPATH" diff --no-ext-diff --no-textconv --binary HEAD 2>/dev/null | sha256sum | awk '{print $1}')"
        final_patch_rc=$?
        evidence_patch_sha="$(sha256sum "$TRACKED_PATCH_REALPATH" 2>/dev/null | awk '{print $1}')"
        evidence_patch_rc=$?
        if [[ "$final_patch_rc" -ne 0 || "$evidence_patch_rc" -ne 0 || -z "$final_patch_sha" || "$final_patch_sha" != "$evidence_patch_sha" ]]; then
            add_reason "TARGET_STATE_CHANGED"
            archive_missing=1
        fi
    fi
    if [[ "$TARGET_DIRTY_UNTRACKED" =~ ^[0-9]+$ && "$TARGET_DIRTY_UNTRACKED" -gt 0 && -n "$UNTRACKED_ARCHIVE_REALPATH" ]]; then
        if ! tar -C "$CLEANUP_TARGET_REALPATH" --compare --gzip --file "$UNTRACKED_ARCHIVE_REALPATH" >/dev/null 2>&1; then
            add_reason "TARGET_STATE_CHANGED"
            archive_missing=1
        fi
    fi
    final_unmerged_index="$(git -C "$CLEANUP_TARGET_REALPATH" ls-files -u 2>/dev/null)"
    final_unmerged_index_rc=$?
    if [[ "$final_unmerged_index_rc" -ne 0 ]]; then
        add_reason "INDEX_STATE_PROBE_FAILED"
        archive_missing=1
    elif [[ -n "$final_unmerged_index" ]]; then
        add_reason "UNMERGED_INDEX_STATE_PRESENT"
        archive_missing=1
    else
        git -C "$CLEANUP_TARGET_REALPATH" diff --no-ext-diff --no-textconv --cached --quiet --ignore-submodules -- 2>/dev/null
        final_staged_index_rc=$?
        if [[ "$final_staged_index_rc" -eq 1 ]]; then
            add_reason "STAGED_INDEX_STATE_PRESENT"
            archive_missing=1
        elif [[ "$final_staged_index_rc" -gt 1 ]]; then
            add_reason "INDEX_STATE_PROBE_FAILED"
            archive_missing=1
        fi
    fi

    final_ignored="$(git -C "$CLEANUP_TARGET_REALPATH" ls-files -o -i --exclude-standard 2>/dev/null)"
    final_ignored_rc=$?
    if [[ "$final_ignored_rc" -ne 0 || -n "$final_ignored" ]]; then
        add_reason "IGNORED_CONTENT_PRESENT"
        archive_missing=1
    fi
    final_submodule_status="$(git -C "$CLEANUP_TARGET_REALPATH" submodule status --recursive 2>/dev/null)"
    final_submodule_status_rc=$?
    if [[ "$final_submodule_status_rc" -ne 0 ]]; then
        add_reason "SUBMODULE_PROBE_FAILED"
        archive_missing=1
    elif grep -q '^-' <<<"$final_submodule_status"; then
        add_reason "UNINITIALIZED_SUBMODULE_PRESENT"
        archive_missing=1
    elif [[ -n "$final_submodule_status" ]]; then
        add_reason "INITIALIZED_SUBMODULE_RECOVERY_REQUIRED"
        archive_missing=1
    fi
    final_dirty_submodules="$(git -C "$CLEANUP_TARGET_REALPATH" submodule foreach --quiet --recursive 'if git config --get-regexp "^filter\." >/dev/null 2>&1; then printf "__FILTER__:%s\n" "$displaypath"; elif test -n "$(git status --porcelain=v1 -uall --ignored=matching)"; then printf "%s\n" "$displaypath"; fi' 2>/dev/null)"
    final_dirty_submodule_rc=$?
    if [[ "$final_dirty_submodule_rc" -ne 0 ]]; then
        add_reason "SUBMODULE_PROBE_FAILED"; archive_missing=1
    elif grep -q '^__FILTER__:' <<<"$final_dirty_submodules"; then
        add_reason "GIT_FILTER_CONFIGURATION_PRESENT"; archive_missing=1
    elif [[ -n "$final_dirty_submodules" ]]; then
        add_reason "DIRTY_SUBMODULE_PRESENT"; archive_missing=1
    fi

    if [[ -n "$ARCHIVE_REF" ]]; then
        if ! git check-ref-format "$ARCHIVE_REF" >/dev/null 2>&1; then
            add_reason "RECOVERY_REF_CHANGED"
            archive_missing=1
        else
            final_archive_ref_commit="$(git show-ref --verify --hash "$ARCHIVE_REF" 2>/dev/null)"
            final_archive_ref_rc=$?
            if [[ "$final_archive_ref_rc" -ne 0 || "$final_archive_ref_commit" != "$TARGET_HEAD" ]]; then
                add_reason "RECOVERY_REF_CHANGED"
                archive_missing=1
            fi
        fi
    fi
    if [[ -n "$BUNDLE_REALPATH" ]]; then
        if ! git bundle verify "$BUNDLE_REALPATH" >/dev/null 2>&1 ||             ! git bundle list-heads "$BUNDLE_REALPATH" 2>/dev/null | awk -v head="$TARGET_HEAD" '$1==head {found=1} END {exit(found ? 0 : 1)}'; then
            add_reason "RECOVERY_EVIDENCE_CHANGED"
            archive_missing=1
        fi
    fi
    if [[ -n "$CHECKSUM_REALPATH" ]]; then
        final_manifest_sha="$(sha256sum "$CHECKSUM_REALPATH" 2>/dev/null | awk '{print $1}')"
        final_manifest_rc=$?
        if [[ "$final_manifest_rc" -ne 0 || -z "$final_manifest_sha" || "$final_manifest_sha" != "$CHECKSUM_MANIFEST_SHA" ]] ||             ! sha256sum -c --strict --status "$CHECKSUM_REALPATH" >/dev/null 2>&1; then
            add_reason "RECOVERY_EVIDENCE_CHANGED"
            archive_missing=1
        fi
    fi
    if ! load_worktree_metadata; then
        add_reason "WORKTREE_REVALIDATION_FAILED"
        archive_missing=1
    else
        final_cleanup_idx="$(worktree_index "$CLEANUP_TARGET_REALPATH" || true)"
        if [[ -z "$final_cleanup_idx" ]]; then
            add_reason "WORKTREE_REVALIDATION_FAILED"
            archive_missing=1
        else
            final_target_git_raw="$(git -C "$CLEANUP_TARGET_REALPATH" rev-parse --path-format=absolute --git-dir 2>/dev/null)"
            final_target_git_rc=$?
            final_target_git_real="$(realpath -e "$final_target_git_raw" 2>/dev/null || true)"
            if [[ "$final_target_git_rc" -ne 0 || "${WT_HEADS[$final_cleanup_idx]:-}" != "$TARGET_HEAD" || "${WT_BRANCHES[$final_cleanup_idx]:-}" != "$TARGET_BRANCH" || -z "$final_target_git_real" || "$final_target_git_real" != "$TARGET_GIT_DIR_REALPATH" ]]; then
                add_reason "WORKTREE_REVALIDATION_FAILED"
                archive_missing=1
            fi
            if [[ "${WT_PRUNABLE_FLAGS[$final_cleanup_idx]:-0}" -eq 1 ]]; then
                add_reason "WORKTREE_PRUNABLE"
                archive_missing=1
            fi
            if [[ "${WT_LOCKED_FLAGS[$final_cleanup_idx]:-0}" -eq 1 ]]; then
                add_reason "WORKTREE_LOCKED"
                archive_missing=1
            fi
        fi
    fi

    validate_proc_view
    scan_cleanup_processes
    add_reason "DESTRUCTIVE_CLEANUP_ATOMICITY_UNPROVEN"
    if [[ "$archive_missing" -ne 0 ]]; then
        ARCHIVE_REQUIREMENT_STATE="MISSING"
    fi
fi

if [[ "$CODING_FILTER_SAFE" -eq 1 ]]; then
    probe_filter_configuration "$WORKSPACE"
    final_filter_rc=$?
    if [[ "$final_filter_rc" -ne 0 ]]; then
        add_reason "CODING_STATE_CHANGED"
    else
        final_coding_head="$(git rev-parse HEAD 2>/dev/null)"
        final_coding_head_rc=$?
        final_branch_value="$(git symbolic-ref --quiet --short HEAD 2>/dev/null)"
        final_branch_rc=$?
        if [[ "$BRANCH" == "DETACHED" ]]; then
            [[ "$final_branch_rc" -eq 1 ]] || add_reason "CODING_STATE_CHANGED"
        elif [[ "$final_branch_rc" -ne 0 || "$final_branch_value" != "$BRANCH" ]]; then
            add_reason "CODING_STATE_CHANGED"
        fi
        if [[ "$final_coding_head_rc" -ne 0 || "$final_coding_head" != "$HEAD" ]]; then
            add_reason "CODING_STATE_CHANGED"
        fi
        final_identity_name="$(git config --get user.name 2>/dev/null)"; final_identity_name_rc=$?
        final_identity_email="$(git config --get user.email 2>/dev/null)"; final_identity_email_rc=$?
        if [[ "$final_identity_name_rc" -ne 0 || "$final_identity_email_rc" -ne 0 || "$final_identity_name" != "$CODING_POLICY_IDENTITY_NAME" || "$final_identity_email" != "$CODING_POLICY_IDENTITY_EMAIL" ]]; then
            add_reason "CODING_POLICY_CHANGED"
        fi
        if [[ "$BRANCH" != "DETACHED" && "$BRANCH" != "UNKNOWN" ]]; then
            final_upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; final_upstream_rc=$?
            if [[ "$CODING_POLICY_UPSTREAM" == "NONE" ]]; then
                final_upstream_remote="$(git config --get "branch.$BRANCH.remote" 2>/dev/null)"; final_upstream_remote_rc=$?
                final_upstream_merge="$(git config --get "branch.$BRANCH.merge" 2>/dev/null)"; final_upstream_merge_rc=$?
                if [[ "$final_upstream_rc" -eq 0 || "$final_upstream_remote_rc" -ne 1 || "$final_upstream_merge_rc" -ne 1 ]]; then
                    add_reason "CODING_POLICY_CHANGED"
                fi
            elif [[ "$final_upstream_rc" -ne 0 || "$final_upstream" != "$CODING_POLICY_UPSTREAM" ]]; then
                add_reason "CODING_POLICY_CHANGED"
            else
                final_divergence="$(git rev-list --left-right --count "HEAD...$final_upstream" 2>/dev/null)"; final_divergence_rc=$?
                if [[ "$final_divergence_rc" -ne 0 ]] || ! read -r final_ahead final_behind <<<"$final_divergence" || [[ "$final_ahead" != "$CODING_POLICY_AHEAD" || "$final_behind" != "$CODING_POLICY_BEHIND" ]]; then
                    add_reason "CODING_POLICY_CHANGED"
                fi
            fi
            final_push_fields="$(git for-each-ref --format='%(push:remotename)|%(push:short)|%(push:remoteref)' "refs/heads/$BRANCH" 2>/dev/null)"; final_push_fields_rc=$?
            if [[ "$final_push_fields_rc" -ne 0 || "$final_push_fields" != "$CODING_POLICY_PUSH_FIELDS" ]]; then
                add_reason "CODING_POLICY_CHANGED"
            fi
            if [[ "$PUSH_REMOTE" != "NONE" ]]; then
                final_push_url="$(git remote get-url --push "$PUSH_REMOTE" 2>/dev/null)"; final_push_url_rc=$?
                if [[ "$final_push_url_rc" -ne 0 || "$final_push_url" != "$CODING_POLICY_PUSH_URL" ]]; then
                    add_reason "CODING_POLICY_CHANGED"
                fi
            fi
        fi
        final_config_sha="$(snapshot_coding_config)"; final_config_rc=$?
        if [[ "$final_config_rc" -ne 0 || "$final_config_sha" != "$CODING_CONFIG_SHA" ]]; then
            add_reason "CODING_POLICY_CHANGED"
        fi
        if final_status_sha="$(git status --porcelain=v1 -z -uall --ignore-submodules=none 2>/dev/null | sha256sum | awk '{print $1}')"; then
            [[ -n "$CODING_STATUS_SHA" && "$final_status_sha" == "$CODING_STATUS_SHA" ]] || add_reason "CODING_STATE_CHANGED"
        else
            add_reason "CODING_STATE_CHANGED"
        fi
        final_index_raw="$(git rev-parse --git-path index 2>/dev/null)"
        final_index_path=""
        if [[ "$final_index_raw" == /* ]]; then
            final_index_path="$(realpath -e "$final_index_raw" 2>/dev/null || true)"
        elif [[ -n "$final_index_raw" ]]; then
            final_index_path="$(realpath -e "$WORKSPACE/$final_index_raw" 2>/dev/null || true)"
        fi
        final_index_sha="$(sha256sum "$final_index_path" 2>/dev/null | awk '{print $1}')"
        final_index_sha_rc=$?
        final_index_meta="$(stat -Lc '%d:%i:%s:%y' "$final_index_path" 2>/dev/null)"
        final_index_meta_rc=$?
        if [[ "$final_index_sha_rc" -ne 0 || "$final_index_meta_rc" -ne 0 || "$final_index_path" != "$CODING_INDEX_PATH" || "$final_index_sha" != "$CODING_INDEX_SHA" || "$final_index_meta" != "$CODING_INDEX_META" ]]; then
            add_reason "CODING_STATE_CHANGED"
        fi
        if ! load_worktree_metadata; then
            add_reason "WORKTREE_REVALIDATION_FAILED"
        else
            final_git_dir="$(git rev-parse --path-format=absolute --git-dir 2>/dev/null)"; final_git_dir_rc=$?
            final_git_common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; final_git_common_rc=$?
            if [[ "$final_git_dir_rc" -ne 0 || "$final_git_common_rc" -ne 0 ]]; then
                add_reason "WORKTREE_REVALIDATION_FAILED"
            else
                validate_worktree_admin_binding "$WORKSPACE" "$final_git_dir" "$final_git_common" || true
            fi
            final_current_idx="$(worktree_index "$WORKSPACE" || true)"
            if [[ -z "$final_current_idx" || "${WT_HEADS[$final_current_idx]:-}" != "$HEAD" || "${WT_PRUNABLE_FLAGS[$final_current_idx]:-0}" -ne 0 || "${WT_LOCKED_FLAGS[$final_current_idx]:-0}" -ne 0 ]]; then
                add_reason "WORKTREE_REVALIDATION_FAILED"
            elif [[ "$BRANCH" == "DETACHED" ]]; then
                [[ -z "${WT_BRANCHES[$final_current_idx]:-}" ]] || add_reason "WORKTREE_REVALIDATION_FAILED"
            elif [[ "${WT_BRANCHES[$final_current_idx]:-}" != "refs/heads/$BRANCH" ]]; then
                add_reason "WORKTREE_REVALIDATION_FAILED"
            fi
        fi
    fi
fi

if [[ "${#reasons[@]}" -eq 0 ]]; then
    PREFLIGHT="PASS"
    emit_result
    if [[ "${#GIT_EXEC_ARGS[@]}" -gt 0 ]]; then
        exec /usr/bin/git "${GIT_EXEC_ARGS[@]:1}"
        exit 127
    fi
    exit 0
fi

PREFLIGHT="BLOCKED"
emit_result
exit 2
