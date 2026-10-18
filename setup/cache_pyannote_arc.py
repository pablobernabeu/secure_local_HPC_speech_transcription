#!/usr/bin/env python3
"""Download the pyannote model weights to where the ARC jobs load them from.

Run this from the ARC login node (which has internet access):

    source ~/paper_speech_transcription/activate_project_env_arc.sh
    python ~/paper_speech_transcription/setup/cache_pyannote_arc.py

Every repository speaker-diarization-3.1 loads is cached: the pipeline, its
segmentation model and its speaker-embedding model. The list is the shared
``preflight.PYANNOTE_PIPELINE_REPOS``, extended by any further ``pyannote/*``
model the downloaded pipeline config names, so a compute node without Hub
access finds everything (audit finding CORE-15).

Where the weights go. pyannote.audio 3.x does not read the Hugging Face hub
cache (``<HF_HOME>/hub``): ``Pipeline.from_pretrained`` and
``Model.from_pretrained`` pass ``cache_dir=CACHE_DIR`` to
``hf_hub_download``, and ``CACHE_DIR`` is ``$PYANNOTE_CACHE`` or
``~/.cache/torch/pyannote`` (pyannote/audio/core/model.py in 3.4.0). The
download therefore goes to ``preflight.pyannote_cache_dir()``, which applies
the same rule. An earlier version wrote to ``<HF_HOME>/hub``, which no job
read, so the pre-caching did not stop a compute node from downloading
(review finding REV-01). No job sets PYANNOTE_CACHE, so on ARC this is
``~/.cache/torch/pyannote``, the directory the committed DER runs loaded
from.

Which snapshot. The loaders do not all ask for the same revision.
``evaluation/benchmark_der.py`` (and ``sweep_der.py`` through it), the
anonymisation benchmark, ``setup/setup_pyannote.py`` and
``setup/setup_environment.sh`` load the pipeline at the commit pinned in
``evaluation/revisions.py``, and
``evaluation/finetune_pyannote_segmentation.py`` loads the segmentation
model at its pin. ``evaluation.hub_loading.pinned_checkpoint`` spells the
pin ``<repo>@<commit>``, because pyannote.audio 3.x has no ``revision``
keyword. ``transcription.py`` loads the pipeline from the Hub at the
default branch (``main``) and records the commits the load resolved to,
read back from the cache. Whichever revision a pipeline is loaded at, it
loads its segmentation and embedding models at ``main``, because its
config names them without one, and the anonymisation benchmark's
fallback, which loads the embedding model directly when the pipeline will
not load, asks for ``main`` too. Each repository is therefore downloaded
at ``main``, which also records ``refs/main`` and lets an offline load
resolve it. The snapshot's commit is then compared with the revision
pinned in ``evaluation/revisions.py``. When they differ, the Hub has moved
since the committed results, the pinned snapshot is downloaded as well,
and the script exits 2 so the difference is not missed.

A damaged config. A download skips any file the cache already holds, so a
damaged one survives a re-run. When the cached pipeline config.yaml is
damaged (on ARC, test jobs 8913985 and 8917186 wrote a stub over it, and
every diarisation load until it was restored failed with KeyError:
'name'), the script says so after downloading, names the file to delete or
restore, and exits 3 instead of reporting success. The same goes for any
blob of the pipeline whose content no longer matches its name, which a
download would link again. The check is preflight's
(:func:`preflight.damaged_pipeline_configs`).

Options:

    --no-save-token     do not store the token in <HF_HOME>/token
    --overwrite-token   replace a different token already stored there

Exit status: 0 cached and matching the pins, 1 no token or no cache
directory, 2 cached but ``main`` differs from a pinned revision, 3 the
cached pipeline config, or a cached blob of the pipeline, is damaged.
"""
import argparse
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluation.revisions import revision_for  # noqa: E402
from preflight import (  # noqa: E402
    PYANNOTE_PIPELINE_REPOS,
    damaged_pipeline_configs,
    pipeline_config_remedy,
    pipeline_damage_heading,
    pyannote_cache_dir,
    resolve_hf_token,
)


def _masked(token: str) -> str:
    """Show only enough of a token to tell two apart (CORE-14)."""
    return f"hf_...{token[-4:]}" if len(token) > 8 else "(set)"


def save_token(hf_home: Path, token: str, overwrite: bool = False) -> bool:
    """Store *token* in ``<hf_home>/token`` with owner-only permissions.

    The hub library reads this file, so a batch job without HF_TOKEN in its
    environment still authenticates. The file is created with mode 0600,
    because $DATA project space is commonly group-readable, and a different
    token already stored there (for example by ``huggingface-cli login``) is
    kept unless *overwrite* is true (CORE-14).

    Returns True when the file now holds *token*. Side effect: may create
    *hf_home* and write the token file.
    """
    path = hf_home / "token"
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing == token:
            return True
        if not overwrite:
            print(f"A different token is already stored in {path}; leaving it "
                  "in place (pass --overwrite-token to replace it).")
            return False
    hf_home.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    try:
        os.chmod(path, 0o600)  # O_CREAT's mode does not apply to an existing file
    except OSError:
        pass
    print(f"Token written to {path} (owner-only)")
    return True


def repos_named_in_config(snapshot_dir: Path) -> list[str]:
    """Return the ``pyannote/*`` model ids a downloaded pipeline config names."""
    config = Path(snapshot_dir) / "config.yaml"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return []
    return sorted(set(re.findall(r"pyannote/[A-Za-z0-9._\-]+", text)))


def cache_all(cache_dir: Path, token: str, downloader) -> list[str]:
    """Download every pyannote repository the pipeline needs into *cache_dir*.

    Parameters
    ----------
    cache_dir:
        The pyannote cache directory (:func:`preflight.pyannote_cache_dir`).
    token:
        HuggingFace token for the gated repositories.
    downloader:
        ``huggingface_hub.snapshot_download`` or a stand-in with the same
        keyword arguments; it returns the local snapshot directory, whose
        name is the commit it holds.

    Returns
    -------
    list[str]
        One line per repository whose ``main`` commit differs from its pin
        in ``evaluation/revisions.py``; empty when all agree or are unpinned.

    Side effects: network downloads into *cache_dir*, including the pinned
    snapshot as well when ``main`` has moved away from it.
    """
    pending = list(PYANNOTE_PIPELINE_REPOS)
    done: set[str] = set()
    moved: list[str] = []
    while pending:
        repo = pending.pop(0)
        if repo in done:
            continue
        print(f"\nDownloading {repo} (main) ...")
        path = Path(downloader(repo_id=repo, token=token,
                               cache_dir=str(cache_dir), revision="main"))
        print(f"  -> {path}")
        done.add(repo)
        pinned = revision_for(repo)
        if pinned and path.name != pinned:
            moved.append(f"{repo}: main is {path.name}, pinned {pinned}")
            print(f"  main has moved from the pinned {pinned}; "
                  "downloading the pinned snapshot too")
            downloader(repo_id=repo, token=token, cache_dir=str(cache_dir),
                       revision=pinned)
        elif not pinned:
            print(f"  {repo} has no pinned revision in evaluation/revisions.py")
        pending += [r for r in repos_named_in_config(path) if r not in done]
    return moved


def main(argv=None) -> int:
    """Cache the pyannote weights and return the exit status in the docstring.

    Side effects: network downloads into :func:`preflight.pyannote_cache_dir`
    and (unless --no-save-token) the token file described in
    :func:`save_token`.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-save-token", action="store_true")
    parser.add_argument("--overwrite-token", action="store_true")
    args = parser.parse_args(argv)

    token, source = resolve_hf_token()
    if not token:
        print("ERROR: no HF token found. Set HF_TOKEN or create hf_token.txt "
              "in the repository root.", file=sys.stderr)
        return 1
    print(f"Token {_masked(token)} from {source}")

    hf_home = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    if not args.no_save_token:
        save_token(hf_home, token, overwrite=args.overwrite_token)

    cache_dir = pyannote_cache_dir()
    if cache_dir is None:
        print("ERROR: no home directory, so pyannote has no cache directory; "
              "set PYANNOTE_CACHE.", file=sys.stderr)
        return 1
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"pyannote cache: {cache_dir}")

    from huggingface_hub import snapshot_download  # noqa: PLC0415

    moved = cache_all(cache_dir, token, snapshot_download)

    # In test jobs 8913985 and 8917186 this function printed "All pyannote
    # weights cached" straight after the stub had replaced the config
    # (NEW-INC-01), and a plain re-run would leave the stub in place.
    damaged = damaged_pipeline_configs(cache_dir)
    if damaged:
        print(f"\nERROR: {pipeline_damage_heading(damaged)}:", file=sys.stderr)
        for path, problem in damaged:
            print(f"  {path} {problem}", file=sys.stderr)
        print(f"Fix: {pipeline_config_remedy(damaged)}", file=sys.stderr)
        return 3
    if moved:
        print("\nWARNING: the Hub's main branch differs from the pinned "
              "revisions for:", file=sys.stderr)
        for line in moved:
            print(f"  {line}", file=sys.stderr)
        # Which loader asks for which revision is set out under "Which
        # snapshot" in the module docstring, which this message summarises.
        print("Loads at a pinned revision find the pinned snapshot, now "
              "cached as well. Loads at main get the new one, which the "
              "committed results did not use.", file=sys.stderr)
        print("transcription.py loads the pipeline at main. Whichever "
              "revision the pipeline is loaded at, it loads its segmentation "
              "and embedding models at main, because its config names them "
              "without one, and the anonymisation benchmark's fallback loads "
              "the embedding model at main too.", file=sys.stderr)
        return 2
    print("\nAll pyannote weights cached. You can now submit the DER benchmark job:")
    print("  cd ~/paper_speech_transcription && sbatch hpc/submit_benchmark_der.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
