# HPC scripts

This directory holds the SLURM job scripts. They were written for the
University of Oxford's ARC service: every script targets the `htc`
cluster (`--clusters=htc`) and its `short` partition, whose limit is
12 hours. ARC users with more than one project choose which to charge with
`--account`; the evaluation scripts' usage lines use
`--account=educ-intract`, and either project account works. To run the
scripts elsewhere, see [HPC_SETUP_GUIDE.md](HPC_SETUP_GUIDE.md).

Submit every script from the repository root. The scripts take the
repository path from `SLURM_SUBMIT_DIR` and write their logs to
`logs/<job name>_<job id>.out` and `.err` under it, so a submission from
another directory cannot find the code or its logs. Each script's header
comment lists every environment variable it reads, with its default, and
the outputs it writes; this page is the map between them.

## How every job starts

Every job script sources [common/arc_common.sh](common/arc_common.sh) and
starts with the same three steps, in place of the copies that used to
drift apart between scripts:

1. `arc_activate` purges the modules, loads `Anaconda3/2025.06-1` (and
   `CUDA/13.0.2` for the GPU jobs), sources `activate_project_env_arc.sh`
   and moves into the repository. The two versions are the ones the
   unversioned `module load` resolved to for every committed job, pinned so
   a new site default cannot change the next run. torch uses the CUDA 12.1
   runtime in its own wheels, not the module.
2. A preflight gate: `python -m preflight`, with `--gpu-required` in every
   GPU job and `--diarisation-required` as well in the DER, DER sweep,
   fine-tuning, case-study and anonymisation jobs. A FAIL stops the job
   with exit 2 (exit 4 in the case study) before any work is done. The CPU
   jobs run the preflight without `--gpu-required`, and `run_tests.sh` and
   `submit_determinism_cpu.sh` add `--lock requirements-lock.txt`, which
   fails on any installed version that differs from the lock. The
   transcription job loads the diarisation pipeline when it is given
   `--speaker-attribution`, but its preflight does not pass
   `--diarisation-required`.
3. `arc_load_hf_token` exports the HuggingFace token for the jobs that need
   one, from `hf_token.txt` in the repository root or `HF_TOKEN`.

No job installs, upgrades, uninstalls or repairs a package. Until the ENV
fixes, several jobs ran `pip install` whenever an import failed and
force-reinstalled torch from the cu121 index whenever CUDA looked missing,
inside the shared environment that produces the results and while sibling
array tasks were importing from it. The environment is now fixed by
`requirements-lock.txt`. A job whose environment is wrong stops, and the
remedy printed in its log is applied from a login node. The ARC login
nodes cap virtual memory at 2 GB, under which the environment's CUDA build
of torch cannot load, so `python -m preflight` reports torch as
unimportable there. Run it on a compute node to check the environment as
the jobs see it.

`activate_project_env_arc.sh` also sets `PYTHONNOUSERSITE=1`: the
account's `~/.local` holds torch 2.8.0+cpu and transformers 4.56.2, which
shadow the environment whenever a user site is on. The preflight's
`isolation` check fails a job whose torch, transformers or pyannote loads
from outside the environment.

## Transcribing recordings

`submit_transcription.sh` is the entry point for transcribing your own
recordings. It runs on the login node, freezes the list of recordings in
`logs/filelist_<timestamp>.txt` and submits one array task per recording
to `batch_transcription.sh`, which runs `transcription.py` on CPU. No GPU
is requested and `CUDA_VISIBLE_DEVICES` is emptied, so a GPU node gives the
worker nothing. It runs the CPU preflight before transcribing, and Slurm's
`--time` is its only time limit. Usage, input directory and options are in
[docs/hpc_usage.md](../docs/hpc_usage.md) and
[ARC_USAGE_GUIDE.md](../ARC_USAGE_GUIDE.md).

## The evaluation pipeline

The scripts below produced the results reported in the manuscript, which
are committed under `output/evaluation/`. They write to
`$DATA/speech_transcription_env/output/evaluation` by default (or to
`REPORT_DIR` where the script reads one), not to the repository, so a
result reaches `output/evaluation/` only when it is copied there and
committed. The order matters where one stage reads another's output.

| Stage | Script | Needs first | GPU | Wall time requested | Writes |
| --- | --- | --- | --- | --- | --- |
| AMI meeting cache | `submit_ami_cache.sh` | nothing | no | 6 h | `$DATA/ami_cache/<split>_timeline_full/`, and `reconstruction_audit_<split>.json` checking each rebuilt meeting against its annotation |
| Diarisation sweep, development split | `submit_der_sweep.sh` | the AMI cache | yes | 12 h | `der_sweep.csv`, `der_sweep_summary.csv`, `der_sweep_selection.json` |
| Diarisation error rate, test split | `submit_benchmark_der.sh` | the AMI cache | yes | 12 h | `der_report.csv`, `der_summary.json` |
| WER sweep over suites and conditions | `submit_sweep.sh` (array 0-4, one suite per task) | nothing | yes | 12 h per task | `wer_report*.csv`, `wer_summary*.json`, per suite, model and condition, in `SWEEP_OUTPUT_DIR` |
| Sweep aggregation | `aggregate_sweep.sh` | every task of the sweep | no | 30 min | `sweep_aggregate.csv`, `sweep_aggregate.json` in `SWEEP_DIR` (default `audit2026/sweep/`) |
| Multilingual WER on FLEURS | `submit_benchmark_wer_multilingual.sh` (array 0-5) | nothing | yes | 12 h per task | `wer_report_fleurs_<config>_<model>*.csv` and summaries |
| Timestamp accuracy | `submit_benchmark_timestamps.sh` | nothing | yes | 4 h | `timestamp_report.csv`, `timestamp_skipped.csv`, `timestamp_summary.json` |
| Filler preservation | `submit_disfluency.sh` | nothing | yes | 12 h | `wer_hypotheses_ami.csv`, `disfluency_summary.json`, `disfluency_report.csv` (a fresh decode; the committed pair is scored locally from the sweep's AMI dump instead, see `evaluation/disfluency.py`) |
| Run-to-run determinism | `submit_determinism.sh` | nothing | yes | 8 h | `determinism/` (job 8978760, on a V100, took 16 min; its summaries, `gpu.txt` and WER report are committed in `determinism/v100_8978760/`) |
| Run-to-run determinism on a processor | `submit_determinism_cpu.sh` | nothing | no | 12 h | `determinism_cpu/` (job 8978759 took 1 h 17 min; its summaries, `cpu.txt` and WER report are committed in `determinism/cpu_8978759/`) |
| Voice anonymisation trade-off | `submit_anonymisation.sh` | nothing | yes | 8 h | `anonymisation_summary.json`, `anonymisation_report.csv` |
| Worked example on a podcast episode | `submit_case_study.sh` | the episode's audio in `$DATA/codex_mentis/audio/`, fetched with `python -m evaluation.fetch_codex_mentis --dest $DATA/codex_mentis`, and a corpus manifest (below) | yes | 2 h | transcripts in the repository's `output/transcripts/` (git-ignored); `podcast_eval_*` in `$DATA/speech_transcription_env/output/case_study/` |

The case study's structural evaluation reads each episode's duration from
a corpus manifest. The job takes `CASE_MANIFEST` when it is set, then
`$DATA/codex_mentis/manifest.json` when it exists (the fetch writes it),
and otherwise the repository's own `data/codex_mentis/manifest.json`
(ca75ced), whose episode 5 entry holds the SHA-256 and size of the
recording on ARC, where no fetch manifest exists. The job stops with exit
2 before transcribing when the manifest it chose does not exist. Until
ca75ced it knew only the fetch manifest, so re-run 8978758 transcribed
and then failed its structural evaluation (NEW-06).

The case study used to write its evaluation into the repository's tracked
`output/case_study/`, which left the ARC clone with a modified file after
every run. A new result is now copied in by hand when it is to be
committed: `cp "$DATA"/speech_transcription_env/output/case_study/podcast_eval_* output/case_study/`
for the evaluation, and the run's `codex_mentis_ep05_review.json` and
`codex_mentis_ep05_manifest.json` from `output/transcripts/`, byte for
byte, so that the review keeps the SHA-256 the manifest records for it.

The sweep and its aggregation can be chained with a dependency, which is
not done automatically. Give both the same directory:

```bash
OUT=$DATA/speech_transcription_env/output/evaluation/<new sweep>
JID=$(SWEEP_OUTPUT_DIR=$OUT sbatch --parsable hpc/submit_sweep.sh)
SWEEP_DIR=$OUT sbatch --dependency=afterok:${JID%%;*} hpc/aggregate_sweep.sh
```

`--parsable` prints `<job id>;<cluster>` when the job is submitted to a
named cluster, hence the `${JID%%;*}`. Without `SWEEP_DIR`,
`aggregate_sweep.sh` aggregates `audit2026/sweep/`, the sweep (jobs
8917985, 8917986 and 8917987, `runs/sweep.env`) behind the committed
255-row matrix. The whole evaluation directory holds several sweeps and
cannot be aggregated as one. A sweep task with `SWEEP_LIMIT` refuses to start unless
`SWEEP_OUTPUT_DIR` is set too.

The committed WER matrix ran Large v3 on Tesla V100-PCIE-32GB cards and
Whisper Medium and distil-large-v3 on NVIDIA L40S cards, as its summaries
record. `submit_sweep.sh` asks for any GPU, so add `--gres=gpu:v100:1` or
`--gres=gpu:l40s:1` to `sbatch` to repeat a model on the same card type.

The committed timestamp results ran on an NVIDIA H100 80GB HBM3
(htc-g059). `submit_benchmark_timestamps.sh` asks for any GPU, and the
`h100` type also covers the H100 PCIe of htc-g055, on which job 7746137 put
one start a 20 ms step later. The `sbatch` command that
`hpc/runs/timestamps.env` gives (and `timestamps_vad.env` with it) therefore
adds `--gres=gpu:h100:1 --constraint=nvlink`, which only htc-g059 and
htc-g060 satisfy. Sourcing either file does not request the card.

The committed diarisation results ran on NVIDIA L40S cards (htc-g066 and
htc-g070), as their environment records show, and so did the August runs
they replaced. `submit_benchmark_der.sh` and `submit_der_sweep.sh` ask for
any GPU, so the commands in `hpc/runs/der_*.env` add `--gres=gpu:l40s:1`.

Several committed results need no cluster and are rebuilt locally from
committed inputs: the masking benchmark (`python -m
evaluation.benchmark_masking`, seed 42 by default), the bootstrap
intervals (`python -m evaluation.bootstrap_ci` and `python -m
evaluation.condition_ci`), the compute footprint (`python -m
evaluation.footprint`, from `output/evaluation/arc_job_ledger.csv`) and the
artefact audit (`python -m evaluation.audit_artefacts`). Each of these
writes into `output/evaluation/` by default, so running one there replaces
the committed file; pass `--output-dir` (or `--output`) to write elsewhere.

Four more are assembled locally from job outputs copied off ARC. The
committed `sweep_aggregate.csv` and `sweep_aggregate.json` were not written
by `aggregate_sweep.sh`: `python -m evaluation.sweep_aggregate` built them
at commit 7214e77 from copies of the 255 summaries in `audit2026/sweep/`,
and the JSON's provenance holds the SHA-256 of each summary
(`hpc/runs/sweep.env`). The filler-preservation pair is scored from the
sweep's AMI hypothesis dump, as the next section describes.
`output/evaluation/fleurs_multilingual_summary.json` is rebuilt from the 48
per-language FLEURS summaries on ARC (six languages, two conditions, four
arms, the fourth from array 8917984 in `audit2026/fleurs_ml/`) by
`python -m evaluation.fleurs_multilingual` with the options its docstring
gives, which reproduces the committed file apart from
`benchmark.assembled_by`, the record of the rebuild's own run. It was first
assembled by hand.
`output/evaluation/determinism/determinism_cross_accelerator.json` is
rebuilt by `python -m evaluation.determinism_cross` from hypothesis dumps,
WER reports and a job log copied from ARC, which
`determinism_cross_accelerator_runs.json` names together with the command.
The result names each input by the SHA-256 of its bytes and with CRLF read
as LF.

The job ledger behind the compute footprint is built from a read-only
sacct dump taken with

```bash
sacct -M htc --starttime 2026-05-16 --endtime now -X -P \
    --format=JobID,JobName,Account,State,ElapsedRaw,Start,End,Partition,AllocTRES,NodeList,WorkDir
```

and copied off the cluster unchanged, since the ledger's provenance
records the dump's SHA-256. It is built locally with `python -m
evaluation.footprint --from-sacct <dump> --captured <date> --sacct-query
'<that query>'`. The window opens on 2026-05-16, the day of the
evaluation's first job. The workflow's own earlier jobs, run from
`~/speech_transcription` between August 2025 and January 2026, are not
part of it. A finished job that held an allocation counts when
`evaluation.footprint.job_category` knows its name and the job ran from a
clone of this repository or from `speech_transcription_env`, or when its
name is one of the few documented to have run elsewhere
(`_RUN_ELSEWHERE`). A job under a known name that ran from any other
directory is left out and listed in the provenance, and a job that ran
from a clone under a new name stops the build until it is given a
category. Name the jobs of a re-run wave `au_<stage>` and their
pre-flights `pf_<stage>`, with a stage that `_STAGE_CATEGORY` lists, and
submit them from a clone. The committed ledger was captured this way on
2026-10-04 at 13:45 BST, after the evaluation's last job had finished,
and holds 197 jobs. Its provenance,
`output/evaluation/arc_job_ledger_provenance.json`, holds the query and
the dump's SHA-256 and lists the jobs of this project left out, each
under its reason: seven, all cancelled while pending. The dump is not
committed, since it lists the shared account's other projects. The
estimate is then made from the committed ledger with `python -m
evaluation.footprint`.

### Which invocation produced each committed result

A bare `sbatch` of a script runs its defaults, and for several scripts the
defaults are not what produced the committed files. The overrides behind
those files, with the ARC job ID and date, are recorded in `hpc/runs/`:

| Committed result | Record |
| --- | --- |
| `der_summary.json`, `der_report.csv` | `hpc/runs/der_default.env` |
| `der_tuned/` | `hpc/runs/der_tuned.env` |
| `der_oracle/` | `hpc/runs/der_oracle.env` |
| `der_concat/` | `hpc/runs/der_concat.env` |
| `der_sweep*.csv`, `der_sweep_selection.json` | `hpc/runs/der_sweep.env` |
| `der_sweep2*.csv`, `der_sweep2_selection.json` | `hpc/runs/der_sweep2.env` |
| `sweep_aggregate.csv`, `sweep_aggregate.json`, `sweep_reports_postfix/`, `sweep_reports_postfix_ami/`, `wer_report.csv`, `wer_summary.json` | `hpc/runs/sweep.env` |
| `fleurs_multilingual_summary.json`, its fourth arm | `hpc/runs/fleurs_ml.env` |
| `timestamp_report.csv`, `timestamp_summary.json`, `timestamp_skipped.csv` | `hpc/runs/timestamps.env` |
| `../evaluation_vad_refine/` | `hpc/runs/timestamps_vad.env` |
| `determinism/` (the H100 files at its top level) and `determinism/l40s_8781724/` | `hpc/runs/determinism.env` |
| `determinism/cpu_8978759/` | `hpc/runs/determinism_cpu.env` |
| `determinism/v100_8978760/` | `hpc/runs/determinism_v100.env` |
| `anonymisation_summary.json`, `anonymisation_report.csv` | `hpc/runs/anonymisation.env` |
| `anonymisation_single_meeting/` | `hpc/runs/anonymisation_single_meeting.env` |
| `../case_study/`: `podcast_eval_summary.json`, `podcast_eval_report.csv`, the review and the run manifest | `hpc/runs/case_study.env` |

Each file is sourced before submission, for example:

```bash
( set -a; . hpc/runs/anonymisation.env || exit 1; set +a
  sbatch --account=educ-intract --gres=gpu:l40s:1 hpc/submit_anonymisation.sh )
```

The `|| exit 1` stops the subshell when the record cannot be read. Bash
carries on past a `.` that cannot find its file, and the subshell would
then submit the script with its own defaults.

`.gitattributes` gives the records LF line endings in every new checkout
(4ba44b9). Sourced by bash on ARC, a record with CRLF endings sets each
value with a trailing carriage return, and `submit_anonymisation.sh` then
rejects `ANON_PRESET` as unknown. The rule does not rewrite a Windows
working copy that checked the records out with CRLF before it arrived,
and `git checkout -- hpc/runs/` leaves such files as they are. Before
copying a record from that working copy to ARC, delete the records and
check them out again (`rm hpc/runs/*.env && git checkout -- hpc/runs/`).
`git ls-files --eol hpc/runs` then shows `w/lf` for each.

Each record sends a reproduction to its own directory under
`$DATA/speech_transcription_env/output/evaluation/repro/`, through its
job's own output variable (`REPORT_DIR`, except `SWEEP_OUTPUT_DIR` in
`sweep.env`, `WER_ML_OUTPUT_DIR` in `fleurs_ml.env` and `CASE_REPORT_DIR`
in `case_study.env`), so it cannot overwrite the ARC copy of the run it
is compared with. Where the run has been made, the original directory is
noted in the file. Two runs of the determinism check wrote into the
directory their record named before they ran: the CPU arm, job 8978759,
into `repro/cpu_arm/`, and the V100 run, job 8978760, into
`repro/v100_arm/`. `hpc/runs/determinism_cpu.env` and
`hpc/runs/determinism_v100.env` now give those directories as the
originals and send a reproduction to `repro/determinism_cpu/` and
`repro/determinism_v100/`. `determinism_v100.env` also sets
`SBATCH_GRES=gpu:v100:1`, which sbatch reads as `--gres`, so that record
requests its card itself.

The two diarisation sweeps, jobs 8976358 and 8976362, wrote the committed
files under these names into `audit2026/der/der_sweep/` and
`audit2026/der/der_sweep2/` on ARC. Neither is the default grid of
`submit_der_sweep.sh`. The equivalent direct commands, from the docstring
of `evaluation/sweep_der.py`, are:

```bash
# der_sweep.csv, der_sweep_summary.csv, der_sweep_selection.json
# (ARC job 8976358). The defaults cell and five thresholds.
python -m evaluation.sweep_der --split validation \
    --cache-dir "$DATA/ami_cache" \
    --clustering-threshold 0.50 0.60 0.70 0.80 0.90 \
    --min-cluster-size 12 --min-duration-off 0.0

# der_sweep2.csv, der_sweep2_summary.csv, der_sweep2_selection.json
# (ARC job 8976362). The defaults cell and a 3 x 3 grid.
python -m evaluation.sweep_der --split validation \
    --cache-dir "$DATA/ami_cache" --output-prefix der_sweep2 \
    --clustering-threshold 0.65 0.70 0.75 \
    --min-cluster-size 12 --min-duration-off 0.0 0.25 0.5
```

The August sweeps they replaced, jobs 8534758 and 8534792, wrote into
`der_sweep_dev/` and `der_sweep_dev2/` and were copied in under these
names. The first predated the defaults cell, so it scored the five
thresholds alone, which `--no-default-cell` repeats.

Some committed results have no `hpc/runs/` record. The filler-preservation
pair is not a job's output. It is scored locally, with the command in the
`evaluation.disfluency` docstring, from the AMI hypothesis dump of sweep
8917985 (task 1), whose record is `hpc/runs/sweep.env`. The first three
FLEURS arms have no record, but `fleurs_multilingual_summary.json` names
each arm's jobs, code commit and GPUs. The reconstruction audit and the
FLEURS diacritic shares have none either, and the commits that added
their current files (942d2c1 and 08d06a8) name their jobs. Nor has
`output/case_study/ep05_raw_text.txt`, kept as the input that
`ner_false_positive_test.md` measured. It is the text of the August
case-study run, job 8441879, which the case study's README names, and
the commit that added it (50314de) names no job. Results kept only as
history are traced in `output/evaluation/README.md`.
`output/evaluation/arc_job_ledger.csv` lists every job of the evaluation,
7662519 to 8983112, and gives each GPU job the board of the node it ran
on. The ledger it replaced, captured on 2026-06-27, listed only jobs
7721017 to 7995595 and recorded every GPU job as `a100`. For a job that
asked for any GPU (`--gres=gpu:1`), the batch step's allocation reads
`gres/gpu:a100` whatever card ran it: jobs 7737896 and 7746221 ran on
Tesla P100s and jobs 7746137 and 7746138 on an H100 PCIe, as their logs
say, and the ledger now records them as `p100-pcie` and `h100-pcie`. The
code commit a job ran was not recorded for any job before
`hpc/common/arc_common.sh` existed. Jobs that source it now write a
record of the Python stack, loaded modules, GPU and git commit to an
`environment/` subdirectory beside their results.

## Checks run on ARC

Two checks are written down here so that they can be repeated as they
stand, with the record of their last runs.

**The test suite on ARC (TESTS-01).** Recorded runs, each from a clean
checkout of the commit named:

| Job | Commit | Result |
| --- | --- | --- |
| 8917831 | eaef44a | 1649 passed, 1 skipped, 1 xfailed |
| 8918061 | d0edd03 | 1658 passed, 1 skipped, 1 xfailed |
| 8978757 | f2578b8 | 2032 passed, 1 skipped, 1 xfailed |
| 8983111 | c4c7b38 | 2058 passed, 1 skipped, 1 xfailed |

The skip is `tests/test_s1_misc_footprint.py:159`, which needs a raw sacct
dump committed under `output/evaluation/`; the expected failure is
`tests/test_privacy_masking_interaction.py::test_real_masker_keeps_turn_separators`.
Until the audit's runs of September 2026, the last run had been on
2026-05-16, before most of the jiwer- and pyannote-dependent tests existed.
From the repository root on ARC:

```bash
sbatch --account=educ-intract hpc/run_tests.sh
```

The job stops with exit 2, before pytest, if any installed version differs
from `requirements-lock.txt`. Record the job ID, the final pytest line
(`N passed, M skipped`) and the skip list that `-rs` prints at the end of
`logs/pytest_<job id>.out`, next to the results commit it vouches for. The
environment record is written to `logs/environment/`. A skip that remains
on ARC is a test that guards nothing there.

Test jobs 8913985 (commit 76d9489, 54 failed) and 8917186 (commit 2e5e852,
18 failed) are not in the table, and they did more than fail. In each, the
pyannote pre-cache test in `tests/test_s1_env_setup.py` was handed the real
`~/.cache/torch/pyannote`, because an earlier test had imported
pyannote.audio, and its stand-in for the Hugging Face Hub wrote a stub
`config.yaml` that names no pipeline through the snapshot's link into the
cached pipeline config (blob `5402e3ca` of
`pyannote/speaker-diarization-3.1`). Every load of the pipeline then failed
until the blob was restored on 2026-10-04 (incident NEW-INC-01). Case-study
job 8918023 ran without speaker attribution and failed, and anonymisation
jobs 8913992, 8917988 and 8917989 loaded the pipeline's embedding model
directly instead (`hpc/runs/anonymisation.env`). The suite now redirects
every model cache into a temporary directory for the session, the stand-in
refuses to write outside the test's directory or through a link, and
`python -m preflight --diarisation-required` fails a job whose cached
pipeline config is damaged. A job from a clone older than that check does
not make it, so before submitting such a job, check that
`git hash-object ~/.cache/torch/pyannote/models--pyannote--speaker-diarization-3.1/blobs/5402e3ca79b6cfa5b0ec283eed920cafe45ee39b`
prints the blob's own name. Seven tests in
`tests/test_test_isolation.py` and `tests/test_preflight_pipeline_config.py`
need symlinks and skip where none can be made, as on Windows without that
privilege. Job 8978757 was their first run on ARC, and all seven passed.

**A CPU smoke test of the segmentation fine-tuning (EDER-FT).** Phase 2 of
`evaluation/finetune_pyannote_segmentation.py` was rewritten against the
pyannote.audio 3.4.0 source. It has passed twice on ARC: job 8913986
(commit 76d9489) and job 8918331 (commit 6f9bf56, loading the base model at
its pinned revision), each with a development-set DER of 0.157 after one
epoch. Before any GPU submission of `submit_finetune_pyannote.sh`, run it
again on the CPU
with eight meetings (enough for two AMI series, so the development split is
not empty), one minute each, one epoch and no evaluation. The job script
itself asks for a GPU, so this is submitted as its own short CPU job,
from the repository root on ARC:

```bash
sbatch --account=educ-intract <<'EOF'
#!/bin/bash
#SBATCH --job-name=finetune_smoke
#SBATCH --clusters=htc
#SBATCH --partition=short
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=logs/finetune_smoke_%j.out
#SBATCH --error=logs/finetune_smoke_%j.err
set -euo pipefail
REPO_DIR="$SLURM_SUBMIT_DIR"
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" || exit 1
arc_preflight --diarisation-required || exit 2
arc_load_hf_token "$REPO_DIR" || exit 1
export CUDA_VISIBLE_DEVICES=""
python -m evaluation.finetune_pyannote_segmentation \
    --limit-meetings 8 --epochs 1 --max-minutes 1 --skip-eval \
    --output-dir "$DATA/speech_transcription_env/output/finetune_smoke_cpu"
EOF
```

It passes when the job exits 0 and
`$DATA/speech_transcription_env/output/finetune_smoke_cpu/segmentation_model/`
holds `segmentation-ami-best.ckpt` and `finetune_provenance.json`. The
checkpoint says nothing about quality. The test is only that Phase 1 and
Phase 2 run end to end on the 3.4.0 API.

## Superseded and auxiliary scripts

`legacy/submit_benchmark_wer.sh` and `legacy/submit_benchmark_wer_gpu.sh`
are the WER benchmarks that `submit_sweep.sh` replaced. They wrote
`wer_report.csv` and `wer_summary.json`, the names the manuscript reads,
so they now refuse to run. Those names now hold the sweep's raw Large v3
test-clean cell (audit finding OUTPUTS-03). The May 2026 pair, most likely
written by the GPU script's array job 7682561, is kept in
`output/evaluation/pilot_may2026/`, and the scripts' headers are the record
of how it was made ([legacy/README.md](legacy/README.md)).
`submit_pilot_benchmark.sh` is the 200-utterance pilot behind job 7721017,
cited in [docs/conditions_audit.md](../docs/conditions_audit.md), and
writes only under `pilot/`. `submit_finetune_pyannote.sh` fine-tunes the
segmentation model and has never produced a reported result.
`evaluate_wer.sh` scores a directory of your own transcripts against
references (see [docs/evaluation.md](../docs/evaluation.md)). By default it
reads `output/transcripts/` in the repository and writes
`wer_report_transcripts.csv` and `wer_summary_transcripts.json` to
`$DATA/speech_transcription_env/output/evaluation/inhouse/`, never the
canonical names. `run_tests.sh` runs the test suite on ARC, where the
optional dependencies that skip tests on a laptop are installed.
