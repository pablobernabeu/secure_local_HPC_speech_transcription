"""Seven more writers leave their own outputs out of the git state (OUTPUTS-12).

evaluation.benchmark_masking, benchmark_der, disfluency,
audit_reconstruction, determinism_cross, benchmark_wer and
fleurs_diacritics already read provenance.run_metadata() before writing
any tracked output, but without an ignore list. A first regeneration in
place therefore recorded a clean tree, and a second one a dirty tree
whenever the first had left a tracked output different from its committed
copy. Each now leaves out the files it rewrites, as
tests/test_provenance_in_place.py checks for sweep_aggregate,
benchmark_timestamps and wer.

Each test regenerates tracked outputs of a throwaway git repository in
place: twice on unchanged code, which must record a clean tree, then once
after a tracked code file has changed, which must record a dirty one.
Nothing needs a model, a corpus, pyannote or jiwer.
"""

from __future__ import annotations

import json
import shutil
import sys
import types
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

import provenance  # noqa: E402
from evaluation import audit_reconstruction as ar  # noqa: E402
from evaluation import benchmark_der as bd  # noqa: E402
from evaluation import benchmark_masking as bm  # noqa: E402
from evaluation import benchmark_wer as bw  # noqa: E402
from evaluation import der_metrics as dm  # noqa: E402
from evaluation import determinism_cross as dc  # noqa: E402
from evaluation import disfluency  # noqa: E402
from evaluation import fleurs_diacritics as fd  # noqa: E402
from evaluation import wer  # noqa: E402
from test_determinism_cross import _dump  # noqa: E402
from test_provenance_in_place import (  # noqa: E402
    _checkout, _edit_code, _rewrote_tracked_files,
)
from test_s1_wer_disfluency import _rows, _write  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _in_place(repo: Path, dirty) -> None:
    """Clean, clean again, then dirty once a tracked code file changes."""
    assert dirty() is False
    assert _rewrote_tracked_files(repo)
    assert dirty() is False
    _edit_code(repo)
    assert dirty() is True


# ---------------------------------------------------------------------------
# evaluation.benchmark_masking: the report, then the summary
# ---------------------------------------------------------------------------

def test_masking_benchmark_in_place_is_dirty_only_when_the_code_is(tmp_path, monkeypatch):
    out_names = ("masking_report.csv", "masking_summary.json")
    repo = _checkout(tmp_path, monkeypatch, [f"output/evaluation/{n}" for n in out_names])
    out = repo / "output" / "evaluation"
    # What is tested is where the state is read, not the masker: one that
    # masks nothing scores every case and loads nothing.
    monkeypatch.setattr(bm, "_build_masker_and_detector",
                        lambda case_insensitive=False, use_ner=False: (str, None))

    def dirty() -> bool | None:
        summary = bm.run(seed=1, n_per_cell=1, output_dir=out)
        written = json.loads((out / "masking_summary.json").read_text(encoding="utf-8"))
        assert written["run_metadata"] == summary["run_metadata"]
        return summary["run_metadata"]["git_dirty"]

    _in_place(repo, dirty)


# ---------------------------------------------------------------------------
# evaluation.benchmark_der: the report and summary, replaced together
# ---------------------------------------------------------------------------

def _meeting(mid: str):
    stats = {"n_utterances": 2, "n_speakers": 2, "duration_s": 60.0,
             "speech_s": 50.0, "overlap_s": 5.0, "overlap_fraction": 0.1,
             "silence_fraction": 0.17}
    return mid, [0.0], [{"start": 0.0, "end": 1.0, "speaker": "A"}], stats


def test_der_benchmark_in_place_is_dirty_only_when_the_code_is(tmp_path, monkeypatch):
    """The pipeline and pyannote's scoring are the fakes of
    tests/test_audit_der_outputs.py."""
    repo = _checkout(tmp_path, monkeypatch, ["output/evaluation/der_report.csv",
                                             "output/evaluation/der_summary.json"])
    out = repo / "output" / "evaluation"
    # run_benchmark records the checkout holding the benchmark; here that is repo.
    monkeypatch.setattr(bd, "_ROOT", repo)
    monkeypatch.setattr(dm, "annotation_from_segments", lambda segs, uri="": segs)
    monkeypatch.setattr(dm, "compute_der", lambda reference, hypothesis, collar=0.25: {
        "uri": "", "der": 0.2, "missed_speech": 0.1, "false_alarm": 0.05,
        "speaker_confusion": 0.05, "total_ref_duration": 1.0,
        "_missed_abs": 0.1, "_fa_abs": 0.05, "_confusion_abs": 0.05})
    monkeypatch.setattr(bd, "load_pipeline", lambda *a, **k: object())
    monkeypatch.setattr(bd, "apply_hyperparameters", lambda pipe, **kw: {
        "clustering": {"threshold": 0.7, "min_cluster_size": 12},
        "segmentation": {"min_duration_off": 0.0}})
    monkeypatch.setattr(bd, "_load_hf_token", lambda: None)
    monkeypatch.setattr(bd, "diarise", lambda *a, **k: [
        {"start": 0.0, "end": 1.0, "speaker": "X"}])
    monkeypatch.setattr(bd, "build_corpus",
                        lambda **kw: iter([_meeting("M0"), _meeting("M1")]))

    def dirty() -> bool | None:
        summary = bd.run_benchmark(out)
        written = json.loads((out / "der_summary.json").read_text(encoding="utf-8"))
        assert written["run_metadata"] == summary["run_metadata"]
        return summary["run_metadata"]["git_dirty"]

    _in_place(repo, dirty)


# ---------------------------------------------------------------------------
# evaluation.disfluency: the summary, then the table
# ---------------------------------------------------------------------------

def test_disfluency_in_place_is_dirty_only_when_the_code_is(tmp_path, monkeypatch):
    repo = _checkout(tmp_path, monkeypatch, ["output/evaluation/disfluency_summary.json",
                                             "output/evaluation/disfluency_report.csv"])
    out = repo / "output" / "evaluation"
    # The dump holds transcript text and is never committed.
    dump = tmp_path / "wer_hypotheses.csv"
    _write(dump, _rows(False), False)
    argv = [str(dump), "--json", str(out / "disfluency_summary.json"),
            "--csv", str(out / "disfluency_report.csv")]

    def dirty() -> bool | None:
        assert disfluency.main(argv) == 0
        summary = json.loads((out / "disfluency_summary.json").read_text(encoding="utf-8"))
        return summary["run_metadata"]["git_dirty"]

    _in_place(repo, dirty)


# ---------------------------------------------------------------------------
# evaluation.audit_reconstruction: the record
# ---------------------------------------------------------------------------

def test_reconstruction_audit_in_place_is_dirty_only_when_the_code_is(tmp_path,
                                                                     monkeypatch):
    """The cache is built as in tests/test_s1_misc_audit_reconstruction.py."""
    pytest.importorskip("soundfile")
    sr = 16_000
    rows = [{"meeting_id": f"M{m}", "speaker_id": f"S{u}",
             "begin_time": float(u), "end_time": u + 0.5,
             "audio": {"array": np.full(sr // 2, 0.2, np.float32),
                       "sampling_rate": sr}}
            for m in range(2) for u in range(2)]
    monkeypatch.setattr(bd, "_stream_ami", lambda split, token: iter(rows))
    list(bd.build_corpus(split="test", cache_dir=tmp_path / "cache"))
    cache = tmp_path / "cache" / "test_timeline_full"

    record = "output/evaluation/reconstruction_audit_test.json"
    repo = _checkout(tmp_path, monkeypatch, [record])

    def dirty() -> bool | None:
        assert ar.main([str(cache), "--json", str(repo / record)]) == 0
        return json.loads((repo / record).read_text(encoding="utf-8"))["run"]["git_dirty"]

    _in_place(repo, dirty)


# ---------------------------------------------------------------------------
# evaluation.determinism_cross: the comparison
# ---------------------------------------------------------------------------

def test_cross_hardware_comparison_in_place_is_dirty_only_when_the_code_is(
        tmp_path, monkeypatch):
    result = "output/evaluation/determinism/determinism_cross_accelerator.json"
    repo = _checkout(tmp_path, monkeypatch, [result])
    first = _dump(tmp_path / "a.csv", [("u1", "THE LAMP", "The lamp.", 0.0),
                                        ("u2", "RIGHT", "Right.", 0.0)])
    second = _dump(tmp_path / "b.csv", [("u1", "THE LAMP", "The lamb.", 0.5),
                                         ("u2", "RIGHT", "Right.", 0.0)])
    argv = ["--dump", f"a={first}", "--dump", f"b={second}", "--subset", "a",
            "--json", str(repo / result)]

    def dirty() -> bool | None:
        assert dc.main(argv) == 0
        written = json.loads((repo / result).read_text(encoding="utf-8"))
        assert set(written["run_metadata"]["packages"]) == {"numpy"}
        return written["run_metadata"]["git_dirty"]

    _in_place(repo, dirty)


# ---------------------------------------------------------------------------
# evaluation.fleurs_diacritics: the shares
# ---------------------------------------------------------------------------

def test_diacritic_shares_in_place_are_dirty_only_when_the_code_is(tmp_path, monkeypatch):
    """The Hub is a stand-in that streams two references to the reader the
    module uses, so the module's own command line runs end to end."""
    result = "output/evaluation/fleurs_diacritic_shares.json"
    repo = _checkout(tmp_path, monkeypatch, [result])
    hub = types.ModuleType("datasets")
    hub.load_dataset = lambda *args, **kwargs: [{"transcription": "źle"},
                                                {"transcription": "dobrze"}]
    monkeypatch.setitem(sys.modules, "datasets", hub)
    argv = ["--languages", "pl_pl", "--out", str(repo / result)]

    def dirty() -> bool | None:
        assert fd.main(argv) == 0
        written = json.loads((repo / result).read_text(encoding="utf-8"))
        assert written["languages"]["pl_pl"]["pct_words_with_diacritic"] == 50
        assert set(written["run_metadata"]["packages"]) == {"datasets", "huggingface_hub"}
        return written["run_metadata"]["git_dirty"]

    _in_place(repo, dirty)


def test_diacritic_shares_record_a_callers_run_metadata_as_given(monkeypatch):
    def refuse(**kwargs):
        raise AssertionError("measure read the git state itself")

    monkeypatch.setattr(provenance, "run_metadata", refuse)
    meta = {"git_commit": "abc", "git_dirty": False}
    record = fd.measure(languages=("nl_nl",), references=lambda config: iter(["goed"]),
                        run_meta=meta)
    assert record["run_metadata"] == meta


# ---------------------------------------------------------------------------
# evaluation.benchmark_wer: the reports, summaries and dump of one call
# ---------------------------------------------------------------------------

@pytest.fixture()
def wer_stubs(monkeypatch):
    """The corpus, the ASR pipeline, seeding and jiwer, as in
    tests/test_benchmark_wer_device.py."""
    def corpus(dataset_name, config, split, limit, ref_field=None, uid_field=None):
        yield "u1", np.zeros(10, dtype="float32"), 16_000, "hello world"

    def metrics(ref: str, hyp: str) -> dict:
        n = len(ref.split())
        return {"wer": 0.0, "mer": 0.0, "wil": 0.0, "cer": 0.0, "hits": n,
                "substitutions": 0, "deletions": 0, "insertions": 0,
                "reference_words": n, "hypothesis_words": len(hyp.split())}

    monkeypatch.setattr(bw, "_iter_samples", corpus)
    monkeypatch.setattr(bw, "_apply_seed", lambda seed: None)
    monkeypatch.setattr(bw, "_build_asr_pipeline",
                        lambda model_id, language="english", device=None, dtype=None:
                        (lambda audio: {"text": "hello world"}))
    monkeypatch.setattr(wer, "compute_metrics", metrics)
    monkeypatch.setattr(wer, "require_jiwer", lambda: None)


def test_wer_benchmark_in_place_is_dirty_only_when_the_code_is(tmp_path, monkeypatch,
                                                               wer_stubs):
    names = ("wer_report.csv", "wer_summary.json", "wer_report_case_fold.csv",
             "wer_summary_case_fold.json", "wer_hypotheses.csv")
    repo = _checkout(tmp_path, monkeypatch, [f"output/evaluation/{n}" for n in names])
    out = repo / "output" / "evaluation"
    runs = bw._build_runs(["raw", "case_fold"], out / "wer_report.csv",
                          out / "wer_summary.json")

    def dirty() -> bool | None:
        bw.run_benchmark("d", "c", "s", "m", None, runs, seed=0, device="cpu",
                         dump_hypotheses=out / "wer_hypotheses.csv")
        states = {json.loads((out / name).read_text(encoding="utf-8"))
                  ["run_metadata"]["git_dirty"]
                  for name in ("wer_summary.json", "wer_summary_case_fold.json")}
        assert len(states) == 1
        return states.pop()

    _in_place(repo, dirty)


def test_wer_benchmark_records_a_callers_run_metadata_as_given(tmp_path, monkeypatch,
                                                               wer_stubs):
    """A sweep over several suites reads the state once, before its first
    file, and hands it to each call."""
    def refuse(**kwargs):
        raise AssertionError("run_benchmark read the git state itself")

    monkeypatch.setattr(provenance, "run_metadata", refuse)
    meta = {"git_commit": "abc", "git_dirty": False}
    runs = bw._build_runs(["raw"], tmp_path / "r.csv", tmp_path / "s.json")
    bw.run_benchmark("d", "c", "s", "m", None, runs, seed=0, device="cpu",
                     run_meta=meta)
    summary = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert summary["run_metadata"] == meta
