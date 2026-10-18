#!/usr/bin/env python3
"""Regenerate example_output/variants/ by running the pipeline on a synthetic interview.

Each variant directory holds what ``python transcription.py example.wav
--language english --mask-personal-names --fix-spurious-repetitions``
writes, with neither, one or both of ``--timestamps`` and
``--speaker-attribution`` added (see :data:`VARIANTS`). The command is run
for real, through ``transcription.main``: argument parsing, the
orchestration in ``process_audio_file``, segmentation, timeline repair,
speaker assignment, clean-up, name masking, the .txt header, the JSON and
WebVTT writers, the review report and the run manifest are all the
pipeline's own code. The examples therefore show the files and keys a
real run writes, and a change to any writer changes them.

An earlier version of this script wrote the files from hand-made
templates. They had drifted from the pipeline: no ``timeline_repairs`` or
``redacted`` keys, a diarisation source label (``hf_cache``) the pipeline
never emits, JSON and captions in the plain variant that a plain run does
not write, and no redacted, review or manifest files (audit findings
XREF-03, CORE-20 and OUTPUTS-13). Its interview text also quoted
evaluation figures that had gone stale (CORE-19); the text below is kept
free of figures so that it cannot fall out of step with the results.

What is replaced, and why:

* The two model calls. ``transcribe_audio_only`` returns a synthetic
  result built from :data:`TURNS` (word-level chunks when timestamps are
  requested, text alone otherwise, as the transformers pipeline does), and
  ``perform_speaker_diarization`` returns one segment per turn with the
  source record the Hugging Face loader produces in offline mode.
* The recording. ``example.wav`` is an empty 16 kHz WAV written to a
  temporary directory; the manifest's ``input_audio`` digest is of that
  placeholder. ``librosa.get_duration`` is answered from the synthetic
  timeline so that the result does not depend on whether librosa is
  installed.
* The Word documents. ``create_word_document`` is replaced by a no-op,
  because a .docx is a zip archive stamped with the time it was written,
  so no two runs match. A real run also writes ``example_transcript.docx``
  (and ``example_transcript_with_speakers.docx``) and lists them in the
  manifest.
* Values that change on every run are pinned: the clock
  (:data:`PINNED_TIME`), the version string (the release in versions.csv
  alone, as an installed copy without git reports it), and the manifest's
  software block (the package versions in requirements-lock.txt, with the
  git fields empty). No signing key is used, so the manifests are unsigned.
* Line endings. Artefacts are written with LF on every platform, as on
  Linux, so that the SHA-256 digests in the manifests do not depend on the
  machine that ran this script. ``.gitattributes`` keeps them LF on
  checkout, so ``python -m provenance verify`` passes on the committed
  files.

The masking log is not part of any variant: it is written only with
``--save-name-masking-logs``, and to ``name_masking_logs/``, not beside
the transcripts.

Run from the project root::

    python tools/generate_example_variants.py

Side effects: deletes every file in each ``example_output/variants/<name>/``
directory and writes the regenerated set in its place. Imports
``transcription`` without transformers when transformers has not been
imported yet, because no model is used and importing it costs minutes and
gigabytes; in such a process ``transcription.TRANSFORMERS_AVAILABLE`` stays
False afterwards.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import os
import re
import sys
import tempfile
import types
import wave
from datetime import datetime
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BASE = REPO / "example_output" / "variants"

#: Variant directory -> the flags added to :data:`BASE_ARGS` to produce it.
VARIANTS = {
    "01_plain": (),
    "02_timestamps": ("--timestamps",),
    "03_diarisation": ("--speaker-attribution",),
    "04_diarisation_and_timestamps": ("--timestamps", "--speaker-attribution"),
}

#: The recording's file name, and so the stem of every output.
AUDIO_NAME = "example.wav"

#: Options every variant shares.
BASE_ARGS = ("--language", "english", "--mask-personal-names",
             "--fix-spurious-repetitions")

#: The clock every timestamp in the examples reads.
PINNED_TIME = datetime(2026, 9, 27, 12, 0, 0)

# Synthetic timing. Each word gets an equal slot, and speaks for most of it,
# at a rate inside the 2 to 4 words per second that confidence.py treats as
# ordinary speech, so the review flags nothing by accident. The values are
# illustrative, not measured.
LEAD_IN_S = 0.5
WORD_SLOT_S = 0.36
WORD_FILL = 0.88
TURN_GAP_S = 0.7
TAIL_S = 1.5

#: (speaker, text) for each turn. The text is what Whisper would return,
#: before any clean-up. It names two fictional people, so that the masked
#: transcripts and the redacted files show placeholders where the raw
#: JSON and captions keep the names. It states no figures: anything a
#: reader might take for a result belongs in the paper and in
#: output/evaluation, where it is regenerated with the code.
TURNS = [
    ("SPEAKER_00",
     "You have been building a transcription workflow for research "
     "recordings. Thank you for joining us today, Dr Rossi. What problem "
     "were you trying to solve?"),
    ("SPEAKER_01",
     "Research interviews are full of personal information: names, places "
     "and details that could identify a participant. Uploading them to a "
     "cloud service moves that information outside the institution, which "
     "many ethics approvals do not allow. This workflow runs every step on "
     "hardware the institution controls, whether that is a laptop or a "
     "university cluster."),
    ("SPEAKER_00", "Which models does it rely on?"),
    ("SPEAKER_01",
     "Speech is transcribed by Whisper through the Hugging Face "
     "transformers library, and speakers are told apart by a pyannote "
     "diarisation pipeline. The model weights are downloaded once, and "
     "after that a run needs no network connection."),
    ("SPEAKER_00", "What happens to the text once the model has produced it?"),
    ("SPEAKER_01",
     "A series of clean-up stages removes stray characters, repairs "
     "spacing and punctuation, and can shorten the runaway repetitions "
     "that Whisper occasionally produces. Personal names are then replaced "
     "with placeholders, using a curated dictionary of first names and "
     "surnames."),
    ("SPEAKER_00", "Does the masking find every name?"),
    ("SPEAKER_01",
     "No, and it matters to say so. A dictionary finds only the names it "
     "contains, and only when they are capitalised, so an unusual or "
     "lower-case name can slip through. Every masked transcript therefore "
     "recommends a review, and the paper reports how often names were "
     "missed."),
    ("SPEAKER_00", "How far can a researcher trust the speaker labels?"),
    ("SPEAKER_01",
     "That depends on the recording. Overlapping speech, similar voices "
     "and distant microphones all make attribution harder, so the labels "
     "should be checked against the audio wherever exact attribution "
     "matters. The paper reports the error rates we measured on meeting "
     "recordings."),
    ("SPEAKER_00", "What do the timestamped files contain?"),
    ("SPEAKER_01",
     "The JSON file keeps the timing of every segment and every word, and "
     "the caption file uses the same timings. Both are written before any "
     "clean-up, so they record exactly what the model produced, and with "
     "masking switched on a redacted copy of each is written beside them. "
     "A review file then points to segments worth checking by ear."),
    ("SPEAKER_00", "And how would someone check a transcript months later?"),
    ("SPEAKER_01",
     "Each run writes a manifest that lists every file it produced with a "
     "digest of its contents, together with the settings and software "
     "versions. Checking the files against that manifest shows whether "
     "anything has changed since."),
    ("SPEAKER_00", "Thank you, Elena. That was very clear."),
]


# ---------------------------------------------------------------------------
# The synthetic model output
# ---------------------------------------------------------------------------

def _timeline():
    """Return ``(words, turns, duration)`` for the synthetic recording.

    *words* is a list of ``(text, start, end)`` with one entry per word of
    :data:`TURNS`, *turns* a list of ``(speaker, start, end)`` spanning each
    turn's words, and *duration* the recording's length in seconds. Times
    are rounded to centiseconds, the resolution Whisper's timestamps have.
    """
    words, turns = [], []
    clock = LEAD_IN_S
    for speaker, text in TURNS:
        turn_start = clock
        for token in text.split():
            words.append((token, round(clock, 2),
                          round(clock + WORD_FILL * WORD_SLOT_S, 2)))
            clock += WORD_SLOT_S
        turns.append((speaker, round(turn_start, 2), words[-1][2]))
        clock += TURN_GAP_S
    return words, turns, round(words[-1][2] + TAIL_S, 2)


def _asr_result(_audio_path, _model=None, _language=None,
                return_timestamps=False):
    """Stand in for ``transcription.transcribe_audio_only``.

    Returns the dict shape the transformers pipeline gives: ``text`` with
    the leading space Whisper's tokeniser produces, ``chunks`` with one
    ``{'text', 'timestamp'}`` entry per word only when timestamps were
    requested, and the ``audio_duration_s`` and ``model_revision`` that
    ``transcribe_audio_only`` adds. The revision is the snapshot
    ``evaluation.revisions`` pins for the model, which is what a run from a
    cache filled by ``setup/download_model.py`` loads.
    """
    from evaluation.revisions import revision_for  # noqa: PLC0415

    words, _, duration = _timeline()
    result = {"text": "".join(f" {token}" for token, _, _ in words),
              "audio_duration_s": duration,
              "model_revision": revision_for(_model)}
    if return_timestamps:
        result["chunks"] = [{"text": f" {token}", "timestamp": (start, end)}
                            for token, start, end in words]
    return result


def _diarisation(t):
    """Return a stand-in for ``perform_speaker_diarization`` in module *t*.

    The source record is the one the Hugging Face loader writes when the
    run is offline, as a cluster job is, with its label taken from the
    pipeline's own resolution policy rather than typed here. The snapshots
    are those ``evaluation.revisions`` pins for the pipeline and for the
    other repositories it loads (``preflight.PYANNOTE_PIPELINE_REPOS``),
    which is what a cache filled by ``setup/cache_pyannote_arc.py`` holds as
    ``main``; that script exits 2 when the Hub has moved from them.
    """
    from evaluation.revisions import revision_for  # noqa: PLC0415
    from preflight import PYANNOTE_PIPELINE_REPOS  # noqa: PLC0415

    plan = t._resolve_diarization_strategy(env={"HF_HUB_OFFLINE": "1"})
    source = {
        "source": plan["attempts"][-1]["source_label"],
        "model_id": t.DEFAULT_DIARIZATION_MODEL,
        "model_path": None,
        "model_revision": revision_for(t.DEFAULT_DIARIZATION_MODEL),
        "sub_model_revisions": {repo: revision_for(repo)
                                for repo in sorted(PYANNOTE_PIPELINE_REPOS)
                                if repo != t.DEFAULT_DIARIZATION_MODEL},
        "offline_mode": plan["offline_mode"],
        "vad_onset": None,
        "vad_offset": None,
        "error": None,
        "speaker_count_hint": None,
        "vad_applied": None,
    }

    def perform_speaker_diarization(_audio_path, **_kwargs):
        _, turns, _ = _timeline()
        return ([{"start": s, "end": e, "speaker": spk} for spk, s, e in turns],
                dict(source))

    return perform_speaker_diarization


# ---------------------------------------------------------------------------
# Pinned values
# ---------------------------------------------------------------------------

class _PinnedClock(datetime):
    """``datetime`` whose ``now()`` always returns :data:`PINNED_TIME`."""

    @classmethod
    def now(cls, tz=None):  # noqa: D401 - mirrors datetime.now
        return cls(*PINNED_TIME.timetuple()[:6], tzinfo=tz)


def _lock_versions(lock_file=REPO / "requirements-lock.txt"):
    """Return ``({package: version}, python_version)`` from the lock file.

    Package names are lower-cased. The Python version is read from the
    file's header comment ("Python 3.12.12"), or ``None`` when absent.
    """
    text = lock_file.read_text(encoding="utf-8")
    packages = {}
    for line in text.splitlines():
        match = re.match(r"\s*([A-Za-z0-9_.\-]+)==(\S+)", line)
        if match:
            packages[match.group(1).lower()] = match.group(2)
    python = re.search(r"Python (\d+\.\d+\.\d+)", text)
    return packages, (python.group(1) if python else None)


def _pinned_software(t, version):
    """Return the manifest's software block with every volatile value pinned.

    The layout comes from the pipeline's own ``_software_provenance`` so
    that a package it starts recording appears here too. Package versions
    are those of requirements-lock.txt (``None`` for a package the locked
    environment does not have); the git fields are ``None``, as for an
    installed copy.
    """
    layout = t._software_provenance()
    packages, python = _lock_versions()
    pinned = {key: None for key in layout}
    pinned["version"] = version
    pinned["packages"] = {
        name: python if name == "python" else packages.get(name.lower())
        for name in layout["packages"]}
    return pinned


def _open_lf(file, mode="r", *args, **kwargs):
    """``open`` that writes text with LF line endings on every platform."""
    if any(flag in mode for flag in "wax") and "b" not in mode \
            and len(args) < 4 and "newline" not in kwargs:
        kwargs["newline"] = "\n"
    return builtins.open(file, mode, *args, **kwargs)


@contextlib.contextmanager
def _stub_module(name, stub):
    """Make ``import <name>`` return *stub* inside the block, then restore."""
    missing = object()
    previous = sys.modules.get(name, missing)
    sys.modules[name] = stub
    try:
        yield
    finally:
        if previous is missing:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def import_pipeline():
    """Return the ``transcription`` module, importing it without transformers.

    Nothing here runs a model, and importing transformers' pipeline takes
    minutes and several gigabytes on a small machine, so transformers is
    hidden while ``transcription`` is first imported. A process that has
    already imported either module is left as it is.
    """
    if "transcription" in sys.modules:
        return sys.modules["transcription"]
    hide = "transformers" not in sys.modules
    if hide:
        sys.modules["transformers"] = None
    try:
        import transcription  # noqa: PLC0415
    finally:
        if hide and sys.modules.get("transformers", 0) is None:
            del sys.modules["transformers"]
    return transcription


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_variant(variant: str, destination: Path) -> list[Path]:
    """Write one variant's files into *destination* and return their paths.

    Runs ``transcription.main`` with :data:`BASE_ARGS` plus the variant's
    flags, with the replacements described in the module docstring, and
    writes the outputs straight into *destination* (created if needed).

    Raises:
        KeyError: *variant* is not in :data:`VARIANTS`.
        RuntimeError: the pipeline did not exit 0; the message carries its
            console output.
    """
    import provenance  # noqa: PLC0415

    t = import_pipeline()
    flags = VARIANTS[variant]
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _, _, duration = _timeline()
    version = t._latest_release() or "unreleased"
    software = _pinned_software(t, version)
    log = io.StringIO()

    with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
        audio = Path(tmp) / AUDIO_NAME
        with wave.open(str(audio), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)

        patch = stack.enter_context
        patch(mock.patch.object(t, "AUDIO_LIBS_AVAILABLE", True))
        patch(mock.patch.object(t, "TRANSFORMERS_AVAILABLE", True))
        patch(mock.patch.object(t, "TRANSCRIPTS_DIR", str(destination)))
        patch(mock.patch.object(t, "transcribe_audio_only", _asr_result))
        patch(mock.patch.object(t, "perform_speaker_diarization",
                                _diarisation(t)))
        patch(mock.patch.object(t, "create_word_document",
                                lambda *_a, **_k: True))
        patch(mock.patch.object(t, "datetime", _PinnedClock))
        patch(mock.patch.object(provenance, "datetime", _PinnedClock))
        patch(mock.patch.object(t, "get_latest_version", lambda: version))
        patch(mock.patch.object(t, "_software_provenance", lambda: software))
        patch(mock.patch.object(t, "open", _open_lf, create=True))
        patch(mock.patch.dict(os.environ))
        os.environ.pop("TRANSCRIPTION_SIGNING_KEY", None)
        patch(_stub_module("librosa", types.SimpleNamespace(
            get_duration=lambda *_a, **_k: duration)))
        patch(mock.patch.object(sys, "argv",
                                ["transcription.py", str(audio),
                                 *BASE_ARGS, *flags]))
        patch(contextlib.redirect_stdout(log))
        patch(contextlib.redirect_stderr(log))
        try:
            t.main()
            code = 0
        except SystemExit as exit_:
            code = exit_.code
    if code != 0:
        raise RuntimeError(f"{variant}: the pipeline exited {code}\n"
                           f"{log.getvalue()}")

    # The manifest is written by provenance through Path.write_text, which
    # the LF patch does not reach. Its line endings are not part of any
    # digest, so they are normalised here to match the other files.
    written = sorted(p for p in destination.iterdir() if p.is_file())
    for path in written:
        data = path.read_bytes()
        if b"\r\n" in data:
            path.write_bytes(data.replace(b"\r\n", b"\n"))
    return written


def main() -> None:
    """Regenerate every variant under :data:`BASE`, replacing what is there."""
    for variant in VARIANTS:
        directory = BASE / variant
        if directory.is_dir():
            for stale in directory.iterdir():
                if stale.is_file():
                    stale.unlink()
        generate_variant(variant, directory)

    print("Generated files:")
    for variant in VARIANTS:
        for f in sorted((BASE / variant).iterdir()):
            print(f"  {f.relative_to(REPO).as_posix()}  "
                  f"({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
