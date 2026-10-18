"""Optional review checks for NEW-12, including controls that can resemble errors.

The case-study fixtures reproduce quoted fragments and failure shapes from
output/case_study/README.md, not the uncommitted 405-cue transcript. Cue
partitions within the quoted spans are illustrative. They test detection;
they cannot estimate precision or sensitivity on recorded speech.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import confidence


def _cue(start, end, text):
    return {"start": start, "end": end, "text": text}


def _passage_indices(cues, **kwargs):
    return {
        record["index"] for record in confidence.flag_segments(
            cues, repeated_passage_words=8, **kwargs)
        if "repeated_passage" in record["flags"]
    }


def test_quoted_24_word_copy_is_found_across_zero_length_cues():
    cues = [
        _cue(179.86, 183.00, "data. Can we just dwell on that for a second?"),
        _cue(183.00, 189.38,
             "Because that number, 680,000 hours of multilingual audio data, "
             "that's just an astonishing number."),
        _cue(189.38, 189.98, "It's so Thanks for watching!"),
        _cue(189.98, 189.98, "data. Can we just dwell on that for a second?"),
        _cue(189.98, 189.98,
             "Because that number, 680,000 hours of multilingual audio data,"),
        _cue(189.98, 189.98, "that's just an astonishing number."),
        _cue(189.98, 195.00, "It's so important to understand why that makes the model so robust."),
    ]
    # The repeated "It's so" also touches the end/start of cues 2 and 6.
    # Cues are review units; a match need not cover every word of a cue.
    assert _passage_indices(cues) == set(range(7))
    flagged = confidence.flag_segments(cues, flag_zero_duration=True)
    assert {r["index"] for r in flagged if "zero_duration" in r["flags"]} == {3, 4, 5}
    assert all("zero_duration" not in r["flags"] for r in confidence.flag_segments(cues))


def test_quoted_crammed_copy_matches_later_cues_despite_different_ending():
    # The quoted crammed cue ends "manual"; the later sentence continues
    # "manually chopped". Their shared runs still exceed eight tokens.
    cues = [
        _cue(315.14, 320.04,
             "So if you're conducting a qualitative study, standard methodology often requires you "
             "to do these in-depth interviews or focus groups that can regularly span. "
             "60 minutes, 90 minutes, even two hours. Easily. "
             "So that means a single two-hour interview has to be manual."),
        _cue(320.04, 325.00,
             "to do these in-depth interviews or focus groups that can regularly span."),
        _cue(325.00, 329.00, "60 minutes, 90 minutes, even two hours."),
        _cue(329.00, 330.00, "Easily."),
        _cue(330.00, 337.00,
             "So that means a single two-hour interview has to be manually chopped "
             "into maybe four or five separate segments."),
    ]
    assert _passage_indices(cues) == {0, 1, 2, 3, 4}


def test_both_copies_have_partner_indices_and_input_is_untouched():
    transcript = {"segments": [
        _cue(0, 4, "We checked every recording before starting the analysis."),
        _cue(4, 7, "There was a brief unrelated remark here."),
        _cue(7, 11, "WE checked every recording before starting the analysis!"),
    ]}
    before = copy.deepcopy(transcript)
    report = confidence.review_transcript(transcript, repeated_passage_words=8)
    records = {r["index"]: r for r in report["flagged"]}
    assert records[0]["repeated_passage_with"] == [2]
    assert records[2]["repeated_passage_with"] == [0]
    assert transcript == before
    assert report["optional_checks"] == {
        "flag_zero_duration": False,
        "repeated_passage_words": 8,
        "repeated_passage_window_s": 60.0,
    }


def test_every_later_copy_links_to_the_earliest_occurrence():
    # With three copies, two partners would satisfy "a matching run";
    # the documented one is the first, so the third copy names cue 0.
    phrase = "We checked every recording before starting the analysis."
    cues = [_cue(0, 4, phrase),
            _cue(4, 8, "There was a brief unrelated remark here."),
            _cue(8, 12, phrase),
            _cue(12, 16, "Another aside followed about the weather outside."),
            _cue(16, 20, phrase)]
    flagged = confidence.flag_segments(cues, repeated_passage_words=8)
    links = {r["index"]: r["repeated_passage_with"] for r in flagged
             if "repeated_passage" in r["flags"]}
    assert links == {0: [2], 2: [0], 4: [0]}


def test_a_contraction_counts_as_two_tokens():
    # The threshold counts tokens, not spoken words: an apostrophe splits
    # a word, so this six-word clause already reaches eight tokens.
    clause = "you know, I don't think that's"
    assert confidence._passage_tokens(clause) == [
        "you", "know", "i", "don", "t", "think", "that", "s"]
    cues = [_cue(0, 4, f"Well, {clause} right."),
            _cue(8, 12, f"And {clause} fair either.")]
    assert _passage_indices(cues) == {0, 1}


def test_options_are_disabled_by_default_and_do_not_add_report_fields():
    cues = [
        _cue(0, 4, "We checked every recording before starting the analysis."),
        _cue(4, 7, "There was a brief unrelated remark here."),
        _cue(7, 11, "We checked every recording before starting the analysis."),
        _cue(11, 11, "Additional words."),
    ]
    report = confidence.review_transcript({"segments": cues})
    assert report["flagged"] == []
    assert "optional_checks" not in report


@pytest.mark.parametrize("start, expected", [(60.0, {0, 1}), (60.001, set())])
def test_window_boundary_is_explicit(start, expected):
    phrase = "We checked every recording before starting the analysis."
    assert _passage_indices([_cue(0, 4, phrase), _cue(start, start + 4, phrase)]) == expected


def test_one_overlapping_occurrence_is_not_two_copies():
    # Nine identical tokens have two equal eight-token windows, but no
    # two non-overlapping eight-token runs. The legacy loop flag may fire.
    assert _passage_indices([_cue(0, 5, " ".join(["yes"] * 9))]) == set()
    assert _passage_indices([_cue(0, 8, " ".join(["yes"] * 16))]) == {0}


def test_window_expiry_keeps_a_later_matching_pair():
    phrase = "We checked every recording before starting the analysis."
    cues = [_cue(t, t + 4, phrase) for t in (0, 70, 80)]
    assert _passage_indices(cues) == {1, 2}


@pytest.mark.parametrize("start,end", [(None, 6), (5, None), ("bad", 6),
                                       (float("nan"), 6), (5, float("inf")),
                                       (8, 6), (True, 6)])
def test_unusable_timing_breaks_passage_matching(start, end):
    phrase = "We checked every recording before starting the analysis."
    cues = [_cue(0, 4, phrase), _cue(start, end, "Intervening words."), _cue(10, 14, phrase)]
    assert _passage_indices(cues) == set()
    flagged = confidence.flag_segments(cues, flag_zero_duration=True)
    assert not any("zero_duration" in r["flags"] for r in flagged)


def test_backwards_cue_order_breaks_passage_matching():
    phrase = "We checked every recording before starting the analysis."
    cues = [_cue(0, 4, phrase), _cue(10, 12, "Intervening words."), _cue(5, 9, phrase)]
    assert _passage_indices(cues) == set()


def test_review_handles_unusable_times_without_inventing_truncation():
    cues = [_cue("bad", "bad", "Ordinary speech here."),
            _cue(None, float("nan"), "Another ordinary sentence.")]
    report = confidence.review_transcript(
        {"segments": cues}, audio_duration_s=10,
        repeated_passage_words=8, flag_zero_duration=True)
    assert report["truncation"] == {"checked": False}
    assert report["flagged"] == []


def test_short_clause_restatement_does_not_meet_threshold():
    cues = [_cue(0, 3, "We should check it again."),
            _cue(3, 6, "What do you think?"),
            _cue(6, 9, "We should check it again.")]
    assert _passage_indices(cues) == set()


def test_genuine_long_restatement_is_advisory_and_is_not_removed():
    phrase = "We checked every recording before starting the analysis."
    cues = [_cue(0, 4, phrase), _cue(10, 14, phrase)]
    before = copy.deepcopy(cues)
    assert _passage_indices(cues) == {0, 1}
    assert cues == before


def test_numerical_differences_prevent_spurious_exact_match():
    cues = [_cue(0, 4, "We found 10 people within this group."),
            _cue(10, 14, "We found 20 people within this group.")]
    assert _passage_indices(cues) == set()
    assert confidence._passage_tokens("Observed -0.05, then +0.05.") == [
        "observed", "-0.05", "then", "+0.05"]


def test_existing_combining_mark_tokens_are_preserved():
    assert confidence._passage_tokens("नमस्ते दुनिया 20") == ["नमस्ते", "दुनिया", "20"]
    assert confidence._tokens("नमस्ते दुनिया 20") == ["नमस्ते", "दुनिया"]


@pytest.mark.parametrize("left,right", [(".5", "5"), ("\u22120.05", "0.05"),
                                         ("1e-3", "1e3"), ("-1.5e+2", "1.5e+2")])
def test_decimal_and_signed_number_contrasts_do_not_match(left, right):
    cues = [_cue(0, 4, f"We found {left} people within this group."),
            _cue(10, 14, f"We found {right} people within this group.")]
    assert _passage_indices(cues) == set()
    assert confidence._passage_tokens(left) == [left]
    assert confidence._passage_tokens(right) == [right]


@pytest.mark.parametrize("number", ["+.5", "-.5", "\u2212.5", "1.5e-3", "1E+3", "1e\u22123"])
def test_signed_decimals_and_exponents_remain_whole(number):
    assert confidence._passage_tokens(f"Observed {number} units.") == ["observed", number, "units"]


def test_numeric_zero_duration_cue_is_also_reviewable():
    flagged = confidence.flag_segments([_cue(2, 2, "680,000")], flag_zero_duration=True)
    assert "zero_duration" in flagged[0]["flags"]
    flagged = confidence.flag_segments([_cue(2, 2, "...")], flag_zero_duration=True)
    assert "zero_duration" not in flagged[0]["flags"]


@pytest.mark.parametrize("width", [True, 0, 1, -8, 2.5, "8"])
def test_bad_token_threshold_is_rejected(width):
    with pytest.raises(ValueError, match="integer of at least two"):
        confidence.flag_segments([], repeated_passage_words=width)


@pytest.mark.parametrize("window", [True, 0, -1, float("inf"), float("nan"), None, "bad"])
def test_bad_window_is_rejected(window):
    with pytest.raises(ValueError, match="finite and positive"):
        confidence.flag_segments([], repeated_passage_window_s=window)


def test_cli_records_optional_settings_and_invalid_options_write_nothing(tmp_path, capsys):
    source = tmp_path / "transcript.json"
    output = tmp_path / "review.json"
    source.write_text(json.dumps({"segments": [_cue(1, 1, "A cue to check.")]}), encoding="utf-8")
    assert confidence.main([str(source), "--flag-zero-duration", "--json", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["optional_checks"]["flag_zero_duration"] is True
    assert report["summary"]["counts_by_flag"] == {"zero_duration": 1}
    untouched = output.read_bytes()
    assert confidence.main([str(source), "--repeated-passage-words", "1",
                            "--json", str(output)]) == 2
    assert output.read_bytes() == untouched
    assert "integer of at least two" in capsys.readouterr().err


def test_cli_refuses_a_window_without_the_passage_check(tmp_path, capsys):
    # The window alone would change nothing and leave no optional_checks
    # record, so a missing --repeated-passage-words is an error.
    source = tmp_path / "transcript.json"
    output = tmp_path / "review.json"
    source.write_text(json.dumps({"segments": [_cue(0, 4, "A cue to check.")]}),
                      encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        confidence.main([str(source), "--repeated-passage-window", "30",
                         "--json", str(output)])
    assert exc.value.code == 2
    assert not output.exists()
    assert "needs --repeated-passage-words" in capsys.readouterr().err
    assert confidence.main([str(source), "--repeated-passage-words", "8",
                            "--repeated-passage-window", "30",
                            "--json", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["optional_checks"]["repeated_passage_window_s"] == 30.0


@pytest.mark.parametrize("start,end,expected_span", [("1", "1", "1.0-1.0s"),
                                                     ("bad", "bad", "n/a"),
                                                     ("nan", "nan", "n/a"),
                                                     ("3", "1", "n/a")])
def test_print_report_validates_external_times_without_changing_fields(
        start, end, expected_span, capsys):
    report = confidence.review_transcript({"segments": [_cue(1, 1, "yes yes yes")]})
    report["flagged"][0].update(start=start, end=end)
    before = copy.deepcopy(report)
    confidence.print_report(report)
    assert expected_span in capsys.readouterr().out
    assert report == before


@pytest.mark.parametrize("start,end,expected_flag", [("1", "1", "zero_duration"),
                                                     ("bad", "bad", "internal_repetition")])
def test_cli_can_print_numeric_string_or_unusable_times(
        start, end, expected_flag, tmp_path, capsys):
    source = tmp_path / "transcript.json"
    source.write_text(json.dumps({"segments": [_cue(start, end, "yes yes yes")]}), encoding="utf-8")
    assert confidence.main([str(source), "--flag-zero-duration"]) == 0
    assert expected_flag in capsys.readouterr().out


def test_archived_review_records_still_reproduce_without_new_options():
    # The committed review ran both optional checks (NEW-12). Flagged alone
    # with the defaults, each cue keeps its default flags and gains none;
    # a repeated passage needs its partner cue, and a cue of zero length
    # needs --flag-zero-duration.
    archived = json.loads((Path(__file__).resolve().parents[1] / "output" / "case_study"
                           / "codex_mentis_ep05_review.json").read_text(encoding="utf-8"))
    optional = {"zero_duration", "repeated_passage"}
    assert {f for r in archived["flagged"] for f in r["flags"]} >= optional
    for old_record in archived["flagged"]:
        expected = [f for f in old_record["flags"] if f not in optional]
        records = confidence.flag_segments([old_record])
        assert [r["flags"] for r in records] == ([expected] if expected else [])
        for record in records:
            assert record["speech_rate"] == old_record["speech_rate"]
            assert "repeated_passage_with" not in record
        if "zero_duration" in old_record["flags"]:
            [record] = confidence.flag_segments([old_record], flag_zero_duration=True)
            assert record["flags"] == ["zero_duration"]


def test_many_identical_tokens_need_no_all_pairs_search():
    # A stress case for a naive index that scans every previous occurrence.
    cues = [_cue(i, i + 1, " ".join(["yes"] * 20)) for i in range(2_000)]
    assert _passage_indices(cues) == set(range(2_000))
