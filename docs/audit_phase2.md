# Phase 2 audit: residual risks in the local diarisation pipeline

This document records the five residual risks identified after the
Phase 2 refactor of `transcription.py` and `evaluation/wer.py`, in May
2026. Each risk is described in terms of the code that created it, the
failure mode it produces if left unaddressed, and the mitigation that was
applied or recommended. It is a record of the Phase 2 state, not a
description of the current code: where the code has since changed, a
status note dated September 2026 at the head of the risk says how. Code
is referred to by function name, because line numbers in
`transcription.py` have moved many times since the audit.

## Risk A: waveform parity between diarisation and ASR

Status, September 2026: both stages now decode through
`audio_io.load_audio`. The speech recognition stage in
`transcribe_audio_only` calls it to get a 16 kHz mono array, and
`perform_speaker_diarization` calls it and hands pyannote the decoded
waveform, not the file path. The risk described below therefore remains
only on the fallback paths: the recogniser uses `librosa.load` when
`audio_io` cannot be imported, and diarisation passes the file path to
pyannote when the in-memory decode fails, which it reports in the log.

At the time of the audit, the automatic speech recognition stage loaded
audio through `librosa.load(audio_path, sr=16000)`, which yields a
float32 mono array resampled to 16 kHz by `librosa`'s default soxr-based
pipeline. The diarisation stage in `perform_speaker_diarization` passed
the original file path directly to the pyannote pipeline, which caused
`pyannote.audio` to decode the file through `torchaudio` (or
`soundfile`) with its own resampling kernel and mono-mixing convention.
The two decoded waveforms are nominally identical but are produced by
different code paths. In practice the timing discrepancy is
sub-millisecond for well-formed WAV input, but for compressed formats
(MP3, M4A, AAC) the two decoders can disagree on sample-accurate frame
boundaries because of decoder-specific priming samples. The downstream
consequence is that a diarisation segment boundary at, say, 12.413 s and
an ASR word boundary at 12.412 s may disagree on the speaker attribution
of a single word at the edge of a turn. The carry-forward rule in
`_assign_speaker_to_interval` absorbs most of this error, but it is not
eliminated. The mitigation recommended then was to decode the input once
and pass the same waveform to both stages, which is what the shared
`audio_io` decoding now does.

## Risk B: capture of the unmasked base transcript

The privacy contract requires that downstream consumers of the raw
machine-readable artefacts (`_transcript.json` and `_transcript.vtt`)
see the same text that the model emitted, so that evaluation against a
hand-checked reference can be performed on the model's output rather
than on a masked variant. In `process_audio_file`, the call to
`write_timestamped_outputs` comes before any mutation of the text by
speaker attribution or name masking, so the raw JSON and VTT contain the
raw model text together with its raw timestamps; the masker is passed to
it separately, and applied only to the redacted set described under
Risk E. `base_transcript_text = main_text` is then assigned immediately
after `main_text` is read from the transcription result, again before
any mutation. The test `tests/test_process_audio_smoke.py` exercises the
path with a synthetic transcription result to confirm that the JSON
contains the unmasked text and the expected `pipeline` provenance block.
The risk here is regression rather than current incorrectness: any
refactor that moved the `write_timestamped_outputs` call after the
masking step would silently propagate redacted text into the raw
timestamped artefacts. The smoke test is the principal guard against
that regression.

## Risk C: name-masking regex versus speaker tags

The masking function built by `create_enhanced_name_masker` iterates the
transcript word by word and decides whether each word should be
replaced by `[NAME]`, `[SURNAME]` or `[TITLE]`. The decision is gated by
a capitalisation test and by a dictionary lookup. At the time of the
audit the test was `word[0].isupper()`; it is now
`_token_is_capitalised`, which judges a token by its first letter so
that a name opening a quotation or a parenthesis is still recognised. A
speaker tag of the form `[SPEAKER_00]` is never in the name dictionary,
so the masking function does not select it for replacement. The tag is
also emitted as a single whitespace-delimited token by
`_format_attributed_text`, so it is not split into pieces that might
each pass the checks. The WER normaliser strips speaker tags through
`_SPEAKER_RE` in `evaluation/wer.py`, so the evaluation pipeline also
treats them as non-content. The `tests/test_privacy_masking_interaction.py`
module exercises three distinct round-trips: it confirms that the
speaker-strip regex does not match the bare word "speakers", that the
formatted output strips cleanly to the original text, and that a
simulated `[REDACTED]` substitution preserves `[SPEAKER_xx]` brackets.
The residual risk is that a future change to the formatter that emits
tags without their surrounding brackets, or that splits them across
whitespace, would break this invariant. The privacy-interaction test is
the guard.

## Risk D: small-N property of the curated names CSV

Status, September 2026: the per-language counts below are taken from
`data/curated_names.csv` as it now stands, and replace the Phase 2
statement that every language had fewer than two hundred entries, which
was never true of English. The optional NER stage mentioned as future
work now exists (`ner_masking.py`), though only through the Python API
and the masking benchmark.

The masking dictionary is built by `create_multilingual_curated_names`
from `data/curated_names.csv`. The CSV is small by design. It holds
1,793 names: 967 English, 180 French, 176 Spanish, 143 Chinese, 141
German, 141 Hindi, 21 Italian, 13 Arabic and 11 Polynesian. The
implication is that the masking is a property of the curated list rather
than a guarantee about the input. A name that does not appear in the CSV
will pass through unmasked, and a common noun that happens to match a
curated name will be masked in error. Neither failure mode is intrinsic
to the algorithm; both are properties of the small-N list. The audit
position taken in Phase 2 is that this is the correct trade-off for a
tool intended to assist manual review rather than to provide
cryptographic privacy guarantees: the masking is an aid to the analyst's
eye, not a substitute for the analyst. With `--save-name-masking-logs`,
`save_replacement_log` writes a CSV per recording to
`name_masking_logs/`, listing every masked word with its sentence and
the rule that masked it, which lets the analyst verify, post hoc, which
words were masked and which were not. Without that flag no log is
written. The mitigation, where stronger guarantees are required, is to
extend the CSV per project or to add a named-entity model, which is what
the NER stage does.

## Risk E: masking applied to text outputs but not to JSON or VTT

Status, September 2026: the stronger mitigation proposed below has
shipped, in a different form from the one proposed. Whenever masking is
on, `write_timestamped_outputs` also writes
`<name>_transcript_redacted.json` and `<name>_transcript_redacted.vtt`,
with the same timings and the names masked, and each file declares its
status in a `redacted` field. The unredacted pair is still written by
default; `--redacted-timestamps-only` suppresses it. The
`*_redacted_transcript.*` names and the `--keep-raw-artefacts` flag
proposed below were never implemented. The review file `_review.json`
applies the same masker to the segment text it quotes. The raw
transcripts, masking logs and other outputs are now also ignored by git,
so that an accidental `git add` of the output tree cannot commit them.

The JSON and VTT artefacts produced by `write_timestamped_outputs` are
written from the raw transcription result before name masking is
applied, by the same chain of calls described under Risk B. This is
deliberate. The masked text is suitable for distribution and for
inclusion in publications; the unmasked timestamped artefacts are
intended as auditable records that remain on the researcher's local
filesystem. The risk that follows is procedural rather than technical:
a user who copies the entire `output/` directory tree without first
filtering it will export the unmasked artefacts alongside the masked
text. At the time of the audit, the mitigation in place was
documentation: the privacy contract section of
`PYANNOTE_SETUP_GUIDE.md` explained that the timestamped artefacts
contain raw text, and the `pipeline` provenance block in the JSON made
the unredacted status of the file inspectable without parsing the body.
The stronger mitigation proposed then was to emit a parallel
`*_redacted_transcript.json` and `*_redacted_transcript.vtt` whenever
masking is active, and to gate the unredacted variants behind an
explicit `--keep-raw-artefacts` flag. That was left for Phase 3 because
it required re-running the masking over the chunk-level data structure
rather than over the flat text.
