"""Tests for provenance.run_metadata and evaluation.revisions."""

from __future__ import annotations

import re
import subprocess

import provenance
from evaluation import revisions


def test_run_metadata_records_commit_and_versions():
    meta = provenance.run_metadata()
    assert set(meta) == {"git_commit", "git_dirty", "python", "platform", "packages"}
    assert set(meta["packages"]) == set(provenance.RESULT_PACKAGES)
    # Run from a git checkout, the commit is a full SHA and dirty is a bool.
    assert meta["git_commit"] is None or re.fullmatch(r"[0-9a-f]{40}", meta["git_commit"])
    assert meta["git_dirty"] in (True, False, None)


def test_git_commit_outside_a_checkout_is_none(tmp_path):
    assert provenance.git_commit(tmp_path) == (None, None)


def test_git_commit_reports_a_dirty_tree(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
    (tmp_path / "f.txt").write_text("a", encoding="utf-8")
    git("add", "f.txt")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "f")
    assert provenance.git_commit(tmp_path)[1] is False
    (tmp_path / "f.txt").write_text("b", encoding="utf-8")
    assert provenance.git_commit(tmp_path)[1] is True


def test_status_changes_keep_a_rename_as_one_change():
    """``git status --porcelain -z`` puts a rename's source in a field of its
    own, which may be shorter than an entry; it must not be read as one."""
    raw = b" M a b.csv\0R  new.csv\0o\0MM c\xc3\xa9\0"
    assert provenance._status_changes(raw) == [
        ("a b.csv",), ("new.csv", "o"), ("cé",)]
    assert provenance._status_changes(b"") == []


def test_revisions_are_full_shas_and_unknown_repos_are_unpinned():
    for repo, sha in revisions.REVISIONS.items():
        assert re.fullmatch(r"[0-9a-f]{40}", sha), repo
    assert (revisions.revision_for("openai/whisper-large-v3")
            == revisions.REVISIONS["openai/whisper-large-v3"])
    assert revisions.revision_for("not/a-repo") is None
    assert revisions.revision_for(None) is None
    assert revisions.revisions_used("openai/whisper-medium", None) == {
        "openai/whisper-medium": revisions.REVISIONS["openai/whisper-medium"]}
