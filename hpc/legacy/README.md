# Retired job scripts

The two scripts here are the WER benchmarks that `hpc/submit_sweep.sh`
replaced. They are kept, unchanged apart from a guard at the top that stops
them running, because their headers are the record of how the May 2026
`wer_report.csv` and `wer_summary.json` were made. That pair was the
manuscript's headline input from its commit on 2026-05-19 (cefaac0) until
audit finding OUTPUTS-03 put the condition sweep's raw Large v3 test-clean
cell under the same names. It is kept in `output/evaluation/pilot_may2026/`
as `wer_report_librispeech_whisper-large-v3_raw.csv` and
`wer_summary_librispeech_whisper-large-v3_raw.json`.

- `submit_benchmark_wer.sh` is the first CPU benchmark. ARC holds four logs
  matching its log pattern, all from 2026-05-16 (jobs 7662692, 7662812,
  7662816 and 7662825); which committed files, if any, they produced is not
  recorded.
- `submit_benchmark_wer_gpu.sh` is the three-model GPU array. Task 0 of
  array job 7682561 (2026-05-18, an NVIDIA L40S) wrote the two canonical
  names on ARC by 23:19 and is the most likely producer of the May pair.
  Slurm records the task as failed because, after writing the LibriSpeech
  pair, it went on to the FLEURS suite, which the node could not fetch
  from the Hugging Face Hub. The pre-repair sweep overwrote the task's
  copies on ARC on 2026-05-26. The May report is identical, up to line
  endings (ARC's copy has CRLF), to `wer_report_gpu.csv`, which job
  7668730, the script's earlier single-model form, wrote on another L40S
  node on 2026-05-17 and which is still on ARC. The May summary agrees
  with that run's `wer_summary_gpu.json` in every value, the per-utterance
  entries included, and adds a `seed` field, which
  `evaluation/benchmark_wer.py` began writing at b29767e, after 7668730 had
  run and before task 0 started.

Both scripts wrote `wer_report.csv` and `wer_summary.json` into the shared
ARC evaluation directory by default, the names of the result the
manuscript reads, and `submit_benchmark_wer.sh` recommended a
`BENCHMARK_LIMIT=200` sanity check into the same files. Running either
could replace the manuscript's input with a partial or differently
versioned result without any warning (audit findings XREF-01 and
SHELL-09). The GPU script's other file names are the ones
`evaluation/sweep.py` writes, so a re-run would also have mixed code
versions across the sweep matrix.

Each script now prints a pointer to `hpc/submit_sweep.sh` and exits 1 before
doing anything. The rest of each file is unmaintained: it still installs
packages from inside the job, which no live script does any more. To see the
scripts as they last ran, use `git log --follow` on either file.

## How the May decode differs from the sweep's

The May summary records neither its library versions nor its card, but
both May jobs' logs record an NVIDIA L40S, torch 2.5.1+cu121 and Python
3.12.12, the torch and Python the sweep's summaries record. The revisions
were not pinned, yet ARC's shared Hugging Face cache, which the May jobs
and the sweep both read through `HF_HOME`, holds one snapshot of the model
and one of the dataset. They are the revisions the sweep pins, downloaded
on 2026-05-16, and the cache's `main` references were last written that
day. The environment's only transformers is 4.57.1, the version the sweep
records, and pip's record of installing it is dated 2025-10-21. Task 0
started 85 seconds after de13451, which made the script an array job, and
the code at de13451 decodes the audio, builds the pipeline and normalises
the text for scoring in the same way as 6f9bf56, except that 6f9bf56 names
the revision. Each of the five utterances the May report and the sweep's
raw Large v3 test-clean report score differently therefore has a
different hypothesis, and of what was recorded only the card separates
the two decodes: an L40S in May, a Tesla V100 in the sweep. The two L40S
runs agree on every utterance, although only task 0 ran with the seed and
with deterministic cuDNN and cuBLAS settings. A third decode, the
pre-repair sweep's on an H100 (job 7729882, task 0), differs from the May
decode on seven utterances and from the sweep's on eight. This is the
environmental drift that audit finding EWER-10 describes.
