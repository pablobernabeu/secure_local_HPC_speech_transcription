# Troubleshooting

Start with `python -m preflight`. In a few seconds it checks the Python
version, torch and CUDA, transformers, audio decoding including ffmpeg,
pyannote and the HuggingFace token, and whether torch, transformers and
pyannote load from the active environment, and it prints a remedy for
each problem it finds. Add `--gpu-required` on a GPU node, or
`--diarisation-required` when you need speaker attribution, to make those
checks fail rather than warn. `--lock requirements-lock.txt` also compares
every installed version with the lock. Every HPC job runs it before doing
any work and stops with exit 2 (exit 4 in the case study) when it fails,
so the report at the top of a failed job's log is the place to start. On
ARC, run it on a compute node rather than a login node: the login nodes
cap virtual memory at 2 GB, under which the environment's CUDA build of
torch cannot load.

## Versions

`requirements.txt` gives the lowest versions the code supports: Python
3.11 or later, transformers 4.56 or later (the language detection the
post-processing relies on needs 4.45, and the timestamp benchmark's
`pipeline(dtype=...)` needs 4.56) and pyannote.audio 3.1 or later, below 4.
The environment that produced the published results is recorded in
`requirements-lock.txt`, and each HPC job that writes results records
the versions it ran with in an `environment/` subdirectory beside them.
The committed diarisation results were produced with pyannote.audio
3.4.0, the version recorded in `output/evaluation/der_summary.json`.

pyannote.audio 4.x is not supported; install with
`pip install "pyannote.audio>=3.1,<4"`. For GPU use, torch and torchaudio
must be CUDA builds of matching versions; `python -m preflight` prints the
install command for the torch it finds. Between transformers 4.48 and 5.6
the ASR pipeline's own language report is always empty, which is why the
workflow asks the model directly and why preflight flags those versions.
The HPC jobs never install anything: repair the environment from a login
node, ideally by installing `requirements-lock.txt`, and resubmit.

## Audio files

On HPC, the wrapper reads recordings from `$TRANSCRIPTION_AUDIO_DIR`, or
`$DATA/speech_transcription_env/audio_input` by default, and says which
directory it read when it finds nothing. It picks up `.wav`, `.mp3`,
`.m4a`, `.flac`, `.ogg` and `.aac` files in any letter case. Locally,
`transcription.py` takes the path you give it.

A compressed file that will not decode usually means no ffmpeg is
available: `python -m audio_io` reports what the current environment can
read, and `python -m audio_io recording.m4a` tries one file. Installing
`imageio-ffmpeg` (in the requirements) provides a bundled ffmpeg.

## Models and the cache

Model weights are cached under `HF_HOME` (by default
`~/.cache/huggingface`). Set `HF_HOME` to a directory with enough space
and use the same value for downloading and for every run; on ARC,
`activate_project_env_arc.sh` sets it to
`$DATA/speech_transcription_env/.huggingface_cache`. `TRANSFORMERS_CACHE`
is deprecated and would override `HF_HOME` for some libraries, so leave
it unset; the HPC jobs unset it.

For offline use, or before a batch on nodes without network access,
fetch the models first:

```bash
python setup/download_model.py        # Whisper, openai/whisper-large-v3 by default
python setup/cache_pyannote_arc.py    # the diarisation models (needs a HuggingFace token)
python -m ner_masking --download      # the optional NER model
```

pyannote.audio 3.x does not read `HF_HOME`: it loads its models from
`$PYANNOTE_CACHE`, or `~/.cache/torch/pyannote` when that is unset, and
`setup/cache_pyannote_arc.py` downloads into that same directory.

When loading the diarisation pipeline fails with `KeyError: 'name'`, the
cached `config.yaml` of `pyannote/speaker-diarization-3.1` has been
damaged: pyannote reads the pipeline's name from it, and the damaged file
has none. Neither a token nor a new download repairs it, because a
download keeps a file the cache already holds. `python -m preflight`
checks that each cached snapshot's `config.yaml` can load and that every
file in the pipeline's `blobs` directory, linked or not, still hashes to
the name it is stored under. It names each damaged file and how to
replace it. With `--diarisation-required` it fails, and the job scripts
of the DER benchmark and sweep, the fine-tuning, the case study and the
anonymisation benchmark pass that option, so those jobs stop before
doing any work.

Outside those jobs, the message depends on the caller. `transcription.py`
runs the same check when the load fails. If it finds the damage, the
error names the damaged file, says that neither a token nor a new
download repairs it and gives the fix, ending with
`Underlying error: KeyError: 'name'`. The DER benchmark does not catch
the error and stops with a traceback ending in `KeyError: 'name'`. The
anonymisation benchmark prints
`could not reuse the diarisation pipeline (KeyError: 'name')`, records
the reason in its summary and loads the embedding model directly.

The jobs that met a damaged config in September 2026 (incident
NEW-INC-01, under Observations from ARC in `ISSUES.md`) ran code at
6f9bf56, from before these checks, and printed less. Case-study job
8918023 asked for a token and ended with `Underlying error: 'name'`, and
anonymisation jobs 8913992, 8917988 and 8917989 printed
`could not reuse the diarisation pipeline ('name')`. 392b975 and 71560ae
added the exception's type to those two messages, and 1bbae87 the damage
report to the first.

To repair the cache, delete the damaged blob and the snapshot's link to
it (or, where the snapshot holds the file itself, that file), then run
`setup/cache_pyannote_arc.py` again, which exits 3 while anything it
checks is still damaged. A damaged blob that no snapshot links to is
deleted on its own, since a download would link it again. Alternatively,
restore the file from an intact copy in the Hugging Face hub cache.
preflight names such a copy when it finds one that still hashes to its
blob's name. For a blob, it otherwise says where the hub cache's blob of
the same name would be, to be used only after `git hash-object` on it
(`sha256sum` for a blob named after a SHA-256) prints that name.

Speaker-attribution problems (tokens, gated models, offline loading) are
covered in [PYANNOTE_SETUP_GUIDE.md](PYANNOTE_SETUP_GUIDE.md).

## Memory and time on HPC

The transcription tasks run on CPU with 32G of memory and 08:00:00 of wall
time each by default. A task SLURM kills for memory needs a larger
`--memory` (for example `--memory 64G`), and one that ends in the
`TIMEOUT` state a larger `--time-limit`, up to the 12-hour limit of the
`short` partition. Check a finished task with
`sacct -M htc -j <job_id> --format=JobID,State,ExitCode,Elapsed,MaxRSS`.

The GPU evaluation jobs stop (exit 2, or exit 4 in the case study) when
their preflight finds no usable CUDA device. If one does, check that it
went to the `htc` cluster with `--gres=gpu:1`, as the scripts' own
`#SBATCH` lines ask. The preflight report says whether torch is a CUDA
build, and when it is, the node or the allocation is the problem, not the
environment.

## Logs

Every job script writes its log to `logs/` in the repository. A
transcription task writes `logs/transcription_<job_id>_<task_id>.out` and
`.err`; a single-file job is not an array, so match its log with
`logs/transcription_<job_id>_*.out`. The wrapper prints the exact
monitoring commands after it submits. The end of a task's `.out` lists
the files it wrote, or says which requested artefacts are missing.

## Transcript quality

Pass `--language` on every run: it also selects the post-processing
rules, and a wrong guess from language detection applies the wrong ones.
`--fix-spurious-repetitions` removes repetition loops, and
`--enhance-audio` may help noisy recordings at the cost of time. With
`--timestamps`, the `_review.json` file flags the segments most likely to
be hallucinated; listen to those passages.

Name masking that hides ordinary words is usually the common-word
filter being off. It is on by default for English, and
`--exclude-common-english-words-from-name-masking` turns it on for other
languages. Specific names can be left unmasked with
`--exclude-names-from-masking "Name1,Name2"`. The Facebook name lists
(`--use-facebook-names-for-masking`, `--use-facebook-surnames-for-masking`)
mask far more ordinary words than the default curated dictionary.

## Reporting a problem

Include the output of `python -m preflight`, the command you ran, the
error from the log, and the recording's format, duration and size.
For issues specific to the University of Oxford cluster, see the
[ARC user guide](https://arc-user-guide.readthedocs.io/).
