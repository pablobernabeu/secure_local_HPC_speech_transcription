"""The sanitised source archive replaces the identifiers and nothing else.

tools/build_decoder_source_deposit.py writes a ``git archive`` of a commit
with the deployment's user name, project accounts and the paths that hold
them replaced in every text member, and documents each change. These
tests build it from a small throwaway repository, with made-up
identifiers, so they need git but no network and no GPU.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import build_decoder_source_deposit as deposit

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")

USER, PROJECT_A, PROJECT_B = "abc1234", "proj-alpha", "proj-beta"
IDENTIFIERS = (USER, PROJECT_A, PROJECT_B)
EXTRA = (("rival_fit", "other_fit"),)
WHEN = "2026-09-27T15:02:22+00:00"


def _nested_zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as inner:
        inner.writestr("word/document.xml", text)
    return buffer.getvalue()


FILES = {
    "hpc/run.sh": (b"#!/bin/bash\n#   sbatch --account=proj-alpha hpc/run.sh\n"
                   b"cd /data/proj-beta/abc1234/env && ls /home/abc1234\n"),
    # CRLF endings, kept in the blob because autocrlf is off.
    "notes.md": (b"Ran as abc1234 on proj-beta.\r\n"
                 b"Outputs in /data/proj-alpha/abc1234/out, then rival_fit.\r\n"),
    "clean.txt": b"nothing to replace\n",
    "data/blob.bin": b"\x00\x01abc1234\x00\xff",
    "doc.docx": _nested_zip("<w:t>proj-alpha</w:t>"),
}


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": WHEN, "GIT_COMMITTER_DATE": WHEN}
    return subprocess.run(
        [GIT, "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "core.autocrlf=false", *args],
        capture_output=True, text=True, check=True, env=env).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for name, data in FILES.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "add", "--chmod=+x", "hpc/run.sh")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _build(repo: Path, out: Path, **kwargs) -> dict:
    return deposit.build("HEAD", out, USER, PROJECT_A, PROJECT_B, EXTRA, repo, **kwargs)


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_text_members_take_the_table_in_order(tmp_path, repo):
    out = tmp_path / "out" / "source_sanitised.zip"
    record = _build(repo, out)
    members = _members(out)
    assert members["hpc/run.sh"] == (b"#!/bin/bash\n#   sbatch --account=<project-a> hpc/run.sh\n"
                                     b"cd $DATA/env && ls $HOME\n")
    # The line endings, CRLF here, are kept.
    assert members["notes.md"] == (b"Ran as <user> on <project-b>.\r\n"
                                   b"Outputs in $DATA/out, then other_fit.\r\n")
    assert members["clean.txt"] == FILES["clean.txt"]
    # Each member carries its git mode as a Unix one, not the 0600 zipfile
    # would give git archive's attribute-less plain files.
    with zipfile.ZipFile(out) as archive:
        modes = {i.filename: (i.create_system, i.external_attr >> 16)
                 for i in archive.infolist()}
    assert modes["hpc/run.sh"] == (3, 0o100755)
    assert modes["clean.txt"] == modes["SANITISED.md"] == (3, 0o100644)
    assert all(mode == (3, 0o40755) for name, mode in modes.items() if name.endswith("/"))
    # Three replacements in the script and four in the notes.
    assert (record["changed_members"], record["replacements"]) == (2, 7)
    assert record["files_from_commit"] == len(FILES)


def test_binary_members_are_left_unchanged_and_reported(tmp_path, repo):
    out = tmp_path / "source_sanitised.zip"
    record = _build(repo, out)
    members = _members(out)
    assert members["data/blob.bin"] == FILES["data/blob.bin"]
    assert members["doc.docx"] == FILES["doc.docx"]
    # The Word document's identifier is inside its own compressed member.
    assert record["binary_members_with_identifiers"] == ["data/blob.bin", "doc.docx"]
    assert record["members_with_identifiers_after_build"] == ["data/blob.bin", "doc.docx"]
    note = members["SANITISED.md"].decode("utf-8")
    assert "- `data/blob.bin`\n- `doc.docx`\n" in note


def test_the_note_lists_each_changed_member_with_its_original_blob(tmp_path, repo):
    out = tmp_path / "source_sanitised.zip"
    _build(repo, out)
    note = _members(out)["SANITISED.md"].decode("utf-8")
    for path in ("hpc/run.sh", "notes.md"):
        assert f"| `{path}` | `{_git(repo, 'rev-parse', f'HEAD:{path}')}` |" in note
    assert "`clean.txt`" not in note
    for replacement in ("$DATA", "$HOME", "<user>", "<project-a>", "<project-b>", "other_fit"):
        assert f"`{replacement}` |" in note
    # It names no original, in any case.
    assert not any(o in note.lower() for o in (*IDENTIFIERS, "rival_fit"))


def test_the_build_is_reproducible_and_recorded(tmp_path, repo):
    first = _build(repo, tmp_path / "a" / "s.zip")
    second = _build(repo, tmp_path / "b" / "s.zip")
    assert first == second
    data = (tmp_path / "a" / "s.zip").read_bytes()
    assert (first["bytes"], first["sha256"]) == (len(data), deposit._sha256(data))
    assert json.loads((tmp_path / "a" / "s.zip.json").read_text(encoding="utf-8")) == first
    commit = _git(repo, "rev-parse", "HEAD")
    assert first["commit"] == commit
    assert set(first["built_with"]) == {"python", "zlib", "zlib_runtime", "zlib_ng"}
    with zipfile.ZipFile(tmp_path / "a" / "s.zip") as archive:
        names = archive.namelist()
        assert names == sorted(names) and "SANITISED.md" in names
        assert {info.date_time for info in archive.infolist()} == {(2026, 9, 27, 15, 2, 22)}
        assert archive.comment == commit.encode("ascii")


def test_the_zip_comment_is_the_full_commit_as_git_archive_writes_it(tmp_path, repo):
    """tools/build_input_deposit.py --decoder-source refuses a decoder
    source whose comment is not the manifest's 40-character decoder
    commit, so the sanitised copy keeps git archive's comment."""
    original = tmp_path / "source.zip"
    _git(repo, "-c", "core.eol=lf", "archive", "--format=zip", "-o", str(original), "HEAD")
    record = deposit.build(_git(repo, "rev-parse", "--short", "HEAD"), tmp_path / "s.zip",
                           USER, PROJECT_A, PROJECT_B, EXTRA, repo)
    commit = _git(repo, "rev-parse", "HEAD")
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(tmp_path / "s.zip") as built:
        assert built.comment == source.comment == commit.encode("ascii")
    assert len(commit) == 40 and record["zip_comment"] == record["commit"] == commit
    assert record["sanitised"] is True and "SANITISED.md" in record["description"]
    note = _members(tmp_path / "s.zip")["SANITISED.md"].decode("utf-8")
    assert note.startswith("# Sanitised source archive\n\nThis archive is a sanitised copy")


def test_the_source_archive_is_checked_against_the_deposited_one(tmp_path, repo):
    original = tmp_path / "source.zip"
    _git(repo, "-c", "core.eol=lf", "archive", "--format=zip", "-o", str(original), "HEAD")
    record = _build(repo, tmp_path / "s.zip", expect_source=original)
    assert record["source_archive"]["sha256"] == deposit._sha256(original.read_bytes())
    assert record["source_archive"]["checked_against"] == "source.zip"
    other = tmp_path / "other.zip"
    other.write_bytes(original.read_bytes() + b"\0")
    with pytest.raises(ValueError, match="differs"):
        _build(repo, tmp_path / "t.zip", expect_source=other)
    # The copy keeps the original's name, so it must not be written over it.
    with pytest.raises(ValueError, match="overwrite"):
        _build(repo, original, expect_source=original)
    assert deposit._sha256(original.read_bytes()) == record["source_archive"]["sha256"]


def test_a_table_that_would_hide_its_order_is_refused():
    with pytest.raises(ValueError, match="appears in a replacement"):
        deposit.substitution_table("user", PROJECT_A, PROJECT_B)
    with pytest.raises(ValueError, match="distinct"):
        deposit.substitution_table(USER, PROJECT_A, PROJECT_A)


def test_an_original_left_in_another_case_stops_the_build(tmp_path, repo, capsys):
    (repo / "upper.txt").write_text("PROJ-ALPHA\n", encoding="utf-8")
    _git(repo, "add", "upper.txt")
    _git(repo, "commit", "-q", "-m", "upper")
    with pytest.raises(ValueError, match="upper.txt"):
        _build(repo, tmp_path / "s.zip")
    argv = ["--repo", str(repo), "--commit", "HEAD", "--output", str(tmp_path / "c.zip"),
            "--user", USER, "--project-a", PROJECT_A, "--project-b", PROJECT_B,
            "--replace", "rival_fit=other_fit"]
    assert deposit.main(argv) == 2
    assert "upper.txt" in capsys.readouterr().err
    assert not (tmp_path / "c.zip").exists()


def test_the_command_line_writes_the_archive_and_its_record(tmp_path, repo, capsys):
    out = tmp_path / "c.zip"
    argv = ["--repo", str(repo), "--commit", "HEAD", "--output", str(out),
            "--user", USER, "--project-a", PROJECT_A, "--project-b", PROJECT_B,
            "--replace", "rival_fit=other_fit"]
    assert deposit.main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads(out.with_name("c.zip.json").read_text(encoding="utf-8"))
    assert printed == _build(repo, tmp_path / "d" / "c.zip")
    with pytest.raises(SystemExit):
        deposit.main([*argv, "--replace", "no-equals-sign"])
