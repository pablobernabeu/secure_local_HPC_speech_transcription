# Advanced usage

## Speaker attribution

Speaker attribution labels who spoke when, using the pyannote pipeline
`pyannote/speaker-diarization-3.1` from HuggingFace. *Diarisation* is the
technical term for the step, and this documentation uses the two names
for the same thing ([glossary.md](glossary.md)). It needs a HuggingFace
token and a one-off model download, which the interactive wizard sets up
in ten to fifteen minutes. [PYANNOTE_SETUP_GUIDE.md](../PYANNOTE_SETUP_GUIDE.md)
covers the setup step by step, its common problems and the HPC specifics.

```bash
python setup/setup_pyannote.py  # Interactive setup wizard (10-15 minutes)
```

With speaker attribution, a run writes two sets of transcripts. The base
`filename_transcript.txt` and `.docx` carry no speaker labels and are the
easier to read. `filename_transcript_with_speakers.txt` and `.docx` put a
label such as `[SPEAKER_00]` before each speaker's turn, for analysing
who said what. The run also writes the timestamped outputs, because the
labels are placed from word timings.

```bash
# For single files with Python
python transcription.py "interview.wav" --speaker-attribution

# For batch processing
hpc/submit_transcription.sh --speaker-attribution

# Combined with other options
hpc/submit_transcription.sh --mask-personal-names --speaker-attribution --language english
```

### Constraining the number of speakers

Measure the effect of these options on your own recordings before you
trust them:

```bash
# A one-to-one interview: interviewer and participant
python transcription.py "interview.wav" --speaker-attribution --num-speakers 2

# A focus group whose exact attendance you are unsure of
python transcription.py "focus_group.wav" --speaker-attribution \
    --min-speakers 4 --max-speakers 7
```

`--num-speakers` fixes the count exactly and takes precedence over
`--min-speakers`/`--max-speakers`, which express a range when only the
range is known. All three apply only with `--speaker-attribution`.

Left alone, the model reliably finds more speakers than a recording
contains, so telling it the true number looks as though it can only
help. On the AMI benchmark, it did harm. Supplying the true count raised
macro diarisation error from 16.6% to 25.0%, worsening ten of the
sixteen meetings, and in the worst case took a meeting from 7.2% to
45.7%. All of the increase came from speaker confusion. Clustering
forced to stop at exactly *n* must merge until it gets there, and merging
two distinct speakers costs far more than leaving a few small spurious
clusters, which contribute comparatively little error.

Those meetings had four speakers each, so the finding does not
automatically transfer to a two-person interview, where a harmful merge
has much less scope. The option exists because the count is often known
in advance, and setting it is not advisable by default. If speaker
labels matter to your analysis, run a recording both ways and compare
before adopting either.

### Accuracy, and when to use it

Accuracy is best on clear recordings of two to four distinct voices with
little background noise, and falls with more speakers, similar voices
(of the same gender, age or accent), overlapping speech and a single
microphone. Speaker attribution therefore suits clearly recorded
interviews, focus groups, panels and meetings, and adds nothing to a
recording of one speaker. On noisy audio, or with many similar voices,
expect the labels to need checking.

The labels are arbitrary. The same voice should keep the same label
through a recording, but a label does not identify a person, and
diarisation does not recognise voices across recordings. For a short
interview, the base transcript (`filename_transcript.txt`) reads:

```
Hello and welcome to today's interview. Thank you for joining us.

Thank you for having me. I'm excited to be here.

Let's start with your background. Can you tell us about your research?

Certainly. I've been working on computational linguistics for the past five years...
```

and the speaker-attributed transcript
(`filename_transcript_with_speakers.txt`):

```
[SPEAKER_00] Hello and welcome to today's interview. Thank you for joining us.

[SPEAKER_01] Thank you for having me. I'm excited to be here.

[SPEAKER_00] Let's start with your background. Can you tell us about your research?

[SPEAKER_01] Certainly. I've been working on computational linguistics for the past five years...
```

### Air-gapped and offline operation

The diarisation model can be loaded entirely from local storage, so that
no network call is made at run time. `perform_speaker_diarization` tries,
in order, a YAML configuration file given with `--diarization-config
PATH`, a local pipeline given with `--diarization-model-path PATH` (its
`config.yaml`, or a directory holding one), and the HuggingFace loader
for the configured `model_id`. The HuggingFace loader is used only when
neither local option was given. If you name a local pipeline and it
cannot be loaded, the Hub model is not tried in its place: the run writes
the transcript without speaker labels and reports itself incomplete.

Setting the environment variable `HF_HUB_OFFLINE=1` or
`TRANSFORMERS_OFFLINE=1` makes the HuggingFace loader read the cache
only, by requesting `local_files_only=True`. When the model is absent
from the cache, the error message names the expected cache directory and
the options that would resolve the situation.

The JSON sidecar records the route taken under `diarization_model_source`
(one of `'local_config'`, `'local_path'`, `'hf_loader'`,
`'hf_loader_offline'` or `'unavailable'`), together with
`diarization_model_id`, `diarization_model_path`,
`diarization_offline_mode` and, when loading failed, `diarization_error`.
The [glossary](glossary.md) defines the labels. The sidecar also records
the Hub snapshots the load used: `diarization_model_revision` for the
pipeline, and `diarization_sub_model_revisions` for the segmentation and
embedding models its configuration names. They are read back from the
cache without pinning the load, so an offline machine whose cache holds
another snapshot still diarises and says which snapshot it used.

## Redacting names from the audio

Masking removes names from the text the workflow writes, but the
recording still says them. For a dataset that will be shared or
archived, that gap matters most, because the audio carries a voice as
well as a name.

`audio_redaction.py` closes it using two things the workflow already
produces: the word-level timestamps written by `--timestamps`, and the
same name-masking decision applied to the transcript. Every word the
masker would redact has its time span silenced, or replaced with a tone:

```bash
# Transcribe with timestamps and masking, then redact the audio
python transcription.py "interview.wav" --timestamps --mask-personal-names
python -m audio_redaction \
    --audio interview.wav \
    --transcript output/transcripts/interview_transcript_redacted.json \
    --out interview_redacted.wav \
    --mode bleep
```

Point `--transcript` at the `_transcript_redacted.json` the run wrote:
its placeholders are the run's own masking decisions, so the audio is
redacted exactly where the text was. Given the raw `_transcript.json`,
the command uses the redacted file beside it when there is one, and only
otherwise rebuilds a masker, which then needs the same masking options
the run used (`python -m audio_redaction --help` lists them).

Two checks stop the command from writing a file that only looks
redacted. A run that finds no name to redact refuses to write its output
unless `--allow-empty` is given, because a `_redacted.wav` identical to
the input would be misleading. A name can be silenced only where a word
timestamp places it, so a run that finds names it cannot place refuses as
well. With `--allow-untimed-names` it writes the output, and those names
stay audible. In a raw transcript, such a name is a name word without a
start or an end time. In a redacted one, it is a `[NAME]` or `[SURNAME]`
in a segment's text that no timed word carries. `[TITLE]` is not
counted, because the redacted word list keeps the honorific itself as a
word. The count is printed on stderr either way, and the report of a
finished run gives it again.

Each refusal exits with status 3, as does a transcript whose words carry
no readable text. A run exits with status 2 when the transcript, or the
redacted file beside it, cannot be read or is not UTF-8 JSON holding an
object whose segments and words are lists of objects. A masker that
cannot be loaded or fails on a word, and audio that cannot be read, give
status 2 as well. Nothing is written on a non-zero status.

`--mode silence` (the default) writes silence in place of a tone. `--pad`
(default 0.05 s) widens each span slightly, so a timestamp that clips the
start or end of a word still covers the whole of it. Redaction is a
separate command, so a recording can be redacted from a transcript
produced earlier without transcribing it again.

The redaction is only as good as the masking that drives it, so a name
the dictionary never knew is spoken in the output as well as written in
the transcript. The optional named-entity stage described in the README
exists for that case. It is also only as good as the timestamps, whose
accuracy the manuscript's timestamp benchmark measures. The pairing of
the two has not itself been scored, so listen to a sample of the output
before releasing a corpus.

## Repetition fixing

Whisper models sometimes get stuck in a loop, especially on difficult
audio or long recordings, and write the same sentence, phrase or word
over and over. `--fix-spurious-repetitions` cuts such loops back:

```bash
# For single files with Python
python transcription.py "audio_input/interview.wav" --fix-spurious-repetitions

# For batch processing
hpc/submit_transcription.sh --fix-spurious-repetitions

# Combined with other options
hpc/submit_transcription.sh --mask-personal-names --fix-spurious-repetitions --language english
```

The repair, `detect_and_fix_repetitions` in `transcription.py`, acts
only on long runs, so the ordinary repetition of speech ("the the
meeting", "and then, and then") passes through unchanged. A sentence
repeated more than five times in a row is kept once, followed by `[...]`
when it ran to more than ten copies. A phrase of two to six words
repeated more than ten times in a row is kept once and followed by
`[...]`, and a word repeated more than five times in a row is kept twice.
A counting sequence ("one two three ... nine") that recurs three or more
times becomes `[...]`, and a run of six or more identical symbols is cut
to three. These are the function's defaults, and the source of their
values is not recorded. The option is off by default. It is most useful
on noisy or long recordings, or when a first transcript shows loops.

## Checking repeated passages

The review that a run with `--timestamps` or `--speaker-attribution`
writes, `<name>_review.json`, uses the established checks for repeated
cues, short decoding loops and implausible speech rates. Two further
checks are off by default. `transcription.py` runs them with
`--review-flag-zero-duration` and `--review-repeated-passage-words` (see
the README's option table), and `python -m confidence` runs them on a
timestamped JSON already written:

```bash
python -m confidence output/transcripts/interview_transcript.json \
    --flag-zero-duration --repeated-passage-words 8 \
    --repeated-passage-window 60 --json review_extended.json
```

This flags non-empty cues with equal start and end times, and both copies
of a matching run of eight or more tokens, even when the run crosses cue
boundaries. The window compares the start times of the cues containing
each copy's first token. Case and punctuation are ignored, but numbers
are kept, so a change in a reported quantity can tell two passages
apart. An apostrophe splits a word, so a contraction such as *don't*
counts as two tokens, and a shared clause of six or seven spoken words
with contractions can reach the eight-token setting. Missing, invalid or
decreasing times interrupt the passage search. The report records the
chosen settings and links a flagged cue to the indices of a matching
partner. The command writes a separate review and leaves the transcript
and its timings unedited. It exits with status 2 when the transcript
cannot be read or is not UTF-8 JSON holding an object whose `segments`
is a list of objects, and when a setting is rejected.

Eight tokens and sixty seconds are provisional settings motivated by the
unflagged passages in the case study, not thresholds fitted to annotated
speech. A speaker may repeat a long clause intentionally, and a copy
with altered wording or outside the window can be missed, so listen to
both passages before deciding what happened. Estimating precision and
recall will require recordings with independently annotated repetitions
and recognition errors. Both checks are off by default so that the
archived reviews and their reported counts remain reproducible, and the
desktop application does not offer them.

## Multilingual name masking

The masker draws on a curated multilingual dictionary,
`data/curated_names.csv`, of 1,793 names in nine languages: 967 English,
180 French, 176 Spanish, 143 Chinese, 141 German, 141 Hindi, 21 Italian,
13 Arabic and 11 Polynesian. It is far smaller than the optional Facebook
lists described below, and so masks fewer ordinary words by mistake.
Each entry is tagged as a first name or a surname and with its language,
written as a full lower-case name such as `english`. Chinese names are
romanised in Pinyin and Hindi names written in Latin script. The CSV is
UTF-8, so accented names such as "Clément" keep their accents, and the
names are sorted within each language. It can be extended by adding
rows, and [dictionary_provenance.md](dictionary_provenance.md) records
where it came from.

### Choosing the languages

By default, the masker uses all nine languages, which gives the widest
coverage and suits recordings whose speakers' backgrounds are varied or
unknown. `--languages-for-name-masking` restricts it to the languages
you name, which reduces false positives when you know the speakers'
linguistic backgrounds or the recording has a regional focus. Languages
are given as full names, in any letter case (`english`, `Spanish`). A
name the dictionary does not contain, or an ISO code such as `en`, stops
the run with an error listing the valid names, because silently loading
no names would mask nothing while the transcript header still said names
were masked.

```bash
# Use all languages (default behaviour)
python transcription.py interview.wav --mask-personal-names

# Use only English names
python transcription.py interview.wav --mask-personal-names --languages-for-name-masking english

# Use multiple specific languages
python transcription.py interview.wav --mask-personal-names --languages-for-name-masking english spanish

# Use Chinese and Hindi for Asian content
python transcription.py interview.wav --mask-personal-names --languages-for-name-masking chinese hindi

# HPC batch with language selection
hpc/submit_transcription.sh --mask-personal-names --languages-for-name-masking english french german
```

The masker itself produced the outputs below. The first two have the
common-word filter on, as it is for an English transcript. The third has
it off, as for a non-English transcript, although none of its names is on
the filter's list, so it would come out the same with the filter on.
With all languages, the default:

```
Input:  "Hello Maria Rodriguez, this is John Smith and Wei Chen speaking with Raj Patel and François Dubois."
Output: "Hello [NAME] [SURNAME], this is [NAME] [SURNAME] and [SURNAME] [SURNAME] speaking with [NAME] [SURNAME] and François [SURNAME]."
```

With English only:

```
Input:  "Hello Maria Rodriguez, this is John Smith and Wei Chen speaking with Raj Patel and François Dubois."
Output: "Hello Maria [SURNAME], this is [NAME] [SURNAME] and Wei Chen speaking with Raj [SURNAME] and François Dubois."
```

"Rodriguez" and "Patel" are in the English list as surnames, and
"Maria", "Raj" and "Dubois" are not. With Chinese and Spanish only:

```
Input:  "Li Wei and Zhang Yu were talking to Carlos Martinez and Ana Rodriguez."
Output: "[SURNAME] [SURNAME] and [SURNAME] [SURNAME] were talking to [NAME] [SURNAME] and [NAME] [SURNAME]."
```

Each Facebook flag, described below, replaces the curated first names or
surnames with its own list, so the language selection then applies only
to the half the curated dictionary still supplies. With both flags, it
matters only if the Facebook lists fail to load and the run falls back
to the curated dictionary.

```bash
# Facebook first names + selected languages for surnames
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --languages-for-name-masking english spanish

# Facebook surnames + selected languages for first names
python transcription.py interview.wav --mask-personal-names --use-facebook-surnames-for-masking --languages-for-name-masking chinese hindi

# Both Facebook databases + language selection (for curated backup)
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking --languages-for-name-masking english
```

### The common-word filter

Some names, such as "Will", "Grace", "Long" and "Hall", are also English
words. The masker only ever masks capitalised words, so the lower-case
word in "they will continue" is safe either way. The problem is the
capitalised word, at the start of a sentence, in a title or as part of a
place name. The common-word filter removes about 660 common English words
from the dictionary. Short names stay: the curated dictionary's "Li",
"Yu" and "Ed" were listed on purpose, and only the scraped Facebook lists
also lose every name shorter than three letters. With all languages
selected, the masker gives:

```
Input:            "Then Will said that Grace and Art would meet Pablo in Long Hall."
Filter off:       "Then [NAME] said that [NAME] and [NAME] would meet [NAME] in [NAME] [SURNAME]."
Filter on:        "Then Will said that Grace and [NAME] would meet [NAME] in Long Hall."
```

"Art" is masked either way, because it is not on the list of common
words. The list, in `filter_problematic_names` in `transcription.py`,
covers colours, months and days, common verbs and nouns and similar
words that double as names, for example will, may, can, is, was, long,
page, hall, west, north, south, june, august, parker, amber, grace, rose,
ruby, fox, bill, joy and hope. It also holds the two short tokens "an"
and "ai", which capitalised at a sentence start or as an acronym would
otherwise be masked as names. Other short names, such as "Li" and "Yu",
stay in the dictionary.

The filter's default follows the transcript language. It is on for
English (`--language english`), to prevent false positives, and off for
other languages, to keep legitimate names such as the Chinese "An" and
"Long". Without `--language`, the default follows the language detected
from the audio, exactly as if it had been stated. Detection is a guess,
and the terminal warns when one was made, so pass `--language` to be
certain. The same language also governs which post-processing stages run
(see [conditions_audit.md](conditions_audit.md#the-language-gate)).
`--exclude-common-english-words-from-name-masking` and its `--no-` form
set the filter either way, on the command line and through the HPC
wrapper alike:

```bash
# English transcript: filtering on automatically
python transcription.py interview.wav --mask-personal-names --language english
# "Then Will said ... in Long Hall." keeps Will, Long and Hall; "Pablo" -> [NAME]

# Chinese transcript: filtering off automatically
python transcription.py interview.wav --mask-personal-names --language chinese
# "An and Long arrived with Mei." -> "[NAME] and [NAME] arrived with [NAME]."
# (with the filter on, "An" and "Long" would be kept)

# English transcript with the filter switched off
python transcription.py interview.wav --mask-personal-names --language english \
    --no-exclude-common-english-words-from-name-masking
# "Then Will said ..." -> "Then [NAME] said ..."

# Non-English transcript with the filter switched on
python transcription.py interview.wav --mask-personal-names --language spanish \
    --exclude-common-english-words-from-name-masking

# HPC batch processing with automatic filtering
hpc/submit_transcription.sh --mask-personal-names --language english
```

Keep the filter on for English audio, and switch it on for any
recording in which words such as "will", "may" and "long" are being
masked. Keep it off where names that are also English words, such as
the Chinese "An" or "Long", are expected.

### Honorifics

An honorific before a masked name is masked with it, as `[TITLE]`, so
that the title does not survive beside the placeholder. The honorifics
are Mr, Mrs, Ms, Miss, Dr, Prof, Professor, Sir, Madam, Lord and Lady
(`TITLE_WORDS` in `transcription.py`), and one is masked only when the
next word is a capitalised dictionary name. A name the dictionary does
not hold leaves its title in place, even when the named-entity stage
masks the name itself. A possessive name takes its title with it, as
the last sentence here shows:

```
Input:  "Thanks to Dr. Smith and Miss Garcia. I miss Sarah. It was Dr. Smith's idea."
Output: "Thanks to [TITLE] [SURNAME] and [TITLE] [SURNAME]. I miss [NAME]. It was [TITLE] [SURNAME]'s idea."
```

The full stop after an abbreviated title (Mr, Mrs, Ms, Dr and Prof)
does not end the sentence, and it goes into the placeholder with the
title. Every honorific but two counts in any case, so "dr Smith" and
"DR Smith" lose the title too. The two are also ordinary words, so they
count only when spelt as the honorific is. "Miss" needs its capital,
since "I miss Sarah" holds the verb, and "Ms" must be spelt exactly so,
since "200 ms" is the unit and "MS" the disease. A lower-case "ms." or
an "MS." therefore ends its sentence like any other word. The masker's
`case_insensitive` parameter lifts the capitalisation requirement for
the name after an honorific, as it does for any name, so "dr smith"
becomes "[TITLE] [SURNAME]". It does not make a lower-case "miss" or
"ms" an honorific.

### Excluding specific names

Some names can be left unmasked while the rest are masked: public
figures such as "Einstein" or "Darwin" whose names give the transcript
essential context, or a participant who has agreed to be named. List
them on the command line, in a file with one name per line, or both.
Matching ignores case ("Einstein", "einstein" and "EINSTEIN" are the
same), and an excluded name is removed from the first names and the
surnames, from the curated dictionary and the Facebook lists alike.
Every other name is still masked.

```bash
# A comma-separated list
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-from-masking "Einstein,Darwin,Newton"

# A file with one name per line
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-file excluded_names.txt

# Both together
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-file celebrities.txt \
  --exclude-names-from-masking "ResearcherName"

# HPC batch processing
hpc/submit_transcription.sh --mask-personal-names \
  --exclude-names-from-masking "Einstein,Curie"
hpc/submit_transcription.sh --mask-personal-names \
  --exclude-names-file excluded_names.txt
```

Leave exclusions out when every participant needs the same protection,
when you are unsure which names may be kept, or for highly sensitive
material.

### The Facebook name lists

The optional `names-dataset` package, from Philippe Remy's
[name-dataset](https://github.com/philipperemy/name-dataset) project,
holds lists extracted from a Facebook data dump: over 730,000 first
names and 980,000 surnames. `--use-facebook-names-for-masking` replaces
the curated first names with its first names, and
`--use-facebook-surnames-for-masking` replaces the curated surnames with
its surnames. The curated dictionary supplies whichever of the two is
not replaced. Both are off by default, because lists that large contain
many ordinary capitalised words, and the masker then hides them.

```bash
# Default behaviour (recommended) - uses curated names only
python transcription.py interview.wav --mask-personal-names

# HPC batch with curated names (recommended)
hpc/submit_transcription.sh --mask-personal-names

# Enable Facebook FIRST NAMES only (surnames remain curated)
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking

# Enable Facebook SURNAMES only (first names remain curated)
python transcription.py interview.wav --mask-personal-names --use-facebook-surnames-for-masking

# Enable BOTH Facebook databases (wider coverage but more false positives)
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking

# HPC batch with Facebook first names only
hpc/submit_transcription.sh --mask-personal-names --use-facebook-names-for-masking

# HPC batch with both Facebook databases
hpc/submit_transcription.sh --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking
```

With the default curated dictionary, "The meeting will begin soon.
Thank you for joining, Mark." becomes "The meeting will begin soon.
Thank you for joining, [NAME]." The Facebook lists always pass through
the common-word filter, whatever its setting, so words on its list, "The"
and "Thank" among them, are never masked. Capitalised words that are not
on the list can be, and the lists are large enough to hold many of them.

The Facebook lists suit recordings whose names come from beyond the nine
languages, or where coverage matters more than readability, provided
someone reviews the output by hand. They suit informal conversation
poorly. When you use them, save the masking log and check both the
transcript and the log for ordinary words replaced by `[NAME]` or
`[SURNAME]`:

```bash
# Enable detailed logging when using Facebook database
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --save-name-masking-logs

# Review the logs before finalising
ls name_masking_logs/
# Check: name_replacements_interview.csv
```

The dictionary is built by `load_global_names(use_facebook_names,
use_facebook_surnames, selected_languages, exclude_common_words)` in
`transcription.py`. If `names-dataset` is not installed or its tables do
not load, the run prints an error and falls back to the curated
dictionary for both first names and surnames. For most users, the
curated dictionary gives the better balance of protection and
readability.

## Optional outputs

### Name masking logs

When names are masked, the run keeps a record of each replacement but
saves it only with `--save-name-masking-logs`. The log is one CSV per
recording, `name_masking_logs/name_replacements_<recording>.csv`,
relative to the directory the command runs from, and a later run on a
recording of the same name replaces it. It has one row per masked word,
with the columns `filename`, `order`, `original`, `replacement`,
`context_sentence` and `source`. `source` records which rule masked the
word: `dictionary`, `ner` (the optional named-entity stage) or `title`
(an honorific before a name). The logs hold the names themselves, so
treat them as confidential. Git ignores the directory, so a log cannot be
committed by accident. A log is the
audit trail of what was masked and the place to look for masking errors.

```bash
# Save name masking logs
python transcription.py "interview.wav" --mask-personal-names --save-name-masking-logs
hpc/submit_transcription.sh --mask-personal-names --save-name-masking-logs
```

### Enhanced audio files

Audio enhancement is off by default and runs only with `--enhance-audio`.
The enhanced recording is then written to a temporary file that is
deleted after the run. Add `--save-enhanced-audio` to keep it as
`output/enhanced_audio/<name>_enhanced.wav`, for example to listen to
what the enhancement did. Without `--enhance-audio` the flag has no
effect.

```bash
python transcription.py "interview.wav" --enhance-audio --save-enhanced-audio
hpc/submit_transcription.sh --enhance-audio --save-enhanced-audio
```
