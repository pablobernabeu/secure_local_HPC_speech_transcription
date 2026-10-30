#!/usr/bin/env python3
"""
Catch the personal names a dictionary cannot know about.

The masking benchmark measured the limit of the curated dictionary
precisely: recall on names held out of it is zero, by construction. A list
can only redact what it has seen, and the names most worth protecting in a
research recording are often exactly the ones no list contains, because
they belong to participants rather than to public figures.

This module adds an optional second stage that recognises people by
context instead of by membership. It wraps a zero-shot named-entity model
(GLiNER, Zaratiana et al., NAACL 2024), which takes the entity types it
should look for as plain text labels at inference time, needs no
fine-tuning, and is small enough to run on a CPU. Nothing here contacts a
network at transcription time: the model is downloaded once, explicitly,
with ``python -m ner_masking --download``, and is then loaded from the
local cache with ``local_files_only=True`` at a pinned revision, so the
workflow's offline guarantee holds and a re-run cannot silently pick up
a re-uploaded checkpoint.

The stage is off by default and additive when on. It never *unmasks*
anything the dictionary caught; it only proposes further spans, so
enabling it can raise recall and can cost precision, and it cannot
silently reduce what was already redacted. The benchmark quantifies both
directions.

The detector is injectable. :class:`PersonNameDetector` takes any callable
of the form ``predict(text, labels, threshold)`` (GLiNER's own method is
adapted to it by :func:`load_person_detector`), so the
tests exercise the whole masking path with a stub and no model, and a
different backend can be substituted without touching the masker.

Usage::

    from ner_masking import load_person_detector
    detector = load_person_detector()          # None when unavailable
    mask, log = create_enhanced_name_masker(ner_detector=detector)

    python -m ner_masking "Ada met Kowalczyk in Warsaw."
"""

from __future__ import annotations

import argparse
import re
import sys

# The entity labels handed to the zero-shot model. Several near-synonyms
# are given because a zero-shot model keys on the label text itself, and a
# person is described differently across the registers this workflow sees
# (interview, lecture, meeting). Non-person labels are deliberately absent:
# this stage exists to find people, and asking for more would widen the
# false-positive surface for no gain in the privacy claim.
PERSON_LABELS = ("person", "person name", "participant name")

# GLiNER returns a score per span. The default is deliberately high: this
# stage runs *behind* a dictionary that already catches the common cases,
# so its job is to add confident finds, not to guess. The benchmark reports
# the trade-off at this setting.
DEFAULT_THRESHOLD = 0.6

# A small, CPU-friendly checkpoint. The PII-tuned community variant is a
# reasonable alternative where a deployment cares more about recall than
# about model size; both share the GLiNER interface.
DEFAULT_MODEL = "urchade/gliner_small-v2.1"
# The Hub commit of DEFAULT_MODEL that is loaded. It is the snapshot in the
# cache that reproduced the committed masking_report_ner.csv byte for byte,
# and every number in masking_summary_ner.json, under gliner 0.2.28 (checked
# 2026-09-25). The regenerated summary also carries a "ner" provenance block
# (model, revision, threshold, labels, call counts) that the committed file
# predates, so that file no longer matches byte for byte. A different model
# name needs its own revision.
DEFAULT_REVISION = "4e091416cf7c3481db542c2a3d26156916f3a47f"

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
# How the masker normalises the word it looks up (transcription.py,
# create_enhanced_name_masker): a trailing possessive is dropped, then every
# non-word character, so "O'Brien" becomes "obrien" and "Jean-Luc"
# "jeanluc". A detected name has to be offered in that form too, or the
# masker never finds it.
_POSSESSIVE_RE = re.compile(r"['’]s?$")
_NON_WORD_RE = re.compile(r"[^\w]")


def _masker_form(token: str) -> str:
    """Return *token* normalised the way the masker normalises a word."""
    return _NON_WORD_RE.sub("", _POSSESSIVE_RE.sub("", token.lower()))


class PersonNameDetector:
    """Return the word tokens that a NER model reads as personal names.

    The masker works word by word, so a span-based model has to be reduced
    to a token decision. Each returned entity's text is split into word
    tokens and lower-cased, and the masker asks whether the word it is
    looking at is in that set. This deliberately loses span structure: a
    two-word name contributes both of its words independently, which is
    what the masker needs and what makes the result comparable with a
    dictionary hit.

    Parameters
    ----------
    predict:
        Callable ``(text, labels, threshold) -> list[dict]``, called with
        those three arguments positionally. Each result is expected to
        carry a ``text`` key, and optionally ``score`` and ``label``.
        GLiNER's own ``predict_entities`` does *not* have this shape (its
        third parameter is ``flat_ner``), so :func:`load_person_detector`
        wraps it; pass a bare ``predict_entities`` here and the threshold
        lands in ``flat_ner``.
    labels, threshold:
        Passed through to *predict*.

    Attributes
    ----------
    n_calls, n_failures:
        Model calls made and calls that raised. A model that raises on
        every call would otherwise turn the stage into a silent no-op,
        and a benchmark would report dictionary-only numbers as the NER
        arm.
    first_error:
        ``repr`` of the first exception, or ``None``.
    """

    def __init__(self, predict, labels=PERSON_LABELS,
                 threshold: float = DEFAULT_THRESHOLD):
        self._predict = predict
        self._labels = list(labels)
        self._threshold = threshold
        self.n_calls = 0
        self.n_failures = 0
        self.first_error: str | None = None

    def tokens_in(self, text: str) -> set[str]:
        """Return lower-cased word tokens belonging to detected people.

        Each entity contributes its letter runs (``"O'Brien"`` gives ``o``
        and ``brien``) and each of its whitespace-separated words in the
        form the masker looks up (``obrien``), so a name with an internal
        apostrophe or hyphen can be matched.

        A failure in the model is reported as "no detections": this stage
        is an enhancement to a masker that already works, and it must never
        be the reason a transcript fails to be produced. The failure is
        counted, and the first one is reported on stderr, so it is not
        silent. An empty or whitespace text short-circuits, since the
        common case in a word loop is plenty of short sentences.
        """
        if not text or not text.strip():
            return set()
        self.n_calls += 1
        try:
            entities = self._predict(text, self._labels, self._threshold) or []
        except Exception as exc:
            self.n_failures += 1
            if self.first_error is None:
                self.first_error = repr(exc)
                print(f"   ⚠️  NER stage failed ({type(exc).__name__}: {exc}); "
                      "those sentences fall back to the name dictionary alone",
                      file=sys.stderr)
            return set()

        tokens: set[str] = set()
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            score = entity.get("score")
            if score is not None and score < self._threshold:
                continue
            entity_text = str(entity.get("text", ""))
            for token in _TOKEN_RE.findall(entity_text):
                tokens.add(token.lower())
            for word in entity_text.split():
                form = _masker_form(word)
                if form:
                    tokens.add(form)
        return tokens


def _revision_for(model_name: str, revision: str | None) -> str | None:
    """Return *revision*, or the pinned one when *model_name* is the default."""
    if revision is not None:
        return revision
    return DEFAULT_REVISION if model_name == DEFAULT_MODEL else None


def load_person_detector(model_name: str = DEFAULT_MODEL,
                         threshold: float = DEFAULT_THRESHOLD,
                         quiet: bool = False,
                         revision: str | None = None,
                         local_files_only: bool = True):
    """Load the zero-shot model and return a detector, or ``None``.

    ``None`` means the optional dependency or its weights are unavailable,
    which is not an error: the caller carries on with the dictionary alone.
    The reason is printed once unless *quiet*, because a user who asked for
    this stage should learn why it is not running rather than silently
    getting the old behaviour.

    Parameters
    ----------
    model_name, threshold:
        The checkpoint and the score a span must reach.
    revision:
        Hub commit to load; defaults to :data:`DEFAULT_REVISION` for the
        default model and to the latest for any other.
    local_files_only:
        Load from the local cache without contacting the network, which is
        the offline guarantee. :func:`download_model` fills the cache.

    GLiNER's ``predict_entities`` takes ``(text, labels, flat_ner=True,
    threshold=0.5)``, so the threshold is passed by keyword. Passed third
    positionally, as this function once did, it lands in ``flat_ner`` and
    the model runs at 0.5 whatever was asked for; thresholds of 0.5 and
    above were rescued by the score filter in
    :meth:`PersonNameDetector.tokens_in`, and those below had no effect.
    """
    try:
        from gliner import GLiNER
    except ImportError:
        if not quiet:
            print("   ℹ️  NER masking unavailable: pip install gliner")
        return None
    try:
        model = GLiNER.from_pretrained(
            model_name, revision=_revision_for(model_name, revision),
            local_files_only=local_files_only)
    except Exception as exc:
        if not quiet:
            hint = (" (download it once with `python -m ner_masking "
                    "--download`)" if local_files_only else "")
            print(f"   ℹ️  NER masking unavailable ({type(exc).__name__}: "
                  f"{exc}){hint}; continuing with the name dictionary alone")
        return None

    def predict(text, labels, threshold):
        return model.predict_entities(text, labels, threshold=threshold)

    detector = PersonNameDetector(predict, threshold=threshold)
    detector.model_name = model_name
    detector.revision = _revision_for(model_name, revision)
    return detector


def download_model(model_name: str = DEFAULT_MODEL,
                   revision: str | None = None) -> None:
    """Fetch *model_name* at its pinned revision into the local cache.

    This is the one step that contacts the network. Side effects: writes
    to the Hugging Face cache.

    Raises
    ------
    ImportError
        If gliner is not installed.
    """
    from gliner import GLiNER
    GLiNER.from_pretrained(model_name,
                           revision=_revision_for(model_name, revision))


def provenance(detector) -> dict:
    """Describe the NER stage for a results file.

    Returns the model id, revision, threshold, labels, gliner version and
    the call and failure counts, so a summary can be tied to what produced
    it.
    """
    try:
        import gliner
        version = getattr(gliner, "__version__", None)
    except ImportError:
        version = None
    return {
        "model_id": getattr(detector, "model_name", None),
        "revision": getattr(detector, "revision", None),
        "threshold": detector._threshold,
        "labels": list(detector._labels),
        "gliner_version": version,
        "calls": detector.n_calls,
        "failures": detector.n_failures,
        "first_error": detector.first_error,
    }


def main(argv=None) -> int:
    """Probe the detector on a sentence, for checking a deployment."""
    parser = argparse.ArgumentParser(
        prog="ner_masking",
        description="Show which words a zero-shot NER model reads as "
                    "personal names.")
    parser.add_argument("text", nargs="*", help="text to analyse")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=None,
                        help="Hub commit (default: the pinned one for the "
                             "default model).")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--download", action="store_true",
                        help="Fetch the model into the local cache and exit; "
                             "the only step that uses the network.")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.download:
        try:
            download_model(args.model, args.revision)
        except Exception as exc:
            print(f"  Download failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 1
        print(f"  cached {args.model} at "
              f"{_revision_for(args.model, args.revision) or 'latest'}")
        return 0

    detector = load_person_detector(args.model, args.threshold,
                                    revision=args.revision)
    if detector is None:
        print("  No detector available.")
        return 1
    text = " ".join(args.text) or "Ada Lovelace met Mr Kowalczyk in Warsaw."
    print(f"  model:     {args.model}")
    print(f"  threshold: {args.threshold}")
    print(f"  text:      {text}")
    print(f"  person tokens: {sorted(detector.tokens_in(text))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
