from __future__ import annotations

from contextlib import contextmanager
import fcntl
from pathlib import Path
import subprocess
import time


class GitStoreError(RuntimeError):
    pass


@contextmanager
def _git_operation_lock(repo_root: Path, *, timeout_seconds: float = 30.0):
    lock_path = repo_root / ".gpmpe-git.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() >= deadline:
                    raise GitStoreError(f"Timed out waiting for git operation lock at '{lock_path}'") from error
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _run_git(repo_root: Path, args: list[str], *, user_name: str, user_email: str) -> str:
    command = ["git", "-c", f"user.name={user_name}", "-c", f"user.email={user_email}", *args]
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


def auto_commit_paths(
    repo_root: Path,
    paths: list[Path],
    message: str,
    *,
    user_name: str,
    user_email: str,
    push_enabled: bool = False,
    remote: str = "origin",
    branch: str = "HEAD",
    lock_timeout_seconds: float = 30.0,
) -> str:
    if not (repo_root / ".git").exists():
        raise GitStoreError(f"No git repository found at '{repo_root}'")

    with _git_operation_lock(repo_root, timeout_seconds=lock_timeout_seconds):
        relative_paths = _relative_repo_paths(repo_root.resolve(), paths)
        _run_git(repo_root, ["add", "--", *relative_paths], user_name=user_name, user_email=user_email)

        has_changes = _run_git(repo_root, ["diff", "--cached", "--name-only"], user_name=user_name, user_email=user_email) != ""
        if not has_changes:
            return ""

        _run_git(repo_root, ["commit", "-m", message], user_name=user_name, user_email=user_email)
        commit_id = _run_git(repo_root, ["rev-parse", "HEAD"], user_name=user_name, user_email=user_email)

        if push_enabled:
            _run_git(repo_root, ["push", remote, branch], user_name=user_name, user_email=user_email)
        
        return commit_id


def pull_latest_changes(
    repo_root: Path,
    *,
    user_name: str,
    user_email: str,
    remote: str = "origin",
    branch: str = "HEAD",
    lock_timeout_seconds: float = 30.0,
) -> bool:
    """Pull changes from origin and return True if anything changed."""
    if not (repo_root / ".git").exists():
        return False

    with _git_operation_lock(repo_root, timeout_seconds=lock_timeout_seconds):
        before = _run_git(repo_root, ["rev-parse", "HEAD"], user_name=user_name, user_email=user_email)

        try:
            _run_git(repo_root, ["pull", "--rebase", remote, branch], user_name=user_name, user_email=user_email)
        except GitStoreError as error:
            raise GitStoreError(f"Sync pull failed: {error}") from error

        after = _run_git(repo_root, ["rev-parse", "HEAD"], user_name=user_name, user_email=user_email)
        return before != after
