# Proposed Spanish V100 control

Prepared on 6 October 2026; no ARC job has been submitted. This is the
smallest full-split control for NEW-05: decode Spanish at the fourth arm's
code on the V100 family used by the third arm, keeping the model, dataset,
language, seed and software stack fixed. It tests whether the recorded
hardware-associated drift persists. It does not rerun the six-language
experiment or replace its committed results.

| Setting | Required value |
| --- | --- |
| Source commit | `6f9bf56a0d5839920537f23d73a166dc0f1e478b`, clean tracked tree |
| Existing script | `hpc/submit_benchmark_wer_multilingual.sh`, array index `2` |
| Dataset | `google/fleurs`, revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`, `es_419`, full `test` split |
| Model | `openai/whisper-large-v3`, revision `06f233fe06e710322aca913c1bc4249a0d71fce1` |
| Decoder/scorer | Language `spanish`, task `transcribe`, native timestamps, seed `42`, condition `raw`; the historical module's defaults |
| Allocation | Cluster `htc`, partition `short`, account `educ-intract`, QoS `standard`, one task, four CPUs, 32 GB RAM, one `gpu:v100`, 12-hour limit |
| Site modules | `Anaconda3/2025.06-1`, `CUDA/13.0.2` |
| Expected run stack | Python `3.12.12`, torch `2.5.1+cu121`, transformers `4.57.1`, datasets `4.8.5`, jiwer `4.0.0`; compare the complete environment with the historical lock and arm 4 records |
| Full output directory | `$DATA/speech_transcription_env/output/evaluation/controls/es_419_v100_6f9bf56` |

The prepared preflight is limited to 30 minutes; the full split retains
the script's 12-hour maximum. These are scheduling limits, not an estimate
of the time or energy the two runs will consume.

Read-only checks on 6 October 2026 found the historical ARC checkout at
the exact clean commit above. All 178 package pins in the environment
lock match the current ARC environment, which uses Python 3.12.12. The
V100 nodes were in mixed use, the P100 nodes remained drained, and no
job matching this project's names was queued or running. Both original
Spanish comparison summaries were recovered and their recorded SHA-256
digests verified; each scores 908 utterances. The local receipts are in
ignored `build/recovered_fleurs_control/`. Refresh capacity and cache
checks immediately before any submission; these observations do not
reserve a card.

The script is unchanged between the recorded decoder commit and the review
checkout. It selects `es_419`/`spanish` from index 2, stops if its raw
summary exists, requires a usable GPU and records the environment. Its
historical benchmark pins the two revisions above, seeds Python, NumPy and
torch, sets `CUBLAS_WORKSPACE_CONFIG=:4096:8` and disables cuDNN
benchmarking. It has no `--device` or `--dtype` options at this commit.
The output must confirm CUDA, the actual V100 board and loaded dtype;
arm 4 used float16, and a changed dtype or environment would confound the
comparison. No package installation or repair belongs inside the job.

Before submission, use a dedicated checkout of that exact commit, check
the pinned cache snapshots and the unchanged shared environment, and
refresh the node-state/account check. The plan's last observation, on
4 October, had V100s on `htc-g003` and `htc-g004` and drained P100 nodes;
it is not a current capacity check. `gpu:v100` does not request the exact
SXM2 board used by arm 3. Retain the allocated board, node and driver
information, and interpret a match as evidence for this control rather
than proof that GPU alone caused the historical drift.

These are prepared submission commands, to be run from the historical
checkout on ARC after the remaining requirements are met. First use the
script's five-utterance decoding preflight in its own directory:

```bash
(
  set -euo pipefail
  test "$(git rev-parse HEAD)" = 6f9bf56a0d5839920537f23d73a166dc0f1e478b
  test -z "$(git status --porcelain --untracked-files=no)"
  : "${DATA:?ARC project storage must be set}"
  mkdir -p logs
  export ARC_ANACONDA_MODULE=Anaconda3/2025.06-1 ARC_CUDA_MODULE=CUDA/13.0.2
  export WER_ML_MODEL=openai/whisper-large-v3 WER_ML_CONDITIONS=raw OVERWRITE=0
  export WER_ML_LIMIT=5
  export WER_ML_OUTPUT_DIR="${DATA}/speech_transcription_env/output/evaluation/controls/es_419_v100_6f9bf56_preflight"
  sbatch --clusters=htc --partition=short --account=educ-intract --qos=standard \
    --array=2 --ntasks=1 --cpus-per-task=4 --mem=32G --time=00:30:00 --gres=gpu:v100:1 \
    --job-name=pf_es419_v100 hpc/submit_benchmark_wer_multilingual.sh
)
```

Only after that job completes successfully and its recorded environment
and output are inspected, run the full split in a distinct directory:

```bash
(
  set -euo pipefail
  test "$(git rev-parse HEAD)" = 6f9bf56a0d5839920537f23d73a166dc0f1e478b
  test -z "$(git status --porcelain --untracked-files=no)"
  : "${DATA:?ARC project storage must be set}"
  mkdir -p logs
  export ARC_ANACONDA_MODULE=Anaconda3/2025.06-1 ARC_CUDA_MODULE=CUDA/13.0.2
  export WER_ML_MODEL=openai/whisper-large-v3 WER_ML_CONDITIONS=raw OVERWRITE=0
  export WER_ML_LIMIT=
  export WER_ML_OUTPUT_DIR="${DATA}/speech_transcription_env/output/evaluation/controls/es_419_v100_6f9bf56"
  sbatch --clusters=htc --partition=short --account=educ-intract --qos=standard \
    --array=2 --ntasks=1 --cpus-per-task=4 --mem=32G --time=12:00:00 --gres=gpu:v100:1 \
    --job-name=ctl_es419_v100 hpc/submit_benchmark_wer_multilingual.sh
)
```

Retain the job logs, scheduler record, `environment/` files,
`wer_report_fleurs_es_419_whisper-large-v3.csv` and
`wer_summary_fleurs_es_419_whisper-large-v3.json`, with SHA-256 digests.
Require 908 scored utterances and no unexplained exclusions, changed
references or identifiers. Compare each utterance's alignment counts and
CER with the third-arm Spanish raw summary; compare scientific records,
not whole JSON bytes containing new run metadata. The original comparison
inputs are not committed and must be recovered and hash-checked first:

| Comparison input | SHA-256 recorded in `fleurs_multilingual_summary.json` |
| --- | --- |
| Arm 3 `wer_summary_fleurs_es_419.json` | `7311b602f06666adf2b4ee0a9538f4727700becc601e8773f34541202f5c519b` |
| Arm 4 `wer_summary_fleurs_es_419_whisper-large-v3.json` | `3c21bba3b288e3b97105fefaada3f1c236bac10268f7c62c5b449f4f9bcd765e` |

The old summaries preserve metrics, not transcript strings. Matching their
records would not establish identical hypotheses. The historical module
can write `--dump-hypotheses`, but the submission script does not expose
that option. The commands above require no code changes and address the
stated metric-record control. If verbatim hypotheses must also be retained,
prepare and review a separately hashed wrapper or an explicit script
override before submission, without changing the decoder. A differing
result would leave the attribution unresolved; neither outcome should
silently alter the canonical multilingual summary or its existing hedge.
