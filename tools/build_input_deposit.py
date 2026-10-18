"""Build the public deposit of the English sweep's recovered inputs.

The 270 files that ``output/evaluation/sweep_input_manifest.json`` lists,
the 255 condition summaries and 15 hypothesis dumps of ARC jobs 8917985 to
8917987, back the committed grid and the scorer-sensitivity and decode
provenance reports, but are too large and too corpus-laden for the
repository. This writes them to one ZIP archive for a separate data
deposit:

    inputs/<name>          each file byte for byte, as recovered from ARC
    sweep_input_manifest.json
    SHA256SUMS             one ``<sha256>  inputs/<name>`` line per file
    README.md              contents, provenance, licences and use

Every file is checked against the manifest's size and SHA-256 before it
is written, and the build stops at the first mismatch or at a file the
manifest does not list. The files are not transformed, so the digests that
``sweep_aggregate.json`` and ``scorer_sensitivity.json`` record still
identify them. Members are written in name order with a fixed timestamp
(the manifest's recovery date), so the same inputs always give the same
archive bytes and the same archive digest, which a detached JSON record
beside the archive gives.

The decoder commit is not in the public repository, which holds releases
only, so the deposit also carries a ``git archive`` of that commit as a
second file. ``--decoder-source`` checks that the ZIP's comment, where
``git archive`` writes the commit, is the manifest's decoder commit, and
the README describes the file and gives its digest.

Usage:
    git -c core.autocrlf=false -c core.eol=lf archive --format=zip \\
        -o <directory>/decoder_source_6f9bf56.zip 6f9bf56
    python tools/build_input_deposit.py \\
        --inputs build/recovered_arc_sweep/inputs \\
        --output <directory outside the repository>/sweep_inputs.zip \\
        --software-doi 10.5281/zenodo.<the software release> \\
        --decoder-source <directory>/decoder_source_6f9bf56.zip
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "output" / "evaluation" / "sweep_input_manifest.json"

README = """\
# Recovered inputs of the English condition sweep

This archive holds the {n_files} files behind the English condition sweep
of the study *Defensive Transcription on the Desk and on the Cluster*:
the {n_summaries} per-condition summaries and the {n_dumps} hypothesis dumps
written by Oxford ARC jobs {jobs} at decoder commit `{commit}` of the
workflow's repository{software}. The files are byte for byte those
recovered from the cluster and verified on {recovered}, {total:,} bytes in
all.

## Contents

- `inputs/wer_summary_<suite>_<model>[_<condition>].json`: one summary per
  corpus, model and post-processing condition, with its benchmark settings,
  scores, per-file results and run metadata.
- `inputs/wer_hypotheses_<suite>_<model>.csv`: one dump per corpus and
  model, giving each utterance's raw and condition-transformed reference
  and hypothesis under every condition, with its word error rate.
- `sweep_input_manifest.json`: the repository's committed inventory of these
  files, with each one's size and SHA-256.
- `SHA256SUMS`: the same digests, which `sha256sum -c SHA256SUMS` checks.

The corpora are {suites}; the models are {models}; the conditions are the
{n_conditions} that the manifest's `grid` block lists.

## Use

With the workflow's source at release 2.0.0 or later and this archive
unpacked into its `build/recovered_arc_sweep/`, so that the files sit in
`build/recovered_arc_sweep/inputs/`:

    python -m evaluation.scorer_sensitivity \\
        --inputs build/recovered_arc_sweep/inputs \\
        --aggregate output/evaluation/sweep_aggregate.json \\
        --input-manifest output/evaluation/sweep_input_manifest.json \\
        --output-csv my_check/scorer_sensitivity.csv \\
        --output-json my_check/scorer_sensitivity.json

    python tools/extract_sweep_decode_provenance.py \\
        --inputs build/recovered_arc_sweep/inputs \\
        --aggregate output/evaluation/sweep_aggregate.json \\
        --input-manifest output/evaluation/sweep_input_manifest.json \\
        --output my_check/sweep_decode_provenance.json

The summaries' digests are those recorded in the repository's
`output/evaluation/sweep_aggregate.json`, whose rows
`python -m evaluation.sweep_aggregate` rebuilds from them.

{decoder_source}## Licences and attribution

The reference text comes from public corpora and keeps their terms:
{notices}
The summaries, and the hypotheses that Whisper models generated and the
workflow's conditions transformed, are released under CC BY 4.0. The
hypotheses contain recognition errors and are not corrected transcripts.
The text is that of the published corpora; this archive adds no other
personal information, and its files record no deployment paths or account
names.
"""

DECODER_SOURCE = """\
## Historical decoder source

`{file}`, deposited beside this archive, is the workflow's source tree at
decoder commit `{commit}`, as `git archive` wrote it. Its ZIP comment is
that commit identifier, and its SHA-256 is `{sha256}`. It is the code that
wrote these files, kept here because the public repository holds the
releases, not this commit. It predates later repairs, among them the
isolation of its tests from shared model caches, so do not run its tests
against a shared model cache; check or rebuild the results with release
2.0.0 or later. Like the release, its run records name the ARC project
paths and account that the jobs used, which the files in this archive do
not. It is licensed as release 2.0.0 is: the code under MIT,
and `manuscript/`, `docs/`, `output/` and `example_output/` under CC BY 4.0.

"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _member(name: str, when: tuple[int, ...]) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=when)
    info.compress_type = zipfile.ZIP_DEFLATED
    # ZipInfo records the building platform (0 on Windows, 3 elsewhere);
    # fixing it keeps the archive's bytes the same wherever it is built.
    info.create_system = 3
    info.external_attr = 0o644 << 16
    return info


def build(inputs: Path, output: Path, manifest_path: Path = MANIFEST,
          software_doi: str | None = None,
          decoder_source: Path | None = None) -> dict:
    """Verify the inputs against the manifest and write the archive.

    *software_doi* names the archived software release in the README, which
    otherwise names no location: the repository itself may not be public.
    *decoder_source* is a ``git archive`` ZIP of the decoder commit, which
    the README then describes. Returns the detached record of the archive
    (also written beside it as ``<archive>.json``).

    Raises:
        ValueError: a listed file is missing or differs from the manifest,
            the input directory holds a file the manifest does not list, or
            the decoder source is not an archive of the decoder commit.
    """
    # A Windows checkout can hold the manifest with CRLF endings. The
    # committed blob has LF, so the deposit carries that form wherever it
    # is built.
    manifest_bytes = manifest_path.read_bytes().replace(b"\r\n", b"\n")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    listed = {entry["name"]: entry for entry in manifest["files"]}
    present = {p.name for p in inputs.iterdir() if p.is_file()}
    if present - set(listed):
        raise ValueError(f"files not in the manifest: {sorted(present - set(listed))}")
    for name, entry in sorted(listed.items()):
        path = inputs / name
        if not path.is_file():
            raise ValueError(f"missing input: {name}")
        if path.stat().st_size != entry["bytes"] or _sha256(path) != entry["sha256"]:
            raise ValueError(f"{name} differs from its manifest entry")

    source = None
    if decoder_source is not None:
        with zipfile.ZipFile(decoder_source) as snapshot:
            comment = snapshot.comment.decode("ascii", "replace")
        if comment != manifest["decoder_commit"]:
            raise ValueError(f"{decoder_source.name} is not an archive of "
                             f"{manifest['decoder_commit']} (its comment is {comment!r})")
        source = {"file": decoder_source.name, "bytes": decoder_source.stat().st_size,
                  "sha256": _sha256(decoder_source)}

    when =dt.date.fromisoformat(manifest["recovered_and_verified_on"]).timetuple()[:6]
    grid = manifest["grid"]
    notices = "\n".join(
        f"- {n['corpus']}: {n['data_licence']} ({n['source']})"
        + (f". {n['distinction']}" if n.get("distinction") else "")
        for n in manifest["corpus_notices"])
    readme = README.format(
        n_files=len(listed), n_summaries=manifest["summaries"],
        n_dumps=manifest["hypothesis_dumps"],
        jobs=manifest["source"].split("jobs ", 1)[-1],
        commit=manifest["decoder_commit"],
        software=(f", archived as https://doi.org/{software_doi}"
                  if software_doi else ""),
        recovered=manifest["recovered_and_verified_on"], total=manifest["total_bytes"],
        suites=", ".join(grid["suites"]), models=", ".join(grid["models"]),
        n_conditions=len(grid["conditions"]), notices=notices,
        decoder_source=(DECODER_SOURCE.format(commit=manifest["decoder_commit"], **source)
                        if source else ""))
    sums = "".join(f"{listed[name]['sha256']}  inputs/{name}\n" for name in sorted(listed))

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compresslevel=9) as archive:
        archive.writestr(_member("README.md", when), readme)
        archive.writestr(_member("SHA256SUMS", when), sums)
        archive.writestr(_member("sweep_input_manifest.json", when), manifest_bytes)
        for name in sorted(listed):
            with (inputs / name).open("rb") as src, \
                    archive.open(_member(f"inputs/{name}", when), "w") as dst:
                for block in iter(lambda: src.read(1 << 20), b""):
                    dst.write(block)

    record = {
        "archive": output.name,
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "files": len(listed),
        "input_bytes": manifest["total_bytes"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "decoder_commit": manifest["decoder_commit"],
        **({"decoder_source": source} if source else {}),
    }
    output.with_name(output.name + ".json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--inputs", type=Path, required=True,
                        help="directory holding the 270 recovered files")
    parser.add_argument("--output", type=Path, required=True,
                        help="the ZIP archive to write")
    parser.add_argument("--manifest", type=Path, default=MANIFEST,
                        help="inventory to check against (default: the committed one)")
    parser.add_argument("--software-doi", default=None, metavar="DOI",
                        help="DOI of the archived software release, named in the README")
    parser.add_argument("--decoder-source", type=Path, default=None, metavar="ZIP",
                        help="git archive ZIP of the decoder commit, deposited beside the archive")
    args = parser.parse_args(argv)
    try:
        record = build(args.inputs, args.output, args.manifest, args.software_doi,
                       args.decoder_source)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
