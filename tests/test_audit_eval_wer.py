"""Audit fixes for the WER scoring path.

Pins normalise_text's current outputs (every committed WER passes through
it, and none of this ran where jiwer was absent), and exercises
benchmark_wer.run_benchmark with a stub corpus, a stub ASR pipeline and a
stub scorer: repeated utterance ids, programming errors that must not be
swallowed, and conditions that score nothing. No audio, model or network.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from evaluation import benchmark_wer as b
from evaluation import wer


# ---------------------------------------------------------------------------
# normalise_text: current behaviour, pinned
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Hello, World!", "hello world"),
    # A quotation typed with apostrophes leaves a stray token. Pinned, not
    # endorsed: changing it moves every committed WER.
    ("'Yes,' she said.", "'yes ' she said"),
    ("‘Yes’", "'yes'"),
    ("don't stop", "don't stop"),
    ("[NAME] said hi", "name said hi"),
    ("well-known 3.5 km", "well known 3 5 km"),
    ("ＡＢＣ", "abc"),                 # NFKC folds full-width
    ("Gerät était", "gerät était"),
    # NFKC leaves double curly quotes alone, for punctuation stripping to
    # remove, and composes a letter and a combining accent, keeping the accent.
    ("\u201cYes,\u201d she said", "yes she said"),
    ("cafe\u0301", "caf\u00e9"),
    ("  many   spaces\n", "many spaces"),
    (None, ""),
])
def test_normalise_text_pins(text, expected):
    assert wer.normalise_text(text) == expected


def test_header_is_stripped_only_when_asked():
    text = "Title\n=====\nmeta\n=====\nbody words"
    assert wer.normalise_text(text) == "body words"
    assert wer.normalise_text(text, strip_header=False) == \
        "title meta body words"


def test_remove_fillers_uses_its_own_list():
    assert wer.normalise_text("um so er uh mhm yes", remove_fillers=True) == \
        "so er mhm yes"


def test_empty_reference_is_refused_before_jiwer_is_needed():
    with pytest.raises(ValueError):
        wer.compute_metrics("   ", "anything")


def test_compute_metrics_counts():
    pytest.importorskip("jiwer")
    m = wer.compute_metrics("a b c", "a x c d")
    assert (m["hits"], m["substitutions"], m["deletions"], m["insertions"]) \
        == (2, 1, 0, 1)
    assert m["wer"] == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# run_benchmark with stubs
# ---------------------------------------------------------------------------

def _fake_metrics(ref: str, hyp: str) -> dict:
    """A stand-in for jiwer: exact-match scoring, enough for bookkeeping."""
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
                        (lambda audio: {"text": "hello world"}))
    monkeypatch.setattr(wer, "compute_metrics", _fake_metrics)
    # The stub scorer needs no jiwer, which is absent from some test hosts.
    monkeypatch.setattr(wer, "require_jiwer", lambda: None)
    return samples


def _runs(tmp_path: Path, names):
    return b._build_runs(list(names), tmp_path / "wer_report.csv",
                         tmp_path / "wer_summary.json")


def _names(path: Path) -> list[str]:
    return [r["name"] for r in csv.DictReader(open(path, encoding="utf-8"))]


def test_repeated_uids_are_renamed_and_counted(stubbed, tmp_path, capsys):
    stubbed[:] = [("1904", "hello world"), ("1675", "hello world"),
                  ("1904", "hello world"), ("1904", "hello world")]
    b.run_benchmark("d", "c", "s", "m", None, _runs(tmp_path, ["raw"]))
    assert _names(tmp_path / "wer_report.csv") == \
        ["1904", "1675", "1904__2", "1904__3"]
    summary = json.loads((tmp_path / "wer_summary.json").read_text("utf-8"))
    assert summary["benchmark"]["n_renamed_duplicate_uids"] == 2
    assert "repeats" in capsys.readouterr().err


def test_a_clean_run_records_its_provenance_and_zero_skips(stubbed, tmp_path):
    """EWER-09/EWER-10: counts are always present, zeros included, and the
    summary names the revisions, the decode and the code that produced it."""
    stubbed[:] = [("a", "hello world"), ("b", "hello world")]
    b.run_benchmark("d", "c", "s", "m", None, _runs(tmp_path, ["raw"]))
    summary = json.loads((tmp_path / "wer_summary.json").read_text("utf-8"))
    assert set(summary["benchmark"]) == {
        "dataset", "config", "split", "model", "utterances", "seed",
        "condition", "language", "n_skipped_transform",
        "n_skipped_empty_reference", "n_skipped_scoring", "n_streamed",
        "n_renamed_duplicate_uids", "wer_invisible", "revisions", "decode", "limit"}
    bench = summary["benchmark"]
    assert bench["n_skipped_empty_reference"] == 0
    assert bench["n_streamed"] == 2
    assert bench["wer_invisible"] is False
    assert bench["revisions"] == {"d": None, "m": None}
    assert set(summary["run_metadata"]) >= {"git_commit", "git_dirty",
                                            "packages"}


@pytest.mark.parametrize("limit", [None, 2])
def test_requested_limit_is_distinct_from_the_streamed_count(stubbed, tmp_path, limit):
    # A cap of two does not establish that the corpus yielded two rows.
    # Every condition records the requested cap alongside the actual count.
    stubbed[:] = [("a", "hello world")]
    b.run_benchmark("d", "c", "s", "m", limit, _runs(tmp_path, ["raw", "case_fold"]))
    for name in ["wer_summary.json", "wer_summary_case_fold.json"]:
        bench = json.loads((tmp_path / name).read_text("utf-8"))["benchmark"]
        assert bench["limit"] == limit
        assert bench["n_streamed"] == 1


def test_a_programming_error_in_a_transform_propagates(stubbed, tmp_path,
                                                       monkeypatch):
    from evaluation import conditions

    def broken(text):
        raise ImportError("transcription is missing")

    cond = conditions.get_condition("case_fold")
    monkeypatch.setitem(conditions._CONDITIONS, "case_fold",
                        conditions.Condition(
                            name="case_fold", description=cond.description,
                            transform=broken, apply_to_reference=True))
    stubbed[:] = [("a", "hello world")]
    with pytest.raises(ImportError):
        b.run_benchmark("d", "c", "s", "m", None,
                        _runs(tmp_path, ["raw", "case_fold"]))


def test_data_errors_are_skipped_counted_and_an_empty_condition_fails(
        stubbed, tmp_path, monkeypatch):
    from evaluation import conditions

    def fussy(text):
        raise ValueError("cannot handle this utterance")

    cond = conditions.get_condition("case_fold")
    monkeypatch.setitem(conditions._CONDITIONS, "case_fold",
                        conditions.Condition(
                            name="case_fold", description=cond.description,
                            transform=fussy, apply_to_reference=True))
    stubbed[:] = [("a", "hello world"), ("b", "hello world")]
    with pytest.raises(SystemExit, match="case_fold"):
        b.run_benchmark("d", "c", "s", "m", None,
                        _runs(tmp_path, ["raw", "case_fold"]))
    # The condition that did score was still written.
    assert _names(tmp_path / "wer_report.csv") == ["a", "b"]
    assert not (tmp_path / "wer_report_case_fold.csv").exists()


def test_skips_are_recorded_in_the_summary(stubbed, tmp_path, monkeypatch):
    from evaluation import conditions

    def picky(text):
        if text.startswith("skip"):
            raise ValueError("no")
        return text

    cond = conditions.get_condition("case_fold")
    monkeypatch.setitem(conditions._CONDITIONS, "case_fold",
                        conditions.Condition(
                            name="case_fold", description=cond.description,
                            transform=picky, apply_to_reference=True))
    stubbed[:] = [("a", "hello world"), ("b", "skip this")]
    b.run_benchmark("d", "c", "s", "m", None,
                    _runs(tmp_path, ["raw", "case_fold"]))
    summary = json.loads(
        (tmp_path / "wer_summary_case_fold.json").read_text("utf-8"))
    assert summary["benchmark"]["n_skipped_transform"] == 1
    assert summary["benchmark"]["utterances"] == 1


# ---------------------------------------------------------------------------
# Smaller helpers
# ---------------------------------------------------------------------------

def test_the_legacy_postprocessed_flags_are_gone():
    """EWER-16: their second naming rule once overwrote the raw report."""
    with pytest.raises(SystemExit):
        b._build_parser().parse_args(["--report-postprocessed", "x.csv"])
    runs = b._build_runs([], Path("a/wer_report.csv"), Path("a/wer_summary.json"))
    assert [r.condition_name for r in runs] == ["raw"]
    assert not hasattr(b, "_postprocess_hypothesis")


def test_the_resample_fallback_warns(monkeypatch, capsys):
    import builtins
    import numpy as np

    real_import = builtins.__import__

    def no_librosa(name, *args, **kwargs):
        if name == "librosa":
            raise ImportError("absent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_librosa)
    out = b._resample(np.ones(8, dtype="float32"), 8_000, 16_000)
    assert out.shape == (16,)
    assert "without anti-aliasing" in capsys.readouterr().err


def test_condition_and_suite_names_must_be_slugs():
    from evaluation import challenge_suites, conditions

    with pytest.raises(ValueError, match="does not match"):
        conditions._register(conditions.Condition(
            name="Pipeline-Full", description="x", transform=str))
    suite = challenge_suites.get_suite("ami")
    import dataclasses
    with pytest.raises(ValueError, match="does not match"):
        challenge_suites._register(dataclasses.replace(suite, name="AMI-x"))
