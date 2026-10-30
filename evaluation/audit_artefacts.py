#!/usr/bin/env python3
"""
Audit the residual-PII attack surface of the files the pipeline emits.

This module confirms, against a directory of committed outputs, the
privacy risk documented in ``docs/audit_phase2.md`` (Risk E): the masked
``.txt`` and ``.docx`` transcripts are de-identified, but the raw
timestamped ``_transcript.json`` and ``.vtt`` captions are written by
``write_timestamped_outputs`` *before* the name-masking pass, so they can
contain unmasked names, and the ``name_masking_logs/*.csv`` records the
original-to-placeholder mapping, so it literally stores the original
names alongside their replacements.

With ``--mask-personal-names`` the pipeline now also writes a redacted
parallel set, ``_transcript_redacted.json`` (whose payload carries
``"redacted": true``) and ``_transcript_redacted.vtt``, and with
``--redacted-timestamps-only`` the raw set is not written at all. The
redacted set is de-identified by design, so it is audited as masked: a
logged name found in it is a leak, not an expected property of a raw file.
So is the review report, ``<base>_review.json``, when its payload carries
``"redacted": true``: transcription.write_review_file copies the text of
each flagged segment into it, masked when masking is on.

The audit walks an output tree and classifies every emitted artefact by
type, recording for each its masking guarantee by design (masked versus
raw). It then reads any ``name_masking_logs`` CSV present, extracts the
set of original names that were masked, and scans the other artefacts in
the tree for verbatim occurrences of those names. Any artefact that is
masked by design yet still contains an original name is reported as a
residual-PII leak; the masking-log CSVs themselves are expected to
contain the originals and are not counted as leaks. A second pass ignores
case, because the masker's main measured leak is the lower-cased name,
which the verbatim scan cannot see; its matches are listed per file under
``leaked_names_casefold`` and counted apart, since ignoring case also
matches ordinary words that are names (``will``, ``mark``).

A masking log belongs to one recording, as
``name_masking_logs/<recording>/<log>.csv`` or, as the pipeline writes
it, ``name_masking_logs/name_replacements_<recording>.csv``. When a log
cannot be read in full, the names it holds cannot be looked for, so the
artefacts of its recording (those under a directory of that name or whose
file name starts with it) are reported as not checked, never as clean;
when none can be tied to it, every artefact is. The audit is then
incomplete, as it is when an artefact cannot be read, and the exit status
says so.

The analysis is pure text and CSV processing. ``.docx`` artefacts are
read through ``python-docx`` when it is importable and skipped otherwise;
no optional reader failure ever crashes the audit, but a skipped file
leaves the audit incomplete.

Usage::

    # The committed audit: example_output into output/evaluation.
    python -m evaluation.audit_artefacts
    # Another tree, reported elsewhere so the committed audit is kept.
    python -m evaluation.audit_artefacts --dir example_output --output-dir my_audit
    # A pipeline run writes output/ and name_masking_logs/ under its working
    # directory, so audit that directory, which holds both, not output/
    # alone, where no masking log would be found.
    python -m evaluation.audit_artefacts --dir path/to/run --output-dir path/to/run_audit

Exit status: 0 when every artefact was checked against every logged name
(a leak does not change it; the report says so), 2 when ``--dir`` is not
a directory, and 3 when the audit is incomplete, because a masking log
could not be read in full or an artefact could not be read. The report
is written in either of the cases 0 and 3.

Outputs
-------
``output/evaluation/artefact_audit.csv``
    One row per audited file: relative path, artefact type, whether the
    type is masked by design, whether residual PII was found, and a short
    human-readable detail string.

``output/evaluation/artefact_audit.json``
    Machine-readable summary: counts by type, the set of original names
    recovered from the masking logs, the logs not read in full, the files
    skipped or not checked, whether the audit is complete, and the
    per-file findings, each with its status.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    import docx as _docx  # python-docx
    _HAS_DOCX = True
except ImportError:
    _HAS_DOCX = False

_DEFAULT_DIR = Path("example_output")
_DEFAULT_OUTPUT_DIR = Path("output/evaluation")

# Artefact-type identifiers.
TYPE_TRANSCRIPT_TXT = "transcript_txt"
TYPE_TRANSCRIPT_DOCX = "transcript_docx"
TYPE_RAW_JSON = "raw_transcript_json"
TYPE_VTT = "vtt_captions"
TYPE_REDACTED_JSON = "redacted_transcript_json"
TYPE_REDACTED_VTT = "redacted_vtt_captions"
TYPE_REDACTED_REVIEW = "redacted_review_json"
TYPE_RAW_REVIEW = "raw_review_json"
TYPE_MASKING_LOG = "name_masking_log_csv"
TYPE_OTHER = "other"

# Masking guarantee by design, keyed by artefact type.  ``True`` means the
# pipeline writes the file only after the name-masking pass; ``False`` means
# the file is written from the raw transcription result, before masking.
_MASKED_BY_DESIGN: dict[str, bool] = {
    TYPE_TRANSCRIPT_TXT: True,
    TYPE_TRANSCRIPT_DOCX: True,
    TYPE_RAW_JSON: False,
    TYPE_VTT: False,
    TYPE_REDACTED_JSON: True,
    TYPE_REDACTED_VTT: True,
    # The review report copies each flagged segment's text, masked when the
    # run masked names ("redacted": true) and raw otherwise.
    TYPE_REDACTED_REVIEW: True,
    TYPE_RAW_REVIEW: False,
    # The masking log deliberately stores the original names; it is not a
    # de-identified artefact and is excluded from the leak scan as a target.
    TYPE_MASKING_LOG: False,
    TYPE_OTHER: False,
}

#: What the audit did with each file (:attr:`FileFinding.status`).
STATUS_SCANNED = "scanned"                  # searched for every logged name
STATUS_NO_NAMES = "nothing_to_scan_for"     # read; the logs hold no name
STATUS_NOT_CHECKED = "not_checked"          # a log of its recording was not read in full
STATUS_SKIPPED = "skipped"                  # could not be read
STATUS_LOG = "masking_log"                  # a masking log, read in full
STATUS_LOG_INCOMPLETE = "masking_log_not_read_in_full"
STATUS_NOT_AUDITED = "not_audited"          # not an audited artefact type
#: The statuses that leave the audit incomplete.
_INCOMPLETE_STATUSES = frozenset({STATUS_NOT_CHECKED, STATUS_SKIPPED,
                                  STATUS_LOG_INCOMPLETE})

#: Exit status when ``--dir`` is not a directory.
EXIT_NO_DIRECTORY = 2
#: Exit status when the audit is incomplete (see the module docstring).
EXIT_INCOMPLETE = 3

# Columns in a name_masking_logs CSV (``REPLACEMENT_LOG_FIELDS`` in transcription.py):
# filename, order, original, replacement, context_sentence, source (dictionary/ner/title).
_LOG_ORIGINAL_COLUMN = "original"
_LOG_REPLACEMENT_COLUMN = "replacement"
_LOG_SOURCE_COLUMN = "source"


@dataclass
class FileFinding:
    """Audit result for a single emitted artefact.

    Attributes
    ----------
    path:
        Path to the artefact relative to the audited directory, using
        forward slashes for portability.
    artefact_type:
        One of the ``TYPE_*`` identifiers in this module.
    masked_by_design:
        ``True`` when the pipeline writes this artefact only after the
        name-masking pass; ``False`` for raw artefacts and for the
        masking-log CSVs themselves.
    residual_pii_found:
        ``True`` when a masked-by-design artefact nonetheless contains a
        verbatim original name recovered from a masking log.
    detail:
        Short human-readable explanation of the finding.
    leaked_names:
        Sorted list of original names found verbatim in this artefact.
    leaked_names_casefold:
        Sorted list of original names found only when case is ignored
        (``pablo`` for a logged ``Pablo``). Lower-cased names are the
        masker's main measured leak, which the case-sensitive scan cannot
        see (EPRIV-25), but a case-insensitive match also catches ordinary
        words that happen to be names (``will``, ``mark``), so these are
        kept apart and do not set *residual_pii_found*.
    status:
        What the audit did with the file, one of the ``STATUS_*`` values:
        whether it was searched for every logged name, could not be read,
        or was searched without the names of a masking log of its
        recording that could not be read in full (``not_checked``).
    """

    path: str
    artefact_type: str
    masked_by_design: bool
    residual_pii_found: bool
    detail: str
    leaked_names: list[str] = field(default_factory=list)
    leaked_names_casefold: list[str] = field(default_factory=list)
    status: str = STATUS_SCANNED


def classify_artefact(path: Path) -> str:
    """Classify *path* into one of the ``TYPE_*`` artefact identifiers.

    Parameters
    ----------
    path:
        Path to a candidate artefact file.

    Returns
    -------
    str
        The artefact-type identifier.  Files whose parent directory is
        ``name_masking_logs`` and whose suffix is ``.csv`` are classified
        as masking logs regardless of their stem.  A ``.json`` file is the
        review report when its payload is an object with a ``flagged``
        list and a ``summary`` (confidence.review_transcript's shape), or a
        ``flagged`` list and a name ending in ``review``. Otherwise it is a
        transcript when its payload is an object with a ``segments`` or
        ``text`` field, or its name contains ``transcript``. Either is the
        redacted kind when the payload carries ``"redacted": true``, and
        raw otherwise.  Any other JSON (a summary, a manifest) is
        ``other``.  A JSON that cannot be parsed or decoded is kept as raw,
        so a malformed file is still scanned as text, not waved through;
        one that cannot be read at all is then reported as skipped by
        :func:`audit_directory`.  A ``.vtt`` is redacted when its stem ends
        in ``_redacted``, the pipeline's naming, since captions carry no
        flag.

    Side effects: reads and parses ``.json`` files.
    """
    suffix = path.suffix.lower()
    stem = path.stem.lower()
    parts = {p.lower() for p in path.parts}

    if suffix == ".csv" and "name_masking_logs" in parts:
        return TYPE_MASKING_LOG
    if suffix == ".docx":
        return TYPE_TRANSCRIPT_DOCX
    if suffix == ".vtt":
        return TYPE_REDACTED_VTT if stem.endswith("_redacted") else TYPE_VTT
    if suffix == ".json":
        payload = _read_json_payload(path)
        if payload is None:
            return TYPE_RAW_JSON
        # The review report was filed as "other", and so never scanned,
        # although it copies the text of every flagged segment.
        is_review = (isinstance(payload, dict)
                     and isinstance(payload.get("flagged"), list)
                     and ("summary" in payload or stem.endswith("review")))
        if is_review:
            return (TYPE_REDACTED_REVIEW if payload.get("redacted") is True
                    else TYPE_RAW_REVIEW)
        is_transcript = isinstance(payload, dict) and (
            "segments" in payload or "text" in payload
            or "transcript" in stem)
        if not is_transcript:
            return TYPE_OTHER
        if payload.get("redacted") is True:
            return TYPE_REDACTED_JSON
        return TYPE_RAW_JSON
    if suffix == ".txt":
        return TYPE_TRANSCRIPT_TXT
    return TYPE_OTHER


def _read_json_payload(path: Path):
    """Return the parsed JSON at *path*, or ``None`` if it cannot be read."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


_POSSESSIVE_RE = re.compile(r"['’][sS]$")


def _strip_name_token(token: str) -> str:
    """Return *token* stripped of surrounding punctuation, whitespace and a
    trailing possessive.

    Names logged by ``save_replacement_log`` carry whatever punctuation was
    attached to the matched word, for example ``"Bernabeu,"`` or
    ``"Bernabeu."``, and a possessive ``"Bernabeu's"``.  Leading and
    trailing non-word characters and a final ``'s`` (straight or curly
    apostrophe) are removed, so that the recovered name matches every form
    of it in prose: a logged ``Bernabeu's`` used to match only the
    possessive (EPRIV-25).
    """
    punctuation = ".,;:!?\"'()[]{}‘’“”"
    name = token.strip().strip(punctuation).strip()
    name = _POSSESSIVE_RE.sub("", name)
    return name.strip(punctuation).strip()


def extract_masked_names(log_path: Path) -> set[str]:
    """Return the set of original names recorded in a masking-log CSV.

    Parameters
    ----------
    log_path:
        Path to a ``name_masking_logs`` CSV with at least an ``original``
        column.

    Returns
    -------
    set of str
        Original names with surrounding punctuation stripped.  Empty and
        single-character tokens are discarded to avoid spurious matches.
        Honorific rows (``source`` ``title``, replacement ``[TITLE]``) are
        skipped: a title is not a name.  The log is decoded as UTF-8 with
        each undecodable byte sequence replaced, so one bad byte costs
        only the name it falls in, which is dropped, not every name after
        it. A log that cannot be read gives no name, one that has no
        ``original`` column gives none, and one that cannot be parsed in
        full gives the names before the error; :func:`audit_directory`
        reports each such problem through :func:`_read_masked_names`.
    """
    return _read_masked_names(log_path)[0]


#: U+FFFD, which ``errors="replace"`` puts in place of each undecodable
#: byte sequence.
_REPLACEMENT_CHAR = "\ufffd"


def _read_masked_names(log_path: Path) -> tuple[set[str], str | None]:
    """Return a masking log's original names and why any may be missing.

    The names are those :func:`extract_masked_names` returns. The second
    element is ``None`` when the whole log was read, and otherwise says,
    as a phrase that follows "masking log", why it was not: the file
    could not be read, it has no ``original`` column, it could not be
    parsed past a CSV error, or it held undecodable bytes, with their
    count. Each name a log fails to give is one the leak scan cannot look
    for, so the artefacts of that recording are reported as not checked.

    The log was once decoded strictly, so one bad byte raised in the
    middle of the file and lost every name of its decode chunk. It is now
    decoded with ``errors="replace"``, as the artefacts are, and the
    replacements are counted: a replacement character that was not in
    the file's bytes marks one undecodable sequence. A name containing
    one is dropped, since its true spelling is unknown.
    """
    names: set[str] = set()
    try:
        raw = log_path.read_bytes()
    except OSError as exc:
        return names, f"could not be read ({type(exc).__name__}: {exc})"
    text = raw.decode("utf-8", errors="replace")
    n_replaced = (text.count(_REPLACEMENT_CHAR)
                  - raw.count(_REPLACEMENT_CHAR.encode("utf-8")))
    problems: list[str] = []
    if n_replaced:
        problems.append(f"held {n_replaced} undecodable byte sequence(s), "
                        "read as U+FFFD")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None or _LOG_ORIGINAL_COLUMN not in reader.fieldnames:
            return names, "; ".join(
                [f"has no '{_LOG_ORIGINAL_COLUMN}' column", *problems])
        for row in reader:
            # The redacted word list masks each word on its own
            # (transcription._redact_segments), so the title rule, which
            # needs the following name, leaves "Dr" in place there. Were
            # titles counted, every such file would be reported as a
            # de-identified artefact leaking a name.
            if (row.get(_LOG_SOURCE_COLUMN) == "title"
                    or (row.get(_LOG_REPLACEMENT_COLUMN) or "")
                    .strip().startswith("[TITLE]")):
                continue
            original = _strip_name_token(row.get(_LOG_ORIGINAL_COLUMN, "") or "")
            if len(original) > 1 and _REPLACEMENT_CHAR not in original:
                names.add(original)
    except csv.Error as exc:
        problems.append(
            f"could not be parsed past a CSV error ({type(exc).__name__}: {exc})")
    return names, ("; ".join(problems) or None)


def _read_text_file(path: Path) -> str | None:
    """Return the decoded text of a plain-text artefact, or ``None`` on error.

    ``None`` tells the caller to report the file as skipped, as for an
    unreadable ``.docx``. An empty string here would be scanned and
    reported as clean although nothing was read.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_docx_text(path: Path) -> str | None:
    """Return the concatenated paragraph text of a ``.docx`` artefact.

    Returns ``None`` when ``python-docx`` is not importable or the file
    cannot be parsed, signalling the caller to skip the artefact rather
    than treat an unreadable file as clean.
    """
    if not _HAS_DOCX:
        return None
    try:
        document = _docx.Document(str(path))
    except Exception:
        return None
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def _find_verbatim_names(text: str, names: set[str]) -> list[str]:
    """Return the sorted names from *names* that occur verbatim in *text*.

    A whole-word, case-sensitive match is required: personal names are
    capitalised in the transcripts, and a case-sensitive word-boundary
    search avoids flagging common words that merely share letters with a
    name.
    """
    found: list[str] = []
    for candidate in names:
        pattern = r"\b" + re.escape(candidate) + r"\b"
        if re.search(pattern, text):
            found.append(candidate)
    return sorted(found)


def _find_casefold_only_names(text: str, names: set[str]) -> list[str]:
    """Return the sorted names that occur in *text* only when case is ignored.

    Complements :func:`_find_verbatim_names`: a name the masker logged as
    ``Pablo`` and missed as ``pablo`` is found here and not there. A name
    found verbatim is not repeated here.
    """
    found: list[str] = []
    for candidate in names:
        pattern = r"\b" + re.escape(candidate) + r"\b"
        if (not re.search(pattern, text)
                and re.search(pattern, text, flags=re.IGNORECASE)):
            found.append(candidate)
    return sorted(found)


def audit_directory(path: Path) -> tuple[list[FileFinding], set[str]]:
    """Audit every emitted artefact under *path* for residual PII.

    The tree is walked once to classify and read each artefact, the set of
    original names is recovered from every ``name_masking_logs`` CSV, and
    every masked-by-design artefact is scanned for verbatim occurrences of
    those names.

    Parameters
    ----------
    path:
        Root of the output tree to audit.

    Returns
    -------
    tuple
        ``(findings, masked_names)`` where *findings* is a list of
        :class:`FileFinding` (one per audited file, sorted by path) and
        *masked_names* is the union of original names recovered from all
        masking logs in the tree.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist or is not a directory.

    Side effects: reads the masking logs, the JSON files and every
    audited artefact under *path*, each once; prints a warning on stderr
    for each masking log that cannot be read in full. An artefact that
    cannot be read is reported as skipped, and one that a masking log not
    read in full may cover (see the module docstring) as not checked,
    never as clean.
    """
    if not path.is_dir():
        raise FileNotFoundError(f"Not a directory: {path}")

    # Ordered by lower-cased path components, the order a Windows path sort
    # gives, which is the order of the committed report. Sorting the Path
    # objects themselves is case-sensitive on Linux, where it put
    # transcripts/README.md first and failed the regeneration gate on the
    # first hosted CI run (GitHub run 39053221780).
    files = sorted((p for p in path.rglob("*") if p.is_file()),
                   key=lambda p: [part.lower() for part in p.relative_to(path).parts])

    # Each file is classified once: classification parses every JSON.
    types = {file_path: classify_artefact(file_path) for file_path in files}

    # First pass: read each masking log once, recover the union of original
    # names, and note each log not read in full with its recording.
    masked_names: set[str] = set()
    logs: dict[Path, tuple[set[str], str | None]] = {}
    for file_path in files:
        if types[file_path] != TYPE_MASKING_LOG:
            continue
        names, problem = _read_masked_names(file_path)
        logs[file_path] = (names, problem)
        masked_names |= names
        if problem:
            print(f"  Warning: masking log {file_path} {problem}; any name it "
                  f"holds beyond the {len(names)} recovered is not scanned "
                  "for, so its recording's artefacts are not checked",
                  file=sys.stderr)

    scannable = [p for p in files
                 if types[p] not in (TYPE_MASKING_LOG, TYPE_OTHER)]
    # The masking logs not read in full that each artefact depends on. A
    # recording's log covers the artefacts named after it; a log that no
    # artefact can be tied to (an unrecognised name, or transcripts written
    # under another --output-name) covers every artefact, since any of them
    # may hold its names. Until this, one bad log among several left its
    # recording's transcripts reported clean.
    depends_on: dict[Path, list[str]] = {p: [] for p in scannable}
    for log_path, (_names, problem) in logs.items():
        if not problem:
            continue
        log_rel = log_path.relative_to(path)
        recording = _log_recording(log_rel.parts)
        covered = [p for p in scannable if recording is not None
                   and _belongs_to(p.relative_to(path).parts, recording)]
        for p in covered or scannable:
            depends_on[p].append(log_rel.as_posix())

    # Second pass: report each file, scanning the artefacts.
    findings: list[FileFinding] = []
    for file_path in files:
        artefact_type = types[file_path]
        masked_by_design = _MASKED_BY_DESIGN.get(artefact_type, False)
        rel = file_path.relative_to(path).as_posix()

        if artefact_type == TYPE_MASKING_LOG:
            originals, problem = logs[file_path]
            if problem:
                findings.append(_unscanned(
                    rel, artefact_type, STATUS_LOG_INCOMPLETE,
                    f"masking log {problem}; {len(originals)} original "
                    "name(s) recovered, any other name it holds is not "
                    "scanned for, and its recording's artefacts are not "
                    "checked"))
            else:
                findings.append(_unscanned(
                    rel, artefact_type, STATUS_LOG,
                    f"masking log; stores {len(originals)} original name(s) "
                    "by design (expected, not a leak)"))
            continue
        if artefact_type == TYPE_OTHER:
            findings.append(_unscanned(rel, artefact_type, STATUS_NOT_AUDITED,
                                       "not an audited artefact type"))
            continue

        # Read artefact text for the leak scan.
        if artefact_type == TYPE_TRANSCRIPT_DOCX:
            text = _read_docx_text(file_path)
            reason = ("python-docx not installed"
                      if not _HAS_DOCX else "unreadable .docx")
        else:
            text = _read_text_file(file_path)
            reason = "unreadable file"
        if text is None:
            findings.append(_unscanned(rel, artefact_type, STATUS_SKIPPED,
                                       f"skipped: {reason}"))
            continue

        leaked = _find_verbatim_names(text, masked_names) if masked_names else []
        casefold = (_find_casefold_only_names(text, masked_names)
                    if masked_names else [])
        residual = bool(leaked)
        missing = depends_on[file_path]
        status = STATUS_NOT_CHECKED if missing else STATUS_SCANNED
        if residual:
            shown = ", ".join(leaked[:5])
            more = "" if len(leaked) <= 5 else f" (+{len(leaked) - 5} more)"
            kind = "raw artefact, unmasked by design" if not masked_by_design \
                else "MASKED-BY-DESIGN ARTEFACT LEAKS PII"
            detail = f"{kind}: contains {shown}{more}"
            if missing:
                detail += f"; {_not_checked_note(missing)}"
        elif missing:
            detail = f"not checked: {_not_checked_note(missing)}"
        elif not masked_names:
            status = STATUS_NO_NAMES
            detail = ("no masking log in tree; nothing to scan for" if not logs
                      else "the masking logs give no name; nothing to scan for")
        else:
            detail = "clean: no logged original name found"
        if casefold:
            detail += ("; ignoring case also matches "
                       f"{', '.join(casefold[:5])} (check by hand)")

        findings.append(FileFinding(
            path=rel,
            artefact_type=artefact_type,
            masked_by_design=masked_by_design,
            residual_pii_found=residual,
            detail=detail,
            leaked_names=leaked,
            leaked_names_casefold=casefold,
            status=status,
        ))

    return findings, masked_names


def _unscanned(rel: str, artefact_type: str, status: str,
               detail: str) -> FileFinding:
    """Return the finding of a file the leak scan did not read.

    A masking log, a file of no audited type or an artefact that could not
    be read: never a leak, with its masking guarantee taken from its type.
    """
    return FileFinding(
        path=rel,
        artefact_type=artefact_type,
        masked_by_design=_MASKED_BY_DESIGN.get(artefact_type, False),
        residual_pii_found=False,
        detail=detail,
        status=status,
    )


def _not_checked_note(logs: list[str]) -> str:
    """Say which masking logs not read in full an artefact depends on."""
    shown = ", ".join(logs[:3]) + ("" if len(logs) <= 3
                                   else f" (+{len(logs) - 3} more)")
    if len(logs) == 1:
        return (f"the masking log {shown} was not read in full, so the "
                "names it holds were not all looked for")
    return (f"the masking logs {shown} were not read in full, so the "
            "names they hold were not all looked for")


def _log_recording(parts: tuple[str, ...]) -> str | None:
    """Return the recording a masking log belongs to, or ``None``.

    *parts* is the log's path relative to the audited tree, split into
    components. Two layouts name the recording:
    ``name_masking_logs/<recording>/<log>.csv``, as example_output keeps
    them, and ``name_masking_logs/name_replacements_<recording>.csv``, as
    transcription.save_replacement_log writes them.
    """
    lowered = [p.lower() for p in parts]
    if "name_masking_logs" not in lowered:
        return None           # the tree itself lies inside such a directory
    below = parts[len(lowered) - lowered[::-1].index("name_masking_logs"):]
    if len(below) >= 2:
        return below[0]
    match = re.fullmatch(r"name_replacements_(.+)\.csv", below[0], re.IGNORECASE)
    return match.group(1) if match else None


def _belongs_to(parts: tuple[str, ...], recording: str) -> bool:
    """Whether the artefact at *parts* is one of *recording*'s.

    It is when one of its directories is named after the recording
    (``transcripts/<recording>/transcript.txt``) or its file name starts
    with the recording's name and an underscore or full stop
    (``<recording>_transcript.txt``), case ignored. A recording whose name
    begins another's ("rec" and "rec_2") claims both, which errs towards
    reporting a file as not checked.
    """
    rec = recording.lower()
    *dirs, name = (p.lower() for p in parts)
    return rec in dirs or name.startswith((rec + "_", rec + "."))


def write_csv(findings: list[FileFinding], out_path: Path) -> None:
    """Write the per-file audit findings to *out_path* as CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "path", "type", "masked_by_design",
            "residual_pii_found", "detail", "leaked_names_casefold",
        ])
        for f in findings:
            writer.writerow([
                f.path, f.artefact_type, f.masked_by_design,
                f.residual_pii_found, f.detail,
                ";".join(f.leaked_names_casefold),
            ])


def write_json(
    findings: list[FileFinding],
    masked_names: set[str],
    out_path: Path,
) -> None:
    """Write a machine-readable summary of the audit to *out_path*.

    Besides the leak counts, the summary records the masking logs not read
    in full, the artefacts skipped as unreadable and those not checked for
    every logged name, and ``audit_complete``, false when any of these
    lists is non-empty, as the exit status of :func:`main` is then 3.
    """
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.artefact_type] = counts.get(f.artefact_type, 0) + 1
    by_status = _paths_by_status(findings)

    payload = {
        "summary": {
            "files_audited": len(findings),
            "counts_by_type": counts,
            "masked_names_recovered": sorted(masked_names),
            "n_masked_names": len(masked_names),
            "residual_pii_files": sum(1 for f in findings if f.residual_pii_found),
            "masked_artefacts_leaking": sum(
                1 for f in findings
                if f.residual_pii_found and f.masked_by_design
            ),
            "raw_artefacts_leaking": sum(
                1 for f in findings
                if f.residual_pii_found and not f.masked_by_design
            ),
            # Masked-by-design files in which a logged name appears only in
            # another case; candidates for a hand check, not counted above.
            "masked_artefacts_casefold_only": sum(
                1 for f in findings
                if f.leaked_names_casefold and f.masked_by_design
            ),
            "docx_reader_available": _HAS_DOCX,
            # What the audit could not check (see FileFinding.status).
            "n_masking_logs": counts.get(TYPE_MASKING_LOG, 0),
            "masking_logs_not_read_in_full": by_status[STATUS_LOG_INCOMPLETE],
            "skipped_files": by_status[STATUS_SKIPPED],
            "files_not_checked": by_status[STATUS_NOT_CHECKED],
            "audit_complete": audit_is_complete(findings),
        },
        "per_file": [asdict(f) for f in findings],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _paths_by_status(findings: list[FileFinding]) -> dict[str, list[str]]:
    """Return the paths of the findings with each incomplete status."""
    by_status: dict[str, list[str]] = {s: [] for s in _INCOMPLETE_STATUSES}
    for f in findings:
        if f.status in by_status:
            by_status[f.status].append(f.path)
    return by_status


def audit_is_complete(findings: list[FileFinding]) -> bool:
    """Whether every masking log was read in full and every artefact checked."""
    return not any(f.status in _INCOMPLETE_STATUSES for f in findings)


def print_summary(findings: list[FileFinding], masked_names: set[str]) -> None:
    """Print a console summary table of the audit findings.

    The lines under the table say where the names came from, which masking
    logs were not read in full and which files were skipped or not
    checked, and close with a notice when the audit is incomplete. It once
    said "No masking logs found in the tree." whenever no name was
    recovered, a tree of unreadable logs included.
    """
    print(f"\n{'─' * 78}")
    print(
        f"  {'File':<46}  {'Type':<20}  Masked  PII"
    )
    print("  " + "─" * 76)
    for f in findings:
        masked = "yes" if f.masked_by_design else "no"
        pii = "LEAK" if f.residual_pii_found else "-"
        shown = f.path if len(f.path) <= 46 else "..." + f.path[-43:]
        print(f"  {shown:<46}  {f.artefact_type:<20}  {masked:<6}  {pii}")
    print("  " + "─" * 76)

    by_status = _paths_by_status(findings)
    n_logs = sum(1 for f in findings if f.artefact_type == TYPE_MASKING_LOG)
    bad_logs = by_status[STATUS_LOG_INCOMPLETE]
    if masked_names:
        preview = ", ".join(sorted(masked_names)[:8])
        print(f"  Original names recovered from masking logs ({len(masked_names)}): "
              f"{preview}")
    elif not n_logs:
        print("  No masking logs found in the tree.")
    elif len(bad_logs) == n_logs:
        print(f"  No original name recovered: none of the {n_logs} masking "
              "log(s) could be read in full.")
    else:
        print(f"  The {n_logs} masking log(s) in the tree give no original name.")
    for label, paths in (
            ("Masking logs not read in full", bad_logs),
            ("Artefacts skipped as unreadable", by_status[STATUS_SKIPPED]),
            ("Artefacts not checked for every logged name",
             by_status[STATUS_NOT_CHECKED])):
        if paths:
            print(f"  {label}: {len(paths)}")
            for p in paths[:5]:
                print(f"    {p}")
            if len(paths) > 5:
                print(f"    (+{len(paths) - 5} more)")

    raw_leak = sum(1 for f in findings
                   if f.residual_pii_found and not f.masked_by_design)
    masked_leak = sum(1 for f in findings
                      if f.residual_pii_found and f.masked_by_design)
    print(f"  Raw artefacts containing original names:    {raw_leak}")
    print(f"  Masked artefacts leaking original names:    {masked_leak}")
    if masked_leak:
        print("  WARNING: a de-identified artefact leaked an original name.")
    if not audit_is_complete(findings):
        print("  INCOMPLETE AUDIT: the files listed above were not checked for "
              f"every logged name (exit status {EXIT_INCOMPLETE}).")
    print(f"{'─' * 78}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.audit_artefacts",
        description=(
            "Audit the residual-PII attack surface of pipeline outputs. "
            "Classifies each emitted artefact as masked or raw by design "
            "and scans for original names recovered from the masking logs."
        ),
        epilog=(
            "Exit status: 0 when every artefact was checked against every "
            "logged name (a leak is reported but does not change it); "
            f"{EXIT_NO_DIRECTORY} when --dir is not a directory; "
            f"{EXIT_INCOMPLETE} when the audit is incomplete, because a "
            "masking log could not be read in full or an artefact (a .docx "
            "without python-docx, say) could not be read. The report is "
            "written in both the 0 and the 3 case."
        ),
    )
    p.add_argument(
        "--dir", type=Path, default=_DEFAULT_DIR,
        help="Directory tree of emitted artefacts to audit (default: "
             "%(default)s). For a pipeline run, give the working directory "
             "that holds both output/ and name_masking_logs/.",
    )
    p.add_argument(
        "--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR,
        help="Destination directory for the audit CSV and JSON (default: "
             "%(default)s, where the committed audit of example_output "
             "lives; give another directory for any other tree).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Audit ``--dir`` and write the report to ``--output-dir``.

    Returns 0 when every artefact was checked, :data:`EXIT_NO_DIRECTORY`
    (2) when the directory does not exist, and :data:`EXIT_INCOMPLETE` (3)
    when a masking log was not read in full or an artefact could not be
    read; the report is written in the first and last case. Side effects:
    reads every file under the tree, writes (overwriting)
    ``artefact_audit.csv`` and ``artefact_audit.json`` and prints a summary.
    """
    args = _build_parser().parse_args(argv)

    # The summary table uses box-drawing characters; force a UTF-8 stdout so
    # the run does not fail on a legacy code-page console (e.g. Windows cp1252).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    try:
        findings, masked_names = audit_directory(args.dir)
    except FileNotFoundError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return EXIT_NO_DIRECTORY

    print(f"Audited tree: {args.dir}  ({len(findings)} files)", flush=True)
    if not _HAS_DOCX:
        print("  Note: python-docx not installed; .docx artefacts skipped.",
              flush=True)

    print_summary(findings, masked_names)

    csv_path = args.output_dir / "artefact_audit.csv"
    json_path = args.output_dir / "artefact_audit.json"
    write_csv(findings, csv_path)
    write_json(findings, masked_names, json_path)
    print(f"  report:  {csv_path}")
    print(f"  summary: {json_path}")
    if not audit_is_complete(findings):
        print("  Error: the audit is incomplete; see the files listed above.",
              file=sys.stderr)
        return EXIT_INCOMPLETE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
