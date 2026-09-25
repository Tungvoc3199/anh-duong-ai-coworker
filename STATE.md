# STATE

## Repository metadata
- Package version: `0.1.0`.
- Local-development default API bind: `127.0.0.1:8790`.
- Runtime DB: `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- Database mode: WAL.
- The repository branch is not authoritative production state.

## Production truth
- First verify with `/usr/local/libexec/anh-duong/runtime-truth`.
- Canonical pointer: `/mnt/f/AIOS/anh-duong-checkpoints/CURRENT-GOLDEN.md`.
- Current snapshot date: `2026-09-25`.
- Golden checkpoint: `AD-EXECUTION-PRESENCE-UX-1 = PASS / CLOSED / LOCKED`.
- Core service: `anh-duong-core.service`.
- Active Core release path at the recorded snapshot: `/home/thadc/AIOS/releases/anh-duong-core/ad-semantic-execution-tool-policy-1-29487e2`.
- Production Core bind at the recorded snapshot: `127.0.0.1:8792`.
- OpenClaw Core URL at the recorded snapshot: `http://host.docker.internal:8792`.
- OpenClaw container: `ad-golden-openclaw-prod`.
- OpenClaw image: `openclaw:2026.7.1-ad-execution-presence-ux-1`.
- Presence plugin source commit: `008497ccb632d257858b54db74dc5dba31be3ef5`.
- Presence plugin runtime SHA256: `2ccc0b20efdec91ad76cd1c06e3852132c82cde6a2f403a58a4a9c64dd63e3df`.
- Core OpenClaw executor runtime SHA256: `e15c53c1b290b1baa1b07ffa1a7fa4dabc59d1f9cc1ed5cda51b1abcdbf51fb6`.
- Closure evidence: `/mnt/f/AIOS/anh-duong-checkpoints/AD-EXECUTION-PRESENCE-UX-1-CLOSED-LOCKED-20260925.md`.

Always verify production fresh before mutation. If this snapshot conflicts with runtime, runtime evidence wins and `CURRENT-GOLDEN.md` must be reconciled after verification.
