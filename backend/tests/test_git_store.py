from pathlib import Path
import fcntl
import subprocess

import pytest

from app.git_store import GitStoreError, auto_commit_paths, pull_latest_changes


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


def test_auto_commit_does_not_push_by_default(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    campaign_file = tmp_path / "campaign.yaml"
    campaign_file.write_text("title: Test\n", encoding="utf-8")

    commit_id = auto_commit_paths(
        tmp_path,
        [campaign_file],
        "Save campaign",
        user_name="Test User",
        user_email="test@example.com",
    )

    assert commit_id


def test_auto_commit_reports_push_errors_when_push_enabled(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    campaign_file = tmp_path / "campaign.yaml"
    campaign_file.write_text("title: Test\n", encoding="utf-8")

    with pytest.raises(GitStoreError, match="not appear to be a git repository"):
        auto_commit_paths(
            tmp_path,
            [campaign_file],
            "Save campaign",
            user_name="Test User",
            user_email="test@example.com",
            push_enabled=True,
            remote="missing-remote",
            branch="HEAD",
        )


def test_auto_commit_rejects_paths_outside_repo(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    outside_file = tmp_path.parent / "outside.yaml"
    outside_file.write_text("title: Outside\n", encoding="utf-8")

    with pytest.raises(GitStoreError, match="outside repository root"):
        auto_commit_paths(
            tmp_path,
            [outside_file],
            "Save campaign",
            user_name="Test User",
            user_email="test@example.com",
        )


def test_auto_commit_uses_git_operation_lock(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    campaign_file = tmp_path / "campaign.yaml"
    campaign_file.write_text("title: Test\n", encoding="utf-8")
    lock_path = tmp_path / ".gpmpe-git.lock"
    lock_path.touch()

    with lock_path.open("r+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        with pytest.raises(GitStoreError, match="Timed out waiting for git operation lock"):
            auto_commit_paths(
                tmp_path,
                [campaign_file],
                "Save campaign",
                user_name="Test User",
                user_email="test@example.com",
                lock_timeout_seconds=0,
            )


def test_pull_latest_changes_uses_configured_remote_and_branch(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True, text=True)
    subprocess.run(["git", "init", work], check=True, capture_output=True, text=True)

    seed_file = work / "campaign.yaml"
    seed_file.write_text("title: First\n", encoding="utf-8")
    subprocess.run(["git", "add", "campaign.yaml"], cwd=work, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test User", "-c", "user.email=test@example.com", "commit", "-m", "Initial"],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "branch", "-M", "main"], cwd=work, check=True, capture_output=True, text=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=work, check=True, capture_output=True, text=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=work, check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(clone)], check=True, capture_output=True, text=True)

    seed_file.write_text("title: Second\n", encoding="utf-8")
    subprocess.run(["git", "add", "campaign.yaml"], cwd=work, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test User", "-c", "user.email=test@example.com", "commit", "-m", "Update"],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=work, check=True, capture_output=True, text=True)

    changed = pull_latest_changes(
        clone,
        user_name="Test User",
        user_email="test@example.com",
        remote="origin",
        branch="main",
    )

    assert changed is True
    assert (clone / "campaign.yaml").read_text(encoding="utf-8") == "title: Second\n"
