# Current Production Golden

This document is a repository-side pointer to the canonical runtime snapshot.

## Canonical source of production truth
Read first:

`/mnt/f/AIOS/anh-duong-checkpoints/CURRENT-GOLDEN.md`

The dated closure artifact for the current baseline is:

`/mnt/f/AIOS/anh-duong-checkpoints/AD-EXECUTION-PRESENCE-UX-1-CLOSED-LOCKED-20260925.md`

## Rules
1. Do not infer production from `main`, a release branch, a worktree, or chat history.
2. Verify fresh systemd, Docker, Core health/ready, configured Core base URL, runtime hashes, and a real Telegram E2E when the checkpoint affects Telegram.
3. Treat `CURRENT-GOLDEN.md` as a pointer, not as stronger evidence than live runtime.
4. Every successful production closure must preserve its dated evidence and then update `CURRENT-GOLDEN.md`.
5. Never overwrite or delete a prior CLOSED/LOCKED evidence artifact to represent a newer state.

## Current snapshot
As of 2026-09-25:
- `AD-EXECUTION-PRESENCE-UX-1 = PASS / CLOSED / LOCKED`.
- Core production: `anh-duong-core.service`, bind `127.0.0.1:8792`.
- OpenClaw: `ad-golden-openclaw-prod`, image `openclaw:2026.7.1-ad-execution-presence-ux-1`.
- Presence plugin runtime SHA256: `2ccc0b20efdec91ad76cd1c06e3852132c82cde6a2f403a58a4a9c64dd63e3df`.
- Source commit for the closed presence checkpoint: `008497ccb632d257858b54db74dc5dba31be3ef5`.
