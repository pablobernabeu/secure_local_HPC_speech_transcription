"""Tests for the optional NER masking stage.

The model itself is an optional dependency and a slow one, so every test
here injects a stub with GLiNER's ``predict_entities`` shape. That is not
a shortcut: the property worth pinning is how the masker *uses* the
detector, and a stub makes each rule testable in isolation, which a real
model's judgement never would.

The load-bearing property is that the stage is purely additive. It may
mask more, never less, so switching it on cannot cost a redaction the
dictionary was already making. The rest guard the ways an optional stage
can misbehave: crashing the transcript, masking titles, or leaving no
audit trail of which stage decided what.
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ner_masking import (
    DEFAULT_THRESHOLD,
    PersonNameDetector,
    load_person_detector,
)


def _masker(**kwargs):
    """Build a masker without its loading chatter on stdout."""
    from transcription import create_enhanced_name_masker
    with contextlib.redirect_stdout(io.StringIO()):
        return create_enhanced_name_masker(**kwargs)


def _detector_for(mapping, score=0.9):
    """A stub detector returning *mapping*'s spans when present in text."""
    def predict(text, labels, threshold):
        return [{"text": span, "score": score, "label": "person"}
                for span in mapping if span in text]
    return PersonNameDetector(predict)


def test_detector_reduces_spans_to_lowercase_tokens():
    detector = _detector_for(["Ada Lovelace"])
    assert detector.tokens_in("I met Ada Lovelace.") == {"ada", "lovelace"}


def test_detector_honours_the_score_threshold():
    detector = _detector_for(["Kowalczyk"], score=0.2)
    assert detector.tokens_in("I met Kowalczyk.") == set()


def test_detector_is_quiet_on_empty_text():
    calls = []

    def predict(text, labels, threshold):
        calls.append(text)
        return []

    detector = PersonNameDetector(predict)
    assert detector.tokens_in("") == set()
    assert detector.tokens_in("   ") == set()
    assert calls == []          # the model is not woken for nothing


def test_detector_survives_a_failing_model():
    """A broken model must degrade to 'found nothing', never propagate."""
    def predict(text, labels, threshold):
        raise RuntimeError("model exploded")

    assert PersonNameDetector(predict).tokens_in("Ada was here.") == set()


def test_detector_ignores_malformed_results():
    def predict(text, labels, threshold):
        return [None, "not a dict", {}, {"text": "Ada"}]

    assert PersonNameDetector(predict).tokens_in("Ada") == {"ada"}


def test_ner_catches_a_name_the_dictionary_misses():
    """The point of the stage: recall on out-of-dictionary names."""
    sentence = "I met Kowalczyk at the workshop."
    plain, _ = _masker()
    assert "Kowalczyk" in plain(sentence)              # the measured limit

    with_ner, _ = _masker(ner_detector=_detector_for(["Kowalczyk"]))
    assert "Kowalczyk" not in with_ner(sentence)
    assert "[NAME]" in with_ner(sentence)


def test_the_stage_is_purely_additive():
    """Enabling NER may mask more, never less.

    Checked against a detector that finds nothing at all, which is the
    case where a regression would show as *lost* redactions.
    """
    sentence = "Maria and Ahmed spoke with Kowalczyk about the study."
    plain, _ = _masker()
    blind, _ = _masker(ner_detector=_detector_for([]))
    assert blind(sentence) == plain(sentence)

    seeing, _ = _masker(ner_detector=_detector_for(["Kowalczyk"]))
    masked_plain = plain(sentence).count("[NAME]") + plain(sentence).count("[SURNAME]")
    masked_ner = seeing(sentence).count("[NAME]") + seeing(sentence).count("[SURNAME]")
    assert masked_ner > masked_plain


def test_titles_are_not_masked_as_names():
    """A real model returns the whole span, titles included.

    Observed with GLiNER: "Doctor Kowalczyk" yields "doctor" as well as the
    surname. The title branch already emits [TITLE], so masking it here
    would be both a false positive and the wrong label.
    """
    detector = _detector_for(["Doctor Kowalczyk"])
    masker, log = _masker(ner_detector=detector)
    out = masker("Doctor Kowalczyk led the session.")
    assert "[NAME]" in out
    assert "doctor" not in out.lower() or "[TITLE]" in out
    sources = {row["original"].lower(): row["source"] for row in log()}
    assert sources.get("kowalczyk") == "ner"


def test_ner_respects_the_capitalisation_gate_by_default():
    """A lower-case NER proposal is refused unless case_insensitive is set.

    Measured reason: the model finds person *references*, not person
    *names*, so on a transcript that discusses people it proposes "speaker
    one", "the researcher", "the user", even "we". On the case-study
    transcript that was fifteen further redactions, every one a false
    positive, beside the dictionary's three, of which two were true names
    (the third was "Jordan", in a speaker's example of a masker taking the
    country for a person). Those references are lower-case and real names
    are capitalised, so the stage is held to the same gate the dictionary
    uses, and the same flag relaxes both together.
    """
    sentence = "we asked the researcher about it"
    detector = _detector_for(["we", "researcher"])

    gated, _ = _masker(ner_detector=detector)
    assert gated(sentence) == sentence          # nothing masked

    relaxed, _ = _masker(ner_detector=detector, case_insensitive=True)
    assert "[NAME]" in relaxed(sentence)        # the flag admits them


def test_capitalised_out_of_dictionary_names_still_pass_the_gate():
    """The gate must not cost the stage its whole purpose."""
    detector = _detector_for(["Kowalczyk"])
    masker, _ = _masker(ner_detector=detector)
    assert "[NAME]" in masker("I met Kowalczyk at the workshop.")


def test_the_log_records_which_stage_masked_each_word():
    """Auditability: the two stages must be separable after the fact."""
    detector = _detector_for(["Kowalczyk"])
    masker, log = _masker(ner_detector=detector)
    masker("Maria met Kowalczyk today.")
    sources = {row["original"].strip(".,").lower(): row["source"]
               for row in log()}
    assert sources["maria"] == "dictionary"
    assert sources["kowalczyk"] == "ner"


def test_dictionary_hits_keep_their_surname_label():
    """A NER find has no first-name/surname distinction and uses [NAME];
    a dictionary surname must keep [SURNAME]."""
    detector = _detector_for(["Kowalczyk"])
    masker, _ = _masker(ner_detector=detector)
    out = masker("I met Bernabeu and Kowalczyk.")
    assert "[SURNAME]" in out       # dictionary surname keeps its label
    assert "[NAME]" in out          # the NER find uses the generic one


def test_a_crashing_detector_does_not_break_masking():
    """The transcript matters more than the enhancement."""
    class Exploding:
        def tokens_in(self, text):
            raise RuntimeError("detector exploded")

    masker, _ = _masker(ner_detector=Exploding())
    out = masker("Maria spoke today.")
    assert "[NAME]" in out          # the dictionary stage still worked


def test_an_exception_after_the_model_call_is_counted(capsys):
    """SC-17: a malformed entity whose score does not compare with the
    threshold raises inside tokens_in, after the model call. The masker
    once swallowed it without a count, so a benchmark that checks
    n_failures reported the NER arm as clean."""
    def predict(text, labels, threshold):
        return [{"text": "Kowalczyk", "score": "high", "label": "person"}]

    detector = PersonNameDetector(predict)
    masker, _ = _masker(ner_detector=detector)
    out = masker("Maria met Kowalczyk. Maria left.")
    assert "[NAME] met Kowalczyk." in out      # the dictionary alone
    assert detector.n_calls == 2
    assert detector.n_failures == 2
    assert "TypeError" in detector.first_error
    # Reported once on stderr, not once per sentence.
    assert capsys.readouterr().err.count("NER stage failed") == 1


def test_a_counted_exception_makes_the_benchmark_refuse_the_arm():
    """The count reaches benchmark_masking._check_ner_ran."""
    from evaluation.benchmark_masking import _check_ner_ran

    class Faulty:
        n_calls = 1
        n_failures = 0
        first_error = None

        def tokens_in(self, text):
            raise KeyError("text")

    detector = Faulty()
    masker, _ = _masker(ner_detector=detector)
    with contextlib.redirect_stderr(io.StringIO()):
        masker("Maria spoke today.")
    assert detector.n_failures == 1
    assert detector.first_error == "KeyError('text')"
    with pytest.raises(SystemExit):
        _check_ner_ran(detector)


def test_load_person_detector_returns_none_when_unavailable(monkeypatch):
    """A missing dependency is reported, not raised."""
    monkeypatch.setitem(sys.modules, "gliner", None)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert load_person_detector(quiet=False) is None
    assert "gliner" in out.getvalue()


def test_threshold_default_is_conservative():
    """The stage runs behind a dictionary, so it should add confident
    finds rather than guesses."""
    assert DEFAULT_THRESHOLD >= 0.5
