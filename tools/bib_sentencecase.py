"""Normalise title casing in ``manuscript/references.bib``.

Rewrites two groups of fields in every entry:

* sentence case for ``title``, ``shorttitle`` and ``subtitle``
  (:data:`SENTENCE_CASE_FIELDS`);
* title case for ``journaltitle``, ``booktitle`` and ``eventtitle``
  (:data:`TITLE_CASE_FIELDS`), so container names such as journals and
  proceedings volumes are capitalised word by word.

In both groups acronyms, proper nouns and tokens with strong original casing
(``>=2`` consecutive uppercase letters, ``camelCase``, or digit-letter
mixes) are protected by wrapping them in single braces, so BibTeX and Quarto
do not flatten their case during compilation.

APA 7 sets book and proceedings-volume titles in sentence case, which
``booktitle`` is not given here. Moving it would rewrite the committed
bibliography, so it is left for the maintainer to decide (audit finding
CORE-24).

The transform is idempotent: running the script twice in a row produces the
same byte-for-byte output, which is asserted by the pytest suite.

Usage
-----

    python tools/bib_sentencecase.py manuscript/references.bib \\
        --protected manuscript/protected_terms.json --in-place

Without ``--in-place`` the transformed bibliography is written to stdout,
which is useful for diff review before committing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from collections.abc import Iterable

try:
    import bibtexparser
    from bibtexparser.bparser import BibTexParser
    from bibtexparser.bwriter import BibTexWriter
except ImportError as exc:  # pragma: no cover - exercised manually
    print(
        "bibtexparser is required. Install with: pip install bibtexparser>=1.4",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


# Fields rewritten to *sentence-case* (only the first word and explicit
# proper nouns/acronyms are capitalised).
SENTENCE_CASE_FIELDS: tuple[str, ...] = (
    "title",
    "shorttitle",
    "subtitle",
)

# Fields rewritten to *title-case* (every word capitalised except short
# function words). Journal names, conference proceedings and event titles
# follow Chicago/AP convention: ``Trends in Hearing``,
# ``Proceedings of the 60th Annual Meeting of the ACL``.
TITLE_CASE_FIELDS: tuple[str, ...] = (
    "journaltitle",
    "booktitle",
    "eventtitle",
)

# Function words that stay lower-case in title-case unless they fall at the
# start or end of the field. Matches the Chicago Manual of Style short list.
_TITLE_CASE_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the",
        "and", "but", "or", "nor", "for", "yet", "so",
        "as", "at", "by", "in", "of", "on", "to", "up",
        "vs", "via", "per",
    }
)

_SENTENCE_PUNCT = ".?!:"


def _load_protected(
    path: Path,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Return ``(acronyms, single_word_proper_nouns, multi_word_proper_nouns)``.

    Single-word entries are returned as ``lowercase -> canonical`` lookup maps.
    Multi-word entries are returned as a list of canonical phrases, used in a
    second pass to wrap whole spans (e.g. ``Raspberry Pi``).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    acronyms = {term.lower(): term.upper() for term in data.get("acronyms", [])}
    proper_single: dict[str, str] = {}
    proper_multi: list[str] = []
    for term in data.get("proper_nouns", []):
        if any(ch.isspace() for ch in term):
            proper_multi.append(term)
        else:
            proper_single[term.lower()] = term
    # Apply longer phrases first so they win when one is a prefix of another.
    proper_multi.sort(key=len, reverse=True)
    return acronyms, proper_single, proper_multi


def _strip_protective_braces(value: str) -> str:
    """Remove all ``{...}`` and ``{{...}}`` brace groups from ``value``.

    BibLaTeX uses braces as case-protection. To enforce a single, curated
    sentence-case style the script first strips every brace group and then
    re-applies brace protection only to terms in the protect-list or those
    flagged by the strong-casing heuristic.
    """
    out_chars: list[str] = []
    depth = 0
    for ch in value:
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth = max(depth - 1, 0)
            continue
        out_chars.append(ch)
    # Collapse double spaces introduced by removed empty braces.
    return re.sub(r"\s{2,}", " ", "".join(out_chars)).strip()


def _has_strong_casing(token_core: str) -> bool:
    """Return True if ``token_core`` carries case signals worth preserving."""
    if re.search(r"[A-Z]{2,}", token_core):
        return True
    if re.search(r"[a-z][A-Z]", token_core):
        return True
    return bool(re.search(r"\d", token_core) and re.search(r"[A-Za-z]", token_core))


# Splits a stripped field value into a stream of three piece kinds:
#   * word     – ``\w`` run with optional internal hyphens/apostrophes/periods
#   * space    – runs of whitespace
#   * punct    – any other run of non-word, non-whitespace characters
# Splitting words from punctuation explicitly lets us catch sub-sentence
# boundaries like ``Gap:Analyzing`` (no space after colon) and joined acronyms
# such as ``ACM/IEEE`` so each part is transformed independently.
_PIECE_RE = re.compile(r"[\w][\w\-\'\.]*|[^\w\s]+|\s+", flags=re.UNICODE)


def _split_possessive(word: str) -> tuple[str, str]:
    """Split a trailing possessive suffix (``Plato's`` -> ``("Plato", "'s")``).

    Handles both straight ``'`` and curly ``’`` apostrophes; returns
    ``(word, "")`` when no possessive suffix is present.
    """
    for apostrophe in ("'", "\u2019"):
        for suffix in (apostrophe + "s", apostrophe):
            if word.lower().endswith(suffix) and len(word) > len(suffix):
                return word[: -len(suffix)], word[-len(suffix):]
    return word, ""


def _transform_word(
    word: str,
    *,
    is_sentence_start: bool,
    acronyms: dict[str, str],
    proper_nouns: dict[str, str],
) -> str:
    """Return ``word`` rewritten according to the protect-list and heuristics.

    Hyphenated compounds (``whisper-series``, ``AI-driven``, ``XLM-RoBERTa``)
    are split on ``-`` and each sub-token is transformed independently so that
    embedded acronyms and proper nouns are preserved without rewriting the
    surrounding stem.
    """
    if not word:
        return word
    word_lower = word.lower()

    if word_lower in acronyms:
        return f"{{{acronyms[word_lower]}}}"
    if word_lower in proper_nouns:
        return f"{{{proper_nouns[word_lower]}}}"

    # Try stripping a possessive suffix (e.g. ``Plato's`` -> ``{Plato}'s``).
    stem, suffix = _split_possessive(word)
    if suffix:
        stem_lower = stem.lower()
        if stem_lower in acronyms:
            return f"{{{acronyms[stem_lower]}}}{suffix}"
        if stem_lower in proper_nouns:
            return f"{{{proper_nouns[stem_lower]}}}{suffix}"

    if "-" in word:
        parts = word.split("-")
        rendered_parts = [
            _transform_word(
                part,
                is_sentence_start=(is_sentence_start and i == 0),
                acronyms=acronyms,
                proper_nouns=proper_nouns,
            )
            for i, part in enumerate(parts)
        ]
        return "-".join(rendered_parts)
    if _has_strong_casing(word):
        return f"{{{word}}}"
    if is_sentence_start:
        return word_lower[0].upper() + word_lower[1:]
    return word_lower


def _wrap_multiword(text: str, multi_word_proper_nouns: list[str]) -> str:
    """Wrap multi-word proper-noun spans in single braces.

    The match is case-insensitive and tolerates variable internal whitespace.
    Spans already enclosed in braces are skipped via boundary lookarounds.
    """
    for canonical in multi_word_proper_nouns:
        escaped = re.escape(canonical).replace(r"\ ", r"\s+")
        pattern = r"(?<![\w{])(" + escaped + r")(?![\w}])"
        text = re.sub(
            pattern,
            lambda _m, c=canonical: "{" + c + "}",
            text,
            flags=re.IGNORECASE,
        )
    return text


def sentence_case_field(
    value: str,
    *,
    acronyms: dict[str, str],
    proper_nouns: dict[str, str],
    multi_word_proper_nouns: list[str] | None = None,
) -> str:
    """Return ``value`` rewritten in sentence-case with brace protection."""
    if not value:
        return value
    stripped = _strip_protective_braces(value)
    if not stripped:
        return value

    pieces = _PIECE_RE.findall(stripped)
    out: list[str] = []
    sentence_start = True
    for piece in pieces:
        if piece.isspace():
            out.append(piece)
            continue
        first = piece[0]
        if first.isalnum() or first == "_":
            out.append(
                _transform_word(
                    piece,
                    is_sentence_start=sentence_start,
                    acronyms=acronyms,
                    proper_nouns=proper_nouns,
                )
            )
            sentence_start = False
        else:
            out.append(piece)
            if piece[-1] in _SENTENCE_PUNCT:
                sentence_start = True
    result = "".join(out)
    if multi_word_proper_nouns:
        result = _wrap_multiword(result, multi_word_proper_nouns)
    return result


def _title_case_word(
    word: str,
    *,
    force_cap: bool,
    acronyms: dict[str, str],
    proper_nouns: dict[str, str],
) -> str:
    """Return ``word`` rewritten in title-case.

    ``force_cap`` is True for the first/last word of the field or for a word
    immediately following sentence-ending punctuation; in those positions
    stop-words are still capitalised.
    """
    if not word:
        return word
    word_lower = word.lower()
    if word_lower in acronyms:
        return f"{{{acronyms[word_lower]}}}"
    if word_lower in proper_nouns:
        return f"{{{proper_nouns[word_lower]}}}"
    stem, suffix = _split_possessive(word)
    if suffix:
        stem_lower = stem.lower()
        if stem_lower in acronyms:
            return f"{{{acronyms[stem_lower]}}}{suffix}"
        if stem_lower in proper_nouns:
            return f"{{{proper_nouns[stem_lower]}}}{suffix}"
    if "-" in word:
        parts = word.split("-")
        return "-".join(
            _title_case_word(
                part,
                force_cap=(force_cap if i == 0 else True),
                acronyms=acronyms,
                proper_nouns=proper_nouns,
            )
            for i, part in enumerate(parts)
        )
    if _has_strong_casing(word):
        return f"{{{word}}}"
    if not force_cap and word_lower in _TITLE_CASE_STOPWORDS:
        return word_lower
    return word_lower[0].upper() + word_lower[1:]


def title_case_field(
    value: str,
    *,
    acronyms: dict[str, str],
    proper_nouns: dict[str, str],
    multi_word_proper_nouns: list[str] | None = None,
) -> str:
    """Return ``value`` rewritten in title-case with brace protection."""
    if not value:
        return value
    stripped = _strip_protective_braces(value)
    if not stripped:
        return value

    pieces = _PIECE_RE.findall(stripped)
    word_indices = [
        i
        for i, p in enumerate(pieces)
        if p and (p[0].isalnum() or p[0] == "_")
    ]
    if not word_indices:
        return value
    first_idx, last_idx = word_indices[0], word_indices[-1]

    out: list[str] = []
    force_next = True  # capitalise after sentence-ending punctuation
    for i, piece in enumerate(pieces):
        if piece.isspace():
            out.append(piece)
            continue
        if piece[0].isalnum() or piece[0] == "_":
            force_cap = force_next or i in (first_idx, last_idx)
            out.append(
                _title_case_word(
                    piece,
                    force_cap=force_cap,
                    acronyms=acronyms,
                    proper_nouns=proper_nouns,
                )
            )
            force_next = False
        else:
            out.append(piece)
            if piece[-1] in _SENTENCE_PUNCT:
                force_next = True
    result = "".join(out)
    if multi_word_proper_nouns:
        result = _wrap_multiword(result, multi_word_proper_nouns)
    return result


def transform_entries(
    entries: Iterable[dict],
    *,
    acronyms: dict[str, str],
    proper_nouns: dict[str, str],
    multi_word_proper_nouns: list[str],
) -> int:
    """Mutate ``entries`` in place. Return number of fields rewritten."""
    rewrites = 0
    for entry in entries:
        for field in SENTENCE_CASE_FIELDS:
            if field not in entry:
                continue
            original = entry[field]
            new_value = sentence_case_field(
                original,
                acronyms=acronyms,
                proper_nouns=proper_nouns,
                multi_word_proper_nouns=multi_word_proper_nouns,
            )
            if new_value != original:
                entry[field] = new_value
                rewrites += 1
        for field in TITLE_CASE_FIELDS:
            if field not in entry:
                continue
            original = entry[field]
            new_value = title_case_field(
                original,
                acronyms=acronyms,
                proper_nouns=proper_nouns,
                multi_word_proper_nouns=multi_word_proper_nouns,
            )
            if new_value != original:
                entry[field] = new_value
                rewrites += 1
    return rewrites


def _build_writer() -> BibTexWriter:
    writer = BibTexWriter()
    writer.indent = "  "
    writer.align_values = True
    writer.add_trailing_comma = True
    writer.order_entries_by = None  # preserve input order
    return writer


def run(
    bib_path: Path,
    protected_path: Path,
    *,
    in_place: bool = False,
) -> str:
    """Apply the transform and return the rewritten BibTeX as a string."""
    acronyms, proper_nouns, multi_word = _load_protected(protected_path)

    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    parser.homogenize_fields = False
    parser.interpolate_strings = False

    raw = bib_path.read_text(encoding="utf-8")
    library = bibtexparser.loads(raw, parser=parser)

    rewrites = transform_entries(
        library.entries,
        acronyms=acronyms,
        proper_nouns=proper_nouns,
        multi_word_proper_nouns=multi_word,
    )

    writer = _build_writer()
    output = writer.write(library)

    if in_place:
        bib_path.write_text(output, encoding="utf-8")
    print(
        f"bib_sentencecase: rewrote {rewrites} field(s) across "
        f"{len(library.entries)} entries.",
        file=sys.stderr,
    )
    return output


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return its exit code.

    Parameters
    ----------
    argv:
        Argument list, or ``None`` to read ``sys.argv``.

    Returns 0 on success; bibtexparser missing exits 2 at import. Side
    effects: with ``--in-place`` the .bib file is rewritten, otherwise the
    transformed bibliography is written to stdout.
    """
    p = argparse.ArgumentParser(description=__doc__)
    # Optional, defaulting to the manuscript bibliography, so the
    # argument-free usage given in tools/README.md works (CORE-24).
    p.add_argument("bib", type=Path, nargs="?",
                   default=Path("manuscript/references.bib"),
                   help="Path to references.bib "
                        "(default: manuscript/references.bib)")
    p.add_argument(
        "--protected",
        type=Path,
        default=Path("manuscript/protected_terms.json"),
        help="Path to the curated protect-list JSON file.",
    )
    p.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite the .bib file in place. Otherwise print to stdout.",
    )
    args = p.parse_args(argv)

    output = run(args.bib, args.protected, in_place=args.in_place)
    if not args.in_place:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
