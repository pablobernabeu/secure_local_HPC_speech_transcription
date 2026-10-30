"""Stage-1 fixes EPRIV-16, EPRIV-28 and the EPRIV-02 level check, and provenance.

EPRIV-16: the manuscript re-derived the loop screen in R with a criterion
that differed from degenerate_baselines. The report now carries the
screen's result per utterance and the summary its thresholds, so a reader
re-pools the guarded figures instead of re-deriving the screen.
EPRIV-28: the guarded baseline is named for its arm.

run() is driven end to end with every loader replaced: a stub corpus, a
stub embedder, a stub recogniser and a stub scorer. No model, network or
GPU; the transform itself runs on short synthetic signals.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Imported before the torch stand-in below is installed: scipy's array-API
# layer inspects whatever module is registered as torch.
pytest.importorskip("scipy.signal")

from evaluation import benchmark_anonymisation as ba
from evaluation import wer
from evaluation.revisions import revision_for

SR = ba.SAMPLE_RATE


def _utterances():
    """Two meetings, two speakers each, two utterances per speaker.

    The speakers swap headset channels between the meetings, as the EN2002
    speakers do.
    """
    rng = np.random.default_rng(0)
    out = []
    for m, swap in (("M1", False), ("M2", True)):
        for s in range(2):
            for _ in range(2):
                i = len(out)
                channel = f"H0{(s + swap) % 2}"
                out.append({"uid": f"AMI_{m}_{channel}_S{s}_{i:07d}_{i + 1:07d}",
                            "speaker": f"S{s}", "meeting": m,
                            "channel": channel,
                            "audio": (0.1 * rng.standard_normal(SR // 2)
                                      ).astype(np.float32),
                            "reference": f"word{i} alpha beta gamma"})
    return out


def _stub_scorer(reference, hypothesis):
    """Position-wise alignment; crude, but consistent across arms."""
    ref, hyp = reference.split(), hypothesis.split()
    shared = min(len(ref), len(hyp))
    hits = sum(a == b for a, b in zip(ref, hyp, strict=False))
    subs = shared - hits
    dels = max(0, len(ref) - len(hyp))
    ins = max(0, len(hyp) - len(ref))
    return {"wer": (subs + dels + ins) / len(ref), "mer": 0.0, "wil": 0.0,
            "cer": 0.0, "hits": hits, "substitutions": subs, "deletions": dels,
            "insertions": ins, "reference_words": len(ref),
            "hypothesis_words": len(hyp)}


def _run_on_stubs(monkeypatch, out_dir, embedder_failures=None):
    """Run the benchmark on stubs into *out_dir*; return (summary, rows, asr kwargs).

    *embedder_failures* is what the stub embedder reports through the
    ``failures`` argument, as the real one does when it falls back.
    """
    utterances = _utterances()
    # The recogniser recognises an utterance by its audio. The original
    # and the control are the same signal, so utterance 0 loops on both;
    # the warped audio matches nothing and loses its first word.
    known = {round(float(np.sum(u["audio"])), 3): u for u in utterances}

    def recognise(inputs):
        u = known.get(round(float(np.sum(inputs["array"])), 3))
        if u is None:
            return {"text": "alpha beta gamma"}
        if u is utterances[0]:
            return {"text": " ".join(["loop"] * 30)}
        return {"text": u["reference"]}

    asr_kwargs = {}

    def pipeline(task, **kwargs):
        asr_kwargs.update(kwargs)
        return recognise

    transformers = types.ModuleType("transformers")
    transformers.pipeline = pipeline
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.float16, torch.float32 = "float16", "float32"
    torch.Tensor = type("Tensor", (), {})      # probed by scipy's array API
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(wer, "jiwer", types.SimpleNamespace())
    monkeypatch.setattr(wer, "compute_metrics", _stub_scorer)
    monkeypatch.setattr(ba, "_load_utterances",
                        lambda limit, hf_token, per_meeting=None, skipped=None:
                        utterances)

    def embed(audio):
        a = np.asarray(audio, dtype=np.float64)
        return np.array([a[:50].sum(), a[50:100].sum(), a[100:150].sum()])

    source = "pyannote/wespeaker-voxceleb-resnet34-LM" + ba._VIA_PIPELINE

    def load_embedder(hf_token, failures=None):
        if failures is not None:
            failures.update(embedder_failures or {})
        return embed, source

    monkeypatch.setattr(ba, "_load_embedder", load_embedder)

    ba.run(out_dir, limit=8, alphas=[0.8], per_meeting=4)
    summary = json.loads((out_dir / "anonymisation_summary.json").read_text(
        encoding="utf-8"))
    with (out_dir / "anonymisation_report.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return summary, rows, asr_kwargs


@pytest.fixture
def finished_run(monkeypatch, tmp_path):
    """Run the benchmark on stubs and return (summary, rows, asr kwargs)."""
    return _run_on_stubs(monkeypatch, tmp_path)


def test_the_report_flags_the_looped_baseline(finished_run):
    summary, rows, _ = finished_run
    flagged = [r["uid"] for r in rows if r["degenerate_baseline"] == "1"]
    assert flagged == [rows[0]["uid"]]
    assert summary["by_alpha"]["0.8"]["n_degenerate_baselines"] == 1


def test_the_guarded_figures_re_pool_from_the_report(finished_run):
    """What the manuscript can do instead of re-deriving the screen."""
    summary, rows, _ = finished_run
    kept = [r for r in rows if r["degenerate_baseline"] == "0"]
    words = sum(int(r["reference_words"]) for r in kept)
    s = summary["by_alpha"]["0.8"]
    assert round(sum(int(r["errors_control"]) for r in kept) / words, 4) == \
        s["wer_baseline_guarded"]
    assert round(sum(int(r["errors_anonymised"]) for r in kept) / words, 4) == \
        s["wer_anonymised_guarded"]


def test_the_screen_is_described_in_the_summary(finished_run):
    summary, _, _ = finished_run
    criterion = summary["degenerate_baseline_criterion"]
    assert criterion["length_factor"] == ba.DEGENERATE_LENGTH_FACTOR
    assert criterion["length_floor"] == ba.DEGENERATE_LENGTH_FLOOR
    assert criterion["screened_arm"] == "resynthesis control"
    assert criterion["report_column"] == "degenerate_baseline"


def test_the_guarded_baseline_is_named_for_its_arm(finished_run):
    s = finished_run[0]["by_alpha"]["0.8"]
    assert s["wer_baseline_name"] == "resynthesis control"
    assert s["wer_original_guarded"] == s["wer_baseline_guarded"]


def test_linkage_is_reported_within_and_across_meetings(finished_run):
    summary, rows, _ = finished_run
    s = summary["by_alpha"]["0.8"]
    for key in ("linkage_rate", "chance", "n_singleton_excluded",
                "linkage_rate_within_meeting", "chance_within_meeting",
                "linkage_rate_cross_meeting", "chance_cross_meeting"):
        assert key in s
    # Two speakers, four utterances each in the whole set: 3 of 7.
    assert s["chance"] == pytest.approx(3 / 7, abs=1e-4)
    assert set(s["linkage_by_candidates"]) == set(ba.CANDIDATE_SETS)
    assert set(summary["linkage_ceiling"]) == set(ba.CANDIDATE_SETS)
    assert summary["speaker_channels"]["change_channel"] == ["S0", "S1"]
    assert {r["meeting"] for r in rows} == {"M1", "M2"}
    assert {r["channel"] for r in rows} == {"H00", "H01"}


def test_the_sample_is_described_per_meeting(finished_run):
    summary = finished_run[0]
    assert summary["accepted_by_meeting"] == {"M1": 4, "M2": 4}
    assert summary["per_meeting_cap"] == 4
    assert summary["sampling"] == ba.sampling_description(4)


def test_the_level_checks_are_reported(finished_run):
    summary, rows, _ = finished_run
    s = summary["by_alpha"]["0.8"]
    assert s["level_ratio_body"] == pytest.approx(1.0, abs=0.2)
    assert s["n_knee_compressed_samples"] == 0
    assert all(r["level_ratio"] and r["knee_samples"] == "0" for r in rows)


class TestBodyLevel:
    """EPRIV-02: a whole-file level ratio can hide an attenuated body."""

    def test_an_edge_transient_inflates_the_whole_file_ratio_only(self):
        original = np.full(1000, 0.1)
        # The body came back at half level; a click at the end restores the
        # whole-file RMS, which is what the old defect produced.
        anonymised = np.full(1000, 0.05)
        anonymised[-5:] = 1.0
        whole = ba.level_ratio([original], [anonymised])
        body = ba.level_ratio([original], [anonymised], edge=20)
        assert whole > 0.8
        assert body == pytest.approx(0.5)

    def test_a_clip_too_short_for_the_edge_is_skipped(self):
        assert ba.level_ratio([np.ones(10)], [np.ones(10)], edge=5) is None


def test_revisions_and_run_metadata_are_recorded(finished_run):
    summary, _, asr_kwargs = finished_run
    model = ba.DEFAULT_ASR_MODEL
    assert summary["revisions"][model] == revision_for(model)
    assert summary["revisions"][ba.DIARISATION_PIPELINE] == \
        revision_for(ba.DIARISATION_PIPELINE)
    # stream_ami loads AMI at its pinned revision (DEPS-04). The embedding
    # model inside the pipeline is loaded by name, so it is recorded with the
    # registry's revision and listed as the one revision not enforced.
    ami, wespeaker = "edinburghcstr/ami", "pyannote/wespeaker-voxceleb-resnet34-LM"
    assert summary["revisions"][ami] == revision_for(ami)
    assert summary["revisions"][wespeaker] == revision_for(wespeaker)
    assert summary["revisions_not_enforced"] == [wespeaker]
    # The recogniser was loaded at the recorded revision.
    assert asr_kwargs["revision"] == revision_for(model)
    meta = summary["run_metadata"]
    assert set(meta) >= {"git_commit", "git_dirty", "python", "packages"}
    assert "numpy" in meta["packages"]


def test_no_embedding_fallback_is_recorded_as_none(finished_run):
    summary = finished_run[0]
    assert summary["embedding_pipeline_error"] is None
    assert summary["embedding_fallback_errors"] == {}


def test_an_embedding_fallback_is_recorded_and_moves_no_number(monkeypatch, tmp_path):
    """The reasons the loader reports reach the summary, and nothing else
    in the summary or the report changes."""
    failures = {ba.DIARISATION_PIPELINE: "RuntimeError: gated",
                "pyannote/wespeaker-voxceleb-resnet34-LM": "OSError: not cached"}
    (tmp_path / "plain").mkdir()
    (tmp_path / "fallback").mkdir()
    plain, plain_rows, _ = _run_on_stubs(monkeypatch, tmp_path / "plain")
    fallback, fallback_rows, _ = _run_on_stubs(monkeypatch, tmp_path / "fallback",
                                               embedder_failures=failures)
    assert fallback["embedding_pipeline_error"] == "RuntimeError: gated"
    assert fallback["embedding_fallback_errors"] == {
        "pyannote/wespeaker-voxceleb-resnet34-LM": "OSError: not cached"}
    added = {"embedding_pipeline_error", "embedding_fallback_errors"}
    assert ({k: v for k, v in fallback.items() if k not in added}
            == {k: v for k, v in plain.items() if k not in added})
    assert fallback_rows == plain_rows


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_a_regeneration_in_place_is_dirty_only_when_the_code_is(monkeypatch,
                                                                 tmp_path):
    """The summary's git state describes the code, not the run's own output.

    It used to be read after the report had been written, so a run into a
    checkout whose report is tracked recorded a dirty tree. Here the report
    and the summary are tracked: two runs in place record a clean tree, and
    a changed code file a dirty one.
    """
    from provenance import git_commit

    repo = tmp_path / "repo"
    out = repo / "output" / "evaluation"
    out.mkdir(parents=True)
    for name in ("anonymisation_report.csv", "anonymisation_summary.json"):
        (out / name).write_text("stale\n", encoding="utf-8")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "core.autocrlf", "false"),
                 ("add", "-A"), ("commit", "-q", "-m", "init")):
        subprocess.run([shutil.which("git"), "-C", str(repo), "-c", "user.email=t@t",
                        "-c", "user.name=t", *args], check=True, capture_output=True)
    # run() records the checkout holding the benchmark; here that is repo.
    monkeypatch.setattr(ba, "_ROOT", repo)

    summary = _run_on_stubs(monkeypatch, out)[0]
    # The run really did rewrite tracked files, so the check is not vacuous.
    assert git_commit(repo)[1] is True
    assert summary["run_metadata"]["git_dirty"] is False
    assert summary["run_metadata"]["git_commit"] == summary["git_commit"]
    assert _run_on_stubs(monkeypatch, out)[0]["run_metadata"]["git_dirty"] is False
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    assert _run_on_stubs(monkeypatch, out)[0]["run_metadata"]["git_dirty"] is True
