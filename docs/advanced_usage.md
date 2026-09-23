# Advanced Usage

## Speaker Attribution

**Feature:** Automatic speaker diarisation (also called speaker attribution) using pyannote/speaker-diarization-3.1 model from HuggingFace.

**Technical Note:** *Diarisation* is the technical term for determining "who spoke when" in an audio recording. In this context, *attribution* means the same thing—assigning speech segments to different speakers. Both terms are used interchangeably.

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

**📖 Setup Guide:** See [PYANNOTE_SETUP_GUIDE.md](../PYANNOTE_SETUP_GUIDE.md) for complete setup instructions and troubleshooting.

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

⚠️ **Accuracy Factors:**
- **Recording quality**: Clear audio with minimal background noise produces better results
- **Number of speakers**: Works best with 2-4 speakers; accuracy decreases with more speakers
- **Speaker similarity**: Similar-sounding voices (e.g., same gender, age, accent) are harder to distinguish
- **Speaker overlap**: Simultaneous speech reduces attribution accuracy
- **Microphone setup**: Single microphone recordings are more challenging than multi-mic setups

**When to use:**
- ✅ Multi-speaker interviews or focus groups
- ✅ Panel discussions or meetings
- ✅ Conversations with distinct voices
- ✅ High-quality recordings with clear speakers
- ❌ Single speaker recordings (unnecessary)
- ❌ Poor quality audio with heavy background noise
- ❌ Many speakers with similar voices

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

## Repetition Fixing

**Problem:** Whisper models sometimes introduce spurious repetitions or get stuck in repetitive patterns, especially with challenging audio or when processing longer segments.

**Examples of repetition artifacts:**
- Repeated phrases: "And then, and then, and then he said..."
- Stuck patterns: "The the the meeting will start"
- Echo effects: "Hello hello, how are you you?"
- Loop artifacts: Entire sentences repeated multiple times

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
- Uses context-aware algorithms to distinguish between artifacts and genuine repetition

**When to use:**
- ✅ Poor quality audio with background noise
- ✅ Long audio files (>30 minutes) where models may get unstable
- ✅ Technical or challenging content where models struggle
- ✅ When you notice repetitive artifacts in initial transcriptions
- ❌ High-quality, short audio files (may not be necessary)

## Multilingual Name Masking

### Overview

The system includes a comprehensive multilingual name database loaded from `data/curated_names.csv` with carefully curated names from 6 major languages, providing safer and more targeted name masking compared to the massive Facebook global database. The CSV format allows easy expansion and maintenance of the name database.

### Supported Languages

- **English**: 185 first names, 41 surnames (common English names)
- **Chinese**: 95 first names, 40 surnames (romanized Pinyin)  
- **French**: 106 first names, 25 surnames (popular French names)
- **German**: 80 first names, 30 surnames (common German names)
- **Hindi**: 96 first names, 28 surnames (romanized Indian names)
- **Spanish**: 105 first names, 34 surnames (Hispanic names)

**Total Coverage**: 618 first names, 184 surnames across all languages

### Default Behaviour

**Without language specification (RECOMMENDED):**
- Uses ALL 6 languages for comprehensive coverage
- Balanced approach between coverage and false positives
- Suitable for international content with diverse speakers

### Language Selection Options

Use the `--languages-for-name-masking` argument to select specific languages for the curated database:

```bash
# Use the default languages: English, Chinese, French, German, Hindi and Spanish
python transcription.py interview.wav --mask-personal-names

# Use all nine supported languages
python transcription.py interview.wav --mask-personal-names --languages-for-name-masking english chinese french german hindi spanish italian arabic polynesian

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

#### Default Languages (English, Chinese, French, German, Hindi and Spanish):
```
Input:  "Hello Maria Rodriguez, this is John Smith and Wei Chen speaking with Raj Patel and François Dubois."
Output: "Hello [NAME] [SURNAME], this is [NAME] [SURNAME] and [SURNAME] [SURNAME] speaking with [NAME] [SURNAME] and François [SURNAME]."
```

#### English Only:
```
Input:  "Hello Maria Rodriguez, this is John Smith and Wei Chen speaking with Raj Patel and François Dubois."
Output: "Hello Maria [SURNAME], this is [NAME] [SURNAME] and Wei Chen speaking with Raj Patel and François Dubois."
```

#### Chinese + Spanish Only:
```
Input:  "Li Wei and Zhang Yu were talking to Carlos Martinez and Ana Rodriguez."
Output: "[SURNAME] [SURNAME] and [SURNAME] [SURNAME] were talking to [NAME] [SURNAME] and [NAME] [SURNAME]."
```

### When to Use Language Selection

**✅ Use specific languages when:**
- You know the linguistic background of speakers
- Processing content with specific regional focus
- Minimizing false positives for particular language contexts
- Working with specialised international content

**✅ Use the default languages, or all nine, when:**
- Processing diverse international content
- Uncertain about speaker backgrounds
- Maximum name coverage is needed
- Working with multicultural environments

### Technical Implementation

- **Unicode Support**: Proper handling of non-Latin scripts
- **Romanization**: Chinese (Pinyin) and Hindi names in Latin script
- **Alphabetical Organisation**: Names sorted within each language set
- **Memory Efficient**: Only selected languages loaded into memory
- **Quality Control**: ~200 carefully selected popular names per language

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

**Problem**: Some legitimate names (like "Will", "Art", "Long", "Hall") are also common English words, leading to false positives where normal text is incorrectly masked.

**Example of the problem:**
```
Input:  "They will continue to art class in the long hall."
Output (without filtering): "They [NAME] continue to [NAME] class in the [NAME] [SURNAME]."
Output (with filtering):    "They will continue to art class in the long hall."
```

**Solution**: The `--exclude-common-english-words-from-name-masking` flag filters out ~200 common English words from the name masking database.

#### Smart Default Behaviour

The system automatically applies intelligent defaults:

- **English transcripts (`--language english`)**: Filtering is **ON by default** to prevent false positives
- **Other languages**: Filtering is **OFF by default** to preserve legitimate names (e.g., Chinese names "An" and "Long")
- **No language specified**: Filtering is **OFF by default** (auto-detect mode assumes multilingual)

#### Usage Examples

```bash
# English transcript - filtering enabled automatically
python transcription.py interview.wav --mask-personal-names --language english
# Output: "will continue" stays as-is, actual names like "Pablo" → [NAME]

# Chinese transcript - filtering disabled automatically  
python transcription.py interview.wav --mask-personal-names --language chinese
# Output: Chinese name "An" → [NAME], English word "an" → [NAME] (Chinese "An" preserved)

# Override default for English (disable filtering)
python transcription.py interview.wav --mask-personal-names --language english --exclude-common-english-words-from-name-masking=false
# Output: "will continue" → "[NAME] continue" (filtering disabled)

# HPC batch processing with automatic filtering
hpc/submit_transcription.sh --mask-personal-names --language english
```

#### Filtered Words

The system filters ~200 common English words including (but not limited to):
- **Articles/pronouns**: an, will, as, may, can, is, are, was
- **Common verbs**: long, art, drew, page, grant
- **Location words**: hall, hunt, west, woods, north, south
- **Time words**: june, may, august, winter, spring
- **Other**: parker, ward, amber, grace, holly, ivy, rose, ruby, fox

This prevents sentences like "We will long for grace and art" from becoming "We [NAME] [NAME] for [NAME] and [NAME]".

#### When to Use

**✅ Enable filtering (or use `--language english`) when:**
- Transcribing English-language audio
- False positives are causing readability issues
- Common words like "will", "may", "long" appear frequently in context

**✅ Disable filtering (or avoid `--language english`) when:**
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

**✅ Recommended for:**
- Content referencing well-known public figures (Einstein, Shakespeare, Darwin)
- Preserving specific participants whilst masking others
- Educational materials where certain names provide essential context
- Names already in public domain

**❌ Avoid when:**
- All participants require equal privacy protection
- Unsure which names should be preserved
- Processing highly sensitive content requiring maximum privacy

### Facebook Names Database Option

#### Overview

The system includes optional comprehensive names databases sourced from Facebook's `names-dataset` package, containing over **1.7 million names**:
- **730,000+ first names** from 106 countries
- **980,000+ surnames** from global datasets

**Database Source:** The names database is provided by Philippe Remy's `name-dataset` project, available at: https://github.com/philipperemy/name-dataset

**⚠️ IMPORTANT: The Facebook database is DISABLED by default** due to high false positive rates when masking common English words.

#### Current Default Behaviour

**Without Facebook database flags (RECOMMENDED):**
- Uses curated database loaded from `data/curated_names.csv` (1,793 carefully selected names across 9 languages)
- Organised by language: `english`, `chinese`, `french`, `german`, `hindi`, `spanish`, `italian`, `arabic`, `polynesian`
- Each entry tagged as 'first' or 'last' name with language code
- Significantly reduced false positives (common English words excluded)
- Better precision for privacy protection
- Maintains conversation flow and readability
- Easily expandable by adding entries to CSV file

#### Enabling Facebook Names Databases

**New Granular Control (Breaking Change):**
- `--use-facebook-names-for-masking`: Use Facebook's 730K+ first names database only
- `--use-facebook-surnames-for-masking`: Use Facebook's 980K+ surnames database only
- **Use both flags together** for full Facebook database coverage
- **Higher risk of false positives** when enabled

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

# Enable BOTH Facebook databases (comprehensive but more false positives)
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking

# HPC batch with Facebook first names only
hpc/submit_transcription.sh --mask-personal-names --use-facebook-names-for-masking

# HPC batch with both Facebook databases
hpc/submit_transcription.sh --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking
```

#### When to Use Facebook Names Database

**⚠️ Warning:** The Facebook database option significantly increases false positives compared to the curated database. Manual quality review is essential when using this option.

**✅ Consider using when:**
- Processing international content with diverse name origins beyond the 9 supported languages
- Maximum name coverage is critical for privacy compliance
- You can manually review transcripts for false positives
- Processing technical or formal content with fewer conversation words

**❌ Avoid when:**
- Processing conversational speech with common English words
- Automated processing without manual review capability
- Readability and natural flow are priorities
- Working with informal interviews or casual conversations

#### Expected Differences

**Default Curated Database:**
```
Speaker: "The meeting will begin soon. Thank you for joining, Mark."
Output:  "[NAME] meeting will begin soon. [NAME] you for joining, [NAME]."
```
*(Note: "The", "Thank", and "Mark" all detected as potential names)*

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
   
   # Review the logs before finalizing
   ls name_masking_logs/
   # Check: interview_name_changes_YYYY-MM-DD_HHMMSS.csv
   ```

#### Technical Implementation

- **Default:** `load_global_names(use_facebook_database=False)`
- **Facebook Enabled:** `load_global_names(use_facebook_database=True)`
- **Memory Impact:** Facebook database requires ~50MB additional RAM
- **Processing Speed:** Minimal impact on transcription performance

#### Recommendation

**For most users:** Stick with the curated database (1,793 names across nine languages, six of which are selected by default) for better balance of privacy protection and readability. The curated database provides comprehensive coverage for English, Chinese, French, German, Hindi, Spanish, Italian, Arabic and Polynesian names whilst minimising false positives. Only enable the Facebook database when comprehensive global name coverage beyond these languages is absolutely essential and you can invest time in manual quality review.

## Optional Output Features

### Name Masking Logs

By default, when name masking is enabled, the system tracks which names were replaced but doesn't save detailed logs. Use `--save-name-masking-logs` to enable comprehensive logging:

**Feature:**
- Saves detailed CSV logs to `name_masking_logs/` directory (in project root)
- Tracks every name replacement with context sentences
- Includes replacement order, original text and masked version

**When to use:**
- ✅ When you need audit trails for privacy compliance
- ✅ For reviewing masking accuracy and false positives
- ✅ When processing sensitive content requiring documentation
- ❌ For casual transcription where detailed logs aren't needed

**Example:**
```bash
# Save name masking logs
python transcription.py "interview.wav" --mask-personal-names --save-name-masking-logs
hpc/submit_transcription.sh --mask-personal-names --save-name-masking-logs
```

### Enhanced Audio Files

By default, the system enhances audio for better transcription but doesn't save the enhanced files. Use `--save-enhanced-audio` to preserve them:

**Feature:**
- Saves enhanced audio files to `output/enhanced_audio/` directory
- Files include noise reduction, amplification and optimisation
- Useful for quality verification or reprocessing

**When to use:**
- ✅ When you want to verify audio enhancement quality
- ✅ For reprocessing with different transcription models
- ✅ When archiving enhanced versions for future use
- ❌ To save disk space (enhanced files can be 2x original size)

**Example:**
```bash
# Save enhanced audio files
python transcription.py "interview.wav" --save-enhanced-audio
hpc/submit_transcription.sh --save-enhanced-audio
```

**Note:** Both features are OFF by default to conserve storage space and focus on essential transcription output.
