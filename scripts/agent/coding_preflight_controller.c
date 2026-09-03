/*
 * Build this controller statically.  It is the trusted pre-exec boundary for
 * coding_preflight.sh: loader and Git overrides are rejected before a dynamic
 * shell or Git binary can be started.
 *
 * Invocation:
 *   coding-preflight-controller --expected-workspace PATH \
 *     [guard policy flags] -- git [git arguments]
 */
#define _XOPEN_SOURCE 700

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

extern char **environ;

#ifndef TRUSTED_GUARD_PATH
#define TRUSTED_GUARD_PATH "/usr/local/libexec/anh-duong/coding_preflight.sh"
#endif
#ifndef TRUSTED_GUARD_REQUIRE_ROOT
#define TRUSTED_GUARD_REQUIRE_ROOT 1
#endif

static const char *const safe_environment[] = {
    "PATH=/usr/bin:/bin",
    "LC_ALL=C",
    "LANG=C",
    "GIT_NO_REPLACE_OBJECTS=1",
    "GIT_OPTIONAL_LOCKS=0",
    "GIT_CONFIG_NOSYSTEM=1",
    "GIT_CONFIG_SYSTEM=/dev/null",
    "GIT_CONFIG_GLOBAL=/dev/null",
    "GIT_CONFIG_COUNT=1",
    "GIT_CONFIG_KEY_0=core.fsmonitor",
    "GIT_CONFIG_VALUE_0=false",
    NULL,
};

static void blocked(const char *reason) {
    printf("CONTROLLER=BLOCKED\nREASON=%s\n", reason);
}

static int unsafe_environment(void) {
    char **entry;

    for (entry = environ; *entry != NULL; ++entry) {
        const char *value = *entry;
        if (strncmp(value, "LD_", 3) == 0 ||
            (strncmp(value, "GIT_", 4) == 0 && strncmp(value, "GIT_PAGER=", 10) != 0) ||
            strncmp(value, "BASH_ENV=", 9) == 0 || strncmp(value, "ENV=", 4) == 0) {
            return 1;
        }
    }
    return 0;
}

static int retarget_option(const char *argument) {
    static const char *const exact[] = {
        "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix",
        "--config-env", "--bare", NULL,
    };
    static const char *const assigned[] = {
        "--git-dir=", "--work-tree=", "--namespace=", "--exec-path=", "--super-prefix=",
        "--config-env=", NULL,
    };
    size_t index;

    if ((strncmp(argument, "-C", 2) == 0 || strncmp(argument, "-c", 2) == 0) &&
        argument[2] != '\0') {
        return 1;
    }
    for (index = 0; exact[index] != NULL; ++index) {
        if (strcmp(argument, exact[index]) == 0) {
            return 1;
        }
    }
    for (index = 0; assigned[index] != NULL; ++index) {
        if (strncmp(argument, assigned[index], strlen(assigned[index])) == 0) {
            return 1;
        }
    }
    return 0;
}

int main(int argc, char **argv) {
    char expected_workspace[PATH_MAX];
    char guard_path[PATH_MAX];
    char **guard_argv;
    const char *expected = NULL;
    struct stat guard_stat;
    int separator = -1;
    int index;
    int policy_start;
    size_t policy_count;
    size_t git_argc;
    size_t out;

    if (unsafe_environment()) {
        blocked("UNSAFE_ENVIRONMENT");
        return 64;
    }
    if (argc < 5 || strcmp(argv[1], "--expected-workspace") != 0) {
        blocked("INVALID_INVOCATION");
        return 64;
    }
    expected = argv[2];
    policy_start = 3;
    for (index = policy_start; index < argc; ++index) {
        if (strcmp(argv[index], "--") == 0) {
            separator = index;
            break;
        }
        if (strcmp(argv[index], "--expected-workspace") == 0 || strcmp(argv[index], "--guard") == 0 ||
            strcmp(argv[index], "--help") == 0 || strcmp(argv[index], "-h") == 0) {
            blocked("INVALID_INVOCATION");
            return 64;
        }
    }
    if (separator < 0 || separator + 2 >= argc || strcmp(argv[separator + 1], "git") != 0) {
        blocked("INVALID_INVOCATION");
        return 64;
    }
    for (index = separator + 2; index < argc; ++index) {
        if (strcmp(argv[index], "--") == 0 || argv[index][0] != '-' || strcmp(argv[index], "-") == 0) {
            break;
        }
        if (retarget_option(argv[index])) {
            blocked("GIT_RETARGET_OPTION");
            return 64;
        }
    }
    if (realpath(expected, expected_workspace) == NULL) {
        blocked("PATH_BINDING_FAILED");
        return 64;
    }
    if (realpath(TRUSTED_GUARD_PATH, guard_path) == NULL || strcmp(guard_path, TRUSTED_GUARD_PATH) != 0 ||
        stat(guard_path, &guard_stat) != 0 || !S_ISREG(guard_stat.st_mode)) {
        blocked("TRUSTED_GUARD_INVALID");
        return 64;
    }
    if (TRUSTED_GUARD_REQUIRE_ROOT &&
        (guard_stat.st_uid != 0 || guard_stat.st_gid != 0 ||
         (guard_stat.st_mode & (S_IWGRP | S_IWOTH)) != 0)) {
        blocked("TRUSTED_GUARD_INVALID");
        return 64;
    }
    if (chdir(expected_workspace) != 0) {
        blocked("PATH_BINDING_FAILED");
        return 64;
    }

    policy_count = (size_t)(separator - policy_start);
    git_argc = (size_t)(argc - separator - 1);
    guard_argv = calloc(policy_count + git_argc + 7, sizeof(*guard_argv));
    if (guard_argv == NULL) {
        blocked("CONTROLLER_ALLOCATION_FAILED");
        return 70;
    }
    guard_argv[0] = "/bin/bash";
    guard_argv[1] = "-p";
    guard_argv[2] = guard_path;
    guard_argv[3] = "--expected-workspace";
    guard_argv[4] = expected_workspace;
    out = 5;
    for (index = policy_start; index < separator; ++index) {
        guard_argv[out++] = argv[index];
    }
    guard_argv[out++] = "--";
    for (index = separator + 1; index < argc; ++index) {
        guard_argv[out++] = argv[index];
    }
    guard_argv[out] = NULL;

    execve("/bin/bash", guard_argv, (char *const *)safe_environment);
    free(guard_argv);
    blocked("GUARD_EXEC_FAILED");
    return 127;
}
