#!/bin/bash
# =============================================================================
# submit_determinism_cpu.sh  -  the determinism check on a processor (Oxford ARC)
#
# The CPU arm of submit_determinism.sh. That job decodes the first AMI test
# utterances on whichever GPU Slurm allocates, in the checkpoint's float16.
# This one decodes the same utterances with the same model, environment,
# seeds and decoding settings on a processor-only node, in float32, which is
# the path transcription.py takes on a desktop without CUDA. Inside the job
# it asks the GPU job's two questions (does a repeat return the same text,
# does the seed matter). Against the GPU runs it measures what the hardware
# and the precision change together, since nothing else on the decode path
# differs: python -m evaluation.determinism_cross compares the hypotheses
# once they are copied off the cluster, as it did for the GPU runs in
# output/evaluation/determinism/determinism_cross_accelerator.json.
#
# The defaults are the values hpc/runs/determinism.env records for the GPU
# runs: suite ami, the first 200 utterances, seeds 0 and 1, and two decodes
# of seed 0, so the arm lines up with them without overrides. Like
# submit_determinism.sh since c0f2258, it decodes seed 1 once, where the two
# runs that record holds, jobs 8554985 and 8781724, decoded it twice and
# compared only the first decode. submit_determinism.sh's own default seeds
# are "0 1 2".
#
# Usage (submit from the repository root on ARC):
#
#   ( set -a; . hpc/runs/determinism_cpu.env || exit 1; set +a
#     sbatch --account=educ-intract hpc/submit_determinism_cpu.sh )
#
# Overrides (set before sbatch): DET_SUITE (ami), MODEL
# (openai/whisper-large-v3), DET_LIMIT (200), DET_SEEDS ("0 1"), DET_REPEATS
# (2), DET_DTYPE (float32), REPORT_DIR (default
# $DATA/speech_transcription_env/output/evaluation; the job writes into its
# determinism_cpu/ subdirectory, so it cannot touch a GPU run's
# determinism/, and refuses to start, exit 3, when a previous run's
# determinism_repeat.json is there), OVERWRITE (1 replaces a previous run's
# results).
#
# Resources. Large v3 holds 1.55 billion parameters, 6.2 GB in float32, so
# 32 GB leaves room for loading and decoding. Every utterance costs one 30 s
# encoder window however short it is, so the default three decodes are 600
# such windows. Job 8978759, which decoded them on 16 cores of an AMD EPYC
# 9634 (htc-c074), took 1 h 17 min by sacct; 12 h is the partition's
# limit, and the log's per-utterance lines show the rate.
# --constraint=cpu keeps the job off the GPU nodes, whose processors would
# otherwise serve it while their cards sat idle. The CPU nodes are of more
# than one generation (Cascade Lake and Genoa in 2026), and the processor
# selects the kernels, so cpu.txt names it; to repeat a run on the same
# generation, narrow the constraint on the command line, for example
# sbatch --constraint=cpu_gen:Cascade_Lake.
#
# Outputs in $REPORT_DIR/determinism_cpu/:
#   seed<N>_run<K>.csv          hypotheses from each run
#   wer_seed<N>_run<K>.csv/.json  the WER report and summary of each run
#   determinism_repeat.json     same seed, repeated
#   determinism_seeds.json      across seeds
#   cpu.txt                     the processor, as gpu.txt names the GPU
#   environment/                the job's software and hardware record
# =============================================================================

#SBATCH --job-name=determinism_cpu
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --constraint=cpu
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --output=logs/determinism_cpu_%j.out
#SBATCH --error=logs/determinism_cpu_%j.err

set -euo pipefail

echo "DETERMINISM ON A PROCESSOR"
echo "=========================="
echo "Started: $(date)   Job: ${SLURM_JOB_ID:-n/a}   Node: $(hostname)"

REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" || exit 1
# The comparison with the GPU runs holds only if the software is the same,
# so an installed version that differs from the lock stops the job here
# instead of confounding the result.
arc_preflight --lock "$REPO_DIR/requirements-lock.txt" || exit 2

# No GPU is requested, and none may be used: an empty CUDA_VISIBLE_DEVICES
# hides any card on the node from torch, and --device cpu below holds the
# model on the processor in any case.
export CUDA_VISIBLE_DEVICES=""
# One intra-op thread per allocated core. torch would otherwise size its
# pool from the cores it can see, and a processor's reduction order can
# depend on the thread count, so the count is fixed and recorded.
THREADS="${SLURM_CPUS_PER_TASK:-16}"
export OMP_NUM_THREADS="$THREADS" MKL_NUM_THREADS="$THREADS"

REPORT_DIR="${REPORT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
OUT="$REPORT_DIR/determinism_cpu"
SUITE="${DET_SUITE:-ami}"
MODEL="${MODEL:-openai/whisper-large-v3}"
LIMIT="${DET_LIMIT:-200}"
SEEDS="${DET_SEEDS:-0 1}"
REPEATS="${DET_REPEATS:-2}"
DTYPE="${DET_DTYPE:-float32}"

# Refuse to overwrite an earlier run's results, as submit_determinism.sh
# does (audit finding SHELL-R6).
if [[ -e "$OUT/determinism_repeat.json" && "${OVERWRITE:-0}" != "1" ]]; then
    echo "ERROR: $OUT already holds a run's results (determinism_repeat.json)." >&2
    echo "   Set REPORT_DIR to a new directory, or OVERWRITE=1 to replace them." >&2
    exit 3
fi
mkdir -p "$OUT" logs

echo ""
echo "Suite:   $SUITE        Model: $MODEL"
echo "Subset:  first $LIMIT utterances"
echo "Seeds:   $SEEDS   (the first run $REPEATS times, the others once)"
echo "Device:  cpu, $DTYPE, $THREADS threads"
echo "Output:  $OUT"

# On this arm the processor is the accelerator, so it is named beside the
# results as gpu.txt names the card on the GPU arm.
CPU_NAME="$(grep -m1 '^model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ *//')" || true
printf '%s\n' "${CPU_NAME:-unknown}" > "$OUT/cpu.txt"

arc_record_env "$OUT"                  \
    "DET_SUITE=${SUITE}"               \
    "MODEL=${MODEL}"                   \
    "DET_LIMIT=${LIMIT}"               \
    "DET_SEEDS=${SEEDS}"               \
    "DET_REPEATS=${REPEATS}"           \
    "DET_DTYPE=${DTYPE}"               \
    "OMP_NUM_THREADS=${THREADS}"       \
    "REPORT_DIR=${REPORT_DIR}"

read -r FIRST_SEED _ <<< "$SEEDS"
for seed in $SEEDS; do
    # Only the first seed's repeats are compared, as in submit_determinism.sh.
    runs=1
    if [[ "$seed" == "$FIRST_SEED" ]]; then
        runs="$REPEATS"
    fi
    for repeat in $(seq 1 "$runs"); do
        dump="$OUT/seed${seed}_run${repeat}.csv"
        echo ""
        echo "--- seed $seed, run $repeat ---"
        python -m evaluation.benchmark_wer      \
            --suite "$SUITE"                    \
            --model "$MODEL"                    \
            --conditions raw                    \
            --seed "$seed"                      \
            --limit "$LIMIT"                    \
            --device cpu                        \
            --dtype "$DTYPE"                    \
            --report  "$OUT/wer_seed${seed}_run${repeat}.csv"   \
            --summary "$OUT/wer_seed${seed}_run${repeat}.json"  \
            --dump-hypotheses "$dump"
    done
done

echo ""
echo "--- same seed, repeated: is the decode deterministic? ---"
REPEAT_DUMPS=()
for repeat in $(seq 1 "$REPEATS"); do
    REPEAT_DUMPS+=("$OUT/seed${FIRST_SEED}_run${repeat}.csv")
done
python -m evaluation.determinism "${REPEAT_DUMPS[@]}" \
    --json "$OUT/determinism_repeat.json"

echo ""
echo "--- across seeds: how much is seed noise? ---"
SEED_DUMPS=()
for seed in $SEEDS; do
    SEED_DUMPS+=("$OUT/seed${seed}_run1.csv")
done
python -m evaluation.determinism "${SEED_DUMPS[@]}" \
    --json "$OUT/determinism_seeds.json"

echo ""
echo "Finished: $(date)"
ls -lh "$OUT"/determinism_*.json 2>/dev/null || true
