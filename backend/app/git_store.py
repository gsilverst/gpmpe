from __future__ import annotations

from pathlib import Path
import subprocess


class GitStoreError(RuntimeError):
    pass


def _run_git(repo_root: Path, args: list[str]) -> str:
    command = ["git", *args]
    result = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed"
        raise GitStoreError(detail)
    return result.stdout.strip()


def _relative_repo_paths(repo_root: Path, paths: list[Path]) -> list[str]:
    relative: list[str] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative.append(str(resolved.relative_to(repo_root)))
        except ValueError as error:
            raise GitStoreError(f"Path '{resolved}' is outside repository root '{repo_root}'") from error
    return relative


def auto_commit_paths(repo_root: Path, paths: list[Path], message: str) -> str:
    if not (repo_root / ".git").exists():
        raise GitStoreError(f"No git repository found at '{repo_root}'")

    relative_paths = _relative_repo_paths(repo_root.resolve(), paths)
    _run_git(repo_root, ["add", "--", *relative_paths])

    has_changes = _run_git(repo_root, ["diff", "--cached", "--name-only"]) != ""
    if not has_changes:
        return ""

    _run_git(repo_root, ["commit", "-m", message])
    return _run_git(repo_root, ["rev-parse", "HEAD"])
