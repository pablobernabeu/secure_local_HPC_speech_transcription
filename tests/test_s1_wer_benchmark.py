"""Stage-1 fixes to the WER benchmark and its paired comparisons.

EWER-10/DEPS-04: the dataset and the model load at pinned revisions, and
every summary names them with the run metadata and the decode.
EWER-09: an utterance whose reference normalises to nothing is skipped for
that condition only; the counts are recorded and normaliser_gain compares
conditions on the utterances both scored.
EWER-22: the hypothesis dump keeps the transcriber's reference apart from
the reference the condition scored against.
EWER-05: a missing spelling map stops the run before the model loads.

No audio, model or network: the corpus, the ASR pipeline and the scorer
are stubbed.
"""

from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from evaluation import benchmark_wer as b
from evaluation import condition_ci, conditions, wer
from evaluation.revisions import REVISIONS


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

def _fake_metrics(ref: str, hyp: str) -> dict:
    """Exact-match scoring, enough for the bookkeeping under test."""
    if not ref.strip():
        raise ValueError("empty")
    r, h = ref.split(), hyp.split()
    hits = sum(1 for x, y in zip(r, h, strict=False) if x == y)
    subs = min(len(r), len(h)) - hits
    dels = max(0, len(r) - len(h))
    ins = max(0, len(h) - len(r))
    return {"wer": (subs + dels + ins) / len(r), "mer": 0.0, "wil": 0.0,
            "cer": 0.0, "hits": hits, "substitutions": subs,
            "deletions": dels, "insertions": ins,
            "reference_words": len(r), "hypothesis_words": len(h)}


@pytest.fixture()
def stubbed(monkeypatch):
    samples: list = []

    def fake_iter(dataset_name, config, split, limit, ref_field=None,
                  uid_field=None):
        import numpy as np
        for uid, ref in samples:
            yield uid, np.zeros(10, dtype="float32"), 16_000, ref

    monkeypatch.setattr(b, "_iter_samples", fake_iter)
    monkeypatch.setattr(b, "_apply_seed", lambda seed: None)
    monkeypatch.setattr(b, "_build_asr_pipeline",
                        lambda model_id, language="english", **_options:
                        (lambda audio: {"text": "Hello World"}))
    monkeypatch.setattr(wer, "compute_metrics", _fake_metrics)
    monkeypatch.setattr(wer, "require_jiwer", lambda: None)
    return samples


def _emptying_condition(monkeypatch, name="case_fold"):
    """Replace *name* by a reference transform that empties 'uh' references,
    as the Whisper normaliser empties filler-only ones."""
    cond = conditions.get_condition(name)

    def transform(text):
        return "" if text.strip().lower() == "uh" else text.lower()

    monkeypatch.setitem(conditions._CONDITIONS, name, conditions.Condition(
        name=name, description=cond.description, transform=transform,
        apply_to_reference=True))


# ---------------------------------------------------------------------------
# EWER-10 / DEPS-04: pinned revisions
# ---------------------------------------------------------------------------

def test_the_dataset_is_streamed_at_its_pinned_revision(monkeypatch):
    captured = {}
    fake = types.ModuleType("datasets")

    class _Stream(list):
        def cast_column(self, *args, **kwargs):
            return self

    def load_dataset(*args, **kwargs):
        captured.update(kwargs)
        return _Stream()

    fake.load_dataset = load_dataset
    fake.Audio = lambda decode=True: None
    monkeypatch.setitem(sys.modules, "datasets", fake)
    assert list(b._iter_samples("librispeech_asr", "clean", "test", 0)) == []
    assert captured["revision"] == REVISIONS["librispeech_asr"]
    captured.clear()
    list(b._iter_samples("some/unpinned", "x", "test", 0))
    assert captured["revision"] is None


def test_the_model_is_loaded_at_its_pinned_revision(monkeypatch):
    captured = {}
    fake = types.ModuleType("transformers")
    fake.pipeline = lambda *args, **kwargs: captured.update(kwargs) or "asr"
    monkeypatch.setitem(sys.modules, "transformers", fake)
    assert b._build_asr_pipeline("openai/whisper-large-v3") == "asr"
    assert captured["revision"] == REVISIONS["openai/whisper-large-v3"]


def test_every_challenge_suite_and_default_model_is_pinned():
    from evaluation.challenge_suites import list_suites
    for suite in list_suites():
        assert suite.dataset in REVISIONS, suite.dataset
    assert b._DEFAULT_DATASET in REVISIONS
    assert b._DEFAULT_MODEL in REVISIONS


def test_the_summary_records_revisions_decode_and_run_metadata(
        stubbed, tmp_path):
    stubbed[:] = [("a", "hello world")]
    runs = b._build_runs(["raw", "case_fold"], tmp_path / "wer_report.csv",
                         tmp_path / "wer_summary.json")
    b.run_benchmark("librispeech_asr", "clean", "test",
                    "openai/whisper-large-v3", None, runs)
    raw = json.loads((tmp_path / "wer_summary.json").read_text("utf-8"))
    folded = json.loads(
        (tmp_path / "wer_summary_case_fold.json").read_text("utf-8"))
    assert raw["benchmark"]["revisions"] == {
        "librispeech_asr": REVISIONS["librispeech_asr"],
        "openai/whisper-large-v3": REVISIONS["openai/whisper-large-v3"]}
    assert set(raw["benchmark"]["decode"]) >= {"device", "dtype",
                                               "model_commit"}
    assert raw["run_metadata"]["packages"]
    # EWER-03: the flag travels with the summary.
    assert raw["benchmark"]["wer_invisible"] is False
    assert folded["benchmark"]["wer_invisible"] is True


# ---------------------------------------------------------------------------
# EWER-09: per-condition skips and the shared-utterance gain
# ---------------------------------------------------------------------------

def test_empty_reference_skips_are_counted_per_condition(
        stubbed, tmp_path, monkeypatch):
    _emptying_condition(monkeypatch)
    stubbed[:] = [("a", "hello world"), ("b", "uh"), ("c", "hello there")]
    runs = b._build_runs(["raw", "case_fold"], tmp_path / "wer_report.csv",
                         tmp_path / "wer_summary.json")
    b.run_benchmark("d", "c", "s", "m", None, runs)
    raw = json.loads((tmp_path / "wer_summary.json").read_text("utf-8"))
    cf = json.loads((tmp_path / "wer_summary_case_fold.json").read_text("utf-8"))
    assert raw["benchmark"]["utterances"] == 3
    assert raw["benchmark"]["n_skipped_empty_reference"] == 0
    assert cf["benchmark"]["utterances"] == 2
    assert cf["benchmark"]["n_skipped_empty_reference"] == 1
    assert cf["benchmark"]["n_streamed"] == 3

    gain = condition_ci.normaliser_gain(
        tmp_path / "wer_report.csv", tmp_path / "wer_report_case_fold.csv")
    assert gain["n_shared"] == 2
    assert gain["n_baseline_only"] == 1
    assert gain["n_condition_only"] == 0
    # On the shared utterances raw scores "Hello World" against the
    # references; the all-utterance figure also carries the dropped one.
    assert gain["macro_baseline_all"] != gain["macro_baseline_shared"]


def _report(path: Path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "name", "wer", "mer", "wil", "cer", "hits", "substitutions",
            "deletions", "insertions", "reference_words", "hypothesis_words"])
        writer.writeheader()
        for name, wer_value, errors, ref_words in rows:
            writer.writerow({"name": name, "wer": wer_value, "mer": 0,
                             "wil": 0, "cer": 0, "hits": ref_words - errors,
                             "substitutions": errors, "deletions": 0,
                             "insertions": 0, "reference_words": ref_words,
                             "hypothesis_words": ref_words})


def test_normaliser_gain_restricts_to_the_shared_utterances(tmp_path):
    # u3 is a hard utterance that only the baseline scored.
    _report(tmp_path / "base.csv", [("u1", 0.2, 2, 10), ("u2", 0.1, 1, 10),
                                    ("u3", 3.0, 3, 1)])
    _report(tmp_path / "cond.csv", [("u1", 0.1, 1, 10), ("u2", 0.1, 1, 10)])
    gain = condition_ci.normaliser_gain(tmp_path / "base.csv",
                                        tmp_path / "cond.csv")
    assert gain["n_shared"] == 2 and gain["n_baseline_only"] == 1
    assert gain["macro_baseline_shared"] == pytest.approx(0.15)
    assert gain["macro_condition_shared"] == pytest.approx(0.1)
    assert gain["macro_gain_shared"] == pytest.approx(1 / 3)
    assert gain["micro_gain_shared"] == pytest.approx((3 / 20 - 2 / 20) / (3 / 20))
    # The naive gain, across different utterance sets, is far larger.
    assert gain["macro_gain_all"] == pytest.approx((3.3 / 3 - 0.1) / (3.3 / 3))
    with pytest.raises(ValueError, match="share"):
        _report(tmp_path / "other.csv", [("zz", 0.0, 0, 5)])
        condition_ci.normaliser_gain(tmp_path / "base.csv",
                                     tmp_path / "other.csv")


def test_a_qualified_sweep_cell_is_discovered_by_its_prefix(tmp_path):
    stem = "wer_report_librispeech_whisper-large-v3"
    _report(tmp_path / f"{stem}.csv", [("u1", 0.2, 2, 10), ("u2", 0.1, 1, 10)])
    _report(tmp_path / f"{stem}_case_fold.csv",
            [("u1", 0.2, 2, 10), ("u2", 0.1, 1, 10)])
    (tmp_path / "wer_summary_librispeech_whisper-large-v3.json").write_text(
        json.dumps({"benchmark": {"condition": "raw"}}), encoding="utf-8")
    found = condition_ci.discover_reports(tmp_path, stem)
    assert set(found) == {"__primary__", "case_fold"}
    rows = condition_ci.gain_rows(tmp_path, prefix=stem)
    assert [r["condition"] for r in rows] == ["case_fold"]
    assert rows[0]["macro_gain_shared"] == 0
    out = tmp_path / "ci.csv"
    gains = tmp_path / "gains.csv"
    condition_ci.main(["--reports", str(tmp_path), "--prefix", stem,
                       "--bootstrap", "50", "--output", str(out),
                       "--gains-output", str(gains)])
    with open(gains, encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == condition_ci._GAIN_FIELDS


# ---------------------------------------------------------------------------
# EWER-22: both references in the dump
# ---------------------------------------------------------------------------

def test_the_dump_keeps_the_transcriber_reference(stubbed, tmp_path):
    stubbed[:] = [("a", "Hello World")]
    runs = b._build_runs(["raw", "case_fold"], tmp_path / "wer_report.csv",
                         tmp_path / "wer_summary.json")
    b.run_benchmark("d", "c", "s", "m", None, runs,
                    dump_hypotheses=tmp_path / "dump.csv")
    with open(tmp_path / "dump.csv", newline="", encoding="utf-8") as fh:
        rows = {r["condition"]: r for r in csv.DictReader(fh)}
    assert rows["case_fold"]["reference_raw"] == "Hello World"
    assert rows["case_fold"]["reference_transformed"] == "hello world"
    assert rows["raw"]["reference_transformed"] == "Hello World"


# ---------------------------------------------------------------------------
# EWER-05: a missing spelling map stops the run before the model loads
# ---------------------------------------------------------------------------

def test_a_missing_spelling_map_fails_before_the_model_loads(
        stubbed, tmp_path, monkeypatch):
    pytest.importorskip("transformers")

    def missing():
        raise conditions.SpellingMapError("openai-whisper is not installed")

    def never(*args, **kwargs):
        pytest.fail("the model loaded although whisper_norm cannot run")

    monkeypatch.setattr(conditions, "whisper_spelling_map_path", missing)
    monkeypatch.setattr(conditions, "_WHISPER_NORM_SINGLETON", None)
    monkeypatch.setattr(b, "_build_asr_pipeline", never)
    stubbed[:] = [("a", "hello world")]
    runs = b._build_runs(["raw", "whisper_norm"], tmp_path / "wer_report.csv",
                         tmp_path / "wer_summary.json")
    with pytest.raises(ImportError, match="openai-whisper"):
        b.run_benchmark("d", "c", "s", "m", None, runs)
    assert not (tmp_path / "wer_summary.json").exists()
