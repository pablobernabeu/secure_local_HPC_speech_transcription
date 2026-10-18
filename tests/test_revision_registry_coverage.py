"""Every Hub repository the code names is pinned or knowingly outside the registry.

Audit finding DEPS-16: model and dataset ids are typed out in many files,
so a revision pinned in one place could be missed in another. Every loader
now asks :func:`evaluation.revisions.revision_for` for its revision, so the
remaining failure is an id that is not in :data:`REVISIONS` (a typo, or a
model added later), which loads the branch head without a word. This test
finds every quoted Hub id in the Python sources and requires each to be in
the registry or in :data:`OUTSIDE_THE_REGISTRY` with its reason.
"""

from __future__ import annotations

import re
from pathlib import Path

from evaluation.revisions import REVISIONS

ROOT = Path(__file__).resolve().parent.parent

#: Hub ids the code names that are pinned some other way, or on purpose not
#: at all, with the reason.
OUTSIDE_THE_REGISTRY = {
    "pyannote/embedding": ("the anonymisation benchmark's last-resort embedding "
                           "model; a run that needs it records its revision as None"),
    "snakers4/silero-vad:v6.2.1": "a torch.hub repository pinned by its release tag",
    "urchade/gliner_small-v2.1": "pinned by ner_masking.py's own revision constant",
}

_HUB_ID = re.compile(
    r"""["']((?:openai|distil-whisper|pyannote|edinburghcstr|google|facebook|"""
    r"""speechbrain|urchade|LIUM|mozilla-foundation|snakers4|nvidia|microsoft)"""
    r"""/[A-Za-z0-9_.:-]+)["']""")


def _sources():
    for pattern in ("*.py", "evaluation/*.py", "setup/*.py", "local_app/*.py", "tools/*.py"):
        yield from ROOT.glob(pattern)


def _named_ids() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in _sources():
        for match in _HUB_ID.finditer(path.read_text(encoding="utf-8")):
            found.setdefault(match.group(1), set()).add(path.relative_to(ROOT).as_posix())
    return found


def test_every_named_hub_id_is_pinned_or_explained():
    unexplained = {repo: sorted(files) for repo, files in _named_ids().items()
                   if repo not in REVISIONS and repo not in OUTSIDE_THE_REGISTRY}
    assert not unexplained, (
        "Hub ids with no pinned revision in evaluation/revisions.py: "
        f"{unexplained}. Pin them there, or add them to OUTSIDE_THE_REGISTRY "
        "with the reason.")


def test_the_registry_covers_the_benchmarked_models_and_corpora():
    for repo in ("openai/whisper-large-v3", "openai/whisper-medium",
                 "distil-whisper/distil-large-v3", "pyannote/speaker-diarization-3.1",
                 "pyannote/segmentation-3.0", "pyannote/wespeaker-voxceleb-resnet34-LM",
                 "edinburghcstr/ami", "google/fleurs", "librispeech_asr",
                 "facebook/voxpopuli"):
        assert re.fullmatch(r"[0-9a-f]{40}", REVISIONS[repo]), repo


def test_the_explained_exceptions_are_still_named_somewhere():
    """An entry whose id no longer appears in the code is stale."""
    named = _named_ids()
    assert not [repo for repo in OUTSIDE_THE_REGISTRY if repo not in named]
