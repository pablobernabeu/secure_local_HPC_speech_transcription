# Local desktop application

For users without HPC access, the project ships with a lightweight,
cross-platform graphical interface that wraps the same Python pipeline
used by the SLURM scripts. It runs on Windows, macOS and Linux from a
single command and requires no additional dependency: the interface is
built on Tk, which is part of the Python standard library.

## Launching

From the root of a checkout:

```bash
python -m local_app.gui
```

The window exposes the main options of the command-line interface
(model, language, audio enhancement, name masking, repetition fixing,
speaker attribution with an optional local diarisation model path,
JSON/VTT timestamps and a custom output name); the others, such as the
masking-language and speaker-count options, are available only on the
command line. When the user presses *Run transcription*, the application
invokes `transcription.py` in a background subprocess and streams its
log into the GUI in real time, so the Tk event loop never blocks on
long inference.

## Why Tk rather than a packaged GUI framework

Two design constraints drove this choice. First, the workflow targets
research environments that often forbid installing arbitrary system
libraries; Tk ships with CPython on all three desktop platforms and
needs nothing extra. Second, the GUI must remain a thin wrapper rather
than a competing entry point: by shelling out to `transcription.py`,
the local interface inherits every flag and bug-fix that lands in the
command-line tool without further work.

## Behaviour parity with the command line

The local GUI calls `transcription.py` with the same flags the SLURM
scripts pass, so the output layout under `output/` is identical. In
particular, enabling the *Emit JSON/VTT timestamps* tick adds `--timestamps`
to the call, which produces `*_transcript.json` and `*_transcript.vtt`
alongside the regular text and Word transcripts (see
[evaluation.md](evaluation.md) for how these feed into WER scoring).

## Checking repeated passages

The review written during transcription uses the established checks for
repeated cues, short decoding loops and implausible speech rates. Two
additional checks can be run on the timestamped JSON after transcription:

```bash
python -m confidence output/transcripts/interview_transcript.json \
    --flag-zero-duration --repeated-passage-words 8 \
    --repeated-passage-window 60 --json review_extended.json
```

This flags non-empty cues with equal start and end times, and both copies
of a matching run of eight or more tokens, even when the run crosses cue
boundaries. The window compares the start times of the cues containing
each copy's first token. Case and punctuation are ignored; numbers are
retained, so changes in a reported quantity can distinguish two passages.
An apostrophe splits a word, so a contraction such as *don't* counts as
two tokens, and a shared clause of six or seven spoken words with
contractions can reach the eight-token setting.
Missing, invalid or decreasing times interrupt the passage search.
The report records the chosen settings and links a flagged cue to the
indices of a matching partner. The command writes a separate review;
it does not edit the transcript or its timings.

Eight tokens and sixty seconds are provisional settings motivated by the
unflagged passages in the case study, not thresholds fitted to annotated
speech. A speaker may repeat a long clause intentionally, and a copy
with altered wording or outside the window can be missed. Listen to both
passages before deciding what happened. Estimating precision and recall
will require recordings with independently annotated repetitions and
recognition errors. Both checks remain off in automatic transcription,
so the archived reviews and their reported counts remain reproducible.

## Packaging for non-technical users

For one-click distribution to colleagues who do not use a terminal, the
module can be frozen with `pyinstaller`:

```bash
pyinstaller --noconfirm --windowed --name "SecureTranscription" \
    -m local_app.gui
```

The resulting bundle still requires the model cache (~3 GB for
`openai/whisper-large-v3`) to be available on first run; for offline
deployments this should be pre-populated under the `HF_HOME` directory
described in [TROUBLESHOOTING.md](../TROUBLESHOOTING.md#models-and-the-cache).
