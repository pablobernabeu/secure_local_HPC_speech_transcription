
# Secure and scalable speech transcription for local and HPC

Automated speech transcription with optional audio enhancement, speaker attribution and text processing. It runs on a laptop or as SLURM (Simple Linux Utility for Resource Management) jobs on a high-performance computing (HPC) cluster, so that recordings never leave the institution that holds them.

## Overview

The workflow handles speech processing from end to end: optional audio enhancement, machine learning-based transcription, text cleaning and privacy protection. The pipeline supports batch processing with parallel job execution for large audio datasets.

The main features are:

- OpenAI Whisper Large v3 transcription, on a GPU (Graphics Processing Unit) when one is available
- Optional audio enhancement and noise reduction (off by default)
- Multilingual personal name masking (1,793 curated names across nine languages, optional Facebook database with 730K+ names)
- Speaker attribution (diarisation) for multi-speaker recordings
- HPC batch processing with SLURM job scheduling
- Plain-text and Microsoft Word transcripts, with optional timestamped JSON and WebVTT

Example outputs are in [example_output](/example_output). The four variants under `example_output/variants/` show, for a short synthetic interview, the files the current code writes under each combination of `--timestamps` and `--speaker-attribution`. `tools/generate_example_variants.py` regenerates them by running the pipeline itself (see [tools/README.md](tools/README.md)). The four transcripts under `example_output/transcripts/` are older: release 1.0.0 wrote them in November 2025, and they carry three defects fixed since, which [their README](example_output/transcripts/README.md) lists. They show the layout of a long transcript, not the quality of the current output.

## System requirements

The workflow needs Python 3.11 or later, a floor that `setup.py` and `python -m preflight` enforce. The ARC environment that produced the published results runs Python 3.12. A CUDA-capable GPU speeds transcription up but is not required, and the HPC transcription jobs themselves run on CPU. SLURM is needed only for the HPC scripts.

`requirements.txt` states the lowest versions the code supports. `requirements-lock.txt` is a `pip freeze` of the ARC environment the result jobs run in, taken on 2026-09-26 (Python 3.12.12, torch 2.5.1+cu121, transformers 4.57.1, pyannote.audio 3.4.0), for rebuilding that environment and checking another against it. It does not say what produced a given result. The environment was changed in place during the project, so the lock shows it as it stood that day, which is not necessarily what every past job ran, as its header says. Each result records its own versions instead. The summaries the evaluation modules write carry a `run_metadata` block (`run` in the timestamp summary). It holds the code commit, whether the working tree was clean, the Python version and the versions of the packages that can move a number. `evaluation/revisions.py` pins the commit of every Hugging Face model and dataset the committed runs loaded, and the WER, diarisation, timestamp and anonymisation summaries record the revisions they used. Each HPC job that writes results also records its Python stack, loaded modules, GPU and git commit in an `environment/` subdirectory beside its outputs. The diarisation summaries record `pyannote_audio_version`, 3.4.0 for the committed runs, and pyannote.audio 4.x is not supported. `requirements-dev.txt` holds the development tools: pytest, pytest-cov and the linter ruff.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for known issues.

## Installation

### Local

```bash
git clone https://github.com/pablobernabeu/secure_local_HPC_speech_transcription.git
cd secure_local_HPC_speech_transcription

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt   # add -r requirements-dev.txt to run the tests
python -m preflight               # check the environment
```

For GPU transcription, install a CUDA build of torch and torchaudio at matching versions. `python -m preflight` prints the command for the installed torch. To install the job environment's exact versions instead of the floors, install from `requirements-lock.txt`, which needs Linux and `--extra-index-url https://download.pytorch.org/whl/cu121` for the `+cu121` builds. `python -m preflight --lock requirements-lock.txt` reports any installed version that differs from it.

### HPC

On Oxford ARC, activate the project environment before installing anything, so that packages go to project storage, outside the home-directory quota:

```bash
source activate_project_env_arc.sh
python setup/install_requirements.py
```

`setup/install_requirements.py` installs `requirements.txt` into the active environment, checks that the core packages import, and then offers to run the speaker-attribution wizard. It does not create the environment. [ARC_USAGE_GUIDE.md](ARC_USAGE_GUIDE.md) describes the ARC layout, and [hpc/HPC_SETUP_GUIDE.md](hpc/HPC_SETUP_GUIDE.md) how to set up on another cluster. Speaker attribution needs a HuggingFace token and a one-off model download ([PYANNOTE_SETUP_GUIDE.md](PYANNOTE_SETUP_GUIDE.md)).

After the first session, activate the environment each time you log in:

```bash
source activate_project_env_arc.sh
```

## Quick start

### On an HPC cluster

```bash
# Every recording in the input directory ($TRANSCRIPTION_AUDIO_DIR, or
# $DATA/speech_transcription_env/audio_input by default)
hpc/submit_transcription.sh --mask-personal-names --language english

# One recording with its own output name
hpc/submit_transcription.sh --single-file /path/to/interview.wav --output-name "client_call" --mask-personal-names
```

### On your own machine

```bash
# Runs immediately on the current machine
python transcription.py "audio_input/test.wav" --mask-personal-names --language english

# With audio enhancement (slower)
python transcription.py "audio_input/test.wav" --mask-personal-names --language english --enhance-audio
```

### Masking names the dictionary has never seen

Name masking works from a curated multilingual dictionary, so it redacts
only names it already knows. Measured on injected names, recall on names
held out of that dictionary is zero. That matters, because the names most
worth protecting in a research recording are usually participants' names,
which can be any name at all.

An optional second stage, in `ner_masking.py`, recognises people from
context, using a small named-entity recognition (NER) model that runs on
CPU. It is zero-shot, meaning it is told at run time which entity types
to look for, with no training on a fixed list. It is additive by
construction: it can only propose further words to redact, never
withdraw one the dictionary caught. Each row of the masking log records
in its `source` column which rule was responsible (`dictionary`, `ner`
or `title`), so the stages can be audited separately.

The model is never downloaded at transcription time. Install the package
and fetch the model once, at a pinned revision, with:

```bash
pip install gliner                 # optional
python -m ner_masking --download   # one-off download into the HuggingFace cache
```

After that it loads from the local cache only, so the offline guarantee
holds. The stage is not yet switchable from `transcription.py` or the
desktop application. It is available through the Python API, by passing
the detector to the masker, and through the masking benchmark:

```python
from ner_masking import load_person_detector
from transcription import create_enhanced_name_masker

detector = load_person_detector()          # None when gliner or the model is missing
mask, get_log = create_enhanced_name_masker(ner_detector=detector)
```

On injected names, it lifts recall on names the dictionary has never
seen, which are precisely the names a list cannot hold, from zero to
0.41 (`output/evaluation/masking_summary_ner.json`). Like the
dictionary, it only considers capitalised words, so the lower-case half
of those names stays unmasked. That gate is deliberate and measured.
Without it, the stage marks references to people as well as personal
*names*. On a real transcript about transcription research, it proposed
"speaker one", "the researcher", "the user" and even "we", fifteen
false redactions beside the dictionary's three. Two of those
three were genuine names, and the third was "Jordan", in a speaker's
example of a masker taking the country for a person. Every reference was
lower-case and every real name capitalised, so the gate removes all
fifteen. The masker's `case_insensitive` parameter (the benchmark's
`--case-insensitive`) relaxes the gate for both stages together, and for
the name after an honorific. It is there for users who want the extra
recall and accept the cost. Like the NER stage, it is not a
`transcription.py` option. The measurements are in
[`output/case_study/ner_false_positive_test.md`](output/case_study/ner_false_positive_test.md).

To see what it detects, and to measure the trade-off on injected names
(both need the one-off download above, and exit with an error without it):

```bash
python -m ner_masking --download   # once, if not done above
python -m ner_masking "Doctor Kowalczyk met Aleksandra in Warsaw."
python -m evaluation.benchmark_masking --ner --output-dir my_masking_benchmark
```

Without `--output-dir`, the benchmark writes into `output/evaluation/`,
where it replaces the committed results.

### Check your environment first

The costly failures with tools like torch and ffmpeg share a shape: the
piece is missing or mislinked, the job fails minutes or hours later, and the
error names neither the cause nor the fix. One command answers all of it in
seconds, with a remedy per finding:

```bash
python -m preflight
```

It checks the Python version, torch and CUDA (with the GPU's name and
memory when present), transformers against the supported range, audio
decoding including ffmpeg, pyannote and its HuggingFace token, and the
optional extras. On a laptop or login node, a missing GPU is a warning.
`--gpu-required` makes it a failure, and `--diarisation-required` (also
spelt `--diarization-required`) does the same for a missing pyannote or
token and for a damaged cached copy of the pipeline's configuration, which
no token repairs. `--lock requirements-lock.txt` also fails on any
installed version that differs from the lock, and `--json PATH` writes the
findings to a file.

Every HPC job script runs this check as a gate before doing any work,
with `--gpu-required` in the GPU jobs and `--diarisation-required` as
well in the diarisation jobs. The test job and the CPU determinism job
add `--lock`. A failure stops the job with exit status 2 (4 in the
case-study job) before any work is done. No job installs or repairs a
package itself: the remedy printed in the log is applied from a login
node (see [hpc/README.md](hpc/README.md)).

### Audio formats

WAV, FLAC, OGG and MP3 are read directly. Compressed containers such as
`.m4a`, `.mp4`, `.aac` and `.wma`, which is what most podcasts and phone
recorders produce, are decoded through ffmpeg. A bundled ffmpeg arrives with
`imageio-ffmpeg` in the requirements, so this normally needs no setup.

To check what the current environment can read, and to probe one file:

```bash
python -m audio_io                    # what this machine can decode
python -m audio_io recording.m4a      # try one file
```

If it reports no ffmpeg, `pip install imageio-ffmpeg` restores support for
compressed formats. Converting to WAV first is always a valid alternative.

### Set the language explicitly

`--language` does more than hint the model. It also selects the
post-processing rules, because several clean-text stages assume English
vocabulary: the contraction repair rewrites a bare `im` to `I'm`, which is
correct in English and wrong in German, where `im` means "in the".

When `--language` is omitted, the language is detected from the audio and the
terminal prints a warning saying which language was assumed. Detection is
usually right, but it is a guess, and a wrong guess applies the wrong rules to
the whole transcript. Passing `--language` removes that risk and is
recommended on every run, including English.

The English rules are skipped for any other language, so a non-English
transcript receives the general stages only (whitespace, sentence
capitalisation, punctuation spacing). Measured on the FLEURS test splits,
this leaves the composite word-error-neutral across the six languages
tested ([docs/conditions_audit.md](docs/conditions_audit.md#the-language-gate)).

### Reviewing segments the model may have invented

Whisper-family models do not fall silent on silence, music or badly degraded
audio: they emit fluent text that was never spoken, and they loop short
phrases. Such a segment reads no differently from a correct one, so a run
with `--timestamps` or `--speaker-attribution` also writes
`<name>_review.json` marking the segments whose shape is characteristic of
those failures, and prints how many were flagged. The same check runs
standalone against any timestamped transcript the workflow wrote:

```bash
python -m confidence output/transcripts/interview_transcript.json
```

The flags are heuristics computed from the text and its timings, because the
transcription pipeline does not expose the model's own confidence. Treat a flag
as a prompt to listen to that passage, not as proof of an error.

### Verifying that a transcript is unaltered

Each run writes `<name>_manifest.json` beside its outputs, listing every
artefact the run wrote with its SHA-256, the digest of the input recording,
and the settings and software versions that produced them. When the input
was converted from another file, `--source-audio` and
`--source-derivation` add the original's digest and the conversion. The
manifest does not cover the masking log or saved enhanced audio, which are
written elsewhere. To check a set of files months later, or on receiving
them from someone else:

```bash
python -m provenance verify output/transcripts/interview_manifest.json
```

It reports any artefact that has been modified, removed or added since the run,
and exits non-zero if so.

By default, this gives *integrity*: it detects accidental corruption and casual
editing. It does not prove authorship, because anyone who can edit a file can
recompute its digest. For *authenticity*, set a secret key before transcribing
and supply the same key when verifying, which adds an HMAC that cannot be
recomputed without it:

```bash
export TRANSCRIPTION_SIGNING_KEY="your-secret-key"
```

The key is never written to the manifest or printed. Keep it outside the output
tree, as you would the HuggingFace token.

See [docs/hpc_usage.md](docs/hpc_usage.md) for HPC usage examples and [docs/advanced_usage.md](docs/advanced_usage.md) for advanced features.

## Command-line options

`python transcription.py --help` lists every option. `hpc/submit_transcription.sh` consumes the four HPC options below and passes every other option to `transcription.py` unchanged, rejecting any it does not recognise before submitting.

| Option | Description |
|--------|-------------|
| `--model MODEL` | HuggingFace model ID (default: openai/whisper-large-v3) |
| `--output-name <name>` | Custom name for output files (without extension). On HPC, only with `--single-file` |
| `--language LANG` | Transcription language (e.g. `english`, `spanish`, `french`). Recommended on every run. Default: auto-detect, which also selects the post-processing rules, so a wrong guess degrades the output |
| `--single-file <path>` | HPC only: transcribe exactly this file instead of the whole input directory |
| `--time-limit HH:MM:SS` | HPC only: wall-clock limit per task (default 08:00:00) |
| `--memory <size>` | HPC only: memory per task (default 32G), e.g. `16G`, `64G` |
| `--enhance-audio` | Enable audio enhancement (off by default) |
| `--mask-personal-names` | Enable personal name masking (off by default) |
| `--fix-spurious-repetitions` | Remove spurious repetitions from Whisper (off by default) |
| `--save-name-masking-logs` | Save each masked word, with its sentence and the rule that masked it, to `name_masking_logs/name_replacements_<name>.csv` (off by default) |
| `--save-enhanced-audio` | Keep the enhanced audio in `output/enhanced_audio/` (off by default) |
| `--use-facebook-names-for-masking` | Use Facebook first names database (~730K names, off by default) |
| `--use-facebook-surnames-for-masking` | Use Facebook surnames database (~980K surnames, off by default) |
| `--languages-for-name-masking LANG ...` | Languages of the curated dictionary to use, as full names in any letter case (`english`, `Spanish`). An unknown name or an ISO code such as `en` is an error. Default: all nine |
| `--exclude-common-english-words-from-name-masking` / `--no-exclude-common-english-words-from-name-masking` | Leave out of the dictionary names that are also common English words ("will", "long"). Default: on when the language, given or detected, is English, otherwise off |
| `--exclude-names-from-masking "name1,name2"` | Comma-separated list of names to exclude |
| `--exclude-names-file path/to/file.txt` | File with names to exclude (one per line) |
| `--speaker-attribution` | Enable speaker diarisation (off by default, requires a HuggingFace token). Also writes the timestamped outputs |
| `--num-speakers N` | Exact number of speakers, when known. Not a free improvement: on the AMI benchmark, fixing the true count made diarisation worse in ten of sixteen meetings (see [docs/advanced_usage.md](docs/advanced_usage.md)). Takes precedence over the two options below |
| `--min-speakers N` / `--max-speakers N` | Bounds on the number of speakers, for when only a range is known |
| `--vad-onset T` / `--vad-offset T` | Thresholds for voice activity detection, the step that decides which parts of a recording contain speech. They apply only to older diarisation pipelines. The default model has no such threshold, and the run reports that the setting has no effect |
| `--diarization-model-path PATH` / `--diarization-config PATH` | Load the diarisation pipeline from local storage instead of the HuggingFace cache, for fully offline operation. The model path may be a `config.yaml` or a directory holding one. If a local pipeline was named and cannot be loaded, the Hub model is not tried: the run writes the transcript without speaker labels and reports itself incomplete. British spellings (`--diarisation-…`) are accepted too |
| `--timestamps` | Emit word- and segment-level timestamps as `_transcript.json` and `_transcript.vtt` alongside the plain-text transcript (captured before name masking, so timing remains synchronised with the raw model output). With `--mask-personal-names`, a `_transcript_redacted.json`/`_transcript_redacted.vtt` pair is written beside them, same timings with the names masked |
| `--redacted-timestamps-only` | Write only the redacted timestamped artefacts, suppressing the unredacted pair. Requires `--mask-personal-names`. Use when the output tree may be exported wholesale |
| `--review-flag-zero-duration` | Also flag, in `<name>_review.json`, non-empty cues whose start and end times are equal. Off by default, and needs `--timestamps` or `--speaker-attribution` |
| `--review-repeated-passage-words N` / `--review-repeated-passage-window S` | Also flag both copies of a run of N or more tokens that recurs across cues within S seconds (60 by default), as when Whisper writes a passage twice. An apostrophe splits a word, so a contraction counts as two tokens. The suggested setting is 8. Off by default, and the run manifest records the settings |
| `--source-audio PATH` | The original recording the input was made from, such as the `.m4a` a WAV was decoded from. The run manifest records its name, size and SHA-256 under `source_audio`, beside the input's own digest, so the published recording can be tied to the transcripts. Ignored when the path is not an existing file |
| `--source-derivation TEXT` | How the input was made from `--source-audio`, for example the ffmpeg command. Recorded in the manifest with the source's digest |
| `-h, --help` | Show help message |

See [docs/advanced_usage.md](docs/advanced_usage.md) for detailed usage examples of advanced features.

## Output structure

```
output/
├── transcripts/                                    # one set per recording
│   ├── filename_transcript.txt                     # base transcript (always)
│   ├── filename_transcript.docx                    # base Word document (always)
│   ├── filename_transcript_with_speakers.txt       # with speaker labels (--speaker-attribution)
│   ├── filename_transcript_with_speakers.docx      # speaker-labelled Word document (--speaker-attribution)
│   ├── filename_transcript.json                    # raw, timestamped output (--timestamps or --speaker-attribution)
│   ├── filename_transcript.vtt                     # WebVTT captions (as above)
│   ├── filename_transcript_redacted.json           # names masked, same timings (as above, with --mask-personal-names)
│   ├── filename_transcript_redacted.vtt            # names masked, same timings (as above, with --mask-personal-names)
│   ├── filename_review.json                        # segments flagged for review (with the timestamped outputs)
│   └── filename_manifest.json                      # SHA-256 of every artefact and the run settings (always)
└── enhanced_audio/                                 # --save-enhanced-audio
    └── filename_enhanced.wav
name_masking_logs/
└── name_replacements_filename.csv                  # --save-name-masking-logs
```

`--redacted-timestamps-only` leaves out the unredacted `.json`/`.vtt` pair. The raw timestamped files contain every name the model heard, so keep them as local records and do not share them. The output directories and the masking logs are ignored by git, so a transcript cannot be committed by accident. To check that no logged name survives in the masked files, audit the directory holding `output/` and `name_masking_logs/` with `python -m evaluation.audit_artefacts --dir <that directory> --output-dir <a report directory>` ([docs/evaluation.md](docs/evaluation.md#auditing-a-runs-outputs-for-residual-names)).

## Evaluation

A small `evaluation` package benchmarks hypothesis transcripts against a reference corpus using [`jiwer`](https://github.com/jitsi/jiwer). Both sides are normalised (Unicode folding, lower-casing, punctuation stripping) before scoring, so that formatting differences are not counted as recognition errors.

```bash
# Your own transcripts against your own references, paired by file stem
python -m evaluation.wer \
    --hypothesis output/transcripts \
    --reference  <reference_dir> \
    --report     my_evaluation/wer_report.csv \
    --summary    my_evaluation/wer_summary.json

# HPC (SLURM), from the repository root: hypotheses, references, report directory
sbatch hpc/evaluate_wer.sh output/transcripts <reference_dir> my_evaluation
```

Without arguments, `hpc/evaluate_wer.sh` reads hypotheses from `output/transcripts/` in the repository, where the transcription jobs write them, and references from `$DATA/speech_transcription_env/reference_transcripts`. It writes `wer_report_transcripts.csv` and `wer_summary_transcripts.json` to `$DATA/speech_transcription_env/output/evaluation/inhouse/`, and refuses to start when that summary already exists, unless `OVERWRITE=1` is set or a third argument names another directory.

`<reference_dir>` holds one reference per recording, named after the recording. Each recording is scored once, from its `.txt`, else its `.json`, else its `.vtt`. `evaluation.wer` defaults to `output/evaluation/wer_report_transcripts.csv` and `wer_summary_transcripts.json`, which are distinct from the committed benchmark files the manuscript reads. Writing your own reports outside `output/evaluation/` keeps them apart from the committed results altogether. See [docs/evaluation.md](docs/evaluation.md) for the methodology, including the normalisation layer, the condition sweep and the SLURM directives used on HPC.

## Reproducing the published results

The results reported in the manuscript are committed under `output/evaluation/`, and the manuscript renders from those files without rerunning anything (see [manuscript/README.md](manuscript/README.md)). To check or rebuild them:

- [hpc/README.md](hpc/README.md) maps each evaluation job to its stage order, prerequisites, resources and outputs, and names the `hpc/runs/*.env` file holding the exact overrides and ARC job ID behind each committed result whose script defaults do not reproduce it.
- `output/evaluation/arc_job_ledger.csv` is the ARC scheduler's record of every job of the evaluation, 203 from 2026-05-16 to 2026-10-19, captured on 2026-10-30 after the last had finished, with each job's elapsed time and allocation. `output/evaluation/footprint_summary.json` is the compute estimated from it. The ledger's `gpu_type` column is the board of the node each GPU job ran on, from the node's GPU label and the card its jobs' logs name. Jobs 7746221 and 7746222, for example, ran on Tesla P100 PCIe cards. `arc_job_ledger_provenance.json` beside it holds the sacct query and the SHA-256 of the dump, which is not committed because it lists the shared account's other projects.
- [output/evaluation/README.md](output/evaluation/README.md) says which committed files are current and which are superseded runs kept as history, with the job or command and the commit behind each.
- `python tools/verify_regeneration.py` re-runs the producers of the committed results that need no GPU (the compute footprint, both paired-interval tables, the canonical normaliser's gain on AMI, the headline bootstrap interval, its reader-cluster sensitivity, the artefact audit and the masking benchmark's dictionary arm) into a temporary directory and compares every file with the committed copy, allowing for line endings. It exits 0 only when all match, and `--skip-masking` leaves out the slowest producer (see [tools/README.md](tools/README.md)).
- `requirements-lock.txt` is the `pip freeze` of the ARC job environment as it stood on 2026-09-26. What each result ran with is recorded beside it, in its summary's run metadata and its job's `environment/` record.
- The manuscript's "Data and code availability" section lists the datasets and the archived software version.

The test suite runs from the repository root with `python -m pytest -q`, after installing `requirements-dev.txt`. Tests whose optional dependencies are missing are skipped.

## Local desktop application

For users without HPC access, a lightweight cross-platform GUI wraps the same pipeline. It runs on Windows, macOS and Linux from a single command:

```bash
python -m local_app.gui
```

See [docs/local_app.md](docs/local_app.md) for the options it exposes and how to package it for colleagues who do not use a terminal.

## Documentation

Each document below has a single, distinct purpose. Start with the one that matches your role.

| Document | Purpose | Audience |
|----------|---------|----------|
| [docs/architecture.md](docs/architecture.md) | Module map, processing stages and output artefacts. | Reviewers, contributors. |
| [docs/glossary.md](docs/glossary.md) | One name for each concept, with the aliases still found in code and older documents. | Everyone. |
| [docs/advanced_usage.md](docs/advanced_usage.md) | Optional features: speaker attribution, audio redaction, repetition fixing, multilingual name masking. | End users. |
| [docs/evaluation.md](docs/evaluation.md) | WER benchmarking methodology, the `evaluation.wer` module, the condition sweep and the audit of a run's outputs for residual names. | Researchers reporting accuracy. |
| [docs/local_app.md](docs/local_app.md) | Cross-platform desktop GUI for non-HPC users. | Local users. |
| [docs/hpc_usage.md](docs/hpc_usage.md) | Transcribing recordings with the SLURM scripts. | HPC users on any cluster. |
| [hpc/README.md](hpc/README.md) | The evaluation jobs: stage order, outputs and the invocation behind each committed result. | Anyone rerunning the benchmarks. |
| [ARC_USAGE_GUIDE.md](ARC_USAGE_GUIDE.md) | How the workflow runs on the University of Oxford HPC, the reference deployment. | Oxford HPC users and those porting to another site. |
| [hpc/HPC_SETUP_GUIDE.md](hpc/HPC_SETUP_GUIDE.md) | Adapting the SLURM scripts for a *different* HPC site. | Administrators porting the workflow. |
| [PYANNOTE_SETUP_GUIDE.md](PYANNOTE_SETUP_GUIDE.md) | One-time configuration for speaker diarisation. | Users enabling `--speaker-attribution`. |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Known issues and their remedies. | Anyone encountering errors. |
| [setup/README.md](setup/README.md) | The installation, model-download and container scripts. | Anyone installing the workflow. |
| [tools/README.md](tools/README.md) | Maintenance scripts, including the regeneration check of the CPU-derived results. | Contributors, reviewers. |
| [docs/ci.md](docs/ci.md) | The GitHub Actions check of the committed statistical results. | Reviewers, contributors. |
| [manuscript/README.md](manuscript/README.md) | How the manuscript renders, and which committed results it reads. | Authors and reviewers. |
| [manuscript/manuscript.qmd](manuscript/manuscript.qmd) | Reproducible Quarto manuscript that renders its tables and figures from the committed results in `output/evaluation/`. | Authors and reviewers. |

## Licence

This project was developed by Dr Pablo Bernabeu at the Department of Education at the University of Oxford. The software, with the name dictionary it installs, is released under the [MIT licence](LICENSE), which matches the licence classifier the package has always declared. The manuscript, the documentation in `docs/`, the results in `output/` and the examples in `example_output/` are released under [CC BY 4.0](LICENSE-docs.md). Material by others keeps its own terms: the bundled APA citation style is CC BY-SA 3.0, and the corpus text some results reproduce keeps its corpus's licence.

## Citation

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23442766.svg)](https://doi.org/10.5281/zenodo.23442766)

If you use this workflow in your research, please cite:

> Bernabeu, P. (2026). *Secure and scalable speech transcription for local and HPC* (Version 2.1.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.23442766

The inputs behind the paper's English condition sweep, with the source of the commit that decoded them, are deposited separately at https://doi.org/10.5281/zenodo.23442874.

The recommended BibTeX entry is:

```text
@misc{secure_local_HPC_speech_transcription,
  author    = {Bernabeu, Pablo},
  title     = {Secure and scalable speech transcription for local and {HPC}},
  year      = {2026},
  publisher = {Zenodo},
  version   = {2.1.0},
  doi       = {10.5281/zenodo.23442766},
  url       = {https://doi.org/10.5281/zenodo.23442766}
}
```
