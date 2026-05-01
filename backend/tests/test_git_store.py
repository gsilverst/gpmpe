from pathlib import Path
import subprocess

import pytest

from app.git_store import GitStoreError, auto_commit_paths


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
