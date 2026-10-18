# Advanced Usage

## Speaker Attribution

**Feature:** Automatic speaker diarisation (also called speaker attribution) using pyannote/speaker-diarization-3.1 model from HuggingFace.

**Technical Note:** *Diarisation* is the technical term for determining "who spoke when" in an audio recording. In this context, *attribution* means the same thing, that is, assigning speech segments to different speakers. Both terms are used interchangeably.

**Output format:** When speaker attribution is enabled, the system produces **two sets of transcripts**:

1. **Base transcripts** (standard filenames):
   - `filename_transcript.txt`
   - `filename_transcript.docx`
   - Clean transcription without speaker labels
   - Use for readability or when speaker identity not needed

2. **Speaker-attributed transcripts** (with `_with_speakers` suffix):
   - `filename_transcript_with_speakers.txt`
   - `filename_transcript_with_speakers.docx`
   - Includes speaker labels like `[SPEAKER_00]`, `[SPEAKER_01]`, etc. before each speaker's segment
   - Use for analysing who said what

**Why both versions?** Speaker labels can make transcripts harder to read, so clean versions are provided alongside attributed versions. You can choose which to use based on your needs.

**Setup guide:** See [PYANNOTE_SETUP_GUIDE.md](../PYANNOTE_SETUP_GUIDE.md) for setup instructions and troubleshooting.

**Quick Setup:**
```bash
python setup/setup_pyannote.py  # Interactive setup wizard (10-15 minutes)
```

**Usage:**
```bash
# For single files with Python
python transcription.py "interview.wav" --speaker-attribution

# For batch processing
hpc/submit_transcription.sh --speaker-attribution

# Combined with other options
hpc/submit_transcription.sh --mask-personal-names --speaker-attribution --language english
```

**Constraining the number of speakers (measure before you trust it):**
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

It is tempting to treat this as a free improvement. Left alone, the model
reliably finds more speakers than a recording contains, so telling it the
true number looks as though it can only help. On the AMI benchmark it did
not. Supplying the true count raised macro diarisation error from 16.6%
to 25.0%, worsening ten of the sixteen meetings, and in the worst case
took a meeting from 7.2% to 45.7%. All of that came from speaker
confusion. The reason is that clustering forced to stop at exactly *n*
must merge until it gets there, and merging two distinct speakers is
far more damaging than leaving a few spurious small clusters,
which contribute comparatively little error.

Those meetings had four speakers each, so the finding does not
automatically transfer to a two-person interview, where there is much
less scope for a harmful merge. The honest position is that the option is
available because the count is often known in advance, not because setting
it is advisable by default. If speaker labels matter to your analysis,
run a recording both ways and compare before adopting either.

**Accuracy factors:**
- **Recording quality**: clear audio with minimal background noise produces better results
- **Number of speakers**: works best with 2-4 speakers; accuracy decreases with more speakers
- **Speaker similarity**: similar-sounding voices (e.g., same gender, age, accent) are harder to distinguish
- **Speaker overlap**: simultaneous speech reduces attribution accuracy
- **Microphone setup**: single-microphone recordings are more challenging than multi-mic setups

**When to use:**
- Multi-speaker interviews or focus groups
- Panel discussions or meetings
- Conversations with distinct voices
- High-quality recordings with clear speakers

**When not to use:**
- Single-speaker recordings (unnecessary)
- Poor-quality audio with heavy background noise
- Many speakers with similar voices

**Example output:**

**Base transcript** (`filename_transcript.txt`):
```
Hello and welcome to today's interview. Thank you for joining us.

Thank you for having me. I'm excited to be here.

Let's start with your background. Can you tell us about your research?

Certainly. I've been working on computational linguistics for the past five years...
```

**Speaker-attributed transcript** (`filename_transcript_with_speakers.txt`):
```
[SPEAKER_00] Hello and welcome to today's interview. Thank you for joining us.

[SPEAKER_01] Thank you for having me. I'm excited to be here.

[SPEAKER_00] Let's start with your background. Can you tell us about your research?

[SPEAKER_01] Certainly. I've been working on computational linguistics for the past five years...
```

**Need help?** See [PYANNOTE_SETUP_GUIDE.md](../PYANNOTE_SETUP_GUIDE.md) for:
- Step-by-step setup instructions
- Common issues and solutions
- HPC-specific guidance
- Performance optimisation tips

### Air-gapped and offline operation

The diarisation model can be loaded entirely from local storage so that
no network call is made at run time. The resolution policy in
`perform_speaker_diarization` tries, in order, an explicit YAML config
file passed through `--diarization-config PATH`, then an explicit local
pipeline passed through `--diarization-model-path PATH` (its
`config.yaml`, or a directory holding one), and finally the
HuggingFace loader for the configured `model_id`. The HuggingFace loader
is used only when neither local option was given: if you name a local
pipeline and it cannot be loaded, the Hub model is not tried in its
place, and the run writes the transcript without speaker labels and
reports itself incomplete. Setting the
environment variable `HF_HUB_OFFLINE=1` or `TRANSFORMERS_OFFLINE=1`
forces the HuggingFace loader to operate cache-only by requesting
`local_files_only=True`; when the model is absent from the cache the
error message names the expected cache directory and the flags that
would resolve the situation. The JSON sidecar records the path that was
taken under the keys `diarization_model_source` (one of `'local_config'`,
`'local_path'`, `'hf_loader'`, `'hf_loader_offline'` or `'unavailable'`),
`diarization_model_id`, `diarization_model_path`,
`diarization_offline_mode` and an optional `diarization_error`; the
labels are defined in the [glossary](glossary.md). It also records the
Hub snapshots the load used, `diarization_model_revision` for the
pipeline and `diarization_sub_model_revisions` for the segmentation and
embedding models its configuration names. They are read back from the
cache without pinning the load, so an offline machine whose cache holds
another snapshot still diarises and says which snapshot it used.

## Redacting names from the audio, not only the transcript

Masking removes names from the text the workflow writes. The recording
still says them. For a dataset that will be shared or archived, that is
the gap that matters, because the audio is the copy that carries a voice
as well as a name.

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
the run used (`python -m audio_redaction --help` lists them). A run that
finds no name to redact refuses to write its output unless
`--allow-empty` is given, because a `_redacted.wav` identical to the
input would be misleading.

`--mode silence` (the default) writes silence instead of a tone. `--pad`
(default 0.05 s) widens each span slightly, so a timestamp that clips the
start or end of a word still covers the whole of it.

It is a separate command rather than a flag on the transcriber, so a
recording can be redacted from a transcript produced earlier without
transcribing it again.

Two limits are worth stating plainly. The redaction is only as good as the
masking that drives it, so a name the dictionary never knew is spoken in
the output as well as written in the transcript; the optional
named-entity stage described in the README exists for exactly that case. And it is only as good as the
timestamps, whose accuracy is measured in the manuscript's timestamp
benchmark. The pairing of the two has not itself been scored, so treat
the output as a strong default rather than a guarantee, and listen to a
sample before releasing a corpus.

## Repetition Fixing

**Problem:** Whisper models sometimes introduce spurious repetitions or get stuck in repetitive patterns, especially with challenging audio or when processing longer segments.

**Examples of repetition artefacts:**
- Repeated phrases: "And then, and then, and then he said..."
- Stuck patterns: "The the the meeting will start"
- Echo effects: "Hello hello, how are you you?"
- Loop artefacts: Entire sentences repeated multiple times

**Solution:** Use the `--fix-spurious-repetitions` flag to enable advanced repetition detection and removal:

```bash
# For single files with Python
python transcription.py "audio_input/interview.wav" --fix-spurious-repetitions

# For batch processing
hpc/submit_transcription.sh --fix-spurious-repetitions

# Combined with other options
hpc/submit_transcription.sh --mask-personal-names --fix-spurious-repetitions --language english
```

**How it works:**
- Detects and removes repetitive word patterns
- Identifies and fixes stuck transcription loops
- Preserves intentional repetitions (like emphasis or natural speech patterns)
- Uses context-aware algorithms to distinguish between artefacts and genuine repetition

**When to use:**
- Poor-quality audio with background noise
- Long audio files (>30 minutes) where models may get unstable
- Technical or challenging content where models struggle
- When you notice repetitive artefacts in initial transcriptions
- Less useful for high-quality, short audio files

## Multilingual Name Masking

### Overview

The system includes a multilingual name database loaded from `data/curated_names.csv` with curated names from 9 languages, providing safer and more targeted name masking than the much larger Facebook global database. The CSV format allows the name database to be expanded and maintained easily.

### Supported languages

English, Chinese (romanised Pinyin), French, German, Hindi (romanised), Spanish, Italian, Arabic and Polynesian. Each entry is tagged as a first name or a surname and with its language, written as a full lower-case name such as `english`.

The dictionary holds 1,793 names: 967 English, 180 French, 176 Spanish, 143 Chinese, 141 German, 141 Hindi, 21 Italian, 13 Arabic and 11 Polynesian.

### Default behaviour

**Without language specification (RECOMMENDED):**
- Uses all 9 languages for broad coverage
- Balances coverage against false positives
- Suitable for international content with diverse speakers

### Language Selection Options

Use the `--languages-for-name-masking` argument to select specific languages for the curated database. Languages are given as full names, in any letter case (`english`, `Spanish`). A name the dictionary does not contain, or an ISO code such as `en`, stops the run with an error listing the valid names, because silently loading no names would mask nothing while the transcript header still said names were masked.

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

### Language Selection Examples

These outputs were produced by the masker itself. The first two use the
common-word filter, which is on for an English transcript; the third
has it off, as for a non-English transcript, because the filter also
drops every name shorter than three letters, such as "Li" and "Yu".

#### All Languages (Default):
```
Input:  "Hello Maria Rodriguez, this is John Smith and Wei Chen speaking with Raj Patel and François Dubois."
Output: "Hello [NAME] [SURNAME], this is [NAME] [SURNAME] and [SURNAME] [SURNAME] speaking with [NAME] [SURNAME] and François [SURNAME]."
```

#### English Only:
```
Input:  "Hello Maria Rodriguez, this is John Smith and Wei Chen speaking with Raj Patel and François Dubois."
Output: "Hello Maria [SURNAME], this is [NAME] [SURNAME] and Wei Chen speaking with Raj [SURNAME] and François Dubois."
```

"Rodriguez" and "Patel" are in the English list as surnames; "Maria",
"Raj" and "Dubois" are not.

#### Chinese + Spanish Only:
```
Input:  "Li Wei and Zhang Yu were talking to Carlos Martinez and Ana Rodriguez."
Output: "[SURNAME] [SURNAME] and [SURNAME] [SURNAME] were talking to [NAME] [SURNAME] and [NAME] [SURNAME]."
```

### When to Use Language Selection

**Use specific languages when:**
- You know the linguistic background of speakers
- Processing content with a specific regional focus
- Minimising false positives for particular language contexts
- Working with specialised international content

**Use all languages (default) when:**
- Processing diverse international content
- Uncertain about speaker backgrounds
- Maximum name coverage is needed
- Working with multicultural environments

### Technical implementation

- **Unicode support**: handles non-Latin scripts
- **Romanisation**: Chinese (Pinyin) and Hindi names in Latin script
- **Alphabetical organisation**: names sorted within each language set
- **Memory efficient**: only selected languages loaded into memory
- **Quality control**: curated names per language

### Combining with Facebook Database

You can combine language selection with Facebook database options:

```bash
# Facebook first names + selected languages for surnames
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --languages-for-name-masking english spanish

# Facebook surnames + selected languages for first names  
python transcription.py interview.wav --mask-personal-names --use-facebook-surnames-for-masking --languages-for-name-masking chinese hindi

# Both Facebook databases + language selection (for curated backup)
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking --languages-for-name-masking english
```

**Note**: When Facebook databases are enabled, the `--languages-for-name-masking` parameter affects the curated database used as a backup/supplement.

### Common English Word Filtering

Some names, such as "Will", "Grace", "Long" and "Hall", are also English words. The masker only ever masks capitalised words, so the lower-case word in "they will continue" is safe either way; the problem is the capitalised word, at the start of a sentence, in a title or as part of a place name. The common-word filter removes from the dictionary about 660 common English words, together with every name shorter than three letters.

With all languages selected, the masker gives:

```
Input:            "Then Will said that Grace and Art would meet Pablo in Long Hall."
Filter off:       "Then [NAME] said that [NAME] and [NAME] would meet [NAME] in [NAME] [SURNAME]."
Filter on:        "Then Will said that Grace and [NAME] would meet [NAME] in Long Hall."
```

"Art" is masked either way, because it is not on the list of common words.

#### Smart Default Behaviour

The system applies these defaults automatically:

- **English transcripts (`--language english`)**: filtering is on by default, to prevent false positives
- **Other languages**: filtering is off by default, to preserve legitimate names such as the Chinese names "An" and "Long"
- **No language specified**: the decision follows the language detected from
  the audio, so an English recording gets filtering ON and a non-English one gets
  it OFF, exactly as if the language had been stated. Detection is a guess,
  though, and the terminal warns you when one was made; pass `--language` to be
  certain. The same detected language also governs which post-processing stages
  run (see [conditions_audit.md](conditions_audit.md#the-language-gate)).

#### Usage Examples

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

The HPC wrapper, `hpc/submit_transcription.sh`, does not yet accept the
`--no-` form, so on the cluster the filter can be forced on but not off.

#### Filtered Words

The list, in `filter_problematic_names` in `transcription.py`, covers
colours, months and days, common verbs and nouns and similar words that
double as names, for example: will, may, can, is, was, long, page, hall,
west, north, south, june, august, parker, amber, grace, rose, ruby, fox,
bill, joy and hope. Names shorter than three letters, such as "An", "Li"
and "Yu", are removed along with them.

#### When to Use

**Enable filtering (or use `--language english`) when:**
- Transcribing English-language audio
- False positives are causing readability issues
- Common words like "will", "may", "long" appear frequently in context

**Disable filtering (or avoid `--language english`) when:**
- Transcribing non-English audio with English loanwords
- Names like Chinese "An" or "Long" are expected
- Working with international speakers using English names
- Processing multilingual content with diverse name origins

### Excluding Specific Names from Masking

Sometimes you may want to preserve certain names in your transcripts whilst masking others. This is useful for keeping public figures, celebrities or specific participants identifiable.

**Use case**: Mask most names for privacy but preserve well-known public figures (e.g., "Einstein", "Darwin") or specific participants for reference.

#### Command-Line Options

**Option 1: Comma-separated list**
```bash
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-from-masking "Einstein,Darwin,Newton"

# HPC batch processing
hpc/submit_transcription.sh --mask-personal-names \
  --exclude-names-from-masking "Einstein,Curie"
```

**Option 2: File with name list** (one name per line)
```bash
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-file excluded_names.txt

# HPC batch processing
hpc/submit_transcription.sh --mask-personal-names \
  --exclude-names-file excluded_names.txt
```

**Option 3: Combine both methods**
```bash
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-file celebrities.txt \
  --exclude-names-from-masking "ResearcherName"
```

#### Behaviour

- **Case-insensitive**: "Einstein", "einstein", "EINSTEIN" all treated identically
- **Applies to both first and surnames**: Excluded names removed from both databases
- **Works with all database options**: Compatible with curated and Facebook databases
- **Only specified names excluded**: All other names still masked normally

#### When to Use

**Recommended for:**
- Content referencing well-known public figures (Einstein, Shakespeare, Darwin)
- Preserving specific participants whilst masking others
- Educational materials where certain names provide essential context
- Names already in the public domain

**Avoid when:**
- All participants require equal privacy protection
- Unsure which names should be preserved
- Processing highly sensitive content requiring maximum privacy

### Facebook Names Database Option

#### Overview

The system includes optional names databases sourced from Facebook's `names-dataset` package, containing over **1.7 million names**:
- **730,000+ first names** from 106 countries
- **980,000+ surnames** from global datasets

**Database source:** The names database is provided by Philippe Remy's `name-dataset` project, available at: https://github.com/philipperemy/name-dataset

**The Facebook database is disabled by default** because of high false positive rates when masking common English words.

#### Current default behaviour

**Without Facebook database flags (RECOMMENDED):**
- Uses the curated database loaded from `data/curated_names.csv` (1,793 names across 9 languages)
- Organised by language: `english`, `chinese`, `french`, `german`, `hindi`, `spanish`, `italian`, `arabic`, `polynesian`
- Each entry tagged as 'first' or 'last' name with a language code
- Fewer false positives (common English words excluded)
- Better precision for privacy protection
- Maintains conversation flow and readability
- Expandable by adding entries to the CSV file

#### Enabling Facebook Names Databases

**Granular control:**
- `--use-facebook-names-for-masking`: use Facebook's 730K+ first names database only
- `--use-facebook-surnames-for-masking`: use Facebook's 980K+ surnames database only
- Use both flags together for full Facebook database coverage
- Higher risk of false positives when enabled

#### Usage Examples

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

#### When to Use Facebook Names Database

**Warning:** The Facebook database option markedly increases false positives compared with the curated database. Manual quality review is essential when using this option.

**Consider using when:**
- Processing international content with diverse name origins beyond the 9 supported languages
- Maximum name coverage is critical for privacy compliance
- You can manually review transcripts for false positives
- Processing technical or formal content with fewer conversation words

**Avoid when:**
- Processing conversational speech with common English words
- Automated processing without manual review capability
- Readability and natural flow are priorities
- Working with informal interviews or casual conversations

#### Expected Differences

With the default curated dictionary, "The meeting will begin soon. Thank you for joining, Mark." becomes "The meeting will begin soon. Thank you for joining, [NAME]." The Facebook lists are large enough to contain many ordinary capitalised words, so with them enabled, sentence-initial words such as "The" or "Thank" can be masked as well; check the masking log to see what was.

#### Required Special Attention

**When using `--use-facebook-names-for-masking`, carefully review:**

1. **Transcripts:** Check for over-masking of common words
   - Look for `[NAME]` and `[SURNAME]` replacing common words
   - Verify conversation flow remains readable
   - Check if context clues remain for understanding

2. **Name Masking Logs:** Use `--save-name-masking-logs` for detailed tracking
   - Review `name_masking_logs/` CSV files for false positives
   - Audit masked terms to identify problematic patterns
   - Use logs to fine-tune masking for specific content types

3. **Quality Control Workflow:**
   ```bash
   # Enable detailed logging when using Facebook database
   python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --save-name-masking-logs
   
   # Review the logs before finalising
   ls name_masking_logs/
   # Check: name_replacements_interview.csv
   ```

#### Technical Implementation

The dictionary is built by `load_global_names(use_facebook_names, use_facebook_surnames, selected_languages, exclude_common_words)` in `transcription.py`. Each Facebook flag replaces the curated first names or surnames with the corresponding `names-dataset` list, which is always passed through the common-word filter whatever the filter setting; the curated dictionary supplies whichever of the two is not replaced. If `names-dataset` is not installed or its tables do not load, the run prints an error and falls back to the curated dictionary for both.

#### Recommendation

**For most users:** Stick with the default curated database (1,793 names across 9 languages) for a better balance of privacy protection and readability. The curated database covers English, Chinese, French, German, Hindi, Spanish, Italian, Arabic and Polynesian names whilst minimising false positives. Only enable the Facebook database when global name coverage beyond these languages is essential and you can invest time in manual quality review.

## Optional Output Features

### Name Masking Logs

By default, when name masking is enabled, the system tracks which names were replaced but doesn't save detailed logs. Use `--save-name-masking-logs` to enable detailed logging:

**Feature:**
- Saves one CSV per recording, `name_masking_logs/name_replacements_<recording>.csv`, relative to the directory the command runs from, replacing any earlier log for a recording of the same name
- One row per masked word, with the columns `filename`, `order`, `original`, `replacement`, `context_sentence` and `source`
- `source` records which rule masked the word: `dictionary`, `ner` (the optional named-entity stage) or `title` (an honorific before a name)
- The logs hold the names themselves, so treat them as confidential; the directory is ignored by git

**When to use:**
- When you need audit trails for privacy compliance
- For reviewing masking accuracy and false positives
- When processing sensitive content requiring documentation
- Not needed for casual transcription

**Example:**
```bash
# Save name masking logs
python transcription.py "interview.wav" --mask-personal-names --save-name-masking-logs
hpc/submit_transcription.sh --mask-personal-names --save-name-masking-logs
```

### Enhanced Audio Files

Audio enhancement is off by default and runs only with `--enhance-audio`. The enhanced recording is then written to a temporary file that is deleted after the run. Add `--save-enhanced-audio` to keep it as `output/enhanced_audio/<name>_enhanced.wav`, for example to listen to what the enhancement did; without `--enhance-audio` the flag has no effect.

```bash
python transcription.py "interview.wav" --enhance-audio --save-enhanced-audio
hpc/submit_transcription.sh --enhance-audio --save-enhanced-audio
```

**Note:** Both features are OFF by default to conserve storage space and focus on essential transcription output.
