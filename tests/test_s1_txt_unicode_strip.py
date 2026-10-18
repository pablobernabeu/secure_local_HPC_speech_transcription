"""Stage-1 fix to remove_emojis_and_unicode_artifacts (audit finding T1-02).

The stage deleted whole scripts (CJK, kana, Hangul, Arabic presentation
forms) through an over-wide emoji range, and every non-ASCII digit,
currency sign and punctuation mark. It now removes only emoji and
characters in symbol or control categories, and maps typographic quotes
to ASCII.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# T1-02: remove_emojis_and_unicode_artifacts keeps every script
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "中文 日本語 ひらがな カタカナ",           # CJK and kana
    "한국어 텍스트",                          # Hangul
    "ﻻ ﷲ ﺍﻟﻌﺮﺑﻴﺔ",                            # Arabic presentation forms
    "русский عربي हिन्दी",                    # Cyrillic, Arabic, Devanagari
    "٣ ١٢ ३",                                 # Arabic-Indic and Devanagari digits
    "¿Qué? «oui» — voilà…",                   # non-ASCII punctuation
    "£5 and €10 and ¥3",                      # currency
    "20°C",                                   # degree sign
    "rock & roll, 50% off + tax",             # isolated ASCII symbols
])
def test_unicode_strip_keeps_text(transcription_module, text):
    assert transcription_module.remove_emojis_and_unicode_artifacts(text) == text


@pytest.mark.parametrize("text, expected", [
    ("It’s here", "It's here"),
    ("l’homme", "l'homme"),
    ("‘quoted’ and “double”", "'quoted' and \"double\""),
    ("„Anführung“", '"Anführung"'),
])
def test_unicode_strip_maps_typographic_quotes(transcription_module, text,
                                               expected):
    assert transcription_module.remove_emojis_and_unicode_artifacts(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("hello 🌍 world", "hello world"),
    ("family \U0001F468\U0000200D\U0001F469\U0000200D\U0001F467 here",
     "family here"),                                 # ZWJ sequence
    ("press 1\U0000FE0F\U000020E3 now", "press 1 now"),  # keycap sequence
    ("thumbs 👍🏽 up", "thumbs up"),                  # skin-tone modifier
    ("♪ la la ♪", "la la"),                          # music notes (So)
    ("™ ©", ""),
    ("zero\U0000200Bwidth", "zerowidth"),            # zero-width space (Cf)
    ("bom\U0000FEFF", "bom"),
])
def test_unicode_strip_removes_emoji_and_artefacts(transcription_module, text,
                                                   expected):
    assert transcription_module.remove_emojis_and_unicode_artifacts(text) == expected


def test_unicode_strip_keeps_joiners_inside_words(transcription_module):
    """ZWNJ is part of Persian spelling; it survives between letters."""
    persian = "می\U0000200Cخواهم"
    assert transcription_module.remove_emojis_and_unicode_artifacts(persian) == persian


def test_unicode_strip_on_ascii_only_collapses_whitespace(transcription_module):
    f = transcription_module.remove_emojis_and_unicode_artifacts
    assert f("  plain   ascii\ntext  ") == "plain ascii text"
    assert f("cost $5 and 50% of it - really?") == "cost $5 and 50% of it - really?"
