"""Audit fixes to the NER masking stage (EPRIV-08, -09, -12, -18).

No model is loaded: a fake ``gliner`` module stands in for the library, with
the real ``predict_entities`` parameter order, so the tests pin the calling
contract rather than a stub's.
"""

from __future__ import annotations

import contextlib
import io
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import ner_masking  # noqa: E402
from ner_masking import PersonNameDetector  # noqa: E402


class _FakeModel:
    """Mimics gliner 0.2.28: predict_entities(text, labels, flat_ner, threshold)."""

    def __init__(self):
        self.calls = []

    def predict_entities(self, text, labels, flat_ner=True, threshold=0.5,
                         multi_label=False):
        self.calls.append({"flat_ner": flat_ner, "threshold": threshold})
        return [{"text": "Ada", "score": 0.4, "label": "person"}
                ] if threshold <= 0.4 else []


@pytest.fixture
def fake_gliner(monkeypatch):
    model = _FakeModel()
    loads = []

    class GLiNER:  # noqa: D401 - stand-in
        @staticmethod
        def from_pretrained(name, **kwargs):
            loads.append((name, kwargs))
            return model

    module = types.ModuleType("gliner")
    module.GLiNER = GLiNER
    module.__version__ = "0.0-test"
    monkeypatch.setitem(sys.modules, "gliner", module)
    return model, loads


def test_threshold_reaches_the_model_by_keyword(fake_gliner):
    model, _ = fake_gliner
    detector = ner_masking.load_person_detector(threshold=0.3, quiet=True)
    assert detector.tokens_in("Ada spoke.") == {"ada"}
    assert model.calls == [{"flat_ner": True, "threshold": 0.3}]


def test_load_is_pinned_and_offline(fake_gliner):
    _, loads = fake_gliner
    ner_masking.load_person_detector(quiet=True)
    name, kwargs = loads[0]
    assert name == ner_masking.DEFAULT_MODEL
    assert kwargs == {"revision": ner_masking.DEFAULT_REVISION,
                      "local_files_only": True}


def test_provenance_records_the_model(fake_gliner):
    detector = ner_masking.load_person_detector(quiet=True)
    detector.tokens_in("Ada spoke.")
    info = ner_masking.provenance(detector)
    assert info["model_id"] == ner_masking.DEFAULT_MODEL
    assert info["revision"] == ner_masking.DEFAULT_REVISION
    assert info["threshold"] == ner_masking.DEFAULT_THRESHOLD
    assert info["gliner_version"] == "0.0-test"
    assert info["calls"] == 1 and info["failures"] == 0


def test_apostrophe_and_hyphen_names_reach_the_masker():
    def predict(text, labels, threshold):
        return [{"text": "O'Brien", "score": 0.9},
                {"text": "Jean-Luc", "score": 0.9}]

    tokens = PersonNameDetector(predict).tokens_in("x")
    assert {"obrien", "jeanluc", "o", "brien", "jean", "luc"} <= tokens


def test_real_masker_masks_apostrophe_and_hyphen_names(transcription_module):
    def predict(text, labels, threshold):
        return [{"text": "O'Brien", "score": 0.9},
                {"text": "Jean-Luc", "score": 0.9}]

    with contextlib.redirect_stdout(io.StringIO()):
        mask, _ = transcription_module.create_enhanced_name_masker(
            ner_detector=PersonNameDetector(predict))
    out = mask("Then O'Brien and Jean-Luc joined the call.")
    assert "O'Brien" not in out and "Jean-Luc" not in out


def test_failures_are_counted_and_reported(capsys):
    def predict(text, labels, threshold):
        raise RuntimeError("tokeniser mismatch")

    detector = PersonNameDetector(predict)
    assert detector.tokens_in("Ada spoke.") == set()
    assert detector.tokens_in("Bo spoke.") == set()
    assert (detector.n_calls, detector.n_failures) == (2, 2)
    assert "tokeniser mismatch" in detector.first_error
    # Reported once, not per sentence.
    assert capsys.readouterr().err.count("NER stage failed") == 1


def test_benchmark_refuses_a_ner_arm_that_never_ran():
    from evaluation.benchmark_masking import _check_ner_ran

    def broken(text, labels, threshold):
        raise RuntimeError("boom")

    detector = PersonNameDetector(broken)
    detector.tokens_in("Ada spoke.")
    with pytest.raises(SystemExit, match="failed on 1 of 1"):
        _check_ner_ran(detector)
    with pytest.raises(SystemExit, match="never called"):
        _check_ner_ran(PersonNameDetector(broken))
