#!/usr/bin/env python3
"""Regenerate the committed artefacts that need no GPU and compare them with the committed copies.

Most of the committed results in ``output/evaluation/`` come from GPU jobs on
Oxford ARC and cannot be rebuilt on a laptop. Eleven of them can: they are
derived on the CPU from other committed files (the job ledger, the
per-utterance WER reports, the example transcripts) or from a seeded
synthetic benchmark. This script re-runs their producers into a temporary
directory and checks that every file matches the copy in the working tree.

A pass shows that the current code still produces the committed numbers. A
failure means either that a change moved a result, which must then be
re-run and documented in CHANGELOG.md, or that the environment differs
from the one recorded in requirements-lock.txt.

Run it from the repository root::

    python tools/verify_regeneration.py            # everything (~2-5 min)
    python tools/verify_regeneration.py --skip-masking

The masking benchmark dominates the run time; it imports transcription.py
but loads no model. Nothing under output/ is written. Exit status is 0 when
every compared file matches, 1 otherwise.

How files are compared: every file is first compared byte for byte. The
artefacts are text (CSV and JSON), and their line endings depend on the
checkout, not on the code: ``.gitattributes`` stores them with LF, a Windows
checkout with ``core.autocrlf=true`` writes them back with CRLF, and the csv
writers emit CRLF on every platform. So a text file whose bytes differ is
compared again with CRLF read as LF, and a match there is reported as
``IDENTICAL ... (up to line endings)``; the earlier byte-only comparison
reported a false DIFFERS for five of the nine files it then compared on any
Linux or macOS checkout (audit finding INTEG-01). A file of any other type
must match byte for byte. The comparison is with the working-tree copy, so
run it on a clean checkout.

Three further allowances, each reported by name when it is what made a file
match. A JSON file may differ in the keys that record when, where and from
which commit it was written (:data:`VOLATILE_JSON_KEYS`: ``run_metadata``,
``generated``, ``generated_at``), since those differ on every run at another
commit; everything else must agree. And ``wer_ci.csv`` may differ in the
path separator of its ``file`` column, which a copy written on Windows
before bootstrap_ci wrote forward slashes everywhere spells with
backslashes.

For ``masking_summary.json`` only, ``curated_names_sha256`` may differ when
both digests identify the current dictionary with LF or CRLF line endings.
The archived benchmark recorded the Windows checkout's raw CRLF digest;
a Linux checkout has the same entries with LF. No dictionary character,
order, field or reported measurement may differ under this allowance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMMITTED = REPO / "output" / "evaluation"


def _jobs(out: Path, skip_masking: bool) -> list[tuple[str, list[str], dict[str, Path]]]:
    """Return (name, argv, {committed file name: regenerated path}) per producer.

    The arguments are the ones recorded for the committed files: seed 42 and
    10,000 bootstrap replicates (the seed and replicate columns inside the
    interval artefacts), the committed ledger, the example transcripts, and
    for the AMI normaliser gain the arguments its provenance sidecar holds.
    """
    jobs = [
        ("speaker_cluster_sensitivity",
         ["-m", "evaluation.speaker_cluster_ci",
          "--report", "output/evaluation/wer_report.csv",
          "--baseline", "output/evaluation/sweep_reports/wer_report.csv",
          "--condition", "output/evaluation/sweep_reports/wer_report_contraction_fix.csv",
          "output/evaluation/sweep_reports/wer_report_pipeline_full.csv",
          "--bootstrap", "10000", "--seed", "42",
          "--output", str(out / "cluster" / "speaker_cluster_sensitivity.json")],
         {"speaker_cluster_sensitivity.json":
          out / "cluster" / "speaker_cluster_sensitivity.json"}),
        ("footprint",
         ["-m", "evaluation.footprint", "--ledger", "output/evaluation/arc_job_ledger.csv",
          "--output-dir", str(out / "footprint")],
         {"footprint_report.csv": out / "footprint" / "footprint_report.csv",
          "footprint_summary.json": out / "footprint" / "footprint_summary.json"}),
        ("condition_ci",
         ["-m", "evaluation.condition_ci", "--reports", "output/evaluation/sweep_reports",
          "--baseline", "raw", "--bootstrap", "10000", "--seed", "42",
          "--output", str(out / "cci" / "condition_ci.csv")],
         {"condition_ci.csv": out / "cci" / "condition_ci.csv"}),
        ("condition_ci_postfix",
         ["-m", "evaluation.condition_ci", "--reports", "output/evaluation/sweep_reports_postfix",
          "--baseline", "raw", "--bootstrap", "10000", "--seed", "42",
          "--output", str(out / "cci" / "condition_ci_postfix.csv")],
         {"condition_ci_postfix.csv": out / "cci" / "condition_ci_postfix.csv"}),
        # The gains need no bootstrap, but --output is required, so the run
        # writes the paired intervals as well. They are not committed, and
        # only the gains are compared.
        ("normaliser_gain_ami",
         ["-m", "evaluation.condition_ci",
          "--reports", "output/evaluation/sweep_reports_postfix_ami",
          "--prefix", "wer_report_ami_whisper-large-v3", "--primary-condition", "raw",
          "--baseline", "raw", "--bootstrap", "10000", "--seed", "42",
          "--output", str(out / "gain" / "condition_ci_ami.csv"),
          "--gains-output", str(out / "gain" / "normaliser_gain_ami.csv")],
         {"normaliser_gain_ami.csv": out / "gain" / "normaliser_gain_ami.csv"}),
        ("wer_ci",
         ["-m", "evaluation.bootstrap_ci",
          "--report", str(Path("output/evaluation/wer_report.csv")),
          "--bootstrap", "10000", "--seed", "42", "--output", str(out / "wer_ci" / "wer_ci.csv")],
         {"wer_ci.csv": out / "wer_ci" / "wer_ci.csv"}),
        ("artefact_audit",
         ["-m", "evaluation.audit_artefacts", "--dir", "example_output",
          "--output-dir", str(out / "audit")],
         {"artefact_audit.csv": out / "audit" / "artefact_audit.csv",
          "artefact_audit.json": out / "audit" / "artefact_audit.json"}),
    ]
    if not skip_masking:
        jobs.append(
            ("masking",
             ["-m", "evaluation.benchmark_masking", "--seed", "42",
              "--output-dir", str(out / "masking")],
             {"masking_report.csv": out / "masking" / "masking_report.csv",
              "masking_summary.json": out / "masking" / "masking_summary.json"}))
    return jobs


# Suffixes of the text artefacts whose line endings follow the checkout (see
# the module docstring). Anything else is compared byte for byte only.
TEXT_SUFFIXES = frozenset({".csv", ".json", ".txt", ".md"})


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare(produced: Path, committed: Path) -> str | None:
    """Say how *produced* matches *committed*, or return None if it does not.

    Returns ``"byte for byte"`` when the bytes are equal, ``"up to line
    endings"`` when *committed* is a text file (:data:`TEXT_SUFFIXES`) and
    the two are equal once every CRLF is read as LF, and ``None`` otherwise.
    Reads both files; writes nothing.
    """
    a, b = produced.read_bytes(), committed.read_bytes()
    if _digest(a) == _digest(b):
        return "byte for byte"
    if (committed.suffix.lower() in TEXT_SUFFIXES
            and a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")):
        return "up to line endings"
    return None


#: Keys that record when, where and from which commit a file was written,
#: not what it measured. A summary that embeds them differs on every run at
#: another commit or on another machine, so JSON files are also compared
#: with these keys removed at any depth (audit gap G5).
VOLATILE_JSON_KEYS = frozenset({"run_metadata", "generated", "generated_at"})


def _strip_volatile(value):
    """Return *value* with every :data:`VOLATILE_JSON_KEYS` key removed."""
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items()
                if k not in VOLATILE_JSON_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def same_but_volatile(produced: Path, committed: Path) -> bool:
    """Whether two JSON files agree once :data:`VOLATILE_JSON_KEYS` are removed."""
    import json

    try:
        a = json.loads(produced.read_text(encoding="utf-8"))
        b = json.loads(committed.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return _strip_volatile(a) == _strip_volatile(b)


def same_masking_but_dictionary_endings(
    produced: Path, committed: Path, dictionary: Path | None = None,
) -> bool:
    """Recognise the archived dictionary's LF/CRLF digest difference only.

    Both hashes must identify the current dictionary. A changed entry fails even
    when all benchmark measurements happen to remain unchanged. The same
    volatile provenance keys as :func:`same_but_volatile` are permitted.
    Reads the three files; writes nothing.
    """
    import json

    if produced.name != "masking_summary.json" or committed.name != produced.name:
        return False
    if dictionary is None:
        dictionary = REPO / "data" / "curated_names.csv"
    try:
        a = _strip_volatile(json.loads(produced.read_text(encoding="utf-8")))
        b = _strip_volatile(json.loads(committed.read_text(encoding="utf-8")))
        data = dictionary.read_bytes().replace(b"\r\n", b"\n")
    except (OSError, ValueError):
        return False
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    a_hash = a.pop("curated_names_sha256", None)
    b_hash = b.pop("curated_names_sha256", None)
    if not isinstance(a_hash, str) or not isinstance(b_hash, str) or a_hash == b_hash:
        return False
    allowed = {_digest(data), _digest(data.replace(b"\n", b"\r\n"))}
    return a_hash in allowed and b_hash in allowed and a == b


def _same_up_to_path_separator(a: Path, b: Path) -> bool:
    """Compare two CSVs with ``\\`` read as ``/`` in the ``file`` column.

    Until a8420df, bootstrap_ci wrote the report path as the platform
    spells it; it now writes it with forward slashes everywhere. A copy
    written on Windows before that differs from a regeneration only in the
    separator.
    """
    def rows(p: Path) -> list[dict]:
        with p.open(newline="", encoding="utf-8") as fh:
            return [{k: (v.replace("\\", "/") if k == "file" else v) for k, v in r.items()}
                    for r in csv.DictReader(fh)]
    return rows(a) == rows(b)


def main(argv: list[str] | None = None) -> int:
    """Run every producer, compare its output with the committed files, report.

    Returns 0 when every compared file matches, 1 when any differs, is
    missing, or its producer exits non-zero. Writes only to a temporary
    directory, which is removed afterwards unless ``--keep`` is given.
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-masking", action="store_true",
                    help="skip the masking benchmark, the slowest producer")
    ap.add_argument("--keep", action="store_true",
                    help="keep the regenerated files and print where they are")
    args = ap.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="verify_regen_"))
    ok = True
    for name, cmd, outputs in _jobs(tmp, args.skip_masking):
        log = tmp / f"{name}.log"
        with log.open("w", encoding="utf-8") as fh:
            rc = subprocess.run([sys.executable, *cmd], cwd=REPO, stdout=fh,
                                stderr=subprocess.STDOUT).returncode
        if rc != 0:
            print(f"FAILED    {name} (exit {rc}; log: {log})")
            ok = False
            continue
        for committed_name, produced in outputs.items():
            committed = COMMITTED / committed_name
            if not produced.exists():
                print(f"MISSING   {committed_name}")
                ok = False
            elif (how := compare(produced, committed)) is not None:
                print(f"IDENTICAL {committed_name} ({how})")
            elif (committed.suffix.lower() == ".json"
                  and same_but_volatile(produced, committed)):
                print(f"IDENTICAL {committed_name} (except "
                      f"{', '.join(sorted(VOLATILE_JSON_KEYS))})")
            elif (committed_name == "masking_summary.json"
                  and same_masking_but_dictionary_endings(produced, committed)):
                print(f"IDENTICAL {committed_name} (dictionary LF/CRLF digest; "
                      "except volatile provenance keys)")
            elif (committed_name == "wer_ci.csv"
                  and _same_up_to_path_separator(produced, committed)):
                print(f"IDENTICAL {committed_name} (up to the path separator in the file column)")
            else:
                print(f"DIFFERS   {committed_name}")
                ok = False
    if args.keep:
        print(f"regenerated files kept in {tmp}")
    else:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
