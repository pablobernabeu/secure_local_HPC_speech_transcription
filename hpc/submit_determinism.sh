#!/bin/bash
# =============================================================================
# submit_determinism.sh  —  run-to-run variation in transcription (Oxford ARC)
#
# Transcribes the same fixed subset several times and compares the words that
# come out. Two questions, and the job answers both in one submission:
#
#   1. Repeated under the *same* seed, does the stack return the same text?
#      Any disagreement is non-determinism, since nothing else differed.
#   2. Under *different* seeds, how far apart do the runs sit? That spread is
#      the resolution below which a reported difference means nothing.
#
# The subset is deliberately small. Determinism is a property of the decode,
# so it shows on a few hundred utterances, and there is no case for spending
# a full corpus pass on it several times over.
#
# Usage (submit from the repository root on ARC):
#
# Account: either project account is valid; the examples use educ-intract.
# Choose by current load, which changes: see the BALANCE note in .hpc-plan.yaml.
#
#   sbatch --account=educ-intract hpc/submit_determinism.sh
#
#   # Wider or narrower
#   DET_LIMIT=500 DET_SEEDS="0 1 2" sbatch --account=educ-intract hpc/submit_determinism.sh
#
# The default DET_SEEDS="0 1 2" does NOT reproduce the committed
# determinism/*.json, which used seeds 0 and 1. The values that did, with the
# job ID, are in hpc/runs/determinism.env. The first seed is decoded
# DET_REPEATS times and every other seed once, because only the first
# seed's repeats are compared. The committed run (job 8554985) still decoded
# every seed DET_REPEATS times and left seed1_run2 unused; the compared
# files are the same either way (audit finding SHELL-08).
#
# Overrides (set before sbatch): DET_SUITE (ami), MODEL
# (openai/whisper-large-v3), DET_LIMIT (200), DET_SEEDS, DET_REPEATS (2),
# DET_DTYPE (unset: the checkpoint's own dtype, float16 for Large v3, as
# every committed run decoded; float32 decodes on the GPU at the CPU arm's
# precision, which separates the precision from the hardware when the two
# arms disagree), REPORT_DIR (default
# $DATA/speech_transcription_env/output/evaluation; the job writes into its
# determinism/ subdirectory and refuses to start, exit 3, when a previous
# run's determinism_repeat.json is there, so give a new run its own
# REPORT_DIR), OVERWRITE (1 replaces a previous run's results).
#
# The same decodes on a processor: hpc/submit_determinism_cpu.sh.
#
# Outputs in $REPORT_DIR/determinism/:
#   seed<N>_run<K>.csv          — hypotheses from each run
#   determinism_repeat.json     — same seed, repeated: the determinism result
#   determinism_seeds.json      — across seeds: the noise floor
# =============================================================================

#SBATCH --job-name=determinism
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=08:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/determinism_%j.out
#SBATCH --error=logs/determinism_%j.err

set -euo pipefail

echo "DETERMINISM AND SEED ROBUSTNESS"
echo "==============================="
echo "Started: $(date)   Job: ${SLURM_JOB_ID:-n/a}   Node: $(hostname)"

REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu || exit 2

REPORT_DIR="${REPORT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
OUT="$REPORT_DIR/determinism"
SUITE="${DET_SUITE:-ami}"
MODEL="${MODEL:-openai/whisper-large-v3}"
LIMIT="${DET_LIMIT:-200}"
SEEDS="${DET_SEEDS:-0 1 2}"
REPEATS="${DET_REPEATS:-2}"
# Without DET_DTYPE no --dtype is passed, so the decode command is the one
# behind the committed runs.
DTYPE_ARGS=()
if [[ -n "${DET_DTYPE:-}" ]]; then
    DTYPE_ARGS=(--dtype "$DET_DTYPE")
fi

# Refuse to overwrite an earlier run's results. Job 8781724 wrote over the
# August run's files in the default directory this way, and a later run
# following hpc/runs/determinism.env would have erased 8781724's in turn
# before they were copied off ARC (audit finding SHELL-R6).
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
echo "Dtype:   ${DET_DTYPE:-as stored in the checkpoint}"
echo "Output:  $OUT"

# The GPU name is recorded because determinism is a property of the stack,
# not of the code alone: the same seed on a different card is a different
# experiment.
nvidia-smi --query-gpu=name --format=csv,noheader > "$OUT/gpu.txt" 2>/dev/null || true

# The fuller record (driver, torch/CUDA builds, every package) beside gpu.txt.
arc_record_env "$OUT"                  \
    "DET_SUITE=${SUITE}"               \
    "MODEL=${MODEL}"                   \
    "DET_LIMIT=${LIMIT}"               \
    "DET_SEEDS=${SEEDS}"               \
    "DET_REPEATS=${REPEATS}"           \
    "DET_DTYPE=${DET_DTYPE:-(checkpoint)}" \
    "REPORT_DIR=${REPORT_DIR}"

read -r FIRST_SEED _ <<< "$SEEDS"
for seed in $SEEDS; do
    # Only the first seed's repeats are compared (determinism_repeat.json);
    # the other seeds enter determinism_seeds.json through run 1 alone, so
    # repeating them would spend GPU time on files nothing reads.
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
            ${DTYPE_ARGS[@]+"${DTYPE_ARGS[@]}"} \
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
