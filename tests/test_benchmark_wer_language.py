"""Tests for the multilingual ``--language`` wiring in ``benchmark_wer``.

The scoring dependencies (jiwer, datasets, transformers) are imported
lazily, so the module and its CLI load without them; these tests run
everywhere and pin the argument plumbing that drives the non-English
FLEURS wave, with ``run_benchmark`` stubbed so no model is built.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import benchmark_wer as b

# --report and --summary are required (EWER-11); run_benchmark is stubbed, so
# nothing is written.
_OUT = ["--report", "r.csv", "--summary", "s.json"]


def test_parser_exposes_language_and_field_overrides():
    ns = b._build_parser().parse_args(
        _OUT + ["--language", "german", "--ref-field", "transcription",
         "--uid-field", "id"])
    assert ns.language == "german"
    assert ns.ref_field == "transcription"
    assert ns.uid_field == "id"


def test_language_defaults_to_english(monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(b, "run_benchmark", lambda **kw: cap.update(kw))
    b.main(_OUT + ["--dataset", "x", "--config", "c", "--split", "test",
            "--conditions", "raw"])
    assert cap["language"] == "english"


def test_explicit_language_and_fields_thread_through(monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(b, "run_benchmark", lambda **kw: cap.update(kw))
    b.main(_OUT + ["--dataset", "google/fleurs", "--config", "fr_fr", "--split", "test",
            "--language", "french", "--ref-field", "transcription",
            "--uid-field", "id", "--conditions", "raw,pipeline_full"])
    assert cap["language"] == "french"
    assert cap["ref_field"] == "transcription"
    assert cap["uid_field"] == "id"
    assert cap["dataset_name"] == "google/fleurs"
    assert cap["config"] == "fr_fr"
    assert [r.condition_name for r in cap["runs"]] == ["raw", "pipeline_full"]


def test_suite_defaults_english_and_cli_overrides(monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(b, "run_benchmark", lambda **kw: cap.update(kw))
    # A suite keeps the English default and supplies its own ref field.
    b.main(_OUT + ["--suite", "fleurs", "--conditions", "raw"])
    assert cap["language"] == "english"
    assert cap["ref_field"] == "transcription"
    # An explicit --language overrides the default even with a suite.
    cap.clear()
    b.main(_OUT + ["--suite", "fleurs", "--language", "spanish", "--conditions", "raw"])
    assert cap["language"] == "spanish"
