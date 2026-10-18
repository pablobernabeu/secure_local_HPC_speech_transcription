"""Systematic evaluation utilities for the transcription workflow."""

from __future__ import annotations

# A convenience for external code: ``from evaluation import normalise_text``
# (and the other names below) resolves to ``evaluation.wer``. Nothing in the
# repository imports them this way; the shim is kept because removing a
# documented import path could break a user's script (audit finding
# EWER-16 leaves that to the maintainer). The names are resolved lazily
# (PEP 562) so that importing a light submodule such as
# ``evaluation.conditions`` does not import the scoring module.
# ``evaluation.wer`` itself imports without jiwer, which only its scoring
# functions need.

_WER_EXPORTS = frozenset({
    "normalise_text",
    "compute_metrics",
    "evaluate_pair",
    "evaluate_directory",
})


def __getattr__(name: str):
    """Resolve the names in ``_WER_EXPORTS`` from :mod:`evaluation.wer`.

    Raises
    ------
    AttributeError
        For any other name, as a module attribute lookup would.
    """
    if name in _WER_EXPORTS:
        from . import wer
        return getattr(wer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    """List the module's names, including the lazily resolved ones."""
    return sorted(set(globals()) | _WER_EXPORTS)
