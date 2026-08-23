# Ánh Dương Core — Runbook systemd

## Path truth

```text
HISTORICAL_SOURCE=/home/thadc/AIOS/anh-duong-core
RELEASE_ROOT=/home/thadc/AIOS/releases/anh-duong-core
ACTIVE_RELEASE=/home/thadc/AIOS/releases/anh-duong-core/current
DATA_MIRROR=/mnt/f/AIOS/anh-duong-data
```

`HISTORICAL_SOURCE` is preserved preimage evidence and is **not** the future production deployment target. The immutable release named by the `ACTIVE_RELEASE` symlink owns source, virtual environment, and canonical service unit. SQLite state remains at `/home/thadc/.local/state/anh-duong-core/anh_duong.db`; configuration remains at `/home/thadc/.config/anh-duong-core/.env`.

## Release preflight and first migration

An approved release must first be cloned or checked out at `RELEASE_ROOT/<RELEASE_SHA>`, validated at its exact SHA, provisioned with its dedicated `.venv`, and verified to import `app` only from that release directory. Dependency installation uses the committed project dependency contract; the repository currently has no lockfile, so deployment is **blocked** unless an approved reproducibility evidence set establishes the exact validated package versions.

Before the first migration, capture the existing unit verbatim and its effective settings as the **first-migration preimage**. Do not assume a user unit:

```bash
systemctl show -p FragmentPath -p WorkingDirectory -p ExecStart anh-duong-core.service
```

Use the detected scope and `FragmentPath` for the approved transition and rollback. Only after all release validation succeeds, atomically update `ACTIVE_RELEASE` to the validated immutable directory, install the service unit from that active release, and restart in the detected scope during the approved maintenance window.

## Service installation

From a validated active release, install the unit without restarting production:

```bash
/home/thadc/AIOS/releases/anh-duong-core/current/scripts/install_systemd.sh
```

The installer refuses to use the historical repository, requires a valid `current` symlink and release `.venv`, reloads the detected system unit configuration, and does not restart the service.

## Runtime verification after approved transition

```bash
curl -fsS http://127.0.0.1:8790/health
curl -fsS http://127.0.0.1:8790/ready
```

Verify workers, audit logging, FINAL SYNC end-to-end behavior, and logs using the actual systemd scope detected during preflight.

## Rollback

If any post-transition gate fails, atomically repoint `ACTIVE_RELEASE` to the previous validated release, reload the same detected systemd scope, restart only under the approved rollback procedure, and re-run health/readiness verification. For the first migration, restore the exact preserved unit preimage and its original effective execution paths.

## Development and diagnostics

Repository-local developer commands stay independent of the production release symlink:

```bash
./scripts/dev.sh
./scripts/status.sh
```

Do not use `HISTORICAL_SOURCE` as a future production runtime path.
