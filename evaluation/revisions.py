"""The exact Hugging Face revisions behind the committed results.

Every model and dataset the workflow loads is named here once, with the
commit it resolved to. The identifiers used to be retyped across about ten
files and loaded from ``main``, so a later upstream push would silently
change what a re-run measured (audit findings DEPS-04, DEPS-16, EWER-10).

The revisions were read on 2026-09-26 from the Hugging Face cache of the ARC
environment that produced the committed results
(``$HF_HOME/hub/<repo>/refs/main``). Each repository held a single snapshot,
so each SHA is the one every committed run loaded, not a later guess.

Loaders pass :func:`revision_for` as ``revision=``. A repository not listed
here returns ``None``, which loads ``main`` as before; the summary then
records ``None`` for it, so an unpinned load is visible.
"""

from __future__ import annotations

#: Repository id -> commit SHA. Keep one entry per repository.
REVISIONS: dict[str, str] = {
    # ASR models (evaluation/benchmark_wer.py, sweep.py, benchmark_timestamps.py,
    # benchmark_anonymisation.py, transcription.py).
    "openai/whisper-large-v3": "06f233fe06e710322aca913c1bc4249a0d71fce1",
    "openai/whisper-medium": "abdf7c39ab9d0397620ccaea8974cc764cd0953e",
    "distil-whisper/distil-large-v3": "8031d2e6ce6631b7fc45629dddfc00271116d981",
    # Diarisation (transcription.py, evaluation/benchmark_der.py, sweep_der.py,
    # benchmark_anonymisation.py). The 3.1 pipeline's config names the
    # segmentation and WeSpeaker models without a revision, so pinning the
    # pipeline does not pin them; they are listed so summaries record them.
    # The WeSpeaker SHA was read from pyannote's own cache on ARC
    # (~/.cache/torch/pyannote), where that model is stored.
    "pyannote/speaker-diarization-3.1": "84fd25912480287da0247647c3d2b4853cb3ee5d",
    "pyannote/segmentation-3.0": "e66f3d3b9eb0873085418a7b813d3b369bf160bb",
    "pyannote/wespeaker-voxceleb-resnet34-LM": "837717ddb9ff5507820346191109dc79c958d614",
    # Evaluation corpora (evaluation/challenge_suites.py, benchmark_wer.py,
    # ami_meetings.py, benchmark_timestamps.py).
    "librispeech_asr": "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1",
    "google/fleurs": "70bb2e84b976b7e960aa89f1c648e09c59f894dd",
    "edinburghcstr/ami": "46f28f2503e2ec48f8867a84eef356c70476beab",
    "facebook/voxpopuli": "42f01879c780b4a2e90ec0b4f616c2ece526e4f1",
}


def revision_for(repo_id: str | None) -> str | None:
    """Return the pinned revision for *repo_id*, or ``None`` if it is not pinned.

    Parameters
    ----------
    repo_id:
        A Hugging Face repository id such as ``"openai/whisper-large-v3"``.
        A local path or ``None`` returns ``None``.

    Returns
    -------
    str or None
        The commit SHA to pass as ``revision=``.
    """
    if not repo_id:
        return None
    return REVISIONS.get(repo_id)


def revisions_used(*repo_ids: str | None) -> dict[str, str | None]:
    """Return ``{repo_id: revision}`` for the repositories a run loaded.

    Written into result summaries so each artefact records exactly which
    snapshot of each model and dataset it came from.
    """
    return {r: revision_for(r) for r in repo_ids if r}
