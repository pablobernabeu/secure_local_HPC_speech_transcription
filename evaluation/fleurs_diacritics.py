#!/usr/bin/env python3
"""Share of FLEURS reference words that carry a diacritic, per language.

``fleurs_multilingual_summary.json`` relates how much the old Unicode strip
inflated each language's word error rate to how often that language writes
a diacritic. The committed shares (88, 60, 56, 60, 50 and 0 per cent) were
measured outside the repository on an unrecorded "representative sample"
(audit finding OUTPUTS-11). This module measures them on the whole test
split the benchmark scores, from the references it scores against.

Definition. A word is a whitespace-separated token of an utterance's
reference, and it carries a diacritic when it holds at least one letter
outside ASCII (``str.isalpha`` and a code point above 127). For the six
Latin-script languages here that is every accented or modified letter,
plus German ``ß``; it is also exactly the set of letters the defect
deleted, since ``remove_emojis_and_unicode_artifacts`` then stripped every
non-ASCII code point. Utterances are counted as the benchmark scores them,
one per recording, so a sentence read by several speakers counts once per
reading.

The reference is the ``transcription`` column, the one
``evaluation.benchmark_wer`` falls back to for FLEURS (see
``evaluation/challenge_suites.py``), streamed at the revision
:mod:`evaluation.revisions` pins for ``google/fleurs``.

Usage (needs network access to the Hub, or its cache)::

    python -m evaluation.fleurs_diacritics \\
        --out output/evaluation/fleurs_diacritic_shares.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evaluation.fleurs_multilingual import LANGUAGES  # noqa: E402

DATASET = "google/fleurs"
SPLIT = "test"
REFERENCE_FIELD = "transcription"
DEFINITION = ("share of whitespace-separated reference words holding at least "
              "one letter outside ASCII (str.isalpha and code point > 127)")
#: The packages the record's run metadata names: the ones that stream the
#: references.
_PACKAGES = ("datasets", "huggingface_hub")


def carries_diacritic(word: str) -> bool:
    """Whether *word* holds a letter outside ASCII (see the module docstring)."""
    return any(ch.isalpha() and ord(ch) > 127 for ch in word)


def shares(references) -> dict:
    """Count utterances, words and words with a diacritic in *references*.

    Returns ``{"n_utterances", "n_words", "n_words_with_diacritic",
    "pct_words_with_diacritic"}``, the percentage rounded to a whole number
    as the committed summary gives it (the counts keep the exact share).
    """
    n_utt = n_words = n_marked = 0
    for text in references:
        n_utt += 1
        words = str(text).split()
        n_words += len(words)
        n_marked += sum(carries_diacritic(w) for w in words)
    pct = round(100 * n_marked / n_words) if n_words else None
    return {"n_utterances": n_utt, "n_words": n_words,
            "n_words_with_diacritic": n_marked, "pct_words_with_diacritic": pct}


def _references(config: str):
    """Yield the reference of every recording of *config*'s test split.

    Streams only the reference column where the loader allows it, so no
    audio is downloaded; otherwise streams the rows with audio decoding off.
    """
    import datasets as hf_datasets

    from evaluation.revisions import revision_for

    kwargs = dict(split=SPLIT, streaming=True, trust_remote_code=False,
                  revision=revision_for(DATASET))
    try:
        ds = hf_datasets.load_dataset(DATASET, config, columns=[REFERENCE_FIELD],
                                      **kwargs)
    except (TypeError, ValueError):
        ds = hf_datasets.load_dataset(DATASET, config, **kwargs)
        ds = ds.cast_column("audio", hf_datasets.Audio(decode=False))
    for row in ds:
        yield row[REFERENCE_FIELD] or ""


def measure(languages=LANGUAGES, references=_references,
            run_meta: dict | None = None) -> dict:
    """Return the record written to ``--out``: the shares and their provenance.

    *run_meta* is recorded as ``run_metadata``: the
    :func:`provenance.run_metadata` that a caller about to write the record
    read first, leaving the record's own file out of the dirty check
    (:func:`main` does). ``None`` reads it here, which counts a rewritten
    copy of the record in the checkout as a change.
    """
    from evaluation.revisions import revision_for
    from provenance import run_metadata

    return {
        "dataset": DATASET,
        "revision": revision_for(DATASET),
        "split": SPLIT,
        "reference_field": REFERENCE_FIELD,
        "definition": DEFINITION,
        "languages": {config: shares(references(config)) for config in languages},
        "run_metadata": (run_meta if run_meta is not None
                         else run_metadata(packages=_PACKAGES)),
    }


def main(argv: list[str] | None = None) -> int:
    """Measure every language and write ``--out``; returns 0."""
    p = argparse.ArgumentParser(prog="evaluation.fleurs_diacritics",
                                description=__doc__.splitlines()[0])
    p.add_argument("--languages", default=",".join(LANGUAGES),
                   help="FLEURS configurations (default: %(default)s).")
    p.add_argument("--out", type=Path, required=True,
                   help="Output JSON.")
    args = p.parse_args(argv)
    from provenance import run_metadata
    # Read before the record is written, leaving it out of the dirty check,
    # as provenance.write_sidecar does for the CSV-only writers. Read inside
    # measure without the ignore list, as it was, a second measurement in
    # place counted the first one's record as uncommitted code (audit
    # finding OUTPUTS-12).
    run_meta = run_metadata(packages=_PACKAGES, ignore=(args.out,))
    record = measure(tuple(c.strip() for c in args.languages.split(",") if c.strip()),
                     run_meta=run_meta)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, indent=2) + "\n")
    for config, entry in record["languages"].items():
        print(f"  {config:<7} {entry['pct_words_with_diacritic']}% of "
              f"{entry['n_words']} words ({entry['n_utterances']} utterances)")
    print(f"  written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
