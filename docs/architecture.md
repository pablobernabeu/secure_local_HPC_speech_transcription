# System architecture

The workflow is a set of top-level Python modules with one entry point,
`transcription.py`, and an evaluation package that measures what it does.
`transcription.py` holds the pipeline itself; the other modules each own
one concern that the pipeline, the evaluation code or a user calls
separately. The terms used here are defined in [glossary.md](glossary.md).

## Modules

| Module | Role |
| --- | --- |
| `transcription.py` | Command-line entry point (`main`) and the pipeline, `process_audio_file`: audio enhancement, speech recognition, the language gate, speaker attribution, text clean-up, name masking and every output file. Also installed as the `transcribe` command. |
| `audio_io.py` | Decodes any supported recording to a 16 kHz mono array, with soundfile first and ffmpeg for compressed formats. `python -m audio_io` reports what the machine can decode. |
| `confidence.py` | The review flags: heuristics that mark segments whose shape suggests hallucination or a decoding loop, written to `_review.json`. `python -m confidence` runs them on an existing transcript. |
| `provenance.py` | Writes the run manifest (SHA-256 of every artefact, the input's digest and the run settings, with an HMAC when `TRANSCRIPTION_SIGNING_KEY` is set) and verifies it with `python -m provenance verify`. |
| `ner_masking.py` | The optional named-entity stage of name masking, loaded offline at a pinned revision. Used through the Python API and the masking benchmark, not by the command line. |
| `audio_redaction.py` | Silences or bleeps the spans of masked words in a recording, from a timestamped transcript. |
| `voice_anonymisation.py` | Disguises a voice with the McAdams transformation. |
| `preflight.py` | The environment check, `python -m preflight`, and the shared HuggingFace token lookup. |
| `local_app/gui.py` | A Tk desktop front end that builds a `transcription.py` command and runs it in a subprocess. |
| `evaluation/` | The benchmarks behind the manuscript: WER and the condition sweep, diarisation error, timestamps, masking, anonymisation, disfluency, determinism and the compute footprint. See [evaluation.md](evaluation.md) and [hpc/README.md](../hpc/README.md). |
| `hpc/`, `setup/`, `tools/` | SLURM job scripts, installation and model-download scripts, and maintenance scripts. |

`setup.py` installs the top-level modules through `py_modules` and
`evaluation` and `local_app` as packages; `transcription.py` imports
`audio_io`, `confidence` and `provenance`, so all of them must be present
for a run to write its review file and manifest.

## Processing stages

`process_audio_file` runs these stages in order for one recording.

1. Audio enhancement, only with `--enhance-audio`: decoding to 16 kHz
   mono, amplification, spectral noise subtraction against a noise
   profile taken from the first half second (which is assumed to hold no
   speech), dynamic range compression and peak limiting. The enhanced audio goes to a temporary file, or to
   `output/enhanced_audio/` with `--save-enhanced-audio`.
2. Speaker diarisation, only with `--speaker-attribution`. The pipeline is
   loaded from `--diarization-config`, then `--diarization-model-path`,
   then the HuggingFace loader; if a named local pipeline fails, the Hub
   is not tried. The recording is decoded with `audio_io` and handed to
   pyannote as a waveform.
3. Speech recognition with the Whisper model given by `--model`
   (`openai/whisper-large-v3` by default), on a GPU when one is available.
   Word timestamps are requested with `--timestamps` or
   `--speaker-attribution`.
4. The language gate. The transcript language is `--language` when given,
   otherwise the language the model detected, otherwise English (recorded
   as assumed). It decides which clean-text stages run in step 7 and, when
   the common-word filter was not set explicitly, whether that filter is
   on.
5. Name masking set-up, only with `--mask-personal-names`: the curated
   dictionary (or the Facebook lists), filtered and with exclusions
   applied.
6. Timestamped outputs, with `--timestamps` or `--speaker-attribution`:
   the raw `_transcript.json` and `_transcript.vtt`, written from the
   model output before any clean-up or masking; with masking, the
   `_transcript_redacted` pair with the same timings and the names masked;
   and `_review.json`.
7. Text processing, applied to the plain transcript and, when speaker
   labels were applied, to each speaker turn separately: removal of emoji
   and symbol artefacts, the optional repetition repair
   (`--fix-spurious-repetitions`), the eight clean-text stages of
   `CLEAN_TEXT_STAGES` (the English-only ones skipped for other
   languages), then name masking.
8. The transcript as `.txt` and `.docx`, and with speaker labels a second
   `_with_speakers` pair; with `--save-name-masking-logs`, the masking log.
9. The manifest, `_manifest.json`, covering every artefact the run wrote.

A run that could not produce something it was asked for, such as speaker
labels when diarisation failed, writes what it can, lists what is
missing and reports itself incomplete.

## Name masking

Masking works word by word, sentence by sentence. A word is masked when
it is capitalised and is in the name dictionary, and replaced with
`[SURNAME]` for a dictionary surname and `[NAME]` otherwise; an honorific
followed by a capitalised dictionary name becomes `[TITLE]`. The
capitalisation requirement is deliberate: it is what keeps ordinary
lower-case words from being masked, and it is also why a name
transcribed in lower case is not masked. The masker's `case_insensitive`
parameter drops the requirement, but no command-line option sets it.
The common-word filter removes from the dictionary names that are also
common English words, and names shorter than three letters. The optional
named-entity stage adds further masks and never removes one. Each
masking-log row records which rule applied.

## Output artefacts

Every run writes `<name>_transcript.txt`, `<name>_transcript.docx` and
`<name>_manifest.json` to `output/transcripts/`, where `<name>` is
`--output-name` or the recording's name. The other artefacts are listed,
with the options that produce them, in the README's output structure.

## Enhancement parameters

| Parameter | Value | Description |
| --- | --- | --- |
| Sampling rate | 16 kHz | Rate the audio is resampled to |
| Noise reference | first 0.5 s | Segment used to estimate the noise spectrum |
| Noise alpha | 2.0 | Spectral subtraction coefficient |
| Compression | 4:1 above 0.1 | Dynamic range compression |
| Gain | 3.61x | Amplification, applied first |
| Peak limit | 0.95 | Level the output is scaled down to when it exceeds it |

These are the constants of `enhance_audio`, which calls them the
'interview_clarity' preset. The source of their values is not recorded.
