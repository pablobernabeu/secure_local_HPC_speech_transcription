"""The input deposit holds exactly the manifest's files, byte for byte.

tools/build_input_deposit.py writes the English sweep's recovered inputs
to the archive for a separate data deposit. It must refuse a file that
differs from the committed inventory or that the inventory does not list,
and the same inputs must always give the same archive bytes.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import build_input_deposit as deposit


def _manifest(tmp_path: Path, files: dict[str, bytes]) -> Path:
    entries = [{"name": name, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
               for name, data in sorted(files.items())]
    manifest = {
        "source": "Oxford ARC audit2026 sweep jobs 1, 2 and 3",
        "decoder_commit": "0" * 40, "recovered_and_verified_on": "2026-10-06",
        "summaries": 1, "hypothesis_dumps": 1,
        "total_bytes": sum(len(d) for d in files.values()),
        "grid": {"suites": ["ami"], "models": ["m"], "conditions": ["raw"]},
        "corpus_notices": [{"corpus": "AMI", "source": "https://example.org",
                            "data_licence": "CC-BY-4.0"}],
        "files": entries,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.fixture()
def inputs(tmp_path):
    files = {"wer_summary_ami_m.json": b'{"summary": 1}\r\n',
             "wer_hypotheses_ami_m.csv": b"uid,wer\nx,0.5\n"}
    folder = tmp_path / "inputs"
    folder.mkdir()
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder, files, _manifest(tmp_path, files)


def test_the_archive_holds_every_file_unchanged(tmp_path, inputs):
    folder, files, manifest = inputs
    record = deposit.build(folder, tmp_path / "out" / "deposit.zip", manifest)
    with zipfile.ZipFile(tmp_path / "out" / "deposit.zip") as archive:
        names = archive.namelist()
        assert names[:3] == ["README.md", "SHA256SUMS", "sweep_input_manifest.json"]
        for name, data in files.items():
            assert archive.read(f"inputs/{name}") == data   # CRLF kept
        sums = archive.read("SHA256SUMS").decode("ascii").splitlines()
        assert sums == [f"{hashlib.sha256(files[n]).hexdigest()}  inputs/{n}"
                        for n in sorted(files)]
        assert archive.read("sweep_input_manifest.json") == manifest.read_bytes()
        readme = archive.read("README.md").decode("utf-8")
    assert "jobs 1, 2 and 3" in readme and "AMI: CC-BY-4.0" in readme
    # CR-06: the aggregate's rebuild command gives its inputs and outputs,
    # as the other two commands do; with its defaults it scanned
    # output/evaluation and would have written over the committed files.
    assert ("python -m evaluation.sweep_aggregate \\\n"
            "        --sweep-dir build/recovered_arc_sweep/inputs \\\n"
            "        --out my_check/sweep_aggregate.csv \\\n"
            "        --out-json my_check/sweep_aggregate.json\n") in readme
    assert "`availability` field predates this deposit" in readme
    assert record["files"] == 2
    detached = json.loads((tmp_path / "out" / "deposit.zip.json").read_text("utf-8"))
    assert detached == record


def test_the_readme_names_the_software_release_only_when_given(tmp_path, inputs):
    folder, _, manifest = inputs
    deposit.build(folder, tmp_path / "a.zip", manifest, software_doi="10.5281/zenodo.1")
    deposit.build(folder, tmp_path / "b.zip", manifest)
    with zipfile.ZipFile(tmp_path / "a.zip") as a, zipfile.ZipFile(tmp_path / "b.zip") as b:
        assert "archived as https://doi.org/10.5281/zenodo.1" in a.read("README.md").decode()
        assert "doi.org" not in b.read("README.md").decode()


def _snapshot(path: Path, commit: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("transcription.py", "print('decoder')\n")
        archive.comment = commit.encode("ascii")
    return path


def test_the_readme_describes_the_decoder_source_when_given(tmp_path, inputs):
    folder, _, manifest = inputs
    source = _snapshot(tmp_path / "decoder_source_0000000.zip", "0" * 40)
    record = deposit.build(folder, tmp_path / "a.zip", manifest, decoder_source=source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert record["decoder_source"] == {"file": source.name, "bytes": source.stat().st_size,
                                        "sha256": digest}
    with zipfile.ZipFile(tmp_path / "a.zip") as archive:
        readme = archive.read("README.md").decode("utf-8")
        assert source.name not in archive.namelist()   # deposited beside it
    assert "## Historical decoder source" in readme and digest in readme
    deposit.build(folder, tmp_path / "b.zip", manifest)
    with zipfile.ZipFile(tmp_path / "b.zip") as archive:
        assert "decoder source" not in archive.read("README.md").decode("utf-8")


def test_a_source_archive_of_another_commit_is_refused(tmp_path, inputs):
    folder, _, manifest = inputs
    source = _snapshot(tmp_path / "other.zip", "1" * 40)
    with pytest.raises(ValueError, match="is not an archive of"):
        deposit.build(folder, tmp_path / "a.zip", manifest, decoder_source=source)
    assert not (tmp_path / "a.zip").exists()


def test_the_record_names_both_zlib_versions(tmp_path, inputs):
    """ZLIB_VERSION is the compile-time headers' version; the library that
    deflated the archive is ZLIB_RUNTIME_VERSION, recorded beside it."""
    import zlib

    folder, _, manifest = inputs
    built = deposit.build(folder, tmp_path / "a.zip", manifest)["built_with"]
    assert built["zlib"] == zlib.ZLIB_VERSION
    assert built["zlib_runtime"] == zlib.ZLIB_RUNTIME_VERSION


def test_the_same_inputs_give_the_same_archive(tmp_path, inputs):
    folder, _, manifest = inputs
    first = deposit.build(folder, tmp_path / "a" / "deposit.zip", manifest)
    second = deposit.build(folder, tmp_path / "b" / "deposit.zip", manifest)
    assert first["sha256"] == second["sha256"]


def test_a_crlf_checkout_of_the_manifest_gives_the_same_archive(tmp_path, inputs):
    folder, _, manifest = inputs
    lf = json.dumps(json.loads(manifest.read_text("utf-8")), indent=2) + "\n"
    manifest.write_bytes(lf.encode("utf-8"))
    crlf = tmp_path / "crlf.json"
    crlf.write_bytes(lf.replace("\n", "\r\n").encode("utf-8"))
    first = deposit.build(folder, tmp_path / "a" / "deposit.zip", manifest)
    second = deposit.build(folder, tmp_path / "b" / "deposit.zip", crlf)
    assert first["sha256"] == second["sha256"]
    assert first["manifest_sha256"] == hashlib.sha256(lf.encode("utf-8")).hexdigest()


def test_a_changed_or_unlisted_file_is_refused(tmp_path, inputs):
    folder, _, manifest = inputs
    (folder / "wer_hypotheses_ami_m.csv").write_bytes(b"uid,wer\nx,0.6\n")
    with pytest.raises(ValueError, match="differs from its manifest entry"):
        deposit.build(folder, tmp_path / "out.zip", manifest)
    (folder / "wer_hypotheses_ami_m.csv").write_bytes(b"uid,wer\nx,0.5\n")
    (folder / "stray.txt").write_bytes(b"x")
    with pytest.raises(ValueError, match="not in the manifest"):
        deposit.build(folder, tmp_path / "out.zip", manifest)


@pytest.mark.parametrize("problem", ["not a zip", "missing source", "missing inputs",
                                     "missing manifest"])
def test_an_unusable_path_exits_2_without_a_traceback(tmp_path, inputs, capsys, problem):
    """main promised status 2 when build refuses its inputs, but a decoder
    source that is not a ZIP or is absent, or an absent --inputs directory,
    ended in a traceback."""
    folder, _, manifest = inputs
    argv = ["--inputs", str(folder), "--output", str(tmp_path / "out.zip"),
            "--manifest", str(manifest)]
    if problem == "not a zip":
        (tmp_path / "source.zip").write_bytes(b"not a zip archive")
        argv += ["--decoder-source", str(tmp_path / "source.zip")]
    elif problem == "missing source":
        argv += ["--decoder-source", str(tmp_path / "absent.zip")]
    elif problem == "missing inputs":
        argv[1] = str(tmp_path / "absent")
    else:
        argv[5] = str(tmp_path / "absent.json")
    assert deposit.main(argv) == 2
    assert capsys.readouterr().err.startswith("Error: ")
    assert not (tmp_path / "out.zip").exists()


def test_a_missing_file_is_refused(tmp_path, inputs):
    folder, _, manifest = inputs
    (folder / "wer_summary_ami_m.json").unlink()
    assert deposit.main(["--inputs", str(folder), "--output",
                         str(tmp_path / "out.zip"), "--manifest", str(manifest)]) == 2
    assert not (tmp_path / "out.zip").exists()
