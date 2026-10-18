"""Keyword arguments for loading gated, pinned models from the Hugging Face Hub.

Two things vary between the loaders this repository calls and have to be
read from each loader's signature rather than hard-coded:

* the token keyword: pyannote.audio 3.x (3.4.0 in the ARC environment)
  names it ``use_auth_token`` on ``Pipeline.from_pretrained``,
  ``Model.from_pretrained`` and ``PretrainedSpeakerEmbedding``, while 4.x
  calls it ``token`` and rejects the old name, so a hard-coded
  ``use_auth_token`` fails with a TypeError on a fresh install (audit
  finding DEPS-10);
* how a revision is given: pyannote.audio 3.x takes it as
  ``"<repo>@<revision>"`` in the checkpoint name and has no ``revision``
  keyword, so the snapshot in :mod:`evaluation.revisions` has to be spelt
  that way to be enforced (DEPS-04).

These helpers were first written for the anonymisation benchmark and are
shared here so that every loader makes the same choice. ``transcription.py``
keeps its own ``_pipeline_load_kwargs``, which also handles offline mode.
Importing this module imports only the standard library.
"""

from __future__ import annotations

import inspect


def _parameters(loader) -> dict:
    """Return *loader*'s parameters, or an empty mapping if unreadable."""
    try:
        return dict(inspect.signature(loader).parameters)
    except (TypeError, ValueError):
        return {}


def _accepts_any_keyword(params) -> bool:
    """True when the parameters include ``**kwargs``."""
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def token_kwargs(loader, token) -> dict:
    """Return the Hugging Face token keyword *loader* accepts.

    ``use_auth_token`` when the loader names it and not ``token`` (pyannote
    3.x); ``token`` when it names that or takes ``**kwargs``; nothing for a
    loader that takes neither. The keyword is chosen from the signature
    rather than by trying each spelling and catching TypeError, which would
    also swallow a TypeError raised inside a genuine load.
    """
    params = _parameters(loader)
    if "use_auth_token" in params and "token" not in params:
        return {"use_auth_token": token}
    if "token" in params or _accepts_any_keyword(params):
        return {"token": token}
    return {}


def pinned_checkpoint(loader, repo_id):
    """Return ``(checkpoint, kwargs)`` loading *repo_id* at its pinned revision.

    The revision comes from :func:`evaluation.revisions.revision_for`. A
    loader with a ``revision`` keyword gets it that way; otherwise it is
    spelt ``"<repo>@<revision>"``, the form pyannote.audio 3.x parses. A
    repository with no pinned revision, or a local path, loads as given.
    """
    from evaluation.revisions import revision_for  # noqa: PLC0415

    revision = revision_for(repo_id)
    if revision is None:
        return repo_id, {}
    if "revision" in _parameters(loader):
        return repo_id, {"revision": revision}
    return f"{repo_id}@{revision}", {}
