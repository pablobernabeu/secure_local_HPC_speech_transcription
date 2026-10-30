#!/bin/bash
# =============================================================================
# submit_case_study.sh  —  End-to-end worked example on real long-form audio
#
# Runs the complete deployed pipeline over one Codex Mentis episode:
# transcription, speaker diarisation, word-level timestamps, name masking,
# the redacted parallel artefacts, the run manifest and the review flags.
# Every privacy and provenance feature the workflow offers is exercised in a
# single pass, on audio that is long-form, conversational and rights-clear.
#
# Episode 5, "Beyond the cloud: Reclaiming data sovereignty in speech
# transcription", is the default: it is about this workflow's own subject,
# which makes it a natural worked example.
#
# The corpus is the author's own NotebookLM podcast, so there is no consent
# or licensing encumbrance, and it is a two-voice dialogue, which gives the
# diarisation a known speaker count to be scored against.
#
# The audio must already be on the cluster; it is git-ignored, so fetch it
# with (from the repository root, on a node with outbound network):
#
#   python -m evaluation.fetch_codex_mentis --dest $DATA/codex_mentis
#
# Outputs land in $REPO/output/transcripts/ (git-ignored) as:
#   codex_mentis_ep05_transcript.txt / .docx      (masked prose)
#   codex_mentis_ep05_transcript.json / .vtt      (raw, timestamped)
#   codex_mentis_ep05_transcript_redacted.*       (masked parallel)
#   codex_mentis_ep05_manifest.json               (digests + provenance)
#   codex_mentis_ep05_review.json                 (segments to review)
# and the structural evaluation in $CASE_REPORT_DIR, by default
# $DATA/speech_transcription_env/output/case_study/, as
#   podcast_eval_summary.json / podcast_eval_report.csv
# with the environment record in its environment/ subdirectory.
#
# The committed copy lives in the repository's output/case_study/, which is
# tracked. The job no longer writes there: a run left the ARC clone with a
# modified tracked file, and a later `git pull` could then conflict (audit
# finding REV-04). To commit a new result, copy it in deliberately. The
# review and run manifest go in as the job wrote them, since the manifest
# records the review's SHA-256:
#   cp "$DATA/speech_transcription_env/output/case_study/podcast_eval_"* output/case_study/
#   cp output/transcripts/codex_mentis_ep05_{review,manifest}.json output/case_study/
# The job refuses to start (exit 6) when $CASE_REPORT_DIR already holds a
# podcast_eval_summary.json, unless OVERWRITE=1.
#
# When the recording is decoded to 16 kHz WAV first, transcription.py is
# given --source-audio (the original recording) and --source-derivation (the
# exact ffmpeg command), so the run manifest records the original's SHA-256
# and how the transcribed file was made from it (audit finding CORE-04).
#
# The structural evaluation takes each episode's duration from a fetch
# manifest: CASE_MANIFEST when it is set, else
# $DATA/codex_mentis/manifest.json when it exists (fetch_codex_mentis writes
# it beside the audio it fetches), else the committed
# data/codex_mentis/manifest.json.
#
# Exit status: 2 no audio or no corpus manifest, 3 no ffmpeg to decode the
# audio, 4 preflight failed (no GPU, no usable pyannote or token), 5 the
# structural evaluation or the provenance verification failed (both are run
# first), 6 an earlier result in the way.
#
# Overrides (set before sbatch):
#   CASE_AUDIO=/path/to/episode.m4a
#   CASE_NAME=codex_mentis_ep05
#   CASE_MANIFEST=/path/to/manifest.json
#   CASE_REPORT_DIR=/path/to/dir
#   OVERWRITE=1
#
# Submit from the repository root:
#   sbatch --account='<your-project>' hpc/submit_case_study.sh
# =============================================================================

#SBATCH --job-name=case_study
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/case_study_%j.out
#SBATCH --error=logs/case_study_%j.err

set -euo pipefail

REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
mkdir -p logs output/transcripts

# Fail in seconds, with named remedies, rather than partway into the run.
# Diarisation is required here, not merely nice to have: this job exists to
# demonstrate speaker attribution, so running without it would "succeed"
# while missing its own point. Exit 4 is this job's documented preflight
# status (2 is taken by the missing-audio check below).
arc_require_gpu --diarisation-required || exit 4

DEFAULT_AUDIO="${DATA}/codex_mentis/audio/ep05_beyond-the-cloud-reclaiming-data-sovereignty-in-speech-trans.m4a"
AUDIO="${CASE_AUDIO:-$DEFAULT_AUDIO}"
NAME="${CASE_NAME:-codex_mentis_ep05}"
REPORT_DIR="${CASE_REPORT_DIR:-${DATA}/speech_transcription_env/output/case_study}"

if [[ ! -f "$AUDIO" ]]; then
    echo "❌ Audio not found: $AUDIO" >&2
    echo "   Fetch it first:  python -m evaluation.fetch_codex_mentis --dest \$DATA/codex_mentis" >&2
    exit 2
fi

# The structural evaluation reads each episode's duration from the corpus
# manifest. fetch_codex_mentis writes one beside the audio it fetches; a
# recording copied to the cluster by hand has only the repository's own,
# data/codex_mentis/manifest.json. The job used to name the first alone, and
# on ARC it does not exist: the evaluation dropped every coverage figure
# without a word until 4b22326 made it refuse a missing manifest, and then
# re-run 8978758 failed after transcribing (NEW-06). The manifest is now
# chosen, and checked, before anything is transcribed.
if [[ -n "${CASE_MANIFEST:-}" ]]; then
    MANIFEST="$CASE_MANIFEST"
elif [[ -f "${DATA}/codex_mentis/manifest.json" ]]; then
    MANIFEST="${DATA}/codex_mentis/manifest.json"
else
    MANIFEST="${REPO_DIR}/data/codex_mentis/manifest.json"
fi
if [[ ! -f "$MANIFEST" ]]; then
    echo "❌ Corpus manifest not found: $MANIFEST" >&2
    echo "   Set CASE_MANIFEST to the fetch manifest that lists the episode." >&2
    exit 2
fi
if [[ -e "$REPORT_DIR/podcast_eval_summary.json" && "${OVERWRITE:-0}" != "1" ]]; then
    echo "❌ $REPORT_DIR already holds a case-study result (podcast_eval_summary.json)." >&2
    echo "   Set CASE_REPORT_DIR to a new directory, or OVERWRITE=1 to replace it." >&2
    exit 6
fi
mkdir -p "$REPORT_DIR"

# Decoding .m4a is no longer necessary: audio_io routes compressed
# containers through ffmpeg, so the pipeline opens them directly. It is kept
# because it is worth doing anyway. The pipeline decodes twice per run, once
# for diarisation and once for transcription, so converting once to 16 kHz
# mono, the rate it resamples to regardless, saves the second decode of a
# half-hour recording and caches the result for any re-run.
#
# The decode means transcription.py sees a derived file, not the recording,
# so SOURCE_ARGS tells the run manifest what the original was and how the
# WAV was made from it (CORE-04). The derivation is the command itself,
# shell-quoted with printf %q so it can be re-run as written.
SOURCE_ARGS=()
case "${AUDIO,,}" in
    *.wav|*.flac|*.ogg|*.mp3) ;;
    *)
        ORIGINAL_AUDIO="$AUDIO"
        CONVERTED="${AUDIO%.*}_16k.wav"
        DECODE_ARGS=(-nostdin -loglevel error -y -i "$ORIGINAL_AUDIO"
                     -ac 1 -ar 16000 -c:a pcm_s16le "$CONVERTED")
        FFMPEG="$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || true)"
        # A cached decode is reused only when the stamp beside it names the
        # SHA-256 of the recording it was decoded from. Without the check, a
        # re-fetched recording (the host re-encodes, fetch_codex_mentis
        # --accept-new) would be transcribed from the old decode while the
        # manifest named the new original (audit finding DEPS-15).
        SOURCE_SHA="$(sha256sum "$ORIGINAL_AUDIO" | cut -d' ' -f1)"
        STAMP="${CONVERTED}.source.sha256"
        if [[ -f "$CONVERTED" && -f "$STAMP" && "$(cat "$STAMP")" == "$SOURCE_SHA" ]]; then
            echo "   Using cached decode: $CONVERTED (source SHA-256 matches)"
            DERIVATION="cached output of an earlier run of: $(printf '%q ' "${FFMPEG:-ffmpeg}" "${DECODE_ARGS[@]}")"
        else
            if [[ -f "$CONVERTED" ]]; then
                echo "   Cached decode $CONVERTED has no matching source stamp; decoding again"
            fi
            if [[ -z "$FFMPEG" || ! -x "$FFMPEG" ]]; then
                echo "❌ Cannot decode ${AUDIO##*.}: no ffmpeg available." >&2
                echo "   Install imageio-ffmpeg, or supply WAV/FLAC/MP3/OGG." >&2
                exit 3
            fi
            echo "   Decoding ${AUDIO##*.} to 16 kHz mono WAV via $FFMPEG"
            "$FFMPEG" "${DECODE_ARGS[@]}"
            printf '%s\n' "$SOURCE_SHA" > "$STAMP"
            DERIVATION="$(printf '%q ' "$FFMPEG" "${DECODE_ARGS[@]}")"
        fi
        SOURCE_ARGS=(--source-audio "$ORIGINAL_AUDIO"
                     --source-derivation "${DERIVATION% }")
        AUDIO="$CONVERTED"
        ;;
esac

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Case study  |  $NAME"
echo "  Audio:   $AUDIO"
echo "  SHA-256: $(sha256sum "$AUDIO" | cut -d' ' -f1)"
echo "  Started: $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true

# Record the software and GPU this run used beside the case-study results.
arc_record_env "$REPORT_DIR"               \
    "CASE_AUDIO=${AUDIO}"                  \
    "CASE_SOURCE_AUDIO=${ORIGINAL_AUDIO:-$AUDIO}" \
    "CASE_NAME=${NAME}"                    \
    "CASE_MANIFEST=${MANIFEST}"            \
    "CASE_REPORT_DIR=${REPORT_DIR}"

# The full deployed pipeline. The language is stated explicitly rather than
# detected, which is what the workflow now recommends to every user. The
# review runs its two optional checks at their suggested settings, because
# the case study is where the default review missed a passage Whisper wrote
# twice and three cues of zero length (audit finding NEW-12).
python transcription.py "$AUDIO"           \
    --language english                     \
    --timestamps                           \
    --speaker-attribution                  \
    --mask-personal-names                  \
    --save-name-masking-logs               \
    --fix-spurious-repetitions             \
    --review-flag-zero-duration            \
    --review-repeated-passage-words 8      \
    --review-repeated-passage-window 60    \
    --output-name "$NAME"                  \
    "${SOURCE_ARGS[@]}"

# The two checks below run whatever the other's outcome, so one failure does
# not hide the other's report, but each status is kept and the job fails if
# either did. Provenance verification is what this case study exists to
# demonstrate, so a failed verify must not end in a success banner.
echo ""
echo "── Reference-free structural evaluation ─────────────────────────────"
EVAL_RC=0
python -m evaluation.benchmark_podcast                                  \
    --transcript "output/transcripts/${NAME}_transcript.json"           \
    --manifest   "$MANIFEST"                                            \
    --output-dir "$REPORT_DIR" || EVAL_RC=$?

echo ""
echo "── Provenance verification ──────────────────────────────────────────"
VERIFY_RC=0
python -m provenance verify "output/transcripts/${NAME}_manifest.json" || VERIFY_RC=$?

echo ""
echo "Structural evaluation exit status: $EVAL_RC"
echo "Provenance verification exit status: $VERIFY_RC"
ls -la "output/transcripts/${NAME}"* 2>/dev/null || true
if [[ $EVAL_RC -ne 0 || $VERIFY_RC -ne 0 ]]; then
    echo "❌ Case study finished with a failed check at $(date)" >&2
    exit 5
fi
echo "✅ Case study complete at $(date)"
echo "   Structural evaluation: $REPORT_DIR"
echo "   To commit it: cp \"$REPORT_DIR\"/podcast_eval_* output/case_study/"
echo "   and: cp output/transcripts/${NAME}_review.json output/transcripts/${NAME}_manifest.json output/case_study/"
