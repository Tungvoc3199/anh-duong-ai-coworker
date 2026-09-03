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
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

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
        if (strncmp(value, "LD_", 3) == 0 || strncmp(value, "GIT_", 4) == 0 ||
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

static int wait_for_success(pid_t pid) {
    int status;

    if (waitpid(pid, &status, 0) < 0) {
        return 0;
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

static int run_guard(const char *guard, const char *workspace, char *const *policy, size_t policy_count) {
    char **guard_argv;
    pid_t pid;
    size_t index;

    guard_argv = calloc(policy_count + 6, sizeof(*guard_argv));
    if (guard_argv == NULL) {
        return 0;
    }
    guard_argv[0] = "/bin/bash";
    guard_argv[1] = "-p";
    guard_argv[2] = (char *)guard;
    guard_argv[3] = "--expected-workspace";
    guard_argv[4] = (char *)workspace;
    for (index = 0; index < policy_count; ++index) {
        guard_argv[index + 5] = policy[index];
    }

    pid = fork();
    if (pid == 0) {
        execve("/bin/bash", guard_argv, (char *const *)safe_environment);
        _exit(127);
    }
    free(guard_argv);
    return pid > 0 && wait_for_success(pid);
}

static int revalidate_workspace(const char *workspace) {
    char output[PATH_MAX + 2];
    char *const git_argv[] = {"git", "rev-parse", "--show-toplevel", NULL};
    ssize_t bytes;
    size_t used = 0;
    int pipe_fds[2];
    pid_t pid;

    if (pipe(pipe_fds) != 0) {
        return 0;
    }
    pid = fork();
    if (pid == 0) {
        if (dup2(pipe_fds[1], STDOUT_FILENO) < 0) {
            _exit(127);
        }
        close(pipe_fds[0]);
        close(pipe_fds[1]);
        execve("/usr/bin/git", git_argv, (char *const *)safe_environment);
        _exit(127);
    }
    close(pipe_fds[1]);
    while (used < sizeof(output) - 1 &&
           (bytes = read(pipe_fds[0], output + used, sizeof(output) - 1 - used)) > 0) {
        used += (size_t)bytes;
    }
    close(pipe_fds[0]);
    if (bytes != 0 || pid < 0 || !wait_for_success(pid)) {
        return 0;
    }
    if (used == 0 || output[used - 1] != '\n') {
        return 0;
    }
    output[used - 1] = '\0';
    return strlen(workspace) + 1 == used && strcmp(output, workspace) == 0;
}

int main(int argc, char **argv) {
    char expected_workspace[PATH_MAX];
    char guard_candidate[PATH_MAX];
    char guard_path[PATH_MAX];
    char **policy;
    char **git_argv;
    const char *expected = NULL;
    int separator = -1;
    int index;
    int policy_start;
    size_t policy_count;

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
    int guard_len = snprintf(guard_candidate, sizeof(guard_candidate),
                             "%s/scripts/coding_preflight.sh", expected_workspace);
    if (guard_len < 0 || (size_t)guard_len >= sizeof(guard_candidate) ||
        realpath(guard_candidate, guard_path) == NULL || chdir(expected_workspace) != 0) {
        blocked("PATH_BINDING_FAILED");
        return 64;
    }

    policy = &argv[policy_start];
    policy_count = (size_t)(separator - policy_start);
    if (!run_guard(guard_path, expected_workspace, policy, policy_count)) {
        blocked("GUARD_FAILED");
        return 2;
    }
    if (chdir(expected_workspace) != 0 || !revalidate_workspace(expected_workspace)) {
        blocked("WORKSPACE_REVALIDATION_FAILED");
        return 2;
    }

    git_argv = &argv[separator + 1];
    execve("/usr/bin/git", git_argv, (char *const *)safe_environment);
    blocked("GIT_EXEC_FAILED");
    return 127;
}
