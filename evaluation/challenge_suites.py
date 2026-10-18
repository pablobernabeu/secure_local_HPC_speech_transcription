#!/usr/bin/env python3
"""
Registry of challenge evaluation suites for the WER benchmark.

Each suite targets a speaker population or acoustic condition that is
under-represented in the primary LibriSpeech test-clean benchmark.  Suites
are invoked via the ``--suite`` argument of ``evaluation.benchmark_wer``
rather than supplying ``--dataset``, ``--config`` and ``--split``
individually.

The four suites registered here extend the benchmark along dimensions
relevant to the project's deployment context — formal academic lectures
with diverse speaker backgrounds:

``fleurs``
    FLEURS English (US) test split (Conneau et al., 2022).  647 utterances
    in the committed runs, from diverse speakers reading Wikipedia and news
    sentences recorded under controlled conditions across multiple
    recording sites.  Reference text is in the ``transcription`` column,
    which contains lower-cased normalised text.  The ``id`` column names
    the sentence, not the recording, and several speakers read the same
    sentence, so ids repeat; the benchmark renames repeats
    ``<id>__<n>``.  Licence: CC-BY-4.0.

``voxpopuli_accented``
    VoxPopuli accented-English test split (Wang et al., 2021).
    8,387 utterances in the committed runs (about 29 hours) of European
    Parliament speeches by non-native
    English speakers representing 15 first-language backgrounds: Dutch,
    German, Czech, Polish, French, Hungarian, Finnish, Romanian, Slovak,
    Spanish, Italian, Estonian, Lithuanian, Croatian and Slovene.  Only a
    ``test`` split is available for this configuration.  Reference text is
    in the ``normalized_text`` column.  Licence: CC0-1.0.

``ami``
    AMI Meeting Corpus, individual headset microphone configuration
    (Carletta et al., 2005).  Approximately 12,600 utterances of
    spontaneous multi-speaker meeting speech recorded in three rooms with
    different acoustic properties; the speaker population includes a
    majority of non-native English users.  Transcriptions follow the KALDI
    AMI S5 convention (upper case); ``normalise_text`` lowercases them
    before scoring.  Reference text is in the ``text`` column.
    Licence: CC-BY-4.0.

``librispeech_other``
    LibriSpeech 'other' test split (Panayotov et al., 2015).  Approximately
    2,939 utterances of read audiobook speech from the harder partition
    used to evaluate ASR systems on noisier recordings and a broader range
    of accents than the canonical 'clean' partition; loaded with the same
    ``librispeech_asr`` HuggingFace loader and only ``config='other'``.
    Licence: CC-BY-4.0.

Corpus audio is streamed via the HuggingFace ``datasets`` API and is not
bundled in the repository. Some committed reports and hypothesis files retain
decoded text, and optional hypothesis dumps also retain corpus references.
The committed artefacts and recovered dumps have a separate retention and
deposit record in ``docs/release_readiness.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Suite names become CLI values and file-name stems.
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Suite:
    """All parameters needed to run a named challenge evaluation suite.

    Attributes
    ----------
    name:
        URL-safe slug used as the ``--suite`` CLI value and as the stem of
        output file names.  Must match ``^[a-z][a-z0-9_]*$``.
    description:
        One-sentence plain-prose summary of the suite (British English,
        no bullet points).
    category:
        Coarse grouping for reporting: ``accented``, ``spontaneous`` or
        ``diverse_speakers``.
    dataset:
        HuggingFace dataset identifier passed to ``datasets.load_dataset``.
    config:
        Dataset configuration name (second positional argument to
        ``load_dataset``).
    split:
        Dataset split to stream (e.g. ``"test"``).
    ref_field:
        Name of the row field that contains the reference transcription.
    uid_field:
        Name of the row field that contains the utterance identifier.
        Not necessarily unique (FLEURS repeats sentence ids); the
        benchmark renames repeats.
    licence:
        SPDX licence identifier for the underlying data.
    citation_key:
        BibTeX key in ``manuscript/references.bib``.
    notes:
        Optional free-text notes about limitations or usage caveats.
    """

    name:         str
    description:  str
    category:     str
    dataset:      str
    config:       str
    split:        str
    ref_field:    str
    uid_field:    str
    licence:      str
    citation_key: str
    notes:        str = ""


_SUITES: dict[str, Suite] = {}


def _register(suite: Suite) -> Suite:
    """Add *suite* to the global registry and return it.

    Raises
    ------
    ValueError
        If the name is already registered or is not a valid slug.
    """
    if not _SLUG_RE.match(suite.name):
        raise ValueError(
            f"Suite name {suite.name!r} does not match {_SLUG_RE.pattern}."
        )
    if suite.name in _SUITES:
        raise ValueError(f"Suite {suite.name!r} is already registered.")
    _SUITES[suite.name] = suite
    return suite


# ---------------------------------------------------------------------------
# Suite 1: FLEURS English (US) — diverse speakers, controlled conditions
# ---------------------------------------------------------------------------
_register(Suite(
    name="fleurs",
    description=(
        "FLEURS English (US) test split: 647 utterances from diverse "
        "speakers reading Wikipedia and news sentences in controlled "
        "recording conditions across multiple sites."
    ),
    category="diverse_speakers",
    dataset="google/fleurs",
    config="en_us",
    split="test",
    ref_field="transcription",
    uid_field="id",
    licence="CC-BY-4.0",
    citation_key="conneauFleursFewshotLearning2023",
    notes=(
        "The 'transcription' column contains lower-cased normalised text. "
        "The committed runs scored 647 test utterances; a validation split "
        "is also available via split='validation'.  Audio is recorded at "
        "16 kHz.  The 'id' column is a sentence id that repeats across "
        "speakers, so the benchmark renames repeated ids '<id>__<n>'."
    ),
))

# ---------------------------------------------------------------------------
# Suite 2: VoxPopuli accented English — L2 speakers, 15 accent varieties
# ---------------------------------------------------------------------------
_register(Suite(
    name="voxpopuli_accented",
    description=(
        "VoxPopuli accented-English test split: 8,387 utterances (about 29 "
        "hours) of European Parliament speeches by non-native English speakers "
        "representing 15 first-language backgrounds (Dutch, German, Czech, "
        "Polish, French, Hungarian, Finnish, Romanian, Slovak, Spanish, "
        "Italian, Estonian, Lithuanian, Croatian and Slovene)."
    ),
    category="accented",
    dataset="facebook/voxpopuli",
    config="en_accented",
    split="test",
    ref_field="normalized_text",
    uid_field="audio_id",
    licence="CC0-1.0",
    citation_key="wangVoxpopuliLargescaleMultilingual2021",
    notes=(
        "Only a 'test' split is available for the en_accented configuration; "
        "there is no train or validation split.  Speeches are drawn from "
        "2009–2020 European Parliament plenary sessions.  The 'raw_text' "
        "column may be empty; use 'normalized_text' as the reference."
    ),
))

# ---------------------------------------------------------------------------
# Suite 3: AMI IHM — spontaneous multi-speaker meeting speech
# ---------------------------------------------------------------------------
_register(Suite(
    name="ami",
    description=(
        "AMI Meeting Corpus (individual headset microphone) test split: "
        "approximately 12,600 utterances of spontaneous multi-speaker "
        "meeting speech recorded in three rooms with different acoustic "
        "properties; the speaker population includes a majority of "
        "non-native English users."
    ),
    category="spontaneous",
    dataset="edinburghcstr/ami",
    config="ihm",
    split="test",
    ref_field="text",
    uid_field="audio_id",
    licence="CC-BY-4.0",
    citation_key="carlettaAMIMeeting2005",
    notes=(
        "Transcriptions follow the KALDI AMI S5 convention (upper case) "
        "and are lowercased by normalise_text before scoring.  The test "
        "set contains ~12,600 utterances; pass --limit 1000 for a faster "
        "diagnostic run.  Many utterances are very short (one or two words), "
        "which inflates per-utterance WER; inspect micro WER alongside macro "
        "WER when interpreting results."
    ),
))

# ---------------------------------------------------------------------------
# Suite 4: LibriSpeech test-other — noisier / more accented read speech
# ---------------------------------------------------------------------------
_register(Suite(
    name="librispeech_other",
    description=(
        "LibriSpeech 'other' test split (Panayotov et al., 2015): "
        "approximately 2,939 utterances of read audiobook speech drawn from "
        "the harder partition used to evaluate ASR systems on noisier "
        "recordings and a broader range of accents than the canonical "
        "'clean' partition."
    ),
    category="diverse_speakers",
    dataset="librispeech_asr",
    config="other",
    split="test",
    ref_field="text",
    uid_field="id",
    licence="CC-BY-4.0",
    citation_key="panayotovLibrispeechASRCorpus2015",
    notes=(
        "Drawn from the same loader as the primary LibriSpeech test-clean "
        "benchmark; the only change is config='other'.  WERs are typically "
        "two to three times higher than on test-clean for the same model, "
        "and the model's tendency to hallucinate repetition loops is more "
        "pronounced — making this suite a useful stress test of the "
        "post-processing conditions."
    ),
))


def get_suite(name: str) -> Suite:
    """Return the registered ``Suite`` for *name*.

    Raises
    ------
    KeyError
        If *name* is not in the registry.  The error message lists all
        available suite names so the caller can propagate a useful diagnostic.
    """
    try:
        return _SUITES[name]
    except KeyError:
        available = ", ".join(sorted(_SUITES))
        raise KeyError(
            f"Unknown suite {name!r}.  Available suites: {available}"
        ) from None


def list_suites() -> list[Suite]:
    """Return all registered suites in alphabetical order by name."""
    return [_SUITES[k] for k in sorted(_SUITES)]
