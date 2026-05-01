from __future__ import annotations

from pathlib import Path
import subprocess


class GitStoreError(RuntimeError):
    pass


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
) -> str:
    if not (repo_root / ".git").exists():
        raise GitStoreError(f"No git repository found at '{repo_root}'")

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
) -> bool:
    """Pull changes from origin and return True if anything changed."""
    if not (repo_root / ".git").exists():
        return False
    
    before = _run_git(repo_root, ["rev-parse", "HEAD"], user_name=user_name, user_email=user_email)
    
    try:
        _run_git(repo_root, ["pull", "--rebase", remote, branch], user_name=user_name, user_email=user_email)
    except GitStoreError as error:
        # If rebase fails due to conflicts, we might need manual intervention or forced resolution
        raise GitStoreError(f"Sync pull failed: {error}") from error
        
    after = _run_git(repo_root, ["rev-parse", "HEAD"], user_name=user_name, user_email=user_email)
    return before != after
