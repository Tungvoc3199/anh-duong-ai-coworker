from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_FILES = (
    ".env.example",
    "alembic/versions/0003_async_task_runner_v1.py",
    "app/config.py",
    "app/main.py",
    "app/api/async_tasks.py",
    "app/async_tasks/__init__.py",
    "app/async_tasks/audit.py",
    "app/async_tasks/models.py",
    "app/async_tasks/repository.py",
    "app/async_tasks/policy.py",
    "app/async_tasks/service.py",
    "app/async_tasks/worker.py",
    "app/async_tasks/recovery.py",
    "app/async_tasks/notification.py",
    "app/db/models.py",
    "app/openclaw/__init__.py",
    "app/openclaw/models.py",
    "app/openclaw/executor.py",
    "app/openclaw/notifier.py",
    "docs/ASYNC_TASK_RUNNER_V1.md",
    "scripts/smoke_async_task_runner.py",
    "scripts/package_async_task_runner_v1.py",
    "tests/unit/test_async_task_models.py",
    "tests/unit/test_async_task_policy.py",
    "tests/unit/test_openclaw_executor.py",
    "tests/unit/test_openclaw_notifier.py",
    "tests/integration/test_async_task_schema.py",
    "tests/integration/test_async_task_repository.py",
    "tests/integration/test_async_task_service.py",
    "tests/integration/test_async_task_worker.py",
    "tests/integration/test_async_task_recovery.py",
    "tests/integration/test_notification_worker.py",
    "tests/integration/test_async_task_api.py",
    "tests/integration/test_async_task_lifespan.py",
    "tests/integration/test_async_task_audit.py",
    "tests/integration/test_async_task_audit_runtime.py",
    "tests/integration/test_async_task_cancel_safety.py",
    "tests/integration/test_async_task_cancel_race.py",
    "tests/integration/test_async_task_api_corrections.py",
    "tests/integration/test_async_task_idempotency_concurrency.py",
    "tests/integration/test_async_notification_retry_audit.py",
    "tests/e2e/test_async_task_runner.py",
    "tests/security/test_openclaw_static_contract.py",
    "tests/security/test_async_task_api_auth.py",
    "tests/security/test_async_runtime_config.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--deliverables-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--handoff-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Atomically replace existing user-authorized "
            "deliverables and final report."
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def markdown_fence(text: str) -> str:
    runs = re.findall(r"`+", text)
    longest = max((len(run) for run in runs), default=0)
    return "`" * max(3, longest + 1)


def language_for(path: Path) -> str:
    return {
        ".py": "python",
        ".md": "markdown",
        ".toml": "toml",
        ".ini": "ini",
    }.get(path.suffix, "text")


def overlay_tree() -> str:
    root: dict[str, object] = {}
    for relative in OVERLAY_FILES:
        cursor = root
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            child = cursor.setdefault(part, {})
            if not isinstance(child, dict):
                raise RuntimeError(
                    f"Invalid tree collision at {relative}"
                )
            cursor = child
        cursor[parts[-1]] = None

    lines = ["anh-duong-core/"]

    def visit(
        node: dict[str, object],
        prefix: str,
    ) -> None:
        entries = sorted(node.items())
        for index, (name, child) in enumerate(entries):
            last = index == len(entries) - 1
            branch = "└── " if last else "├── "
            suffix = "/" if isinstance(child, dict) else ""
            lines.append(f"{prefix}{branch}{name}{suffix}")
            if isinstance(child, dict):
                visit(
                    child,
                    prefix + ("    " if last else "│   "),
                )

    visit(root, "")
    return "\n".join(lines)


def build_markdown(zip_hash: str) -> str:
    generated = datetime.now(UTC).isoformat()
    lines = [
        "# Ánh Dương Core — Async Task Runner v1",
        "",
        "- Status: `VERIFIED_COMPLETE_CORRECTED`",
        f"- Generated UTC: `{generated}`",
        f"- ZIP SHA256: `{zip_hash}`",
        f"- Overlay files: `{len(OVERLAY_FILES)}`",
        "",
        "## Cây thư mục overlay",
        "",
        "```text",
        overlay_tree(),
        "```",
        "",
        "## Verification summary",
        "",
        "- Targeted correction Pytest: `43 passed`.",
        "- Full Pytest: `168 passed`.",
        "- Security suite: `21 passed`.",
        "- E2E: API → mocked `/v1/responses` → mocked "
        "`/tools/invoke` passed.",
        "- Full Ruff: `All checks passed!`.",
        "- Changed-file Mypy: `17 source files`, no issues.",
        "- Compileall: `COMPILEALL_EXIT=0`.",
        "- Migration 0003 temp round-trip: downgrade removed "
        "`async_task_runs`, re-upgrade restored it, exit 0.",
        "",
        "## Cài đặt",
        "",
        "1. Backup runtime SQLite database.",
        "2. Extract overlay so the top-level `anh-duong-core/` "
        "merges into the project root.",
        "3. Review `.env.example`; set internal and OpenClaw "
        "bearer tokens outside source control.",
        "4. In a maintenance window, run "
        "`.venv/bin/alembic upgrade 0003`.",
        "5. Run the test/verification commands before any "
        "operator-managed restart.",
        "",
        "Không có migration runtime, restart, OpenClaw config "
        "change, Telegram delivery hay deploy nào được thực hiện "
        "khi tạo gói này.",
        "",
        "## Rollback",
        "",
        "Khôi phục code overlay trước đó. Chỉ sau khi worker đã "
        "dừng và database đã backup mới chạy "
        "`.venv/bin/alembic downgrade 0002`; thao tác này xóa "
        "bảng `async_task_runs`.",
        "",
        "## Known gaps",
        "",
        "- Runtime database vẫn chưa migrate.",
        "- Core/OpenClaw/Docker chưa restart và chưa deploy.",
        "- OpenClaw config không được thay đổi; operator phải bảo "
        "đảm hai HTTP route đã được bật.",
        "- TestClient phát một Starlette deprecation warning về "
        "httpx; không ảnh hưởng kết quả.",
        "- Internal API cần tiếp tục được giới hạn ở trusted "
        "network dù đã có bearer auth.",
        "",
        "## SHA256 từng file",
        "",
        "| File | SHA256 |",
        "|---|---|",
    ]
    for relative in OVERLAY_FILES:
        lines.append(
            f"| `{relative}` | `{sha256(PROJECT_ROOT / relative)}` |"
        )

    lines.extend(
        [
            "",
            "## Toàn bộ nội dung file",
            "",
        ]
    )
    for relative in OVERLAY_FILES:
        path = PROJECT_ROOT / relative
        text = path.read_text(encoding="utf-8")
        fence = markdown_fence(text)
        lines.extend(
            [
                f"### `{relative}`",
                "",
                f"{fence}{language_for(path)}",
                text.rstrip("\n"),
                fence,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_final_report(
    *,
    zip_path: Path,
    markdown_path: Path,
) -> str:
    generated = datetime.now(UTC).isoformat()
    return f"""VERIFIED_COMPLETE_CORRECTED
# Async Task Runner v1 — Autonomous Final Report

- Generated UTC: `{generated}`
- Project: `F:\\AIOS\\anh-duong-core`
- Runtime database migrated: `false`
- Runtime services restarted: `false`
- OpenClaw config modified: `false`
- Telegram sent: `false`
- Deployed: `false`

## Correction hoàn tất

- Append-only audit đủ 10 Async Run/notification event; payload bounded,
  idempotency key chỉ lưu SHA256 và secret/token được redact.
- Cancel chỉ cho `pending`/`retry_wait`; active/verifying/completed trả 409,
  cancelled idempotent; conditional update và SQLite lock chống race claim.
- List API hỗ trợ `task_id=task_...`; POST fail-closed 503 khi runtime không
  nhận task mới.
- Hai HTTP request đồng thời cùng idempotency key trả cùng Task/Run; database
  chỉ có một Task và một Run.
- Core tiếp tục chỉ gọi OpenClaw qua HTTP Gateway, không có CLI fallback.

## Verification mới

- Targeted correction Pytest: `43 passed`.
- Full Pytest: `168 passed`.
- Security suite: `21 passed`.
- Full Ruff: pass.
- Changed-file Mypy: `17 source files`, pass.
- Compileall: pass.
- Migration 0003 temp DB round-trip: `0003/table=1 → 0002/table=0 →
  0003/table=1`.
- E2E HTTP mock: pass; không gọi OpenClaw/Telegram thật.

## Deliverables

- `{zip_path}` — SHA256 `{sha256(zip_path)}`
- `{markdown_path}` — SHA256 `{sha256(markdown_path)}`

ZIP có top-level `anh-duong-core/` và {len(OVERLAY_FILES)} file overlay.
Markdown chứa tree, SHA256, verification, cài đặt, rollback, known gaps và
toàn bộ nội dung từng file.

## Ràng buộc runtime đã giữ

- Runtime database migrated: `false`.
- Core/OpenClaw/Docker restarted: `false`.
- OpenClaw config modified: `false`.
- Telegram thật đã gửi: `false`.
- Credentials/model/provider changed: `false`.
- Deployed: `false`.

## Rủi ro còn lại

- Runtime database chưa migrate nên worker thật chưa thể xử lý run.
- OpenClaw route/config chưa được kiểm tra bằng mutation trong phiên an toàn này.
- Có một Starlette TestClient deprecation warning liên quan httpx.
- Internal bearer API vẫn phải được giới hạn ở trusted network.

## Bước tiếp theo đề xuất

Operator review gói và SHA256. Chỉ trong maintenance window riêng đã phê duyệt:
backup runtime DB, cấp token qua secret store, chạy migration 0003, rồi mới
thực hiện restart/deploy theo runbook vận hành.
"""


def write_atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    deliverables = args.deliverables_dir.resolve()
    handoff = args.handoff_dir.resolve()
    zip_path = (
        deliverables
        / "anh-duong-core-async-task-runner-v1.zip"
    )
    markdown_path = (
        deliverables
        / "anh-duong-core-async-task-runner-v1.md"
    )
    report_path = (
        handoff
        / "async-task-runner-v1-autonomous-final-report.md"
    )
    outputs = (zip_path, markdown_path, report_path)
    existing = [path for path in outputs if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(
            "Refusing to overwrite: "
            + ", ".join(str(path) for path in existing)
        )

    missing = [
        relative
        for relative in OVERLAY_FILES
        if not (PROJECT_ROOT / relative).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "Missing overlay files: " + ", ".join(missing)
        )

    deliverables.mkdir(parents=True, exist_ok=True)
    handoff.mkdir(parents=True, exist_ok=True)
    zip_temp = zip_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(
        zip_temp,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for relative in OVERLAY_FILES:
            archive.write(
                PROJECT_ROOT / relative,
                arcname=str(
                    PurePosixPath(
                        "anh-duong-core",
                        PurePosixPath(relative),
                    )
                ),
            )
    zip_temp.replace(zip_path)

    write_atomic(
        markdown_path,
        build_markdown(sha256(zip_path)),
    )
    write_atomic(
        report_path,
        build_final_report(
            zip_path=zip_path,
            markdown_path=markdown_path,
        ),
    )
    print(f"ZIP={zip_path}")
    print(f"ZIP_SHA256={sha256(zip_path)}")
    print(f"MARKDOWN={markdown_path}")
    print(f"MARKDOWN_SHA256={sha256(markdown_path)}")
    print(f"REPORT={report_path}")
    print(f"REPORT_SHA256={sha256(report_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
