"""Tests for ``manuscript/references.bib`` and ``tools/bib_sentencecase.py``.

Two groups of tests live here.

The first group asserts invariants directly on the committed
``manuscript/references.bib``, because that file, and not a temporary
copy, is what the manuscript renders against. A 2026 audit found the
bibliography carrying 24 absolute ``file`` paths into the author's own
Zotero storage, a ``[No title found]`` placeholder, an entry dated a year
into the future and two Title Case titles, none of which the previous
suite could see. The checks below are written so that each of those
defects fails a named test.

The second group exercises the transform in ``tools/bib_sentencecase.py``
itself, including the possessive and multi-word proper-noun handling that
earlier over-corrections motivated.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest

bibtexparser = pytest.importorskip("bibtexparser")

from tools import bib_sentencecase as bsc  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REFERENCES_BIB = PROJECT_ROOT / "manuscript" / "references.bib"
MANUSCRIPT_QMD = PROJECT_ROOT / "manuscript" / "manuscript.qmd"
PROTECTED_JSON = PROJECT_ROOT / "manuscript" / "protected_terms.json"

# Quarto cross-reference namespaces. ``@fig-perfile`` is a reference to a
# figure, not a citation, and must not be looked for in the bibliography.
CROSSREF_PREFIXES = (
    "sec-", "fig-", "tbl-", "eq-", "lst-", "thm-", "lem-", "cor-",
    "prp-", "cnj-", "def-", "exm-", "exr-", "sol-", "rem-", "alg-",
)

_ENTRY_RE = re.compile(r"^@(\w+)\{([^,]+),", re.MULTILINE)
_FENCED_RE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_CITE_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_:.#$%&+?<>~/-]*)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _entries() -> list[tuple[str, str, str]]:
    """Return ``(kind, key, body)`` for every entry in the committed bib."""
    text = _read(REFERENCES_BIB)
    out = []
    for chunk in re.split(r"\n(?=@)", text):
        match = _ENTRY_RE.match(chunk)
        if match:
            out.append((match.group(1), match.group(2), chunk))
    return out


def _field(body: str, name: str) -> str | None:
    match = re.search(r"\n\s*" + name + r"\s*=\s*\{(.*?)\}\s*,?\s*\n", body, re.S)
    return match.group(1).strip() if match else None


def _cited_keys() -> set[str]:
    """Citation keys the manuscript actually uses.

    Fenced code is removed first so that an ``@`` inside an R chunk cannot
    be mistaken for a citation, and Quarto cross-references are dropped by
    namespace. Anything left over is treated as a citation and is expected
    to resolve, which is what makes a deleted-but-still-cited key fail.
    """
    prose = _FENCED_RE.sub("", _read(MANUSCRIPT_QMD))
    keys = set()
    for raw in _CITE_RE.findall(prose):
        key = raw.rstrip(".,;:)")
        if key.startswith(CROSSREF_PREFIXES) or "." in key:
            continue
        keys.add(key)
    return keys


@pytest.fixture(scope="module")
def entries():
    assert REFERENCES_BIB.exists(), "manuscript/references.bib is missing"
    return _entries()


@pytest.fixture(scope="module")
def protected_lists():
    acronyms, single, multi = bsc._load_protected(PROTECTED_JSON)
    return acronyms, single, multi


# --------------------------------------------------------------------------
# Invariants on the committed bibliography
# --------------------------------------------------------------------------

def test_every_cited_key_resolves(entries):
    """No citation in the manuscript may point at a missing entry."""
    available = {key for _, key, _ in entries}
    missing = sorted(_cited_keys() - available)
    assert not missing, f"cited but absent from references.bib: {missing}"


def test_no_file_field_leaks_a_local_path(entries):
    """``file`` fields carry absolute paths and identify the author."""
    offenders = [key for _, key, body in entries if _field(body, "file")]
    assert not offenders, f"entries carrying a file field: {offenders}"


def test_no_placeholder_titles(entries):
    """Reference-manager placeholders and stray macros are not titles."""
    bad = []
    for _, key, body in entries:
        title = _field(body, "title")
        if not title:
            bad.append((key, "<missing>"))
            continue
        lowered = title.lower()
        if "no title found" in lowered or "mkbibemph" in lowered:
            bad.append((key, title))
    assert not bad, f"placeholder or corrupt titles: {bad}"


def test_no_entry_is_dated_in_the_future(entries):
    """A date later than today is a metadata error, not a publication."""
    this_year = datetime.date.today().year
    bad = []
    for _, key, body in entries:
        stamp = _field(body, "date") or _field(body, "year")
        if not stamp:
            continue
        match = re.match(r"(\d{4})", stamp)
        if match and int(match.group(1)) > this_year:
            bad.append((key, stamp))
    assert not bad, f"entries dated after {this_year}: {bad}"


def test_every_entry_carries_a_year(entries):
    bad = [key for _, key, body in entries
           if not (_field(body, "date") or _field(body, "year"))]
    assert not bad, f"entries with no date: {bad}"


def test_cited_titles_are_sentence_case(entries):
    """APA 7 sentence case on every title the manuscript actually cites.

    Braced groups are removed before the check, so a brace-protected
    proper noun such as ``{LibriSpeech}`` is allowed to keep its capitals
    while an unprotected ``Named Entity Recognition`` is not. A word that
    follows a colon, question mark or full stop opens a new sentence and
    is therefore allowed to be capitalised.
    """
    cited = _cited_keys()
    offenders = {}
    for _, key, body in entries:
        if key not in cited:
            continue
        title = _field(body, "title")
        bare = re.sub(r"\{[^{}]*\}", " ", title)
        words = bare.split()
        stray = [
            word for i, word in enumerate(words)
            if i > 0
            and re.match(r"^[A-Z]", word)
            and not words[i - 1].endswith((":", "?", ".", "!"))
        ]
        if stray:
            offenders[key] = stray
    assert not offenders, f"titles not in sentence case: {offenders}"


def test_committed_bib_is_a_fixed_point_of_the_transform(tmp_path):
    """The transform must leave the committed bibliography untouched.

    Running it on a copy and finding a diff means either the file drifted
    out of sentence case or a proper noun in it is missing from
    ``protected_terms.json`` and would be folded on the next run. Line
    endings are normalised first, since the tool writes whatever the host
    platform uses and that says nothing about the content.
    """
    work = tmp_path / "references.bib"
    work.write_bytes(REFERENCES_BIB.read_bytes())
    bsc.run(work, PROTECTED_JSON, in_place=True)
    before = _read(REFERENCES_BIB).replace("\r\n", "\n")
    after = work.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert after == before, (
        "tools/bib_sentencecase.py would rewrite the committed bibliography"
    )


# --------------------------------------------------------------------------
# The transform itself
# --------------------------------------------------------------------------

def test_plato_proper_noun_with_possessive(protected_lists):
    """``Plato's`` must survive sentence-casing (possessive split)."""
    acronyms, single, multi = protected_lists
    out = bsc.sentence_case_field(
        "A solution to {Plato}'s problem: How children learn",
        acronyms=acronyms, proper_nouns=single,
        multi_word_proper_nouns=multi,
    )
    assert "{Plato}" in out, out
    assert "how children learn" in out.lower()


def test_multi_word_proper_noun_wrap(protected_lists):
    acronyms, single, multi = protected_lists
    out = bsc.sentence_case_field(
        "Performance of {Whisper} on Raspberry Pi devices",
        acronyms=acronyms, proper_nouns=single,
        multi_word_proper_nouns=multi,
    )
    assert "{Raspberry Pi}" in out


def test_tool_name_keeps_its_own_casing(protected_lists):
    """``Vink`` and ``pyannote.audio`` were folded by an earlier version."""
    acronyms, single, multi = protected_lists
    out = bsc.sentence_case_field(
        "From voice to ink ({Vink}): Development of a transcription tool",
        acronyms=acronyms, proper_nouns=single,
        multi_word_proper_nouns=multi,
    )
    assert "{Vink}" in out, out
    out = bsc.sentence_case_field(
        "{pyannote.audio}: Neural building blocks for speaker diarization",
        acronyms=acronyms, proper_nouns=single,
        multi_word_proper_nouns=multi,
    )
    assert "{pyannote.audio}" in out, out


def test_acronym_uppercased(protected_lists):
    acronyms, single, multi = protected_lists
    out = bsc.sentence_case_field(
        "An hpc-oriented asr pipeline using gpu acceleration",
        acronyms=acronyms, proper_nouns=single,
        multi_word_proper_nouns=multi,
    )
    assert "{HPC}" in out
    assert "{ASR}" in out
    assert "{GPU}" in out


def test_title_case_routing_keeps_stopwords_lower(protected_lists):
    acronyms, single, multi = protected_lists
    out = bsc.title_case_field(
        "advances in information retrieval and the analysis of speech",
        acronyms=acronyms, proper_nouns=single,
        multi_word_proper_nouns=multi,
    )
    assert out == "Advances in Information Retrieval and the Analysis of Speech"


def test_title_case_first_and_last_capitalised(protected_lists):
    acronyms, single, multi = protected_lists
    out = bsc.title_case_field(
        "the long and winding road of",
        acronyms=acronyms, proper_nouns=single,
        multi_word_proper_nouns=multi,
    )
    assert out.startswith("The "), out
    assert out.endswith(" Of"), out


def test_idempotent_on_curated_bib(tmp_path):
    """Running the transform twice produces identical bytes."""
    work = tmp_path / "references.bib"
    work.write_bytes(REFERENCES_BIB.read_bytes())

    bsc.run(work, PROTECTED_JSON, in_place=True)
    after_first = work.read_bytes()
    bsc.run(work, PROTECTED_JSON, in_place=True)
    after_second = work.read_bytes()

    assert after_first == after_second, "second run modified the file"
