from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
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


@contextmanager
def _git_auth_environment(token: str | None):
    if not token:
        yield None
        return

    askpass_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as askpass:
            askpass_path = Path(askpass.name)
            askpass.write(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  *Username*) printf '%s\\n' \"x-access-token\" ;;\n"
                "  *Password*) printf '%s\\n' \"$GPMPE_GIT_TOKEN\" ;;\n"
                "  *) printf '%s\\n' \"$GPMPE_GIT_TOKEN\" ;;\n"
                "esac\n"
            )
        askpass_path.chmod(0o700)
        yield {
            **os.environ,
            "GIT_ASKPASS": str(askpass_path),
            "GIT_TERMINAL_PROMPT": "0",
            "GPMPE_GIT_TOKEN": token,
        }
    finally:
        if askpass_path is not None:
            askpass_path.unlink(missing_ok=True)


def _run_git(
    repo_root: Path,
    args: list[str],
    *,
    user_name: str,
    user_email: str,
    env: dict[str, str] | None = None,
) -> str:
    command = ["git", "-c", f"user.name={user_name}", "-c", f"user.email={user_email}"]
    if env is not None and "GIT_ASKPASS" in env:
        command.extend(["-c", "credential.helper="])
    command.extend(args)
    result = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, check=False, env=env)
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
    remote_url: str | None = None,
    branch: str = "HEAD",
    lock_timeout_seconds: float = 30.0,
    credential_secret: str | None = None,
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
            with _git_auth_environment(credential_secret) as env:
                push_remote = remote_url or remote
                _run_git(repo_root, ["push", push_remote, branch], user_name=user_name, user_email=user_email, env=env)
        
        return commit_id


def changed_paths_for_paths(
    repo_root: Path,
    paths: list[Path],
    *,
    user_name: str,
    user_email: str,
    lock_timeout_seconds: float = 30.0,
) -> list[str]:
    if not (repo_root / ".git").exists():
        raise GitStoreError(f"No git repository found at '{repo_root}'")

    with _git_operation_lock(repo_root, timeout_seconds=lock_timeout_seconds):
        relative_paths = _relative_repo_paths(repo_root.resolve(), paths)
        status = _run_git(
            repo_root,
            ["status", "--porcelain", "--", *relative_paths],
            user_name=user_name,
            user_email=user_email,
        )

    changed: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        path = line[2:].strip() if len(line) > 2 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path.strip())
    return changed


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
