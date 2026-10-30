"""CSV-only result writers leave a provenance sidecar (audit finding OUTPUTS-12).

condition_ci and bootstrap_ci write tables with nowhere to record the code
commit, the package versions or the inputs. Each now writes
``<stem>_provenance.json`` beside its table, whose input and artefact
digests do not depend on the checkout's line endings, and whose arguments
leave out the output path, so a regeneration elsewhere differs only in
``run_metadata``.

The sidecar's ``git_dirty`` describes the code and inputs that made the
table. It used to be read after the table had been written, so a committed
table regenerated in place recorded true whenever the new table differed
from the committed one, and on every regeneration after the first, which
had rewritten the sidecar. The tests at the end run the writers in a
throwaway git repository to pin the corrected behaviour.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("numpy")

import provenance
from evaluation import bootstrap_ci, condition_ci
from provenance import sha256_text_file, sidecar_path, write_sidecar

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _write_report(path: Path, rows, crlf: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="" if crlf else "\n", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\r\n" if crlf else "\n")
        writer.writerow(["name", "wer"])
        writer.writerows(rows)


@pytest.fixture()
def cell(tmp_path: Path) -> Path:
    d = tmp_path / "reports"
    base = [(f"utt{i:02d}", 0.1 + (i % 3) / 100) for i in range(30)]
    _write_report(d / "wer_report.csv", base)
    _write_report(d / "wer_report_costly.csv", [(n, w + 0.05) for n, w in base])
    return d


def test_text_digest_ignores_line_endings(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_bytes(b"name,wer\r\nu1,0.1\r\n")
    b.write_bytes(b"name,wer\nu1,0.1\n")
    assert sha256_text_file(a) == sha256_text_file(b)


def test_condition_ci_writes_a_sidecar(cell, tmp_path):
    out = tmp_path / "out" / "cci.csv"
    out.parent.mkdir()
    assert condition_ci.main(["--reports", str(cell), "--primary-condition", "raw",
                              "--bootstrap", "200", "--seed", "3",
                              "--output", str(out)]) == 0
    side = json.loads((out.parent / "cci_provenance.json").read_text(encoding="utf-8"))
    assert side["tool"] == "evaluation.condition_ci"
    assert side["artefact"] == "cci.csv"
    assert side["artefact_sha256_lf"] == sha256_text_file(out)
    assert side["arguments"]["bootstrap"] == 200 and side["arguments"]["seed"] == 3
    assert "output" not in side["arguments"]
    assert [Path(i["path"]).name for i in side["inputs"]] == [
        "wer_report.csv", "wer_report_costly.csv"]
    assert {"git_commit", "packages"} <= set(side["run_metadata"])


def test_bootstrap_ci_writes_a_sidecar(cell, tmp_path):
    out = tmp_path / "wer_ci.csv"
    report = cell / "wer_report.csv"
    assert bootstrap_ci.main(["--report", str(report), "--bootstrap", "200",
                              "--seed", "3", "--output", str(out)]) == 0
    side = json.loads((tmp_path / "wer_ci_provenance.json").read_text(encoding="utf-8"))
    assert side["tool"] == "evaluation.bootstrap_ci"
    assert side["arguments"]["report"] == [report.as_posix()]
    assert side["inputs"][0]["sha256_lf"] == sha256_text_file(report)


def test_a_regeneration_elsewhere_differs_only_in_run_metadata(cell, tmp_path):
    """The same inputs in an LF copy and an output elsewhere: same sidecar
    apart from run_metadata, because digests ignore line endings and the
    output path is not recorded."""
    first, second = tmp_path / "one" / "t.csv", tmp_path / "two" / "t.csv"
    for out in (first, second):
        out.parent.mkdir()
        out.write_text("a,b\n1,2\n", encoding="utf-8")
    report = cell / "wer_report.csv"
    a = write_sidecar(first, tool="x", arguments={"k": 1}, inputs=[report])
    b = write_sidecar(second, tool="x", arguments={"k": 1}, inputs=[report])
    strip = [{k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items()
              if k != "run_metadata"} for p in (a, b)]
    assert strip[0] == strip[1]


def test_a_run_meta_given_by_the_caller_is_recorded_as_given(tmp_path):
    out = tmp_path / "t.csv"
    out.write_text("a,b\n1,2\n", encoding="utf-8")
    meta = {"git_commit": "abc", "git_dirty": False, "python": "3", "platform": "p",
            "packages": {"numpy": "2"}}
    side = json.loads(write_sidecar(out, tool="x", arguments={}, inputs=[],
                                    run_meta=meta).read_text(encoding="utf-8"))
    assert side["run_metadata"] == meta
    assert sidecar_path(out) == tmp_path / "t_provenance.json"


# ---------------------------------------------------------------------------
# git_dirty when a committed table is regenerated in place
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [GIT, "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def checkout(tmp_path):
    """A git repository holding code, a cell of reports and committed tables.

    The reports carry the alignment counts the gains table needs. Each table
    has a committed sidecar beside it, as the repository's
    ``output/evaluation`` does, and the names hold a space and a non-ASCII
    letter, which ``git status`` would quote without ``-z``.
    """
    repo = tmp_path / "repo"
    results = repo / "results é"
    (results / "reports").mkdir(parents=True)
    for name, extra in (("wer_report.csv", 0), ("wer_report_costly.csv", 1)):
        with open(results / "reports" / name, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(["name", "wer", "substitutions", "deletions",
                             "insertions", "reference_words"])
            for i in range(30):
                errors = i % 3 + extra
                writer.writerow([f"utt{i:02d}", errors / 10, errors, 0, 0, 10])
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    for name in ("cci table.csv", "gains.csv", "wer_ci.csv"):
        (results / name).write_text("stale\n", encoding="utf-8")
        sidecar_path(results / name).write_text("{}\n", encoding="utf-8")
    _git(repo, "init", "-q")
    # Persistent, not per call: provenance runs its own git status here.
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture()
def code_checkout(checkout, monkeypatch):
    """Make the writers read the git state of *checkout* instead of this one.

    run_metadata asks for the checkout holding provenance.py, which is the
    code that ran; here the code is taken to live in the temporary
    repository.
    """
    real = provenance.git_commit
    monkeypatch.setattr(
        provenance, "git_commit",
        lambda repo_dir=None, ignore=(): real(checkout if repo_dir is None else repo_dir,
                                               ignore=ignore))
    return checkout


def _dirty(table: Path) -> bool | None:
    side = json.loads(sidecar_path(table).read_text(encoding="utf-8"))
    return side["run_metadata"]["git_dirty"]


def _condition_ci(repo: Path) -> tuple[Path, Path]:
    results = repo / "results é"
    table, gains = results / "cci table.csv", results / "gains.csv"
    assert condition_ci.main(["--reports", str(results / "reports"),
                              "--primary-condition", "raw", "--bootstrap", "200",
                              "--seed", "3", "--output", str(table),
                              "--gains-output", str(gains)]) == 0
    return table, gains


@needs_git
def test_git_commit_leaves_out_the_paths_it_is_told_to_ignore(checkout):
    table = checkout / "results é" / "cci table.csv"
    table.write_text("new\n", encoding="utf-8")
    assert provenance.git_commit(checkout)[1] is True
    assert provenance.git_commit(checkout, ignore=[table])[1] is False
    # A path outside the checkout cannot hide a change inside it.
    assert provenance.git_commit(checkout, ignore=[checkout.parent / "x.csv"])[1] is True
    (checkout / "code.py").write_text("x = 2\n", encoding="utf-8")
    assert provenance.git_commit(checkout, ignore=[table])[1] is True


@needs_git
def test_a_staged_rename_is_ignored_only_when_both_names_are(checkout):
    table = checkout / "results é" / "cci table.csv"
    _git(checkout, "mv", str(table), str(table.with_name("moved.csv")))
    assert provenance.git_commit(checkout, ignore=[table])[1] is True
    assert provenance.git_commit(
        checkout, ignore=[table, table.with_name("moved.csv")])[1] is False


@needs_git
def test_write_sidecar_alone_leaves_out_its_artefact_and_sidecar(checkout):
    table = checkout / "results é" / "cci table.csv"
    table.write_text("new\n", encoding="utf-8")
    write_sidecar(table, tool="x", arguments={}, inputs=[], repo_dir=checkout)
    assert _dirty(table) is False
    (checkout / "code.py").write_text("x = 2\n", encoding="utf-8")
    write_sidecar(table, tool="x", arguments={}, inputs=[], repo_dir=checkout)
    assert _dirty(table) is True


@needs_git
def test_condition_ci_in_place_is_dirty_only_when_the_code_is(code_checkout):
    """Both tables of one run, regenerated in place, then again, then on new code.

    The gains sidecar used to see the main table the same run had just
    written, and a second regeneration before committing saw the first.
    """
    table, gains = _condition_ci(code_checkout)
    # The run really did change tracked files, so the checks are not vacuous.
    assert provenance.git_commit(code_checkout)[1] is True
    assert (_dirty(table), _dirty(gains)) == (False, False)
    _condition_ci(code_checkout)
    assert (_dirty(table), _dirty(gains)) == (False, False)
    (code_checkout / "code.py").write_text("x = 2\n", encoding="utf-8")
    _condition_ci(code_checkout)
    assert (_dirty(table), _dirty(gains)) == (True, True)


@needs_git
def test_bootstrap_ci_in_place_is_dirty_only_when_the_code_is(code_checkout):
    """One table regenerated in place, then again, then on new code."""
    results = code_checkout / "results é"
    table = results / "wer_ci.csv"
    argv = ["--report", str(results / "reports" / "wer_report.csv"),
            "--bootstrap", "200", "--seed", "3", "--output", str(table)]
    assert bootstrap_ci.main(argv) == 0
    assert provenance.git_commit(code_checkout)[1] is True
    assert _dirty(table) is False
    assert bootstrap_ci.main(argv) == 0
    assert _dirty(table) is False
    (code_checkout / "code.py").write_text("x = 2\n", encoding="utf-8")
    assert bootstrap_ci.main(argv) == 0
    assert _dirty(table) is True
