#!/bin/bash
# =============================================================================
# aggregate_sweep.sh  —  Aggregate per-suite WER summaries after a sweep
#
# Runs evaluation/sweep_aggregate.py to collect all wer_summary*.json files
# produced by submit_sweep.sh and write a single cross-tabulation CSV and
# JSON for the manuscript.
#
# Intended to be submitted after the sweep array has completed, with
# SWEEP_DIR naming the directory the sweep wrote to (its SWEEP_OUTPUT_DIR),
# either manually or via a SLURM dependency:
#
#   JID=$(SWEEP_OUTPUT_DIR=$OUT sbatch --parsable hpc/submit_sweep.sh)
#   SWEEP_DIR=$OUT sbatch --dependency=afterok:${JID%%;*} hpc/aggregate_sweep.sh
#
# Default SWEEP_DIR:
#   $DATA/speech_transcription_env/output/evaluation/audit2026/sweep
# the directory of the sweep (jobs 8917985, 8917986, 8917987, see
# hpc/runs/sweep.env) that the committed 255-row
# sweep_aggregate.{csv,json} was built from. A bare
# `sbatch hpc/aggregate_sweep.sh` therefore rebuilds the committed matrix.
# The whole evaluation directory holds that sweep beside earlier ones and
# pre-flights, so aggregating it stops on repeated cells (audit findings
# SHELL-02, REV-02).
#
# Outputs, beside the summaries they aggregate:
#   $SWEEP_DIR/sweep_aggregate.csv
#   $SWEEP_DIR/sweep_aggregate.json
#
# Override examples:
#   SWEEP_DIR=/path/to/dir   sbatch hpc/aggregate_sweep.sh
#   INCLUDE_PILOT=true       sbatch hpc/aggregate_sweep.sh   # pilot rows as <suite>@pilot
#   PIPELINE_VERSION="..."   sbatch hpc/aggregate_sweep.sh   # --pipeline-version
#
# pipeline_version: each row takes it from its summary's own field, then from
# the git commit in the summary's run metadata, and only then from
# --pipeline-version. Summaries written since run metadata existed carry
# their commit, so a sweep needs no PIPELINE_VERSION. The older post-fix
# summaries in postfix/ predate it; aggregating them needs
# SWEEP_DIR=.../postfix PIPELINE_VERSION="post-fix (af3bee0)", the label
# the aggregate committed in aa6e61d carried.
#
# SWEEP_DIR is searched recursively and must hold one sweep: two summaries
# for the same (suite, model, condition) cell stop the job. Summaries of
# corpora outside the sweep, such as the multilingual FLEURS runs, are
# skipped with a warning.
# =============================================================================

#SBATCH --job-name=sweep_aggregate
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=00:30:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=logs/sweep_aggregate_%j.out
#SBATCH --error=logs/sweep_aggregate_%j.err

set -euo pipefail

# ---------------------------------------------------------------------------
# Environment (CPU-only; no GPU requested). The preflight runs without
# --gpu-required and stops the job (exit 2) only on a FAIL.
# ---------------------------------------------------------------------------
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" || exit 1
arc_preflight || exit 2

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
REPORT_DIR="${SWEEP_DIR:-${DATA}/speech_transcription_env/output/evaluation/audit2026/sweep}"
if [[ ! -d "$REPORT_DIR" ]]; then
    echo "❌ SWEEP_DIR ${REPORT_DIR} does not exist." >&2
    exit 1
fi

INCLUDE_PILOT_ARG=()
if [[ "${INCLUDE_PILOT:-false}" == "true" ]]; then
    INCLUDE_PILOT_ARG=(--include-pilot)
fi

# The fallback label for rows whose summary records no version (see the
# header).
PIPELINE_VERSION_ARG=()
if [[ -n "${PIPELINE_VERSION:-}" ]]; then
    PIPELINE_VERSION_ARG=(--pipeline-version "$PIPELINE_VERSION")
fi

# Record the software this aggregation ran with beside its results.
arc_record_env "$REPORT_DIR"                      \
    "SWEEP_DIR=${REPORT_DIR}"                     \
    "INCLUDE_PILOT=${INCLUDE_PILOT:-false}"       \
    "PIPELINE_VERSION=${PIPELINE_VERSION:-(from the summaries)}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Sweep aggregate"
echo "  Sweep dir:  ${REPORT_DIR}"
echo "  Pipeline:   ${PIPELINE_VERSION:-(from the summaries)}"
echo "  Output:     ${REPORT_DIR}/sweep_aggregate.{csv,json}"
echo "  Started:    $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python -m evaluation.sweep_aggregate          \
    --sweep-dir  "${REPORT_DIR}"              \
    --out        "${REPORT_DIR}/sweep_aggregate.csv"  \
    --out-json   "${REPORT_DIR}/sweep_aggregate.json" \
    "${PIPELINE_VERSION_ARG[@]}"              \
    "${INCLUDE_PILOT_ARG[@]}"

echo ""
echo "✅ Aggregate complete at $(date)"
echo "   CSV:  ${REPORT_DIR}/sweep_aggregate.csv"
echo "   JSON: ${REPORT_DIR}/sweep_aggregate.json"
