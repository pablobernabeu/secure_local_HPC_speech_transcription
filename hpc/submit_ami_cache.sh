#!/bin/bash
# =============================================================================
# submit_ami_cache.sh  —  build the AMI meeting reconstruction cache (CPU only)
#
# Streams the utterance-level AMI IHM release, reassembles each meeting on its
# original timeline, and writes the result as a WAV plus a JSON reference.
# Downloading and decoding roughly eighteen hours of audio is network- and
# CPU-bound, so it runs here without a GPU; the diarisation jobs then read the
# cache instead of re-downloading the corpus for every configuration.
#
# Usage (from the repository root on ARC):
#
# Account: either project account is valid; the examples use educ-intract.
# Choose by current load, which changes: see the BALANCE note in .hpc-plan.yaml.
#
#   sbatch --account=educ-intract hpc/submit_ami_cache.sh
#
#   # One split only
#   SPLITS=validation sbatch --account=educ-intract hpc/submit_ami_cache.sh
#
# Overrides (set before sbatch): SPLITS ("validation test"), MIX_MODE
# (timeline), MAX_MINUTES (unset = whole meetings), CACHE_DIR
# ($DATA/ami_cache), REPORT_DIR ($DATA/speech_transcription_env/output/
# evaluation). CACHE_DIR, MAX_MINUTES and REPORT_DIR are generic names that
# sbatch passes through from the submitting shell; the effective values are
# echoed.
#
# Output: $DATA/ami_cache/<split>_timeline_full/, and for each split the
# reconstruction audit $REPORT_DIR/reconstruction_audit_<split>.json
# (evaluation/audit_reconstruction.py): whether each rebuilt meeting's audio
# sits where its reference annotation says, re-derived from the waveform, so
# the cache the DER jobs score carries its own archived check. The audit
# runs on the full-length timeline cache, the one the DER benchmark reads;
# with MIX_MODE=concat or MAX_MINUTES set it is skipped, and the job says so.
# An audit that fails fails the job, after every split has been audited.
# =============================================================================

#SBATCH --job-name=ami_cache
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=06:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=logs/ami_cache_%j.out
#SBATCH --error=logs/ami_cache_%j.err

set -euo pipefail

echo "AMI MEETING RECONSTRUCTION CACHE"
echo "================================"
echo "Started: $(date)   Job: ${SLURM_JOB_ID:-n/a}   Node: $(hostname)"

# Environment, CPU preflight and token (hpc/common/arc_common.sh). The
# preflight runs without --gpu-required and stops the job (exit 2) only on
# a FAIL, such as a package loaded from outside the environment.
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" || exit 1
arc_preflight || exit 2
arc_load_hf_token "$REPO_DIR" || exit 1

CACHE_DIR="${CACHE_DIR:-${DATA}/ami_cache}"
REPORT_DIR="${REPORT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
SPLITS="${SPLITS:-validation test}"
MIX_MODE="${MIX_MODE:-timeline}"
mkdir -p "$CACHE_DIR" "$REPORT_DIR" logs

MAX_MINUTES_ARG=()
if [[ -n "${MAX_MINUTES:-}" ]]; then
    MAX_MINUTES_ARG=(--max-minutes "$MAX_MINUTES")
fi

echo "Splits: $SPLITS   Mix mode: $MIX_MODE   Max minutes: ${MAX_MINUTES:-(whole meetings)}"

# Record the software this cache was built with beside the cache itself.
arc_record_env "$CACHE_DIR"                       \
    "SPLITS=${SPLITS}"                            \
    "MIX_MODE=${MIX_MODE}"                        \
    "MAX_MINUTES=${MAX_MINUTES:-}"                \
    "CACHE_DIR=${CACHE_DIR}"                      \
    "REPORT_DIR=${REPORT_DIR}"

for split in $SPLITS; do
    echo ""
    echo "--- $split ($MIX_MODE) -> $CACHE_DIR"
    python -m evaluation.benchmark_der \
        --split "$split"             \
        --mix-mode "$MIX_MODE"       \
        --cache-dir "$CACHE_DIR"     \
        --build-cache-only           \
        "${MAX_MINUTES_ARG[@]}"
done

# Audit each full-length timeline reconstruction. The directory name is
# benchmark_der._cache_paths' "<split>_timeline_full"; other layouts are
# named after their cap, and a truncated or concatenated cache is not what
# the DER benchmark scores, so they are not audited.
AUDIT_RC=0
if [[ "$MIX_MODE" == "timeline" && -z "${MAX_MINUTES:-}" ]]; then
    for split in $SPLITS; do
        echo ""
        echo "--- reconstruction audit: $split -> $REPORT_DIR/reconstruction_audit_${split}.json"
        python -m evaluation.audit_reconstruction "$CACHE_DIR/${split}_timeline_full" \
            --json "$REPORT_DIR/reconstruction_audit_${split}.json" || AUDIT_RC=$?
    done
else
    echo ""
    echo "Reconstruction audit skipped: it covers the full-length timeline cache"
    echo "(MIX_MODE=timeline, MAX_MINUTES unset) that the DER benchmark reads."
fi

echo ""
du -sh "$CACHE_DIR"/* 2>/dev/null || true
echo "Finished: $(date)"
if [[ $AUDIT_RC -ne 0 ]]; then
    echo "❌ A reconstruction audit failed (last exit status $AUDIT_RC)." >&2
    exit "$AUDIT_RC"
fi
