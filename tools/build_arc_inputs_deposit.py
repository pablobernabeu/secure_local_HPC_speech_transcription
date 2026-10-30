"""Build the public deposit of the multilingual and cross-hardware inputs.

Three committed results rest on files that stayed on Oxford ARC: the
multilingual FLEURS table (``fleurs_multilingual_summary.json``), the
Spanish V100 control (``fleurs_es419_v100_control.json``) and the
cross-hardware determinism comparison
(``determinism/determinism_cross_accelerator.json``).
``output/evaluation/arc_inputs_manifest.json`` lists the files their
producers read, and the job logs that name the cards of the multilingual
arms whose summaries record none, with each file's size and SHA-256. This
writes them to one ZIP archive, the second bundle of the data deposit
beside the English sweep's inputs (``tools/build_input_deposit.py``):

    inputs/evaluation/<path>   from $DATA/speech_transcription_env/output/evaluation/<path>
    inputs/clone/logs/<name>   from logs/ in the ARC clone $HOME/paper_speech_transcription
    arc_inputs_manifest.json
    SHA256SUMS                 one ``<sha256>  inputs/<path>`` line per file
    README.md                  contents, provenance, licences and the rebuild commands

The archive follows the sweep deposit's conventions, whose member helper
it uses: members in name order, a fixed timestamp (the manifest's recovery
date), zlib's default level, and a detached JSON record beside the archive
naming the Python and zlib versions that deflated it, since the archive's
digest reproduces only under the same deflate implementation.

Every file is checked against the manifest before anything is written, and
the build stops at the first mismatch or at a file the manifest does not
name. Most files are deposited byte for byte, so the digests that the
committed results record still identify them. A file whose entry is
marked ``sanitised`` is deposited with the deployment's paths and account
names replaced by the placeholders of the manifest's ``sanitisation``
table. Its entry gives ``sha256``, of the bytes deposited, beside
``original_sha256``, of the original on ARC, which is the digest a
committed result records where one does, and counts the replacements of
each placeholder. ``--inputs`` may hold either form. Deposited bytes are
taken as they are, so the archive can be rebuilt from its own unpacked
``inputs/``. An original is sanitised with the replacements in
``--identifiers``, a JSON list of ``[private string, placeholder]`` pairs
applied in order, which stays outside the repository because it names the
deployment; the result must have the manifest's digest and counts.

Usage:
    python tools/build_arc_inputs_deposit.py \\
        --inputs <directory the files were copied into from ARC> \\
        --identifiers <private replacements, outside the repository> \\
        --output <directory outside the repository>/multilingual_hardware_inputs.zip
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import sys
import zipfile
import zlib
from pathlib import Path

from build_input_deposit import _member, _sha256

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "output" / "evaluation" / "arc_inputs_manifest.json"

#: Where the README's commands expect the archive unpacked, relative to the
#: root of a checkout of the release.
UNPACKED = "build/arc_inputs"

README = """\
# Inputs of the multilingual and cross-hardware results

This archive holds the {n_files} files behind three results of the study
*Defensive Transcription on the Desk and on the Cluster*: the
multilingual FLEURS comparison, the Spanish V100 control of its fourth
arm and the comparison of one decode across hardware. Oxford ARC jobs
wrote them; they were copied from the cluster and checked against the
digests `sha256sum` printed there on {recovered}. Of the {n_files},
{n_exact} are deposited byte for byte and {n_sanitised} as sanitised copies
(see Sanitisation), {total:,} bytes in all. The workflow's repository
commits the three results and the code that builds them{software}, but
not these inputs.

## Layout

- `inputs/evaluation/`: files from the workflow's evaluation directory on
  ARC, `$DATA/speech_transcription_env/output/evaluation/`, at their paths
  under it. The multilingual comparison's third arm wrote into that
  directory itself, so its summaries sit at the top of
  `inputs/evaluation/`.
- `inputs/clone/logs/`: job logs from `logs/` in the ARC clone
  `$HOME/paper_speech_transcription`.
- `arc_inputs_manifest.json`: the repository's committed receipt for these
  files: each one's size and SHA-256 as deposited and the digest of the
  original on ARC, the result it backs, and the jobs and code commits that
  wrote it.
- `SHA256SUMS`: the digests of the files as deposited, which
  `sha256sum -c SHA256SUMS` checks.

{files}## Use

With the workflow's source at release {release} or later and this archive
unpacked into its `{unpacked}/`, so that the files sit in
`{unpacked}/inputs/`, each command below rebuilds a committed result into
`my_check/`. Compare it with the committed file.

{commands}## Sanitisation

{sanitisation}

| On ARC | In this archive |
| --- | --- |
{table}

The manifest marks each sanitised file, gives the size and SHA-256 of its
original on ARC (`original_bytes`, `original_sha256`) beside those of the
copy deposited (`bytes`, `sha256`), and counts the replacements of each
placeholder (`substitutions`). Nothing else in these files changed.

## Licences and attribution

The reference text and the audio behind the scores come from public
corpora and keep their terms:

{notices}

The FLEURS summaries keep per-utterance error rates and word alignment
counts, not text. The AMI hypothesis dumps hold each utterance's
reference text and the hypothesis Whisper Large v3 generated for it.
The hypotheses are generated derivatives, they contain recognition
errors, and they are not corrected transcripts. The summaries, reports,
dumps, logs and environment records are released under CC BY 4.0. The
reference text is that of the published corpora, and this archive adds
no other personal information.
"""


def _section(artefact: str, entry: dict, files: list[dict]) -> str:
    """The README's list of the files behind one committed result.

    The summaries, dumps, reports and records come first, in path order,
    and the job logs after them.
    """
    lines = [f"### Files behind `{artefact}`", "", entry["description"], ""]
    for f in sorted(files, key=lambda f: (f["path"].startswith("clone/"), f["path"])):
        if artefact in f["backs"]:
            mark = " (sanitised copy)" if f.get("sanitised") else ""
            lines.append(f"- `inputs/{f['path']}`{mark}: {f['role']}")
    return "\n".join(lines) + "\n\n"


def _command(artefact: str, entry: dict, deposited: set[str]) -> str:
    """Render one result's rebuild command from its manifest entry.

    An argument naming an input as ``@<path>`` is pointed at the unpacked
    archive.

    Raises:
        ValueError: an ``@<path>`` names neither a deposited file nor a
            directory holding one.
    """
    lines = [f"python -m {entry['module']}"]
    for arg in entry["arguments"]:
        head, at, path = arg.partition("@")
        if at:
            if path not in deposited and not any(
                    p.startswith(path.rstrip("/") + "/") for p in deposited):
                raise ValueError(f"{artefact}: the argument {arg!r} names no file "
                                 "of the manifest")
            arg = f"{head}{UNPACKED}/inputs/{path}"
        lines.append(arg)
    body = " \\\n        ".join(lines)
    return f"### `{artefact}`\n\n    {body}\n\n{entry['reproduces']}\n\n"


def sanitise(data: bytes, replacements) -> tuple[bytes, dict[str, int]]:
    """Replace each private string with its placeholder, in the order given.

    Returns the new bytes and the number of replacements per placeholder,
    in the order the placeholders first occur among *replacements*, with
    those that replaced nothing left out.
    """
    counts: dict[str, int] = {}
    for private, placeholder in replacements:
        needle = private.encode("utf-8")
        counts[placeholder] = counts.get(placeholder, 0) + data.count(needle)
        data = data.replace(needle, placeholder.encode("utf-8"))
    return data, {k: n for k, n in counts.items() if n}


def _read_identifiers(path: Path | None, allowed) -> list[tuple[str, str]] | None:
    """Read ``--identifiers``: ``[private string, placeholder]`` pairs.

    Raises:
        ValueError: the file is not such a list, a private string is empty,
            or a placeholder is not one of the manifest's sanitisation table.
    """
    if path is None:
        return None
    pairs = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(pairs, list) or not all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) for s in p)
            for p in pairs):
        raise ValueError(f"{path}: expected a list of [private string, placeholder] pairs")
    for private, placeholder in pairs:
        if not private or placeholder not in allowed:
            raise ValueError(f"{path}: {placeholder!r} is not one of the placeholders "
                             f"{sorted(allowed)}, or a private string is empty")
    return [tuple(p) for p in pairs]


def _deposited_bytes(entry: dict, data: bytes, replacements) -> bytes:
    """Return the bytes to deposit for *entry*, read from *data*.

    Raises:
        ValueError: *data* is neither the deposited form nor, for a
            sanitised entry, an original that sanitises to it with the
            manifest's counts.
    """
    digest = hashlib.sha256(data).hexdigest()
    if len(data) == entry["bytes"] and digest == entry["sha256"]:
        return data
    if not entry.get("sanitised"):
        raise ValueError(f"{entry['path']} differs from its manifest entry")
    if digest != entry["original_sha256"] or len(data) != entry["original_bytes"]:
        raise ValueError(f"{entry['path']} is neither the deposited file nor the ARC "
                         "original its manifest entry names")
    if replacements is None:
        raise ValueError(f"{entry['path']} is the ARC original; --identifiers is "
                         "needed to sanitise it")
    clean, counts = sanitise(data, replacements)
    if (len(clean) != entry["bytes"] or hashlib.sha256(clean).hexdigest() != entry["sha256"]
            or counts != entry["substitutions"]):
        raise ValueError(f"{entry['path']} sanitised does not give its manifest digest "
                         "and counts")
    return clean


def build(inputs: Path, output: Path, manifest_path: Path = MANIFEST,
          identifiers: Path | None = None, software_doi: str | None = None) -> dict:
    """Verify the inputs against the manifest and write the archive.

    *identifiers* is the private replacements file (see the module
    docstring), needed only when *inputs* holds an ARC original of a
    sanitised file; when given, no deposited file may still hold one of
    its private strings. *software_doi* names the archived software
    release in the README. Returns the detached record of the archive,
    also written beside it as ``<archive>.json``.

    Raises:
        ValueError: *inputs* is not a directory; a listed file is missing
            or differs from the manifest; a file there is not listed; a
            deposited file still holds a private string; or a command in
            the manifest names a file it does not list.
    """
    # A Windows checkout can hold the manifest with CRLF endings. The
    # committed blob has LF, so the deposit carries that form wherever it
    # is built.
    manifest_bytes = manifest_path.read_bytes().replace(b"\r\n", b"\n")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    listed = {f["path"]: f for f in manifest["files"]}
    table = manifest["sanitisation"]["table"]
    replacements = _read_identifiers(identifiers, {row["placeholder"] for row in table})
    if not inputs.is_dir():
        raise ValueError(f"input directory not found: {inputs}")
    present = {p.relative_to(inputs).as_posix() for p in inputs.rglob("*") if p.is_file()}
    stray = present - set(listed)
    if stray:
        raise ValueError(f"files not in the manifest: {sorted(stray)}")

    deposit: dict[str, bytes] = {}
    for path, entry in sorted(listed.items()):
        source = inputs / path
        if not source.is_file():
            raise ValueError(f"missing input: {path}")
        data = _deposited_bytes(entry, source.read_bytes(), replacements)
        for private, _ in replacements or ():
            if private.encode("utf-8") in data:
                raise ValueError(f"{path} still holds a private string")
        deposit[path] = data

    files = sorted(listed.values(), key=lambda f: f["path"])
    total = sum(f["bytes"] for f in files)
    if total != manifest["total_bytes"] or len(files) != manifest["files_deposited"]:
        raise ValueError("the manifest's totals do not match its file list")
    n_sanitised = sum(bool(f.get("sanitised")) for f in files)
    notices = "\n".join(f"- {n['corpus']}: {n['data_licence']} ({n['source']})"
                        + (f". {n['detail']}" if n.get("detail") else "")
                        for n in manifest["corpus_notices"])
    artefacts = manifest["artefacts"]
    readme = README.format(
        n_files=len(files), recovered=manifest["recovered_and_verified_on"], total=total,
        n_exact=len(files) - n_sanitised, n_sanitised=n_sanitised,
        software=(f", archived as https://doi.org/{software_doi}" if software_doi else ""),
        release=manifest["release"], unpacked=UNPACKED,
        files="".join(_section(name, artefacts[name], files) for name in artefacts),
        commands="".join(_command(name, artefacts[name], set(listed)) for name in artefacts),
        sanitisation=manifest["sanitisation"]["readme"],
        table="\n".join(f"| {row['on_arc']} | `{row['placeholder']}` |" for row in table),
        notices=notices)
    sums = "".join(f"{f['sha256']}  inputs/{f['path']}\n" for f in files)

    when = dt.date.fromisoformat(manifest["recovered_and_verified_on"]).timetuple()[:6]
    output.parent.mkdir(parents=True, exist_ok=True)
    # Each member is written through its own ZipInfo, whose compression
    # level is unset, so zlib's default level (6) applies, as in the sweep
    # deposit.
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(_member("README.md", when), readme)
        archive.writestr(_member("SHA256SUMS", when), sums)
        archive.writestr(_member("arc_inputs_manifest.json", when), manifest_bytes)
        for path in sorted(deposit):
            archive.writestr(_member(f"inputs/{path}", when), deposit[path])

    record = {
        "archive": output.name,
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "files": len(files),
        "input_bytes": total,
        "sanitised_files": n_sanitised,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        # As in the sweep deposit: the headers' zlib version, the library
        # that deflated the archive, and zlib-ng's where CPython uses it.
        "built_with": {"python": platform.python_version(),
                       "zlib": zlib.ZLIB_VERSION,
                       "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
                       "zlib_ng": getattr(zlib, "ZLIBNG_VERSION", None)},
    }
    output.with_name(output.name + ".json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main(argv=None) -> int:
    """Build the deposit from the command line and print its record.

    *argv* replaces ``sys.argv[1:]``. Returns 0 once the archive and its
    JSON record are written, and 2, with the reason on stderr, when
    :func:`build` refuses the inputs or a file cannot be read or written.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--inputs", type=Path, required=True,
                        help="directory holding the files at the manifest's paths")
    parser.add_argument("--output", type=Path, required=True,
                        help="the ZIP archive to write")
    parser.add_argument("--manifest", type=Path, default=MANIFEST,
                        help="receipt to check against (default: the committed one)")
    parser.add_argument("--identifiers", type=Path, default=None, metavar="JSON",
                        help="private [string, placeholder] pairs that sanitise an "
                             "ARC original; keep it outside the repository")
    parser.add_argument("--software-doi", default=None, metavar="DOI",
                        help="DOI of the archived software release, named in the README")
    args = parser.parse_args(argv)
    try:
        record = build(args.inputs, args.output, args.manifest, args.identifiers,
                       args.software_doi)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
