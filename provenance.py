#!/usr/bin/env python3
"""
Record what produced a transcript, and make later alteration detectable.

Every artefact the workflow emits already carries a provenance block naming
the models and settings that produced it, but nothing ties the set together
or shows whether a file has changed since it was written. A researcher
returning to a transcript months later, or a reviewer receiving one, has no
way to confirm that the text in front of them is the text the pipeline
produced from the recording it names.

This module writes a run manifest beside the artefacts. The manifest lists
the files the caller passes with their SHA-256, the SHA-256 of the input
audio, and the pipeline provenance, and it carries a digest of its own
canonical form. :func:`verify_manifest` recomputes all of it and reports
any listed file that has been altered or removed, and any file beside the
manifest that shares its stem but is not listed.

What is covered is what the caller lists. ``transcription.py`` lists the
transcripts, captions and documents it wrote under ``output/transcripts``.
Two kinds of output lie outside that and are not covered: the name-masking
log (``name_masking_logs/name_replacements_<stem>.csv``, written relative
to the working directory and holding the original names), and enhanced
audio kept with ``--save-enhanced-audio``. A change to either goes
undetected by :func:`verify_manifest` (CORE-05); pass their paths
explicitly, with a *base_dir* that contains them, to cover them.

The recording a manifest names under ``input_audio`` is the file that was
transcribed. When that file was derived from another (the case study
converts an .m4a to a 16 kHz WAV first), ``source_audio`` records the
original's digest and how the transcribed file was derived, so a reader
holding the original can tie it to the transcripts (CORE-04).

Two levels of assurance are available, and the difference matters:

*Integrity* is the default and needs no key. It detects accidental
corruption, a truncated copy, an edit made in passing, and any change to
the manifest itself. It does not prove authorship, because anyone able to
edit an artefact can recompute the digests to match.

*Authenticity* is opt-in and requires a secret key, supplied through the
``TRANSCRIPTION_SIGNING_KEY`` environment variable or a key file. The
manifest then also carries an HMAC-SHA256 over its canonical form, which
cannot be recomputed without the key, so a manifest that verifies under a
key the reader holds was written by someone who held it too. The key is
never written to the manifest or printed.

Usage::

    python -m provenance verify output/transcripts/interview_manifest.json
    python -m provenance verify path/to/manifest.json --key-file signing.key
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime
from pathlib import Path

MANIFEST_SUFFIX = "_manifest.json"
_CHUNK = 1 << 16
_KEY_ENV = "TRANSCRIPTION_SIGNING_KEY"
# Bumped when the manifest layout changes in a way a verifier must know about.
MANIFEST_VERSION = 1


#: Packages whose version can change a result: the ASR and diarisation
#: stack, the scoring library, the data loader and the numerics under them.
RESULT_PACKAGES = ("torch", "torchaudio", "transformers", "pyannote.audio", "jiwer",
                   "datasets", "numpy", "scipy", "librosa", "soundfile", "gliner",
                   "huggingface_hub")


def _status_changes(porcelain_z: bytes) -> list[tuple[str, ...]]:
    """Split ``git status --porcelain -z`` output into one tuple of paths per change.

    Each entry is ``XY <path>``. A rename or copy is followed by a field of
    its own holding the source path, which belongs to the same change.
    Paths are relative to the top of the checkout and decoded as the file
    system spells them.
    """
    fields = porcelain_z.split(b"\0")
    changes = []
    i = 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if len(field) < 4:  # the empty field after the final NUL
            continue
        paths = [os.fsdecode(field[3:])]
        if (field[:1] in (b"R", b"C") or field[1:2] in (b"R", b"C")) and i < len(fields):
            paths.append(os.fsdecode(fields[i]))
            i += 1
        changes.append(tuple(paths))
    return changes


def _checkout_paths(paths, top: str) -> set[str]:
    """Return *paths* as ``git status`` names them, case-normalised for comparison.

    That is relative to the top of the checkout, with forward slashes. A
    path outside the checkout cannot be a tracked change and is dropped.
    """
    root = Path(top).resolve()
    found = set()
    for path in paths:
        try:
            relative = Path(path).resolve().relative_to(root)
        except (OSError, RuntimeError, ValueError):
            continue
        found.add(os.path.normcase(relative.as_posix()))
    return found


def git_commit(repo_dir=None, ignore=()) -> tuple[str | None, bool | None]:
    """Return ``(commit, dirty)`` for the checkout at *repo_dir*.

    *repo_dir* defaults to the directory holding this file. ``dirty`` is
    True when tracked files differ from the commit, so a result made from
    uncommitted code is visible as such. A change to one of the files in
    *ignore* does not count, and a rename counts unless both of its names
    are ignored. A writer passes the artefacts it is about to write there:
    they are the result being described, not the code or inputs that made
    it. Without this, a committed table regenerated in place recorded a
    dirty tree whenever the new table differed from the committed one, and
    on every regeneration after the first, which had rewritten the sidecar.
    Both are ``None`` when git or the checkout is unavailable; this never
    raises.
    """
    import subprocess  # noqa: PLC0415

    cwd = Path(repo_dir) if repo_dir is not None else Path(__file__).resolve().parent
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                                text=True, timeout=10, check=True).stdout.strip() or None
        # --no-optional-locks: a status call must not rewrite .git/index,
        # because array jobs may call this concurrently in one clone. -z
        # gives each path unquoted, so it can be compared with *ignore*.
        status = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain",
                                 "-z", "--untracked-files=no"], cwd=cwd,
                                capture_output=True, timeout=30, check=True).stdout
        changes = _status_changes(status)
        if ignore and changes:
            top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                                 capture_output=True, timeout=10, check=True).stdout
            skip = _checkout_paths(ignore, os.fsdecode(top.rstrip(b"\r\n")))
            changes = [paths for paths in changes
                       if not all(os.path.normcase(p) in skip for p in paths)]
    except (OSError, subprocess.SubprocessError):
        return None, None
    return commit, bool(changes)


def run_metadata(packages=RESULT_PACKAGES, repo_dir=None, ignore=()) -> dict:
    """Return what produced a result: code commit, Python and package versions.

    Written into every evaluation summary (audit finding OUTPUTS-12), so an
    artefact names the commit, whether the tree was clean, and the versions
    of the packages that can move its numbers. A package that is not
    installed is recorded as ``None``. *ignore* lists files whose changes do
    not make the tree dirty: the artefacts the caller writes (see
    :func:`git_commit`). Call it before writing them, so that the state
    recorded is the one the code ran in.

    Returns
    -------
    dict
        ``{"git_commit", "git_dirty", "python", "platform", "packages"}``.
    """
    import platform  # noqa: PLC0415
    from importlib import metadata  # noqa: PLC0415

    versions = {}
    for package in packages:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    commit, dirty = git_commit(repo_dir, ignore=ignore)
    return {"git_commit": commit, "git_dirty": dirty, "python": platform.python_version(),
            "platform": platform.platform(), "packages": versions}


def canonical_json(payload) -> bytes:
    """Return a deterministic UTF-8 serialisation of *payload*.

    Keys are sorted and separators fixed, so that two runs producing equal
    content produce byte-identical output and therefore an equal digest.
    Without this, a digest would depend on dictionary ordering and would
    differ between interpreters for no meaningful reason.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 of *data*."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    """Return the hex SHA-256 of the file at *path*, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text_file(path) -> str:
    """Return the hex SHA-256 of a text file with every CRLF read as LF.

    A committed CSV is stored with LF and checked out with CRLF on Windows,
    so its raw digest depends on the checkout. This one does not, which is
    what a record of a result's inputs needs.
    """
    return sha256_bytes(Path(path).read_bytes().replace(b"\r\n", b"\n"))


#: The packages a sidecar records: the CSV-only writers compute with numpy.
SIDECAR_PACKAGES = ("numpy",)


def sidecar_path(output) -> Path:
    """Return where :func:`write_sidecar` puts the sidecar of *output*."""
    out = Path(output)
    return out.with_name(f"{out.stem}_provenance.json")


def write_sidecar(output, *, tool, arguments, inputs, packages=SIDECAR_PACKAGES,
                  repo_dir=None, run_meta=None) -> Path:
    """Write ``<stem>_provenance.json`` beside a CSV-only artefact.

    For writers whose only output is a table, which has nowhere to hold a
    ``run_metadata`` block (audit finding OUTPUTS-12). The sidecar names the
    tool and its arguments, each input with its line-ending-independent
    digest (:func:`sha256_text_file`), the artefact's own digest, and
    :func:`run_metadata`. Output paths are left out of *arguments* by the
    caller, so a regeneration into another directory differs from the
    committed sidecar only in ``run_metadata``.

    *run_meta* is the :func:`run_metadata` the caller read before writing
    anything, recorded as given (*packages* and *repo_dir* are then
    unused). A caller writing more than one artefact must pass it: read
    here, after the first table had been written, the git state included
    that table. Without it, the state is read now, leaving the artefact and
    its sidecar out of the dirty check.

    Returns the sidecar's path. Overwrites an existing sidecar.
    """
    out = Path(output)
    sidecar = sidecar_path(out)
    if run_meta is None:
        run_meta = run_metadata(packages=packages, repo_dir=repo_dir,
                                ignore=(out, sidecar))
    payload = {
        "artefact": out.name,
        "artefact_sha256_lf": sha256_text_file(out),
        "tool": tool,
        "arguments": arguments,
        "inputs": [{"path": Path(p).as_posix(), "sha256_lf": sha256_text_file(p)}
                   for p in sorted(inputs, key=lambda p: Path(p).as_posix())],
        "run_metadata": run_meta,
    }
    with open(sidecar, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, indent=2) + "\n")
    return sidecar


class KeyFileError(ValueError):
    """An explicitly named key file could not be read or holds no key."""


def load_key(key_file=None):
    """Return the signing key as bytes, or ``None`` when none is configured.

    A key file takes precedence over the environment variable. Whitespace
    around the key is stripped, so a file written by an editor with a
    trailing newline still works.

    Parameters
    ----------
    key_file:
        Optional path to a file holding the key. When given, it must be
        readable and non-empty.

    Returns
    -------
    bytes or None
        The key, or ``None`` when no key file was named and the
        ``TRANSCRIPTION_SIGNING_KEY`` variable is unset or empty, which
        selects integrity-only mode.

    Raises
    ------
    KeyFileError
        When *key_file* is given but cannot be read or is empty. A caller who
        names a key file has asked for an authenticity check, so silently
        falling back to integrity-only mode would let a forged manifest pass
        with exit code 0 (audit finding CORE-03).
    """
    if key_file:
        try:
            raw = Path(key_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise KeyFileError(f"cannot read key file {key_file}: {exc}") from exc
        if not raw:
            raise KeyFileError(f"key file {key_file} is empty")
        return raw.encode("utf-8")
    raw = (os.environ.get(_KEY_ENV) or "").strip()
    return raw.encode("utf-8") if raw else None


def _entry(path: Path, base_dir: Path) -> dict:
    stat = path.stat()
    return {
        "path": path.relative_to(base_dir).as_posix(),
        "bytes": stat.st_size,
        "sha256": sha256_file(path),
    }


def _audio_record(path) -> dict:
    """Name, size and SHA-256 of an audio file."""
    p = Path(path)
    return {"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)}


def build_manifest(files, base_dir, provenance=None, audio_path=None,
                   source_audio=None, derivation=None) -> dict:
    """Return a manifest describing *files*.

    Parameters
    ----------
    files:
        Paths to the artefacts of one run. Any manifest file among them is
        ignored, because a manifest cannot contain its own digest.
    base_dir:
        Directory the recorded paths are relative to.
    provenance:
        Free-form block describing what produced the run (models, language,
        settings). Copied verbatim into the manifest.
    audio_path:
        The input recording, the file actually transcribed. Its digest is
        recorded under ``input_audio`` so a reader can confirm which audio
        the transcripts came from, without the audio itself being needed
        to check the transcripts.
    source_audio:
        Optional original recording from which *audio_path* was derived
        (for example the .m4a a 16 kHz WAV was converted from). Recorded
        under ``source_audio`` with its digest, so the chain from the
        published recording to the transcripts is explicit. Ignored when
        it is not an existing file.
    derivation:
        Optional free text saying how *audio_path* was made from
        *source_audio* (the conversion command); stored in
        ``source_audio["derivation"]``.

    Returns
    -------
    dict
        The manifest, with ``manifest_sha256`` over everything else. The
        keys ``input_audio`` and ``source_audio`` are present only when
        their file exists.
    """
    base = Path(base_dir)
    entries = []
    for f in sorted({Path(p) for p in files}):
        if f.name.endswith(MANIFEST_SUFFIX) or not f.is_file():
            continue
        entries.append(_entry(f, base))

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provenance": provenance or {},
        "artefacts": entries,
    }
    if audio_path and Path(audio_path).is_file():
        manifest["input_audio"] = _audio_record(audio_path)
    if source_audio and Path(source_audio).is_file():
        manifest["source_audio"] = _audio_record(source_audio)
        if derivation:
            manifest["source_audio"]["derivation"] = str(derivation)
    # A digest of everything above, so that altering any recorded digest is
    # itself detectable without re-reading the artefacts.
    manifest["manifest_sha256"] = sha256_bytes(canonical_json(manifest))
    return manifest


def sign_manifest(manifest: dict, key: bytes) -> dict:
    """Return *manifest* with an HMAC-SHA256 over its canonical form.

    The signature covers the manifest excluding the signature block itself,
    so verification can reproduce exactly the signed bytes.
    """
    body = {k: v for k, v in manifest.items() if k != "signature"}
    signed = dict(manifest)
    signed["signature"] = {
        "algorithm": "HMAC-SHA256",
        "value": hmac.new(key, canonical_json(body), hashlib.sha256).hexdigest(),
    }
    return signed


def write_manifest(files, base_dir, out_path, provenance=None,
                   audio_path=None, key=None, source_audio=None,
                   derivation=None) -> dict:
    """Build a manifest for *files* and write it to *out_path*.

    Parameters are as for :func:`build_manifest`, plus *out_path* (where the
    JSON is written, parent directories created) and *key* (optional HMAC
    key; the manifest is signed when it is given).

    Returns the manifest dictionary that was written.

    Raises
    ------
    ValueError
        When no artefact survives the filtering in :func:`build_manifest`.
        A manifest over nothing would later verify as OK while protecting
        nothing, which is what a prefix glob produced for a stem containing
        ``[...]`` (audit finding CORE-01). Nothing is written in that case.

    New callers should prefer :func:`write_run_manifest`, which takes the
    exact list of files a run wrote and refuses paths that do not exist.
    """
    manifest = build_manifest(files, base_dir, provenance, audio_path,
                              source_audio=source_audio, derivation=derivation)
    if not manifest["artefacts"]:
        raise ValueError(
            f"refusing to write {out_path}: no artefacts to record")
    if key:
        manifest = sign_manifest(manifest, key)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def write_run_manifest(artefacts, base_dir, out_path, provenance=None,
                       audio_path=None, key=None, source_audio=None,
                       derivation=None) -> dict:
    """Write a manifest over exactly the files one run wrote.

    This is the entry point the pipeline should use. Discovering a run's
    files by a filename-prefix glob (``f"{base_name}*"``) sweeps in other
    runs that share the prefix (``P1`` matches ``P10_transcript.txt``) and
    stale outputs from an earlier run of the same name, and matches nothing
    when the name contains glob metacharacters such as ``[P01]`` (audit
    finding CORE-01). Passing the paths the writers returned avoids all
    three.

    Parameters
    ----------
    artefacts:
        Iterable of paths written by this run. ``None`` entries are ignored,
        so a caller can pass optional outputs unconditionally. Duplicates are
        collapsed.
    base_dir:
        Directory the recorded paths are relative to. Every artefact must lie
        inside it.
    out_path, provenance, audio_path, key, source_audio, derivation:
        As for :func:`write_manifest`.

    Returns
    -------
    dict
        The manifest that was written to *out_path*.

    Raises
    ------
    ValueError
        When the list is empty, when a listed path is not an existing file,
        or when it lies outside *base_dir*. Nothing is written in any of
        these cases, because a manifest that silently omits a file the run
        claimed to write is a false provenance record.
    """
    base = Path(base_dir).resolve()
    paths = []
    for item in artefacts:
        if item is None:
            continue
        p = Path(item)
        if not p.is_file():
            raise ValueError(f"artefact {p} does not exist or is not a file")
        try:
            p.resolve().relative_to(base)
        except ValueError as exc:
            raise ValueError(f"artefact {p} lies outside {base_dir}") from exc
        paths.append(p.resolve())
    if not paths:
        raise ValueError(
            f"refusing to write {out_path}: no artefacts to record")
    return write_manifest(paths, base, out_path, provenance=provenance,
                          audio_path=audio_path, key=key,
                          source_audio=source_audio, derivation=derivation)


def _other_run_stems(base: Path, stem: str) -> list[str]:
    """Stems of the other runs in *base* whose names extend *stem*.

    A run is recognised by its ``<other>_manifest.json``. Only stems that
    start with *stem* can collide with its prefix match, so only those are
    returned; *stem* itself is excluded.
    """
    others = []
    for manifest in base.glob(glob.escape(stem) + "*" + MANIFEST_SUFFIX):
        other = manifest.name[: -len(MANIFEST_SUFFIX)]
        if other != stem and other.startswith(stem):
            others.append(other)
    return others


def verify_manifest(manifest_path, base_dir=None, key=None,
                    check_extra=True, require_signature=False) -> dict:
    """Check the artefacts described by a manifest against what is on disk.

    Returns a report with an ``ok`` flag and, when something is wrong, the
    specific files at fault. The checks are, in order: the manifest's own
    digest, the signature when a key is given, then each artefact's digest,
    then any unlisted file beside the manifest whose name starts with the
    manifest's stem (``<stem>_*``, but also ``<stem>.txt`` or ``<stem>
    (copy).docx``), leaving out files that another run's manifest in the
    same directory accounts for by name (``P10_*`` when verifying ``P1``).

    When *require_signature* is true, a result whose signature was not
    positively verified (unsigned manifest, or no key supplied) counts as a
    failure, and ``report["signature_required"]`` is set.
    """
    path = Path(manifest_path)
    base = Path(base_dir) if base_dir else path.parent
    report = {
        "manifest": str(path), "ok": False, "signed": False,
        "manifest_digest_ok": False, "signature_ok": None,
        "verified": [], "modified": [], "missing": [], "unlisted": [],
    }
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report["error"] = f"cannot read manifest: {exc}"
        return report

    signature = manifest.get("signature")
    report["signed"] = signature is not None

    # 1. The manifest's own digest, computed over the body that excludes the
    #    digest and any signature.
    recorded = manifest.get("manifest_sha256")
    body = {k: v for k, v in manifest.items()
            if k not in ("manifest_sha256", "signature")}
    report["manifest_digest_ok"] = bool(
        recorded and hmac.compare_digest(recorded, sha256_bytes(canonical_json(body))))

    # 2. The signature, when the reader holds a key.
    if key and signature:
        signed_body = {k: v for k, v in manifest.items() if k != "signature"}
        expected = hmac.new(
            key, canonical_json(signed_body), hashlib.sha256).hexdigest()
        report["signature_ok"] = hmac.compare_digest(
            str(signature.get("value", "")), expected)
    elif key and not signature:
        report["signature_ok"] = False

    # 3. Each recorded artefact.
    listed = set()
    for entry in manifest.get("artefacts", []):
        rel = entry.get("path", "")
        listed.add(rel)
        target = base / rel
        if not target.is_file():
            report["missing"].append(rel)
        elif sha256_file(target) != entry.get("sha256"):
            report["modified"].append(rel)
        else:
            report["verified"].append(rel)

    # 4. Files added to the run since the manifest was written. A new file is
    #    not tampering with a recorded one, but it changes what an exporter
    #    would carry away, so it is reported.
    if check_extra:
        stem = path.name[: -len(MANIFEST_SUFFIX)] if path.name.endswith(
            MANIFEST_SUFFIX) else ""
        # The input recording is recorded under ``input_audio`` (and the
        # original it was derived from under ``source_audio``) rather than
        # as an artefact, so it is accounted for and must not count as
        # unlisted when it happens to sit beside the outputs.
        audio_names = {(manifest.get(key) or {}).get("name")
                       for key in ("input_audio", "source_audio")} - {None}
        if stem:
            # Every file whose name starts with the stem, escaped so that a
            # ``[..]`` in it is not read as a character class and matches
            # nothing (audit finding CORE-01). The match is deliberately
            # broader than the ``<stem>_<suffix>`` names the pipeline writes:
            # an unmasked copy saved as ``<stem>.txt`` or as
            # ``<stem> (edited).docx`` is exactly what an exporter must not
            # carry away unnoticed (CORE-R4). Files of another run in the same directory
            # whose stem extends this one (``P1`` beside ``P10``, ``ep05``
            # beside ``ep05_v2``) are that run's to verify, so they are
            # skipped when its manifest is present.
            owners = _other_run_stems(base, stem)
            for candidate in sorted(base.glob(glob.escape(stem) + "*")):
                if not candidate.is_file() or candidate.name.endswith(MANIFEST_SUFFIX):
                    continue
                if candidate.name in audio_names:
                    continue
                if any(candidate.name.startswith(other + "_") for other in owners):
                    continue
                rel = candidate.relative_to(base).as_posix()
                if rel not in listed:
                    report["unlisted"].append(rel)

    report["ok"] = (
        report["manifest_digest_ok"]
        and not report["modified"] and not report["missing"]
        and not report["unlisted"]
        and report["signature_ok"] is not False
    )
    if require_signature:
        report["signature_required"] = True
        if report["signature_ok"] is not True:
            report["ok"] = False
    return report


def print_report(report: dict) -> None:
    """Print a human-readable summary of :func:`verify_manifest`."""
    print(f"\nManifest: {report['manifest']}")
    if report.get("error"):
        print(f"  Error: {report['error']}")
        return
    print(f"  Manifest digest: {'ok' if report['manifest_digest_ok'] else 'MISMATCH'}")
    if report["signature_ok"] is None:
        print("  Signature:       "
              + ("present, no key supplied" if report["signed"] else "unsigned")
              + (" (a verified signature was required)"
                 if report.get("signature_required") else ""))
    else:
        print(f"  Signature:       {'ok' if report['signature_ok'] else 'INVALID'}")
    print(f"  Verified:        {len(report['verified'])} artefact(s)")
    for label in ("modified", "missing", "unlisted"):
        for rel in report[label]:
            print(f"  {label.upper():<9} {rel}")
    print(f"  Result:          {'OK' if report['ok'] else 'FAILED'}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="provenance",
        description="Verify transcription artefacts against a run manifest.")
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify", help="check artefacts against a manifest")
    v.add_argument("manifest", type=Path, help="path to a *_manifest.json")
    v.add_argument("--base-dir", type=Path, default=None,
                   help="directory the recorded paths are relative to "
                        "(default: the manifest's own directory)")
    v.add_argument("--key-file", type=Path, default=None,
                   help=f"file holding the signing key (default: the "
                        f"{_KEY_ENV} environment variable, if set); "
                        f"implies --require-signature")
    v.add_argument("--require-signature", action="store_true",
                   help="fail unless the manifest carries a signature that "
                        "verifies under the supplied key")
    return p


def main(argv=None) -> int:
    """Run the ``provenance`` command line and return its exit code.

    Parameters
    ----------
    argv:
        Argument list, or ``None`` to read ``sys.argv``.

    Returns
    -------
    int
        0 when the manifest verifies, 1 when any check fails (digest
        mismatch, modified, missing or unlisted artefact, bad or required but
        absent signature), and 2 when a named key file cannot be used. Shell
        callers gate on these codes.

    Side effects: reconfigures stdout to UTF-8 and prints the report.
    """
    args = _build_parser().parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        key = load_key(args.key_file)
    except KeyFileError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    # Naming a key file is a request for an authenticity check, so an
    # unsigned manifest must not pass as integrity-only (CORE-03).
    require = args.require_signature or args.key_file is not None
    report = verify_manifest(args.manifest, args.base_dir, key,
                             require_signature=require)
    print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
