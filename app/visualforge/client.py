from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.visualforge.models import VisualForgeCompiledPrompt, VisualPromptSpec

_ISOLATED_RUNNER = (
    "import runpy,sys; src=sys.argv.pop(1); "
    "sys.path.insert(0, src); runpy.run_module(\"visualforge\", run_name=\"__main__\")"
)


class VisualForgeRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VisualForgeClient:
    def __init__(
        self,
        *,
        root: Path,
        expected_commit: str,
        python_executable: str = "/usr/bin/python3",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.root = root
        self.expected_commit = expected_commit
        self.python_executable = python_executable
        self.timeout_seconds = timeout_seconds

    async def compose(self, spec: VisualPromptSpec) -> VisualForgeCompiledPrompt:
        self._validate_root()
        head = await self._git_head()
        if head != self.expected_commit:
            raise VisualForgeRuntimeError(
                "visualforge_revision_mismatch",
                f"VisualForge HEAD {head} does not match pinned {self.expected_commit}.",
            )
        dirty = await self._git_status()
        if dirty:
            raise VisualForgeRuntimeError(
                "visualforge_worktree_dirty",
                "VisualForge tracked worktree differs from the pinned commit.",
            )
        argv = self._compose_argv(spec)
        stdout = await self._run(argv)
        return self._parse(stdout, spec)

    def _compose_argv(self, spec: VisualPromptSpec) -> list[str]:
        argv = [
            self.python_executable,
            "-I",
            "-c",
            _ISOLATED_RUNNER,
            str(self.root / "src"),
            "compose",
            "--query",
            spec.query,
            "--brief",
            spec.brief,
            "--template",
            spec.template,
            "--adapter",
            spec.adapter,
        ]
        if spec.required_text:
            argv.extend(("--required-text", spec.required_text))
        if spec.aspect_ratio:
            argv.extend(("--aspect-ratio", spec.aspect_ratio))
        return argv

    def _validate_root(self) -> None:
        if not self.root.is_dir():
            raise VisualForgeRuntimeError(
                "visualforge_root_missing",
                f"VisualForge root not found: {self.root}",
            )
        if not (self.root / "src" / "visualforge" / "__main__.py").is_file():
            raise VisualForgeRuntimeError(
                "visualforge_runtime_missing",
                "VisualForge Python module is missing from the pinned root.",
            )

    async def _git_status(self) -> str:
        return await self._run(
            ["git", "-C", str(self.root), "status", "--porcelain", "--untracked-files=all"],
            use_pythonpath=False,
        )

    async def _git_head(self) -> str:
        stdout = await self._run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            use_pythonpath=False,
        )
        head = stdout.strip()
        if not head:
            raise VisualForgeRuntimeError(
                "visualforge_revision_unknown",
                "VisualForge revision could not be determined.",
            )
        return head

    async def _run(
        self,
        argv: list[str],
        *,
        use_pythonpath: bool = True,
    ) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self.root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise VisualForgeRuntimeError(
                "visualforge_process_unavailable", str(error)
            ) from error
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError as error:
            process.kill()
            await process.communicate()
            raise VisualForgeRuntimeError(
                "visualforge_timeout", "VisualForge local execution timed out."
            ) from error
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[:1200]
            raise VisualForgeRuntimeError(
                "visualforge_execution_failed",
                detail or f"VisualForge exited with code {process.returncode}.",
            )
        return stdout.decode("utf-8", errors="strict")

    @staticmethod
    def _parse(stdout: str, spec: VisualPromptSpec) -> VisualForgeCompiledPrompt:
        try:
            payload: Any = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise VisualForgeRuntimeError(
                "visualforge_invalid_json", "VisualForge returned invalid JSON."
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), str):
            raise VisualForgeRuntimeError(
                "visualforge_invalid_contract", "VisualForge response is missing prompt."
            )
        compiled = VisualForgeCompiledPrompt.model_validate(payload)
        if compiled.adapter != spec.adapter:
            raise VisualForgeRuntimeError(
                "visualforge_adapter_mismatch",
                "VisualForge returned a different adapter than requested.",
            )
        if not compiled.provenance_notes:
            raise VisualForgeRuntimeError(
                "visualforge_provenance_missing",
                "VisualForge returned no provenance for the selected VisualDNA.",
            )
        if spec.required_text and compiled.required_text != spec.required_text:
            raise VisualForgeRuntimeError(
                "visualforge_text_fidelity_failed",
                "VisualForge did not preserve the required text exactly.",
            )
        if spec.required_text and spec.required_text not in compiled.prompt:
            raise VisualForgeRuntimeError(
                "visualforge_text_fidelity_failed",
                "VisualForge compiled prompt omitted the required text.",
            )
        return compiled
