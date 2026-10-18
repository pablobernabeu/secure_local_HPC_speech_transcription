# Worked case study: one end-to-end run

Evidence from the complete deployed pipeline over a real recording,
produced by `hpc/submit_case_study.sh`. Every figure below comes from ARC
job 9124852, run on 2026-10-18 at commit fc652ab, unless the sentence
names another run. Two files here come from the August run, job 8441879:
`ep05_raw_text.txt`, its transcript text, and `ner_false_positive_test.md`,
a measurement of the NER masking stage made on that text. The last two
sections trace the earlier runs and list the files.

## The recording and the run

Episode 5 of *Codex Mentis*, "Beyond the cloud: Reclaiming data sovereignty
in speech transcription": 31,357,663 bytes, SHA-256
`a1f082338f01ccd36237b3bf5c87418b15f1b83e628049bb20c96f8d9a6a2448`, and
32 minutes 18 seconds by the podcast feed, as `data/codex_mentis/manifest.json`
records. The corpus is the author's own NotebookLM podcast, so it is
redistribution-clean, and it is a two-voice dialogue, which gives
diarisation a speaker count to be scored against without a reference
transcript. The episode is about this workflow's own subject.

Job 9124852 ran from 00:09 to 00:27 BST on an NVIDIA L40S (node htc-g075,
account `educ-lift`), from a clean clone at fc652ab, with Python 3.12.12,
torch 2.5.1+cu121, transformers 4.57.1 and pyannote.audio 3.4.0. It used
Whisper Large v3 (Hub revision 06f233fe) and pyannote
speaker-diarization-3.1 (revision 84fd2591), with the language stated as
English and timestamps, speaker attribution, name masking and repetition
repair all enabled. It also ran the review's two optional checks, for cues
of zero length and for repeated passages of at least eight words within
60 s (`--review-flag-zero-duration --review-repeated-passage-words 8
--review-repeated-passage-window 60`). It transcribed a 16 kHz mono WAV
decoded from the recording by an earlier run and reused because the stamp
beside it named the recording's SHA-256. By its own SHA-256 it is the WAV
the August run transcribed. The run was made to show two changes of
17 October 2026: the masker's handling of an abbreviated title (NEW-09)
and the optional review checks (NEW-12). It ran on an L40S because the
RTX A6000 nodes that ran job 8983112 are reserved for another group until
October 2027.

Test job 9124851 ran the whole test suite from the same clone first:
2,355 passed, 1 skipped, 1 expected failure and 1 failure. The failure was
the test that runs the masker over `ep05_raw_text.txt` and compares its
count with the committed summary, which then held job 8983112's three
redactions. It found four, the fourth being the `[TITLE]` this run was
made to show, and it passes against this run's summary. The job's
environment record stays beside its result on ARC, and
`hpc/runs/case_study.env` records the invocation.

## What the run produced

`transcription.py` wrote eleven files. Ten are in `output/transcripts/`:
the masked transcript as text and as a Word document, each with and
without speaker labels; the raw timestamped JSON and WebVTT captions and
their redacted parallels; the review file; and the run manifest. The
eleventh is the name-masking log, written to `name_masking_logs/` under
the working directory, which holds each masked name beside its
replacement. The manifest covers nine of the eleven, as the paragraph on
provenance below explains. The job itself wrote the structural evaluation
and its environment record into its report directory.

## Results

### Preflight and diarisation

The job opens with the environment check,
`python -m preflight --gpu-required --diarisation-required`. All ten of
its checks passed on the compute node, with no failure and no warning:
python, numpy, audio, torch, transformers, diarisation, isolation,
librosa, word documents and evaluation. The torch check names the GPU it
found, "NVIDIA L40S (44 GB)", on CUDA 12.1. The transformers check notes
that the pipeline's own language report is empty on 4.57.1, which does not
affect the workflow. At this code a pass of the diarisation check means
that the pipeline's cached configuration parses and names its pipeline,
and that every cached file of the speaker-diarization-3.1 repository still
hashes to its name, which is how the check catches the damage that stopped
job 8918023. The check does not hash the weights of the segmentation and
embedding models that the pipeline also loads. Because both flags are
demanded, the job would have stopped within seconds, with remedies, had
the GPU or speaker attribution been missing.

Diarisation found two speakers, in 243 segments, against the two voices
of the dialogue, so the speaker count error is zero. Each cue of the
transcript takes the speaker whose diarised speech overlaps it most. Read
that way, the cues fall into 170 turns, and the cues assigned to
`SPEAKER_00` last 674.4 s in all and those assigned to `SPEAKER_01`
1,207.8 s, consistent with a dialogue in which one voice leads. This is
the reference-free check the corpus was chosen for.

### Timestamps and their repair

The timestamped JSON holds 403 cues and 5,477 words, every word timed.
Two measures say how much of the recording the transcript accounts for.
`speech_s`, 1,841.42 s, is the union of the words' own intervals, so the
pauses between words do not count, and `coverage_ratio`, 0.9502, is that
over the length of the recording. `segment_span_s`, 1,882.12 s, is the
union of the cue spans, which also take in the pauses of up to a second
that the segmenter allows inside a cue, and `segment_coverage_ratio`,
0.9712, is that over the same length. The last cue ends at 1,936.34 s
(`span_end_s`), 1.66 s before the recording does (`end_drift_s`). The gap
from one cue to the next has a median of 0.0 s and a maximum of 2.2 s. No
word starts before the one before it or ends before it starts
(`monotonicity_violations` 0), and no cue overlaps the next (`n_overlaps`
0). The first run of the job, 8400094, measured four monotonicity
violations and five overlapping cues, and jobs 8441879, 8983112 and this
run measured none, because the pipeline now repairs the timeline before
writing it.

The outputs give two lengths for the recording. The structural evaluation
takes its length from `data/codex_mentis/manifest.json`, which records the
podcast feed's `itunes:duration` in whole seconds: 1,938 s. It finds the
episode by its number (`duration_source` "episode"), since the file
transcribed is the `_16k.wav` made from the manifest's `.m4a`. The review
measures the decoded WAV itself, with `librosa.get_duration`: 1,938.87 s.
The coverage ratios and the end drift are against the first, the
truncation check below against the second.

The timeline repair records what it took in the JSON as
`timeline_repairs`. For this run that was `word_retimed` 63,
`word_order_enforced` 0, `word_end_clamped` 0, `segment_overlap_clamped` 4
and `segment_merged` 3. The repair trusts the longest run of word start
times that never goes backwards and leaves those words alone.
`word_retimed` counts the words outside that run, each moved into the
interval its trusted neighbours define: it starts where the previous
trusted word starts and ends no later than the next one starts.
`word_end_clamped` counts words that ended before they started, whose end
was raised to their start. Cues are then derived again from their words.
`segment_overlap_clamped` counts cues that began before the previous cue
ended and were moved to start at its end, carrying their words with them.
`segment_merged` counts cues that lay wholly inside the previous one and
were merged into it, text and words. The August code collapsed such cues
to zero length instead. `word_order_enforced` counts words a final
running-maximum check had to move, and zero says the passes before it
left nothing to do. A change under a microsecond is made but not counted.

### Review flags and truncation

The review flagged 13 of the 403 cues, 3.23 per cent. Four have a high
speech rate, eleven belong to a repeated passage and three have no
duration, and five carry two of these flags. The speech-rate check counts
a cue's words as runs of letters, so "It's" counts as two and a numeral not
at all, and flags a cue faster than seven words a second. The two optional
checks are recorded in the review's `optional_checks` and in the run
manifest's `review_settings`. The zero-duration check flags a cue whose end
equals its start. The repeated-passage check slides a run of eight words,
ignoring case and punctuation, along the text, across cue boundaries, and
flags every cue that holds part of a run met again, without overlap,
within 60 s; each such cue names a partner in `repeated_passage_with`.
Without these two checks the review would have flagged the four cues of
high speech rate that job 8983112 flagged.

The first flag (17.98 to 18.66 s, six words, 8.82 a second) is "It's
good to be here.", the second voice's reply to the welcome. Its text is
right for that point in the conversation, so the flag points at timing:
either the reply was quick or Whisper timed it short.

The next eight flags, on cues 46 to 53, mark a fabrication. At 189.38 s
the speaker says "It's so", and the model adds "Thanks for watching!",
the sign-off of online videos and a known Whisper hallucination, squeezed
into the last 0.02 s of the cue (189.38 to 189.98 s, six words, 10.0 a
second), which is flagged for its rate as well. Whisper then repeats the
25 timed words spoken from 179.86 to 189.38 s ("data. Can we just dwell
on that for a second? Because that number, 680,000 hours of multilingual
audio data, that's just an astonishing number.") and "It's so" once more,
before the sentence goes on: "important to understand why that makes the
model so robust." The repeated words are all timed at 189.98 s with no
duration, in three cues of zero length and at the start of the next. The
three cues of zero length carry the zero-duration flag, and the
repeated-passage check links the copy, cues 50 to 53, to the speech it
repeats, cues 46 to 49. Job 8983112 wrote the same cues with the same
times, and its review, which had neither check, flagged only the cue of
"Thanks for watching!".

The flags on cues 84 to 86 mark a passage written twice. Cue 84 runs from
315.14 to 320.04 s and holds 44 words in 4.90 s, 8.98 a second, so it is
flagged for its rate. After "standard methodology often requires you",
the cue runs on with 31 more words, from "to do these in-depth
interviews" to "has to be manual.", all timed between 319.80 and
320.00 s. The same passage is then spoken in full from 320.04 s, in cues
85 and 86, where its last sentence goes on "has to be manually chopped
into maybe four or five separate segments". The repeated-passage check
links the crammed copy in cue 84 to both. The segmenter starts a new cue
after each full stop, and the three cues that followed the crammed copy's
first full stop lay wholly inside the cue it began in, so the repair
merged them into it. These are all three of the run's `segment_merged`
repairs, and the reason one cue holds four sentence ends. The August run,
whose code collapsed such cues to zero length instead, had more cues
(408) and no flag here.

The last flag (1,303.48 to 1,303.50 s, one word, 50.0 a second) is a
doubled word: Whisper's text has `false positives. positives.` at this
point. The first copy ends the sentence at 1,303.48 s. The segmenter
starts a new cue after a full stop, so the second copy opens a cue of its
own, and since it ends in a full stop too, the next word, "It", opens
another at 1,303.50 s. The copy ends 0.02 s after the first one, one step
of the 20 ms grid on which every word time in the transcript falls. The
repair merges a cue into its predecessor only when the cue ends inside it,
and otherwise starts it no earlier than the predecessor's end, so the copy
stays as a cue of 0.02 s. The repair keeps no record of a word's time
before it, so whether this cue was moved forward to 1,303.48 s or began
there cannot be read from the output. One word in 0.02 s trips the rate
flag, and the flag points at a real defect: a word said once and written
twice. A single repeated word is too short for the repeated-passage check.
The cue had the same 0.02 s span, and the same flag, in the August run,
whose README described it as a cue of zero length.

The review's truncation check compares the end of the last cue,
1,936.34 s, with the length of the recording measured from the WAV,
1,938.87 s. The shortfall is 2.53 s, 0.13 per cent of the recording, far
inside the tenth at which the check would report a truncated transcript,
so the transcript is not cut short.

### Masking, repetition and provenance

Run over the 5,382 whitespace-separated tokens of the raw text, the name
masker makes four redactions, a rate of 0.074 per cent, the same four it
made in the run's own transcript, as its masking log records. Three are
capitalised words in the curated name list, two listed as first names
and one as a surname. Two of those are the first name and surname of the
workflow's author, in the closing credits. The third is "Jordan", in a
speaker's example of a false positive: masking "Jordan" when the talk is
of the country, not a person. The dictionary masks it there, since it
lists Jordan as a first name and does not read context. The fourth
redaction is the "Dr." before the author's name, replaced with `[TITLE]`
now that the masker no longer splits its text after an abbreviated title
(NEW-09). Job 8983112, whose code split the text there, left that "Dr."
in place. No other word was masked. This is the precision measurement the injection
benchmark cannot supply, because its carrier sentences contain no
confusable tokens by construction. On this transcript it finds one
masked word that names no one. `ner_false_positive_test.md` counted all
three names as genuine, Jordan included, until a hand correction on
2026-10-04, and now counts the same two. The optional NER stage took no
part in the run. It is reached only through the Python API and the
masking benchmark, not through an option of `transcription.py`, the job
passes no such option, and gliner, which the stage needs, is not
installed in the job's environment (the manifest records its version as
null). `ner_false_positive_test.md` measures that stage on the August
run's text.

The longest run of one repeated token in the raw text is two
(`max_immediate_repeat`), so no loop of a repeated word survived into the
output. The doubled "positives." of the last flag is one such pair. The
measure looks only at a word repeated in place, so it cannot see the
passages written twice that the repeated-passage check flags. Those are
in every text output of the run, as Whisper wrote them, since the repair
moves times and never adds or drops a word, and the review marks them
for a reader to check.

The job checked the run manifest with `python -m provenance verify`, and
it verified: its digest of its own content matched, and the nine
artefacts it lists matched their recorded SHA-256, with none missing,
altered or unlisted. The run was unsigned, which is the default, as
signing is opt-in. The nine are every file the run wrote under
`output/transcripts/` except the manifest, which cannot list itself and
carries the digest of its own content instead (`manifest_sha256`). The
manifest does not cover the name-masking log, which holds the original
names and lies outside `output/transcripts/`, so a change to the log
would go unnoticed (CORE-05), as `provenance.py` says. Under `input_audio`
it records the file that was transcribed, the 16 kHz WAV (62,043,798
bytes, SHA-256 `ee52c7ba...`). Under `source_audio` it records the
published recording (31,357,663 bytes, SHA-256 `a1f08233...`, the digest
in `data/codex_mentis/manifest.json`) with the ffmpeg command that made
the WAV from it, so the chain runs from the episode anyone can download to
the transcripts (CORE-04). Its software block names the commit, fc652ab,
with a clean tree, the version stamp `1.0.0+gfc652ab87144`, since the
run predates the 2.0.0 row in `versions.csv`, and the versions of Python,
transformers, torch and pyannote.audio. `review_settings` records the two
optional checks.

## Earlier runs

Six runs of the job are on record. Job 8400094 (2026-08-02,
`educ-intract`) measured the pipeline as first shipped: four monotonicity
violations and five overlapping cues. Job 8441879 (2026-08-05,
`educ-lift`, a Tesla P100 on htc-g032, commit 25c2582) ran after the
first timeline repair and the preflight gate, and measured none of
either. Its text remains as `ep05_raw_text.txt`. Job 8918023 (2026-09-27)
could not load the diarisation pipeline, which failed with
`KeyError: 'name'` because test jobs had written a stub over its cached
configuration on ARC (incident NEW-INC-01), so it transcribed without
speakers and failed. Job 8978758 (2026-10-04, commit f2578b8, an RTX
A6000 on htc-g050) transcribed and diarised the episode, but its
structural evaluation was pointed at a corpus manifest that does not
exist on ARC and refused to go on without it (NEW-06), so the job failed.
Commits ca75ced and c4c7b38 made the job read the repository's own
manifest when there is no other, and check it before transcribing. Job
8983112 (2026-10-04, commit c4c7b38, an RTX A6000 on htc-g052,
`educ-intract`) then completed, and its transcript JSON matched 8978758's
in every field but the time it was written. Its summary, review and
manifest were committed here until this run replaced them.

Job 9124852 is the run this README describes. Its text differs from job
8983112's in eleven places among some 5,480 words. "span" and "hours"
lose their full stops in the passage spoken from 320.04 s, which this run
therefore writes as two cues where job 8983112 wrote four, and this is
why it has 403 cues to 405. "you know," is added after "factors that",
"you can't see the exact model versions" becomes "you can model
versions", "explained" becomes "explain" and "Optimized" "Optimize", a
second "coverage" is gone, "Tier 2," becomes "tier two,", "databases,"
loses its comma, and "First Names" and "Surnames" are no longer
capitalised. Between c4c7b38 and fc652ab the code changed the masker, the
review and comments, not the decoding, so these differences come with
the change of card. The talk times move with the cues, by 7 s at most.
The masking differs by the `[TITLE]` alone, and the review by the two
optional checks.

## Files here

- `podcast_eval_summary.json` and `podcast_eval_report.csv`: job
  9124852's structural evaluation (`python -m evaluation.benchmark_podcast`),
  the first nested and the second one flat CSV row without the talk
  times. Both are copies from the job's report directory on ARC, except
  that git stores the CSV with LF line endings where the job wrote CRLF.
- `codex_mentis_ep05_review.json`: job 9124852's review file, with the
  flagged cues, the summary, the optional checks and the truncation check.
- `codex_mentis_ep05_manifest.json`: job 9124852's run manifest. It and
  the review are byte-for-byte copies of the job's own files in
  `output/transcripts/`, so the review here has the SHA-256 that the
  manifest records for it.
- `ep05_raw_text.txt`: the transcript text of the August run, job
  8441879, extracted from its timestamped JSON before masking. It is the
  text `ner_false_positive_test.md` measured, and tests read it. Job
  9124852's text differs from it in nine places, which that note lists.
- `ner_false_positive_test.md`: what the optional NER masking stage costs
  in false positives on real speech, measured on `ep05_raw_text.txt`.
- `ner_label_phrasings.json`: the words the NER stage marks in that text
  under the shipped label set and each of three narrower phrasings, split
  by the capitalisation gate (`python tools/ner_label_phrasings.py
  --output output/case_study/ner_label_phrasings.json`, 17 October 2026).

No transcript of job 9124852 is committed. Its two JSON transcripts are
888 KB each, the job can be run again, and the manifest records the
digest of every file it lists.
