"""The ARC inputs deposit holds the receipt's files, each in its recorded form.

tools/build_arc_inputs_deposit.py writes the inputs of the multilingual
comparison, the Spanish control and the cross-hardware comparison to the
archive for the data deposit. It must refuse a file that differs from the
committed receipt or that the receipt does not name, sanitise only the
files the receipt marks and only into the bytes and counts it records, and
give the same archive bytes from the same inputs. The committed receipt
must cover every input digest the three results record.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import build_arc_inputs_deposit as deposit

#: Stand-ins for a deployment's identifiers; the real ones stay out of the
#: repository.
PRIVATE = [["/data/proj-x/u123", "$DATA"], ["/home/u123", "$HOME"], ["u123", "<user>"],
           ["proj-x", "<project-a>"]]
SUMMARY = b'{"summary": 1}\r\n'
LOG = b"Output dir: /data/proj-x/u123/out\nScripts: /home/u123/clone\nGPU: 0\nCard X\n"
ENV = b"slurm_account: proj-x\nworking_dir: /home/u123/clone\nuser: u123\n"
TABLE = [{"on_arc": "`/data/<project>/<user>`", "placeholder": "$DATA"},
         {"on_arc": "`/home/<user>`", "placeholder": "$HOME"},
         {"on_arc": "the user name", "placeholder": "<user>"},
         {"on_arc": "the project code", "placeholder": "<project-a>"}]


def _entry(path: str, data: bytes, sanitise: bool = False) -> dict:
    out, counts = deposit.sanitise(data, PRIVATE) if sanitise else (data, {})
    entry = {"path": path, "bytes": len(out), "sha256": hashlib.sha256(out).hexdigest(),
             "original_sha256": hashlib.sha256(data).hexdigest()}
    if sanitise:
        entry.update(original_bytes=len(data), sanitised=True, substitutions=counts)
    entry.update(role="a file", backs=["output/evaluation/x.json"])
    return entry


def _manifest(tmp_path: Path, arguments=None, files=None) -> Path:
    files = files or [_entry("evaluation/arm/wer_summary_x.json", SUMMARY),
                      _entry("clone/logs/job_1.out", LOG, sanitise=True),
                      _entry("evaluation/env/env_1.txt", ENV, sanitise=True)]
    manifest = {
        "recovered_and_verified_on": "2026-10-30", "release": "9.9.9",
        "files_deposited": len(files), "total_bytes": sum(f["bytes"] for f in files),
        "sanitisation": {"table": TABLE, "readme": "Two files are sanitised copies."},
        "artefacts": {"output/evaluation/x.json": {
            "description": "The result X.", "module": "evaluation.x",
            "arguments": arguments or ["--in @evaluation/arm/wer_summary_x.json",
                                       "--dir @evaluation/arm",
                                       "--env @evaluation/env/env_1.txt",
                                       "--out my_check/x.json"],
            "reproduces": "It comes back identical."}},
        "corpus_notices": [{"corpus": "AMI", "source": "https://example.org",
                            "data_licence": "CC-BY-4.0"}],
        "files": files,
    }
    path = tmp_path / "manifest.json"
    # Bytes, so the file has LF endings on Windows too, as the committed blob does.
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return path


def _write(folder: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return folder


@pytest.fixture()
def raw(tmp_path):
    """The originals as copied from the cluster."""
    folder = _write(tmp_path / "raw", {"evaluation/arm/wer_summary_x.json": SUMMARY,
                                       "clone/logs/job_1.out": LOG,
                                       "evaluation/env/env_1.txt": ENV})
    identifiers = tmp_path / "private.json"
    identifiers.write_text(json.dumps(PRIVATE), encoding="utf-8")
    return folder, identifiers, _manifest(tmp_path)


def test_sanitise_counts_each_placeholder_in_the_order_given():
    clean, counts = deposit.sanitise(ENV, PRIVATE)
    assert clean == b"slurm_account: <project-a>\nworking_dir: $HOME/clone\nuser: <user>\n"
    assert counts == {"$HOME": 1, "<user>": 1, "<project-a>": 1}
    assert list(counts) == ["$HOME", "<user>", "<project-a>"]


def test_the_archive_holds_each_file_in_its_recorded_form(tmp_path, raw):
    folder, identifiers, manifest = raw
    out = tmp_path / "out" / "deposit.zip"
    record = deposit.build(folder, out, manifest, identifiers)
    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
        assert names[:3] == ["README.md", "SHA256SUMS", "arc_inputs_manifest.json"]
        assert archive.read("inputs/evaluation/arm/wer_summary_x.json") == SUMMARY  # CRLF kept
        log = archive.read("inputs/clone/logs/job_1.out")
        assert log == b"Output dir: $DATA/out\nScripts: $HOME/clone\nGPU: 0\nCard X\n"
        env = archive.read("inputs/evaluation/env/env_1.txt")
        assert env == deposit.sanitise(ENV, PRIVATE)[0]
        sums = archive.read("SHA256SUMS").decode("ascii").splitlines()
        assert sums == [f"{hashlib.sha256(log).hexdigest()}  inputs/clone/logs/job_1.out",
                        f"{hashlib.sha256(SUMMARY).hexdigest()}  "
                        "inputs/evaluation/arm/wer_summary_x.json",
                        f"{hashlib.sha256(env).hexdigest()}  inputs/evaluation/env/env_1.txt"]
        assert archive.read("arc_inputs_manifest.json") == manifest.read_bytes()
        readme = archive.read("README.md").decode("utf-8")
    assert record["files"] == 3 and record["sanitised_files"] == 2
    assert json.loads((tmp_path / "out" / "deposit.zip.json").read_text("utf-8")) == record
    assert "release 9.9.9 or later" in readme and "AMI: CC-BY-4.0" in readme
    assert "- `inputs/evaluation/arm/wer_summary_x.json`: a file" in readme
    assert "- `inputs/evaluation/env/env_1.txt` (sanitised copy): a file" in readme
    assert "Of the 3,\n1 are deposited byte for byte and 2 as sanitised copies" in readme
    assert "Two files are sanitised copies." in readme
    assert "| `/home/<user>` | `$HOME` |" in readme


def test_the_command_points_every_input_at_the_unpacked_archive(tmp_path, raw):
    folder, identifiers, manifest = raw
    deposit.build(folder, tmp_path / "a.zip", manifest, identifiers)
    with zipfile.ZipFile(tmp_path / "a.zip") as archive:
        readme = archive.read("README.md").decode("utf-8")
    assert ("    python -m evaluation.x \\\n"
            "        --in build/arc_inputs/inputs/evaluation/arm/wer_summary_x.json \\\n"
            "        --dir build/arc_inputs/inputs/evaluation/arm \\\n"
            "        --env build/arc_inputs/inputs/evaluation/env/env_1.txt \\\n"
            "        --out my_check/x.json\n\nIt comes back identical.") in readme


def test_a_command_naming_an_unlisted_file_is_refused(tmp_path, raw):
    folder, identifiers, _ = raw
    manifest = _manifest(tmp_path, arguments=["--in @evaluation/arm/other.json"])
    with pytest.raises(ValueError, match="names no file of the manifest"):
        deposit.build(folder, tmp_path / "a.zip", manifest, identifiers)
    assert not (tmp_path / "a.zip").exists()


def test_the_same_inputs_give_the_same_archive_in_either_form(tmp_path, raw):
    """From the cluster's originals with the private replacements, or from the
    archive's own unpacked inputs without them: the same bytes."""
    folder, identifiers, manifest = raw
    first = deposit.build(folder, tmp_path / "a" / "deposit.zip", manifest, identifiers)
    second = deposit.build(folder, tmp_path / "b" / "deposit.zip", manifest, identifiers)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(tmp_path / "a" / "deposit.zip") as archive:
        archive.extractall(unpacked)
    third = deposit.build(unpacked / "inputs", tmp_path / "c" / "deposit.zip", manifest)
    assert first["sha256"] == second["sha256"] == third["sha256"]


def test_a_crlf_checkout_of_the_manifest_gives_the_same_archive(tmp_path, raw):
    folder, identifiers, manifest = raw
    crlf = tmp_path / "crlf.json"
    crlf.write_bytes(manifest.read_bytes().replace(b"\n", b"\r\n"))
    first = deposit.build(folder, tmp_path / "a" / "deposit.zip", manifest, identifiers)
    second = deposit.build(folder, tmp_path / "b" / "deposit.zip", crlf, identifiers)
    assert first["sha256"] == second["sha256"]
    assert first["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_the_record_names_both_zlib_versions(tmp_path, raw):
    import zlib

    folder, identifiers, manifest = raw
    built = deposit.build(folder, tmp_path / "a.zip", manifest, identifiers)["built_with"]
    assert built["zlib"] == zlib.ZLIB_VERSION
    assert built["zlib_runtime"] == zlib.ZLIB_RUNTIME_VERSION


def test_an_original_is_sanitised_only_with_the_replacements(tmp_path, raw):
    folder, identifiers, manifest = raw
    with pytest.raises(ValueError, match="--identifiers is needed"):
        deposit.build(folder, tmp_path / "a.zip", manifest)
    # Replacements that miss one string sanitise to other bytes.
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps(PRIVATE[:1]), encoding="utf-8")
    with pytest.raises(ValueError, match="does not give its manifest digest"):
        deposit.build(folder, tmp_path / "a.zip", manifest, partial)
    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps([["u123", "<someone>"]]), encoding="utf-8")
    with pytest.raises(ValueError, match="is not one of the placeholders"):
        deposit.build(folder, tmp_path / "a.zip", manifest, unknown)
    assert not (tmp_path / "a.zip").exists()


def test_counts_that_differ_from_the_receipt_are_refused(tmp_path, raw):
    """The right bytes with the wrong substitution counts mean the receipt
    misdescribes the edit."""
    folder, identifiers, _ = raw
    entry = _entry("evaluation/env/env_1.txt", ENV, sanitise=True)
    entry["substitutions"] = {"$HOME": 2}
    manifest = _manifest(tmp_path, files=[_entry("evaluation/arm/wer_summary_x.json", SUMMARY),
                                          _entry("clone/logs/job_1.out", LOG, sanitise=True),
                                          entry])
    with pytest.raises(ValueError, match="digest and counts"):
        deposit.build(folder, tmp_path / "a.zip", manifest, identifiers)


def test_a_deposited_file_holding_a_private_string_is_refused(tmp_path, raw):
    """A file deposited byte for byte must not carry an identifier either."""
    folder, identifiers, _ = raw
    leaky = b'{"path": "/home/u123/x"}\n'
    (folder / "evaluation/arm/wer_summary_x.json").write_bytes(leaky)
    manifest = _manifest(tmp_path, files=[_entry("evaluation/arm/wer_summary_x.json", leaky),
                                          _entry("clone/logs/job_1.out", LOG, sanitise=True),
                                          _entry("evaluation/env/env_1.txt", ENV,
                                                 sanitise=True)])
    with pytest.raises(ValueError, match="still holds a private string"):
        deposit.build(folder, tmp_path / "a.zip", manifest, identifiers)


def test_a_changed_or_unlisted_file_is_refused(tmp_path, raw):
    folder, identifiers, manifest = raw
    (folder / "evaluation/arm/wer_summary_x.json").write_bytes(b'{"summary": 2}\r\n')
    with pytest.raises(ValueError, match="differs from its manifest entry"):
        deposit.build(folder, tmp_path / "out.zip", manifest, identifiers)
    (folder / "evaluation/arm/wer_summary_x.json").write_bytes(SUMMARY)
    (folder / "evaluation/env/env_1.txt").write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="neither the deposited file nor the ARC original"):
        deposit.build(folder, tmp_path / "out.zip", manifest, identifiers)
    (folder / "evaluation/env/env_1.txt").write_bytes(ENV)
    (folder / "evaluation/stray.txt").write_bytes(b"x")
    with pytest.raises(ValueError, match="not in the manifest"):
        deposit.build(folder, tmp_path / "out.zip", manifest, identifiers)
    assert not (tmp_path / "out.zip").exists()


@pytest.mark.parametrize("problem", ["missing inputs", "missing manifest", "missing file",
                                     "malformed identifiers"])
def test_an_unusable_path_exits_2_without_a_traceback(tmp_path, raw, capsys, problem):
    folder, identifiers, manifest = raw
    argv = ["--inputs", str(folder), "--output", str(tmp_path / "out.zip"),
            "--manifest", str(manifest), "--identifiers", str(identifiers)]
    if problem == "missing inputs":
        argv[1] = str(tmp_path / "absent")
    elif problem == "missing manifest":
        argv[5] = str(tmp_path / "absent.json")
    elif problem == "missing file":
        (folder / "clone/logs/job_1.out").unlink()
    else:
        identifiers.write_text('{"u123": "<user>"}', encoding="utf-8")
    assert deposit.main(argv) == 2
    assert capsys.readouterr().err.startswith("Error: ")
    assert not (tmp_path / "out.zip").exists()


# The committed receipt -----------------------------------------------------

def _committed() -> dict:
    return json.loads(deposit.MANIFEST.read_text(encoding="utf-8"))


def test_the_receipt_covers_every_input_digest_the_three_results_record():
    """Each input digest a result records is the original of a deposited file:
    the file itself, or the original of its sanitised copy. So the deposit
    cannot drift from what the producers read."""
    originals = {f["original_sha256"] for f in _committed()["files"]}
    evaluation = PROJECT_ROOT / "output" / "evaluation"

    multilingual = json.loads((evaluation / "fleurs_multilingual_summary.json")
                              .read_text("utf-8"))
    recorded = [i["sha256"] for i in multilingual["benchmark"]["inputs"]]
    assert len(recorded) == 48 and set(recorded) <= originals

    control = json.loads((evaluation / "fleurs_es419_v100_control.json").read_text("utf-8"))
    recorded = [i["sha256"] for i in control["inputs"] if i["role"] != "multilingual_summary"]
    assert len(recorded) == 9 and set(recorded) <= originals

    cross = json.loads((evaluation / "determinism" / "determinism_cross_accelerator.json")
                       .read_text("utf-8"))
    recorded = [i["sha256"] for run in cross["runs"].values()
                for i in run["inputs"].values()]
    assert len(recorded) == 13 and set(recorded) <= originals


def test_the_receipt_is_consistent_and_names_no_deployment_path():
    receipt = _committed()
    files = receipt["files"]
    placeholders = {row["placeholder"] for row in receipt["sanitisation"]["table"]}
    assert receipt["files_deposited"] == len(files)
    assert receipt["total_bytes"] == sum(f["bytes"] for f in files)
    assert len({f["path"] for f in files}) == len(files)
    for f in files:
        assert f["backs"] and set(f["backs"]) <= set(receipt["artefacts"])
        if f.get("sanitised"):
            assert f["original_sha256"] != f["sha256"] and "original_bytes" in f
            assert f["substitutions"] and set(f["substitutions"]) <= placeholders
        else:
            assert f["original_sha256"] == f["sha256"] and "substitutions" not in f
    # The sanitisation table names the layout with placeholders, never a path.
    text = deposit.MANIFEST.read_text(encoding="utf-8")
    assert not re.search(r"/(data|home)/(?!<)", text)
