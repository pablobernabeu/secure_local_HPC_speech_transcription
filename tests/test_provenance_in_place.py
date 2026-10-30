"""Three more writers read the git state before they write (OUTPUTS-12).

evaluation.sweep_aggregate, evaluation.benchmark_timestamps and
evaluation.wer each write more than one file and record
provenance.run_metadata() in the last. They used to read it after the
first had been written, so a regeneration in place in a checkout counted
an output as a change to the tree whenever it differed from the committed
copy: at once for an output written before the read, and from the second
regeneration on for one written after it. Each now reads the state once,
before anything is written, leaving out the files it rewrites, as
condition_ci, bootstrap_ci and benchmark_anonymisation already do
(tests/test_provenance_sidecars.py, tests/test_s1_anon_report.py).

Each test regenerates tracked outputs of a throwaway git repository in
place: twice on unchanged code, which must record a clean tree, then once
after a tracked code file has changed, which must record a dirty one.
Nothing needs a model, a corpus or jiwer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

import provenance
from evaluation import benchmark_timestamps as bt
from evaluation import sweep_aggregate as agg
from evaluation import wer

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _git(repo: Path, *args: str) -> None:
    subprocess.run([GIT, "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    *args], check=True, capture_output=True, text=True)


def _checkout(tmp_path: Path, monkeypatch, outputs: list[str]) -> Path:
    """A git repository holding code.py and committed stand-ins for *outputs*.

    *outputs* are paths relative to the repository. run_metadata asks for
    the checkout that holds provenance.py, the code that ran; here that
    code is taken to live in this repository.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    for name in outputs:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale\n", encoding="utf-8")
    _git(repo, "init", "-q")
    # Persistent, not per call: provenance runs its own git status here.
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    real = provenance.git_commit
    monkeypatch.setattr(
        provenance, "git_commit",
        lambda repo_dir=None, ignore=(): real(repo if repo_dir is None else repo_dir,
                                               ignore=ignore))
    return repo


def _edit_code(repo: Path) -> None:
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")


def _rewrote_tracked_files(repo: Path) -> bool:
    """Whether the run changed tracked files, so the checks are not vacuous."""
    return provenance.git_commit(repo)[1] is True


# ---------------------------------------------------------------------------
# evaluation.sweep_aggregate: the CSV, then the JSON that records the state
# ---------------------------------------------------------------------------

def _sweep_summaries(d: Path) -> Path:
    d.mkdir(parents=True)
    for condition, rate in (("raw", 0.1), ("case_fold", 0.1)):
        payload = {"benchmark": {"dataset": "librispeech_asr", "config": "clean",
                                 "split": "test", "model": "openai/whisper-large-v3",
                                 "utterances": 3, "seed": 42, "condition": condition},
                   "summary": {"files": 3, "macro_wer": rate, "macro_mer": rate,
                               "macro_wil": rate, "macro_cer": rate,
                               "total_reference_words": 30}}
        name = ("wer_summary.json" if condition == "raw"
                else f"wer_summary_{condition}.json")
        (d / name).write_text(json.dumps(payload), encoding="utf-8")
    return d


def test_sweep_aggregate_in_place_is_dirty_only_when_the_code_is(tmp_path, monkeypatch):
    # A directory name with a space, which git status quotes unless read
    # with -z, as provenance reads it.
    repo = _checkout(tmp_path, monkeypatch, ["results x/sweep_aggregate.csv",
                                             "results x/sweep_aggregate.json"])
    sweep_dir = _sweep_summaries(tmp_path / "sweep")
    out_csv = repo / "results x" / "sweep_aggregate.csv"
    out_json = out_csv.with_suffix(".json")
    argv = ["--sweep-dir", str(sweep_dir), "--out", str(out_csv),
            "--out-json", str(out_json)]

    def dirty() -> bool | None:
        agg.main(argv)
        payload = json.loads(out_json.read_text(encoding="utf-8"))
        return payload["provenance"]["run_metadata"]["git_dirty"]

    assert dirty() is False
    assert _rewrote_tracked_files(repo)
    # The JSON's time stamp differs on every run, so the second run sees a
    # JSON the first rewrote.
    assert dirty() is False
    _edit_code(repo)
    assert dirty() is True


def test_write_aggregate_json_alone_leaves_out_its_own_file(tmp_path, monkeypatch):
    """Called without run_meta it reads the state itself, ignoring only *path*."""
    repo = _checkout(tmp_path, monkeypatch, ["out/agg.json"])
    rows = agg.aggregate_sweep(_sweep_summaries(tmp_path / "sweep"))
    path = repo / "out" / "agg.json"
    for expected in (False, False):
        agg.write_aggregate_json(rows, path, tmp_path / "sweep")
        meta = json.loads(path.read_text(encoding="utf-8"))["provenance"]["run_metadata"]
        assert meta["git_dirty"] is expected
    assert _rewrote_tracked_files(repo)
    _edit_code(repo)
    agg.write_aggregate_json(rows, path, tmp_path / "sweep")
    meta = json.loads(path.read_text(encoding="utf-8"))["provenance"]["run_metadata"]
    assert meta["git_dirty"] is True


# ---------------------------------------------------------------------------
# evaluation.benchmark_timestamps: report and skipped files, then the summary
# ---------------------------------------------------------------------------

@pytest.fixture()
def timestamp_stubs(monkeypatch):
    """The corpus, the Whisper pipeline and the token lookup, stubbed.

    The same stand-ins as tests/test_s1_misc_timestamps.py. A run of three
    rows scores two and skips the second, whose final chunk has no end
    timestamp, so the skipped file has a row.
    """
    rows = [{"audio_id": f"AMI_EN2002a_H00_MEE071_{i:07d}_{i + 100:07d}",
             "meeting_id": "EN2002a",
             "audio": {"array": np.zeros(16_000, dtype=np.float32),
                       "sampling_rate": 16_000}} for i in range(4)]

    class _Dataset(list):
        def cast_column(self, name, feature):
            return self

    fake = types.ModuleType("datasets")
    fake.load_dataset = lambda **kwargs: _Dataset(rows)
    fake.Audio = lambda decode=True: ("Audio", decode)
    monkeypatch.setitem(sys.modules, "datasets", fake)
    monkeypatch.setattr(bt, "_load_hf_token", lambda: None)

    calls = []

    def pipe(audio):
        calls.append(audio)
        if len(calls) % 3 == 2:    # the second utterance of each 3-row run
            return {"text": "a b", "chunks": [{"timestamp": (0.0, 0.4)},
                                              {"timestamp": (0.4, None)}]}
        return {"text": "a", "chunks": [{"timestamp": (0.0, 0.9)}]}

    settings = {"device": "cpu", "gpu": None, "dtype": "float32",
                "chunk_length_s": 30, "stride_length_s": 5, "model_revision": "r"}
    monkeypatch.setattr(bt, "_load_whisper", lambda model_id: (pipe, settings))


def test_timestamp_benchmark_in_place_is_dirty_only_when_the_code_is(
        tmp_path, monkeypatch, timestamp_stubs):
    names = ("timestamp_report.csv", "timestamp_skipped.csv", "timestamp_summary.json")
    repo = _checkout(tmp_path, monkeypatch, [f"output/evaluation/{n}" for n in names])
    out = repo / "output" / "evaluation"

    def dirty() -> bool | None:
        summary = bt.run_benchmark(out, "openai/whisper-large-v3", limit=3)
        written = json.loads((out / "timestamp_summary.json").read_text(encoding="utf-8"))
        assert written["run"] == summary["run"]
        return summary["run"]["git_dirty"]

    assert dirty() is False
    assert _rewrote_tracked_files(repo)
    assert (out / "timestamp_skipped.csv").read_text(encoding="utf-8").count("\n") == 2
    assert dirty() is False
    _edit_code(repo)
    assert dirty() is True


# ---------------------------------------------------------------------------
# evaluation.wer: the report, then the summary
# ---------------------------------------------------------------------------

def test_wer_cli_in_place_is_dirty_only_when_the_code_is(tmp_path, monkeypatch):
    repo = _checkout(tmp_path, monkeypatch, ["output/evaluation/r.csv",
                                             "output/evaluation/s.json"])
    refs, hyps = tmp_path / "ref", tmp_path / "hyp"
    for d in (refs, hyps):
        d.mkdir()
        (d / "rec.txt").write_text("one two three", encoding="utf-8")

    # Scoring needs jiwer; what is tested here is only where the state is read.
    def score(ref, hyp, normaliser_kwargs=None):
        return wer.PairResult(name=hyp.stem, wer=0.0, mer=0.0, wil=0.0, cer=0.0,
                              hits=3, substitutions=0, deletions=0, insertions=0,
                              reference_words=3, hypothesis_words=3)

    monkeypatch.setattr(wer, "evaluate_pair", score)
    summary = repo / "output" / "evaluation" / "s.json"
    argv = ["--hypothesis", str(hyps), "--reference", str(refs),
            "--report", str(repo / "output" / "evaluation" / "r.csv"),
            "--summary", str(summary)]

    def dirty() -> bool | None:
        assert wer.main(argv) == 0
        return json.loads(summary.read_text(encoding="utf-8"))["run_metadata"]["git_dirty"]

    assert dirty() is False
    assert _rewrote_tracked_files(repo)
    assert dirty() is False
    _edit_code(repo)
    assert dirty() is True
