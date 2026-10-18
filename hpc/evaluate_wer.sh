#!/bin/bash
# =============================================================================
#  evaluate_wer.sh — score your own transcripts against references on ARC
#
#  Runs the standalone `evaluation.wer` module over a directory of
#  transcripts written by hpc/batch_transcription.sh and a directory of
#  reference transcripts matched to them by file name. WER scoring is
#  light-weight and CPU-bound; the script stays on the `htc` cluster's
#  `short` partition so it can be queued behind the transcription jobs.
#
#  Submission:
#      sbatch hpc/evaluate_wer.sh                            # defaults below
#      sbatch hpc/evaluate_wer.sh path/to/hyp path/to/ref [path/to/report_dir]
#
#  Defaults:
#      hypotheses  $REPO_DIR/output/transcripts, where batch_transcription.sh
#                  writes (the old default, $DATA/.../output/transcripts, is a
#                  directory nothing writes to; audit finding NEW-02)
#      references  $DATA/speech_transcription_env/reference_transcripts
#      reports     $DATA/speech_transcription_env/output/evaluation/inhouse
#
#  Outputs, in the report directory:
#      wer_report_transcripts.csv     one row per matched transcript
#      wer_summary_transcripts.json   the corpus-level summary
#  The names are evaluation.wer's own defaults and the directory is this
#  script's. It used to write wer_report.csv and wer_summary.json into the
#  evaluation directory, the names of the LibriSpeech Large v3 result the
#  manuscript reads, so scoring your own recordings overwrote that result on
#  ARC (audit findings SHELL-09, XREF-01). The job refuses to start (exit 3)
#  when the summary already exists, unless OVERWRITE=1.
#
#  Exit status: 1 no environment or no references, 2 preflight failed,
#  3 an earlier summary in the way, 4 no transcripts to score.
#
#  Reference: https://arc-user-guide.readthedocs.io/en/latest/arc-script-basics.html
# =============================================================================

#SBATCH --job-name=wer_eval
#SBATCH --output=logs/wer_eval_%j.out
#SBATCH --error=logs/wer_eval_%j.err
#SBATCH --clusters=htc
#SBATCH --partition=short
#SBATCH --time=01:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=2
# WER scoring is CPU-only; no GPU is requested.

set -euo pipefail

echo "📐 ARC WER EVALUATION"
echo "====================="
echo "Job started at: $(date)"
echo "Node:           ${SLURM_NODENAME:-local}"
echo "Job ID:         ${SLURM_JOB_ID:-n/a}"
echo "Cluster:        ${SLURM_CLUSTER_NAME:-n/a}"

# -----------------------------------------------------------------------------
# Environment (CPU). The preflight replaces the old `pip install jiwer` on a
# failed import: a job never installs into the shared environment, and
# jiwer is pinned in requirements-lock.txt.
# -----------------------------------------------------------------------------
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" || exit 1
arc_preflight || exit 2
if ! python -c "import jiwer"; then
    echo "❌ jiwer is not importable; it is pinned in requirements-lock.txt." >&2
    exit 2
fi

# -----------------------------------------------------------------------------
# Arguments
# -----------------------------------------------------------------------------
HYPOTHESIS_DIR="${1:-${REPO_DIR}/output/transcripts}"
REFERENCE_DIR="${2:-${DATA}/speech_transcription_env/reference_transcripts}"
REPORT_DIR="${3:-${DATA}/speech_transcription_env/output/evaluation/inhouse}"
REPORT_CSV="$REPORT_DIR/wer_report_transcripts.csv"
SUMMARY_JSON="$REPORT_DIR/wer_summary_transcripts.json"

echo "Hypothesis:  $HYPOTHESIS_DIR"
echo "Reference:   $REFERENCE_DIR"
echo "Report dir:  $REPORT_DIR"

if [[ ! -d "$REFERENCE_DIR" ]]; then
    echo "❌ Reference directory not found: $REFERENCE_DIR" >&2
    exit 1
fi
# evaluation.wer scores the .txt and .json files at the top of the directory;
# with none there it would write an empty report and exit 0.
if [[ ! -d "$HYPOTHESIS_DIR" ]] || [[ -z "$(find "$HYPOTHESIS_DIR" -maxdepth 1 -type f \
        \( -iname '*.txt' -o -iname '*.json' \) -print -quit)" ]]; then
    echo "❌ No transcripts (.txt or .json) in $HYPOTHESIS_DIR." >&2
    echo "   Pass the directory holding them as the first argument." >&2
    exit 4
fi
if [[ -e "$SUMMARY_JSON" && "${OVERWRITE:-0}" != "1" ]]; then
    echo "❌ $SUMMARY_JSON already exists." >&2
    echo "   Pass another report directory as the third argument, or OVERWRITE=1." >&2
    exit 3
fi
mkdir -p "$REPORT_DIR" logs

# Record the software this scoring ran with beside its results.
arc_record_env "$REPORT_DIR"                  \
    "HYPOTHESIS_DIR=${HYPOTHESIS_DIR}"        \
    "REFERENCE_DIR=${REFERENCE_DIR}"          \
    "REPORT_DIR=${REPORT_DIR}"

# -----------------------------------------------------------------------------
# Run evaluation
# -----------------------------------------------------------------------------
python -m evaluation.wer \
    --hypothesis "$HYPOTHESIS_DIR" \
    --reference  "$REFERENCE_DIR" \
    --report     "$REPORT_CSV" \
    --summary    "$SUMMARY_JSON"

echo "✅ Finished at $(date)"
echo "   $REPORT_CSV"
echo "   $SUMMARY_JSON"
