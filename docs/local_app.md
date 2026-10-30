# Local desktop application

For users without HPC access, the project ships with a lightweight,
cross-platform graphical interface that wraps the same Python pipeline
the SLURM scripts use. It runs on Windows, macOS and Linux from a single
command and needs no further Python package, because the interface is
built on Tk, which is part of the Python standard library.

## Launching

From the root of a checkout:

```bash
python -m local_app.gui
```

Some Linux distributions ship Tk as a separate operating-system package,
and their Python cannot import it until that package is installed. If
the launch stops at `import tkinter`, install `python3-tk` on Debian or
Ubuntu, or `python3-tkinter` on Fedora, with the system's package
manager, since pip cannot install it.

The window exposes the main options of the command-line interface: the
model, the language, audio enhancement, name masking, repetition fixing,
speaker attribution with an optional local diarisation model path,
JSON/VTT timestamps and a custom output name. The others, such as the
masking-language and speaker-count options and the two optional review
checks ([advanced_usage.md](advanced_usage.md#checking-repeated-passages)),
are available only on the command line. When the user presses *Run
transcription*, the application
invokes `transcription.py` in a background subprocess and streams its
log into the GUI in real time, so the Tk event loop never blocks on
long inference.

## Why Tk

Two design constraints led to Tk in place of a packaged GUI framework.
First, the workflow targets research environments that often forbid
installing arbitrary system libraries, and Tk ships with CPython on all
three desktop platforms, if on some Linux distributions as the separate
package described above. Second, the GUI must remain a thin wrapper and
not become a second entry point. Because it shells out to
`transcription.py`, the local interface inherits every fix that lands in
the command-line tool without further work.

## Behaviour parity with the command line

The local GUI calls `transcription.py` with the same flags the SLURM
scripts pass, so the output layout under `output/` is identical. In
particular, enabling the *Emit JSON/VTT timestamps* tick adds `--timestamps`
to the call, which produces `*_transcript.json` and `*_transcript.vtt`
alongside the regular text and Word transcripts (see
[evaluation.md](evaluation.md) for how these feed into WER scoring).

## Packaging for non-technical users

For one-click distribution to colleagues who do not use a terminal, the
module can be frozen with `pyinstaller`:

```bash
pyinstaller --noconfirm --windowed --name "SecureTranscription" \
    -m local_app.gui
```

The resulting bundle still requires the model cache (~3 GB for
`openai/whisper-large-v3`) to be available on first run. For offline
deployments, fill it beforehand under the `HF_HOME` directory described
in [TROUBLESHOOTING.md](../TROUBLESHOOTING.md#models-and-the-cache).
