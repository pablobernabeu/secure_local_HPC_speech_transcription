#!/bin/bash
# =============================================================================
# submit_anonymisation.sh  —  voice anonymisation trade-off on Oxford ARC
#
# Measures both sides of the trade at several McAdams coefficients: whether
# the voice stops being recognisable, and what the disguise costs the words.
#
# The transform itself is CPU-only and needs no cluster. This job is here for
# the evaluation, which needs a speaker-embedding model and an ASR pass over
# each utterance twice, once before and once after.
#
# Usage (submit from the repository root on ARC).
# Account: either project account is valid; the examples use educ-intract.
# Choose by current load, which changes: see the BALANCE note in .hpc-plan.yaml.
#
# The two published configurations, one command each. ANON_PRESET fixes the
# utterance count, the coefficients and the per-meeting cap, and REPORT_DIR
# names a fresh directory, so neither can overwrite a result it is to be
# compared with. hpc/runs/anonymisation.env and
# hpc/runs/anonymisation_single_meeting.env hold the same two invocations,
# with the jobs behind the committed files:
#
#   Multi-meeting, the configuration of the committed
#   output/evaluation/anonymisation_{summary.json,report.csv}, job 8917989
#   (400 utterances, the first 25 usable ones in start-time order from each
#   of the 16 test meetings, alphas 0.5 0.7 0.8 0.9):
#
#     ANON_PRESET=multi-meeting \
#     REPORT_DIR="$DATA/speech_transcription_env/output/evaluation/repro/anonymisation" \
#       sbatch --account=educ-intract hpc/submit_anonymisation.sh
#
#   Single meeting, the configuration of the committed
#   output/evaluation/anonymisation_single_meeting/, job 8917988
#   (200 utterances from the front of the split, which is the meeting
#   EN2002a, alphas 0.5 0.7 0.8 0.9):
#
#     ANON_PRESET=single-meeting \
#     REPORT_DIR="$DATA/speech_transcription_env/output/evaluation/repro/anonymisation_single_meeting" \
#       sbatch --account=educ-intract hpc/submit_anonymisation.sh
#
# Both committed runs used these presets at code 6f9bf56. Earlier runs of the
# same configurations predate the fixes to the transform's overlap-add, the
# linkage chance level and the per-meeting cap (audit findings EPRIV-02,
# EPRIV-04, EPRIV-03), and their numbers do not reproduce. Job 8781723 took
# up to 42 utterances from one meeting under a cap of 25, and job 8573363 read
# the meeting in the order the dataset streams it, not in start-time order, so
# it drew a different 200 utterances.
#
# Without a preset the script's own defaults apply, which are NOT a published
# configuration: ANON_LIMIT=300, ANON_ALPHAS="0.7 0.8 0.9", no per-meeting cap.
# Override them with ANON_LIMIT, ANON_ALPHAS and ANON_PER_MEETING; a preset
# combined with any of them is refused, so a reproduction cannot be altered
# by a variable left over in the shell.
#
# REPORT_DIR defaults to a directory named after the job,
#   $DATA/speech_transcription_env/output/evaluation/anonymisation_runs/<job id>
# and the job refuses to start when REPORT_DIR already holds an
# anonymisation_summary.json, unless ANON_OVERWRITE=1.
#
# Outputs in $REPORT_DIR:
#   anonymisation_summary.json  — the privacy/intelligibility curve
#   anonymisation_report.csv    — one row per (coefficient, utterance)
# =============================================================================

#SBATCH --job-name=anonymisation
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=08:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/anonymisation_%j.out
#SBATCH --error=logs/anonymisation_%j.err

set -euo pipefail

echo "VOICE ANONYMISATION TRADE-OFF"
echo "============================="
echo "Started: $(date)   Job: ${SLURM_JOB_ID:-n/a}   Node: $(hostname)"

# The configuration is settled before any module or model is loaded, so a
# mistake in it costs seconds of the allocation, not the model load.
case "${ANON_PRESET:-}" in
    "")
        LIMIT="${ANON_LIMIT:-300}"
        ALPHAS="${ANON_ALPHAS:-0.7 0.8 0.9}"
        # ANON_PER_MEETING caps how many utterances are accepted from any
        # one meeting. Unset reads from the front of the split, as the
        # first published run did (one meeting, four speakers).
        PER_MEETING="${ANON_PER_MEETING:-}"
        ;;
    single-meeting|multi-meeting)
        if [[ -n "${ANON_LIMIT:-}${ANON_ALPHAS:-}${ANON_PER_MEETING:-}" ]]; then
            echo "ANON_PRESET=${ANON_PRESET} fixes the configuration; unset" \
                 "ANON_LIMIT, ANON_ALPHAS and ANON_PER_MEETING, or drop the" \
                 "preset to set them yourself." >&2
            exit 2
        fi
        ALPHAS="0.5 0.7 0.8 0.9"
        if [[ "$ANON_PRESET" == single-meeting ]]; then
            LIMIT=200
            PER_MEETING=""
        else
            LIMIT=400
            PER_MEETING=25
        fi
        ;;
    *)
        echo "Unknown ANON_PRESET '${ANON_PRESET}'; use single-meeting or" \
             "multi-meeting, or leave it unset." >&2
        exit 2
        ;;
esac

REPORT_DIR="${REPORT_DIR:-${DATA:?DATA is not set; give REPORT_DIR explicitly}/speech_transcription_env/output/evaluation/anonymisation_runs/${SLURM_JOB_ID:-local_$(date +%Y%m%d_%H%M%S)}}"
if [[ -f "$REPORT_DIR/anonymisation_summary.json" && "${ANON_OVERWRITE:-0}" != 1 ]]; then
    echo "$REPORT_DIR already holds an anonymisation_summary.json. Give a" \
         "fresh REPORT_DIR, or set ANON_OVERWRITE=1 to replace it." >&2
    exit 2
fi

PER_MEETING_ARG=()
if [[ -n "$PER_MEETING" ]]; then
    PER_MEETING_ARG=(--per-meeting "$PER_MEETING")
fi

# Environment, GPU gate and token through the shared helper, as in every
# other result job (audit finding SHELL-10): pinned Anaconda3 and CUDA
# modules instead of whatever `module load` resolves to that day, and a
# preflight failure stops the job with exit 2.
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu --diarisation-required || exit 2
# The pyannote embedding model is gated.
arc_load_hf_token "$REPO_DIR" || exit 1

mkdir -p "$REPORT_DIR" logs

echo ""
echo "Preset: ${ANON_PRESET:-(none)}"
echo "Utterances: $LIMIT      Coefficients: $ALPHAS"
echo "Per meeting: ${PER_MEETING:-(no cap)}"
echo "Report dir: $REPORT_DIR"
echo ""

# Record the software and GPU this run used beside its results.
arc_record_env "$REPORT_DIR"                          \
    "ANON_PRESET=${ANON_PRESET:-}"                    \
    "ANON_LIMIT=${LIMIT}"                             \
    "ANON_ALPHAS=${ALPHAS}"                           \
    "ANON_PER_MEETING=${PER_MEETING}"                 \
    "REPORT_DIR=${REPORT_DIR}"

# $ALPHAS is split on purpose: each coefficient is its own argument.
# shellcheck disable=SC2086
python -m evaluation.benchmark_anonymisation \
    --output-dir "$REPORT_DIR"               \
    --limit "$LIMIT"                         \
    --alphas $ALPHAS                         \
    "${PER_MEETING_ARG[@]}"

echo ""
echo "Finished: $(date)"
ls -lh "$REPORT_DIR"/anonymisation_* 2>/dev/null || true
