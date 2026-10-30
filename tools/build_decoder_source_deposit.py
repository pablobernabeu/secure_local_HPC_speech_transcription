"""Build the sanitised source archive of a commit for the data deposit.

The data deposit of the English sweep also holds the workflow's source at
the decoder commit, ``6f9bf56``, as ``git archive`` wrote it, because the
public repository holds releases, not that commit. Its run records,
scripts and result files name the Oxford ARC user, the two project
accounts and the paths that hold them, and two of its files name other
projects' jobs on the shared account. On 30 October 2026 the author
decided to remove those identifiers from release 2.1.1 and its deposits
(docs/privacy_review.md). This writes the sanitised copy:

1. ``git archive --format=zip`` of the commit, taken into memory, with
   ``core.autocrlf`` off and ``core.eol=lf`` as the deposited original
   was made (``--expect-source`` checks the result against that file);
2. in every text member, UTF-8 without a NUL byte, plain string
   replacements in a fixed order: the user's data directory under either
   project becomes ``$DATA``, the home directory ``$HOME``, the user name
   ``<user>``, and the two accounts ``<project-a>`` and ``<project-b>``,
   followed by any ``--replace OLD=NEW`` given (other projects' job
   names). Binary members are left as they are, and one that contains an
   identifier is reported;
3. a ZIP archive with the members in name order, every timestamp the
   commit's time, zlib's default compression level and the full commit
   identifier as its comment, as ``git archive`` writes it, which
   ``tools/build_input_deposit.py --decoder-source`` checks against the
   manifest's decoder commit. The same commit and the same
   replacements give the same bytes under the same deflate
   implementation (see tools/build_input_deposit.py). Its root also holds
   ``SANITISED.md``, which gives the substitutions and, for every changed
   member, its path and the git blob id of its original content;
4. a detached JSON record beside the archive, ``<archive>.json``.

The identifiers are arguments, not constants, so that neither this
script nor its tests carry them. ``SANITISED.md`` and the record describe
each original by its role and give only the replacements. The finished
archive is read back and every member scanned, without regard to case,
for each original string, inside any ZIP member as well (a Word document
is one), and the record lists what the scan found.

Usage:
    python tools/build_decoder_source_deposit.py --commit 6f9bf56 \\
        --user <ARC user> --project-a <first account> \\
        --project-b <second account> \\
        [--replace "<other project's job name>=<neutral name>" ...] \\
        --expect-source <directory>/decoder_source_6f9bf56.zip \\
        --output <deposit directory>/decoder_source_6f9bf56.zip

The archive keeps the original's file name, so that the data record
holds one decoder-source file. SANITISED.md and the record's
``sanitised`` field say which copy it is.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import platform
import shutil
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NOTE = "SANITISED.md"

#: The role of each original in the substitution table, in the order the
#: replacements are made. A data path goes before the bare user name it
#: contains, and the user name before the accounts.
ROLES = (
    "the user's data directory under the first project account, "
    "`/data/<project-a>/<user>`",
    "the user's data directory under the second project account, "
    "`/data/<project-b>/<user>`",
    "the user's home directory, `/home/<user>`",
    "the ARC user name anywhere else",
    "the first project account code",
    "the second project account code",
)
#: The role of each further replacement (``--replace``).
EXTRA_ROLE = "a name of another project's job, or a phrase listing such names"

SANITISED = """\
# Sanitised source archive

This archive is a sanitised copy of the workflow's source tree at commit
`{commit}`: the tree as
`git -c core.autocrlf=false -c core.eol=lf archive --format=zip {short}`
writes it, with deployment identifiers replaced. Its ZIP comment is that
commit identifier, as `git archive` writes it. On 30 October 2026 the
author decided to remove from release 2.1.1 and its deposits the Oxford
ARC user name, the two ARC project account codes, the absolute paths that
contain them, and the names of other projects' jobs on the shared
account. The names of the cluster, its nodes, its login node, partitions
and QoS are unchanged: they identify the public cluster, which the paper
names.

## Substitutions

Every text member (UTF-8 without a NUL byte) had these plain string
replacements made, in this order. Binary members are unchanged.

| Original | Replacement |
| --- | --- |
{table}

ARC sets `$DATA` to the user's project data directory. A placeholder in
angle brackets stands for a value to supply. The commands in this archive
are otherwise as committed, and a shell reads an unquoted placeholder,
such as `--account=<project-a>`, as redirections, so put an account of
your own in its place before running one. Release 2.1.1 writes these
commands with a quoted `--account='<your-project>'`. A result file
rebuilt from the original inputs carries the original strings again; the
sanitised copies differ from it in these strings only.

## Changed members

{n_changed} of the archive's {n_members} members from the commit changed.
Each is listed with the git blob id of its original content at
`{short}`, by which the original can be found in the development
repository.

| Member | Original blob |
| --- | --- |
{changed}
{binary}"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(repo: Path, *args: str) -> bytes:
    git = shutil.which("git")
    if git is None:
        raise ValueError("git is not on PATH")
    result = subprocess.run([git, "-C", str(repo), *args], capture_output=True)
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: "
                         f"{result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def substitution_table(user: str, project_a: str, project_b: str,
                       extra: tuple[tuple[str, str], ...] = ()) -> list[tuple[str, str]]:
    """The ordered (original, replacement) pairs: the identifier table,
    then *extra*. Raises ValueError for an empty or repeated original, or
    one that occurs in a replacement, which would make the order matter in
    a way the table does not show."""
    table = [(f"/data/{project_a}/{user}", "$DATA"), (f"/data/{project_b}/{user}", "$DATA"),
             (f"/home/{user}", "$HOME"), (user, "<user>"),
             (project_a, "<project-a>"), (project_b, "<project-b>"), *extra]
    originals = [old for old, _ in table]
    if any(not old for old in originals) or len(set(originals)) != len(originals):
        raise ValueError("every original must be non-empty and distinct")
    for old, _ in table:
        if any(old in new for _, new in table):
            raise ValueError(f"an original appears in a replacement: {old!r}")
    return table


def _is_text(data: bytes) -> bool:
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _found(data: bytes, needles: list[bytes]) -> bool:
    """Whether *data*, or any member of it that is itself a ZIP archive,
    holds one of *needles*, ignoring case."""
    folded = data.lower()
    if any(n in folded for n in needles):
        return True
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as inner:
                return any(_found(inner.read(name), needles) for name in inner.namelist())
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
            return False
    return False


def _member(name: str, mode: int, when: tuple[int, ...]) -> zipfile.ZipInfo:
    """A member written as a Unix one with the file *mode* git gives it."""
    info = zipfile.ZipInfo(name, date_time=when)
    is_dir = name.endswith("/")
    info.compress_type = zipfile.ZIP_STORED if is_dir else zipfile.ZIP_DEFLATED
    # ZipInfo records the building platform (0 on Windows, 3 elsewhere);
    # fixing it keeps the bytes the same wherever the archive is built.
    # git archive marks a plain file as an MS-DOS one with no attributes,
    # which zipfile would write as mode 0600 (owner only) under a Unix
    # host, so every member carries its git mode instead: 0644 or 0755 for
    # a file, 0755 and the MS-DOS directory flag for a directory.
    info.create_system = 3
    info.external_attr = (0o40755 << 16) | 0x10 if is_dir else mode << 16
    return info


def build(commit: str, output: Path, user: str, project_a: str, project_b: str,
          extra: tuple[tuple[str, str], ...] = (), repo: Path = REPO,
          expect_source: Path | None = None) -> dict:
    """Write the sanitised archive of *commit* to *output* and its record
    beside it as ``<output>.json``; return the record.

    *user*, *project_a* and *project_b* are the identifiers to replace,
    and *extra* further (original, replacement) pairs made after them.
    *expect_source*, when given, is the deposited ``git archive`` of the
    commit, which the archive taken in memory must equal byte for byte.

    Raises:
        ValueError: git cannot archive the commit, the table is not valid
            (:func:`substitution_table`), the archive taken in memory
            differs from *expect_source* or *output* is that file, the
            commit already holds a member named ``SANITISED.md``, or a text
            member still holds an original after the replacements (one of
            another case, say).
    """
    table = substitution_table(user, project_a, project_b, extra)
    if expect_source is not None and Path(output).resolve() == Path(expect_source).resolve():
        raise ValueError("the output would overwrite the deposited original")
    needles = [old.lower().encode("utf-8") for old, _ in table]
    full = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    source_bytes = _git(repo, "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                        "archive", "--format=zip", full)
    if expect_source is not None:
        expected = Path(expect_source).read_bytes()
        if expected != source_bytes:
            raise ValueError(f"git archive of {full[:7]} differs from {expect_source} "
                             f"({_sha256(source_bytes)} against {_sha256(expected)})")
    blobs: dict[str, str] = {}
    modes: dict[str, int] = {}
    for entry in _git(repo, "ls-tree", "-r", "-z", "--full-tree", full).split(b"\0"):
        if entry:
            meta, path = entry.split(b"\t", 1)
            mode, _, oid = meta.decode().split()
            blobs[path.decode("utf-8")] = oid
            modes[path.decode("utf-8")] = int(mode, 8)
    seconds = int(_git(repo, "show", "-s", "--format=%ct", full).decode().strip())
    when = dt.datetime.fromtimestamp(seconds, dt.UTC).timetuple()[:6]

    members: dict[str, tuple[int, bytes]] = {}
    changed: list[tuple[str, str]] = []
    binary_hits: list[str] = []
    left: list[str] = []
    replacements = 0
    with zipfile.ZipFile(io.BytesIO(source_bytes)) as source:
        for info in source.infolist():
            data = source.read(info)
            if not info.is_dir() and _is_text(data):
                text = data.decode("utf-8")
                for old, new in table:
                    replacements += text.count(old)
                    text = text.replace(old, new)
                new_data = text.encode("utf-8")
                if new_data != data:
                    changed.append((info.filename, blobs.get(info.filename, "")))
                if _found(new_data, needles):
                    left.append(info.filename)
                data = new_data
            elif not info.is_dir() and _found(data, needles):
                binary_hits.append(info.filename)
            members[info.filename] = (modes.get(info.filename, 0o100644), data)
    if NOTE in members:
        raise ValueError(f"the commit already holds a member named {NOTE}")
    if left:
        raise ValueError(f"text members still hold an original: {sorted(left)}")

    roles = [*ROLES, *[EXTRA_ROLE] * (len(table) - len(ROLES))]
    pairs = [(role, new) for role, (_, new) in zip(roles, table, strict=True)]
    n_files = sum(1 for name in members if not name.endswith("/"))
    binary = ("" if not binary_hits else
              "\n## Binary members holding an identifier\n\nThese binary members hold "
              "an original and are left unchanged:\n\n"
              + "".join(f"- `{name}`\n" for name in sorted(binary_hits)))
    note = SANITISED.format(
        commit=full, short=full[:7],
        table="\n".join(f"| {role} | `{new}` |" for role, new in pairs),
        n_changed=len(changed), n_members=n_files,
        changed="\n".join(f"| `{path}` | `{blob}` |" for path, blob in sorted(changed)),
        binary=binary)
    members[NOTE] = (0o100644, note.encode("utf-8"))

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Each member is written through its own ZipInfo with no compression
    # level set, so zlib's default level (6) applies.
    with zipfile.ZipFile(output, "w") as archive:
        for name in sorted(members):
            mode, data = members[name]
            archive.writestr(_member(name, mode, when), data)
        archive.comment = full.encode("ascii")

    archive_bytes = output.read_bytes()
    found = []
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as written:
        for name in written.namelist():
            if _found(written.read(name), needles):
                found.append(name)
    record = {
        "archive": output.name,
        "bytes": len(archive_bytes),
        "sha256": _sha256(archive_bytes),
        "commit": full,
        "sanitised": True,
        "description": (f"git archive of {full} with the deployment identifiers replaced "
                        f"in every text member; {NOTE} in the archive gives the "
                        "substitutions and the changed members"),
        "zip_comment": full,
        "source_archive": {"bytes": len(source_bytes), "sha256": _sha256(source_bytes),
                           "checked_against": Path(expect_source).name if expect_source
                           else None},
        "files_from_commit": n_files,
        "changed_members": len(changed),
        "replacements": replacements,
        "substitutions": [{"original": role, "replacement": new} for role, new in pairs],
        "binary_members_with_identifiers": sorted(binary_hits),
        "members_with_identifiers_after_build": sorted(found),
        # The archive's digest reproduces only under the same deflate
        # implementation; see tools/build_input_deposit.py.
        "built_with": {"python": platform.python_version(),
                       "zlib": zlib.ZLIB_VERSION,
                       "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
                       "zlib_ng": getattr(zlib, "ZLIBNG_VERSION", None)},
    }
    output.with_name(output.name + ".json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _pair(text: str) -> tuple[str, str]:
    old, sep, new = text.partition("=")
    if not sep or not old:
        raise argparse.ArgumentTypeError(f"expected OLD=NEW, got {text!r}")
    return old, new


def main(argv=None) -> int:
    """Build the archive from the command line and print its record.

    Returns 0 once the archive and its record are written, and 2, with the
    reason on stderr, when :func:`build` refuses or a file cannot be read
    or written.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--commit", required=True, help="the commit to archive")
    parser.add_argument("--output", type=Path, required=True, help="the ZIP archive to write")
    parser.add_argument("--user", required=True, help="the ARC user name to replace")
    parser.add_argument("--project-a", required=True, help="the account written <project-a>")
    parser.add_argument("--project-b", required=True, help="the account written <project-b>")
    parser.add_argument("--replace", type=_pair, action="append", default=[],
                        metavar="OLD=NEW", help="a further replacement, made after the table")
    parser.add_argument("--repo", type=Path, default=REPO, help="the git repository")
    parser.add_argument("--expect-source", type=Path, default=None, metavar="ZIP",
                        help="the deposited git archive of the commit, to check against")
    args = parser.parse_args(argv)
    try:
        record = build(args.commit, args.output, args.user, args.project_a, args.project_b,
                       tuple(args.replace), args.repo, args.expect_source)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
