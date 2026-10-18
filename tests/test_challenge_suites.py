"""Tests for the challenge-suite registry in evaluation.challenge_suites.

These tests exercise the registry structure without requiring any audio data,
network access, or optional packages such as jiwer or pyannote.audio.  They
verify that all required fields are present and non-empty, that names follow
the expected slug convention, that ordering is deterministic, and that the
``get_suite`` helper raises an informative ``KeyError`` for unknown names.
"""

from __future__ import annotations

import re

import pytest

from evaluation.challenge_suites import Suite, _SUITES, get_suite, list_suites

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_REQUIRED_FIELDS = (
    "name",
    "description",
    "category",
    "dataset",
    "config",
    "split",
    "ref_field",
    "uid_field",
    "licence",
    "citation_key",
)


def test_registry_is_non_empty():
    assert len(_SUITES) >= 3, (
        "At least three challenge suites must be registered "
        f"(found {len(_SUITES)})."
    )

def test_suite_names_are_valid_slugs():
    for name in _SUITES:
        assert _SLUG_RE.match(name), (
            f"Suite name {name!r} is not a valid lower-case slug "
            "(ASCII letters, digits and underscores only, starting with a "
            "letter)."
        )


def test_suite_names_are_unique():
    names = list(_SUITES.keys())
    assert len(names) == len(set(names)), "Duplicate suite names detected."


def test_required_fields_non_empty():
    for suite in list_suites():
        for field in _REQUIRED_FIELDS:
            value = getattr(suite, field)
            assert value, (
                f"Suite {suite.name!r} has an empty or missing "
                f"'{field}' field."
            )


def test_list_suites_returns_alphabetical_order():
    suites = list_suites()
    names = [s.name for s in suites]
    assert names == sorted(names), (
        "list_suites() must return suites in alphabetical order by name."
    )


def test_list_suites_covers_all_registered():
    assert {s.name for s in list_suites()} == set(_SUITES.keys())


def test_get_suite_returns_correct_object():
    for name, expected in _SUITES.items():
        result = get_suite(name)
        assert isinstance(result, Suite)
        assert result is expected


def test_get_suite_raises_for_unknown_name():
    with pytest.raises(KeyError, match="Available suites:"):
        get_suite("nonexistent_suite_xyz_abc")


def test_suite_dataclass_is_immutable():
    suite = list_suites()[0]
    with pytest.raises((AttributeError, TypeError)):
        suite.name = "mutated"  # type: ignore[misc]


def test_known_suites_have_expected_hf_identifiers():
    """Spot-check the three initial suites for correct HuggingFace dataset IDs."""
    suite_map = {s.name: s for s in list_suites()}

    assert suite_map["fleurs"].dataset == "google/fleurs"
    assert suite_map["fleurs"].config == "en_us"
    assert suite_map["fleurs"].split == "test"

    assert suite_map["voxpopuli_accented"].dataset == "facebook/voxpopuli"
    assert suite_map["voxpopuli_accented"].config == "en_accented"
    assert suite_map["voxpopuli_accented"].split == "test"

    assert suite_map["ami"].dataset == "edinburghcstr/ami"
    assert suite_map["ami"].config == "ihm"
    assert suite_map["ami"].split == "test"

    assert suite_map["librispeech_other"].dataset == "librispeech_asr"
    assert suite_map["librispeech_other"].config == "other"
    assert suite_map["librispeech_other"].split == "test"


def test_known_suites_have_expected_ref_fields():
    """Each dataset uses a different column for its reference transcription."""
    suite_map = {s.name: s for s in list_suites()}

    # FLEURS stores normalised text in 'transcription'
    assert suite_map["fleurs"].ref_field == "transcription"

    # VoxPopuli stores normalised English text in 'normalized_text'
    assert suite_map["voxpopuli_accented"].ref_field == "normalized_text"

    # AMI uses the standard 'text' column
    assert suite_map["ami"].ref_field == "text"

    # LibriSpeech 'other' uses the standard 'text' column (same loader as test-clean)
    assert suite_map["librispeech_other"].ref_field == "text"


def test_known_suites_have_expected_uid_fields():
    suite_map = {s.name: s for s in list_suites()}
    assert suite_map["fleurs"].uid_field == "id"
    assert suite_map["voxpopuli_accented"].uid_field == "audio_id"
    assert suite_map["ami"].uid_field == "audio_id"
    assert suite_map["librispeech_other"].uid_field == "id"


def test_licences_are_non_empty_strings():
    for suite in list_suites():
        assert isinstance(suite.licence, str) and suite.licence.strip(), (
            f"Suite {suite.name!r} has no licence string."
        )


def test_citation_keys_are_non_empty_strings():
    for suite in list_suites():
        assert isinstance(suite.citation_key, str) and suite.citation_key.strip(), (
            f"Suite {suite.name!r} has no citation_key."
        )
