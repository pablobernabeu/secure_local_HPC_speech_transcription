#!/usr/bin/env python3
"""Local speech transcription pipeline: the command-line tool and its stages.

Run as ``python transcription.py <audio> [options]``. For one recording it
can, depending on the flags:

1. enhance the audio (``--enhance-audio``);
2. diarise speakers with pyannote.audio (``--speaker-attribution``);
3. transcribe with a Whisper model through transformers, detecting the
   language when none is given;
4. write word-timestamped JSON and WebVTT before any post-processing
   (``--timestamps``), with a name-masked parallel set when masking is on,
   and a review report flagging suspect segments;
5. clean the text (the stages in :data:`CLEAN_TEXT_STAGES`, English-only
   ones skipped for other languages) and optionally repair runaway
   repetitions (``--fix-spurious-repetitions``);
6. mask personal names with a curated dictionary
   (``--mask-personal-names``), optionally logging every replacement;
7. write .txt and .docx transcripts, with and without speaker labels, and
   a run manifest hashing every artefact the run wrote.

The clean-up stages are also imported by ``evaluation/conditions.py`` for
the WER benchmark, so their behaviour is fixed by committed results.

Side effects: outputs go under ``output/`` and ``name_masking_logs/``
relative to the working directory. Heavy dependencies (torch, librosa,
transformers, python-docx, pyannote.audio) are optional at import time, so
the text and masking helpers work without them; a missing one is reported
on stdout. Importing the module installs no warning filters.
"""

import os
import sys
import re
import argparse
from pathlib import Path
from datetime import datetime
import csv
import functools
import json
import unicodedata
from collections import Counter
# Make docx import optional for testing name masking
try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    DOCX_AVAILABLE = True
except ImportError:
    print("Warning: python-docx not available - Word document creation disabled")
    DOCX_AVAILABLE = False
    Document = None
    WD_ALIGN_PARAGRAPH = None
# No warnings filter is installed here. A module-level
# warnings.filterwarnings("ignore") used to sit on this line, and because
# evaluation/conditions.py imports this module inside the WER benchmark it
# silenced every later warning in that process (library deprecations,
# dtype fallbacks, empty-slice RuntimeWarnings), so a degraded run looked
# clean in its log. Filter a specific warning, by category and module, at
# the call site that raises it if one ever proves too noisy.

# Audio processing imports - make conditional to allow name masking to work independently
try:
    import librosa
    import soundfile as sf
    import numpy as np
    import torch
    AUDIO_LIBS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Audio processing libraries not available - {e}")
    print("Name masking will work, but audio transcription will be disabled")
    AUDIO_LIBS_AVAILABLE = False
    librosa = None
    sf = None
    np = None
    torch = None

# Make ffmpeg reachable before anything tries to decode audio.  Setting
# IMAGEIO_FFMPEG_EXE alone, as this did previously, achieves nothing for
# audio loading: that variable is read by imageio, whereas librosa, audioread
# and pydub all shell out to a binary named ``ffmpeg`` found on PATH.  A
# bundled ffmpeg carries a versioned filename and so stayed invisible to
# them, which is why compressed formats such as .m4a failed to open with
# "Format not recognised" on machines that in fact had a usable decoder.
try:
    from audio_io import ensure_ffmpeg_on_path, load_audio
    _FFMPEG_PATH = ensure_ffmpeg_on_path()
    _HAS_AUDIO_IO = True
except Exception as _audio_io_error:  # pragma: no cover - defensive
    _FFMPEG_PATH = None
    _HAS_AUDIO_IO = False
    print(f"Warning: audio_io unavailable ({_audio_io_error}); "
          "compressed audio may not load")

# Transformers import - also conditional
try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    print("Warning: transformers not available - transcription disabled")
    TRANSFORMERS_AVAILABLE = False
    pipeline = None

#: Where a run writes its outputs. These are relative to the working
#: directory, which is conventional for a command-line tool and what the
#: repository's callers rely on: the GUI and the HPC scripts change into
#: the repository first. Inputs the tool ships with (data/curated_names.csv,
#: versions.csv, hf_token.txt) are resolved against this script instead.
TRANSCRIPTS_DIR = "output/transcripts"
ENHANCED_AUDIO_DIR = "output/enhanced_audio"


# Enhanced name masking with global database and logging
def ensure_names_dataset():
    """Return whether the optional names-dataset package can be imported.

    It is needed only for the Facebook name lists. The check is an import
    and nothing more: an earlier version prepended the user site-packages
    directory to sys.path for the rest of the process (which, in a venv
    with user site disabled, put it ahead of the standard library and the
    environment's own packages) and built a whole NameDataset only to test
    it, so the large tables were loaded twice.
    """
    try:
        import names_dataset  # noqa: F401
    except ImportError as e:
        print(f"   ⚠️  names-dataset package not available: {e}")
        print("   📋 Will use enhanced basic names fallback")
        return False
    print("   ✅ names-dataset package found and imported")
    return True

def load_global_names(use_facebook_names=False, use_facebook_surnames=False,
                      selected_languages=None, exclude_common_words=True):
    """Load and filter global names database using names-dataset package.

    Args:
        use_facebook_names (bool): If True, use Facebook's global first names
                                 database (730K+ names).
                                 If False, use curated multilingual first names.
                                 Default: False (to avoid false positives)
        use_facebook_surnames (bool): If True, use Facebook's global surnames
                                    database (980K+ names).
                                    If False, use curated multilingual surnames.
                                    Default: False (to avoid false positives)
        selected_languages (list): Languages to include from curated database,
                                 case-insensitive. If None, uses every
                                 language in data/curated_names.csv
                                 (see :func:`curated_name_languages`).
        exclude_common_words (bool): Remove names that are also common
                                 English words (:func:`filter_problematic_names`).

    Returns:
        tuple: ``(first_names, surnames)``, two sets of lower-case names.

    Raises:
        FileNotFoundError, RuntimeError, ValueError: as
        :func:`create_multilingual_curated_names`, whenever the curated
        dictionary is needed and cannot supply names for the request.
    """

    # Determine what to load based on flags
    use_any_facebook = use_facebook_names or use_facebook_surnames

    # If no Facebook database is requested, use multilingual curated names directly
    if not use_any_facebook:
        print("   [DATABASE] Using MULTILINGUAL CURATED NAMES DATABASE "
              "(Facebook database disabled)")
        print("   [INFO] Curated names per language are counted below")
        print("   [SUCCESS] Reduces false positives from global names")
        return create_multilingual_curated_names(selected_languages, exclude_common_words)

    # Facebook database requested for names and/or surnames
    print("   [GLOBAL] FACEBOOK GLOBAL DATABASE REQUESTED")
    if use_facebook_names and use_facebook_surnames:
        print("   [LOAD] Loading both first names and surnames from Facebook database")
    elif use_facebook_names:
        print("   [LOAD] Loading first names only from Facebook database")
    elif use_facebook_surnames:
        print("   [LOAD] Loading surnames only from Facebook database")
    print("   [WARNING] May cause false positives with common words")

    # Try to use the names-dataset package
    if not ensure_names_dataset():
        print("   [ERROR] FACEBOOK DATABASE UNAVAILABLE: names-dataset package not installed")
        print("   [FALLBACK] Using multilingual curated names")
        return create_multilingual_curated_names(selected_languages, exclude_common_words)

    print("   Loading names-dataset package...")
    from names_dataset import NameDataset

    # Constructed once: the tables are large, and an earlier version built
    # a second instance only to test that the first would work.
    try:
        nd = NameDataset()
    except (OSError, ValueError, RuntimeError) as e:
        print(f"   [ERROR] FACEBOOK DATABASE FAILED: {e}")
        print("   [FALLBACK] Using multilingual curated names")
        return create_multilingual_curated_names(selected_languages, exclude_common_words)
    print("   ✅ Names-dataset package loaded successfully")

    # names-dataset 3.x exposes plain dicts keyed by name. Earlier code also
    # probed get_first_names(), search() and a data attribute, APIs no
    # supported release has; they are gone.
    def _names_from(attribute):
        table = getattr(nd, attribute, None)
        if not isinstance(table, dict):
            print(f"   ⚠️  names-dataset has no '{attribute}' table ({type(table).__name__})")
            return set()
        return {name.lower().strip() for name in table if name.strip()}

    all_first_names = _names_from('first_names') if use_facebook_names else set()
    all_surnames = _names_from('last_names') if use_facebook_surnames else set()
    if use_facebook_names:
        print(f"   ✅ Extracted {len(all_first_names)} first names")
    if use_facebook_surnames:
        print(f"   ✅ Extracted {len(all_surnames)} surnames")

    # Fewer than a hundred names means the table did not load properly.
    # TODO: justify (source unknown) the threshold of 100.
    missing = []
    if use_facebook_names and len(all_first_names) <= 100:
        missing.append("first names")
    if use_facebook_surnames and len(all_surnames) <= 100:
        missing.append("surnames")
    if missing:
        print(f"   [ERROR] FACEBOOK DATABASE FAILED: insufficient data for: {', '.join(missing)}")
        print("   [FALLBACK] Using multilingual curated names")
        return create_multilingual_curated_names(selected_languages, exclude_common_words)

    print("   ✅ FACEBOOK DATABASE LOADED SUCCESSFULLY")
    print(f"   📊 Raw extraction: {len(all_first_names)} first names, {len(all_surnames)} surnames")

    # Apply filtering to both sets (only if they were loaded)
    filtered_first_names = (filter_problematic_names(all_first_names)
                            if use_facebook_names else set())
    filtered_surnames = filter_problematic_names(all_surnames) if use_facebook_surnames else set()

    # Merge with curated multilingual names for the types not requested from Facebook
    if not use_facebook_names or not use_facebook_surnames:
        basic_first_names, basic_surnames = create_multilingual_curated_names(
            selected_languages, exclude_common_words)
        if not use_facebook_names:
            filtered_first_names = basic_first_names
        if not use_facebook_surnames:
            filtered_surnames = basic_surnames

    print(f"   [INFO] Final counts: {len(filtered_first_names)} first names, "
          f"{len(filtered_surnames)} surnames")
    if use_facebook_names:
        print(f"   [REMOVED] {len(all_first_names) - len(filtered_first_names)} common first names")
    if use_facebook_surnames:
        print(f"   [REMOVED] {len(all_surnames) - len(filtered_surnames)} common surnames")

    return filtered_first_names, filtered_surnames

#: Names shorter than this are dropped from the Facebook-derived name sets
#: by :func:`filter_problematic_names`. Those sets hold hundreds of
#: thousands of scraped entries, and their one- and two-letter "names" are
#: mostly initials and ordinary tokens. TODO: justify (source unknown) the
#: value of three.
MIN_FACEBOOK_NAME_LENGTH = 3


def filter_problematic_names(names, drop_short=True):
    """Remove names that coincide with common English words.

    Args:
        names: a set of lower-case names.
        drop_short: also remove names shorter than
            :data:`MIN_FACEBOOK_NAME_LENGTH`. The Facebook-derived sets
            are filtered this way. The curated dictionary is not
            (:func:`create_multilingual_curated_names` passes ``False``):
            its short entries, the Chinese surnames Li, Wu, Xu, Hu, Yu and
            Lu and the English names Al, Ed and Jo among them, were each
            listed on purpose, and dropping them left those names unmasked
            without a log row (audit finding T1-07).

    Returns:
        A new set without the common English words listed below (so that
        "Will", "Mark" or "May" in running text are not masked) and, with
        *drop_short*, without the short names.
    """

    # List of common English words that should not be masked
    common_words = {
        # Colours
        'red', 'blue', 'green', 'yellow', 'orange', 'purple', 'pink', 'brown', 'black', 'white',
        'grey', 'gray',
        'violet', 'rose', 'lily', 'amber', 'jade', 'ruby', 'pearl', 'ivory', 'silver', 'golden',

        # Months/Time
        'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september',
        'october', 'november', 'december',
        'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
        'morning', 'evening', 'dawn', 'dusk',

        # Common verbs/actions
        'will', 'can', 'might', 'shall', 'should', 'would', 'could',
        'go', 'come', 'run', 'walk', 'talk', 'see', 'hear', 'feel', 'think',
        'hope', 'wish', 'want', 'need', 'have', 'get', 'make', 'take', 'give',
        'work', 'play', 'read', 'write', 'draw', 'paint', 'sing', 'dance',

        # Common nouns
        'house', 'home', 'car', 'book', 'phone', 'computer', 'table', 'chair', 'door', 'window',
        'water', 'food', 'money', 'time', 'day', 'night', 'week', 'month', 'year',
        'man', 'woman', 'child', 'person', 'people', 'family', 'friend',
        'school', 'job', 'office', 'shop', 'store', 'market',
        'hill', 'valley', 'river', 'lake', 'sea', 'ocean', 'mountain', 'forest', 'field',
        'stone', 'rock', 'wood', 'tree', 'flower', 'grass', 'leaf',

        # Common adjectives
        'good', 'bad', 'big', 'small', 'long', 'short', 'tall', 'wide', 'narrow',
        'hot', 'cold', 'warm', 'cool', 'dry', 'wet', 'clean', 'dirty',
        'new', 'old', 'young', 'fast', 'slow', 'hard', 'soft', 'strong', 'weak',
        'happy', 'sad', 'angry', 'calm', 'quiet', 'loud', 'bright', 'dark',
        'rich', 'poor', 'free', 'busy', 'easy', 'simple', 'difficult',

        # Occupations/Titles
        'doctor', 'nurse', 'teacher', 'student', 'worker', 'manager', 'director',
        'cook', 'baker', 'farmer', 'driver', 'pilot', 'captain', 'judge',
        'artist', 'writer', 'singer', 'actor', 'player', 'hunter', 'fisher',
        'mason', 'taylor', 'turner', 'walker', 'parker', 'porter', 'carter',

        # Geographic/Place terms
        'north', 'south', 'east', 'west', 'center', 'middle', 'top', 'bottom',
        'city', 'town', 'village', 'country', 'state', 'place', 'area', 'region',
        'street', 'road', 'avenue', 'lane', 'way', 'path', 'bridge', 'park',
        'church', 'temple', 'hall', 'tower', 'castle', 'palace',
        'island', 'beach', 'shore', 'coast', 'port', 'bay', 'gulf',

        # Animals
        'cat', 'dog', 'bird', 'fish', 'horse', 'cow', 'pig', 'sheep', 'goat',
        'lion', 'tiger', 'bear', 'wolf', 'fox', 'deer', 'rabbit', 'mouse',
        'bee', 'ant', 'fly', 'spider', 'snake', 'frog', 'duck', 'swan',

        # Body parts
        'head', 'face', 'eye', 'ear', 'nose', 'mouth', 'hand', 'foot', 'arm', 'leg',
        'heart', 'brain', 'bone', 'skin', 'hair', 'nail',

        # Common words that are often names
        'angel', 'joy', 'grace', 'faith', 'charity', 'patience', 'mercy',
        'peace', 'love', 'dream', 'star', 'moon', 'sun', 'sky',
        'rain', 'snow', 'wind', 'storm', 'thunder', 'lightning',

        # Misc common words
        'name', 'names', 'word', 'letter', 'number', 'page', 'line', 'text',
        'picture', 'image', 'photo', 'video', 'music', 'song', 'sound', 'voice',
        'game', 'sport', 'team', 'winner', 'loser', 'score', 'point',
        'question', 'answer', 'problem', 'solution', 'idea', 'plan', 'goal',
        'start', 'end', 'begin', 'finish', 'stop', 'pause', 'continue',
        'yes', 'no', 'maybe', 'never', 'always', 'sometimes', 'often', 'rarely',

        # Single letters that might be names
        'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
        'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',

        # Common conversation words
        'the', 'okay', 'yeah', 'well', 'but', 'move', 'thank', 'thanks', 'please',
        'sorry', 'excuse', 'hello', 'hi', 'bye', 'goodbye', 'welcome', 'congrats',
        'um', 'uh', 'oh', 'ah', 'hmm', 'wow', 'great', 'nice', 'fine', 'sure',
        'actually', 'really', 'basically', 'obviously', 'definitely', 'probably',
        'perhaps', 'anyway', 'however', 'therefore', 'because', 'since',
        'although', 'though', 'unless', 'until', 'while', 'during', 'before', 'after',

        # Additional problematic words
        'whale', 'whales', 'look', 'let', 'lets', 'every', 'put', 'nor', 'did', 'wave',
        'wait', 'mummy', 'baby', 'lots', 'lovely', 'say', 'painting', 'shower', 'nowhere',
        'pardon', 'breakfast', 'bible', 'wayo', 'shovel', 'shadows', 'meow', 'noy',

        # Question words and pronouns
        'what', 'who', 'when', 'where', 'why', 'how', 'which', 'whose',
        'he', 'she', 'it', 'they', 'we', 'you', 'me', 'him', 'her', 'them', 'us',
        'this', 'that', 'these', 'those', 'here', 'there', 'now', 'then',
        'some', 'any', 'all', 'each', 'many', 'much', 'few', 'little',

        # Prepositions and conjunctions
        'in', 'on', 'at', 'by', 'for', 'with', 'without', 'to', 'from', 'of',
        'about', 'above', 'below', 'under', 'over', 'through', 'between', 'among',
        'and', 'or', 'so', 'if', 'as', 'than', 'like', 'unlike',

        # Common verbs that might appear as names
        'do', 'does', 'be', 'am', 'is', 'are', 'was', 'were', 'been', 'being',
        'has', 'had', 'having', 'got', 'getting', 'putting',
        'said', 'saying', 'tell', 'told', 'telling', 'ask', 'asked', 'asking',
        'know', 'knew', 'known', 'knowing', 'thought', 'thinking',
        'looked', 'looking', 'seem', 'seemed', 'seeming', 'try', 'tried', 'trying',

        # Common contractions (without apostrophes since they're stripped in processing)
        'hes', 'shes', 'its', 'thats', 'whats', 'wheres', 'theres', 'youre', 'theyre',
        'werent', 'cant', 'dont', 'wont', 'isnt', 'arent', 'wasnt', 'havent', 'hasnt', 'hadnt',
        'ill', 'youll', 'hell', 'shell', 'theyll', 'ive', 'youve', 'weve', 'theyve',
        'id', 'youd', 'hed', 'shed', 'wed', 'theyd', 'heres',

        # Numbers and quantities
        'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
        'first', 'second', 'third', 'fourth', 'fifth', 'last', 'next', 'another',
        'more', 'most', 'less', 'least', 'enough', 'too', 'very', 'quite', 'rather',

        # Technology and modern words
        'app', 'web', 'site', 'email', 'call', 'chat', 'post', 'share',
        'click', 'tap', 'swipe', 'scroll', 'zoom', 'search', 'find', 'save', 'delete',
        'update', 'download', 'upload', 'install', 'connect', 'wifi', 'internet',

        # Business and finance
        'buy', 'sell', 'pay', 'cost', 'price', 'cheap', 'expensive', 'sale',
        'deal', 'offer', 'discount', 'tax', 'fee', 'bill', 'check', 'cash', 'card',
        'bank', 'account', 'loan', 'debt', 'invest', 'profit', 'loss', 'budget'
    }

    # Two curated short names are also ordinary English tokens, and the
    # capitalisation gate cannot tell them apart from the names: the
    # article "an" (capitalised at a sentence start) and the acronym "AI",
    # which occurs twelve times in the case-study transcript
    # (output/case_study/ep05_raw_text.txt). They were masked by accident
    # of the length filter until the curated names were exempted from it.
    common_words |= {'an', 'ai'}

    # Remove problematic names
    filtered = names - common_words

    if drop_short:
        filtered = {name for name in filtered
                    if len(name) >= MIN_FACEBOOK_NAME_LENGTH}

    return filtered

#: The curated name dictionary. Resolved against this script, not the
#: working directory, so the masker finds it wherever it is launched from.
CURATED_NAMES_CSV = Path(__file__).resolve().parent / 'data' / 'curated_names.csv'


def _read_curated_names_rows(csv_path=None):
    """Return the curated CSV as ``(name, type, language)`` lower-case triples.

    Raises:
        FileNotFoundError: the CSV is absent, for example when this script
            was copied without ``data/``.
        RuntimeError: the CSV exists but cannot be read or lacks the
            ``name``, ``type`` and ``language`` columns.

    A missing or unreadable dictionary used to yield two empty sets, so a
    run labelled as masked passed every name through verbatim. Failing
    here is the only way that run cannot look successful.
    """
    csv_path = Path(csv_path) if csv_path is not None else CURATED_NAMES_CSV
    if not csv_path.exists():
        raise FileNotFoundError(
            f"The curated name dictionary was not found at {csv_path}. Name "
            f"masking cannot run without it; restore data/curated_names.csv "
            f"next to transcription.py.")
    try:
        with open(csv_path, encoding='utf-8') as f:
            return [(row['name'].strip().lower(),
                     row['type'].strip().lower(),
                     row['language'].strip().lower())
                    for row in csv.DictReader(f)]
    except (OSError, UnicodeDecodeError, csv.Error, KeyError,
            AttributeError) as exc:
        raise RuntimeError(
            f"The curated name dictionary at {csv_path} could not be read "
            f"({type(exc).__name__}: {exc}). It must be UTF-8 CSV with the "
            f"columns name, type and language.") from exc


def curated_name_languages(csv_path=None):
    """Return the sorted distinct languages present in the curated CSV.

    This is the single source of the language list: the masker's default,
    the validation of ``--languages-for-name-masking`` and its help text
    all read it, so a language added to the CSV is picked up everywhere.
    Raises as :func:`_read_curated_names_rows` does.
    """
    return sorted({lang for _, _, lang in _read_curated_names_rows(csv_path)
                   if lang})


def normalise_name_languages(selected_languages, available):
    """Validate a requested language list against *available*.

    Args:
        selected_languages: the caller's list, or ``None`` for every
            available language. Values are stripped and lower-cased, so
            ``English`` selects ``english``; lower-case input is unchanged.
        available: the languages the CSV actually contains.

    Returns:
        A list of languages in request order, without duplicates.

    Raises:
        ValueError: the list is empty or names a language the CSV does not
            contain. Either used to load no names at all and mask nothing
            while the transcript header still claimed masking.
    """
    if selected_languages is None:
        return list(available)
    requested = []
    for value in selected_languages:
        lang = str(value).strip().lower()
        if lang and lang not in requested:
            requested.append(lang)
    if not requested:
        raise ValueError(
            "No language was given for the name dictionary. Choose from: "
            + ", ".join(available) + ".")
    unknown = [lang for lang in requested if lang not in available]
    if unknown:
        raise ValueError(
            "The name dictionary has no entries for: " + ", ".join(unknown)
            + ". Choose from: " + ", ".join(available)
            + " (full language names, not ISO codes).")
    return requested


def create_multilingual_curated_names(selected_languages=None, exclude_common_words=True,
                                      csv_path=None):
    """Create a multilingual curated names database from CSV file.

    Loads names from data/curated_names.csv which contains columns:
    - name: The personal name
    - type: Either 'first' or 'last' (surname)
    - language: Full lower-case language name (see :func:`curated_name_languages`)

    Args:
        selected_languages (list): Languages to include, case-insensitive.
                                 If None, includes every language in the CSV.
        exclude_common_words (bool): Remove names that are also common
                                 English words (:func:`filter_problematic_names`).
        csv_path: Override for the CSV location, for tests.

    Returns:
        tuple: (first_names_set, surnames_set) with combined names from selected languages

    Raises:
        FileNotFoundError, RuntimeError: the CSV is missing or unreadable.
        ValueError: the language list is empty or names an unknown language.
    """
    rows = _read_curated_names_rows(csv_path)
    available = sorted({lang for _, _, lang in rows if lang})
    selected_languages = normalise_name_languages(selected_languages, available)

    print("   [DATABASE] Loading multilingual curated names from CSV")
    print(f"   [LANGUAGES] Selected: {', '.join(selected_languages)}")

    # Load names from CSV and organise by language and type
    language_stats = {lang: {'first': 0, 'last': 0} for lang in selected_languages}
    all_first_names = set()
    all_surnames = set()

    for name, name_type, language in rows:
        # Only include names from selected languages
        if language not in language_stats:
            continue

        if name_type == 'first':
            all_first_names.add(name)
            language_stats[language]['first'] += 1
        elif name_type == 'last':
            all_surnames.add(name)
            language_stats[language]['last'] += 1

    # Report statistics by language
    for lang in selected_languages:
        stats = language_stats[lang]
        print(f"   [LOADED] {lang.title()}: {stats['first']} first names, {stats['last']} surnames")

    print(f"   [SUCCESS] CSV database loaded: {len(all_first_names)} first names, "
          f"{len(all_surnames)} surnames")

    # Conditionally filter out common English words to prevent false
    # positives. The length filter is for the scraped Facebook sets only;
    # every curated name was listed deliberately (audit finding T1-07).
    if exclude_common_words:
        print("   [FILTERING] Removing common English words from curated database...")
        filtered_first_names = filter_problematic_names(all_first_names,
                                                        drop_short=False)
        filtered_surnames = filter_problematic_names(all_surnames,
                                                     drop_short=False)

        removed_first = len(all_first_names) - len(filtered_first_names)
        removed_last = len(all_surnames) - len(filtered_surnames)

        if removed_first > 0 or removed_last > 0:
            print(f"   [REMOVED] {removed_first} common first names, "
                  f"{removed_last} common surnames")

        print(f"   [FINAL] {len(filtered_first_names)} first names, "
              f"{len(filtered_surnames)} surnames after filtering")

        return filtered_first_names, filtered_surnames
    else:
        print("   [INFO] Common word filtering disabled - using full curated database")
        return all_first_names, all_surnames


#: Honorifics the masker rewrites to ``[TITLE]`` when a dictionary name
#: follows. Exported so that evaluation/benchmark_masking.py, which keeps a
#: copy (_TITLE_WORDS) to exclude these redactions from its precision
#: denominator, can import it instead; an honorific added here and not
#: there would silently lower the reported precision.
TITLE_WORDS = frozenset({'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor',
                         'sir', 'madam', 'lord', 'lady'})

#: The honorifics in TITLE_WORDS that are abbreviations, and so are often
#: written with a full stop ("Dr.", "Mrs."). The full words are left out
#: because a sentence often ends on one ("Yes, sir."), and the sentence
#: after it must not be read as the name it introduces.
_ABBREVIATED_TITLES = frozenset({'mr', 'mrs', 'ms', 'dr', 'prof'})

#: Text ending in one of those abbreviations and a single full stop, the
#: abbreviation standing as its own token after any opening punctuation.
#: "Mr.", "Mrs.", "Dr." and "Prof." match in any case, so a transcript that
#: writes "dr. Smith" keeps its honorific with its name. "Ms." matches only
#: as written, capital M and lower-case s, because a lower-case "ms." is the
#: unit and "MS." the disease: a sentence ending "200 ms." or "diagnosed
#: with MS." must not be joined to the next one, whose first name the
#: honorific rule would then mask as "[TITLE] [NAME]".
_ABBREVIATED_TITLE_END_RE = re.compile(
    r'(?:^|\s)\W*(?:(?i:'
    + '|'.join(sorted(_ABBREVIATED_TITLES - {'ms'}))
    + r')|Ms)\.$')


def _is_title_token(token, clean_word):
    """Return whether *token* is an honorific the title rule may mask.

    The rule then masks it only when the next word is a dictionary name,
    so a name found by the NER stage alone keeps its title
    ("Dr Yusuf" becomes "Dr [NAME]"; 40 title-position held-out rows of
    the committed NER arm, 92 of its case-insensitive variant).

    *clean_word* is the token lower-cased with its punctuation and any
    possessive clitic removed, as the masker computes it. Most honorifics
    count in any case. Two are ordinary words in another spelling: "miss"
    is the verb ("I miss Sarah") and "ms" the unit ("200 ms"), or in
    capitals the disease ("MS"). They count only when spelt as the
    honorific is, "Miss" with an initial capital and "Ms" exactly, whatever
    ``case_insensitive`` says, since that option relaxes the gate on names
    and not on what a title is. Before this test the masker read every
    "miss" or "ms" in front of a name as a title, so "I miss Sarah a lot."
    became "I [TITLE] [NAME] a lot.".
    """
    if clean_word not in TITLE_WORDS:
        return False
    if clean_word == 'ms':
        return re.sub(r'\W', '', re.sub(r"['’]s?(?=\W*$)", '', token)) == 'Ms'
    if clean_word == 'miss':
        return _token_is_capitalised(token)
    return True


def _split_sentences_for_masking(text):
    """Split *text* into the sentences the name masker reads one at a time.

    The split falls after each full stop, question mark or exclamation
    mark. On its own that ended a sentence at "Dr." and began the next at
    the name, and the honorific rule, which looks for a name in the next
    word of the same sentence, then left "Dr." unmasked before
    "[NAME] [SURNAME]" (audit finding NEW-09). A piece that ends in an
    abbreviated title is therefore joined to the piece after it.
    """
    sentences = []
    for piece in re.split(r'(?<=[.!?])\s+', text):
        if sentences and _ABBREVIATED_TITLE_END_RE.search(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)
    return sentences


def _token_is_capitalised(token):
    """Return whether *token*'s core begins with an upper-case character.

    The core is the token with leading and trailing non-word characters
    removed, so '"Sarah,' and '(John)' are judged by their own first
    letter. Testing the raw first character, as the masker once did, let
    every name that opens a quotation or parenthesis through unmasked,
    because a quote or bracket is never upper-case. For a token that begins
    with a word character the result is identical to ``token[0].isupper()``.
    """
    core = re.sub(r'^\W+|\W+$', '', token)
    return core[:1].isupper()


#: A masked token split into leading punctuation, the name itself, an
#: optional possessive clitic ("'s", "’s" or a bare apostrophe, as in
#: "James'") and trailing punctuation.
_MASKED_TOKEN_RE = re.compile(r"(\W*)(.*?)(['’]s?)?(\W*)", re.DOTALL)


def _wrap_placeholder(token, placeholder):
    """Return *placeholder* in place of the name in *token*.

    Leading punctuation (an opening quote or bracket) stays in front of the
    placeholder and trailing punctuation after it, so the reader still sees
    the quotation or sentence as it was. A possessive clitic is kept as a
    suffix, so "Bernabeu's idea." becomes "[SURNAME]'s idea.". Punctuation
    inside the name ("O'Brien") is part of the name and is replaced with
    it.

    Earlier versions appended every non-word character of the token after
    the placeholder, which turned "Sarah's" into "[NAME]'" and "O'Brien"
    into "[SURNAME]'" (audit finding T1-03). Scoring code that compares a
    token with a bare placeholder must now remove a trailing clitic as
    well as punctuation (see evaluation/benchmark_masking._strip_marker).

    Args:
        token: one whitespace-delimited word of the transcript.
        placeholder: the replacement, such as ``[NAME]``.

    Returns:
        The replacement token.
    """
    leading, _name, clitic, trailing = _MASKED_TOKEN_RE.fullmatch(token).groups()
    return leading + placeholder + (clitic or '') + trailing


def create_enhanced_name_masker(use_facebook_names=False, use_facebook_surnames=False,
                                selected_languages=None, exclude_common_words=True,
                                excluded_names=None, case_insensitive=False, ner_detector=None):
    """Create enhanced name masking with global database and logging.

    Args:
        use_facebook_names (bool): If True, use Facebook's global first names database.
                                 If False, use curated multilingual first names only.
        use_facebook_surnames (bool): If True, use Facebook's global surnames database.
                                    If False, use curated multilingual surnames only.
        selected_languages (list): Languages to include in curated database,
                                 case-insensitive; None means every language
                                 in the CSV. An empty or unknown list raises
                                 ValueError (see normalise_name_languages).
        exclude_common_words (bool): If True, filter out common English words from name database.
                                    Default: True (recommended for English transcripts).
        excluded_names (set): Set of names (case-insensitive) to exclude from masking.
                            Useful for preserving public figures, celebrities,
                            or specific participants.
        ner_detector: Optional second stage with a ``tokens_in(text)`` method
                            (see ``ner_masking.PersonNameDetector``) that
                            recognises people by context rather than by
                            dictionary membership. It addresses the
                            dictionary's measured limit, that recall on names
                            it has never seen is zero. It is purely additive:
                            it proposes further words to mask and can never
                            unmask a dictionary hit, so enabling it may raise
                            recall and may cost precision, and each masking-log
                            row records which stage was responsible. A
                            sentence it fails on is masked by the dictionary
                            alone. ner_masking.PersonNameDetector counts a
                            failure of its model (``n_failures``) and reports
                            the first on stderr; any other exception that
                            ``tokens_in`` raises is counted here in the same
                            ``n_failures`` (and ``first_error``) when the
                            detector has them, and the first is reported on
                            stderr, so a benchmark that checks the count
                            sees every sentence the stage did not read.
        case_insensitive (bool): Drop the capitalisation requirement, for
                            both stages and for the name after an honorific,
                            so a lower-case dictionary match is masked too;
                            the benchmark measures the precision this costs.
                            It does not make a lower-case "miss" or "ms" an
                            honorific (see _is_title_token).

    Returns:
        ``(mask, get_log)``. ``mask(text, filename="unknown")`` returns the
        masked text; ``get_log()`` returns the rows (see
        :data:`REPLACEMENT_LOG_FIELDS`) of the most recent ``mask`` call
        only, because each call resets the log.

    Raises:
        FileNotFoundError, RuntimeError, ValueError: the dictionary cannot
        be loaded, the language list is empty or unknown, or no name is
        left after exclusions.
    """

    print("   Loading global name database...")
    first_names, surnames = load_global_names(use_facebook_names, use_facebook_surnames,
                                              selected_languages, exclude_common_words)

    # Apply excluded names (case-insensitive)
    if excluded_names:
        excluded_names_lower = {name.lower() for name in excluded_names}
        first_names = {name for name in first_names if name.lower() not in excluded_names_lower}
        surnames = {name for name in surnames if name.lower() not in excluded_names_lower}
        print(f"   ℹ️  Excluding {len(excluded_names)} name(s) from masking")

    # An empty dictionary masks nothing while every header still says names
    # were masked, so it is refused rather than returned as a working masker.
    if not first_names and not surnames:
        raise ValueError(
            "Name masking was requested but the name dictionary is empty "
            "after loading and exclusions, so no name would be masked.")

    titles = TITLE_WORDS

    replacement_log = []
    # Whether this masker has reported an exception of the NER stage on
    # stderr, so that a detector without a first_error attribute is
    # reported once and not once per sentence.
    ner_failure_reported = [False]

    def mask_names_with_logging(text, filename="unknown"):
        """Enhanced name masking function with detailed logging."""
        nonlocal replacement_log
        replacement_log = []  # Reset for new file

        sentences = _split_sentences_for_masking(text)
        masked_sentences = []
        replacement_counter = 1

        for sentence in sentences:
            if not sentence.strip():
                masked_sentences.append(sentence)
                continue

            words = sentence.split()
            masked_words = []

            # Ask the optional second stage which words this sentence's
            # context reads as personal names. It runs per sentence rather
            # than per word because a NER model needs the surrounding words
            # to tell a name from an ordinary noun, and per document because
            # that would cost more memory than a long recording can spare.
            ner_tokens = set()
            if ner_detector is not None:
                try:
                    ner_tokens = ner_detector.tokens_in(sentence)
                except Exception as exc:  # never fatal, but counted
                    # An exception after the model call (a malformed entity
                    # whose score does not compare with the threshold, or a
                    # detector of another kind) is counted with the
                    # detector's model failures, so that
                    # benchmark_masking._check_ner_ran sees it, and the
                    # first is reported on stderr as a model failure is
                    # (review finding SC-17). The sentence is masked by the
                    # dictionary alone, as after a model failure.
                    ner_tokens = set()
                    first = getattr(ner_detector, "first_error", None) is None
                    if hasattr(ner_detector, "n_failures"):
                        ner_detector.n_failures += 1
                        if first:
                            ner_detector.first_error = repr(exc)
                    if first and not ner_failure_reported[0]:
                        ner_failure_reported[0] = True
                        print(f"   ⚠️  NER stage failed ({type(exc).__name__}: "
                              f"{exc}); those sentences fall back to the name "
                              "dictionary alone", file=sys.stderr)

            for word_idx, word in enumerate(words):
                original_word = word
                # Strip a trailing possessive clitic ("'s", "'", and curly
                # variants) before the dictionary lookup so that "Bernabeu's"
                # matches the name "Bernabeu". The clitic may be followed by
                # closing punctuation ("It was Sarah's."), which is why the
                # anchor tolerates trailing non-word characters. Internal
                # apostrophes (O'Brien, D'Angelo) are still preserved.
                stem = re.sub(r"['’]s?(?=\W*$)", "", word.lower())
                clean_word = re.sub(r'[^\w]', '', stem)

                # Skip if empty after cleaning
                if not clean_word:
                    masked_words.append(word)
                    continue

                # Check if word is capitalised. The test reads the token's
                # core, so a name opening a quotation or parenthesis
                # ('"Sarah,', '(John)') is judged by its own first letter,
                # not by the quote in front of it.
                is_capitalized = _token_is_capitalised(word)

                # Dictionary membership. Sentence position plays no part:
                # a sentence-initial "Will" is protected only because the
                # common-word filter removed it from the dictionary.
                is_first_name = clean_word in first_names
                is_surname = clean_word in surnames
                is_title = _is_title_token(word, clean_word)

                # Mask when the token is capitalised and in the dictionary.
                # The capitalisation requirement is the masker's main recall
                # limiter (lower-cased names leak). case_insensitive=True relaxes
                # it to mask any dictionary match regardless of case, trading
                # recall for precision; the benchmark quantifies that trade-off.
                should_mask = (is_capitalized or case_insensitive) and (is_first_name or is_surname)

                # The optional NER stage supplies what a list cannot: names
                # it has never seen. It is consulted only when the
                # dictionary has not already decided to mask, so it can add
                # redactions but never remove one, and the source is
                # recorded below so an auditor can separate the two stages.
                # A NER model returns the whole person span, so "Doctor
                # Kowalczyk" yields "doctor" alongside the name. Titles are
                # handled by their own branch below, which emits [TITLE],
                # and masking them here as names would be both a false
                # positive and a worse label, so they are excluded.
                #
                # The stage is also held to the same capitalisation gate as
                # the dictionary, for a measured reason. The model finds
                # person *references*, not person *names*, so on a
                # transcript that discusses people it proposes "speaker
                # one", "the researcher", "the user" and even "we". On the
                # case-study transcript that was 15 further redactions,
                # every one a false positive, beside the dictionary's 3, of
                # which 2 were true names (the third was "Jordan", in a
                # speaker's example of a masker taking the country for a
                # person). Those references are lower-case and real
                # names are capitalised, so this gate removes them at the
                # cost of lower-case names, which is the same trade the
                # dictionary makes and which case_insensitive relaxes for
                # both stages together.
                is_ner_person = (bool(ner_tokens)
                                 and (is_capitalized or case_insensitive)
                                 and clean_word in ner_tokens
                                 and clean_word not in titles)
                masked_by = "dictionary" if should_mask else None
                if not should_mask and is_ner_person:
                    should_mask = True
                    masked_by = "ner"

                # Check for title + name combinations. The next word is held
                # to the same capitalisation gate as any name, which
                # case_insensitive relaxes here too: "Dr. smith" under that
                # option once gave "Dr. [SURNAME]", the name masked by the
                # dictionary branch and the title kept.
                if is_title and word_idx + 1 < len(words):
                    # The form the name lookup uses, possessive clitic
                    # removed, so "Dr. Smith's" loses its title as well
                    # (review finding CR-02).
                    next_word = re.sub(r'[^\w]', '', re.sub(
                        r"['’]s?(?=\W*$)", "", words[word_idx + 1].lower()))
                    next_is_capitalized = _token_is_capitalised(words[word_idx + 1])
                    if ((next_is_capitalized or case_insensitive)
                            and (next_word in first_names or next_word in surnames)):
                        # Log the title
                        replacement_log.append({
                            'order': replacement_counter,
                            'original': original_word,
                            'replacement': '[TITLE]',
                            'context_sentence': sentence.strip(),
                            'filename': filename,
                            # Titles are masked by the honorific rule, not by
                            # either name stage, and every log row states
                            # which rule was responsible.
                            'source': 'title',
                        })
                        replacement_counter += 1
                        # The full stop of "Dr." belongs to the title, not
                        # to the sentence, so it is replaced with it:
                        # "[TITLE]. [SURNAME]" would read as two sentences.
                        title_token = (word[:-1] if _ABBREVIATED_TITLE_END_RE.search(word)
                                       else word)
                        masked_words.append(_wrap_placeholder(title_token, '[TITLE]'))
                        continue

                # Process names (requires capitalisation + database match)
                if should_mask:
                    # Choose appropriate replacement based on name type.
                    # A NER find carries no first-name/surname distinction,
                    # so it uses the generic placeholder.
                    if is_surname and masked_by == "dictionary":
                        replacement = _wrap_placeholder(word, '[SURNAME]')
                    else:
                        replacement = _wrap_placeholder(word, '[NAME]')

                    # Log the replacement, recording which stage found it so
                    # that the two can be audited and measured separately.
                    replacement_log.append({
                        'order': replacement_counter,
                        'original': original_word,
                        'replacement': replacement,
                        'context_sentence': sentence.strip(),
                        'filename': filename,
                        'source': masked_by or 'dictionary'
                    })
                    replacement_counter += 1

                    masked_words.append(replacement)
                else:
                    masked_words.append(word)

            masked_sentences.append(' '.join(masked_words))

        return ' '.join(masked_sentences)

    def get_replacement_log():
        """Get the current replacement log."""
        return replacement_log

    return mask_names_with_logging, get_replacement_log

#: Columns of a name-masking log. ``source`` records which rule masked the
#: token (``dictionary``, ``ner`` or ``title``), so the two name stages can
#: be audited separately. It is appended last so that readers that address
#: columns by name, such as ``evaluation/audit_artefacts.py``, keep working
#: on logs written before the column existed.
REPLACEMENT_LOG_FIELDS = ('filename', 'order', 'original', 'replacement',
                          'context_sentence', 'source')


def save_replacement_log(replacement_log, filename):
    """Write a masking log to ``name_masking_logs/name_replacements_<stem>.csv``.

    Args:
        replacement_log: rows from the masker's ``get_replacement_log``, one
            dict per masked token with the keys in
            :data:`REPLACEMENT_LOG_FIELDS`.
        filename: the recording's file name; only its stem names the log.

    Returns:
        ``None``. Nothing is written when *replacement_log* is empty.

    Side effects:
        Creates ``name_masking_logs/`` relative to the current working
        directory (like ``output/``, not relative to this script), and
        overwrites any earlier log for a recording with the same stem, as
        the transcripts under ``output/transcripts`` are overwritten. The
        CSV is written to a temporary file and renamed into place, so a
        failure part-way leaves no truncated log for an audit to trust.
    """
    if not replacement_log:
        return

    logs_dir = Path("name_masking_logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(filename).stem
    log_file = logs_dir / f"name_replacements_{base_name}.csv"
    tmp_file = log_file.with_name(log_file.name + ".tmp")

    try:
        with open(tmp_file, 'w', newline='', encoding='utf-8') as csvfile:
            # extrasaction stays at its 'raise' default: a row carrying a key
            # this header does not know is a schema drift that should fail
            # loudly, as the 'source' column once did, not be dropped.
            writer = csv.DictWriter(csvfile, fieldnames=REPLACEMENT_LOG_FIELDS)
            writer.writeheader()
            for entry in replacement_log:
                writer.writerow(entry)
        os.replace(tmp_file, log_file)
    finally:
        if tmp_file.exists():
            tmp_file.unlink()

    print(f"   📝 Name replacement log saved: {log_file}")
    print(f"   📊 Total replacements: {len(replacement_log)}")

#: Characters that only ever occur in emoji, removed with any zero-width
#: joiner that binds them into a sequence. Listed block by block because
#: the single class this replaced, U+24C2 to U+1F251, ran straight through
#: the CJK, kana, Hangul, Yi and Arabic presentation-form blocks and so
#: deleted whole scripts from Chinese, Japanese and Korean transcripts
#: (audit finding T1-02).
_EMOJI_CHARS = (
    "\U0001F000-\U0001FAFF"  # mahjong to pictographs extended-A, flags, skin tones
    "\U00002600-\U000027BF"  # miscellaneous symbols and dingbats
    "\U00002B00-\U00002BFF"  # miscellaneous symbols and arrows
    "\U000024C2"             # circled M, the one emoji in enclosed alphanumerics
    "\U0000FE0E\U0000FE0F"   # text and emoji presentation selectors
    "\U000020E3"             # combining enclosing keycap
    "\U000E0020-\U000E007F"  # tag characters of subdivision flags
)
_ZWJ = "\U0000200D"
_EMOJI_RE = re.compile(
    f"{_ZWJ}?[{_EMOJI_CHARS}]+(?:{_ZWJ}+[{_EMOJI_CHARS}]+)*{_ZWJ}?")

#: Typographic quotation marks mapped to their ASCII forms. Deleting them,
#: as the stage once did, fused "It’s" into "Its" and "l’homme" into
#: "lhomme"; the ASCII apostrophe is what the rest of the pipeline and the
#: WER normaliser expect.
_TYPOGRAPHIC_QUOTES = str.maketrans({
    "\U00002018": "'", "\U00002019": "'", "\U0000201A": "'", "\U0000201B": "'",
    "\U0000201C": '"', "\U0000201D": '"', "\U0000201E": '"', "\U0000201F": '"',
})

#: Unicode general categories removed beyond ASCII: other and modifier
#: symbols (where emoji and pictographic artefacts live), and the control,
#: format, surrogate, private-use and unassigned codepoints. Letters,
#: marks, digits of every script, punctuation, spaces and the currency and
#: mathematical symbols are orthographic content and are kept.
_ARTEFACT_CATEGORIES = frozenset({"So", "Sk", "Cc", "Cf", "Cs", "Co", "Cn"})

#: Symbols in a removed category that are nevertheless ordinary text. The
#: degree sign is category So, and "20°C" should not become "20C".
_KEPT_SYMBOLS = frozenset({"\U000000B0"})

#: Zero-width (non-)joiners are format characters, but between two letters
#: they are part of the spelling in Persian and the Indic scripts, so they
#: are kept there and removed elsewhere.
_JOINERS = frozenset({"\U0000200C", _ZWJ})


def _is_letter_or_mark(ch):
    """Return whether *ch* is a letter or a combining mark of any script."""
    return unicodedata.category(ch)[0] in ("L", "M")


def remove_emojis_and_unicode_artifacts(text):
    """Remove emoji and Unicode artefacts from a transcription.

    Only emoji and characters in symbol or control categories are removed
    (:data:`_ARTEFACT_CATEGORIES`). Letters, combining marks and digits are
    kept whatever their script, so Chinese, Japanese, Korean, Arabic
    (presentation forms included), Devanagari and accented Latin text all
    pass through intact, as do punctuation such as ``¿``, ``«`` and ``…``
    and currency signs such as ``£`` and ``€``. Typographic quotation marks
    become their ASCII forms (:data:`_TYPOGRAPHIC_QUOTES`). ASCII input is
    returned with its whitespace collapsed and otherwise unchanged.

    An earlier version deleted every CJK, kana and Hangul character through
    an over-wide emoji range, dropped every non-ASCII digit, currency sign
    and punctuation mark, and removed isolated ASCII symbols such as the
    ``&`` in "rock & roll" (audit finding T1-02). That last step is gone:
    what it removed is now either kept as text or already removed by
    category, and the WER normaliser turns every such mark into a space,
    so its removal never affected a score.

    Args:
        text: the transcript.

    Returns:
        The cleaned text, stripped, with every run of whitespace (line
        breaks included) collapsed to one space.
    """
    # Step 1: map typographic quotes to ASCII, then remove emoji runs,
    # joiners inside emoji sequences included.
    text = text.translate(_TYPOGRAPHIC_QUOTES)
    text = _EMOJI_RE.sub('', text)

    # Step 2: remove the remaining artefacts by Unicode category. ASCII is
    # always kept, so English text is unchanged by this step.
    kept = []
    for i, ch in enumerate(text):
        if ord(ch) < 128 or ch in _KEPT_SYMBOLS:
            kept.append(ch)
        elif ch in _JOINERS:
            if (0 < i < len(text) - 1 and _is_letter_or_mark(text[i - 1])
                    and _is_letter_or_mark(text[i + 1])):
                kept.append(ch)
        elif unicodedata.category(ch) not in _ARTEFACT_CATEGORIES:
            kept.append(ch)
    text = ''.join(kept)

    # Step 3: collapse whitespace, including non-breaking and ideographic
    # spaces, which Python's \s matches.
    return re.sub(r'\s+', ' ', text).strip()

#: A 2-6 word phrase is cut only when it occurs more than this many times
#: *max_repetitions* in a row, a more lenient bar than for sentences and
#: single words, because short phrases ("thank you", "you know") are
#: repeated in genuine speech far more often than whole sentences are.
#: With the default *max_repetitions* of 5 a phrase loop is cut from its
#: eleventh occurrence. TODO: justify (source unknown) the factor of two.
PHRASE_REPETITION_LENIENCY = 2

#: A sentence repeated more than this many times in a row is followed by a
#: visible ``[...]`` once it is cut back to one copy, so a reader can tell
#: a decoding loop was removed; shorter runs above *max_repetitions* are
#: cut silently. TODO: justify (source unknown) the value of ten.
SENTENCE_LOOP_MARKER_ABOVE = 10

#: A 2-6 word phrase followed by at least four more occurrences of itself.
#: The phrase is matched lazily, so the shortest repeating unit is found:
#: with a greedy phrase an eleven-fold "thank you" loop was read as five
#: copies of "thank you thank you" and never reached the threshold.
_PHRASE_LOOP_RE = re.compile(r'(\b\w+(?:\s+\w+){1,5}?)\s*(?:\1\s*){4,}',
                             flags=re.IGNORECASE)


def detect_and_fix_repetitions(text, max_repetitions=5):
    """
    Enhanced repetition detection and fixing for AI-generated artefacts.
    Handles massive repetitive patterns that are clearly AI artefacts.
    This addresses patterns like 'I have this. I have this.' repeated 80+ times.

    Args:
        text: the transcript.
        max_repetitions: the most consecutive repeats kept as genuine
            speech. A sentence repeated more often is kept once (with
            ``[...]`` after it beyond :data:`SENTENCE_LOOP_MARKER_ABOVE`
            repeats); a 2-6 word phrase is cut to one copy followed by
            ``[...]`` when it occurs more than
            :data:`PHRASE_REPETITION_LENIENCY` times this many times in a
            row, counted without regard to case; and a word repeated more
            often is kept twice. No production caller changes it. TODO:
            justify (source unknown) the default of 5.

    Returns:
        The repaired text with whitespace collapsed to single spaces, or
        *text* unchanged if the repair would leave it empty.

    The phrase count was once computed as twice the number of copies plus
    one, so every phrase loop the pattern could see (five copies or more)
    was cut, and it was case-sensitive, so a loop whose first copy was
    capitalised was never cut at all (audit finding T1-05).
    """
    # Step 1: Detect and fix sentence-level repetitions (AI artefacts)
    # Pattern: Same sentence repeated many times
    sentences = re.split(r'(?<=[.!?])\s+', text)
    cleaned_sentences = []

    i = 0
    while i < len(sentences):
        current_sentence = sentences[i].strip()
        if not current_sentence:
            i += 1
            continue

        # Count consecutive identical sentences
        repetition_count = 1
        j = i + 1
        while j < len(sentences) and sentences[j].strip() == current_sentence:
            repetition_count += 1
            j += 1

        # If we find massive repetitions (more than max_repetitions), it's likely an AI artefact
        if repetition_count > max_repetitions:
            # Keep only one instance and add a note about the repetition
            cleaned_sentences.append(current_sentence)
            if repetition_count > SENTENCE_LOOP_MARKER_ABOVE:
                cleaned_sentences.append("[...]")
            i = j
        else:
            # Keep all instances of normal repetitions
            for _ in range(repetition_count):
                cleaned_sentences.append(current_sentence)
            i = j

    text = ' '.join(cleaned_sentences)

    # Step 2: Detect and fix phrase-level repetitions within sentences
    # Pattern: "word word word word" repeated many times within a sentence
    def fix_phrase_repetitions(match):
        full_match = match.group(0)
        repeated_phrase = match.group(1)

        # Count the copies directly, ignoring case as the pattern does.
        repetition_count = len(re.findall(re.escape(repeated_phrase),
                                          full_match, flags=re.IGNORECASE))

        if repetition_count > max_repetitions * PHRASE_REPETITION_LENIENCY:
            # Keep the whitespace the match consumed after the last copy,
            # so the next word is not glued to the marker.
            trailing = full_match[len(full_match.rstrip()):]
            return f"{repeated_phrase} [...]{trailing}"
        return full_match

    # Look for patterns like "phrase phrase phrase phrase"
    text = _PHRASE_LOOP_RE.sub(fix_phrase_repetitions, text)

    # Step 3: Remove excessive counting sequences that are causing the bug
    counting_pattern = r'(?:one\s+two\s+three\s+four\s+five\s+six\s+seven\s+eight\s+nine\s*){3,}'
    text = re.sub(counting_pattern, '[...]', text, flags=re.IGNORECASE)

    # Step 4: Remove excessive emoji repetitions
    text = re.sub(r'([^\w\s])\s*\1{5,}', r'\1\1\1', text)

    # Step 5: Clean up simple word repetitions more conservatively
    words = text.split()
    cleaned_words = []
    i = 0
    while i < len(words):
        word = words[i]
        count = 1

        # Count consecutive identical words
        while i + count < len(words) and words[i + count].lower() == word.lower():
            count += 1

        # Keep only reasonable number of repetitions
        if count > max_repetitions:
            cleaned_words.extend(words[i:i+2])  # Keep just 2 instances
        else:
            cleaned_words.extend(words[i:i+count])

        i += count

    result = ' '.join(cleaned_words)
    return result if result else text

# ---------------------------------------------------------------------------
# Atomic post-processing stages
# ---------------------------------------------------------------------------
# The eight helper functions below are the atomic stages that
# ``clean_transcription_text`` applies, in order, to a raw ASR
# hypothesis.  They are exposed at module scope so that the WER
# benchmark in ``evaluation/conditions.py`` can register each as an
# individually-named condition and so that ``tests/test_conditions.py``
# can verify their behaviour in isolation and as a composition.  The
# public ``clean_transcription_text`` function below is the in-order
# composition of these stages, preserving production behaviour
# byte-for-byte.

#: The four spellings of the "undefined" artefact the stage marks, as whole
#: words, unless already bracketed. Where the artefact comes from is not
#: recorded. The list dates from the repository's first commit (8d8c58e,
#: November 2025), which already marked these words in the transcription
#: text as "speech artifacts", and whose speaker-attribution module deleted
#: "excessive 'undefined' words" from it, so the token had been seen in the
#: workflow's Whisper output before any history was kept. No transcript or
#: hypothesis committed under output/ or example_output/ contains it.
#:
#: The manuscript lists the same four spellings, each marked as a whole
#: word unless already bracketed, and says an ordinary word that begins
#: with those letters, such as "undefinable", is left alone. A prefix
#: pattern such as ``\bundefin\w*``, which an earlier draft gave, would
#: rewrite that word into "[undefined]". The earlier implementation matched
#: the same four words but only between two runs of whitespace, so it
#: missed an occurrence at the start or end of the text, one before
#: punctuation ("the value was undefin.") and the second of two in a row
#: (audit finding T1-14).
_UNDEFINED_RE = re.compile(
    r'(?<!\[)\b(?:undefining|undefined|undefine|undefin)\b(?!\])',
    flags=re.IGNORECASE)


def _undefined_tag(text):
    """Mark ``undefin*`` speech artefacts as ``[undefined]``.

    Each whole-word ``undefined``, ``undefine``, ``undefin`` or
    ``undefining`` (any case) becomes ``[undefined]``, wherever it stands;
    surrounding whitespace is left alone. Idempotent: a bracketed token is
    not matched again. The real English word "undefined" is marked too,
    as it always has been.

    Args:
        text: the transcript.

    Returns:
        The text with the artefacts marked.
    """
    return _UNDEFINED_RE.sub('[undefined]', text)


#: The non-lexical fillers this workflow recognises. Deliberately narrow:
#: every entry is a hesitation sound with no lexical reading in English, so
#: bracketing or counting one cannot swallow a real word. "Oh" and "well"
#: are excluded for that reason, being ordinary words as often as fillers.
#: Exported because the disfluency benchmark scores what the pipeline calls
#: a filler, and a second list would drift from this one.
FILLER_TOKENS = ("um", "uh", "er", "ah", "hmm", "mm", "mhm", "uhuh", "uhhuh")

#: Hyphenated backchannels, bracketed whole before single fillers are.
#: TODO: justify (source unknown) the choice of these four; they are the
#: forms the audit found half-bracketed.
BACKCHANNEL_TOKENS = ("uh-huh", "mm-hmm", "uh-uh", "mm-mm")

# The boundaries below replace \b. A filler must not touch a word
# character, an opening or closing bracket (so a second pass leaves a
# bracketed filler alone), or an apostrophe, and must not be joined by a
# hyphen to a word on either side. The apostrophe guard stops "o'er" and
# "e'er" becoming "o'[er]" and "e'[er]" (audit finding EWER-03); the
# hyphen guard stops a compound such as "uh-oh" or "um-hum" being
# bracketed element by element (T1-18).
_FILLER_BEFORE = r"(?<![\[\w'’])(?<!\w-)"
_FILLER_AFTER = r"(?![\]\w'’])(?!-\w)"

_BACKCHANNEL_RE = re.compile(
    r"(?<![\[\w'’-])(" + '|'.join(BACKCHANNEL_TOKENS) + r")(?![\]\w'’-])",
    flags=re.IGNORECASE,
)

_FILLER_RE = re.compile(
    _FILLER_BEFORE + r'(' + '|'.join(FILLER_TOKENS) + r')' + _FILLER_AFTER,
    flags=re.IGNORECASE,
)


def _filler_bracket(text):
    """Wrap unambiguous non-lexical filler tokens in square brackets.

    Hyphenated backchannels (:data:`BACKCHANNEL_TOKENS`) are bracketed
    whole first, so ``Mm-hmm`` becomes ``[Mm-hmm]``; the stage once gave
    ``[Mm]-[hmm]`` and ``[uh]-huh`` (audit finding T1-18). Then each
    standalone filler in :data:`FILLER_TOKENS` is bracketed, case
    preserved. A filler inside a hyphenated compound or next to an
    apostrophe ("o'er") is not a standalone filler and is left alone.
    The boundaries also exclude ``[`` and ``]``, so the stage is
    idempotent: a second application finds every filler already bracketed.

    evaluation/disfluency.py removes the brackets before counting and
    counts a hyphenated compound as one filler, so its counts are the same
    for ``[Mm-hmm]`` as they were for ``[Mm]-[hmm]``.

    Args:
        text: the transcript.

    Returns:
        The text with fillers bracketed.
    """
    text = _BACKCHANNEL_RE.sub(r'[\1]', text)
    return _FILLER_RE.sub(r'[\1]', text)


# Contraction repair table: maps regex-pattern keys to canonical
# apostrophised forms.  The first block covers inline contractions
# (``im``, ``dont``); the second block covers space-separated
# Whisper artefacts (``isn t``, ``don t``); the remaining blocks
# cover future, perfect and conditional auxiliaries.
#
# INVARIANT: no key may be a word that is already correct English.
# A key is a *misspelling* the recogniser produces, and rewriting it is
# a repair; a key that is also an ordinary word makes the stage rewrite
# correct text into something else, which is corruption and not repair.
# The table once held seven such keys, and the two commonest of them,
# ``were`` -> "we're" and ``its`` -> "it's", damaged 228 utterances of
# LibriSpeech test-clean while improving none. The others were ``wont``
# (a custom), ``cant`` (jargon), ``shed``, ``wed`` and ``id``. Every one
# of them is a frequent English word, and the substitution they cause
# accounted for the whole measured cost of the post-processing layer.
# Nothing was lost by removing them: the recogniser writes these
# contractions with their apostrophes already, which is why no utterance
# anywhere in the sweep improved under this stage.
# See :func:`test_contraction_fix_never_rewrites_correct_english`.
_CONTRACTIONS = {
    # Basic contractions
    r'\bim\b':       "I'm",
    r'\byoure\b':    "you're",
    r'\btheyre\b':   "they're",
    r'\bdont\b':     "don't",
    r'\bisnt\b':     "isn't",
    r'\barent\b':    "aren't",
    r'\bwasnt\b':    "wasn't",
    r'\bwerent\b':   "weren't",
    r'\bhasnt\b':    "hasn't",
    r'\bhavent\b':   "haven't",
    r'\bhadnt\b':    "hadn't",
    r'\bcouldnt\b':  "couldn't",
    r'\bshouldnt\b': "shouldn't",
    r'\bwouldnt\b':  "wouldn't",
    r'\bdidnt\b':    "didn't",
    r'\bdoesnt\b':   "doesn't",

    # Space-separated contractions (Whisper model artefacts)
    r'\bisn\s+t\b':     "isn't",
    r'\bdoesn\s+t\b':   "doesn't",
    r'\bdon\s+t\b':     "don't",
    r'\bwon\s+t\b':     "won't",
    r'\bcan\s+t\b':     "can't",
    r'\baren\s+t\b':    "aren't",
    r'\bwasn\s+t\b':    "wasn't",
    r'\bweren\s+t\b':   "weren't",
    r'\bhasn\s+t\b':    "hasn't",
    r'\bhaven\s+t\b':   "haven't",
    r'\bhadn\s+t\b':    "hadn't",
    r'\bcouldn\s+t\b':  "couldn't",
    r'\bshouldn\s+t\b': "shouldn't",
    r'\bwouldn\s+t\b':  "wouldn't",
    r'\bdidn\s+t\b':    "didn't",

    # Will contractions
    r'\btheyll\b':  "they'll",
    r'\byoull\b':   "you'll",
    r'\bitll\b':    "it'll",
    r'\bthatll\b':  "that'll",
    r'\bwholl\b':   "who'll",
    r'\bwhatll\b':  "what'll",

    # Have contractions
    r'\bive\b':       "I've",
    r'\byouve\b':     "you've",
    r'\bweve\b':      "we've",
    r'\btheyve\b':    "they've",
    r'\bcouldve\b':   "could've",
    r'\bshouldve\b':  "should've",
    r'\bwouldve\b':   "would've",

    # Would contractions.  ``id``, ``shed`` and ``wed`` are absent by the
    # invariant above: each is an ordinary English word, so repairing it
    # would rewrite "his id was checked" and "she shed a tear".
    r'\byoud\b':   "you'd",
    r'\bhed\b':    "he'd",
    r'\btheyd\b':  "they'd",
}


def _contraction_fix(text):
    """Repair contractions, applying ``_CONTRACTIONS`` case-insensitively."""
    for pattern, replacement in _CONTRACTIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


# Common-phrase fix table.  The majority of entries map their pattern
# back to its own lower-case spelling.  Because every row runs with
# re.IGNORECASE, those rows are not inert: they lower-case a capitalised
# occurrence ("Kind of" -> "kind of"). _sentence_capitalise later restores
# a capital at a sentence start, so only mid-sentence capitals are lost.
# They are retained for production parity, so that the WER benchmark sees
# the same sequence of substitutions that the desktop pipeline applies
# (the WER normaliser lower-cases, so scores are unaffected).  The
# remaining entries (``i mean`` -> ``I mean`` and similar) restore the
# capital ``I`` in fixed lexical hedges.
_COMMON_PHRASES = {
    r'\band all\b':       'and all',
    r'\bkind of\b':       'kind of',
    r'\bsort of\b':       'sort of',
    r'\byou know\b':      'you know',
    r'\bi mean\b':        'I mean',
    r'\bi think\b':       'I think',
    r'\bi guess\b':       'I guess',
    r'\bi feel like\b':   'I feel like',
    r'\bgoing to\b':      'going to',
    r'\bwant to\b':       'want to',
    r'\bhave to\b':       'have to',
    r'\btrying to\b':     'trying to',
    r'\bused to\b':       'used to',
    r'\bsupposed to\b':   'supposed to',
    r'\ba lot of\b':      'a lot of',
    r'\ba little bit\b':  'a little bit',
    r'\ball of\b':        'all of',
    r'\bsome of\b':       'some of',
    r'\bone of\b':        'one of',
    r'\bnone of\b':       'none of',
}


def _common_phrase_fix(text):
    """Normalise capitalisation in common lexical hedges."""
    for pattern, replacement in _COMMON_PHRASES.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


#: A private-use character that stands in for a full stop the clean-up
#: stages must not treat as punctuation: one inside a dotted abbreviation
#: or a hostname (see :func:`_keep_dots`).
_KEPT_DOT = ''

#: Single letters joined by full stops: "i.e.", "e.g.", "U.S.", "a.m.".
_DOTTED_ABBREVIATION_RE = re.compile(r'(?<![^\W\d_])(?:[^\W\d_]\.){2,}')

#: Abbreviations whose final full stop never ends a sentence, because they
#: introduce what follows. Others ("U.S.", "p.m.") may end one, so their
#: final stop is left as a possible boundary.
_CONTINUING_ABBREVIATIONS = frozenset({'i.e.', 'e.g.'})

#: Top-level domains a lower-case dotted token must end in to be read as a
#: hostname. Domains that are also common words ("in", "it", "is", "me",
#: "to", "so") are left out, so that two sentences glued at a chunk join
#: ("then.it") are still separated.
_HOSTNAME_TLDS = ('com', 'org', 'net', 'edu', 'gov', 'mil', 'info', 'io',
                  'ac', 'co', 'uk', 'eu', 'de', 'fr', 'es', 'nl', 'pl', 'ca',
                  'au', 'ch', 'se', 'dk', 'fi', 'ie', 'pt', 'jp', 'cn', 'nz',
                  'za', 'br', 'ru')

#: A lower-case hostname such as "example.com" or "ox.ac.uk".
_HOSTNAME_RE = re.compile(
    r'(?<![\w.])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:'
    + '|'.join(_HOSTNAME_TLDS) + r')(?!\w)')


def _keep_dots(text, keep_continuing_final=False):
    """Hide the full stops that belong to abbreviations and hostnames.

    The spacing and capitalisation stages read every full stop as the end
    of a sentence, so "i.e. often" was delivered as "I. E. Often", "U.S."
    as "U. S." and "example.com" as "example. Com" (audit finding T2-01).
    Each internal full stop of a dotted abbreviation, and every full stop of
    a lower-case hostname, is replaced by :data:`_KEPT_DOT`; the final stop
    of an abbreviation is kept as punctuation, except for those in
    :data:`_CONTINUING_ABBREVIATIONS` when *keep_continuing_final* is set.

    Returns ``(text, hidden)``. When *text* already holds the stand-in
    character nothing is hidden, so :func:`_restore_dots` cannot turn a
    character of the input into a full stop.
    """
    if _KEPT_DOT in text:
        return text, False

    def abbreviation(match):
        token = match.group(0)
        if keep_continuing_final and token.lower() in _CONTINUING_ABBREVIATIONS:
            return token.replace('.', _KEPT_DOT)
        return token[:-1].replace('.', _KEPT_DOT) + '.'

    text = _DOTTED_ABBREVIATION_RE.sub(abbreviation, text)
    text = _HOSTNAME_RE.sub(lambda m: m.group(0).replace('.', _KEPT_DOT), text)
    return text, True


def _restore_dots(text, hidden):
    """Undo :func:`_keep_dots`."""
    return text.replace(_KEPT_DOT, '.') if hidden else text


def _whitespace_normalise(text):
    """Collapse runs of whitespace and tidy spacing around ``,`` and ``.``.

    The full stops inside an abbreviation or a hostname are not spaced
    (:func:`_keep_dots`).
    """
    text, hidden = _keep_dots(text)
    text = re.sub(r'\s+', ' ', text)              # Multiple spaces to single
    text = re.sub(r'\s+([,.])', r'\1', text)      # No space before , or .
    text = re.sub(r'([,.])([a-zA-Z])', r'\1 \2',  # Insert space after , or .
                  text)
    return _restore_dots(text, hidden)


#: The first letter of a sentence: optional whitespace, then a letter of
#: any script (a word character that is neither a digit nor "_").
_SENTENCE_INITIAL_LETTER_RE = re.compile(r'^(\s*)([^\W\d_])')


def _sentence_capitalise(text):
    """Capitalise sentence-initial words.

    Sentence-initial capitalisation is an orthographic convention shared by
    every language this workflow handles, so this stage is not gated on
    language.  Capitalising the standalone pronoun ``i`` is specific to
    English and lives in :func:`_pronoun_i_fix`.

    A letter of any script directly after optional whitespace is
    capitalised, so ``élève`` and ``über`` gain their capitals as ``the``
    always did; the pattern once matched ASCII ``a``-``z`` only (audit
    finding T1-16). A sentence that opens with anything else, a bracketed
    filler (``[um] so``), a quotation mark or a digit, is left as it is.
    The letter is title-cased rather than upper-cased: the two agree for
    every Latin, Greek and Cyrillic letter, but Georgian has no capitals
    in running text and its title case leaves the letter unchanged, while
    its upper case would substitute the Mtavruli form. Scripts without
    case pass through unchanged.

    A full stop inside an abbreviation or a hostname, and the last one of
    "i.e." and "e.g.", does not end a sentence (:func:`_keep_dots`).

    Args:
        text: the transcript.

    Returns:
        The text with sentence-initial letters capitalised.
    """
    text, hidden = _keep_dots(text, keep_continuing_final=True)
    sentences = re.split(r'([.!?])', text)
    for i in range(0, len(sentences), 2):  # Every other element is sentence content
        if sentences[i].strip():
            # Capitalise the first word of the sentence
            sentences[i] = _SENTENCE_INITIAL_LETTER_RE.sub(
                lambda m: m.group(1) + m.group(2).title(),
                sentences[i],
            )
    return _restore_dots(''.join(sentences), hidden)


def _pronoun_i_fix(text):
    """Capitalise the standalone English first-person pronoun ``i``.

    Split out of :func:`_sentence_capitalise` so that it can be gated on
    language: ``i`` is a frequent ordinary word in other languages -- it is
    the Italian masculine plural definite article, as in ``i libri`` -- and
    capitalising it there corrupts the transcript.  The split is
    behaviour-preserving for English because the two rules do not interact:
    a sentence-initial ``i`` is already upper-cased by the preceding stage.

    The ``i`` of a dotted abbreviation ("i.e.", "e.i.") is not the pronoun
    and is left alone (audit finding T2-01).
    """
    return re.sub(r'(?<![^\W\d_]\.)\bi\b(?!\.[^\W\d_]\.)', 'I', text)


#: A mark that needs a space after it: one of . , ! ? ; : followed by
#: something other than whitespace or another such mark, except a . , or :
#: between two digits. That exception keeps decimals ("3.5", French
#: "3,5"), thousands separators ("1,000") and clock times ("10:30") whole;
#: without it they were delivered as "3. 5", "1, 000" and "10: 30" (audit
#: findings T1-04 and T2-01).
_SPACE_AFTER_MARK_RE = re.compile(
    r'([.,!?;:])(?=[^\s.,!?;:])(?!(?<=\d[.,:])\d)')

#: A run of repeated . , ! or ? to collapse to one mark. An unspaced run of
#: three or more full stops is an ellipsis and is kept as "..."
#: (see :func:`_collapse_repeated_mark`).
_REPEATED_MARK_RE = re.compile(r'([.,!?])(?:\s*\1)+')

#: A pair of straight double quotes and what they enclose.
_QUOTED_SPAN_RE = re.compile(r'"([^"]*)"')


def _collapse_repeated_mark(match):
    """Return the replacement for one :data:`_REPEATED_MARK_RE` match."""
    run = match.group(0)
    if run.startswith('...') and set(run) == {'.'}:
        return '...'
    return match.group(1)


def _punct_space_fix(text):
    """Normalise spacing around punctuation, quotes and parentheses.

    Removes whitespace before . , ! ? ; : and puts one space after them,
    except between two digits, so numbers and clock times stay whole.
    Collapses repeated marks ("!!" to "!"), keeping an unspaced "..." as an
    ellipsis rather than reducing it to a full stop. Straight double quotes
    are paired from the left, and whitespace just inside each pair is
    removed; the space before an opening quote is kept, so 'he said
    "Sarah"' no longer becomes 'he said"Sarah"', a form in which the name
    masker could not see the name (audit finding T1-03). Parentheses get a
    space outside and none inside. The full stops inside an abbreviation
    ("i.e.", "U.S.") or a hostname ("example.com") are not spaced
    (:func:`_keep_dots`, audit finding T2-01).

    Args:
        text: the transcript.

    Returns:
        The respaced text, stripped of leading and trailing whitespace.
    """
    text, hidden = _keep_dots(text)
    # Fix spaces before punctuation (keep space after)
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    # Ensure space after punctuation marks (but not before another, and
    # not inside a number)
    text = _SPACE_AFTER_MARK_RE.sub(r'\1 ', text)
    # Remove duplicate punctuation, keeping an ellipsis
    text = _REPEATED_MARK_RE.sub(_collapse_repeated_mark, text)
    # Fix space between adjacent punctuation
    text = re.sub(r'([.,!?;:])\s+([.,!?;:])', r'\1\2', text)
    # Quotation mark spacing. Whitespace is removed only inside a pair, so
    # the space the rule above puts before a closing quote goes and the
    # space before an opening quote stays. An unpaired quote is left where
    # it is.
    text = _QUOTED_SPAN_RE.sub(lambda m: '"' + m.group(1).strip() + '"', text)
    text = re.sub(r'"\s+', '" ', text)
    text = re.sub(r'"\s*([.,!?;:])', r'"\1', text)
    # Parentheses spacing
    text = re.sub(r'\s*\(\s*', ' (', text)
    text = re.sub(r'\s*\)\s*', ') ', text)
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    return _restore_dots(text, hidden).strip()


# Ordered tuple of atomic stages that compose ``clean_transcription_text``.
# Exposed for introspection by ``evaluation.conditions`` and by the
# registry-coverage test in ``tests/test_conditions.py``.  The order
# mirrors the original monolithic implementation and must not be
# rearranged without re-running the WER benchmark, because some stages
# are not commutative (for example, ``_punct_space_fix`` depends on
# the whitespace normalisation having already happened).
CLEAN_TEXT_STAGES = (
    _undefined_tag,
    _filler_bracket,
    _contraction_fix,
    _common_phrase_fix,
    _whitespace_normalise,
    _sentence_capitalise,
    _pronoun_i_fix,
    _punct_space_fix,
)


# Stages that assume an English vocabulary.  They are applied only when the
# transcript language is English; on other languages they corrupt real
# words rather than repairing artefacts.  Most sharply, ``_contraction_fix``
# rewrites the very common German preposition ``im`` ("in dem") to the
# English contraction ``I'm``, which on the FLEURS German test split alone
# raised the composite's word error rate by roughly a sixth.  The remaining
# clean-text stages (whitespace, sentence capitalisation, punctuation
# spacing) are orthographically general and always run.
_ENGLISH_ONLY_CLEAN_STAGES = frozenset({
    _undefined_tag,
    _filler_bracket,
    _contraction_fix,
    _common_phrase_fix,
    _pronoun_i_fix,
})


def _normalise_language_token(value):
    """Return a bare lower-case language token, or ``None``.

    Whisper reports a language either as a plain name (``german``), an ISO
    code (``de``), or a special token (``<|de|>``), depending on the
    transformers version and on where in the result the value appears.
    All three are reduced to the bare token so that
    :func:`_language_is_english` can classify them.
    """
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    match = re.fullmatch(r"<\|([a-z][a-z0-9_-]*)\|>", token)
    if match:
        token = match.group(1)
    return token or None


def detect_audio_language(transcriber, audio_array, sampling_rate=16000):
    """Return the language Whisper detects for *audio_array*, or ``None``.

    Uses the model's own ``detect_language``, which runs a single forward
    pass over the first mel segment and returns the argmax over the
    language tokens.  This is deliberately not the ASR pipeline's
    ``return_language`` reporting: between transformers 4.48 and 5.6 the
    generation path strips the language token before the tokenizer sees it,
    so that field is ``None`` on those versions (observed with 4.57.1 in
    ARC job 8293568, recorded in
    output/evaluation/fleurs_multilingual_summary.json; preflight.py
    reports the version a given environment has).  Going through
    ``detect_language`` is stable across the whole supported range.

    Detection is best effort.  Any failure is reported and yields ``None``,
    which leaves the caller on its English default rather than costing a
    transcription.
    """
    try:
        model = transcriber.model
        extractor = transcriber.feature_extractor
        features = extractor(
            audio_array, sampling_rate=sampling_rate, return_tensors="pt",
        ).input_features
        features = features.to(model.device, dtype=model.dtype)
        lang_ids = model.detect_language(input_features=features)
        lang_to_id = getattr(model.generation_config, "lang_to_id", None) or {}
        id_to_lang = {int(v): k for k, v in lang_to_id.items()}
        token = _normalise_language_token(id_to_lang.get(int(lang_ids[0])))
        if not token:
            return None
        # Report the full language name (``german``) rather than the ISO code
        # (``de``) that lang_to_id carries, so that a detected language is
        # recorded in the same vocabulary as an explicit --language and the
        # provenance field does not change shape with how the run was invoked.
        return _language_name(token)
    except Exception as exc:
        print(f"   Language detection unavailable ({exc}); assuming English.")
        return None


def _detected_language(transcription_result):
    """Return the language recorded on *transcription_result*, or ``None``.

    ``transcribe_audio_only`` stores the detected language under the
    top-level ``language`` key, which is this project's own convention; the
    chunk values that some transformers versions attach are read as a
    fallback, taking the most common so that one mis-detected chunk cannot
    decide a whole recording.  Ties resolve away from English, because
    wrongly concluding "English" re-enables the English-only clean-text
    stages on a non-English transcript, which is the damaging direction.
    Any unexpected shape yields ``None``, leaving the caller's default.

    An ISO code or special token (``de``, ``<|de|>``) is returned as the
    full name (``german``) through :func:`_language_name`, the vocabulary
    :func:`detect_audio_language` and ``--language`` use, so the header no
    longer reads "Language: De" when the value came from the chunks (audit
    finding T2-14).
    """
    if not isinstance(transcription_result, dict):
        return None

    top = _normalise_language_token(transcription_result.get("language"))
    if top:
        return _language_name(top)

    chunks = transcription_result.get("chunks")
    if not isinstance(chunks, (list, tuple)):
        return None
    chunk_langs = []
    for chunk in chunks:
        if isinstance(chunk, dict):
            token = _normalise_language_token(chunk.get("language"))
            if token:
                chunk_langs.append(token)
    if not chunk_langs:
        return None
    # Named before counting, so "de" and "german" on different chunks are
    # counted as one language.
    counts = Counter(_language_name(token) for token in chunk_langs)
    # Most frequent wins; a tie resolves to the non-English token.
    return min(counts.items(),
               key=lambda kv: (-kv[1], _language_is_english(kv[0])))[0]


def _language_is_english(language) -> bool:
    """Return ``True`` when *language* denotes English, or is unset.

    ``None`` and the empty string default to English, so every existing
    caller that passes no language -- and the whole English benchmark --
    keeps its behaviour byte-for-byte.  The Whisper language name
    (``english``), the ISO code (``en``, ``en-US``, ``en_us``) and
    Whisper's special-token form (``<|en|>``) all count; the value is
    reduced by :func:`_normalise_language_token` first. The special-token
    form, which ``--language`` accepts, once counted as non-English, so the
    English-only stages were silently skipped (audit finding T2-14).
    """
    lang = _normalise_language_token(language)
    if lang is None:
        return True  # unset, or an unusable value: keep the English default
    return lang in ("english", "en") or lang.startswith(("en-", "en_"))


def _whisper_language_table():
    """Return Whisper's code-to-name table (``{'de': 'german', ...}``).

    It is the table transformers ships with the Whisper tokenizer, read
    rather than copied so that it cannot drift from the model's. ``None``
    when transformers is not installed.
    """
    try:
        from transformers.models.whisper.tokenization_whisper import LANGUAGES
    except ImportError:
        return None
    return LANGUAGES


def _language_name(token):
    """Return Whisper's full name for a language code, or *token* itself.

    ``de`` becomes ``german``, and a value that is already a name, or that
    Whisper's table does not know, is returned unchanged; without
    transformers the token is returned as it is. Used so that a language
    recorded in a header or manifest has the same vocabulary however it
    was obtained.
    """
    table = _whisper_language_table()
    return table.get(token, token) if table else token


def clean_transcription_text(text, language="english"):
    """Apply the production text-cleaning pipeline to *text*.

    The function is the in-order composition of the atomic stages in
    :data:`CLEAN_TEXT_STAGES`.  Stages that assume English vocabulary
    (:data:`_ENGLISH_ONLY_CLEAN_STAGES`) are skipped when *language* is not
    English, so that, for example, the German preposition ``im`` is not
    rewritten to ``I'm``.  *language* defaults to English, leaving English
    callers and the English benchmark byte-for-byte unchanged.
    """
    english = _language_is_english(language)
    for stage in CLEAN_TEXT_STAGES:
        if not english and stage in _ENGLISH_ONLY_CLEAN_STAGES:
            continue
        text = stage(text)
    return text


# ---------------------------------------------------------------------------
# End of post-processing helpers.
# ---------------------------------------------------------------------------

def _transcript_title(input_file, original_filename=None):
    """Return ``(title, display_stem)`` for a transcript header.

    The title is the recording's stem with underscores shown as colons.
    TODO: justify (source unknown). The mapping dates from the initial
    release (3557fe3) with no stated reason; a plausible one is that ':'
    cannot appear in a Windows file name, so a recording named for a time
    or a 'Project: session' label arrives with '_' in its place.
    """
    stem = Path(original_filename).stem if original_filename else Path(input_file).stem
    return stem.replace('_', ':'), stem


def _transcript_header_lines(*, input_file, original_filename=None,
                             model=None, language=None, mask_names=False,
                             fix_repetitions=False, use_facebook_names=False,
                             use_facebook_surnames=False,
                             enhance_audio_enabled=False,
                             speaker_attribution=False,
                             language_assumed=False):
    """Return the metadata lines shared by the .txt and .docx headers.

    *language_assumed* marks a language that was neither given nor
    detected, so the header does not read as if English decoding had been
    requested when Whisper in fact chose the language itself.

    Both writers print these lines between their own separators, so a
    header change made here reaches both files; they were once two copies
    that had begun to drift. Lines for options that were off are omitted.
    Order: input, processing time, version, model, then audio
    enhancement, language, repetitions, privacy and speaker attribution.
    """
    input_name = Path(original_filename).name if original_filename else Path(input_file).name
    lines = [
        f"Input file: {input_name}",
        f"Processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Transcription system version: {get_latest_version()}",
    ]
    if model:
        lines.append(f"Model: {model}")
    if enhance_audio_enabled:
        lines.append("Audio enhanced before transcription")
    if language and language_assumed:
        lines.append(f"Language: {language.title()} (assumed for "
                     f"post-processing; not given and not detected)")
    elif language:
        lines.append(f"Language: {language.title()}")
    if fix_repetitions:
        lines.append("Edited to remove likely spurious repetitions.")
    if mask_names:
        if use_facebook_names or use_facebook_surnames:
            lines.append("Privacy: Personal names masked using Facebook list (review recommended)")
        else:
            lines.append("Privacy: Personal names masked using internal list (review recommended)")
    if speaker_attribution:
        lines.append("Speaker attribution: Enabled (accuracy depends on recording quality, "
                     "speaker count, and speaker similarity)")
    return lines


def create_word_document(text_content, output_path, input_file, *,
                         mask_names=False, model_name=None, language=None,
                         fix_repetitions=False, original_filename=None,
                         use_facebook_names=False, use_facebook_surnames=False,
                         enhance_audio_enabled=False, speaker_attribution=False,
                         language_assumed=False):
    """Write *text_content* to a Word document with a title and metadata.

    Args:
        text_content: the transcript; each blank-line-separated block
            becomes one paragraph.
        output_path: the .docx to write.
        input_file, original_filename: name the title and the input line
            (the original name wins, so a temporary file is never shown).
        mask_names ... speaker_attribution: the run's settings, recorded in
            the header by :func:`_transcript_header_lines`.

    Returns ``True`` when the document was saved and ``False`` otherwise
    (python-docx missing, or any error while building or saving, which is
    printed). Callers report success only on ``True``; a failed save can
    leave an older .docx from a previous run at *output_path*.
    """
    if not DOCX_AVAILABLE:
        print("   ⚠️  Word document creation skipped - python-docx not available")
        return False

    try:
        doc = Document()

        title_text, _ = _transcript_title(input_file, original_filename)

        # Level 0 is Word's Title style, larger than Heading 1.
        title = doc.add_heading(title_text, 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # The .txt header underlines to the title's width; a proportional
        # font gives '=' no fixed width, so the .docx uses a fixed rule.
        # TODO: justify (source unknown) the width of 52.
        metadata_para = doc.add_paragraph()
        metadata_para.add_run("="*52).bold = True

        for line in _transcript_header_lines(
                input_file=input_file, original_filename=original_filename,
                model=model_name, language=language, mask_names=mask_names,
                fix_repetitions=fix_repetitions,
                use_facebook_names=use_facebook_names,
                use_facebook_surnames=use_facebook_surnames,
                enhance_audio_enabled=enhance_audio_enabled,
                speaker_attribution=speaker_attribution,
                language_assumed=language_assumed):
            doc.add_paragraph(line)

        metadata_para2 = doc.add_paragraph()
        metadata_para2.add_run("="*52).bold = True

        doc.add_paragraph()

        # Split by double newlines to preserve paragraph structure
        paragraphs = text_content.split("\n\n")
        for paragraph in paragraphs:
            if paragraph.strip():
                para = doc.add_paragraph(paragraph.strip())
                # Set line spacing to 1.5
                para.paragraph_format.line_spacing = 1.5

        doc.save(output_path)
        return True
    except Exception as e:
        print(f"Error creating Word document: {e}")
        return False
def enhance_audio(input_path, output_path):
    """Enhance a recording for transcription and write it to *output_path*.

    The steps, in the order the code applies them:

    1. Decode to 16 kHz mono and multiply by a fixed gain of 3.61
       (+11.2 dB). The gain comes first, so every later step sees the
       amplified signal.
    2. Spectral subtraction. The noise profile is the mean STFT magnitude
       of the first 15 frames (``int(0.5 * 16000 / 512)`` at librosa's
       default 2048-sample window and 512-sample hop), roughly the first
       half second, so the step assumes that half second holds no speech;
       a recording that opens with speech uses speech as its noise
       profile. Twice the profile is subtracted from every frame, floored
       at a tenth of the original magnitude, so no bin is attenuated by
       more than 20 dB. The inverse STFT is called without ``length=``, so
       the output is cut to a whole number of hops, losing up to 511
       samples (32 ms) at the end.
    3. A static soft-clipping curve, applied to each sample on its own:
       magnitudes above 0.1 are reduced to 0.1 plus a quarter of the excess.
       Earlier documentation called this dynamic-range compression, but it
       has no level envelope, attack or release, so it reshapes the
       waveform (a form of distortion) rather than compressing dynamics.
       After the gain in step 1 it bends every input sample whose
       magnitude exceeds about 0.028 (0.1 / 3.61).
    4. Peak normalisation to 0.95, only when the peak exceeds 0.95.

    The result is written as WAV. The constants were labelled the
    'interview_clarity' preset, a name defined nowhere else in the
    repository. TODO: justify (source unknown) the gain of 3.61, the
    subtraction factor of 2.0, the 0.1 floor, the 0.1 threshold, the
    ratio of 4 and the 0.95 ceiling; they are unchanged since the first
    commit (audit finding T2-07).

    Args:
        input_path: the recording, any format :func:`audio_io.load_audio`
            (or librosa) can decode.
        output_path: where the enhanced WAV is written.

    Returns ``None``. Writes *output_path*, a full copy of the recording.
    """
    print(" Enhancing audio quality...")

    # Load audio.  Goes through audio_io so that compressed formats such as
    # .m4a work wherever an ffmpeg exists, rather than only where libsndfile
    # happens to support the container.
    if _HAS_AUDIO_IO:
        audio, sr = load_audio(input_path, sr=16000)
    else:
        audio, sr = librosa.load(input_path, sr=16000)

    # The 'interview_clarity' constants; see the docstring for what each
    # step does and why the values are unjustified.
    # 1. Fixed amplification (3.61x, +11.2 dB), applied before everything
    #    else.
    audio = audio * 3.61

    # 2. Noise reduction using spectral subtraction (librosa's default
    #    2048-sample window and 512-sample hop)
    stft = librosa.stft(audio)
    magnitude = np.abs(stft)
    phase = np.angle(stft)

    # Noise profile: the mean of the frames in roughly the first 0.5 s,
    # assumed to hold no speech. 512 is librosa's default hop.
    noise_frames = int(0.5 * sr / 512)
    noise_magnitude = np.mean(magnitude[:, :noise_frames], axis=1, keepdims=True)

    # Subtract twice the profile, keeping at least a tenth of each bin
    # (at most 20 dB of attenuation).
    alpha = 2.0
    clean_magnitude = magnitude - alpha * noise_magnitude
    clean_magnitude = np.maximum(clean_magnitude, 0.1 * magnitude)

    # Reconstruct audio. Without length= the output is floored to a whole
    # number of hops, dropping up to 511 samples at the end.
    clean_stft = clean_magnitude * np.exp(1j * phase)
    audio = librosa.istft(clean_stft)

    # 3. Static soft-clipping curve, sample by sample: above the threshold
    #    the excess is divided by the ratio. There is no level envelope,
    #    so this is waveshaping, not dynamic-range compression.
    threshold = 0.1
    ratio = 4.0
    audio_abs = np.abs(audio)
    mask = audio_abs > threshold
    audio[mask] = np.sign(audio[mask]) * (threshold + (audio_abs[mask] - threshold) / ratio)

    # 4. Peak normalisation to prevent clipping
    max_val = np.max(np.abs(audio))
    if max_val > 0.95:
        audio = audio * (0.95 / max_val)

    sf.write(output_path, audio, sr)
    print(f"   Enhanced audio saved to {output_path}")

_OFFLINE_ENV_VARS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")


def _is_offline_mode(env=None) -> bool:
    """Return True when either ``HF_HUB_OFFLINE`` or ``TRANSFORMERS_OFFLINE``
    is set to a truthy value in *env* (defaults to ``os.environ``).

    A value is considered truthy when, after stripping and lowercasing, it
    is one of ``{'1', 'true', 'yes', 'on'}``. This matches the convention
    used by the ``huggingface_hub`` library.
    """
    if env is None:
        env = os.environ
    truthy = {"1", "true", "yes", "on"}
    for name in _OFFLINE_ENV_VARS:
        val = env.get(name)
        if val is not None and val.strip().lower() in truthy:
            return True
    return False


def _diarization_uses_powerset(pipeline_obj) -> bool:
    """Return True when the pipeline's segmentation head is powerset.

    pyannote 3.x predicts one class per *combination* of simultaneously
    active speakers rather than one score per speaker, so there is no
    binary onset or offset threshold anywhere in the pipeline. Callers
    use this to tell the user that ``--vad-onset``/``--vad-offset`` have
    no target on this model, instead of appearing to honour them.
    """
    try:
        return bool(pipeline_obj._segmentation.model.specifications.powerset)
    except AttributeError:
        return False


def _apply_vad_thresholds(pipeline_obj, vad_onset=None, vad_offset=None):
    """Apply binary VAD thresholds, and report only what actually changed.

    ``setattr`` on an ordinary Python object always succeeds, and it
    happily creates an attribute that did not exist, so an assignment to
    a name the pipeline never reads looks indistinguishable from a real
    override. The earlier version of this code took that success at face
    value and printed "VAD thresholds applied" while the pipeline went on
    using its defaults.

    Two conditions are therefore required before a threshold counts as
    applied: the attribute must already exist and hold a number, since a
    threshold the pipeline actually consults necessarily has a default;
    and the value must survive a read-back. Writing to a name that was
    absent would only invent an attribute nothing consults.

    Returns ``(applied, message)``: a dict of the thresholds that took
    effect, and a line to show the user.
    """
    requested = {name: value for name, value in
                 (("onset", vad_onset), ("offset", vad_offset))
                 if value is not None}
    if not requested:
        return {}, None

    if _diarization_uses_powerset(pipeline_obj):
        return {}, ("--vad-onset/--vad-offset have no effect on this model: "
                    "it uses powerset segmentation, which predicts speaker "
                    "combinations directly and has no binary threshold. "
                    "The pipeline defaults were used.")

    # Candidate attribute paths, tried in order; the first that already
    # holds a number and survives a read-back is used. pyannote.audio 3.x
    # (requirements.txt floors it at 3.1) has two kinds: 'segmentation.
    # threshold' on a SpeakerDiarization pipeline with a binary
    # (non-powerset) segmentation model, whose segmentation parameters are
    # only 'threshold' and 'min_duration_off', so it has no offset; and the
    # top-level 'onset'/'offset' of VoiceActivityDetection-style pipelines
    # loaded through --diarization-config. The pyannote 2.x names
    # 'segmentation_onset', 'segmentation_offset' and 'segmentation.offset'
    # exist on no supported version and were removed (audit finding T2-19).
    candidates = {
        "onset": ("segmentation.threshold", "onset"),
        "offset": ("offset",),
    }
    applied = {}
    for name, value in requested.items():
        for path in candidates[name]:
            parts = path.split(".")
            try:
                target = pipeline_obj
                for part in parts[:-1]:
                    target = getattr(target, part)
                leaf = parts[-1]
                float(getattr(target, leaf))   # must already hold a number
                setattr(target, leaf, value)
                if abs(float(getattr(target, leaf)) - float(value)) < 1e-9:
                    applied[name] = value
                    break
            except (AttributeError, KeyError, TypeError, ValueError):
                continue

    if not applied:
        return {}, ("Could not apply --vad-onset/--vad-offset to this "
                    "pipeline; no threshold attribute accepted the value. "
                    "The pipeline defaults were used.")
    missing = sorted(set(requested) - set(applied))
    message = "VAD thresholds applied: " + ", ".join(
        f"{k}={v}" for k, v in sorted(applied.items()))
    if missing:
        message += f" (no effect: {', '.join(missing)})"
    return applied, message


#: The diarisation pipeline loaded from the Hugging Face Hub when no local
#: pipeline is given. evaluation/benchmark_der.py, benchmark_anonymisation.py
#: and the setup scripts still carry their own copy of this identifier.
DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"


def _resolve_hf_token():
    """Return the Hugging Face token the diarisation loader uses, or ``None``.

    Delegates to :func:`preflight.resolve_hf_token` so the pipeline and
    preflight agree on where a token comes from (audit findings CORE-13,
    XREF-04): the ``HF_TOKEN``, ``HUGGINGFACE_TOKEN`` and
    ``HUGGING_FACE_HUB_TOKEN`` variables, then ``hf_token.txt`` at the
    repository root and in the working directory, then ``$HF_TOKEN_PATH``,
    ``<HF_HOME>/token`` and ``~/.huggingface/token``. A narrower lookup
    that only a test called was removed (PIPE-02, INTEG-04).

    Side effects: reads the environment and the candidate token files;
    writes nothing.
    """
    from preflight import resolve_hf_token
    return resolve_hf_token()[0]


def _resolve_local_pipeline_path(path):
    """Return the config file a local pyannote pipeline is loaded from.

    pyannote 3.x ``Pipeline.from_pretrained`` loads a local pipeline only
    from a config *file*; any other string is taken as a Hub repository
    id. A directory, which the documentation suggested, therefore never
    loaded locally. A directory is resolved to the ``config.yaml`` inside
    it, and a path that is neither raises ``FileNotFoundError``.
    """
    p = Path(path)
    if p.is_dir():
        config = p / "config.yaml"
        if config.is_file():
            return str(config)
        raise FileNotFoundError(
            f"'{path}' is a directory without a config.yaml; pass a pyannote "
            f"pipeline config file or a directory that contains one")
    if p.is_file():
        return str(p)
    raise FileNotFoundError(f"local diarisation pipeline '{path}' not found")


def _pipeline_load_kwargs(from_pretrained, token, offline):
    """Choose the keyword arguments *from_pretrained* actually accepts.

    pyannote.audio 3.x names the token ``use_auth_token`` and has no
    ``local_files_only``; later versions call it ``token``. Selecting by
    signature replaces the earlier approach of calling with each spelling
    and catching TypeError, which also swallowed TypeErrors raised inside a
    genuine load. ``local_files_only`` is passed only where it is accepted;
    otherwise offline mode relies on huggingface_hub honouring
    ``HF_HUB_OFFLINE`` itself.
    """
    import inspect
    try:
        params = inspect.signature(from_pretrained).parameters
    except (TypeError, ValueError):
        params = {}
    open_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD
                      for p in params.values())
    kwargs = {}
    if 'use_auth_token' in params and 'token' not in params:
        kwargs['use_auth_token'] = token
    elif 'token' in params or open_kwargs:
        kwargs['token'] = token
    if offline and ('local_files_only' in params or open_kwargs):
        kwargs['local_files_only'] = True
    return kwargs


#: What pyannote.audio 3.x fetches from the Hub: a pipeline's config
#: (PIPELINE_PARAMS_NAME) and the weights of each model it names
#: (HF_PYTORCH_WEIGHTS_NAME).
_PIPELINE_CONFIG_NAME = "config.yaml"
_MODEL_WEIGHTS_NAME = "pytorch_model.bin"

#: A Hub checkpoint as pyannote's loaders take one: ``org/name``, optionally
#: followed by ``@revision``.
_HUB_CHECKPOINT_RE = re.compile(r"[\w.-]+/[\w.-]+(@\S+)?")


def _cached_snapshot(checkpoint, filename):
    """Return ``(path, commit)`` of the cached *filename* a load of *checkpoint* opens.

    pyannote.audio 3.x keeps no record of the snapshot it loaded. Its
    loaders split *checkpoint* at ``@`` into a repository and a revision
    (``main`` when there is none) and hand both to ``hf_hub_download`` with
    pyannote's own cache (:func:`preflight.pyannote_cache_dir`), which
    resolves a branch through ``refs/<branch>`` to the commit whose
    directory, ``snapshots/<commit>/``, holds the file. It does that on a
    download and on an offline read alike, so the same lookup made after a
    load (``huggingface_hub.try_to_load_from_cache``) returns the file the
    load opened, and its directory names the commit. Only a job moving
    ``refs/main`` in the same cache in between could make them differ.

    Returns ``(None, None)`` when that cannot be determined: huggingface_hub
    does not import, no cache directory resolves, or the cache holds no
    such file at that revision. Never raises, because a run that has
    already diarised must not fail over its provenance record.
    """
    repo_id, *revision = str(checkpoint).split('@')
    try:
        from huggingface_hub import try_to_load_from_cache
        from preflight import pyannote_cache_dir
        cache_dir = pyannote_cache_dir()
        if cache_dir is None:
            return None, None
        path = try_to_load_from_cache(repo_id, filename, cache_dir=str(cache_dir),
                                      revision=revision[0] if revision else None)
    except Exception:  # see the docstring
        return None, None
    # Not a path: nothing cached, or a marker that the file is known absent.
    if not isinstance(path, str):
        return None, None
    return path, Path(path).parent.name


def _sub_model_revisions(config_path):
    """Return ``{repo: commit or None}`` for the Hub models a pipeline config names.

    speaker-diarization-3.1 keeps no weights of its own: its config names
    ``pyannote/segmentation-3.0`` and ``pyannote/wespeaker-voxceleb-resnet34-LM``
    without a revision, and pyannote loads each one's weights from its
    cache's ``main`` (:func:`_cached_snapshot`), so the pipeline's snapshot
    does not say which weights ran. Each value under ``pipeline.params``
    naming a Hub model, as a string or as the ``checkpoint`` of a mapping
    (the two forms pyannote's ``get_model`` loads), is looked up. A value
    naming a file on disk is a local model and is left out.

    Returns None when the config cannot be read, and an empty dict when it
    names no Hub model. The keys are sorted, so the record does not depend
    on the order the config lists the models in.
    """
    try:
        import yaml
        with open(config_path, encoding='utf-8') as handle:
            params = yaml.safe_load(handle)['pipeline'].get('params') or {}
        values = list(params.values())
    except Exception:  # as in _cached_snapshot
        return None
    revisions = {}
    for value in values:
        if isinstance(value, dict):
            value = value.get('checkpoint')
        if (isinstance(value, str) and _HUB_CHECKPOINT_RE.fullmatch(value)
                and not os.path.isfile(value)):
            revisions[value.split('@')[0]] = _cached_snapshot(
                value, _MODEL_WEIGHTS_NAME)[1]
    return dict(sorted(revisions.items()))


def _load_failure(exc):
    """Say why a diarisation load failed: the exception's type and message.

    The message alone can hide what went wrong. The audit wave's case study
    reported only "Underlying error: 'name'", which is how a KeyError for
    the key ``name`` prints: pyannote had read a cached pipeline config
    with no pipeline name, which a test run had written over the real one
    (see tests/test_s1_env_setup.py). With the type, the record reads
    "KeyError: 'name'".
    """
    return f"{type(exc).__name__}: {exc}"


def _expected_pipeline_cache_path(checkpoint):
    """Return where an offline load of *checkpoint* looks for the pipeline.

    That is ``models--<org>--<name>`` in pyannote's own cache
    (:func:`preflight.pyannote_cache_dir`), the directory
    ``setup/cache_pyannote_arc.py`` fills. pyannote.audio 3.x never reads
    the hub cache under ``HF_HOME``, which the offline error message used
    to name, so a user who filled the directory it named still had no
    pipeline: the mistake audit findings CORE-R3 and REV-01 corrected in
    preflight and in the caching script. A ``@revision`` suffix is not
    part of the directory name. When no cache directory resolves, the rule
    is spelled out instead of a path.
    """
    folder = "models--" + str(checkpoint).split('@')[0].replace('/', '--')
    try:
        from preflight import pyannote_cache_dir
        cache_dir = pyannote_cache_dir()
    except Exception:  # only a message depends on it
        cache_dir = None
    if cache_dir is None:
        return f"$PYANNOTE_CACHE (or ~/.cache/torch/pyannote)/{folder}"
    return os.path.join(str(cache_dir), folder)


def _damaged_pipeline_cache(checkpoint):
    """Say what is damaged in pyannote's cached copy of *checkpoint*, or ``None``.

    The check is preflight's (:func:`preflight.damaged_pipeline_configs`),
    which covers ``pyannote/speaker-diarization-3.1``, so any other
    checkpoint gives ``None``, as does a cache with nothing damaged. A
    damaged config fails every load whether or not a token is found,
    because the Hub client returns a file already in the cache without
    fetching it again. In the audit wave a test run had written a stub over
    the cached config (NEW-INC-01), and the case study's error asked only
    for a token. Returns what is damaged and how to repair it, as
    sentences for the error message. Never raises, since only a message
    depends on it.
    """
    try:
        from preflight import (
            PYANNOTE_PIPELINE_REPOS, damaged_pipeline_configs,
            pipeline_config_remedy, pipeline_damage_heading)
        if str(checkpoint).split('@')[0] != PYANNOTE_PIPELINE_REPOS[0]:
            return None
        damaged = damaged_pipeline_configs()
        if not damaged:
            return None
        heading = pipeline_damage_heading(damaged)
        found = "; ".join(f"{path} {problem}" for path, problem in damaged)
        return (f"{heading[:1].upper()}{heading[1:]}: {found}. Neither a token "
                f"nor a new download repairs it. Fix: "
                f"{pipeline_config_remedy(damaged)}.")
    except Exception:  # only a message depends on it
        return None


def _resolve_diarization_strategy(model_path=None, diarization_config=None,
                                  model_id=DEFAULT_DIARIZATION_MODEL,
                                  env=None):
    """Plan the ordered sequence of diarisation-loading attempts.

    This is a pure helper extracted so that the resolution policy can be
    unit-tested without importing ``pyannote.audio`` or making any network
    call. It returns a dict with keys:

    * ``offline_mode``: ``True`` if either ``HF_HUB_OFFLINE`` or
      ``TRANSFORMERS_OFFLINE`` is set to a truthy value.
    * ``attempts``: an ordered list of ``{'kind', 'path', 'source_label'}``
      dicts. ``kind`` is one of ``'local_config'``, ``'local_path'`` or
      ``'hf_loader'``. When ``offline_mode`` is True, the ``hf_loader``
      entry (if present) is marked with ``source_label`` ``'hf_loader_offline'``
      to flag a cache-only load (see :func:`_pipeline_load_kwargs`).

    The order is: explicit YAML config (``--diarization-config``) first,
    then explicit local directory (``--diarization-model-path``), then
    finally the HuggingFace loader for ``model_id``.
    """
    offline = _is_offline_mode(env)
    attempts: list[dict] = []
    if diarization_config:
        attempts.append({
            'kind': 'local_config',
            'path': str(diarization_config),
            'source_label': 'local_config',
        })
    if model_path:
        attempts.append({
            'kind': 'local_path',
            'path': str(model_path),
            'source_label': 'local_path',
        })
    attempts.append({
        'kind': 'hf_loader',
        'path': model_id,
        'source_label': 'hf_loader_offline' if offline else 'hf_loader',
    })
    return {'offline_mode': offline, 'attempts': attempts}


def _speaker_count_kwargs(num_speakers=None, min_speakers=None,
                          max_speakers=None) -> dict:
    """Translate speaker-count hints into pyannote pipeline arguments.

    Constraining the count is not the free improvement it appears to be.
    Left alone, the clustering step reliably finds more speakers than a
    meeting contains, which invites the conclusion that telling it the
    true number can only help. Measured on the AMI test split it did the
    opposite: fixing the true count raised the macro diarisation error
    rate and worsened most meetings, one of them several-fold, and the
    increase came from speaker confusion. The figures are in
    output/evaluation/der_summary.json (count estimated) and
    output/evaluation/der_oracle/der_summary.json (true count given), and
    the diarisation section of the manuscript reports them; they are not
    repeated here because a re-run changes them, and an earlier copy in
    this docstring had already drifted from the report (audit finding
    T2-20). Agglomerative clustering forced to stop at exactly *n* has to
    merge until it gets there, and one merge of two distinct speakers
    costs far more than several spurious small clusters that the
    diarisation-error mapping largely discounts.

    The options are offered because the count is often known in advance
    and pyannote supports constraining it, not because doing so is
    advisable by default. See the diarisation section of the manuscript.

    An exact count and a range are mutually exclusive in pyannote, so an
    exact count wins and the range is dropped rather than passed
    alongside it, which the pipeline would reject. Values below one are
    ignored, since they cannot describe a recording that contains speech.
    """
    if num_speakers is not None and int(num_speakers) >= 1:
        return {"num_speakers": int(num_speakers)}
    bounds = {}
    if min_speakers is not None and int(min_speakers) >= 1:
        bounds["min_speakers"] = int(min_speakers)
    if max_speakers is not None and int(max_speakers) >= 1:
        bounds["max_speakers"] = int(max_speakers)
    if ("min_speakers" in bounds and "max_speakers" in bounds
            and bounds["min_speakers"] > bounds["max_speakers"]):
        raise ValueError(
            f"--min-speakers ({bounds['min_speakers']}) exceeds "
            f"--max-speakers ({bounds['max_speakers']})")
    return bounds


def perform_speaker_diarization(audio_path, model_path=None,
                                model_id=DEFAULT_DIARIZATION_MODEL,
                                diarization_config=None,
                                vad_onset=None,
                                vad_offset=None,
                                num_speakers=None,
                                min_speakers=None,
                                max_speakers=None):
    """Perform speaker diarisation using pyannote.audio.

    Resolution policy
    -----------------
    The pipeline is loaded in the following order:

        1. ``--diarization-config PATH`` → load a local YAML config file
           that references on-disk segmentation and embedding checkpoints
           directly. This is the fully air-gapped strategy.
        2. ``--diarization-model-path PATH`` → load a local pipeline: a
           pyannote ``config.yaml``, or a directory (such as a snapshot)
           that contains one.
        3. HuggingFace loader for ``model_id`` → checks the local cache
           first; downloads from the Hub only when the weights are absent
           and offline mode is not active. A HuggingFace token
           (``HF_TOKEN``/``HUGGINGFACE_TOKEN`` env var or ``hf_token.txt``)
           is required for gated models such as
           ``pyannote/speaker-diarization-3.1``.

    When a local pipeline was given (1 or 2) and none of them loads, the
    run does not fall back to the Hub: silently substituting the default
    model for the one the user chose is worse than no diarisation. A
    loader that returns ``None`` (pyannote 3.x does, for a gated model
    without a token or accepted terms) counts as a failure.

    Offline mode is activated by setting either ``HF_HUB_OFFLINE=1`` or
    ``TRANSFORMERS_OFFLINE=1`` in the environment. ``local_files_only=True``
    is passed only to a loader that accepts it (pyannote 3.x does not);
    otherwise the cache-only lookup relies on huggingface_hub honouring
    those variables itself. The error message produced on a cache miss
    names the expected location in pyannote's own cache
    (:func:`_expected_pipeline_cache_path`). When the Hub load fails and
    that cache holds a damaged copy of the pipeline
    (:func:`_damaged_pipeline_cache`), the error says so and how to replace
    it, in place of the token or cache advice, which cannot repair it.

    ``num_speakers``, ``min_speakers`` and ``max_speakers`` constrain how
    many speakers the clustering step may find. The count is often known
    before the recording is made, but constraining it is not reliably an
    improvement; see :func:`_speaker_count_kwargs` for what was measured.

    ``vad_onset`` and ``vad_offset`` set the thresholds at which voice
    activity detection, the step that decides which parts of a recording
    contain speech at all, declares speech to have started and stopped.
    They apply only to pipelines built on a binary segmentation model.
    The default pipeline is not one: pyannote 3.x predicts which
    *combination* of speakers is active in each window rather than
    scoring each speaker separately, so there is no threshold to move.
    :func:`_apply_vad_thresholds` reports what it was actually able to
    change, rather than reporting success for a write nothing reads.

    Downloading model weights is an outbound-only operation that carries no
    user data. The privacy guarantee of this project concerns audio
    recordings and transcriptions not leaving the institution.

    Returns
    -------
    tuple[list[dict] | None, dict]
        A list of ``{'start', 'end', 'speaker'}`` segments (or ``None`` if
        diarisation could not be performed) and a metadata dict with keys
        ``source`` (``'local_config'``, ``'local_path'``, ``'hf_loader'``,
        ``'hf_loader_offline'`` or ``'unavailable'``), ``model_id``,
        ``model_path`` (when known), ``model_revision``,
        ``sub_model_revisions``, ``offline_mode`` (bool) and an optional
        ``error`` string. ``model_revision`` is the Hub commit of the
        pipeline the HuggingFace loader read, and ``sub_model_revisions``
        maps each Hub model the loaded config names (segmentation and
        embedding) to the commit its weights came from; a value is ``None``
        where the cache cannot say, and ``model_revision`` is ``None`` for
        a local pipeline. Callers persist this metadata in the JSON sidecar
        and the run manifest so reviewers can audit how the model was
        obtained and which snapshot ran.
    """
    print("  🎭 Performing speaker diarisation...")

    plan = _resolve_diarization_strategy(
        model_path=model_path,
        diarization_config=diarization_config,
        model_id=model_id,
    )
    offline_mode = plan['offline_mode']

    source_info: dict = {
        'source': 'unavailable',
        'model_id': model_id,
        'model_path': None,
        # The Hub snapshots the load used (audit finding DEPS-04), read back
        # from the cache once a pipeline has loaded. The load itself is not
        # pinned, as the Whisper load is not: an offline machine whose cache
        # holds another snapshot would then not diarise at all.
        'model_revision': None,
        'sub_model_revisions': None,
        'offline_mode': offline_mode,
        'vad_onset': vad_onset,
        'vad_offset': vad_offset,
        'error': None,
    }
    try:
        speaker_kwargs = _speaker_count_kwargs(
            num_speakers, min_speakers, max_speakers)
    except ValueError as exc:
        print(f"   ⚠️  {exc}")
        source_info['error'] = str(exc)
        return None, source_info
    source_info['speaker_count_hint'] = speaker_kwargs or None
    if speaker_kwargs:
        print("   Speaker count constrained: "
              + ", ".join(f"{k}={v}" for k, v in sorted(speaker_kwargs.items())))
    if offline_mode:
        print("   Offline mode active (HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE).")

    try:
        from pyannote.audio import Pipeline
        import torch
    except (ImportError, OSError) as e:
        message = f"pyannote.audio not importable: {e}"
        print(f"   ⚠️  {message}")
        print("   Skipping speaker diarisation...")
        source_info['error'] = message
        return None, source_info

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    pipeline_obj = None
    attempts_desc: list[str] = []

    explicit_local = any(a['kind'] != 'hf_loader' for a in plan['attempts'])

    for attempt in plan['attempts']:
        kind = attempt['kind']
        path = attempt['path']
        label = attempt['source_label']

        if kind in ('local_config', 'local_path'):
            what = "local config" if kind == 'local_config' else "local path"
            attempts_desc.append(f"{what} '{path}'")
            try:
                print(f"   Loading diarisation pipeline from {what}: {path}")
                config_file = _resolve_local_pipeline_path(path)
                pipeline_obj = Pipeline.from_pretrained(config_file)
                if pipeline_obj is None:
                    raise RuntimeError("pyannote returned no pipeline")
                source_info['source'] = label
                source_info['model_path'] = path
                # A local config is no Hub snapshot, so model_revision stays
                # None and model_path says what was loaded. The models it
                # names may still come from pyannote's cache.
                source_info['sub_model_revisions'] = _sub_model_revisions(
                    config_file)
                source_info['error'] = None
                break
            except Exception as e:
                print(f"   ⚠️  Could not load from {what}: {_load_failure(e)}")
                source_info['error'] = f"{what} failed: {_load_failure(e)}"

        elif kind == 'hf_loader':
            if explicit_local:
                # Every pipeline the user named has failed. Loading the
                # default Hub model instead would diarise with a model the
                # user did not choose, recorded only in a provenance field.
                message = (
                    f"Diarisation model could not be loaded. Tried: "
                    f"{'; '.join(attempts_desc)}. Not falling back to "
                    f"'{path}' from the Hub because a local pipeline was "
                    f"requested; omit --diarization-config and "
                    f"--diarization-model-path to use it. Last error: "
                    f"{source_info['error']}"
                )
                print(f"   ⚠️  {message}")
                source_info['error'] = message
                return None, source_info
            hf_token = _resolve_hf_token()
            attempts_desc.append(
                f"HuggingFace loader for '{path}'"
                f"{' (offline, cache only)' if offline_mode else ''}"
            )
            try:
                if offline_mode:
                    print(f"   Loading {path} via HuggingFace cache "
                          f"(offline mode, no download)...")
                else:
                    print(f"   Loading {path} via HuggingFace "
                          f"(cache or download)...")
                pipeline_obj = Pipeline.from_pretrained(
                    path, **_pipeline_load_kwargs(
                        Pipeline.from_pretrained, hf_token, offline_mode))
                if pipeline_obj is None:
                    # pyannote 3.x prints its own notice and returns None
                    # for a gated model when the token is missing or the
                    # terms were not accepted, rather than raising.
                    raise RuntimeError(
                        "pyannote returned no pipeline (gated model: token "
                        "missing or terms not accepted)")
                source_info['source'] = label
                config_file, source_info['model_revision'] = _cached_snapshot(
                    path, _PIPELINE_CONFIG_NAME)
                source_info['sub_model_revisions'] = (
                    _sub_model_revisions(config_file) if config_file else None)
                source_info['error'] = None
                break
            except Exception as e:
                tried = "; ".join(attempts_desc)
                damage = _damaged_pipeline_cache(path)
                if damage:
                    # The token and cache advice below would mislead: a
                    # token does not repair a damaged cached file, and a
                    # download keeps it. A missing token is still named,
                    # since fetching the file again needs one.
                    no_token = ("" if offline_mode or hf_token else
                                " No HuggingFace token was found either (HF_TOKEN "
                                "or hf_token.txt), and fetching the file again "
                                "needs one.")
                    message = (
                        f"Diarisation model could not be loaded"
                        f"{' in offline mode' if offline_mode else ''}. "
                        f"Tried: {tried}. {damage}{no_token} "
                        f"Underlying error: {_load_failure(e)}"
                    )
                elif offline_mode:
                    expected = _expected_pipeline_cache_path(path)
                    message = (
                        f"Diarisation model could not be loaded in offline "
                        f"mode. Tried: {tried}. Expected the model to be "
                        f"pre-populated under '{expected}'. Either populate "
                        f"that cache (setup/cache_pyannote_arc.py does, on "
                        f"a machine with Hub access), pass "
                        f"--diarization-model-path or "
                        f"--diarization-config, or unset HF_HUB_OFFLINE / "
                        f"TRANSFORMERS_OFFLINE to allow a download. "
                        f"Underlying error: {_load_failure(e)}"
                    )
                else:
                    message = (
                        f"Diarisation model could not be loaded. Tried: {tried}. "
                        "Ensure a HuggingFace token is available (HF_TOKEN env "
                        "var or hf_token.txt) and that you have accepted the "
                        "model's terms of service on the Hub. "
                        f"Underlying error: {_load_failure(e)}"
                    )
                print(f"   ⚠️  {message}")
                source_info['error'] = message
                return None, source_info

    try:
        pipeline_obj.to(device)
        print(f"   Model loaded on {device} (source: {source_info['source']})")

        # Apply optional VAD threshold overrides, reporting only what the
        # pipeline actually accepted (see _apply_vad_thresholds).
        _vad_applied, _vad_message = _apply_vad_thresholds(
            pipeline_obj, vad_onset, vad_offset)
        if _vad_message:
            print(f"   {'' if _vad_applied else '⚠️  '}{_vad_message}")
        source_info['vad_applied'] = _vad_applied or None

        print("   Running diarisation (this may take a while)...")
        # Hand pyannote an already-decoded waveform rather than a path.  Given
        # a path it reads the file itself through libsndfile, which cannot
        # open compressed containers such as .m4a and fails with "Format not
        # recognised"; decoding here routes those formats through ffmpeg via
        # audio_io.  Falling back to the path keeps the previous behaviour if
        # decoding is unavailable for any reason.  Only the decoding is
        # guarded: an inference failure (CUDA out of memory, say) used to be
        # caught here too, reported as a decode failure, and the whole
        # pipeline re-run from the path, doubling the GPU time and reporting
        # the second error instead of the first.
        diarization_input = audio_path
        if _HAS_AUDIO_IO:
            try:
                _wave, _wave_sr = load_audio(audio_path, sr=16000, mono=True)
                diarization_input = {
                    "waveform": torch.from_numpy(
                        np.asarray(_wave, dtype=np.float32)).unsqueeze(0),
                    "sample_rate": _wave_sr,
                }
            except Exception as _dia_decode_error:
                print(f"   ⚠️  In-memory decode failed "
                      f"({_dia_decode_error}); pyannote will read the file "
                      f"path itself")
        diarization = pipeline_obj(diarization_input, **speaker_kwargs)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                'start': float(turn.start),
                'end': float(turn.end),
                'speaker': speaker,
            })

        n_speakers = len({seg['speaker'] for seg in segments})
        print(f"   ✅ Diarisation complete: {len(segments)} segments, "
              f"{n_speakers} speaker(s)")
        source_info['error'] = None
        return segments, source_info
    except Exception as e:
        message = f"diarisation runtime failure: {e}"
        print(f"   ⚠️  {message}")
        source_info['error'] = message
        return None, source_info

#: The distribution name setup.py installs this workflow under.
_DIST_NAME = "speech-transcription-system"


def _latest_release(versions_file=None):
    """Return the newest release listed in versions.csv, or ``None``.

    Rows are ordered by their ISO ``date``. Of two rows with the same date
    the higher version number wins, whichever comes first in the file:
    versions.csv lists the newest release first, so its row order cannot
    break the tie (2.1.0 and 2.1.1 share a date, and the row below won
    before). Only versions without a number fall back on the later row.
    ``None`` when the file is absent, empty or unreadable.
    """
    path = Path(versions_file) if versions_file else Path(__file__).parent / "versions.csv"
    try:
        with open(path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    rows = [r for r in rows if (r.get('version') or '').strip()]
    if not rows:
        return None
    def _number(version):
        return tuple(int(part) for part in re.findall(r'\d+', version))

    newest = max(enumerate(rows), key=lambda item: (
        (item[1].get('date') or ''), _number(item[1]['version']), item[0]))
    return newest[1]['version'].strip()


@functools.lru_cache(maxsize=1)
def get_latest_version():
    """Return a readable version string for the code that is running.

    From a git checkout the string is the newest release in versions.csv
    followed by the commit, as a PEP 440 local label: ``1.0.0+g1a2b3c4d5e6f``,
    with ``.dirty`` appended when tracked files differ from that commit.
    The release number alone once stamped every transcript as 1.0.0 however
    much the code had changed since (audit finding T2-02); the commit
    identifies the code exactly, and the release number stays for a human
    reader. The commit is read through :func:`provenance.git_commit`, the
    helper the run manifests and evaluation summaries use, and only when
    this script sits at the root of its checkout, so that a copy installed
    inside some other repository does not report that repository's commit.

    Without git the release alone is returned: from versions.csv, or from
    the installed distribution's metadata when the file was not shipped,
    or ``"Unknown"``.

    Returns:
        str: the version string.

    Side effects: runs ``git`` once per process; the result is cached.
    """
    release = _latest_release()
    here = Path(__file__).resolve().parent
    commit = dirty = None
    if (here / ".git").exists():
        try:
            from provenance import git_commit
        except ImportError:
            git_commit = None
        if git_commit is not None:
            commit, dirty = git_commit(here)
    if commit:
        return (f"{release or 'unreleased'}+g{commit[:12]}"
                f"{'.dirty' if dirty else ''}")
    if release:
        return release
    try:
        from importlib import metadata
        return metadata.version(_DIST_NAME)
    except Exception:
        return "Unknown"

def save_transcript_file(output_file, formatted_text, base_name, input_file, *,
                        original_filename=None, model=None, language=None,
                        mask_names=False, fix_repetitions=False,
                        use_facebook_names=False, use_facebook_surnames=False,
                        enhance_audio_enabled=False, speaker_attribution=False,
                        language_assumed=False):
    """
    Save transcript to file with appropriate headers.

    Args:
        output_file: Path to output file
        formatted_text: Formatted transcript text
        base_name: Base name for display when there is no original_filename
        input_file: Original input file path
        original_filename: Original filename (if different from input_file)
        model: Model used for transcription
        language: Language specified (if any)
        mask_names: Whether name masking was enabled
        fix_repetitions: Whether repetition fixing was enabled
        use_facebook_names: Whether Facebook names database was used
        use_facebook_surnames: Whether Facebook surnames database was used
        enhance_audio_enabled: Whether audio enhancement was enabled
        speaker_attribution: Whether this file has speaker labels

    The settings are keyword-only: the call sites once passed a dozen of
    them positionally, in a different order from create_word_document's.
    Writes *output_file*; errors propagate to the caller.
    """
    # newline='\n': the same transcript must hash the same on Windows and
    # Linux, because run manifests record every artefact's SHA-256.
    with open(output_file, 'w', encoding='utf-8', newline='\n') as f:
        # Add title with filename
        display_filename = Path(original_filename).stem if original_filename else base_name
        title = display_filename.replace('_', ':')  # see _transcript_title
        f.write(f"{title}\n")
        f.write(f"{'='*len(title)}\n\n")

        for line in _transcript_header_lines(
                input_file=input_file, original_filename=original_filename,
                model=model, language=language, mask_names=mask_names,
                fix_repetitions=fix_repetitions,
                use_facebook_names=use_facebook_names,
                use_facebook_surnames=use_facebook_surnames,
                enhance_audio_enabled=enhance_audio_enabled,
                speaker_attribution=speaker_attribution,
                language_assumed=language_assumed):
            f.write(f"{line}\n")

        f.write(f"{'='*len(display_filename)}\n\n")

        # Write transcription
        f.write(formatted_text + "\n\n")

def _speaker_lookup(diarization_segments):
    """Prepare diarisation segments for repeated interval queries.

    Returns ``(segments, starts, max_ends)`` where *segments* is sorted by
    start time, *starts* supports a bisect lookup, and *max_ends[i]* is the
    largest end time among segments ``0..i``.

    That last array is what makes the backward scan correct. Diarisation
    output is sorted by start but **not** by end, because a speaker's long
    turn can enclose short interjections by others: pyannote emits one
    track per speaker, so overlapping speech produces overlapping
    segments. A scan that stops at the first segment ending before the
    query would therefore stop at an enclosed interjection and never reach
    the enclosing turn. Comparing against the running maximum instead
    stops only when no earlier segment can possibly reach the query.
    """
    segments = sorted(diarization_segments or [], key=lambda s: s['start'])
    starts, max_ends = [], []
    running = float('-inf')
    for seg in segments:
        starts.append(seg['start'])
        running = max(running, seg['end'])
        max_ends.append(running)
    return segments, starts, max_ends


def _assign_speaker_to_interval(start, end, sorted_segments, segment_starts,
                                fallback_speaker, segment_max_ends=None):
    """Return the speaker whose diarisation segment overlaps ``[start, end]``
    most, falling back to ``fallback_speaker`` (carry-forward) or
    ``'SPEAKER_UNKNOWN'`` when no segment overlaps. A zero-length interval
    goes to the latest-starting segment that contains it, half-open.

    ``sorted_segments`` must be sorted by ``start`` and ``segment_starts``
    is the pre-extracted list of start times used for bisect lookup.
    ``segment_max_ends`` is the prefix maximum of end times from
    :func:`_speaker_lookup`; when it is not supplied it is derived here, at
    the cost of a linear pass, so that older callers stay correct.
    """
    import bisect
    if not sorted_segments:
        return fallback_speaker or 'SPEAKER_UNKNOWN'
    if end is None or end < start:
        end = start
    if segment_max_ends is None:
        segment_max_ends = []
        running = float('-inf')
        for seg in sorted_segments:
            running = max(running, seg['end'])
            segment_max_ends.append(running)
    # A zero-length query (a word with no end time, or one the timeline
    # repair clamped to its start) overlaps every segment by zero, so the
    # overlap rule alone can never select one and the word would inherit
    # the previous speaker even from inside another speaker's turn. Such a
    # point is instead given to the segment that contains it, half-open
    # [start, end) so a word at a turn boundary goes to the turn it opens.
    is_point = end <= start
    containing_speaker = None
    # Locate the first segment whose start is after ``end`` (upper bound).
    hi = bisect.bisect_right(segment_starts, end)
    # Walk backwards from ``hi - 1`` while any earlier segment could still
    # reach ``start``.
    best_speaker = None
    best_overlap = 0.0
    i = hi - 1
    while i >= 0:
        if segment_max_ends[i] <= start:
            break
        seg = sorted_segments[i]
        overlap = max(0.0, min(end, seg['end']) - max(start, seg['start']))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = seg['speaker']
        elif (is_point and containing_speaker is None
              and seg['start'] <= start < seg['end']):
            # The scan runs from the latest start backwards, so the first
            # containing segment is the latest-starting one: an enclosed
            # interjection wins over the long turn around it.
            containing_speaker = seg['speaker']
        i -= 1
    if best_speaker is not None:
        return best_speaker
    if containing_speaker is not None:
        return containing_speaker
    return fallback_speaker or 'SPEAKER_UNKNOWN'


def _attribute_chunks_to_speakers(chunks, diarization_segments):
    """Assign a speaker label to each word/short chunk from the ASR pipeline.

    Returns a list of ``{'start', 'end', 'text', 'speaker'}`` dicts in input
    order. The last seen speaker is carried forward into silent gaps so
    short pauses between words by the same speaker do not produce
    ``SPEAKER_UNKNOWN`` runs.
    """
    if not chunks:
        return []
    sorted_segments, segment_starts, segment_max_ends = _speaker_lookup(
        diarization_segments)
    attributed = []
    last_speaker = None
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        ts = chunk.get('timestamp') or (None, None)
        start, end = ts
        if start is None:
            continue
        if end is None:
            end = start
        speaker = _assign_speaker_to_interval(
            float(start), float(end),
            sorted_segments, segment_starts,
            fallback_speaker=last_speaker,
            segment_max_ends=segment_max_ends,
        )
        attributed.append({
            'start': float(start),
            'end': float(end),
            'text': (chunk.get('text') or '').strip(),
            'speaker': speaker,
        })
        last_speaker = speaker
    return attributed


def _format_attributed_text(attributed_chunks):
    """Render ``attributed_chunks`` as a transcript with ``[SPEAKER_xx]``
    prefixes, grouping consecutive same-speaker chunks into paragraphs.
    """
    paragraphs: list[tuple[str, list[str]]] = []
    for entry in attributed_chunks:
        text = (entry.get('text') or '').strip()
        if not text:
            continue
        speaker = entry.get('speaker') or 'SPEAKER_UNKNOWN'
        if paragraphs and paragraphs[-1][0] == speaker:
            paragraphs[-1][1].append(text)
        else:
            paragraphs.append((speaker, [text]))
    return "\n\n".join(
        f"[{spk}] {' '.join(words)}" for spk, words in paragraphs
    )


def apply_speaker_labels_to_transcript(transcript_text, diarization_segments,
                                       audio_duration, chunks=None):
    """Apply speaker labels to a transcript.

    Preferred path: when word-level ``chunks`` from the ASR pipeline are
    supplied, attribution is computed from the actual word timestamps using
    greatest-interval overlap against the diarisation segments.

    Legacy path: when ``chunks`` is ``None`` the function falls back to a
    uniform time-per-word approximation against ``audio_duration``. This is
    only kept so that callers without timestamps continue to work; new code
    should always supply ``chunks``. The pipeline always does, because
    speaker attribution forces word timestamps, so the legacy path is
    reached only when the ASR result carries no timed chunks at all.

    Returns the transcript with one ``[SPEAKER] text`` paragraph per turn,
    separated by blank lines, or *transcript_text* unchanged when there are
    no diarisation segments. Words that no segment covers carry the
    previous speaker forward, or ``SPEAKER_UNKNOWN`` before the first
    covered word; no word is ever dropped.
    """
    if not diarization_segments:
        return transcript_text

    if chunks:
        attributed = _attribute_chunks_to_speakers(chunks, diarization_segments)
        if attributed:
            print(f"   ✅ Speaker labels applied to {len(attributed)} chunks")
            return _format_attributed_text(attributed)
        # Otherwise fall through to legacy approximation.

    print("   Applying speaker labels to transcript (legacy approximation)...")
    words = transcript_text.split()
    if not words:
        return transcript_text
    time_per_word = audio_duration / len(words) if audio_duration else 0
    result_lines = []
    current_speaker = None
    current_text: list[str] = []
    for idx, word in enumerate(words):
        current_time = idx * time_per_word
        speaker_for_word = None
        for seg in diarization_segments:
            if seg['start'] <= current_time <= seg['end']:
                speaker_for_word = seg['speaker']
                break
        # Uncovered words carry the previous speaker forward. Before the
        # first covered word there is none, and those words used to be
        # labelled "[None]", or dropped altogether when no word was covered.
        speaker = speaker_for_word or current_speaker or 'SPEAKER_UNKNOWN'
        if speaker != current_speaker:
            if current_text:
                result_lines.append(f"[{current_speaker}] {' '.join(current_text)}")
            current_speaker = speaker
            current_text = [word]
        else:
            current_text.append(word)
    if current_text:
        result_lines.append(f"[{current_speaker}] {' '.join(current_text)}")
    print("   ✅ Speaker labels applied (legacy)")
    return '\n\n'.join(result_lines)

#: Chunked long-form decoding windows, in seconds, for the transformers ASR
#: pipeline. 30 s is Whisper's native input window (Radford et al., 2023),
#: used whenever timestamps are requested; the plain path uses shorter
#: chunks. TODO: justify (source unknown) the plain 15/2 values and both
#: strides; they date from fbabc7c without a stated reason. Because
#: --speaker-attribution forces word timestamps, it also switches to the
#: 30/5 windows, so its unlabelled transcript can differ in wording from a
#: plain run on the same audio. The manuscript reports these values, and
#: setup/download_model.py and evaluation/benchmark_timestamps.py repeat
#: them; changing them here changes committed example transcripts.
ASR_CHUNK_S_TIMESTAMPED, ASR_STRIDE_S_TIMESTAMPED = 30, 5
ASR_CHUNK_S_PLAIN, ASR_STRIDE_S_PLAIN = 15, 2


def transcribe_audio_only(audio_path, model="openai/whisper-large-v3", language=None,
                          return_timestamps=False):
    """Perform transcription only - no diarization.

    Args:
        audio_path: path to audio file.
        model: HuggingFace model ID.
        language: optional language hint.
        return_timestamps: False (no timestamps), True/'segment' (segment-level),
            or 'word' (word-level). Word-level enables `chunks` containing
            ``{'text': ..., 'timestamp': (start, end)}`` entries used for
            generating ``.json`` and ``.vtt`` outputs. Any timestamps also
            switch the decoding windows (see ASR_CHUNK_S_TIMESTAMPED).

    Returns:
        ``None`` if the model cannot be loaded or transcription fails (the
        error is printed). Otherwise the transformers pipeline's dict:
        ``text``, ``chunks`` when timestamps were requested, and, when no
        *language* was given, a ``language`` key holding the detected
        language's full name (see :func:`detect_audio_language`). This
        project also adds ``audio_duration_s``, the length of the decoded
        recording in seconds, which the review's truncation check needs
        and which is otherwise measured only when speakers are attributed
        (audit finding T3-05).

    Side effects:
        Builds the ASR pipeline on every call, which loads the model and
        downloads it on first use unless it is cached; callers transcribing
        many files pay that cost per file. Uses the GPU when available.
    """
    print("  Transcribing audio (no diarization)...")

    try:
        device = 0 if torch.cuda.is_available() else -1

        # Map our argument onto the transformers pipeline expectation.
        if return_timestamps == 'word':
            timestamps_arg = 'word'
        elif return_timestamps in (True, 'segment'):
            timestamps_arg = True
        else:
            timestamps_arg = False

        # Base pipeline arguments
        pipeline_args = {
            "model": model,  # User-specified or default model
            "dtype": torch.float16 if torch.cuda.is_available() else torch.float32,
            "device": device,
            "return_timestamps": timestamps_arg,
            "chunk_length_s": (ASR_CHUNK_S_TIMESTAMPED if timestamps_arg
                               else ASR_CHUNK_S_PLAIN),
            "stride_length_s": (ASR_STRIDE_S_TIMESTAMPED if timestamps_arg
                                else ASR_STRIDE_S_PLAIN),
            "ignore_warning": True
        }

        if language:
            pipeline_args["generate_kwargs"] = {"language": language}
            print(f"   Language set to {language.title()}")

        transcriber = pipeline("automatic-speech-recognition", **pipeline_args)
        print(f"   Transcription model loaded (device: {'GPU' if device >= 0 else 'CPU'})")
        if timestamps_arg:
            print(f"   Timestamps: {timestamps_arg}")
    except Exception as e:
        print(f"   Failed to load transcription model: {e}")
        return None

    # Perform transcription
    print("    Running transcription...")
    try:
        # Decode here rather than letting transformers invoke ffmpeg itself,
        # and go through audio_io so that compressed containers such as .m4a
        # load wherever any ffmpeg exists, bundled or system.
        if _HAS_AUDIO_IO:
            audio_array, sr = load_audio(audio_path, sr=16000)
        else:
            audio_array, sr = librosa.load(audio_path, sr=16000)
        transcription_result = transcriber(audio_array)
        print("     Transcription completed")
        # The recording is already decoded here, so its length costs
        # nothing, where measuring it again from the file would decode it
        # a second time.
        if isinstance(transcription_result, dict) and sr:
            transcription_result.setdefault(
                "audio_duration_s", len(audio_array) / float(sr))
        # The Hub snapshot the model was loaded from, for the run manifest
        # (audit finding DEPS-04). The load is not pinned to a revision,
        # because an offline machine whose cache holds a different snapshot
        # would then fail to load at all; recording it says which one ran.
        if isinstance(transcription_result, dict):
            transcription_result.setdefault(
                "model_revision", _loaded_model_revision(transcriber))

        # When the caller gave no language hint, ask the model which language
        # it heard, so that the post-processing gate can skip the
        # English-only clean-text stages on non-English audio.  This is a
        # separate, cheap forward pass over the first mel segment rather than
        # the ASR pipeline's return_language reporting, which is empty on the
        # transformers versions this project runs (see detect_audio_language).
        # The result is stored under the top-level ``language`` key, which is
        # this project's convention and what _detected_language reads.
        if not language and isinstance(transcription_result, dict):
            detected = detect_audio_language(transcriber, audio_array, sr)
            if detected:
                transcription_result.setdefault("language", detected)

        return transcription_result
    except Exception as e:
        print(f"   Transcription failed: {e}")
        return None


def _format_vtt_timestamp(seconds):
    """Format seconds as WebVTT timestamp ``HH:MM:SS.mmm``.

    The value is rounded to whole milliseconds before it is split into
    fields. Formatting the fractional seconds last, as this once did,
    rounded 59.9996 up to '60.000' without carrying into the minutes, a
    cue time WebVTT parsers reject.
    """
    if seconds is None:
        seconds = 0.0
    total_ms = round(max(0.0, float(seconds)) * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


#: Caption segmentation: a new cue starts after a pause longer than
#: _CAPTION_MAX_GAP_S, when the cue would exceed _CAPTION_MAX_CHARS, or
#: after sentence-final punctuation. TODO: justify (source unknown) both
#: values; they shape the committed case-study cues and the review flags.
_CAPTION_MAX_GAP_S = 1.0
_CAPTION_MAX_CHARS = 180
#: A chunk shorter than this is taken to be word-level output rather than
#: a sentence-level segment. TODO: justify (source unknown).
_WORD_CHUNK_MAX_S = 2.5


def _build_segments_from_chunks(chunks, max_gap=_CAPTION_MAX_GAP_S,
                                max_chars=_CAPTION_MAX_CHARS):
    """Group word/short chunks into readable caption-sized segments.

    Returns a list of ``{'start', 'end', 'text', 'words': [...]}`` dicts.
    """
    segments = []
    current = None
    for chunk in chunks or []:
        ts = chunk.get('timestamp') if isinstance(chunk, dict) else None
        text = (chunk.get('text') if isinstance(chunk, dict) else '') or ''
        text = text.strip()
        if not text or not ts:
            continue
        start, end = ts
        if start is None:
            continue
        if end is None:
            end = start
        word_entry = {'word': text, 'start': float(start), 'end': float(end)}
        if current is None:
            current = {'start': float(start), 'end': float(end),
                       'text': text, 'words': [word_entry]}
            continue
        gap = float(start) - current['end']
        joined_len = len(current['text']) + 1 + len(text)
        ends_sentence = current['text'].endswith(('.', '!', '?'))
        if gap > max_gap or joined_len > max_chars or ends_sentence:
            segments.append(current)
            current = {'start': float(start), 'end': float(end),
                       'text': text, 'words': [word_entry]}
        else:
            current['end'] = float(end)
            current['text'] = (current['text'] + ' ' + text).strip()
            current['words'].append(word_entry)
    if current is not None:
        segments.append(current)
    return segments


# The benchmark that measures timeline defects (evaluation/benchmark_podcast)
# tolerates discrepancies below a microsecond; repairs smaller than this are
# still clamped, for exactness, but are not counted, so the recorded counts
# stay comparable to the violation counts a reader would measure.
_TIMELINE_EPS = 1e-6


def _timed(value) -> bool:
    """True when *value* is a real, comparable timestamp.

    ``None`` means the word carries no timing; NaN compares false against
    everything and would silently disable the repairs around it, so both are
    treated as untimed and skipped.
    """
    return value is not None and value == value


def _longest_ordered_run(values):
    """Return the index set of one longest non-decreasing subsequence.

    Patience algorithm, O(n log n). The repair uses it to choose which
    words to retime: everything outside a longest ordered run is, by
    construction, the smallest set of words whose adjustment makes the
    whole sequence run forwards. Without this, a single word glitched far
    ahead of its true position would drag every later word up to it; with
    it, the glitched word is the one that moves.
    """
    import bisect
    tails: list = []      # smallest attainable tail value per run length
    tail_idx: list = []   # index of the element holding that tail
    prev = [None] * len(values)
    for i, value in enumerate(values):
        j = bisect.bisect_right(tails, value)
        if j == len(tails):
            tails.append(value)
            tail_idx.append(i)
        else:
            tails[j] = value
            tail_idx[j] = i
        if j:
            prev[i] = tail_idx[j - 1]
    kept = set()
    k = tail_idx[-1] if tail_idx else None
    while k is not None:
        kept.add(k)
        k = prev[k]
    return kept


def _repair_segment_timeline(segments):
    """Make the timeline physically consistent, and count what that took.

    Whisper's word timestamps come from its attention weights, and a long
    recording occasionally yields a word timed far from its true position;
    segment cues built from such words can then overlap. Every downstream
    consumer of the timeline (captioning, alignment, the audio redactor's
    span arithmetic) is entitled to assume time runs forwards, so the
    pipeline repairs the timeline before writing it and discloses the
    repair counts in the JSON payload as ``timeline_repairs``.

    The repair touches the fewest words possible. The words on a longest
    non-decreasing run of start times are trusted as the timeline's spine
    and never retimed; only the words outside it, the minimal set by
    construction, are moved into the interval their trusted neighbours
    define. An early version instead raised every subsequent word to a
    glitched one's time, which kept the timeline consistent but let one
    glitch distort dozens of neighbours. On the case-study episode it
    clamped 131 timings (job 8441879), where this one retimed 64 words,
    clamped 4 cues and merged 3 (job 8983112).

    After the word pass: a word ending before it starts has its end raised
    to its start; segment cues are re-derived from their words' envelope
    wherever timed words exist; a cue that still overlaps its predecessor
    is clamped forward, carrying its words with it; and a cue swallowed
    whole by its predecessor is merged into it, text and words, rather
    than being collapsed into a zero-length cue.

    Two counters record word movement, and they are kept apart because
    they mean different things. ``word_retimed`` counts words moved by the
    minimal retiming above, which is the repair proper.
    ``word_order_enforced`` counts words moved by the running-maximum net
    in :func:`_enforce_flat_word_order`, which should have nothing left to
    do once the retiming and the cue repairs have run. A non-zero value
    there is therefore a signal about this function rather than about the
    model: it says some case reached the net that the earlier passes were
    expected to have settled. They shared one counter until 2026-08-11,
    which made exactly that distinction impossible to draw from a payload.

    Counts track only material changes (beyond the one-microsecond
    tolerance the timeline benchmark itself uses); sub-tolerance wobble is
    left in place, exactly as the benchmark disregards it. NaN timings are
    normalised to ``None`` (untimed) first, both because NaN comparisons
    would silently disable the repairs around them and because NaN is not
    valid strict JSON. A payload with zero counts therefore certifies that
    no material defect was found.

    Mutates *segments* in place (the list object is preserved, so callers
    holding a reference see the merged result) and returns the counts.
    """
    counts = {
        "word_retimed": 0,
        "word_order_enforced": 0,
        "word_end_clamped": 0,
        "segment_overlap_clamped": 0,
        "segment_merged": 0,
    }

    # Pass 0: normalise NaN timings to None so nothing downstream has to
    # reason about a value that compares false with everything.
    for segment in segments:
        for key in ("start", "end"):
            if segment.get(key) is not None and not _timed(segment.get(key)):
                segment[key] = None
        for word in segment.get("words") or []:
            for key in ("start", "end"):
                if word.get(key) is not None and not _timed(word.get(key)):
                    word[key] = None

    # Pass 1: retime the minimal set of words. Start times are compared at
    # the benchmark's own tolerance (rounding to the microsecond), so
    # float wobble does not evict a healthy word from the trusted run.
    flat = [w for segment in segments for w in segment.get("words") or []
            if _timed(w.get("start")) and _timed(w.get("end"))]
    if flat:
        kept = _longest_ordered_run([round(w["start"], 6) for w in flat])
        next_kept_start = [None] * len(flat)
        upcoming = None
        for i in range(len(flat) - 1, -1, -1):
            next_kept_start[i] = upcoming
            if i in kept:
                upcoming = flat[i]["start"]
        previous_kept_start = None
        for i, word in enumerate(flat):
            if i in kept:
                previous_kept_start = word["start"]
                continue
            anchor = (previous_kept_start if previous_kept_start is not None
                      else next_kept_start[i])
            if anchor is None:
                continue
            new_start = anchor
            new_end = word["end"]
            if next_kept_start[i] is not None:
                new_end = min(new_end, next_kept_start[i])
            new_end = max(new_end, new_start)
            if (abs(new_start - word["start"]) > _TIMELINE_EPS
                    or abs(new_end - word["end"]) > _TIMELINE_EPS):
                counts["word_retimed"] += 1
            word["start"], word["end"] = new_start, new_end

    # Pass 2: no word may end before it starts, trusted or not.
    for word in flat:
        if word["end"] < word["start"]:
            if word["start"] - word["end"] > _TIMELINE_EPS:
                counts["word_end_clamped"] += 1
            word["end"] = word["start"]

    # Passes 3 and 4 interact (a merge can hand a clamped host words that
    # a later cue derivation would move, and vice versa), so they run to a
    # fixpoint. Convergence is quick because every adjustment only raises
    # word timings or shrinks the segment list; the bound is a backstop.
    # The test suite checks that a full repair leaves the safety net
    # nothing to do, not that four passes always suffice, so running out
    # is reported instead of passing silently. The 'converged' key appears
    # only then, so ordinary payloads keep their shape.
    # TODO: justify (source unknown) the bound of four passes.
    for _iteration in range(4):
        changed = _repair_segment_cues(segments, counts)
        changed = _enforce_flat_word_order(segments, counts) or changed
        if not changed:
            break
    else:
        # The fourth pass changed something, which does not by itself mean
        # a fifth would: probe a copy, so the repaired data stay exactly
        # what four passes produce.
        import copy
        probe = copy.deepcopy(segments)
        probe_counts = dict(counts)
        still_changing = _repair_segment_cues(probe, probe_counts)
        still_changing = (_enforce_flat_word_order(probe, probe_counts)
                          or still_changing)
        if still_changing:
            counts["converged"] = False
            print("   ⚠️  Timeline repair did not reach a fixpoint in four "
                  "passes; the timestamps may still overlap.")

    return counts


def _repair_segment_cues(segments, counts):
    """One pass over segment cues: derive, merge, clamp. Returns whether
    anything changed.

    Cues follow their words' envelope wherever timed words exist. A cue
    that overlaps its predecessor is clamped forward, carrying its words.
    A cue swallowed whole by its predecessor is merged into it, text and
    words, rather than being collapsed into a zero-length cue; merged
    words are raised to the host's running word floor first, so a merge
    can never place a word behind the timeline it joins.
    """
    changed = False
    repaired: list = []
    previous_end = None
    word_floor = None      # last timed word start already emitted
    for segment in segments:
        words = [w for w in segment.get("words") or []
                 if _timed(w.get("start")) and _timed(w.get("end"))]
        if words:
            envelope_start = words[0]["start"]
            envelope_end = max(envelope_start,
                               max(w["end"] for w in words))
            if (segment.get("start") != envelope_start
                    or segment.get("end") != envelope_end):
                changed = True
            segment["start"], segment["end"] = envelope_start, envelope_end
        start, end = segment.get("start"), segment.get("end")
        if not _timed(start) or not _timed(end):
            repaired.append(segment)
            if words:
                word_floor = words[-1]["start"]
            continue
        if previous_end is not None and start < previous_end:
            if end <= previous_end + _TIMELINE_EPS and repaired:
                host = repaired[-1]
                floor = word_floor
                if floor is None and _timed(host.get("start")):
                    floor = host["start"]
                for word in words:
                    if floor is not None and word["start"] < floor:
                        word["start"] = floor
                    if word["end"] < word["start"]:
                        word["end"] = word["start"]
                    floor = word["start"]
                host["text"] = " ".join(
                    part for part in (str(host.get("text") or "").strip(),
                                      str(segment.get("text") or "").strip())
                    if part)
                if segment.get("words"):
                    host.setdefault("words", []).extend(segment["words"])
                if words:
                    word_floor = words[-1]["start"]
                    if _timed(host.get("end")):
                        host["end"] = max(host["end"],
                                          max(w["end"] for w in words))
                        previous_end = host["end"]
                counts["segment_merged"] += 1
                changed = True
                continue
            if previous_end - start > _TIMELINE_EPS:
                counts["segment_overlap_clamped"] += 1
            segment["start"] = start = previous_end
            changed = True
            # Carry the words with their cue: the clamp value is the
            # previous segment's end, at least every earlier word start,
            # so global word order is preserved.
            for word in words:
                if word["start"] < start:
                    word["start"] = start
                if word["end"] < word["start"]:
                    word["end"] = word["start"]
            if words:
                segment["end"] = max(start, max(w["end"] for w in words))
        if segment["end"] < segment["start"]:
            segment["end"] = segment["start"]
            changed = True
        previous_end = segment["end"]
        repaired.append(segment)
        if words:
            word_floor = words[-1]["start"]
    if len(repaired) != len(segments):
        changed = True
    segments[:] = repaired
    return changed


def _enforce_flat_word_order(segments, counts):
    """Guarantee non-decreasing word starts across the whole document.

    The minimal retiming and the cue repairs handle every case the
    production pipeline produces; this net exists so the guarantee is
    structural rather than an argument about which cases can occur. It is
    a running-maximum clamp, and on already-consistent input it does
    nothing. Returns whether anything changed.
    """
    changed = False
    previous_start = None
    for segment in segments:
        for word in segment.get("words") or []:
            start, end = word.get("start"), word.get("end")
            if not _timed(start) or not _timed(end):
                continue
            if previous_start is not None and start < previous_start:
                if previous_start - start > _TIMELINE_EPS:
                    counts["word_order_enforced"] += 1
                word["start"] = start = previous_start
                changed = True
            if end < start:
                if start - end > _TIMELINE_EPS:
                    counts["word_end_clamped"] += 1
                word["end"] = start
                changed = True
            previous_start = start
    return changed


# Keys under which a transcript segment or word may carry its text.
# ``_build_segments_from_chunks`` writes word text as ``word``; the shipped
# example artefacts use ``text``. Both occur, so redaction must
# cover either rather than assuming one, because masking a key that is not
# present would leave the real text untouched.
_TEXT_KEYS = ('text', 'word')


def _redact_segments(segments, mask_fn):
    """Return a copy of *segments* with every text field masked.

    Segment text and each constituent word are masked independently, so a
    name is removed from whichever field a reader happens to consult.
    Timings and speaker labels are copied unchanged, so the artefact stays
    usable for captioning and alignment while carrying no personal names.

    Each segment and word dict is a new dict, and every ``words`` list is a
    new list, even an empty one, so editing the redacted set never touches
    the raw one. Other nested values are shared (the copy is not deep); the
    pipeline stores none that anything mutates. A segment without a
    ``words`` key does not gain one, so both JSON files keep one shape.
    """
    def _mask_entry(entry):
        masked = dict(entry)
        for key in _TEXT_KEYS:
            if key in masked:
                masked[key] = mask_fn(masked.get(key) or '')
        return masked

    redacted = []
    for seg in segments:
        new_seg = _mask_entry(seg)
        if isinstance(seg.get('words'), list):
            new_seg['words'] = [_mask_entry(w) for w in seg['words']]
        redacted.append(new_seg)
    return redacted


def write_timestamped_outputs(transcription_result, output_dir, base_name,
                              audio_path, model=None, language=None,
                              diarization_segments=None,
                              diarization_source=None,
                              mask_fn=None, write_raw=True,
                              language_provenance=None):
    """Write timestamped outputs (``.json`` and ``.vtt``) from the pipeline
    result, before any text post-processing.

    Two parallel sets can be produced. The raw set preserves the model's
    output verbatim and therefore still contains any personal names that
    were spoken. When *mask_fn* is supplied, a ``_redacted`` set is written
    alongside it with the same timings and speaker labels but the names
    masked, so that a researcher exporting the output tree has a
    de-identified artefact to share. Setting *write_raw* to ``False``
    suppresses the unredacted set entirely, which is the strict mode for
    deployments that must not retain it.

    This preserves a faithful, machine-readable record of the model's
    output, with timing information intact, that downstream evaluation
    (e.g. WER scoring) and captioning workflows can rely on.

    When ``diarization_segments`` is supplied, each emitted segment gets
    a ``speaker`` field (greatest-interval overlap, carry-forward into
    silent gaps) and the VTT cue is wrapped with a ``<v SPEAKER_xx>``
    voice tag. The top-level JSON gains a ``pipeline`` block recording
    how the diarisation model was sourced (``local_config``, ``local_path``,
    ``hf_loader``, ``hf_loader_offline`` or ``unavailable``) and which Hub
    snapshots it loaded (``diarization_model_revision``,
    ``diarization_sub_model_revisions``), so reviewers can audit provenance
    after the fact.

    Returns a dict with paths to the files written.
    """
    os.makedirs(output_dir, exist_ok=True)
    chunks = transcription_result.get('chunks') if isinstance(transcription_result, dict) else None
    raw_text = (transcription_result.get('text', '')
                if isinstance(transcription_result, dict) else '')

    has_word_chunks = bool(chunks) and any(
        isinstance(c, dict) and c.get('timestamp') and
        (c['timestamp'][1] is None or
         (c['timestamp'][1] - (c['timestamp'][0] or 0.0)) < _WORD_CHUNK_MAX_S)
        for c in chunks
    )
    segments = _build_segments_from_chunks(chunks) if has_word_chunks else []
    if not segments and chunks:
        # Treat each chunk as its own segment.
        for c in chunks:
            if not isinstance(c, dict):
                continue
            ts = c.get('timestamp') or (None, None)
            start, end = ts
            if start is None:
                continue
            segments.append({
                'start': float(start),
                'end': float(end if end is not None else start),
                'text': (c.get('text') or '').strip(),
                'words': [],
            })

    # Repair the timeline before speakers are attached, so that speaker
    # assignment works from the corrected timings, and keep the counts for
    # the payload: zero everywhere certifies the model's own timing was
    # already consistent, and anything else says exactly how much was
    # clamped.
    timeline_repairs = _repair_segment_timeline(segments)

    # Attach a ``speaker`` to every segment when diarisation is available.
    if diarization_segments:
        sorted_segs, seg_starts, seg_max_ends = _speaker_lookup(
            diarization_segments)
        last_speaker = None
        for seg in segments:
            # The timeline repair normalises NaN timings to None and keeps
            # untimed words and segments, and None cannot be compared with
            # a diarisation time: querying with it raised TypeError, which
            # lost every timestamped artefact. An untimed item has no time
            # to look up, so it inherits the speaker around it instead.
            if _timed(seg.get('start')) and _timed(seg.get('end')):
                speaker = _assign_speaker_to_interval(
                    seg['start'], seg['end'], sorted_segs, seg_starts,
                    fallback_speaker=last_speaker,
                    segment_max_ends=seg_max_ends,
                )
            else:
                speaker = last_speaker or 'SPEAKER_UNKNOWN'
            seg['speaker'] = speaker
            last_speaker = speaker
            # Also stamp constituent words when present, for consumers that
            # want word-level voice tagging.
            for w in seg.get('words') or []:
                if not (_timed(w.get('start')) and _timed(w.get('end'))):
                    w['speaker'] = speaker
                    continue
                w['speaker'] = _assign_speaker_to_interval(
                    w['start'], w['end'],
                    sorted_segs, seg_starts, fallback_speaker=last_speaker,
                    segment_max_ends=seg_max_ends,
                )

    pipeline_block = {
        'asr_model': model,
        'asr_model_revision': (transcription_result.get('model_revision')
                               if isinstance(transcription_result, dict) else None),
        'language': language,
    }
    if language_provenance:
        # Where 'language' came from: requested, detected, or assumed when
        # neither was available (Whisper then chose the decoding language
        # itself, so the assumed value is only the post-processing one).
        pipeline_block.update(language_provenance)
    if diarization_source is not None:
        pipeline_block['diarization_model_source'] = diarization_source.get('source')
        pipeline_block['diarization_model_id'] = diarization_source.get('model_id')
        pipeline_block['diarization_model_revision'] = diarization_source.get(
            'model_revision')
        pipeline_block['diarization_sub_model_revisions'] = diarization_source.get(
            'sub_model_revisions')
        pipeline_block['diarization_model_path'] = diarization_source.get('model_path')
        pipeline_block['diarization_offline_mode'] = diarization_source.get('offline_mode', False)
        if diarization_source.get('error'):
            pipeline_block['diarization_error'] = diarization_source['error']

    json_payload = {
        'audio_file': os.path.basename(audio_path),
        'model': model,
        'language': language,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'pipeline': pipeline_block,
        'timeline_repairs': timeline_repairs,
        'text': raw_text,
        'segments': segments,
    }
    if diarization_segments is not None:
        json_payload['diarization_segments'] = [
            {'start': s['start'], 'end': s['end'], 'speaker': s['speaker']}
            for s in diarization_segments
        ]
    def _write_pair(suffix, segs, text, redacted):
        """Write one JSON/VTT pair and return their paths."""
        payload = dict(json_payload)
        payload['text'] = text
        payload['segments'] = segs
        payload['redacted'] = redacted
        j = os.path.join(output_dir, f"{base_name}_transcript{suffix}.json")
        with open(j, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        v = os.path.join(output_dir, f"{base_name}_transcript{suffix}.vtt")
        with open(v, 'w', encoding='utf-8', newline='\n') as f:
            f.write("WEBVTT\n\n")
            for i, seg in enumerate(segs, start=1):
                if not seg.get('text'):
                    continue
                f.write(f"{i}\n")
                f.write(f"{_format_vtt_timestamp(seg['start'])} --> "
                        f"{_format_vtt_timestamp(seg['end'])}\n")
                speaker = seg.get('speaker') if diarization_segments else None
                if speaker:
                    f.write(f"<v {speaker}>{seg['text'].strip()}</v>\n\n")
                else:
                    f.write(seg['text'].strip() + "\n\n")
        return j, v

    written = {'segments': segments}
    if write_raw:
        json_path, vtt_path = _write_pair("", segments, raw_text, False)
        written['json'] = json_path
        written['vtt'] = vtt_path
        print(f"   📄 Raw JSON written: {json_path}")
        print(f"   🎬 WebVTT captions written: {vtt_path}")
        if mask_fn is None:
            print("   ⚠️  These retain any spoken names: they are written "
                  "before masking.")

    if mask_fn is not None:
        r_json, r_vtt = _write_pair(
            "_redacted", _redact_segments(segments, mask_fn),
            mask_fn(raw_text or ''), True)
        written['json_redacted'] = r_json
        written['vtt_redacted'] = r_vtt
        print(f"   🛡️  Redacted JSON written: {r_json}")
        print(f"   🛡️  Redacted WebVTT written: {r_vtt}")

    return written

def _loaded_model_revision(transcriber):
    """Return the Hub commit *transcriber*'s model was loaded from, or None.

    transformers stores the snapshot it resolved, from the Hub or from the
    local cache, as ``config._commit_hash``; a model loaded from a plain
    directory has none, and that is recorded as None.
    """
    config = getattr(getattr(transcriber, 'model', None), 'config', None)
    revision = getattr(config, '_commit_hash', None)
    return revision if isinstance(revision, str) else None


def _software_provenance():
    """Return the workflow version, package versions and git commit of a run.

    Recorded in the run manifest because the same flags on a different
    transformers, torch or pyannote.audio can produce different text and
    speaker labels. ``version`` is the string the transcript headers carry
    (:func:`get_latest_version`), so a manifest and its transcripts can be
    matched. A package that is not installed, or a checkout without git,
    is recorded as ``None`` rather than failing the run.
    """
    from provenance import run_metadata
    meta = run_metadata(packages=('transformers', 'torch', 'pyannote.audio', 'gliner'))
    versions = {'python': meta['python'], **meta['packages']}
    return {'version': get_latest_version(), 'packages': versions,
            'git_commit': meta['git_commit'], 'git_dirty': meta['git_dirty']}


def _excluded_names_digest(excluded_names):
    """Summarise the exclusion list without writing the names themselves.

    The manifest travels with the de-identified outputs, so it records how
    many names were excluded and a SHA-256 of the sorted, lower-cased list,
    which lets two runs be compared without disclosing who was kept.
    """
    import hashlib
    names = sorted({str(n).strip().lower() for n in excluded_names or ()
                    if str(n).strip()})
    return {
        'count': len(names),
        'sha256': (hashlib.sha256('\n'.join(names).encode('utf-8')).hexdigest()
                   if names else None),
    }


#: A speaker-attributed paragraph as :func:`_format_attributed_text` writes
#: it: a bracketed label, one space, then the turn's text.
_SPEAKER_TURN_RE = re.compile(r'(\[[^\]\n]+\]) (.*)', re.DOTALL)

#: Text that ends a sentence: a full stop, question or exclamation mark,
#: optionally followed by closing quotes or brackets.
_SENTENCE_END_RE = re.compile(r'[.!?]["\')\]]*\s*$')

#: A turn that opens with the English pronoun "I" on its own or in a
#: contraction ("I'm", "I've"). The English-only stages capitalise it
#: wherever it stands, so its capital is not a sentence-initial one.
_PRONOUN_I_START_RE = re.compile(r"\s*I\b")


def postprocess_transcript_text(text, language, fix_repetitions=False,
                                mask_fn=None, get_log=None,
                                filename="unknown", speaker_turns=False):
    """Run the production clean-up and masking chain on a transcript.

    The chain is emoji and Unicode-artefact removal, the optional
    repetition repair, :func:`clean_transcription_text` and the optional
    name masker, in that order. It is the one place both the plain and the
    speaker-attributed transcripts are processed, so they cannot drift
    apart.

    Args:
        text: the transcript.
        language: passed to :func:`clean_transcription_text`.
        fix_repetitions: apply :func:`detect_and_fix_repetitions`.
        mask_fn: the masker's ``mask(text, filename)``, or ``None``.
        get_log: the masker's log accessor, read after each masking call.
        filename: recorded in each masking-log row.
        speaker_turns: *text* is speaker-attributed, one ``[LABEL] text``
            paragraph per turn separated by blank lines.

    Returns:
        ``(processed_text, replacement_log)``, the log being every row the
        masker produced (empty when masking is off).

    Every stage collapses whitespace, so run over a speaker-attributed
    transcript as one string the chain used to merge all turns into a
    single line, and the .docx into a single paragraph. With
    *speaker_turns* each turn's text is processed on its own and the label
    and blank-line separators are put back. The masker resets its log on
    every call, so the rows of each turn are gathered and renumbered here.
    Plain text (the default) goes through the chain exactly as before.

    Cleaning a turn on its own capitalises its first letter, which is right
    after a full stop but wrong where word-level attribution changed
    speaker mid-sentence. The masker takes any capitalised dictionary word
    for a name, so a turn break between "the" and "art of listening" lost
    "art" to ``[NAME]`` in the speaker-attributed transcript while the
    plain one kept it (audit finding PIPE-01). A turn whose previous turn
    did not end a sentence, and whose text started with a lower-case
    letter of any script (the letters :func:`_sentence_capitalise`
    capitalises), therefore gets that letter back before masking, so both
    transcripts reach the same masking decisions. English "I" keeps its
    capital, which the English-only stages give it in any position.
    """
    replacement_log = []
    english = _language_is_english(language)

    def _clean(body):
        """Return *body* before and after :func:`clean_transcription_text`."""
        body = remove_emojis_and_unicode_artifacts(body)
        if fix_repetitions:
            body = detect_and_fix_repetitions(body)
        return body, clean_transcription_text(body, language)

    def _mask(body):
        if mask_fn:
            body = mask_fn(body, filename)
            if get_log:
                for row in get_log():
                    row = dict(row)
                    row['order'] = len(replacement_log) + 1
                    replacement_log.append(row)
        return body

    if not speaker_turns:
        return _mask(_clean(text)[1]), replacement_log

    turns = []
    # The previous turn's cleaned, unmasked text. The cleaned form is used
    # because emoji removal can strip what followed a full stop.
    previous = None
    for paragraph in text.split('\n\n'):
        if not paragraph.strip():
            continue
        match = _SPEAKER_TURN_RE.fullmatch(paragraph.strip())
        before, body = _clean(match.group(2) if match else paragraph)
        first = _SENTENCE_INITIAL_LETTER_RE.match(before)
        if (previous is not None
                and not _SENTENCE_END_RE.search(previous)
                and first and first.group(2).islower()
                and not (english and _PRONOUN_I_START_RE.match(body))):
            body = _SENTENCE_INITIAL_LETTER_RE.sub(
                lambda m: m.group(1) + m.group(2).lower(), body, count=1)
        if body.strip():
            previous = body
        body = _mask(body)
        turns.append(f"{match.group(1)} {body}".rstrip() if match else body)
    return '\n\n'.join(turns), replacement_log


def write_review_file(segments, review_path, audio_duration_s=None,
                      mask_fn=None, review_options=None):
    """Flag suspect segments and write the review report to *review_path*.

    Args:
        segments: the raw (unmasked) timestamped segments.
        review_path: where the JSON report is written.
        audio_duration_s: recording length, which lets the review flag a
            transcript ending well before the audio does, something no
            per-segment check can see. The timestamp benchmark found that
            Whisper's last segment can end well before its clip, mostly
            with every word transcribed; on a whole recording such a
            shortfall can also mean speech left untranscribed, so the
            review flags it for a listen.
        mask_fn: the run's name masker, or ``None`` when masking is off.
        review_options: optional checks passed to
            :func:`confidence.review_transcript` (``flag_zero_duration``,
            ``repeated_passage_words``, ``repeated_passage_window_s``);
            ``None`` keeps the default review, which records no
            ``optional_checks`` block.

    Returns:
        The review dict that was written.

    Side effects:
        Writes *review_path*. Calls *mask_fn* once per flagged segment,
        which resets that masker's replacement log.

    The flags are computed on the raw segments so that the counts and
    rates are exactly those of an unmasked run; masking first could merge
    or empty tokens and shift the duplicate and speech-rate flags. Each
    flagged record copies its segment's text, though, and with masking on
    that copy must be masked: the review sits beside the redacted
    artefacts, and under --redacted-timestamps-only it was the one file in
    the tree that still carried the spoken names.
    """
    from confidence import review_transcript
    review = review_transcript({'segments': segments},
                               audio_duration_s=audio_duration_s,
                               **(review_options or {}))
    review['redacted'] = mask_fn is not None
    if mask_fn is not None:
        for record in review.get('flagged') or []:
            record['text'] = mask_fn(record.get('text') or '')
    with open(review_path, 'w', encoding='utf-8', newline='\n') as rf:
        json.dump(review, rf, indent=2, ensure_ascii=False)
    return review


def process_audio_file(input_file, mask_names=False, model="openai/whisper-large-v3",
                       language=None, original_filename=None, fix_repetitions=False,
                       output_name=None, save_name_masking_logs=False,
                       save_enhanced_audios=False, enhance_audio_enabled=False,
                       use_facebook_names=False, use_facebook_surnames=False,
                       selected_languages=None, speaker_attribution=False,
                       exclude_common_words=None, excluded_names=None, timestamps=False,
                       diarization_model_path=None, diarization_config=None,
                       vad_onset=None, vad_offset=None, redacted_timestamps_only=False,
                       num_speakers=None, min_speakers=None, max_speakers=None,
                       source_audio=None, source_derivation=None,
                       review_options=None):
    """Transcribe one recording and write every artefact the flags request.

    Args:
        input_file: the recording.
        mask_names: mask personal names (dictionary stage).
        model: Hugging Face id of the Whisper model.
        language: decoding and post-processing language; ``None`` lets
            Whisper detect it (see the language fields in the provenance).
        original_filename: the name to show and to derive outputs from
            when *input_file* is a temporary copy.
        fix_repetitions: apply :func:`detect_and_fix_repetitions`.
        output_name: base name for every output, overriding the file name.
        save_name_masking_logs: write the masking log (see
            :func:`save_replacement_log`).
        save_enhanced_audios: keep the enhanced recording under
            output/enhanced_audio instead of a deleted temporary file.
        enhance_audio_enabled: run :func:`enhance_audio` first.
        use_facebook_names, use_facebook_surnames, selected_languages:
            dictionary sources (see :func:`create_enhanced_name_masker`).
        speaker_attribution: diarise and label speakers. This forces word
            timestamps, so the timestamped JSON/VTT and review are written
            too, with 30 s decoding windows.
        exclude_common_words: ``None`` (the default) means decide from the
            language actually used: on for English, off otherwise. Pass
            ``False`` explicitly to keep common words in the dictionary.
        excluded_names: names never to mask, case-insensitive.
        timestamps: write the timestamped JSON/VTT and the review report.
        diarization_model_path, diarization_config, vad_onset, vad_offset,
        num_speakers, min_speakers, max_speakers: passed to
            :func:`perform_speaker_diarization`.
        redacted_timestamps_only: suppress the unredacted timestamped
            artefacts, leaving only the masked parallel set. It has an
            effect only when name masking is enabled, because without a
            masker there is nothing to write in their place.
        source_audio, source_derivation: the original recording and how
            *input_file* was made from it, recorded in the run manifest.
        review_options: optional review checks (see
            :func:`write_review_file`), recorded in the run manifest as
            ``review_settings``. They apply only when the timestamped
            outputs, and with them the review, are written.

    Returns:
        ``True`` when every requested artefact was written. ``False`` when
        processing failed, or when it finished but a requested artefact
        (timestamped outputs, review, speaker labels, a .docx or the
        manifest) could not be produced; the missing items are printed.

    Side effects:
        Writes under ``output/transcripts`` (and ``output/enhanced_audio``,
        ``name_masking_logs``) relative to the working directory:
        ``<name>_transcript.txt``/``.docx``, ``_with_speakers`` variants,
        ``_transcript[_redacted].json``/``.vtt``, ``_review.json`` and
        ``_manifest.json``. Existing files of the same name are
        overwritten. A temporary enhanced recording is always deleted.
        Loads the ASR (and diarisation) models, which may download them.
    """

    print(f"\n{'='*80}")
    print(f" PROCESSING: {input_file}")
    print(f"{'='*80}")

    if not AUDIO_LIBS_AVAILABLE or not TRANSFORMERS_AVAILABLE:
        print(" ❌ Error: Required audio processing libraries not available")
        print(f"    Audio libraries: {'✅' if AUDIO_LIBS_AVAILABLE else '❌'}")
        print(f"    Transformers: {'✅' if TRANSFORMERS_AVAILABLE else '❌'}")
        print("    Run `python -m preflight` for a full diagnosis with "
              "remedies for each missing piece")
        return False

    if not os.path.exists(input_file):
        print(f" Error: Audio file not found: {input_file}")
        return False

    # Artefacts the flags asked for that could not be produced. Each is
    # reported as it happens and the run then carries on, so the other
    # outputs are still written, but a non-empty list makes the run fail:
    # a job that silently lacks its timestamps, review, Word document,
    # speaker labels or manifest must not be recorded as a success.
    missing_artefacts = []

    # The enhanced recording is a full copy of the participant's audio. When
    # it is not being kept it lives in a temporary file, which the finally
    # clause below removes on every exit path, including an exception
    # raised after enhancement.
    enhanced_audio_path = None
    enhanced_audio_is_temporary = False

    try:
        # Step 1: Audio enhancement
        print("\n🎵 AUDIO ENHANCEMENT")
        print("-" * 40)

        # One name for every artefact of this run: --output-name if given,
        # else the original file name (for temporary-file processing), else
        # the input's. It used to be derived three times, and the enhanced
        # recording's copy ignored --output-name.
        base_name = output_name or Path(original_filename or input_file).stem
        if output_name:
            print(f"📝 Using custom output name: {output_name}")

        # Conditionally enhance audio based on enhance_audio_enabled flag
        audio_file_for_transcription = input_file  # Default to original file

        if enhance_audio_enabled:
            if save_enhanced_audios:
                os.makedirs(ENHANCED_AUDIO_DIR, exist_ok=True)
                enhanced_audio_path = f"{ENHANCED_AUDIO_DIR}/{base_name}_enhanced.wav"
                print(f"   🎧 Saving enhanced audio to: {enhanced_audio_path}")
            else:
                # Use temporary file if not saving enhanced audio
                import tempfile
                temp_fd, enhanced_audio_path = tempfile.mkstemp(suffix='.wav', prefix='enhanced_')
                enhanced_audio_is_temporary = True
                os.close(temp_fd)  # Close file descriptor, keep path
                print("   🎧 Using temporary enhanced audio (not saved)")

            enhance_audio(input_file, enhanced_audio_path)
            audio_file_for_transcription = enhanced_audio_path
        else:
            print("   🎧 Using original audio (enhancement disabled)")

        # Step 2: Speaker Diarization (if enabled)
        diarization_segments = None
        diarization_source = None
        audio_duration = None
        if speaker_attribution:
            print("\n🎭 SPEAKER DIARIZATION")
            print("-" * 40)
            diarization_segments, diarization_source = perform_speaker_diarization(
                audio_file_for_transcription,
                model_path=diarization_model_path,
                diarization_config=diarization_config,
                vad_onset=vad_onset,
                vad_offset=vad_offset,
                num_speakers=num_speakers,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )
            if diarization_source:
                src = diarization_source.get('source')
                mid = diarization_source.get('model_id')
                mpath = diarization_source.get('model_path')
                print(f"   Diarisation model source: {src} "
                      f"(id={mid}, path={mpath})")

            # Get audio duration for speaker label mapping
            try:
                import librosa
                audio_duration = librosa.get_duration(path=audio_file_for_transcription)
                print(f"   Audio duration: {audio_duration:.2f} seconds")
            except Exception as e:
                print(f"   ⚠️  Could not determine audio duration: {e}")

        # Step 3: Transcription
        print("\n📝 TRANSCRIPTION")
        print("-" * 40)
        # Speaker attribution needs word-level timestamps to align speakers
        # against actual word boundaries, so we force ``word`` even when the
        # user did not pass ``--timestamps`` explicitly.
        effective_timestamps = 'word' if (timestamps or speaker_attribution) else False
        transcription_result = transcribe_audio_only(
            audio_file_for_transcription, model, language,
            return_timestamps=effective_timestamps)

        if not transcription_result:
            print("❌ Transcription failed - cannot continue")
            if enhance_audio_enabled and save_enhanced_audios:
                print(f"   🎧 Enhanced audio preserved at: {enhanced_audio_path}")
            return False

        # The review's truncation check needs the recording's length. It
        # used to be measured only inside the speaker-attribution block, so
        # a --timestamps run without diarisation never checked for early
        # truncation (audit finding T3-05). The review now falls back on
        # the length of the audio the model decoded; speaker labelling
        # keeps using audio_duration alone, so its behaviour is unchanged.
        review_duration = audio_duration
        if review_duration is None and isinstance(transcription_result, dict):
            review_duration = transcription_result.get('audio_duration_s')

        # Resolve the language the post-processing gate should use.  An
        # explicit --language always wins; otherwise fall back to whatever
        # Whisper reports having decoded with, so that a user who lets the
        # model auto-detect still gets the English-only clean-text stages
        # skipped on non-English audio.  When neither is available English is
        # assumed for post-processing, and recorded as assumed: Whisper chose
        # the decoding language itself, so the provenance must not read as
        # if English decoding had been requested.
        language_detected = None if language else _detected_language(transcription_result)
        effective_language = language or language_detected
        language_assumed = False
        if not language:
            print()
            if effective_language:
                print(f"   ⚠️  Language not specified; auto-detected as "
                      f"{effective_language.title()}.")
            else:
                effective_language = "english"
                language_assumed = True
                print("   ⚠️  Language not specified and detection was "
                      "unavailable; assuming English.")
            print("      Post-processing applies English-specific rules only to "
                  "English transcripts, so a wrong")
            print(f"      guess degrades the output. Pass "
                  f"--language {(effective_language or 'english').lower()} "
                  f"to state it explicitly.")
            print()

        # Resolve the name-masking default now that the language is known.
        # ``None`` means the caller did not decide, so filtering common English
        # words out of the name database follows the language actually used:
        # the filter stops ordinary English words (Mark, Will, Rose) being
        # masked as names, and is meaningless on other languages.
        if exclude_common_words is None:
            exclude_common_words = _language_is_english(effective_language)

        # Initialise name masking before the timestamped artefacts are
        # written, so that a redacted parallel set can be produced from the
        # same masker that will later redact the transcript text.
        mask_names_func = None
        get_replacement_log_func = None
        if mask_names:
            print("   Initializing enhanced name masking with global database...")
            mask_names_func, get_replacement_log_func = create_enhanced_name_masker(
                use_facebook_names, use_facebook_surnames, selected_languages,
                exclude_common_words, excluded_names)

        # Step 3b: Persist raw, timestamped artefacts *before* any
        # post-processing or privacy filters. This preserves synchronisation
        # between model output and timing information, and gives downstream
        # evaluation (WER) a faithful record of what the model produced.
        # When masking is enabled a redacted parallel set is written too, so
        # that the exportable artefact is de-identified.
        # Every file this run writes under output/transcripts is recorded
        # here as it is written, so the manifest lists exactly this run's
        # artefacts (see the manifest step below).
        run_artefacts = []
        if timestamps or speaker_attribution:
            print("\n🕒 TIMESTAMPED OUTPUT (raw, pre-filter)")
            print("-" * 40)
            # Suppressing the raw set only makes sense when a masker exists to
            # produce the redacted one; otherwise nothing would be written.
            if redacted_timestamps_only and mask_names_func is None:
                print("   ⚠️  --redacted-timestamps-only needs "
                      "--mask-personal-names; keeping the raw artefacts.")
                redacted_timestamps_only = False
            os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
            _ts_written = None
            try:
                _ts_written = write_timestamped_outputs(
                    transcription_result,
                    output_dir=TRANSCRIPTS_DIR,
                    base_name=base_name,
                    audio_path=input_file,
                    model=model,
                    # Record the language actually used (detected when the
                    # caller passed none), so the provenance block states
                    # what produced the transcript rather than what was asked.
                    language=effective_language,
                    diarization_segments=diarization_segments,
                    diarization_source=diarization_source,
                    mask_fn=mask_names_func,
                    write_raw=not redacted_timestamps_only,
                    language_provenance={
                        'language_requested': language,
                        'language_detected': language_detected,
                        'language_assumed': language_assumed,
                    },
                )
                run_artefacts.extend(
                    _ts_written[key]
                    for key in ('json', 'vtt', 'json_redacted', 'vtt_redacted')
                    if key in _ts_written)
                # Mark the segments whose shape is characteristic of
                # hallucination or a decoding loop, so that a reader has
                # something drawing their attention to them. These are
                # heuristics, not model confidence; the summary says so.
                try:
                    review_path = os.path.join(
                        TRANSCRIPTS_DIR, f"{base_name}_review.json")
                    review = write_review_file(
                        _ts_written.get('segments') or [], review_path,
                        audio_duration_s=review_duration,
                        mask_fn=mask_names_func,
                        review_options=review_options)
                    run_artefacts.append(review_path)
                    n_flagged = review['summary']['flagged']
                    if n_flagged:
                        print(f"   🔎 {n_flagged} segment(s) flagged for review "
                              f"({review['summary']['flag_rate'] * 100:.1f}%): "
                              f"{review_path}")
                    else:
                        print(f"   🔎 No segments flagged for review: {review_path}")
                    _trunc = review.get('truncation') or {}
                    if not review_duration:
                        print("   ⚠️  The recording's duration is unknown, so "
                              "the review could not check whether the "
                              "transcript stops early.")
                    elif _trunc.get('truncated'):
                        print(f"   ⚠️  Transcript ends {_trunc['shortfall_s']:.1f}s "
                              f"before the recording does "
                              f"({_trunc['shortfall_fraction'] * 100:.0f}% "
                              f"unaccounted for): the model may have stopped "
                              f"early. Check the end of the audio.")
                except Exception as review_error:
                    # Named so as not to shadow the re module, which an
                    # 'as re' binding makes local to this whole function.
                    print(f"   ⚠️  Could not compute review flags: {review_error}")
                    missing_artefacts.append(
                        f"review report ({review_error})")
            except Exception as e:
                print(f"   ⚠️  Failed to write timestamped outputs: {e}")
                missing_artefacts.append(f"timestamped JSON/VTT ({e})")

        # Step 4: Process and clean transcription text
        print("\n🔧 TEXT PROCESSING AND ENHANCEMENT")
        print("-" * 40)

        main_text = transcription_result.get('text', '')

        # Store base transcription for dual output when speaker attribution is enabled
        base_transcript_text = main_text
        speaker_labels_applied = False

        # Apply speaker attribution if enabled and segments available
        if speaker_attribution and diarization_segments:
            print("\n  🎭 SPEAKER ATTRIBUTION")
            print("-" * 40)
            chunks_for_alignment = (
                transcription_result.get('chunks')
                if isinstance(transcription_result, dict) else None
            )
            # Prefer the repaired timeline over the raw pipeline chunks, so
            # the speaker-labelled text and the timestamped JSON attribute
            # words from the same timings. Without this the two artefacts
            # could disagree on the speaker of any word the repair moved.
            if _ts_written and _ts_written.get('segments'):
                repaired_chunks = []
                for _seg in _ts_written['segments']:
                    for _w in _seg.get('words') or []:
                        _ws, _we = _w.get('start'), _w.get('end')
                        if _ws is None or _we is None:
                            continue
                        repaired_chunks.append({
                            'text': _w.get('word', _w.get('text', '')),
                            'timestamp': (_ws, _we),
                        })
                if repaired_chunks:
                    chunks_for_alignment = repaired_chunks
            main_text = apply_speaker_labels_to_transcript(
                main_text, diarization_segments, audio_duration,
                chunks=chunks_for_alignment,
            )
            speaker_labels_applied = main_text != base_transcript_text
        elif speaker_attribution:
            print("\n  ⚠️  Speaker attribution requested but diarisation unavailable")
            reason = (diarization_source or {}).get('error') or 'no segments'
            missing_artefacts.append(f"speaker attribution ({reason})")

        # Name masking was initialised earlier, before the timestamped
        # artefacts were written, so that both sets share one masker.
        filename = Path(original_filename).name if original_filename else Path(input_file).name
        print("   Removing emojis and Unicode artefacts...")
        if fix_repetitions:
            print("   Detecting and fixing repetitive patterns...")
        else:
            print("   Skipping repetition detection (not enabled)")
        print("   Applying text clean-up stages...")
        if mask_names_func:
            print("   Applying enhanced name masking with logging...")
        main_text, replacement_log = postprocess_transcript_text(
            main_text, effective_language, fix_repetitions=fix_repetitions,
            mask_fn=mask_names_func, get_log=get_replacement_log_func,
            filename=filename, speaker_turns=speaker_labels_applied)

        if mask_names_func and get_replacement_log_func:
            if replacement_log and save_name_masking_logs:
                print(f"   💾 Saving name replacement log ({len(replacement_log)} replacements)")
                save_replacement_log(replacement_log, filename)
            elif replacement_log and not save_name_masking_logs:
                print(f"   ℹ️  Name replacement log available ({len(replacement_log)} "
                      f"replacements) - use --save-name-masking-logs to save")

        # Transcripts are written as continuous paragraphs, never wrapped:
        # create_word_document and evaluation/wer.py both rely on blank
        # lines being the only breaks.
        formatted_main_text = main_text.strip()

        # Step 4: Save results with enhanced formatting
        print("\n💾 SAVING RESULTS")
        print("-" * 40)

        # Ensure output directory exists
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

        # The run settings every transcript header records, passed by
        # keyword to both writers.
        header_settings = dict(
            original_filename=original_filename, language=effective_language,
            mask_names=mask_names, fix_repetitions=fix_repetitions,
            use_facebook_names=use_facebook_names,
            use_facebook_surnames=use_facebook_surnames,
            enhance_audio_enabled=enhance_audio_enabled,
            language_assumed=language_assumed)

        def _save_word_document(text, path, with_speakers, label):
            """Save one .docx, reporting success only if it was written."""
            if create_word_document(
                    text, path, input_file, model_name=model,
                    speaker_attribution=with_speakers, **header_settings):
                run_artefacts.append(path)
                print(f"   ✅ {label} saved: {path}")
            else:
                print(f"   ❌ {label} not saved: {path}")
                missing_artefacts.append(f"{label} {path}")

        # If speaker labels were applied, save both versions. This used to
        # require audio_duration as well, which only the legacy labelling
        # path reads, so a recording whose duration librosa could not
        # probe got a single speaker-labelled _transcript.txt instead.
        if speaker_labels_applied:
            # Save version WITHOUT speaker labels
            output_file_base = f"{TRANSCRIPTS_DIR}/{base_name}_transcript.txt"

            # Process base transcript (without speakers) through same cleaning pipeline
            print("   Processing base transcript (without speaker labels)...")
            base_text_processed = base_transcript_text

            # Apply same text processing to base transcript
            base_text_processed, _ = postprocess_transcript_text(
                base_text_processed, effective_language,
                fix_repetitions=fix_repetitions, mask_fn=mask_names_func,
                filename=filename)
            formatted_base_text = base_text_processed.strip()

            save_transcript_file(output_file_base, formatted_base_text, base_name, input_file,
                               model=model, speaker_attribution=False,
                               **header_settings)
            run_artefacts.append(output_file_base)
            print(f"   ✅ Base transcript saved: {output_file_base}")

            # Save version WITH speaker labels
            output_file_speakers = f"{TRANSCRIPTS_DIR}/{base_name}_transcript_with_speakers.txt"
            save_transcript_file(output_file_speakers, formatted_main_text, base_name, input_file,
                               model=model, speaker_attribution=True,
                               **header_settings)
            run_artefacts.append(output_file_speakers)
            print(f"   ✅ Speaker-attributed transcript saved: {output_file_speakers}")

            word_output_base = Path(output_file_base).with_suffix('.docx').as_posix()
            _save_word_document(formatted_base_text, word_output_base,
                                False, "Base Word document")

            word_output_speakers = Path(output_file_speakers).with_suffix('.docx').as_posix()
            _save_word_document(formatted_main_text, word_output_speakers,
                                True, "Speaker-attributed Word document")

        else:
            # Standard single output (no speaker attribution or it failed).
            # No speaker labels reached this text, so the header must not
            # announce speaker attribution even when it was requested.
            output_file = f"{TRANSCRIPTS_DIR}/{base_name}_transcript.txt"

            save_transcript_file(output_file, formatted_main_text, base_name, input_file,
                               model=model, speaker_attribution=False,
                               **header_settings)
            run_artefacts.append(output_file)
            print(f"   ✅ Transcript saved: {output_file}")

            word_output_file = Path(output_file).with_suffix('.docx').as_posix()
            _save_word_document(formatted_main_text, word_output_file,
                                False, "Word document")

        # Record what produced this run, and make later alteration
        # detectable. The manifest lists the transcripts, captions,
        # documents and review this run wrote, with their digests, beside
        # the input recording's digest and the pipeline settings. The
        # name-masking log and kept enhanced audio are not listed, so a
        # change to either goes undetected (CORE-05). The list is the exact
        # paths collected above, not a directory scan: a prefix glob would
        # also certify another recording's files (interview1* matches
        # interview10_*) and stale files of an earlier run with other flags,
        # and miss this run's own files when the name holds glob characters
        # ('session[1]'). Signing is opt-in, and integrity needs no key.
        try:
            from provenance import load_key, write_manifest
            transcript_dir = TRANSCRIPTS_DIR
            manifest_path = os.path.join(
                transcript_dir, f"{base_name}_manifest.json")
            manifest = write_manifest(
                list(dict.fromkeys(run_artefacts)), transcript_dir,
                manifest_path,
                provenance={
                    'asr_model': model,
                    'asr_model_revision': (
                        transcription_result.get('model_revision')
                        if isinstance(transcription_result, dict) else None),
                    'language': effective_language,
                    'language_requested': language,
                    'language_detected': language_detected,
                    'language_assumed': language_assumed,
                    'name_masking': bool(mask_names),
                    'repetition_fix': bool(fix_repetitions),
                    'speaker_attribution': bool(speaker_attribution),
                    # 'timestamps' keeps its meaning (the flag as given);
                    # speaker attribution also writes the timestamped
                    # set, which the next field records.
                    'timestamps': bool(timestamps),
                    'timestamped_artefacts_written': any(
                        str(p).endswith(('_transcript.json',
                                         '_transcript_redacted.json'))
                        for p in run_artefacts),
                    'redacted_timestamps_only': bool(redacted_timestamps_only),
                    'audio_enhancement': bool(enhance_audio_enabled),
                    # The optional review checks change the review, whose
                    # digest this manifest records. The key is written only
                    # when they are on, so a default run's manifest is the
                    # one it has always been (example_output/variants).
                    **({'review_settings': dict(review_options)}
                       if review_options else {}),
                    # Settings that change the masked text or the speaker
                    # labels, so two runs differing only in these no longer
                    # carry identical provenance.
                    'name_masking_settings': ({
                        'languages': selected_languages or 'all',
                        'use_facebook_names': bool(use_facebook_names),
                        'use_facebook_surnames': bool(use_facebook_surnames),
                        'exclude_common_words': bool(exclude_common_words),
                        'excluded_names': _excluded_names_digest(excluded_names),
                    } if mask_names else None),
                    'diarization_settings': ({
                        'source': (diarization_source or {}).get('source'),
                        'model_id': (diarization_source or {}).get('model_id'),
                        'model_revision': (diarization_source or {}).get(
                            'model_revision'),
                        'sub_model_revisions': (diarization_source or {}).get(
                            'sub_model_revisions'),
                        'model_path': diarization_model_path,
                        'config': diarization_config,
                        'num_speakers': num_speakers,
                        'min_speakers': min_speakers,
                        'max_speakers': max_speakers,
                        'vad_onset': vad_onset,
                        'vad_offset': vad_offset,
                        'error': (diarization_source or {}).get('error'),
                    } if speaker_attribution else None),
                    'software': _software_provenance(),
                },
                audio_path=input_file,
                key=load_key(),
                # The file transcribed may be a derivative (a 16 kHz WAV
                # decoded from an .m4a). Naming the original, with its
                # digest and the conversion, keeps the chain from the
                # recording to these artefacts verifiable (CORE-04).
                source_audio=source_audio,
                derivation=source_derivation,
            )
            signed = 'signed' if manifest.get('signature') else 'unsigned'
            print(f"   🔏 Run manifest written ({signed}, "
                  f"{len(manifest.get('artefacts', []))} artefacts): {manifest_path}")
        except Exception as e:
            print(f"   ⚠️  Could not write the run manifest: {e}")
            missing_artefacts.append(f"run manifest ({e})")

        if enhance_audio_enabled and save_enhanced_audios:
            print(f"   🎧 Enhanced audio preserved at: {enhanced_audio_path}")

        if missing_artefacts:
            print(f"\n❌ INCOMPLETE: {input_file} was processed, but these "
                  f"requested artefacts were not produced:")
            for item in missing_artefacts:
                print(f"   - {item}")
            return False

        print(f"\n✅ SUCCESS: Enhanced processing completed for {input_file}")
        return True

    except Exception as e:
        print(f" Error processing {input_file}: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # A SIGTERM from a scheduler time limit still bypasses this; only
        # an ordinary return or exception is covered.
        if (enhanced_audio_is_temporary and enhanced_audio_path
                and os.path.exists(enhanced_audio_path)):
            try:
                os.unlink(enhanced_audio_path)
                print("   🗑️  Temporary enhanced audio cleaned up")
            except OSError as cleanup_error:
                print(f"   ⚠️  Could not delete the temporary enhanced "
                      f"audio {enhanced_audio_path}: {cleanup_error}")

def main():
    """Command-line entry point: parse the options and process one file.

    Exits 0 when :func:`process_audio_file` succeeds and 1 when it fails
    or a requested artefact was not produced. Invalid options, an unknown
    or empty --languages-for-name-masking, a missing name dictionary and
    an unreadable --exclude-names-file exit 2 (argparse's usage error)
    before any audio is read.
    """
    parser = argparse.ArgumentParser(description='Ultimate Enhanced Transcription Processor')
    parser.add_argument('audio_file', help='Input audio file path')
    parser.add_argument('--mask-personal-names', action='store_true',
                       help='Enable personal name masking (boolean flag)')
    parser.add_argument('--use-facebook-names-for-masking', action='store_true',
                       help='Use Facebook global first names database (730K+ names, may cause '
                            'false positives). Default: use curated basic names only.')
    parser.add_argument('--use-facebook-surnames-for-masking', action='store_true',
                       help='Use Facebook global surnames database (980K+ surnames, may cause '
                            'false positives). Default: use curated basic surnames only.')
    # The supported languages are read from the CSV itself so that the help
    # text cannot drift from the dictionary. A missing CSV is reported when
    # masking is actually requested, not here, so --help still works.
    try:
        _name_languages = ', '.join(curated_name_languages())
    except (FileNotFoundError, RuntimeError):
        _name_languages = 'the languages in data/curated_names.csv'
    parser.add_argument('--languages-for-name-masking', type=str, nargs='+',
                       default=None, metavar='LANG',
                       help='Languages to include in curated names database (case-insensitive '
                            f'full names). Supported: {_name_languages}. Default: all of them.')
    # BooleanOptionalAction adds the --no- form. With store_true there was
    # no way to turn the filter off for an English run, and the documented
    # '=false' spelling was an argparse error.
    parser.add_argument('--exclude-common-english-words-from-name-masking',
                       action=argparse.BooleanOptionalAction, default=None,
                       help='Exclude common English words (e.g., "will", "long", "art") from name '
                            'masking. Default: on when the language, given or detected, is '
                            'English, otherwise off.')
    parser.add_argument('--exclude-names-from-masking', type=str, default=None,
                       help='Comma-separated list of names to exclude from masking (e.g., '
                            '"John,Sarah,Einstein"). Case-insensitive.')
    parser.add_argument('--exclude-names-file', type=str, default=None,
                       help='Path to file containing names to exclude from masking (one name per '
                            'line). Case-insensitive.')
    parser.add_argument('--model', type=str, default="openai/whisper-large-v3",
                       help='HuggingFace model ID (default: openai/whisper-large-v3)')
    parser.add_argument('--language', type=str, default=None,
                       help='Specify transcription language (e.g., "english", "spanish", '
                            '"french"). Default: auto-detect language')
    parser.add_argument('--source-audio', type=str, default=None,
                       help='The original recording the input was derived from (for example '
                            'the .m4a an input WAV was decoded from); its SHA-256 is recorded in '
                            'the run manifest beside the input\'s')
    parser.add_argument('--source-derivation', type=str, default=None,
                       help='How the input was made from --source-audio (for example the '
                            'ffmpeg command); recorded in the run manifest')
    parser.add_argument('--original-filename', type=str, default=None,
                       help='Original filename to use for output (for temp file processing)')
    parser.add_argument('--fix-spurious-repetitions', action='store_true',
                       help='Enable automatic repetition pattern detection and removal')
    parser.add_argument('--output-name', type=str, default=None,
                       help='Custom name for output files (without extension)')
    parser.add_argument('--save-name-masking-logs', action='store_true',
                       help='Save detailed logs of name replacements to '
                            'name_masking_logs/ directory')
    parser.add_argument('--save-enhanced-audio', action='store_true',
                       help='Save enhanced audio files to output/enhanced_audio/ directory')
    parser.add_argument('--enhance-audio', action='store_true',
                       help='Enable audio enhancement for better transcription quality '
                            '(disabled by default)')
    parser.add_argument('--speaker-attribution', action='store_true',
                       help='Enable speaker diarization/attribution (disabled by default). Note: '
                            'Accuracy depends on recording quality, number of speakers, and '
                            'speaker similarity. Implies word timestamps, which also switches the '
                            'ASR to 30 s decoding windows, so the unlabelled transcript can differ '
                            'slightly from a plain run.')
    parser.add_argument('--diarization-model-path', '--diarisation-model-path',
                       dest='diarization_model_path', type=str, default=None,
                       help='Local pyannote diarisation pipeline: a config.yaml, or a directory '
                            'containing one. If it cannot be loaded, the run does not fall back to '
                            'the Hub model. When omitted, the HuggingFace loader is used: the '
                            'local cache is checked first and weights are downloaded from the Hub '
                            'only when absent, which requires a HuggingFace token.')
    parser.add_argument('--diarization-config', '--diarisation-config',
                       dest='diarization_config', type=str, default=None,
                       help='Path to a local pyannote diarisation YAML config file referencing '
                            'on-disk segmentation and embedding checkpoints. Use this for fully '
                            'air-gapped operation. Tried before --diarization-model-path; if '
                            'neither loads, the run does not fall back to the Hub model. Setting '
                            'HF_HUB_OFFLINE=1 or TRANSFORMERS_OFFLINE=1 makes the HuggingFace '
                            'loader cache-only, through huggingface_hub honouring those variables.')
    parser.add_argument('--vad-onset', '--vad-onset-threshold',
                       dest='vad_onset', type=float, default=None,
                       metavar='THRESH',
                       help='Speech-detection onset threshold, for diarisation pipelines that '
                            'expose one: a pyannote 3.x speaker-diarisation pipeline with a binary '
                            '(non-powerset) segmentation model, or a voice-activity pipeline '
                            'loaded with --diarization-config. The default model, '
                            'pyannote/speaker-diarization-3.1, has no such threshold, so this '
                            'option has no effect there and says so at run time rather than '
                            'appearing to be honoured. Only used when --speaker-attribution is '
                            'active.')
    parser.add_argument('--vad-offset', '--vad-offset-threshold',
                       dest='vad_offset', type=float, default=None,
                       metavar='THRESH',
                       help='Speech-detection offset threshold. On pyannote 3.x it applies only to '
                            'binary-segmentation voice-activity pipelines loaded with '
                            '--diarization-config; the default diarisation model has no such '
                            'threshold, and the run says so. Only used when --speaker-attribution '
                            'is active.')
    parser.add_argument('--num-speakers', dest='num_speakers', type=int,
                       default=None, metavar='N',
                       help='Exact number of speakers in the recording. Speaker confusion is the '
                            'largest component of diarisation error, and most of it comes from the '
                            'clustering step having to infer how many speakers there are; a '
                            'one-to-one interview has exactly two, so state it. Overrides '
                            '--min-speakers/--max-speakers. Only used when --speaker-attribution '
                            'is active.')
    parser.add_argument('--min-speakers', dest='min_speakers', type=int,
                       default=None, metavar='N',
                       help='Lower bound on the number of speakers, for when the exact count is '
                            'not known. Only used when --speaker-attribution is active.')
    parser.add_argument('--max-speakers', dest='max_speakers', type=int,
                       default=None, metavar='N',
                       help='Upper bound on the number of speakers. Only used when '
                            '--speaker-attribution is active.')
    parser.add_argument('--timestamps', action='store_true',
                       help='Emit word- and segment-level timestamps as .json and .vtt alongside '
                            'the plain text transcript. Captured before name masking and other '
                            'post-processing to preserve synchronisation. With '
                            '--mask-personal-names, a redacted parallel set is written alongside '
                            'them. Timestamps use 30 s decoding windows (15 s otherwise), so the '
                            'text can differ slightly from a plain run.')
    parser.add_argument('--redacted-timestamps-only', action='store_true',
                       help='Write only the redacted timestamped artefacts, suppressing the '
                            'unredacted .json and .vtt. Requires --mask-personal-names. Use this '
                            'when the output tree may be exported wholesale and must carry no '
                            'personal names.')
    # The review's optional checks (confidence.py), off by default so that
    # a default run writes the review it always has. They need the
    # timestamped outputs, which the review is computed from.
    parser.add_argument('--review-flag-zero-duration', action='store_true',
                       help='Also flag, in the review, non-empty cues whose start and end times '
                            'are equal. Needs --timestamps or --speaker-attribution.')
    parser.add_argument('--review-repeated-passage-words', type=int, default=None,
                       metavar='N',
                       help='Also flag, in the review, both copies of a run of N or more tokens '
                            'that recurs across cues, as a passage Whisper writes twice does. An '
                            'apostrophe splits a word, so a contraction counts as two tokens. '
                            'Suggested: 8. Needs --timestamps or --speaker-attribution.')
    parser.add_argument('--review-repeated-passage-window', type=float,
                       default=None, metavar='SECONDS',
                       help='Maximum gap, in seconds, between the starting cues of two repeated '
                            'runs (default: 60). Needs --review-repeated-passage-words.')

    args = parser.parse_args()

    # Checked here, before any audio is read, so that a mistyped option
    # fails at once and not after a GPU transcription; an option that would
    # change nothing is refused for the same reason.
    review_options = None
    if args.review_repeated_passage_window is not None \
            and args.review_repeated_passage_words is None:
        parser.error("--review-repeated-passage-window needs "
                     "--review-repeated-passage-words")
    if args.review_flag_zero_duration or args.review_repeated_passage_words is not None:
        if not (args.timestamps or args.speaker_attribution):
            parser.error("the --review- options need --timestamps or "
                         "--speaker-attribution, which write the review")
        from confidence import _PASSAGE_WINDOW_S, flag_segments
        review_options = {
            'flag_zero_duration': bool(args.review_flag_zero_duration),
            'repeated_passage_words': args.review_repeated_passage_words,
            'repeated_passage_window_s': (
                _PASSAGE_WINDOW_S if args.review_repeated_passage_window is None
                else args.review_repeated_passage_window),
        }
        try:
            # flag_segments validates its options before it reads a segment.
            flag_segments([], **review_options)
        except ValueError as exc:
            parser.error(str(exc))

    mask_names = args.mask_personal_names
    use_facebook_names = args.use_facebook_names_for_masking
    use_facebook_surnames = args.use_facebook_surnames_for_masking
    selected_languages = args.languages_for_name_masking
    if mask_names:
        # Validate before any audio is touched: a capitalised, ISO-coded or
        # misspelt language used to load an empty dictionary and write a
        # transcript whose header claimed the names had been masked.
        try:
            selected_languages = normalise_name_languages(
                selected_languages, curated_name_languages())
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            parser.error(str(exc))
    transcription_language = args.language
    original_filename = args.original_filename
    fix_repetitions = args.fix_spurious_repetitions
    output_name = args.output_name
    save_name_masking_logs = args.save_name_masking_logs
    save_enhanced_audios = args.save_enhanced_audio
    enhance_audio_enabled = args.enhance_audio
    speaker_attribution_enabled = args.speaker_attribution

    # Whether to exclude common English words from name masking.  When the
    # user does not decide, leave the value as None and let
    # ``process_audio_file`` resolve it from the language actually used: that
    # is the detected language when --language was not given, which the CLI
    # cannot know at this point.
    exclude_common_words = args.exclude_common_english_words_from_name_masking

    # Parse excluded names from command line and file
    excluded_names = set()
    if args.exclude_names_from_masking:
        # Parse comma-separated names (case-insensitive)
        excluded_names.update(name.strip().lower()
                              for name in args.exclude_names_from_masking.split(',')
                              if name.strip())

    if args.exclude_names_file:
        # Read names from file (one per line, case-insensitive)
        # An unreadable exclusion file is an error, not a warning: carrying
        # on would mask the very names the user asked to keep.
        try:
            with open(args.exclude_names_file, encoding='utf-8') as f:
                excluded_names.update(line.strip().lower() for line in f if line.strip())
        except (OSError, UnicodeDecodeError) as e:
            parser.error(f"could not read --exclude-names-file "
                         f"{args.exclude_names_file}: {e}")

    print(" ENHANCED TRANSCRIPTION PROCESSOR")
    print("=" * 55)

    # Determine the input file to process
    input_file = args.audio_file

    print(f"Input: {input_file}")
    print(f"Model: {args.model}")
    if transcription_language:
        print(f"Language: {transcription_language.title()}")
    else:
        print("Language: Auto-detect")
    # Built from the flags actually given; this banner is what an audit of
    # a SLURM log reads first, and it used to print fixed claims ('no
    # timestamps', 'requires HuggingFace token') whatever the run did.
    features = []
    if args.timestamps or speaker_attribution_enabled:
        features.append("word timestamps (.json/.vtt)")
    if fix_repetitions:
        features.append("repetition detection")
    if enhance_audio_enabled:
        features.append("audio enhancement")
    print(f"Features: {', '.join(features) if features else 'plain transcript'}")
    print("Text Processing: clean-up stages (English-only ones skipped for other languages)")
    if mask_names:
        print("Privacy: Personal name masking enabled")
        if excluded_names:
            print(f"         Excluding {len(excluded_names)} name(s) from masking")
    if speaker_attribution_enabled:
        if args.diarization_config or args.diarization_model_path:
            print("Speaker Attribution: Enabled (local pipeline)")
        else:
            print("Speaker Attribution: Enabled (Hugging Face model; needs a "
                  "token unless already cached)")

    success = process_audio_file(
        input_file, mask_names=mask_names, model=args.model,
        language=transcription_language, original_filename=original_filename,
        fix_repetitions=fix_repetitions, output_name=output_name,
        save_name_masking_logs=save_name_masking_logs,
        save_enhanced_audios=save_enhanced_audios,
        enhance_audio_enabled=enhance_audio_enabled,
        use_facebook_names=use_facebook_names,
        use_facebook_surnames=use_facebook_surnames,
        selected_languages=selected_languages,
        speaker_attribution=speaker_attribution_enabled,
        exclude_common_words=exclude_common_words,
        excluded_names=excluded_names, timestamps=args.timestamps,
        diarization_model_path=args.diarization_model_path,
        diarization_config=args.diarization_config,
        vad_onset=args.vad_onset, vad_offset=args.vad_offset,
        redacted_timestamps_only=args.redacted_timestamps_only,
        num_speakers=args.num_speakers, min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
        source_audio=args.source_audio, source_derivation=args.source_derivation,
        review_options=review_options)

    if success:
        print("\n JOB COMPLETED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("\n JOB FAILED!")
        sys.exit(1)

if __name__ == "__main__":
    main()
