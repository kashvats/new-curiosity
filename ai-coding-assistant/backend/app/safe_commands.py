"""Constrained subprocess execution for agent verification.

An executable allowlist alone is not enough: `python -c` or `git reset --hard` can
be destructive. This module therefore validates both executable and subcommand.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from app.config import settings


@dataclass
class CommandResult:
    args: list[str]
    status: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["passed"] = self.passed
        return data


def _resolve_cwd(project_root: str | Path, cwd: str | None) -> Path:
    root = Path(project_root).resolve()
    target = root if not cwd else (root / cwd).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Command cwd escapes candidate project") from exc
    if not target.is_dir():
        raise ValueError(f"Command cwd does not exist: {target}")
    return target


def _block_path_escape_args(args: Sequence[str]) -> None:
    for raw in args[1:]:
        value = raw.split("=", 1)[-1] if "=" in raw else raw
        if "../" in value.replace("\\", "/") or value == "..":
            raise ValueError("Command argument contains parent-directory traversal")
        if value.startswith(("/", "~")):
            raise ValueError("Absolute/home paths are not allowed in agent commands")


def _validate_subcommand(args: Sequence[str]) -> None:
    exe = Path(args[0]).name
    tail = list(args[1:])
    if exe in {"python", "python3"}:
        if len(tail) < 2 or tail[0] != "-m" or tail[1] not in {"compileall", "pytest"}:
            raise ValueError("Agent Python execution is limited to '-m compileall' and '-m pytest'")
    elif exe == "git":
        if not tail or tail[0] not in {"status", "diff", "show", "log", "rev-parse"}:
            raise ValueError("Agent git execution is read-only")
    elif exe == "npm":
        if not tail:
            raise ValueError("npm subcommand is required")
        if tail[0] == "test":
            return
        if len(tail) >= 2 and tail[0] == "run" and tail[1] in {"test", "lint", "typecheck", "check", "build"}:
            return
        raise ValueError("Agent npm execution is limited to test/lint/typecheck/check/build scripts")
    elif exe == "ruff":
        if not tail or tail[0] != "check":
            raise ValueError("Agent ruff execution is limited to 'ruff check'")
    elif exe in {"pytest", "mypy"}:
        return
    else:
        raise ValueError(f"No safe subcommand policy exists for executable '{exe}'")


def validate_args(args: Sequence[str]) -> list[str]:
    if not args or not all(isinstance(v, str) and v for v in args):
        raise ValueError("Command args must be a non-empty string array")
    executable = Path(args[0]).name
    configured = getattr(settings, "AGENT_ALLOWED_EXECUTABLES", "")
    allowed = set(configured if isinstance(configured, (list, tuple, set)) else [v.strip() for v in str(configured).split(",") if v.strip()])
    if executable not in allowed:
        raise ValueError(f"Executable '{executable}' is not allowed for agents")
    blocked_tokens = {"&&", "||", ";", "|", ">", ">>", "<"}
    if any(token in blocked_tokens for token in args):
        raise ValueError("Shell control tokens are not allowed")
    _block_path_escape_args(args)
    _validate_subcommand(args)
    return list(args)


def run_safe_command(
    project_root: str | Path,
    args: Sequence[str],
    *,
    cwd: str | None = None,
    timeout_seconds: int | None = None,
    env_allowlist: Iterable[str] = ("PATH", "HOME", "USER", "TMPDIR", "TEMP", "PYTHONPATH"),
) -> CommandResult:
    import time

    checked_args = validate_args(args)
    target_cwd = _resolve_cwd(project_root, cwd)
    timeout = int(timeout_seconds or getattr(settings, "COMMAND_TIMEOUT_SECONDS", 120))
    max_output = int(getattr(settings, "MAX_COMMAND_OUTPUT_CHARS", 40_000))
    clean_env = {k: os.environ[k] for k in env_allowlist if k in os.environ}
    clean_env.setdefault("PYTHONUNBUFFERED", "1")

    started = time.monotonic()
    try:
        proc = subprocess.run(
            checked_args,
            cwd=target_cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean_env,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        return CommandResult(
            args=checked_args,
            status="passed" if proc.returncode == 0 else "failed",
            exit_code=proc.returncode,
            stdout=(proc.stdout or "")[-max_output:],
            stderr=(proc.stderr or "")[-max_output:],
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(checked_args, "timeout", -1, stdout[-max_output:], stderr[-max_output:], elapsed)
