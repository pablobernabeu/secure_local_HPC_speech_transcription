#!/usr/bin/env python3
"""
Registry of post-processing conditions for the WER benchmark.

A *condition* is a named transformation that is applied to the ASR
hypothesis text before it is scored against the reference.  Conditions
are designed to disentangle the contribution of different layers of
post-processing (repetition-loop repair, canonical text normalisation,
and so on) to the overall word error rate.

Each condition declares whether the same transformation must also be
applied to the reference text.  This is required for canonical
normalisers such as the Whisper English normaliser, where the
normaliser changes both transcripts in a way that would systematically
bias the score if applied to only one side (for example, expanding
``isn't`` to ``is not`` in the hypothesis but not in the reference
would manufacture insertions).

Most conditions are atomic: each applies a single well-defined
transformation.  The one composite, ``pipeline_full``, applies the
production pipeline's stages in production order.  A benchmark run
scores any number of conditions on one decode (see
``evaluation.benchmark_wer --conditions``).

Seventeen conditions are registered: the baseline ``raw``; one per stage
of the production post-processing chain (``unicode_strip``,
``repetition_fix``, and the eight stages of
``transcription.clean_transcription_text``: ``undefined_tag``,
``filler_bracket``, ``contraction_fix``, ``common_phrase_fix``,
``whitespace_normalise``, ``sentence_capitalise``, ``pronoun_i_fix`` and
``punct_space_fix``); the composite ``pipeline_full``; and five
diagnostic conditions that the production pipeline does not apply
(``whisper_norm``, ``filler_strip``, ``dedup_window``, ``punct_strip``,
``case_fold``).  Their registrations below carry their descriptions.
:func:`default_sweep_conditions` is the list a sweep scores by default.
The seven policy conditions the manuscript compares are:

``raw``
    Identity transformation.  Establishes the unmodified baseline.

``repetition_fix``
    Applies ``transcription.detect_and_fix_repetitions``, which
    truncates Whisper's pathological repetition loops without touching
    any other content.  On whisper-medium against LibriSpeech
    test-clean it cut insertions from 1,092 to 349 (see the
    registration's notes).  Off by default in ``transcription.py``,
    which applies it only with ``--fix-spurious-repetitions``.

``whisper_norm``
    Applies the published Whisper English text normaliser, with its
    British-to-American spelling map, to both sides.  Expands
    contractions, normalises numerals and currency, collapses
    punctuation, lowercases, removes some hesitations and maps British
    spellings to American ones.  See :func:`load_whisper_spelling_map`.

``filler_strip``
    Removes the unambiguous non-lexical disfluency vocabulary
    (``um``, ``uh``, ``er``, ``ah``, ``mm``, ``hmm`` and their
    length variants) from the hypothesis only.  Aligns spontaneous-
    speech hypotheses with read-speech references whose transcripts
    do not record such tokens by convention.

``dedup_window``
    Collapses immediately-adjacent duplicate tokens in the
    hypothesis (``the the cat`` becomes ``the cat``).  Targets
    short stutter-like repetitions that survive ``repetition_fix``,
    which is tuned for longer n-gram repetition loops.  It also
    collapses adjacent grammatical reduplication (``had had``,
    ``that that``).

``punct_strip``
    Removes sentence punctuation symmetrically from both the
    hypothesis and the reference, replacing each punctuation
    character with a space and collapsing the resulting runs of
    whitespace.  Intra-word apostrophes are preserved so that
    contractions are not split into spurious tokens.  Applied
    symmetrically because reference transcripts vary in their
    punctuation conventions and an asymmetric strip would
    manufacture insertions or deletions.

``case_fold``
    Lowercases both the hypothesis and the reference.  Because the
    scoring normaliser lowercases both sides anyway, it scores exactly
    as ``raw`` (see below).

What normalised WER can and cannot see
--------------------------------------
Every condition is scored after :func:`evaluation.wer.normalise_text`,
which lowercases both sides and replaces every character other than a
letter, digit, underscore, whitespace or apostrophe with a space.  A
condition that changes only case, punctuation, spacing or square brackets
therefore scores exactly as ``raw``, whatever it does to the transcript.
Seven conditions are of this kind by construction and are registered with
``wer_invisible=True``: ``case_fold``, ``common_phrase_fix``,
``sentence_capitalise``, ``pronoun_i_fix``, ``whitespace_normalise``,
``punct_space_fix`` and ``filler_bracket``.  Their word error rate equals
the baseline's on every corpus, so a null difference for one of them is
guaranteed by the method and says nothing about whether the stage helps
or harms a reader.  Each benchmark summary records the flag
(``benchmark.wer_invisible``) and the sweep aggregate carries it as a
column, so tables and figures can label these conditions as unmeasurable
under normalised WER.

Three conditions come close without qualifying.  ``punct_strip`` runs
before the normaliser, so it can score differently from ``raw`` only on
a character that the normaliser would have rewritten or removed before
its own punctuation strip, because ``punct_strip`` has already made it
a space.  The normaliser maps the curly single quotation marks (U+2018
and U+2019, the second also the typographic apostrophe) to the
apostrophe it keeps, so ``don’t`` becomes ``don t`` under
``punct_strip`` but ``don't`` under ``raw``.  NFKC folds some
characters into ones the normaliser keeps (``™`` into ``TM``) and joins
a combining accent to its letter, and the normaliser removes a speaker
tag such as ``SPEAKER-01`` whole, where ``punct_strip`` leaves
``SPEAKER 01``.  In the committed post-fix grid only the curly marks
move a cell: each FLEURS cell scores two errors fewer, because one
reference sentence, read twice, writes ``Hira‘”``, which ``raw`` scores
as ``hira'`` against the ``Hira`` that all three models write.
``undefined_tag`` rewrites ``undefine``, ``undefin`` and ``undefining``
to ``undefined``, which changes a scored token.  ``unicode_strip``
deletes a symbol where the normaliser would put a space, so a symbol
between two letters joins two scored tokens into one.  None of them is
flagged.

``filler_bracket`` is flagged because the production stage brackets whole
tokens only: a hyphenated backchannel whole (``[uh-huh]``), and nothing
inside a hyphenated compound or next to an apostrophe.  The committed
post-fix grid predates that guard, and its ``filler_bracket`` cells differ
from ``raw`` in 3 of 15 cells, all through words such as ``o'er``, which
the stage then bracketed as ``o'[er]``, two scored tokens.  The case
conditions are invisible for every letter whose capital lower-cases back
to it, which is all but a handful (``ß`` title-cases to ``Ss``); none of
those opens a sentence in the corpora scored.

Filler inventories
------------------
Five lists of non-lexical fillers are in play.  They differ, and they are
deliberately not unified here: bringing ``filler_strip`` or the
production list into line with another would move committed word error
rates, which is a decision for the maintainer (audit findings EWER-15
and XREF-08).

=================================  =======================================  ======================
Inventory                          Tokens (all matched case-insensitively)  Used by
=================================  =======================================  ======================
``transcription.FILLER_TOKENS``    um uh er ah hmm mm mhm uhuh uhhuh; and   ``filler_bracket``,
                                   ``BACKCHANNEL_TOKENS`` uh-huh mm-hmm     ``pipeline_full``
                                   uh-uh mm-mm, bracketed whole
``conditions._FILLER_RE``          um uh uhm umm erm er ah mm mhm hmm hm,   ``filler_strip``
                                   each also lengthened (ummm, uhhh)
``disfluency._FILLER_STEM``        the union of the two rows above, with    filler retention and
                                   lengthened spellings, hyphenated and     reference recall
                                   unhyphenated backchannels (mm-hmm,       (``evaluation.
                                   mmhmm, uh-huh) and ``huh`` only as the   disfluency``)
                                   second element of a compound
``wer._FILLER_WORDS``              uh um erm ah eh mm hmm                   ``python -m evaluation.
                                                                            wer --remove-fillers``
Whisper ``EnglishTextNormalizer``  hmm mm mhm mmm uh um (its                ``whisper_norm``, both
                                   ``ignore_patterns``)                     sides
=================================  =======================================  ======================

Why each differs:

* The production list is narrow on purpose: every entry is a hesitation
  with no lexical reading in English, so bracketing one can never swallow
  a real word (``oh`` and ``well`` are excluded for that reason).  It
  matches exact tokens, so lengthened spellings such as ``ummm`` are not
  bracketed, and a filler inside a hyphenated compound or next to an
  apostrophe is not a standalone filler.
* ``filler_strip`` removes the lengthened spellings and ``erm``, ``uhm``
  and ``hm``, which the production list lacks, and leaves ``uhuh``,
  ``uhhuh`` and every hyphenated compound alone.  Why its coverage was
  chosen to differ from the production list is not recorded.  The
  consequence is that ``filler_strip`` and ``filler_bracket`` act on
  different vocabularies, in both directions, so they are not exact
  counterparts.
* The disfluency detector must see everything either condition might
  remove; a narrower detector would shrink its own denominator, and a
  condition that deleted every ``erm`` would score as having preserved
  the fillers.  Broader is the safe direction.
* ``wer._FILLER_WORDS`` serves only the ``--remove-fillers`` flag of the
  standalone scorer; no committed result uses it.
* The Whisper list is part of the published normaliser and is not ours to
  change.  It is why ``whisper_norm`` empties filler-only references (such
  AMI utterances are then skipped, see ``benchmark.n_skipped_empty_reference``)
  while keeping ``er``, ``ah`` and ``erm``.

The registry deliberately mirrors the structure of
``evaluation/challenge_suites.py``: callers obtain conditions by name
through :func:`get_condition` and enumerate them through
:func:`list_conditions`.  No condition has side effects beyond the
returned string, apart from ``whisper_norm`` reading and caching its
spelling map on first use.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path


@dataclass(frozen=True)
class Condition:
    """A named text transformation applied to ASR hypotheses (and optionally references).

    Attributes
    ----------
    name:
        URL-safe slug used as the ``--conditions`` CLI value and as a
        component of output file names.  Must match
        ``^[a-z][a-z0-9_]*$``.
    description:
        One-sentence plain-prose summary of what the condition does
        (British English, no bullet points).
    transform:
        Pure function ``str -> str``.  Must not have side effects and
        must accept the empty string.
    apply_to_reference:
        Whether the same transformation is also applied to the
        reference text before scoring.  ``True`` for canonical
        normalisers that must be applied symmetrically; ``False`` for
        hypothesis-only fixes such as repetition repair.
    language_aware:
        Whether ``transform`` accepts a second positional ``language``
        argument.  The benchmark passes its ``--language`` through to
        such conditions so that the production composite can gate its
        English-only stages; ordinary conditions ignore language and
        keep the plain ``str -> str`` signature.
    wer_invisible:
        ``True`` when the scoring normaliser
        (:func:`evaluation.wer.normalise_text` with its defaults) maps
        the condition's output to the same tokens as its input for any
        text, so the condition's word error rate equals the baseline's
        by construction.  Such a condition changes only case,
        punctuation, spacing or square brackets.  Reports carry the flag
        so that a null result can be labelled as unmeasurable rather than
        read as evidence of no effect (see the module docstring).  The
        baseline ``raw`` itself is not flagged.
    notes:
        Optional free-text caveats or implementation notes.
    """

    name:               str
    description:        str
    transform:          Callable[..., str]
    apply_to_reference: bool = False
    language_aware:     bool = False
    wer_invisible:      bool = False
    notes:              str  = ""


_CONDITIONS: dict[str, Condition] = {}

# Slug validation pattern, enforced by _register (also used by tests).
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _register(condition: Condition) -> Condition:
    """Add *condition* to the global registry and return it.

    Raises
    ------
    ValueError
        If the name is already registered or is not a valid slug (names
        become CLI values and file-name suffixes).
    """
    if not _SLUG_RE.match(condition.name):
        raise ValueError(
            f"Condition name {condition.name!r} does not match "
            f"{_SLUG_RE.pattern}."
        )
    if condition.name in _CONDITIONS:
        raise ValueError(
            f"Condition {condition.name!r} is already registered."
        )
    _CONDITIONS[condition.name] = condition
    return condition


# ---------------------------------------------------------------------------
# Transform implementations
# ---------------------------------------------------------------------------
def _identity(text: str) -> str:
    """Return *text* unchanged."""
    return text


def _repetition_fix(text: str) -> str:
    """Truncate pathological repetition loops produced by Whisper-family models.

    Delegates to ``transcription.detect_and_fix_repetitions``, which is
    the function already used by the local desktop pipeline.  Imported
    lazily so that the registry module itself remains importable in
    environments that lack the full transcription dependency set.
    """
    from transcription import detect_and_fix_repetitions
    return detect_and_fix_repetitions(text)


# ---------------------------------------------------------------------------
# Atomic production-pipeline stages
# ---------------------------------------------------------------------------
# The wrappers below expose each atomic stage of the desktop
# post-processing pipeline as an individually-named condition.  They
# delegate to functions defined in ``transcription`` so that the
# benchmark and the production pipeline cannot drift out of sync.

def _unicode_strip(text: str) -> str:
    """Remove emoji and symbol or control characters from *text*.

    Letters, combining marks and digits are kept whatever their script,
    typographic quotation marks become ASCII ones, and punctuation and
    currency signs are kept (see
    ``transcription.remove_emojis_and_unicode_artifacts``).
    """
    from transcription import remove_emojis_and_unicode_artifacts
    return remove_emojis_and_unicode_artifacts(text)


def _undefined_tag(text: str) -> str:
    """Mark ``undefin*`` speech artefacts as ``[undefined]``."""
    from transcription import _undefined_tag as _impl
    return _impl(text)


def _filler_bracket(text: str) -> str:
    """Wrap unambiguous non-lexical fillers in square brackets."""
    from transcription import _filler_bracket as _impl
    return _impl(text)


def _contraction_fix(text: str) -> str:
    """Repair common contractions and Whisper space-split artefacts."""
    from transcription import _contraction_fix as _impl
    return _impl(text)


def _common_phrase_fix(text: str) -> str:
    """Normalise capitalisation in a fixed set of lexical hedges."""
    from transcription import _common_phrase_fix as _impl
    return _impl(text)


def _whitespace_normalise(text: str) -> str:
    """Collapse runs of whitespace and tidy spacing around commas and stops."""
    from transcription import _whitespace_normalise as _impl
    return _impl(text)


def _sentence_capitalise(text: str) -> str:
    """Capitalise sentence-initial words (the pronoun is ``_pronoun_i_fix``)."""
    from transcription import _sentence_capitalise as _impl
    return _impl(text)


def _pronoun_i_fix(text: str) -> str:
    """Capitalise the standalone English first-person pronoun ``i``."""
    from transcription import _pronoun_i_fix as _impl
    return _impl(text)


def _punct_space_fix(text: str) -> str:
    """Normalise spacing around punctuation, quotes and parentheses."""
    from transcription import _punct_space_fix as _impl
    return _impl(text)


def _pipeline_full(text: str, language: str = "english") -> str:
    """Apply the production post-processing chain with repetition repair on.

    Delegates to ``transcription.postprocess_transcript_text`` with
    ``fix_repetitions=True``, the function ``transcription.py`` itself
    runs on every transcript, so the benchmark cannot drift from it.  The
    chain is the Unicode strip, repetition repair and the clean-text
    stages.  Repetition repair is what ``--fix-spurious-repetitions``
    switches on; a default run of ``transcription.py`` or the desktop app
    omits it, so this composite is the opt-in configuration, not the
    default one (audit finding EWER-04).  No masker is applied.
    *language* is forwarded so that the English-only stages are skipped
    on other languages; it defaults to English.
    """
    from transcription import postprocess_transcript_text
    return postprocess_transcript_text(text, language, fix_repetitions=True)[0]


# ---------------------------------------------------------------------------
# whisper_norm: the published Whisper English normaliser
# ---------------------------------------------------------------------------
# The Whisper normaliser standardises British spellings to American ones
# through a spelling map, applied to both sides so that "colour" and
# "color" score as the same word. The condition used to construct the
# normaliser with an empty map, which standardises nothing, under a
# docstring that claimed the opposite; the committed whisper_norm cells
# were therefore stricter than the published normaliser (audit finding
# EWER-05). The map is now loaded explicitly and never defaults to empty.
#
# Source: openai-whisper's whisper/normalizers/english.json, the file its
# own EnglishSpellingNormalizer loads. The ARC job environment pins
# openai-whisper==20250625 (requirements-lock.txt), whose file has the
# SHA-256 below (1,739 entries, read on ARC on 2026-09-26). The
# normalizer.json shipped in the Whisper model repositories on the Hub is
# the same map plus one entry ("mm" -> "hmm"), so it is not used.
_WHISPER_SPELLING_MAP_SHA256 = (
    "6607f948be9824d2e1b2fa2223cd94c06c45afa4e05ea0e3d5e1f2bdffde2465")

_WHISPER_NORM_SINGLETON: Callable[[str], str] | None = None
_WHISPER_NORM_PROVENANCE: dict | None = None


class SpellingMapError(ImportError):
    """The published spelling map is missing, altered or malformed.

    A subclass of :class:`ImportError` so that the WER benchmark treats it
    as a fault of the environment, which stops the run before the model
    loads, and never as a per-utterance data error to be skipped.
    """


def whisper_spelling_map_path() -> Path:
    """Return the path of openai-whisper's ``normalizers/english.json``.

    The package is located with :func:`importlib.util.find_spec`, which does
    not execute its ``__init__`` (that would import torch and the Whisper
    model code, none of which the map needs).

    Raises
    ------
    SpellingMapError
        If openai-whisper is not installed or does not hold the file.
        whisper_norm refuses to run without the map rather than fall back
        to an empty one.
    """
    spec = importlib.util.find_spec("whisper")
    locations = list(spec.submodule_search_locations or []) if spec else []
    for location in locations:
        candidate = Path(location) / "normalizers" / "english.json"
        if candidate.is_file():
            return candidate
    raise SpellingMapError(
        "whisper_norm needs the published Whisper English spelling map, "
        "whisper/normalizers/english.json from openai-whisper (the ARC job "
        "environment pins openai-whisper==20250625). Install it with "
        "`pip install openai-whisper==20250625`; the condition does not run "
        "with an empty map."
    )


def load_whisper_spelling_map(
    path: Path | str | None = None,
    expected_sha256: str | None = _WHISPER_SPELLING_MAP_SHA256,
) -> dict[str, str]:
    """Load and check the British-to-American spelling map.

    Parameters
    ----------
    path:
        The JSON file to read.  ``None`` reads openai-whisper's own copy
        (:func:`whisper_spelling_map_path`).
    expected_sha256:
        The digest the file must have.  Defaults to that of openai-whisper
        20250625's file, so a different map cannot slip in unnoticed;
        ``None`` skips the check (tests use this with a small fixture).

    Returns
    -------
    dict
        The map, ``{british: american}``.

    Raises
    ------
    SpellingMapError
        If ``path`` is ``None`` and openai-whisper is not installed, if the
        digest differs, or if the file is not a non-empty JSON object of
        strings to strings.
    """
    source = Path(path) if path is not None else whisper_spelling_map_path()
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise SpellingMapError(
            f"{source} has SHA-256 {digest}, not the {expected_sha256} of "
            "openai-whisper 20250625's spelling map; whisper_norm refuses to "
            "score with a different map."
        )
    try:
        mapping = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpellingMapError(f"{source} is not valid JSON: {exc}") from exc
    if (not isinstance(mapping, dict) or not mapping
            or not all(isinstance(k, str) and isinstance(v, str)
                       for k, v in mapping.items())):
        raise SpellingMapError(
            f"{source} is not a non-empty map of strings to strings")
    return mapping


def _whisper_norm(text: str) -> str:
    """Apply the published Whisper English text normaliser.

    Built on first use and cached at module scope: transformers'
    ``EnglishTextNormalizer`` (the port of openai-whisper's class, which
    differs from it only in taking the spelling map as an argument)
    constructed with openai-whisper's spelling map.  It expands
    contractions, normalises numerals and currency, removes the
    hesitations ``hmm``, ``mm``, ``mhm``, ``mmm``, ``uh`` and ``um``,
    removes bracketed and parenthesised text, collapses punctuation,
    lowercases and maps British spellings to American ones.

    Raises
    ------
    ImportError
        If transformers is missing, or (as :class:`SpellingMapError`) if
        openai-whisper's spelling map is missing or not the pinned one.
    """
    global _WHISPER_NORM_SINGLETON, _WHISPER_NORM_PROVENANCE
    if _WHISPER_NORM_SINGLETON is None:
        from importlib import metadata

        from transformers.models.whisper.english_normalizer import (
            EnglishTextNormalizer,
        )
        source = whisper_spelling_map_path()
        # The pin is read from the module at call time, not bound as a
        # default argument, so a test can substitute a small fixture map.
        mapping = load_whisper_spelling_map(
            source, expected_sha256=_WHISPER_SPELLING_MAP_SHA256)
        _WHISPER_NORM_SINGLETON = EnglishTextNormalizer(mapping)

        def _version(package):
            try:
                return metadata.version(package)
            except metadata.PackageNotFoundError:
                return None

        _WHISPER_NORM_PROVENANCE = {
            "implementation": ("transformers.models.whisper.english_normalizer."
                               "EnglishTextNormalizer"),
            "transformers": _version("transformers"),
            "spelling_map": "openai-whisper whisper/normalizers/english.json",
            "openai_whisper": _version("openai-whisper"),
            "spelling_map_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "spelling_map_entries": len(mapping),
        }
    return _WHISPER_NORM_SINGLETON(text)


# The filler-strip regex matches standalone non-lexical disfluency tokens
# (the unfilled and filled pauses commonly produced by spontaneous speech
# and occasionally hallucinated by Whisper-family models on noisy audio).
# It deliberately excludes lexical hedges such as "like" and "you know"
# whose removal would change semantic content.  The lookbehind and
# lookahead both exclude word characters and hyphens, so backchannel
# constructions such as "uh-huh" and "mm-hmm" are left untouched.  The
# trailing punctuation and single-space group absorbs the comma and
# space that typically follow a filler in punctuated transcripts, so
# that the surrounding sentence is left grammatically clean.
_FILLER_RE = re.compile(
    r"(?<![\w-])"
    r"(?:um+|uh+|uhm+|umm+|erm+|er+|ah+|mm+|mhm+|hmm+|hm+)"
    r"(?![\w-])"
    r"[,;:.!?]*\s?",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s{2,}")


def _filler_strip(text: str) -> str:
    """Remove standalone non-lexical filler tokens from *text*.

    The condition targets the unambiguous disfluency vocabulary
    (``um``, ``uh``, ``er``, ``ah``, ``mm``, ``hmm`` and their length
    variants) and is hypothesis-only by design: LibriSpeech and the
    other read-speech benchmarks do not transcribe these tokens in their
    references, so removing them from the hypothesis aligns the two
    sides without altering reference content.  The function is
    idempotent because a second application has no fillers left to
    strip and the whitespace collapse is a no-op on already-clean text.
    """
    out = _FILLER_RE.sub("", text)
    out = _WHITESPACE_RE.sub(" ", out).strip()
    return out


# The dedup-window comparison strips all non-word characters so that
# ``the,`` and ``the`` and ``THE`` are recognised as the same token for
# the purpose of the adjacency check, while the original surface form
# of the first occurrence is preserved in the output.  An empty
# normalised form (a token that is pure punctuation) is treated as
# never matching, so a stray comma between two real words never causes
# either of them to be dropped.
_DEDUP_NORM_RE = re.compile(r"[^\w]+")


def _dedup_window(text: str) -> str:
    """Collapse immediately-adjacent duplicate tokens in *text*.

    The window is deliberately fixed at one token: a duplicate is
    removed only when it sits directly next to its predecessor under
    case-insensitive, punctuation-insensitive comparison.  Wider
    windows (two or three tokens) would catch additional cases such
    as ``I uh I went`` collapsing to ``I uh went``, flattening
    self-corrections that have a word between the repeats.  The
    one-token window leaves those intact while still removing the
    textbook stutter pattern ``the the cat``.

    It does not spare adjacent grammatical reduplication: ``I said
    that that was wrong`` becomes ``I said that was wrong`` and ``had
    had enough`` becomes ``had enough``.  Where a reference records
    such a pair, the condition is charged a deletion, which is part of
    its measured cost.

    The function is idempotent because a single pass already removes
    every adjacent duplicate and a second pass therefore has nothing
    to collapse.
    """
    tokens = text.split()
    if not tokens:
        return text
    kept = [tokens[0]]
    prev_norm = _DEDUP_NORM_RE.sub("", tokens[0]).lower()
    for tok in tokens[1:]:
        cur_norm = _DEDUP_NORM_RE.sub("", tok).lower()
        if cur_norm and cur_norm == prev_norm:
            # Skip the duplicate; the previous token's normalised form
            # is preserved so that runs of three or more (``the the the``)
            # collapse to a single retained token.
            continue
        kept.append(tok)
        prev_norm = cur_norm
    return " ".join(kept)


# The punctuation-strip regex matches any character that is neither a
# word character (letter, digit or underscore), nor whitespace, nor an
# apostrophe.  Apostrophes are preserved so that contractions such as
# ``don't`` and ``isn't`` remain single tokens rather than being split
# into spurious bigrams.  Each matched punctuation character is
# replaced with a single space and the resulting runs of whitespace
# are then collapsed by the shared ``_WHITESPACE_RE``.
_PUNCT_RE = re.compile(r"[^\w\s']")


def _punct_strip(text: str) -> str:
    """Remove sentence punctuation from *text*, symmetrically.

    The transformation replaces each non-word, non-space,
    non-apostrophe character with a space and then collapses the
    resulting whitespace.  It is applied to both the hypothesis and
    the reference because reference transcripts differ in their
    punctuation conventions (some include sentence-final periods,
    others do not; quotation marks are used inconsistently) and an
    asymmetric strip would manufacture insertions or deletions on
    every punctuation token.  Intra-word apostrophes are preserved
    so that ``don't`` is not split into ``don`` and ``t``.  The
    function is idempotent because a second application has no
    punctuation left to remove.
    """
    out = _PUNCT_RE.sub(" ", text)
    out = _WHITESPACE_RE.sub(" ", out).strip()
    return out


def _case_fold(text: str) -> str:
    """Lowercase *text* using the standard Python ``str.lower``.

    The transformation is applied symmetrically to both the hypothesis
    and the reference so that a model emitting capitalised tokens is
    not penalised against a reference that does not capitalise them,
    nor vice versa.  ``str.lower`` is used rather than ``str.casefold``
    because the latter performs additional Unicode mappings (such as
    German ``ß`` -> ``ss``) that go beyond the scope of pure case
    folding and would overlap with the territory of ``whisper_norm``.
    The function is trivially idempotent.
    """
    return text.lower()


# ---------------------------------------------------------------------------
# Condition 1: raw (identity baseline)
# ---------------------------------------------------------------------------
_register(Condition(
    name="raw",
    description=(
        "Identity transformation: the hypothesis is scored exactly as "
        "produced by the ASR pipeline.  Establishes the unmodified "
        "baseline against which post-processing conditions are compared."
    ),
    transform=_identity,
    apply_to_reference=False,
    notes="No-op; always present in the registry as the canonical baseline.",
))

# ---------------------------------------------------------------------------
# Condition 2: repetition_fix (hypothesis-only repair of Whisper loops)
# ---------------------------------------------------------------------------
_register(Condition(
    name="repetition_fix",
    description=(
        "Truncates the pathological n-gram repetition loops that "
        "Whisper-family models occasionally emit on long or degraded "
        "audio, using transcription.detect_and_fix_repetitions."
    ),
    transform=_repetition_fix,
    apply_to_reference=False,
    notes=(
        "Hypothesis-only: the reference is not expected to contain such "
        "loops and applying the function to it would be a no-op in all "
        "tested cases.  On whisper-medium against LibriSpeech test-clean "
        "this condition reduces insertions from 1,092 to 349 (the May run "
        "before the condition registry: total_insertions in "
        "output/evaluation/pilot_may2026/"
        "wer_summary_librispeech_whisper-medium_raw.json "
        "and ..._postprocessed.json).  transcription.py applies it only "
        "with --fix-spurious-repetitions, which is off by default."
    ),
))

# ---------------------------------------------------------------------------
# Condition 3: whisper_norm (canonical symmetric normaliser)
# ---------------------------------------------------------------------------
_register(Condition(
    name="whisper_norm",
    description=(
        "Applies the published Whisper English text normaliser, with its "
        "British-to-American spelling map, to both the hypothesis and the "
        "reference: expands contractions, normalises numerals and "
        "currency, removes some hesitations and bracketed text, collapses "
        "punctuation, lowercases and maps British spellings to American "
        "ones, so that colour and color score as the same word."
    ),
    transform=_whisper_norm,
    apply_to_reference=True,
    notes=(
        "transformers.models.whisper.english_normalizer.EnglishTextNormalizer "
        "constructed with openai-whisper's whisper/normalizers/english.json "
        "(openai-whisper 20250625, SHA-256 pinned in "
        "_WHISPER_SPELLING_MAP_SHA256); fails rather than run with an empty "
        "map.  Results scored before this fix used an empty map, which "
        "standardised no spelling and so were stricter than the published "
        "normaliser.  The normaliser removes um, uh, hmm, mm, mhm and mmm, "
        "so a filler-only reference normalises to nothing and that "
        "utterance is skipped under this condition only "
        "(benchmark.n_skipped_empty_reference); compare with raw on the "
        "shared utterances (evaluation.condition_ci.normaliser_gain)."
    ),
))


# ---------------------------------------------------------------------------
# Condition 4: filler_strip (hypothesis-only disfluency removal)
# ---------------------------------------------------------------------------
_register(Condition(
    name="filler_strip",
    description=(
        "Removes the unambiguous non-lexical filler tokens "
        "(um, uh, er, erm, ah, mm, mhm, hmm and their length variants) "
        "from the hypothesis only, leaving lexical hedges and "
        "backchannels intact.  Aligns spontaneous-speech hypotheses "
        "with read-speech references whose transcripts omit such "
        "tokens by convention."
    ),
    transform=_filler_strip,
    apply_to_reference=False,
    notes=(
        "Word-boundary anchors that also exclude hyphens prevent the "
        "regex from matching inside compound backchannels such as "
        "uh-huh or mm-hmm.  Lexical hedges (like, you know, sort of) "
        "are deliberately not in scope because their removal changes "
        "semantic content and would bias the comparison against "
        "models that correctly transcribe them."
    ),
))


# ---------------------------------------------------------------------------
# Condition 5: dedup_window (hypothesis-only adjacent-duplicate collapse)
# ---------------------------------------------------------------------------
_register(Condition(
    name="dedup_window",
    description=(
        "Collapses immediately-adjacent duplicate tokens in the "
        "hypothesis under case-insensitive, punctuation-insensitive "
        "comparison.  Targets short stutter-like repetitions "
        "(``the the cat``) that survive repetition_fix, which is "
        "tuned for longer n-gram repetition loops."
    ),
    transform=_dedup_window,
    apply_to_reference=False,
    notes=(
        "Window is fixed at one token: a duplicate is removed only "
        "when it sits directly next to its predecessor.  Wider windows "
        "would catch ``I uh I went`` at the cost of flattening "
        "self-corrections with a word between the repeats.  Adjacent "
        "grammatical reduplication is collapsed too (``I said that that "
        "was wrong`` loses one ``that``), which costs a deletion "
        "wherever the reference records it.  Hypothesis-only because "
        "reference transcripts of read speech rarely contain adjacent "
        "duplicates."
    ),
))


# ---------------------------------------------------------------------------
# Condition 6: punct_strip (symmetric sentence-punctuation removal)
# ---------------------------------------------------------------------------
_register(Condition(
    name="punct_strip",
    description=(
        "Removes sentence punctuation symmetrically from the hypothesis "
        "and the reference, replacing each non-word, non-space, "
        "non-apostrophe character with a space and collapsing the "
        "resulting whitespace.  Intra-word apostrophes are preserved so "
        "that contractions are not split into spurious tokens."
    ),
    transform=_punct_strip,
    apply_to_reference=True,
    notes=(
        "Applied symmetrically because reference transcripts vary in "
        "their punctuation conventions; an asymmetric strip would "
        "manufacture insertions or deletions on every punctuation "
        "token.  The scoring normaliser strips the same character class "
        "from both sides of every condition, so against raw this "
        "condition can differ only where its strip runs first, on a "
        "character the normaliser would have rewritten or removed "
        "before stripping: it turns a curly single quotation mark "
        "(U+2018 or U+2019, the second also the typographic apostrophe) "
        "into a space, whereas the normaliser maps it to an ASCII "
        "apostrophe, so don’t scores as don t here and as don't under "
        "raw.  It does the same to a character that NFKC folds into "
        "ones the normaliser keeps (™ into TM), to a combining accent "
        "that NFKC joins to its letter, and to the hyphen of a speaker "
        "tag such as SPEAKER-01, which the normaliser removes whole.  "
        "Any difference from raw measures that, not the removal of "
        "sentence punctuation."
    ),
))


# ---------------------------------------------------------------------------
# Condition 7: case_fold (symmetric lowercasing)
# ---------------------------------------------------------------------------
_register(Condition(
    name="case_fold",
    description=(
        "Lowercases both the hypothesis and the reference using "
        "str.lower.  The scoring normaliser already lowercases both sides "
        "of every condition, so this condition scores exactly as raw by "
        "construction: it cannot isolate any contribution of case "
        "folding to word error rate."
    ),
    transform=_case_fold,
    apply_to_reference=True,
    wer_invisible=True,
    notes=(
        "Uses str.lower rather than str.casefold so that additional "
        "Unicode mappings (such as German eszett to ss) do not creep "
        "in; those mappings overlap with the territory of the Whisper "
        "canonical normaliser and would muddy the contrast between "
        "this condition and whisper_norm.  Trivially idempotent."
    ),
))


# ---------------------------------------------------------------------------
# Conditions 8-17: atomic production-pipeline stages and the composite
# ---------------------------------------------------------------------------
# Each of the following conditions except ``pipeline_full`` corresponds to
# a single atomic stage of the desktop transcription pipeline.  They are
# registered so that the WER benchmark can measure the contribution of
# each stage in isolation, in addition to the composite ``pipeline_full``.
# All nine stages are hypothesis-only: the reference is read-speech canonical
# text and the production pipeline targets idiosyncrasies of the
# hypothesis.  Together with ``pipeline_full``, the registry now covers
# every transformation that the desktop pipeline applies to a
# hypothesis between raw model output and final saved text.

_register(Condition(
    name="unicode_strip",
    description=(
        "Removes emoji and characters in the symbol and control "
        "categories from the hypothesis, keeping the letters, combining "
        "marks and digits of every script, punctuation and currency "
        "signs, and mapping typographic quotation marks to ASCII; the "
        "first stage of the desktop pipeline.  On English read-speech "
        "benchmarks the effect is expected to be small because "
        "Whisper-family models rarely emit emoji on clean audio."
    ),
    transform=_unicode_strip,
    apply_to_reference=False,
    notes=(
        "Delegates to transcription.remove_emojis_and_unicode_artifacts. "
        "Idempotent because a second application finds no removable "
        "codepoint left.  Not WER-invisible: a symbol deleted between two "
        "letters joins two scored tokens, where the normaliser would have "
        "put a space.  Committed results scored before the stage kept "
        "every script (audit finding T1-02) used a version that also "
        "deleted typographic apostrophes and non-Latin scripts."
    ),
))

_register(Condition(
    name="undefined_tag",
    description=(
        "Replaces the speech-artefact tokens ``undefined``, "
        "``undefine``, ``undefin`` and ``undefining`` with the "
        "bracketed marker ``[undefined]`` in the hypothesis.  Reflects "
        "the desktop pipeline's handling of model fragments that "
        "occasionally surface when audio is cut off mid-word."
    ),
    transform=_undefined_tag,
    apply_to_reference=False,
    notes=(
        "Idempotent because the patterns match unbracketed tokens "
        "only; the bracketed replacement contains no whitespace-"
        "separated ``undefin*`` tokens that a second pass could match.  "
        "Not WER-invisible: the brackets vanish under the scoring "
        "normaliser, but the variants undefine, undefin and undefining "
        "are rewritten to undefined, which changes a scored token."
    ),
))

_register(Condition(
    name="filler_bracket",
    description=(
        "Wraps unambiguous non-lexical fillers in square brackets in "
        "the hypothesis, leaving the surface tokens visible to a human "
        "reader while distinguishing them from lexical content: a "
        "hyphenated backchannel is bracketed whole (``[uh-huh]``), and a "
        "filler inside a hyphenated compound or next to an apostrophe is "
        "left alone.  The scoring normaliser turns brackets into spaces, "
        "so a bracketed filler scores as the bare one and this condition "
        "scores exactly as raw by construction: it keeps every filler as "
        "a scored word, and its WER cannot show any cost or benefit of "
        "the marking."
    ),
    transform=_filler_bracket,
    apply_to_reference=False,
    wer_invisible=True,
    notes=(
        "The patterns exclude ``[`` and ``]`` on either side, so that a "
        "second application leaves already-bracketed fillers untouched "
        "and the transformation is idempotent.  This differs from the "
        "original monolithic implementation, where re-running would have "
        "produced ``[[um]]``; the change is documented in the manuscript.  "
        "Against a reference that omits fillers, each filler is one "
        "insertion under this condition and under raw alike; "
        "filler_strip, which deletes them, is the condition whose "
        "difference from raw measures that cost.  The committed post-fix "
        "cells predate the apostrophe guard and differ from raw where the "
        "stage bracketed inside words such as o'er."
    ),
))

_register(Condition(
    name="contraction_fix",
    description=(
        "Repairs the common contractions emitted without apostrophes "
        "by Whisper-family models, including the space-split artefacts "
        "such as ``isn t`` produced by the model's BPE tokeniser.  "
        "Aligns the hypothesis with reference transcripts that record "
        "the apostrophised forms."
    ),
    transform=_contraction_fix,
    apply_to_reference=False,
    notes=(
        "Idempotent because each table entry rewrites an unapostrophised "
        "source pattern to its apostrophised form; a second pass finds "
        "the apostrophised form, which does not match the source "
        "pattern.  The table is the single source of truth for the "
        "desktop pipeline."
    ),
))

_register(Condition(
    name="common_phrase_fix",
    description=(
        "Normalises capitalisation in a fixed set of lexical hedges "
        "(``i mean`` to ``I mean``, ``Kind of`` to ``kind of``).  It "
        "changes case only, which the scoring normaliser removes, so it "
        "scores exactly as raw by construction; it is registered for "
        "production parity, not because WER can measure it."
    ),
    transform=_common_phrase_fix,
    apply_to_reference=False,
    wer_invisible=True,
    notes=(
        "Idempotent: the table maps each source pattern to a target "
        "string that, when fed back as input, matches the same row "
        "and is rewritten to itself.  Included so that the benchmark "
        "sees the same sequence of substitutions as the desktop "
        "pipeline."
    ),
))

_register(Condition(
    name="whitespace_normalise",
    description=(
        "Collapses runs of whitespace and tidies the spacing around "
        "commas and full stops in the hypothesis.  Stage 5 of the "
        "desktop clean-text pipeline.  Spacing and punctuation vanish "
        "under the scoring normaliser, so it scores exactly as raw by "
        "construction."
    ),
    transform=_whitespace_normalise,
    apply_to_reference=False,
    wer_invisible=True,
    notes=(
        "Idempotent: a second pass finds whitespace already collapsed "
        "to single spaces and commas already correctly spaced."
    ),
))

_register(Condition(
    name="sentence_capitalise",
    description=(
        "Capitalises sentence-initial words (after ``.``, ``!`` or "
        "``?``) in the hypothesis.  Sentence-initial capitalisation is an "
        "orthographic convention shared across the languages this "
        "workflow handles, so the stage is not gated on language.  It "
        "changes case only, so it scores exactly as raw by construction."
    ),
    transform=_sentence_capitalise,
    apply_to_reference=False,
    wer_invisible=True,
    notes=(
        "Idempotent: a sentence whose first letter is already upper "
        "case is left unchanged.  Capitalisation of the standalone "
        "pronoun ``i`` was split out into ``pronoun_i_fix`` so that it "
        "can be gated on language."
    ),
))

_register(Condition(
    name="pronoun_i_fix",
    description=(
        "Capitalises the standalone English first-person pronoun ``i`` "
        "in the hypothesis.  English-specific by nature: ``i`` is an "
        "ordinary word in other languages, notably the Italian masculine "
        "plural article in ``i libri``, where capitalising it corrupts "
        "the transcript.  It changes case only, so it scores exactly as "
        "raw by construction."
    ),
    transform=_pronoun_i_fix,
    apply_to_reference=False,
    wer_invisible=True,
    notes=(
        "Split out of sentence_capitalise so the language gate can skip "
        "it on non-English transcripts.  The split is behaviour-preserving "
        "for English because a sentence-initial ``i`` is already "
        "upper-cased by the preceding stage.  Idempotent: ``I`` is "
        "already upper case."
    ),
))

_register(Condition(
    name="punct_space_fix",
    description=(
        "Normalises spacing around punctuation, quotation marks and "
        "parentheses, removes duplicate punctuation and collapses "
        "adjacent-punctuation runs.  Stage 8 of the desktop "
        "clean-text pipeline.  It touches only spacing and punctuation "
        "other than the apostrophe, all of which the scoring normaliser "
        "removes, so it scores exactly as raw by construction."
    ),
    transform=_punct_space_fix,
    apply_to_reference=False,
    wer_invisible=True,
    notes=(
        "Idempotent: each substitution removes a specific irregularity "
        "and the regular form does not re-match the source pattern."
    ),
))

_register(Condition(
    name="pipeline_full",
    description=(
        "Applies the production post-processing chain that "
        "transcription.py runs with --fix-spurious-repetitions: unicode "
        "strip, repetition repair and the eight atomic clean-text stages, "
        "in production order.  Repetition repair is off by default in "
        "transcription.py and the desktop app, so this is the opt-in "
        "configuration (the one the project's case study used), not what "
        "a default run delivers; a default run omits the repetition "
        "repair.  No name masking is applied."
    ),
    transform=_pipeline_full,
    apply_to_reference=False,
    language_aware=True,
    notes=(
        "Calls transcription.postprocess_transcript_text with "
        "fix_repetitions=True, which composes unicode_strip, "
        "repetition_fix, undefined_tag, filler_bracket, contraction_fix, "
        "common_phrase_fix, whitespace_normalise, sentence_capitalise, "
        "pronoun_i_fix and punct_space_fix, in that order; on "
        "non-English transcripts the English-only stages are skipped.  "
        "The decode also differs from a production run: the benchmark "
        "decodes the whole utterance with the language forced, whereas "
        "transcription.py decodes in chunks and forces a language only "
        "when one is given.  On a GPU, transcription.py decodes in "
        "float16 and the benchmark in the checkpoint's own precision, "
        "float16 for Large v3 and distil-large-v3 and float32 for "
        "Whisper Medium (each summary the benchmark writes records it "
        "under benchmark.decode.dtype), so the two differ in precision "
        "only for Whisper Medium.  On a processor both decode in "
        "float32.  Hypothesis-only because the constituent stages are "
        "all hypothesis-only."
    ),
))


# ---------------------------------------------------------------------------
# Default sweep list
# ---------------------------------------------------------------------------
# The conditions a sweep scores besides the production clean-text stages,
# which default_sweep_conditions() reads from transcription.CLEAN_TEXT_STAGES
# so that a stage added there is scored without a second list to update
# (audit finding EWER-13: the hand-typed list had missed pronoun_i_fix).
# ``raw`` must stay first: the first condition is written to the unsuffixed
# primary path, which evaluation.condition_ci reads as the baseline when no
# summary says otherwise.
_SWEEP_HEAD = ("raw", "unicode_strip", "repetition_fix")
_SWEEP_TAIL = ("pipeline_full", "filler_strip", "dedup_window", "punct_strip",
               "case_fold", "whisper_norm")


def default_sweep_conditions() -> tuple[str, ...]:
    """Return the condition names a sweep scores when none are given.

    The list has three layers: the production chain (``raw``, the Unicode
    strip, repetition repair, every stage of
    ``transcription.CLEAN_TEXT_STAGES`` in production order, and the
    composite ``pipeline_full``); the diagnostic ablations that production
    does not apply (``filler_strip``, ``dedup_window``, ``punct_strip``,
    ``case_fold``); and ``whisper_norm``, the published normaliser.  It
    covers every registered condition.

    Imports :mod:`transcription` (and so its optional audio stack) on
    first call.
    """
    from transcription import CLEAN_TEXT_STAGES
    stages = tuple(stage.__name__.lstrip("_") for stage in CLEAN_TEXT_STAGES)
    return _SWEEP_HEAD + stages + _SWEEP_TAIL


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_condition(name: str) -> Condition:
    """Return the registered ``Condition`` for *name*.

    Raises
    ------
    KeyError
        If *name* is not in the registry.  The error message lists all
        available condition names so the caller can propagate a useful
        diagnostic.
    """
    try:
        return _CONDITIONS[name]
    except KeyError:
        available = ", ".join(sorted(_CONDITIONS))
        raise KeyError(
            f"Unknown condition {name!r}.  Available conditions: {available}"
        ) from None


def list_conditions() -> list[Condition]:
    """Return all registered conditions in alphabetical order by name."""
    return [_CONDITIONS[k] for k in sorted(_CONDITIONS)]


def condition_provenance(name: str) -> dict | None:
    """Return what a condition's transform was built from, or ``None``.

    Only ``whisper_norm`` depends on external data (its spelling map and the
    transformers class), so only it reports anything: the implementation,
    the library versions and the map's digest and size.  The block exists
    once the transform has run at least once; a benchmark writes it into
    the condition's summary so the artefact names the normaliser that
    scored it.
    """
    if name == "whisper_norm" and _WHISPER_NORM_PROVENANCE is not None:
        return dict(_WHISPER_NORM_PROVENANCE)
    return None
