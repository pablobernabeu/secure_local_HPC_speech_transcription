"""Compare what the NER stage proposes on the case study under each label set.

output/case_study/ner_false_positive_test.md argues that narrower label
phrasings do not stop the zero-shot model proposing person references
that are not names. This records the measurement behind that paragraph
(audit finding NEW-10), which a local run made on 4 October 2026 without
committing: the shipped label set and each of the three single phrasings
the note names, run over ``output/case_study/ep05_raw_text.txt`` split
into sentences as the name masker splits it, at the pinned model, revision
and threshold.

For every word of every sentence that the model's entities cover, it
records the word in the form the masker looks up and whether the
masker's capitalisation gate would let the NER stage mask it. Title words
are left out, since the masker never lets the NER stage mask one.

Usage:
    python tools/ner_label_phrasings.py \\
        --output output/case_study/ner_label_phrasings.json
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import io
import json
import sys
from importlib.metadata import version
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TEXT = REPO / "output" / "case_study" / "ep05_raw_text.txt"

#: The shipped set first, then the three phrasings the note names.
LABEL_SETS = {
    "shipped": None,                      # ner_masking.PERSON_LABELS
    "person name": ("person name",),
    "personal name": ("personal name",),
    "name of a person": ("name of a person",),
}


def measure(text: str, predict, sentences_of, is_capitalised, masker_form,
            titles, label_sets: dict, threshold: float) -> dict:
    """Return, per label set, the words its entities cover in *text*.

    The model is reached only through *predict* ``(text, labels,
    threshold)``, so a test can supply a fake one.
    """
    from ner_masking import PersonNameDetector

    sentences = [s for s in sentences_of(text) if s.strip()]
    results = {}
    for name, labels in label_sets.items():
        detector = PersonNameDetector(predict, labels=labels, threshold=threshold)
        gated, ungated = collections.Counter(), collections.Counter()
        for sentence in sentences:
            tokens = detector.tokens_in(sentence)
            for word in sentence.split():
                form = masker_form(word)
                if not form or form not in tokens or form in titles:
                    continue
                (gated if is_capitalised(word) else ungated)[form] += 1
        results[name] = {
            "labels": list(labels),
            "capitalised": dict(sorted(gated.items())),
            "lower_case": dict(sorted(ungated.items())),
            "model_calls": detector.n_calls,
            "model_failures": detector.n_failures,
        }
    return {"n_sentences": len(sentences), "label_sets": results}


def main(argv=None) -> int:
    """Measure every label set on the case study and write the report.

    *argv* replaces ``sys.argv[1:]``. Returns 0. Needs gliner and the
    pinned model in the local Hugging Face cache (it is loaded with
    ``local_files_only``), and raises when either is missing. Side
    effects: runs ``git`` through :func:`provenance.run_metadata`, reads
    the case-study text, writes ``--output`` with LF line endings,
    replacing it, and prints the capitalised words each label set covers.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    import ner_masking
    from provenance import run_metadata
    metadata = run_metadata(ignore=[args.output])
    with contextlib.redirect_stdout(io.StringIO()):
        import transcription
    from gliner import GLiNER

    model = GLiNER.from_pretrained(ner_masking.DEFAULT_MODEL,
                                   revision=ner_masking.DEFAULT_REVISION,
                                   local_files_only=True)

    def predict(text, labels, threshold):
        # By keyword: predict_entities' third parameter is flat_ner.
        return model.predict_entities(text, labels, threshold=threshold)

    label_sets = {name: labels or ner_masking.PERSON_LABELS
                  for name, labels in LABEL_SETS.items()}
    text = TEXT.read_text(encoding="utf-8")
    result = measure(text, predict, transcription._split_sentences_for_masking,
                     transcription._token_is_capitalised, ner_masking._masker_form,
                     transcription.TITLE_WORDS, label_sets,
                     ner_masking.DEFAULT_THRESHOLD)
    report = {
        "description": ("Words the NER stage's entities cover in the case-study "
                        "text, per label set, split by whether the masker's "
                        "capitalisation gate would let the stage mask them "
                        "(audit finding NEW-10)."),
        "input": {"path": TEXT.relative_to(REPO).as_posix(),
                  "sha256_lf": hashlib.sha256(
                      text.replace("\r\n", "\n").encode("utf-8")).hexdigest()},
        "model": ner_masking.DEFAULT_MODEL,
        "revision": ner_masking.DEFAULT_REVISION,
        "threshold": ner_masking.DEFAULT_THRESHOLD,
        "gliner": version("gliner"),
        **result,
        "run_metadata": metadata,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8", newline="\n")
    for name, block in report["label_sets"].items():
        print(f"{name:<18} capitalised: {', '.join(block['capitalised']) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
