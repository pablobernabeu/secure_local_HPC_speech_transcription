"""Shared pytest fixtures.

The transcription pipeline imports heavy dependencies (``torch``,
``transformers``, ``librosa``) that are not available on every machine.
The module is written to tolerate those imports failing (it falls back
to ``AUDIO_LIBS_AVAILABLE = False``), so we can still import it for unit
testing the pure-Python helpers used by Phase 2 of the audit.

Every model cache is redirected into one temporary directory for the whole
session, so no test can read or write the machine's real caches; see
``MODEL_CACHE_DIRS`` below.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


#: The model caches, redirected for the whole session. On ARC, test-suite
#: jobs 8913985 (commit 76d9489) and 8917186 (commit 2e5e852) each ran
#: test_s1_env_setup.py's pre-cache test after another test had imported
#: pyannote.audio, so preflight.pyannote_cache_dir() returned the real
#: ~/.cache/torch/pyannote. The test's stand-in downloader then wrote its
#: 119-byte stub config.yaml through the snapshot's symlink into blob
#: 5402e3ca of pyannote/speaker-diarization-3.1, and every
#: Pipeline.from_pretrained on the cluster failed with KeyError: 'name'
#: until the blob was restored (incident NEW-INC-01). The variables are set
#: here, when pytest imports this file and before it imports any test
#: module, because most of the libraries read them once, at their own
#: import: pyannote.audio fixes CACHE_DIR then and binds it as the default
#: cache_dir of its from_pretrained loaders, and huggingface_hub,
#: transformers and datasets fix their cache paths the same way. torch.hub
#: (Silero VAD) and openai-whisper read TORCH_HOME and XDG_CACHE_HOME at
#: each load, which the session values cover as well.
MODEL_CACHE_ROOT = Path(tempfile.mkdtemp(prefix="pytest-model-caches-")).resolve()
MODEL_CACHE_DIRS = {
    "PYANNOTE_CACHE": MODEL_CACHE_ROOT / "pyannote",
    "HF_HOME": MODEL_CACHE_ROOT / "huggingface",
    "HF_HUB_CACHE": MODEL_CACHE_ROOT / "huggingface" / "hub",
    "HUGGINGFACE_HUB_CACHE": MODEL_CACHE_ROOT / "huggingface" / "hub",
    "TORCH_HOME": MODEL_CACHE_ROOT / "torch",
    "XDG_CACHE_HOME": MODEL_CACHE_ROOT / "xdg",
}
#: Narrower or older names that transformers (TRANSFORMERS_CACHE and the
#: two PYTORCH_* names), datasets (its cache, downloads and extractions)
#: and huggingface_hub read ahead of the directories above, so a value
#: inherited from the shell would reach past the redirect. They are removed
#: for the session. Checked against the versions installed on ARC:
#: transformers 4.57.1, huggingface_hub 0.35.3, datasets 4.8.5, torch 2.5.1
#: (whose TORCH_HUB and TORCH_MODEL_ZOO only warn) and pyannote.audio 3.4.0;
#: speechbrain 1.0.3 reads no cache variable of its own.
OVERRIDING_CACHE_VARIABLES = (
    "TRANSFORMERS_CACHE", "PYTORCH_TRANSFORMERS_CACHE",
    "PYTORCH_PRETRAINED_BERT_CACHE", "HF_DATASETS_CACHE",
    "HF_DATASETS_DOWNLOADED_DATASETS_PATH", "HF_DATASETS_EXTRACTED_DATASETS_PATH",
    "HF_MODULES_CACHE", "HF_ASSETS_CACHE", "HUGGINGFACE_ASSETS_CACHE", "HF_XET_CACHE",
)

# Undone in pytest_unconfigure, which also removes MODEL_CACHE_ROOT, so a
# process that runs pytest in-process gets its own environment back. A test
# that sets one of these variables with its own monkeypatch overrides the
# session value for that test only.
_SESSION_PATCH = pytest.MonkeyPatch()
for _name, _directory in MODEL_CACHE_DIRS.items():
    _SESSION_PATCH.setenv(_name, str(_directory))
for _name in OVERRIDING_CACHE_VARIABLES:
    _SESSION_PATCH.delenv(_name, raising=False)


def redirect_loaded_pyannote_caches(patch: pytest.MonkeyPatch) -> list[str]:
    """Point CACHE_DIR of every imported pyannote module at the session cache.

    The environment above only reaches a pyannote imported after this file.
    A copy imported earlier, or imported during a test that had replaced
    PYANNOTE_CACHE, keeps the directory it saw, and
    preflight.pyannote_cache_dir() reads it from the module first; that is
    the route by which jobs 8913985 and 8917186 reached the real cache.
    Default arguments bound at such an import are not rewritten, which is
    why the environment is set before any test module is imported.

    Parameters
    ----------
    patch:
        Records each change, so that undoing it restores the module.

    Returns the names of the modules changed. Side effect: sets
    ``CACHE_DIR`` on those modules through *patch*.
    """
    target = MODEL_CACHE_DIRS["PYANNOTE_CACHE"]
    changed = []
    for name, module in list(sys.modules.items()):
        if module is None or not (name == "pyannote" or name.startswith("pyannote.")):
            continue
        current = getattr(module, "CACHE_DIR", None)
        if not isinstance(current, (str, os.PathLike)):
            continue
        try:
            if Path(current).expanduser().resolve().is_relative_to(MODEL_CACHE_ROOT):
                continue
        except (OSError, ValueError):
            pass
        try:
            patch.setattr(module, "CACHE_DIR",
                          str(target) if isinstance(current, str) else target)
        except (AttributeError, TypeError):
            # A stand-in a test left in sys.modules may refuse new values;
            # failing here would error every test that follows.
            continue
        changed.append(name)
    return changed


@pytest.fixture(scope="session", autouse=True)
def isolated_model_caches():
    """The session's model-cache directory, with pyannote pointed at it.

    Returns ``MODEL_CACHE_ROOT``, under which every variable in
    ``MODEL_CACHE_DIRS`` points. Side effect: redirects an already imported
    pyannote (:func:`redirect_loaded_pyannote_caches`) until the session
    ends.
    """
    redirect_loaded_pyannote_caches(_SESSION_PATCH)
    return MODEL_CACHE_ROOT


@pytest.fixture(autouse=True)
def _pyannote_cache_stays_isolated(isolated_model_caches):
    """Before each test, redirect any pyannote module imported since the last.

    A test that imports pyannote for the first time while it has replaced
    or removed PYANNOTE_CACHE leaves CACHE_DIR pointing wherever that test
    chose, possibly the real cache, so the next test starts again from the
    session directory.
    """
    redirect_loaded_pyannote_caches(_SESSION_PATCH)


def pytest_unconfigure(config):
    """Restore the environment and remove the session's model caches."""
    _SESSION_PATCH.undo()
    shutil.rmtree(MODEL_CACHE_ROOT, ignore_errors=True)


#: Environment a cluster job carries that would reach through the tests'
#: stubs. On ARC, Lmod exports `module` and `ml` as bash functions
#: (BASH_FUNC_module%% ...), which beat any stub on PATH, and sets BASH_ENV
#: to its init script, which every non-interactive bash sources and which
#: defines `module` again; the SLURM_* and DATA variables of the job running
#: the suite point the job scripts at the real repository clone and data
#: tree. With them in place the shell-job tests ran the real module system
#: and real paths instead of their stubs (ARC jobs 8913985 and 8917186).
#: Tests that need one of these set it themselves.
#: The overrides a caller passes to a job script (CASE_*, OVERWRITE) go too:
#: one left exported in the shell that runs the suite, such as CASE_MANIFEST,
#: would override what a test sets up.
_HOST_JOB_ENV_PREFIXES = ("BASH_FUNC_", "SLURM_", "LMOD", "__LMOD", "CASE_")
_HOST_JOB_ENV_NAMES = ("DATA", "MODULEPATH", "MODULESHOME", "LOADEDMODULES", "_LMFILES_",
                       "MODULEPATH_ROOT", "SBATCH_ACCOUNT", "SBATCH_CLUSTERS",
                       "BASH_ENV", "ENV", "OVERWRITE")


@pytest.fixture(autouse=True)
def _hermetic_job_environment(monkeypatch):
    """Remove the host's module system and job variables from every test.

    Side effects: deletes matching variables from ``os.environ`` for the
    duration of each test (restored afterwards by ``monkeypatch``). Locally,
    where none are set, this changes nothing.
    """
    for name in list(os.environ):
        if name.startswith(_HOST_JOB_ENV_PREFIXES) or name in _HOST_JOB_ENV_NAMES:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def transcription_module():
    """Load ``transcription.py`` even when audio dependencies are absent.

    The module already guards each optional import with ``try/except`` so
    a plain ``import transcription`` works, but executing the file via
    ``importlib`` makes the test independent of whether the project is
    installed as a package.
    """
    path = PROJECT_ROOT / "transcription.py"
    spec = importlib.util.spec_from_file_location("transcription", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["transcription"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:  # pragma: no cover - tolerated for headless envs
        # Surface in the test log without aborting collection. Helpers used
        # by these tests are defined before any import that could fail.
        print(f"[conftest] transcription import partial: {e}")
    return module
