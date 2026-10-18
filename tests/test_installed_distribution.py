"""A real installed wheel must supply the default masker's dictionary.

Builds use the local setuptools backend without dependency installation.
The subprocess smoke check runs with site imports disabled: it exercises
the installed text helpers, not audio/model inference or optional NER.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DATA = ("data/curated_names.csv", "versions.csv")


def _run(args, cwd):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                            text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def distributions():
    if importlib.util.find_spec("setuptools") is None:
        pytest.skip("the local setuptools build backend is unavailable")
    # A nested build below a long Windows checkout can exceed legacy path
    # limits. This owned temporary directory also keeps every import and
    # build outside the source checkout.
    temporary = tempfile.TemporaryDirectory(prefix="wheel-")
    scratch = Path(temporary.name).resolve()
    assert scratch.is_relative_to(Path(tempfile.gettempdir()).resolve())
    source, artifacts = scratch / "source", scratch / "artifacts"
    source.mkdir()
    artifacts.mkdir()
    for path in [*ROOT.glob("*.py"), ROOT / "README.md", ROOT / "MANIFEST.in",
                 *ROOT.glob("LICENSE*"), *ROOT.glob("Licence*"),
                 ROOT / "requirements.txt", ROOT / "requirements-dev.txt",
                 *(ROOT / name for name in RUNTIME_DATA)]:
        destination = source / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    for name in ("evaluation", "local_app"):
        shutil.copytree(ROOT / name, source / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Direct PEP 517 calls use the already installed backend. They neither
    # create an environment nor resolve/install any declared dependency.
    script = ("import sys; from setuptools.build_meta import build_wheel, build_sdist; "
              "output = sys.argv[1]; build_wheel(output); build_sdist(output)")
    _run([sys.executable, "-c", script, str(artifacts)], source)
    try:
        yield scratch, next(artifacts.glob("*.whl")), next(artifacts.glob("*.tar.gz"))
    finally:
        temporary.cleanup()


def test_wheel_retains_exact_runtime_resources(distributions):
    _, wheel, _ = distributions
    with zipfile.ZipFile(wheel) as archive:
        for name in RUNTIME_DATA:
            assert archive.read(name) == (ROOT / name).read_bytes()
        assert "evaluation/revisions.py" in archive.namelist()
        assert "local_app/gui.py" in archive.namelist()


def test_sdist_can_rebuild_a_complete_wheel(distributions):
    scratch, _, sdist = distributions
    unpacked = scratch / "from-sdist"
    unpacked.mkdir()
    with tarfile.open(sdist) as archive:
        archive.extractall(unpacked, filter="data")
    source = next(unpacked.iterdir())
    for name in [*RUNTIME_DATA, "requirements.txt", "requirements-dev.txt"]:
        assert (source / name).read_bytes() == (ROOT / name).read_bytes()
    artifacts = scratch / "rebuilt"
    artifacts.mkdir()
    _run([sys.executable, "-c",
          "import sys; from setuptools.build_meta import build_wheel; build_wheel(sys.argv[1])",
          str(artifacts)], source)
    with zipfile.ZipFile(next(artifacts.glob("*.whl"))) as archive:
        for name in RUNTIME_DATA:
            assert archive.read(name) == (ROOT / name).read_bytes()


def test_installed_default_masker_and_version_from_unrelated_directory(distributions):
    scratch, wheel, _ = distributions
    installed, unrelated = scratch / "installed", scratch / "unrelated"
    unrelated.mkdir()
    _run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
          "--disable-pip-version-check",
          "--no-compile", "--target", str(installed), str(wheel)], unrelated)
    with (ROOT / "versions.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_release = max(enumerate(rows),
                           key=lambda item: (item[1]["date"], item[0]))[1]["version"]
    # -I ignores PYTHONPATH and the current directory; -S excludes the
    # machine's site-packages. Only the wheel target is added. An empty
    # PATH prevents the optional ffmpeg import from creating a shim.
    script = r'''
import contextlib, io, json, os, sys
from pathlib import Path
os.environ["PATH"] = ""
sys.path.insert(0, sys.argv[1])
with contextlib.redirect_stdout(io.StringIO()):
    import transcription
    mask, _ = transcription.create_enhanced_name_masker()
site = Path(sys.argv[1]).resolve()
assert Path(transcription.__file__).resolve().parent == site
assert transcription.CURATED_NAMES_CSV == site / "data" / "curated_names.csv"
assert mask("Sarah arrived.") == "[NAME] arrived."
assert mask("sarah arrived.") == "sarah arrived."
assert transcription._latest_release() == sys.argv[2]
assert transcription.get_latest_version() == sys.argv[2]
print(json.dumps({"installed_masker": True, "release": transcription.get_latest_version()}))
'''
    result = _run([sys.executable, "-I", "-S", "-c", script,
                   str(installed), expected_release], unrelated)
    assert json.loads(result.stdout) == {"installed_masker": True,
                                       "release": expected_release}
