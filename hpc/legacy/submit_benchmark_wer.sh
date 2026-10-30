#!/bin/bash
# Everything after the `exit 1` below is kept as a record and never runs, so
# ShellCheck's unreachable-command note (SC2317) is switched off for the file.
# shellcheck disable=SC2317
# RETIRED (audit findings XREF-01, SHELL-09): kept only as the record of how
# the legacy wer_report.csv and wer_summary.json were first made. It wrote
# those names, which the manuscript reads, by default and even for a
# BENCHMARK_LIMIT sanity check, so it refuses to run. Use hpc/submit_sweep.sh;
# see hpc/legacy/README.md. The body below is unmaintained: it still carries
# the in-job `pip install` that the live scripts no longer have.
echo "hpc/legacy/submit_benchmark_wer.sh is retired; use hpc/submit_sweep.sh (hpc/legacy/README.md)." >&2
exit 1
# =============================================================================
# submit_benchmark_wer.sh  —  SLURM job for public-benchmark WER evaluation
#
# Evaluates the transcription pipeline against a public ASR corpus
# (default: LibriSpeech test-clean) and writes results to:
#
#   $DATA/speech_transcription_env/output/evaluation/wer_report.csv
#   $DATA/speech_transcription_env/output/evaluation/wer_summary.json
#
# Usage (submit from the repository root):
#
#   sbatch hpc/submit_benchmark_wer.sh
#
# Override corpus parameters without editing this file:
#
#   BENCHMARK_DATASET=LIUM/tedlium \
#   BENCHMARK_CONFIG=release3      \
#   BENCHMARK_SPLIT=test           \
#   sbatch hpc/submit_benchmark_wer.sh
#
# To score only a subset of utterances (useful for a quick sanity check):
#
#   BENCHMARK_LIMIT=200 sbatch hpc/submit_benchmark_wer.sh
#
# To also keep the verbatim hypotheses, for scoring what a condition did to
# the words rather than only to the error rate:
#
#   DUMP_HYPOTHESES=1 sbatch hpc/submit_benchmark_wer.sh
#
# PROVENANCE: superseded by submit_benchmark_wer_gpu.sh and then
# submit_sweep.sh. ARC holds four logs matching its logs/benchmark_wer_%j.out
# pattern, all from 2026-05-16 (7662692, 7662812, 7662816, 7662825). Which
# committed files, if any, they produced is not recorded. Note that it
# writes the canonical wer_report.csv / wer_summary.json by default, so
# running it overwrites the files the manuscript reads.
# =============================================================================

#SBATCH --job-name=benchmark_wer
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=logs/benchmark_wer_%j.out
#SBATCH --error=logs/benchmark_wer_%j.err

set -euo pipefail

# -----------------------------------------------------------------------------
module purge
module load Anaconda3 || true

REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
ACTIVATION_SCRIPT="$REPO_DIR/activate_project_env_arc.sh"
if [[ -f "$ACTIVATION_SCRIPT" ]]; then
    # shellcheck source=/dev/null
    source "$ACTIVATION_SCRIPT"
else
    echo "❌ Activation script not found at $ACTIVATION_SCRIPT" >&2
    exit 1
fi

cd "$REPO_DIR"

# Suppress the FutureWarning from transformers about the deprecated
# TRANSFORMERS_CACHE variable, which may be set by the cluster environment.
unset TRANSFORMERS_CACHE

# -----------------------------------------------------------------------------
# Corpus parameters (can be overridden via environment before sbatch)
# -----------------------------------------------------------------------------
DATASET="${BENCHMARK_DATASET:-librispeech_asr}"
CONFIG="${BENCHMARK_CONFIG:-clean}"
SPLIT="${BENCHMARK_SPLIT:-test}"
LIMIT="${BENCHMARK_LIMIT:-}"   # empty string = full split

# -----------------------------------------------------------------------------
# Ensure datasets package is available
# -----------------------------------------------------------------------------
python -c "import datasets" 2>/dev/null \
    || pip install --quiet "datasets>=2.14.0"

# -----------------------------------------------------------------------------
# Output paths — mirror the defaults in evaluate_wer.sh
# -----------------------------------------------------------------------------
REPORT_DIR="${DATA}/speech_transcription_env/output/evaluation"
mkdir -p "$REPORT_DIR" logs

LIMIT_ARG=()
if [[ -n "$LIMIT" ]]; then
    LIMIT_ARG=(--limit "$LIMIT")
fi

# -----------------------------------------------------------------------------
# Optionally keep the verbatim reference and hypothesis text alongside the
# metrics, so a question about what a condition did to the words can be
# answered without transcribing the corpus again.  Off by default, because
# the file holds transcript text.
DUMP_ARG=()
if [[ -n "${DUMP_HYPOTHESES:-}" ]]; then
    DUMP_ARG=(--dump-hypotheses "$REPORT_DIR/wer_hypotheses.csv")
    echo "Hypothesis dump: $REPORT_DIR/wer_hypotheses.csv"
fi

python -m evaluation.benchmark_wer \
    --dataset  "$DATASET"          \
    --config   "$CONFIG"           \
    --split    "$SPLIT"            \
    --report   "$REPORT_DIR/wer_report.csv"  \
    --summary  "$REPORT_DIR/wer_summary.json" \
    "${LIMIT_ARG[@]}" "${DUMP_ARG[@]}"

echo "✅ Benchmark complete at $(date)"
