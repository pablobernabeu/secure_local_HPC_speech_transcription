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

The analysis is pure text and CSV processing. ``.docx`` artefacts are
read through ``python-docx`` when it is importable and skipped gracefully
otherwise; no optional reader failure ever crashes the audit.

Usage::

    python -m evaluation.audit_artefacts
    python -m evaluation.audit_artefacts --dir example_output
    python -m evaluation.audit_artefacts --dir output --output-dir output/evaluation

Outputs
-------
``output/evaluation/artefact_audit.csv``
    One row per audited file: relative path, artefact type, whether the
    type is masked by design, whether residual PII was found, and a short
    human-readable detail string.

``output/evaluation/artefact_audit.json``
    Machine-readable summary: counts by type, the set of original names
    recovered from the masking logs, and the per-file findings.
"""

from __future__ import annotations

import argparse
import csv
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
    # The masking log deliberately stores the original names; it is not a
    # de-identified artefact and is excluded from the leak scan as a target.
    TYPE_MASKING_LOG: False,
    TYPE_OTHER: False,
}

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
    """

    path: str
    artefact_type: str
    masked_by_design: bool
    residual_pii_found: bool
    detail: str
    leaked_names: list[str] = field(default_factory=list)
    leaked_names_casefold: list[str] = field(default_factory=list)


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
        as masking logs regardless of their stem.  A ``.json`` file is a
        transcript when its payload is an object with a ``segments`` or
        ``text`` field, or its name contains ``transcript``; it is the
        redacted set when the payload carries
        ``"redacted": true``, and raw otherwise.  Any other JSON (a
        summary, a manifest) is ``other``.  A JSON that cannot be parsed is
        kept as raw, so an unreadable file is still scanned as text rather
        than waved through.  A ``.vtt`` is redacted when its stem ends in
        ``_redacted``, the pipeline's naming, since captions carry no flag.

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
        skipped: a title is not a name.
    """
    names: set[str] = set()
    try:
        with open(log_path, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or _LOG_ORIGINAL_COLUMN not in reader.fieldnames:
                return names
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
                if len(original) > 1:
                    names.add(original)
    except (OSError, UnicodeDecodeError, csv.Error):
        return names
    return names


def _read_text_file(path: Path) -> str:
    """Return the decoded text of a plain-text artefact, or ``""`` on error."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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

    # First pass: recover the union of original names from the masking logs.
    masked_names: set[str] = set()
    for file_path in files:
        if classify_artefact(file_path) == TYPE_MASKING_LOG:
            masked_names |= extract_masked_names(file_path)

    # Second pass: classify and scan each artefact.
    findings: list[FileFinding] = []
    for file_path in files:
        artefact_type = classify_artefact(file_path)
        masked_by_design = _MASKED_BY_DESIGN.get(artefact_type, False)
        rel = file_path.relative_to(path).as_posix()

        if artefact_type == TYPE_MASKING_LOG:
            originals = extract_masked_names(file_path)
            detail = (
                f"masking log; stores {len(originals)} original name(s) "
                "by design (expected, not a leak)"
            )
            findings.append(FileFinding(
                path=rel,
                artefact_type=artefact_type,
                masked_by_design=False,
                residual_pii_found=False,
                detail=detail,
            ))
            continue

        # Read artefact text for the leak scan.
        if artefact_type == TYPE_TRANSCRIPT_DOCX:
            text = _read_docx_text(file_path)
            if text is None:
                reason = ("python-docx not installed"
                          if not _HAS_DOCX else "unreadable .docx")
                findings.append(FileFinding(
                    path=rel,
                    artefact_type=artefact_type,
                    masked_by_design=masked_by_design,
                    residual_pii_found=False,
                    detail=f"skipped: {reason}",
                ))
                continue
        elif artefact_type == TYPE_OTHER:
            findings.append(FileFinding(
                path=rel,
                artefact_type=artefact_type,
                masked_by_design=masked_by_design,
                residual_pii_found=False,
                detail="not an audited artefact type",
            ))
            continue
        else:
            text = _read_text_file(file_path)

        leaked = _find_verbatim_names(text, masked_names) if masked_names else []
        casefold = (_find_casefold_only_names(text, masked_names)
                    if masked_names else [])
        residual = bool(leaked)
        if not masked_names:
            detail = "no masking log in tree; nothing to scan for"
        elif residual:
            shown = ", ".join(leaked[:5])
            more = "" if len(leaked) <= 5 else f" (+{len(leaked) - 5} more)"
            kind = "raw artefact, unmasked by design" if not masked_by_design \
                else "MASKED-BY-DESIGN ARTEFACT LEAKS PII"
            detail = f"{kind}: contains {shown}{more}"
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
        ))

    return findings, masked_names


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
    """Write a machine-readable summary of the audit to *out_path*."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.artefact_type] = counts.get(f.artefact_type, 0) + 1

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
        },
        "per_file": [asdict(f) for f in findings],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def print_summary(findings: list[FileFinding], masked_names: set[str]) -> None:
    """Print a console summary table of the audit findings."""
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

    if masked_names:
        preview = ", ".join(sorted(masked_names)[:8])
        print(f"  Original names recovered from masking logs ({len(masked_names)}): "
              f"{preview}")
    else:
        print("  No masking logs found in the tree.")

    raw_leak = sum(1 for f in findings
                   if f.residual_pii_found and not f.masked_by_design)
    masked_leak = sum(1 for f in findings
                      if f.residual_pii_found and f.masked_by_design)
    print(f"  Raw artefacts containing original names:    {raw_leak}")
    print(f"  Masked artefacts leaking original names:    {masked_leak}")
    if masked_leak:
        print("  WARNING: a de-identified artefact leaked an original name.")
    print(f"{'─' * 78}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.audit_artefacts",
        description=(
            "Audit the residual-PII attack surface of pipeline outputs. "
            "Classifies each emitted artefact as masked or raw by design "
            "and scans for original names recovered from the masking logs."
        ),
    )
    p.add_argument(
        "--dir", type=Path, default=_DEFAULT_DIR,
        help="Directory tree of emitted artefacts to audit "
             "(default: %(default)s).",
    )
    p.add_argument(
        "--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR,
        help="Destination directory for the audit CSV and JSON "
             "(default: %(default)s).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Audit ``--dir`` and write the report to ``--output-dir``.

    Returns 0 on success and 2 when the directory does not exist. Side
    effects: reads every file under the tree, writes (overwriting)
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
        return 2

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
