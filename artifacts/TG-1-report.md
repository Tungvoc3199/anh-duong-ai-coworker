# TG-1 Report

## TG-1 Verdict

```text
PASS
```

Hai Telegram request thật sau bản sửa tối thiểu đều nhận đúng một phản hồi và có evidence xuyên suốt `Telegram → OpenClaw → Core prepare → OpenClaw execution → Telegram`.

## Changes

- Thêm plugin `@anh-duong/openclaw-core-gate` phía OpenClaw với ba hook `before_prompt_build`, `before_agent_run`, `agent_end`.
- Thêm HTTP client validate contract Core, timeout hữu hạn, structured log và fail-closed; không retry và không CLI/direct-model fallback.
- Thêm bốn biến runtime theo tên: `ANH_DUONG_CORE_ENABLED`, `ANH_DUONG_CORE_BASE_URL`, `ANH_DUONG_CORE_INTERNAL_TOKEN`, `ANH_DUONG_CORE_TIMEOUT_SECONDS`.
- Thêm bốn mapping environment vào `openclaw/docker-compose.yml`.
- Kích hoạt plugin dạng managed npm-pack trên filesystem ext4 của OpenClaw; không rebuild/update image.
- Thêm `scripts/verify_tg1_runtime.ps1` để kiểm tra runtime và các hash cấu hình bảo vệ.
- Sau manual attempt đầu, sửa đúng một nguyên nhân trong `app/routing/fast_router.py`: classifier direct chưa nhận diện phép tính ký hiệu ngắn nên rơi vào `workflow.ambiguous_input`. Rule mới chỉ nhận mẫu arithmetic TG-1 hẹp; precedence của workflow side-effect giữ nguyên.
- Thêm regression test nguyên văn request TG-1 vào `tests/unit/test_core_request_pipeline_behavior.py`.

Integration giữ correlation bằng mapping:

```text
OpenClaw runId <uuid> → Core request_id tg-<uuid>
Telegram chat/session → hash hoặc [REDACTED] trong log/artifact
```

Direct dùng Core route `direct`, capability `conversational_response`, `execution_required=false`. Workflow dùng Core route `workflow`, capability `planning`, `execution_required=true` và OpenClaw trả kế hoạch theo contract hiện tại; Async Worker vẫn tắt.

Khi Core timeout, mất kết nối, trả 401/403/5xx hoặc schema sai, hook chặn agent run và trả thông báo an toàn; không bypass Core.

## Verification evidence

### Telegram direct recheck

| Field | Evidence |
|---|---|
| Inbound UTC | `2026-08-01T15:07:05Z` |
| Telegram update reference | `661907925` |
| Inbound message ID | `2375` (ordered same-chat correlation) |
| Response message ID | `2376` |
| Chat/session | `telegram:[REDACTED]`; session `sha256:8776f403220a` |
| OpenClaw correlation ID | `217869a3-7fa6-4e5d-b63a-381bc885596f` |
| Core request ID | `tg-217869a3-7fa6-4e5d-b63a-381bc885596f` |
| Core audit event | `aud_c63d55768ee94acd9958d6aa4165904e` |
| Core prepare | HTTP 200; `direct` / `conversational_response`; execution false |
| OpenClaw execution | Core envelope present; 9Router HTTP 200; status success |
| Telegram response | `42` |
| Duplicate/fallback | 1 send success; 0 send failure; 0 duplicate; 0 fallback |

### Telegram workflow recheck

| Field | Evidence |
|---|---|
| Inbound UTC | `2026-08-01T15:07:16Z` |
| Telegram update reference | `661907926` |
| Inbound message ID | `2377` (ordered same-chat correlation) |
| Response message ID | `2378` |
| Chat/session | `telegram:[REDACTED]`; session `sha256:8776f403220a` |
| OpenClaw correlation ID | `f748a1a3-631d-4e22-a48b-953b637ec923` |
| Core request ID | `tg-f748a1a3-631d-4e22-a48b-953b637ec923` |
| Core audit event | `aud_6022e4fdb0e646938929bf07f00c5694` |
| Core prepare | HTTP 200; `workflow` / `planning`; execution true |
| OpenClaw execution | Core envelope present; 9Router HTTP 200; status success |
| Telegram response | Ba bước read-only: trạng thái, health/status, log; cấm sửa/restart |
| Duplicate/fallback | 1 send success; 0 send failure; 0 duplicate; 0 fallback |

Cả hai cửa sổ log đều có đúng `1 inbound → 1 Core prepare → 1 model execution HTTP 200 → 1 Telegram send`. Core journal ghi hai `POST /api/internal/requests/prepare` HTTP 200. Core audit ghi cùng request ID với OpenClaw.

### Tests and runtime

- TDD route fix RED: 1 failure đúng kỳ vọng (`workflow` thay vì `direct`).
- Targeted GREEN: 45 passed.
- Full Core pytest sau fix: 319 passed, 1 cảnh báo Starlette/httpx đã có.
- Ruff: PASS.
- Mypy: PASS, 65 source files.
- Compileall: PASS.
- Plugin tests trước manual gate: 33/33 trên host, runtime 2026.7.1 và managed package.
- OpenClaw Telegram targeted regression: PASS.
- OpenClaw native command/session suite: 38 passed; 3 lỗi Windows `/tmp` giống baseline, không thuộc TG-1.
- OpenClaw aggregate check trước manual gate bị giới hạn bởi host Node 24.14.0 thấp hơn yêu cầu 24.15.0 và child `pnpm install`; không có source OpenClaw nào khác ngoài Compose bị sửa.
- Verifier cuối: 25 passed, 0 failed.
- Core `/health`: HTTP 200.
- Core `/ready`: HTTP 200.
- Core reachable từ Gateway: HTTP 200.
- Gateway: running và healthy.
- OpenClaw runtime: 2026.7.1; immutable image ID giữ nguyên.
- Telegram: configured, running, polling probe PASS.
- Alembic: `0003 (head)`.
- Async Worker: `false`.

### Configuration integrity

- Telegram token hash: unchanged.
- Telegram config hash: unchanged.
- Agent model/model map hashes: unchanged.
- Provider hash: unchanged.
- 9Router hash: unchanged.
- Secret scan trên Gateway/Core records của hai request: 4 configured candidates, 0 exact occurrence, 0 pattern occurrence.

## Security confirmation

```text
Telegram token unchanged
Model unchanged
Provider unchanged
9Router unchanged
Async Worker remains false
No secret committed
No secret printed in report
No CLI fallback added
No direct-model fallback
No database schema changed
No duplicate Telegram response
```

Không đóng gói `.env`, live `openclaw.json`, backup, database, `.git`, `node_modules` hoặc runtime secret.

## Rollback

Backup: `F:\AIOS\anh-duong-checkpoints\backups\TG-1-20260801T114348Z`

Windows PowerShell — chạy ở bất kỳ thư mục nào:

```powershell
$backup = 'F:\AIOS\anh-duong-checkpoints\backups\TG-1-20260801T114348Z\openclaw'
Copy-Item -LiteralPath "$backup\docker-compose.yml" -Destination 'F:\AIOS\openclaw\docker-compose.yml' -Force
Copy-Item -LiteralPath "$backup\.env" -Destination 'F:\AIOS\openclaw\.env' -Force
```

Ubuntu/WSL — chạy ở bất kỳ thư mục nào:

```bash
cd /mnt/f/AIOS/openclaw
docker exec openclaw-openclaw-gateway-1 sh -lc 'cd /app && node openclaw.mjs plugins uninstall anh-duong-core' || true
cp /mnt/f/AIOS/anh-duong-checkpoints/backups/TG-1-20260801T114348Z/openclaw/openclaw.json /home/thadc/.openclaw/openclaw.json
chown thadc:thadc /home/thadc/.openclaw/openclaw.json
chmod 600 /home/thadc/.openclaw/openclaw.json
OPENCLAW_IMAGE=openclaw:2026.7.1-codex-runtime-verified-local docker compose up -d --no-deps --force-recreate openclaw-gateway
```

Ubuntu/WSL — chạy trong: `/mnt/f/AIOS/anh-duong-core`

```bash
git apply -R --unidiff-zero artifacts/TG-1-route-direct-fix.patch
sudo systemctl restart anh-duong-core.service
```

Windows PowerShell — chạy ở bất kỳ thư mục nào:

```powershell
& 'F:\AIOS\anh-duong-core\scripts\verify_tg1_runtime.ps1'
```

Không chạy `docker compose down -v`, không xóa volume/state/SQLite. Rollback chưa được thực thi vì TG-1 đang PASS.

## Artifacts

- `F:\AIOS\anh-duong-checkpoints\TG-1-overlay.zip`
- `F:\AIOS\anh-duong-checkpoints\TG-1-overlay-content.md`
- `F:\AIOS\anh-duong-checkpoints\TG-1-report.md`
- `F:\AIOS\anh-duong-checkpoints\TG-1-runtime.log`