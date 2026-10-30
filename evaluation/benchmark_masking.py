#!/usr/bin/env python3
"""
Benchmark the personal-name masking layer as a PII-detection task.

The transcription pipeline ships an optional name-masking pass
(``transcription.create_enhanced_name_masker``) that replaces detected
personal names with ``[NAME]``, ``[SURNAME]`` or ``[TITLE]`` placeholders.
The manuscript lists this masking as a privacy contribution but never
measures how well it actually redacts names.  This module supplies the
missing experiment: it treats masking as detection and reports precision,
recall, F1 and false-negative leakage, broken down by the factors that the
masker's design makes salient.

Method (reproducible name injection, no manual annotation)
----------------------------------------------------------
The masker only redacts a word when its first letter is upper case (the
letter, not a quotation mark or bracket in front of it) and the
lower-cased word is present in the curated dictionary
(``data/curated_names.csv``, nine languages).  Both properties are
adversarial knobs, so the benchmark varies them explicitly:

* **Name pool.**  Personal names are drawn from two pools.  *In-dictionary*
  names are sampled from the curated CSV across its nine languages.
  *Out-of-dictionary* names come from a hand-built held-out list
  (:data:`OUT_OF_DB_NAMES`) of real personal names verified to be absent
  from the CSV; these probe recall on unseen names and expose the
  small, closed-dictionary limitation.
* **Carrier templates.**  Each name is injected into sentence templates
  with a ``{name}`` slot and otherwise known non-name tokens, covering
  five positions: sentence-start, mid-sentence, immediately after a
  title (``Dr {name}``), and, as later cells, just after an opening
  quotation mark (``"{name}``) and an opening parenthesis (``({name}``).
  The last two probe reported speech and asides, where the masker once
  tested the capitalisation of the quote rather than of the name and
  leaked it (audit findings EPRIV-10, T1-03).  Their cases follow all the
  original ones, so the report's first rows are the original cases in
  their original order.
* **Casing.**  Every case is generated in both Title-case and lower-case
  to expose the capitalisation dependency.

For each ``(name x template x casing x position)`` case the benchmark
records the gold span of the injected token, runs the masker, and counts a
**hit** when that token became a placeholder.  Carrier (non-name) tokens
that the masker replaces are counted as **false positives**.

Scoring
-------
Per cell and overall::

    recall    = injected names masked / injected names total
    precision = injected names masked / all tokens the masker replaced
    f1        = harmonic mean of precision and recall
    leakage   = 1 - recall          (the privacy-relevant false-negative rate)

Outputs
-------
``output/evaluation/masking_report.csv``
    One row per case (name, language, in_db, kind, casing, position,
    gold token, masker output, hit / false-positive counts).
``output/evaluation/masking_summary.json``
    Overall metrics plus per-breakdown metrics (in_db, language, casing,
    morphology, position) and the run's ``n`` and ``seed``.  The language
    breakdown labels every held-out name ``held_out``, so the curated
    languages' cells hold in-dictionary names only.

Usage::

    python -m evaluation.benchmark_masking
    python -m evaluation.benchmark_masking --seed 7 --n-per-cell 3

This module is pure Python and CPU-only: it imports the masker factory
from :mod:`transcription` but touches none of the audio or model code.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CSV = _PROJECT_ROOT / "data" / "curated_names.csv"
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "output" / "evaluation"
_DEFAULT_SEED = 42
_DEFAULT_N_PER_CELL = 4

_PLACEHOLDER_RE = re.compile(r"\[(?:NAME|SURNAME|TITLE)\]")

# Held-out personal names verified absent from data/curated_names.csv at the
# time of writing (checked case-insensitively against every CSV entry).  They
# exist purely to measure recall on names the closed dictionary has never
# seen.  The verification is re-run at load time by
# :func:`_partition_out_of_db_names`, which drops any entry that has since
# been added to the CSV, so the "out-of-dictionary" label can never silently
# become false.
#
# The second element is a sampling stratum, not the name's origin: the
# benchmark draws n_per_cell names per stratum. The labels are the curated
# language each name was filed under when the list was written, and several
# are wrong as origins (Mariko, Kenji, Yuki and Nakamura are Japanese, filed
# as chinese; Katarzyna, Grzegorz and Agnieszka are Polish, filed as
# polynesian; Nowak is Polish, filed as german). They used to be reported as
# languages, which put Polish names in the Polynesian cell of by_language
# (audit finding EPRIV-19). Held-out cases are now labelled "held_out"; the
# strata are kept as they were so that the seeded sample, and therefore every
# out_of_db figure, is unchanged.
OUT_OF_DB_NAMES: tuple[tuple[str, str], ...] = (
    # (name, sampling stratum)
    ("Bjork", "english"), ("Soren", "german"), ("Eirlys", "english"),
    ("Mariko", "chinese"), ("Kenji", "chinese"), ("Yuki", "chinese"),
    ("Wenjun", "chinese"), ("Xiulan", "chinese"), ("Nakamura", "chinese"),
    ("Dmitri", "english"), ("Svetlana", "english"),
    ("Olamide", "english"), ("Chidi", "english"), ("Nkemdirim", "english"),
    ("Ngozi", "english"), ("Adaeze", "english"), ("Kwame", "english"),
    ("Okafor", "english"),
    ("Thiago", "spanish"), ("Renata", "spanish"), ("Mateus", "spanish"),
    ("Aurelio", "italian"), ("Giuliana", "italian"), ("Federica", "italian"),
    ("Priyanka", "hindi"), ("Devika", "hindi"),
    ("Abdul", "arabic"), ("Yusuf", "arabic"),
    ("Heloise", "french"), ("Thibault", "french"), ("Beaumont", "french"),
    ("Gunther", "german"), ("Annelies", "german"), ("Nowak", "german"),
    ("Katarzyna", "polynesian"), ("Grzegorz", "polynesian"),
    ("Agnieszka", "polynesian"),
    ("Tamatoa", "polynesian"), ("Keanu", "polynesian"), ("Sefa", "polynesian"),
    ("Anaru", "polynesian"), ("Wiremu", "polynesian"),
)

# Carrier templates.  Each has a single ``{name}`` slot, and ``position``
# labels where the slot sits.  False positives are counted by position in
# :func:`_score_case`: every token other than the slot is a carrier word, so
# any placeholder on one (bar an honorific) is a false positive.
@dataclass(frozen=True)
class _Template:
    position: str
    text: str


_BASE_TEMPLATES: tuple[_Template, ...] = (
    _Template("start", "{name} arrived at the clinic before the appointment."),
    _Template("mid", "Yesterday the patient told {name} about the results."),
    _Template("title", "The referral was signed by Dr {name} this morning."),
)
# A name directly after an opening quotation mark or parenthesis, where
# the punctuation is part of the whitespace token the masker sees (audit
# findings EPRIV-10, T1-03). Only a leading mark touches the slot, so the
# possessive clitic still ends the token. Added as cells after the
# original ones: build_cases generates them last.
_PUNCTUATED_TEMPLATES: tuple[_Template, ...] = (
    _Template("quoted",
              'The patient said "{name} signed the referral" this morning.'),
    _Template("bracketed",
              "The results were sent ({name} requested them) yesterday."),
)
_TEMPLATES: tuple[_Template, ...] = _BASE_TEMPLATES + _PUNCTUATED_TEMPLATES

_CASINGS = ("title", "lower")
# The by_language label of every held-out (out-of-dictionary) case.
_HELD_OUT_LANGUAGE = "held_out"
# 'possessive' appends a clitic ("'s") to probe whether the masker redacts
# "Aaron's" as well as "Aaron" (the audit found "Bernabeu's" leaking).
_MORPHOLOGIES = ("bare", "possessive")

# Honorifics the masker recognises and rewrites to ``[TITLE]`` when they
# precede a detected name (see ``transcription.create_enhanced_name_masker``).
# A ``[TITLE]`` placeholder landing on one of these words is a by-design
# redaction of the honorific, not a privacy false positive, so it is excluded
# from the precision denominator rather than counted against the masker.
_TITLE_WORDS = frozenset({
    "mr", "mrs", "ms", "miss", "dr", "prof", "professor",
    "sir", "madam", "lord", "lady",
})


@dataclass
class _Case:
    """One scored injection case."""

    name: str
    language: str
    in_db: bool
    kind: str          # 'first' or 'surname'
    casing: str        # 'title' or 'lower'
    position: str      # 'start', 'mid', 'title'
    morphology: str    # 'bare' or 'possessive'
    template: str
    gold_token: str    # the injected token as it appears in the sentence
    sentence: str
    masked: str = ""
    hit: bool = False              # injected token redacted?
    false_positives: int = 0       # carrier tokens redacted
    replaced_total: int = 0        # placeholders in masker output
    # False for a CSV name the masker's common-word filter removes from its
    # dictionary ("Grace", "Taylor", "Will"): labelled in_db by CSV
    # membership, but not a name the masker can know. Not written to the
    # report CSV; it only moves the case into its own by_in_db cell.
    in_effective_dict: bool = True


@dataclass
class _Tally:
    """Accumulator for one breakdown cell."""

    n: int = 0
    hits: int = 0
    injected_replaced: int = 0   # == hits (injected tokens redacted)
    false_positives: int = 0
    replaced_total: int = 0

    def add(self, case: _Case) -> None:
        """Count one scored *case* into this cell."""
        self.n += 1
        if case.hit:
            self.hits += 1
            self.injected_replaced += 1
        self.false_positives += case.false_positives
        self.replaced_total += case.replaced_total

    def metrics(self) -> dict:
        """Return recall, precision, F1, leakage and the raw counts.

        An empty cell, or one with no replacements, reports 0.0 rather
        than dividing by zero.
        """
        recall = self.hits / self.n if self.n else 0.0
        precision = (
            self.injected_replaced / self.replaced_total
            if self.replaced_total else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) else 0.0
        )
        return {
            "n": self.n,
            "recall": recall,
            "precision": precision,
            "f1": f1,
            "leakage": 1.0 - recall,
            "hits": self.hits,
            "false_positives": self.false_positives,
            "replaced_total": self.replaced_total,
        }


def load_in_db_names(csv_path: Path = _DEFAULT_CSV) -> list[tuple[str, str, str]]:
    """Load ``(name, kind, language)`` triples from the curated CSV.

    Parameters
    ----------
    csv_path:
        Path to ``curated_names.csv`` (columns ``name``, ``type``,
        ``language``).

    Returns
    -------
    list of (name, kind, language)
        ``kind`` is ``'first'`` or ``'surname'`` (the CSV's ``last`` type is
        renamed to ``surname`` for readability).  Every curated name is
        kept, however short: the masker now holds the curated names under
        three characters (Li, Wu, Al, Ed and the like), which its loader
        used to discard, so the benchmark samples them too (audit finding
        T1-07). Dropping them here once kept the sample to names the
        masker could know; including them changes the sample, and so every
        cell, from the committed run's.
    """
    triples: list[tuple[str, str, str]] = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["name"].strip()
            ctype = row["type"].strip().lower()
            lang = row["language"].strip().lower()
            if not name:
                continue
            kind = "surname" if ctype == "last" else "first"
            triples.append((name, kind, lang))
    return triples


def _partition_out_of_db_names(
    csv_path: Path = _DEFAULT_CSV,
) -> list[tuple[str, str]]:
    """Return the held-out names that are genuinely absent from the CSV.

    Re-verifies :data:`OUT_OF_DB_NAMES` against the live CSV so the
    out-of-dictionary label cannot drift if the dictionary grows.  Any name
    that has since been added is silently dropped.
    """
    in_csv = {n.lower() for n, _, _ in load_in_db_names(csv_path)}
    return [(n, lang) for n, lang in OUT_OF_DB_NAMES if n.lower() not in in_csv]


def _effective_dictionary(csv_path: Path = _DEFAULT_CSV) -> set[str]:
    """Return the lower-cased names the benchmark's masker actually holds.

    The masker built by :func:`_build_masker` uses the curated CSV minus the
    common English words ``transcription.filter_problematic_names`` removes
    (among them "grace", "taylor" and "will"). Sampling the in-dictionary
    pool from the raw CSV therefore labels some names in_db that the
    masker cannot know; this set lets them be told apart.

    For the default CSV the masker's own loader is called with the
    benchmark's settings (all languages, common words excluded), so the
    set is exactly the masker's. For another CSV, as in the tests, the same
    filter is applied to that file's first names and surnames, with
    ``drop_short=False`` as the masker's loader applies it to curated names
    (audit finding T1-07). Side effect: the loader's console report is
    discarded.
    """
    from transcription import (
        create_multilingual_curated_names,
        filter_problematic_names,
    )
    if Path(csv_path).resolve() == _DEFAULT_CSV.resolve():
        with contextlib.redirect_stdout(io.StringIO()):
            first, last = create_multilingual_curated_names()
        return set(first) | set(last)
    names: set[str] = set()
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["type"].strip().lower() in ("first", "last"):
                names.add(row["name"].strip().lower())
    with contextlib.redirect_stdout(io.StringIO()):
        return set(filter_problematic_names(names, drop_short=False))


def _build_masker(case_insensitive: bool = False,
                  use_ner: bool = False) -> Callable[[str], str]:
    """Return the masking function of :func:`_build_masker_and_detector`."""
    return _build_masker_and_detector(case_insensitive, use_ner)[0]


def _build_masker_and_detector(case_insensitive: bool = False,
                               use_ner: bool = False):
    """Construct the enhanced name masker, silencing its console output.

    Returns ``(mask_func, detector)``, where *detector* is the NER stage's
    :class:`ner_masking.PersonNameDetector`, or ``None`` without *use_ner*,
    so the caller can check that the stage actually ran.

    ``create_enhanced_name_masker`` prints a verbose database-loading
    report to stdout.  The benchmark builds the masker once and redirects
    that chatter to a throwaway buffer so the CLI output stays clean.

    Parameters
    ----------
    case_insensitive:
        Passed through to the masker.  When ``True`` the masker drops its
        capitalisation requirement, which the benchmark uses to quantify the
        recall/precision trade-off of that heuristic.
    use_ner:
        Attach the optional zero-shot NER stage.  This is the arm that
        measures whether recognising people by context recovers the recall
        the closed dictionary cannot reach, and what it costs in precision.

    Raises
    ------
    SystemExit
        If *use_ner* is set but no detector can be loaded.  Silently
        measuring the dictionary alone and labelling the result as the NER
        arm would be worse than refusing to run.
    """
    from transcription import create_enhanced_name_masker

    detector = None
    if use_ner:
        from ner_masking import load_person_detector
        detector = load_person_detector()
        if detector is None:
            raise SystemExit(
                "--ner was requested but no NER model could be loaded; "
                "install it with `pip install gliner` and cache the model "
                "with `python -m ner_masking --download`.  Refusing to report "
                "dictionary-only numbers under the NER arm."
            )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mask_func, _get_log = create_enhanced_name_masker(
            case_insensitive=case_insensitive,
            ner_detector=detector,
        )
    return mask_func, detector


def _check_ner_ran(detector) -> None:
    """Refuse to label a run as the NER arm unless the model really ran.

    Loading the model is not enough: a model that raises on every call is
    swallowed per sentence, and the run would then measure the dictionary
    alone under the NER label.

    Raises
    ------
    SystemExit
        If any call failed, or no call was made.
    """
    if detector.n_failures:
        raise SystemExit(
            f"the NER stage failed on {detector.n_failures} of "
            f"{detector.n_calls} sentences (first: {detector.first_error}); "
            "refusing to report these numbers as the NER arm.")
    if not detector.n_calls:
        raise SystemExit("the NER stage was never called; refusing to "
                         "report these numbers as the NER arm.")


def _strip_token(tok: str) -> str:
    """Lower-case a token with surrounding punctuation removed.

    Matches the masker's own ``re.sub(r'[^\\w]', '', word.lower())`` cleaning
    so that carrier-token comparisons line up with what the masker sees.
    """
    return re.sub(r"[^\w]", "", tok.lower())


def _score_case(case: _Case, mask_func: Callable[[str], str]) -> None:
    """Run the masker on *case* and populate its hit / false-positive fields.

    The injected token is a **hit** when the masker output, aligned token by
    token with the input sentence, shows a placeholder at the injected
    position.  Carrier *content* tokens that became placeholders are counted
    as false positives.  A ``[TITLE]`` placeholder landing on a recognised
    honorific (e.g. ``Dr`` in the title template) is a by-design redaction,
    not a false positive: it is excluded from both the false-positive count
    and the precision denominator (``replaced_total``).  Token alignment is
    positional: every template substitutes a single word for the ``{name}``
    slot, so the masker (which never splits or merges words) preserves the
    token count.
    """
    masked = mask_func(case.sentence)
    case.masked = masked

    in_tokens = case.sentence.split()
    out_tokens = masked.split()

    if len(in_tokens) != len(out_tokens):
        # Defensive: should not happen for these templates, but never
        # silently mis-score.  Treat as a miss and count every placeholder as
        # a false positive so the case still contributes conservatively.
        n_placeholders = sum(
            1 for t in out_tokens if _PLACEHOLDER_RE.fullmatch(_strip_marker(t))
        )
        case.hit = False
        case.false_positives = n_placeholders
        case.replaced_total = n_placeholders
        return

    name_idx = in_tokens.index(case.gold_token)
    replaced_total = 0
    for idx, (src, dst) in enumerate(zip(in_tokens, out_tokens, strict=True)):
        if _PLACEHOLDER_RE.fullmatch(_strip_marker(dst)) is None:
            continue
        if idx == name_idx:
            case.hit = True
            replaced_total += 1
        elif _strip_token(src) in _TITLE_WORDS:
            # By-design honorific redaction; neither a hit nor a leak.
            continue
        else:
            case.false_positives += 1
            replaced_total += 1
    case.replaced_total = replaced_total


def _strip_marker(tok: str) -> str:
    """Strip what the masker keeps around a placeholder.

    The masker keeps the original word's punctuation on either side of the
    placeholder (``[NAME].``, ``"[NAME]``) and, for a possessive, the
    clitic (``[SURNAME]'s``, or ``[SURNAME]'`` from an older masker).  A
    trailing ``'s`` or ``’s`` (or a bare apostrophe) is removed first, then
    every non-word, non-bracket character, so that a bare ``[NAME]`` regex
    matches all of these forms and keeping the clitic does not change a
    hit into a miss (audit finding T1-03).
    """
    return re.sub(r"[^\w\[\]]", "", re.sub(r"['’]s?(?=\W*$)", "", tok))


def _apply_casing(name: str, casing: str) -> str:
    """Return *name* Title-cased or fully lower-cased."""
    if casing == "lower":
        return name.lower()
    return name[:1].upper() + name[1:]


def build_cases(
    seed: int,
    n_per_cell: int,
    csv_path: Path = _DEFAULT_CSV,
) -> list[_Case]:
    """Construct the full list of injection cases for one benchmark run.

    For each pool (in-dictionary, out-of-dictionary) the function samples
    ``n_per_cell`` names per language (per kind, for the in-dictionary pool;
    per sampling stratum, for the held-out pool), then crosses every sampled
    name with every template, casing and morphology.  Sampling is driven by
    a seeded :class:`random.Random` so runs are reproducible.  Cases over
    :data:`_BASE_TEMPLATES` come first, in the order they always had, and
    the cases over :data:`_PUNCTUATED_TEMPLATES` follow.  Held-out names are
    labelled with the language ``held_out`` (see :data:`OUT_OF_DB_NAMES`).

    Parameters
    ----------
    seed:
        Seed for the sampling RNG.
    n_per_cell:
        Names sampled per (language, kind) cell for the in-dictionary pool,
        and per language for the out-of-dictionary pool.
    csv_path:
        Path to the curated CSV.

    Returns
    -------
    list of :class:`_Case`
    """
    rng = random.Random(seed)
    cases: list[_Case] = []

    # In-dictionary pool: sample per (language, kind).
    in_db = load_in_db_names(csv_path)
    by_cell: dict[tuple[str, str], list[str]] = {}
    for name, kind, lang in in_db:
        by_cell.setdefault((lang, kind), []).append(name)

    selected: list[tuple[str, str, str, bool]] = []
    for (lang, kind), pool in sorted(by_cell.items()):
        picks = rng.sample(pool, min(n_per_cell, len(pool)))
        for name in picks:
            selected.append((name, kind, lang, True))

    # Out-of-dictionary pool: sample per stratum from the held-out list.
    out_db = _partition_out_of_db_names(csv_path)
    by_stratum: dict[str, list[str]] = {}
    for name, stratum in out_db:
        by_stratum.setdefault(stratum, []).append(name)
    for _stratum, pool in sorted(by_stratum.items()):
        picks = rng.sample(pool, min(n_per_cell, len(pool)))
        for name in picks:
            # Held-out names have no annotated first/surname role; label
            # 'unknown' so the kind breakdown stays honest. Their stratum
            # is not their language, so they get a label of their own.
            selected.append((name, "unknown", _HELD_OUT_LANGUAGE, False))

    # Label, without changing what is sampled (which would move every
    # committed cell), the in-CSV names the masker's filter removed.
    effective = _effective_dictionary(csv_path)

    # Cross every selected name with templates, casings and morphologies:
    # the original templates first, then the punctuated ones, so the
    # original cases keep their order.
    for templates in (_BASE_TEMPLATES, _PUNCTUATED_TEMPLATES):
        for name, kind, lang, is_in_db in selected:
            in_effective = (not is_in_db) or name.lower() in effective
            for template in templates:
                # The whitespace token holding the slot: "{name}", or
                # '"{name}' and "({name}" in the punctuated templates.
                slot = next(t for t in template.text.split() if "{name}" in t)
                for casing in _CASINGS:
                    for morphology in _MORPHOLOGIES:
                        base = _apply_casing(name, casing)
                        token = (base + "'s" if morphology == "possessive"
                                 else base)
                        cases.append(_Case(
                            name=name,
                            language=lang,
                            in_db=is_in_db,
                            kind=kind,
                            casing=casing,
                            position=template.position,
                            morphology=morphology,
                            template=template.text,
                            gold_token=slot.format(name=token),
                            sentence=template.text.format(name=token),
                            in_effective_dict=in_effective,
                        ))
    return cases


def score_cases(
    cases: list[_Case], mask_func: Callable[[str], str]
) -> None:
    """Score every case in place by running the masker."""
    for case in cases:
        _score_case(case, mask_func)


def summarise(cases: list[_Case], seed: int, n_per_cell: int) -> dict:
    """Aggregate scored *cases* into the overall and per-breakdown metrics.

    Returns a JSON-serialisable dict with an ``overall`` block and
    ``by_in_db``, ``by_casing``, ``by_morphology``, ``by_position`` and
    ``by_language`` breakdowns, plus the run's ``n``, ``seed`` and
    ``n_per_cell``. ``by_in_db`` has an ``in_csv_filtered_common_word``
    cell only when a sampled CSV name is one the masker's common-word
    filter removed (none is at the default seed), so ``in_db`` means "in
    the masker's effective dictionary".
    """
    overall = _Tally()
    by_in_db: dict[str, _Tally] = {}
    by_casing: dict[str, _Tally] = {}
    by_morphology: dict[str, _Tally] = {}
    by_position: dict[str, _Tally] = {}
    by_language: dict[str, _Tally] = {}

    def _cell(d: dict[str, _Tally], key: str) -> _Tally:
        return d.setdefault(key, _Tally())

    for case in cases:
        overall.add(case)
        if not case.in_db:
            membership = "out_of_db"
        elif case.in_effective_dict:
            membership = "in_db"
        else:
            membership = "in_csv_filtered_common_word"
        _cell(by_in_db, membership).add(case)
        _cell(by_casing, case.casing).add(case)
        _cell(by_morphology, case.morphology).add(case)
        _cell(by_position, case.position).add(case)
        _cell(by_language, case.language).add(case)

    def _dump(d: dict[str, _Tally]) -> dict:
        return {k: v.metrics() for k, v in sorted(d.items())}

    return {
        "n": overall.n,
        "seed": seed,
        "n_per_cell": n_per_cell,
        "overall": overall.metrics(),
        "by_in_db": _dump(by_in_db),
        "by_casing": _dump(by_casing),
        "by_morphology": _dump(by_morphology),
        "by_position": _dump(by_position),
        "by_language": _dump(by_language),
    }


_REPORT_FIELDS = (
    "name", "language", "in_db", "kind", "casing", "position", "morphology",
    "gold_token", "sentence", "masked", "hit",
    "false_positives", "replaced_total",
)


def write_report(cases: list[_Case], path: Path) -> None:
    """Write one CSV row per case to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_REPORT_FIELDS)
        writer.writeheader()
        for case in cases:
            row = asdict(case)
            writer.writerow({k: row[k] for k in _REPORT_FIELDS})


def write_summary(summary: dict, path: Path) -> None:
    """Write the aggregated *summary* dict to *path* as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


def _print_block(title: str, block: dict) -> None:
    """Print one breakdown of the summary as a table on stdout."""
    print(f"  {title}")
    header = f"    {'cell':<14}{'n':>5}{'recall':>9}{'prec':>8}{'f1':>8}{'leak':>8}"
    print(header)
    for cell, m in block.items():
        print(
            f"    {cell:<14}{m['n']:>5}{m['recall']:>9.3f}"
            f"{m['precision']:>8.3f}{m['f1']:>8.3f}{m['leakage']:>8.3f}"
        )


def run(
    seed: int, n_per_cell: int, output_dir: Path, case_insensitive: bool = False,
    use_ner: bool = False,
) -> dict:
    """Build, score and report the masking benchmark; return the summary.

    When *case_insensitive* is set the masker's capitalisation requirement is
    dropped (the recall/precision ablation) and the outputs are written with a
    ``_caseinsensitive`` suffix so they do not overwrite the default run.
    When *use_ner* is set the optional zero-shot NER stage is attached, which
    is the arm that measures whether recognising people by context recovers
    the recall the closed dictionary cannot reach; its outputs carry a
    ``_ner`` suffix for the same reason.

    Side effects: writes (overwriting) ``masking_report{suffix}.csv`` and
    ``masking_summary{suffix}.json`` in *output_dir* and prints the
    summary. The summary records the SHA-256 of the curated name list and
    :func:`provenance.run_metadata` (which runs ``git``), read before
    anything is written and leaving those two files out of the dirty
    check. Sampling uses a :class:`random.Random` seeded with *seed*, so no
    global RNG state is touched. The NER arm loads a model from the local
    cache.
    """
    from provenance import run_metadata, sha256_file

    suffix = "_caseinsensitive" if case_insensitive else ""
    if use_ner:
        suffix += "_ner"
    report_path = output_dir / f"masking_report{suffix}.csv"
    summary_path = output_dir / f"masking_summary{suffix}.json"
    # The git state is read once, before anything is written, leaving out
    # the two files this run rewrites, as provenance.write_sidecar does for
    # the CSV-only writers. Without the ignore list, a second regeneration
    # in place counted the first one's report and summary as uncommitted
    # code (audit finding OUTPUTS-12). Another arm's files still count.
    run_meta = run_metadata(ignore=(report_path, summary_path))

    cases = build_cases(seed, n_per_cell)
    mask_func, detector = _build_masker_and_detector(
        case_insensitive, use_ner=use_ner)
    score_cases(cases, mask_func)
    summary = summarise(cases, seed, n_per_cell)
    summary["case_insensitive"] = case_insensitive
    summary["ner_stage"] = use_ner
    # What produced the numbers: the name dictionary's digest (the masker's
    # recall is a property of it) and the code and package versions (audit
    # finding DEPS-04).
    summary["curated_names_sha256"] = sha256_file(_DEFAULT_CSV)
    summary["run_metadata"] = run_meta
    if detector is not None:
        _check_ner_ran(detector)
        from ner_masking import provenance
        # Model, revision, threshold, labels and library version, so the
        # numbers can be tied to what produced them.
        summary["ner"] = provenance(detector)

    write_report(cases, report_path)
    write_summary(summary, summary_path)

    ov = summary["overall"]
    mode = "case-insensitive" if case_insensitive else "default (capitalisation-gated)"
    if use_ner:
        mode += " + NER"
    print(f"Name-masking PII benchmark  (seed={seed}, n={ov['n']}, mode={mode})")
    print(
        f"  OVERALL  recall={ov['recall']:.3f}  precision={ov['precision']:.3f}  "
        f"f1={ov['f1']:.3f}  leakage={ov['leakage']:.3f}"
    )
    print()
    _print_block("by dictionary membership:", summary["by_in_db"])
    print()
    _print_block("by casing:", summary["by_casing"])
    print()
    _print_block("by morphology:", summary["by_morphology"])
    print()
    _print_block("by position:", summary["by_position"])
    print()
    _print_block("by language:", summary["by_language"])
    print()
    print(f"  report:   {report_path}")
    print(f"  summary:  {summary_path}")
    return summary


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.benchmark_masking",
        description=(
            "Evaluate the personal-name masking layer as a PII-detection "
            "task (precision, recall, F1, leakage) using reproducible "
            "name injection."
        ),
    )
    p.add_argument(
        "--seed", type=int, default=_DEFAULT_SEED,
        help="Seed for name sampling (default: %(default)s).",
    )
    p.add_argument(
        "--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR,
        help="Directory for report CSV and summary JSON (default: %(default)s).",
    )
    p.add_argument(
        "--n-per-cell", type=int, default=_DEFAULT_N_PER_CELL,
        help=(
            "Names sampled per (language, kind) cell for the in-dictionary "
            "pool, and per language for the held-out pool "
            "(default: %(default)s)."
        ),
    )
    p.add_argument(
        "--case-insensitive", action="store_true", dest="case_insensitive",
        help=(
            "Build the masker with case_insensitive=True (drops the "
            "capitalisation requirement) to measure the recall/precision "
            "trade-off; writes *_caseinsensitive outputs."
        ),
    )
    p.add_argument(
        "--ner", action="store_true", dest="use_ner",
        help=(
            "Attach the optional zero-shot NER stage, which recognises "
            "people by context rather than by dictionary membership.  "
            "Measures whether it recovers the recall the closed dictionary "
            "cannot reach, and what that costs in precision; writes *_ner "
            "outputs.  Requires `pip install gliner`."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and call :func:`run`."""
    args = _build_parser().parse_args(argv)
    run(
        seed=args.seed,
        n_per_cell=args.n_per_cell,
        output_dir=args.output_dir,
        case_insensitive=args.case_insensitive,
        use_ner=args.use_ner,
    )


if __name__ == "__main__":
    main()
