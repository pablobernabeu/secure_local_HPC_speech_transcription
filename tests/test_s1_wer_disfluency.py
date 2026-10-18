"""Stage-1 fixes to the filler-preservation scorer.

ESTATS-01: reference recall was divided by the fillers left in the
*transformed* reference (58 for whisper_norm on AMI, against the
transcriber's 4,084), and conditions were compared over different
utterance sets. Recall is now scored against the transcriber's reference.
Each condition is reported over its own utterances, with the number it
lacks, as the finding proposed, and also over the utterances all of them
scored.
ESTATS-08: standalone "huh" counted as a filler and "mmhmm" did not.
The filler_bracket stage may bracket a backchannel element by element
("[uh]-huh") or whole ("[uh-huh]"); both must count as the bare form.
XREF-08: retention cannot see whether a kept filler is marked, so the
marked ones are counted on their own.
"""

from __future__ import annotations

import csv
import json

import pytest

from evaluation import disfluency
from evaluation.disfluency import (count_fillers, count_marked, score_dump_sets,
                                   score_pair)


# ---------------------------------------------------------------------------
# ESTATS-08: the detector's vocabulary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["huh?", "HUH", "Huh, really", "so huh"])
def test_standalone_huh_is_not_a_filler(text):
    assert sum(count_fillers(text).values()) == 0


def test_huh_still_completes_the_backchannel():
    assert count_fillers("uh-huh") == count_fillers("UH-HUH") == \
        count_fillers("uhuh")


@pytest.mark.parametrize("text", ["mmhmm", "Mmhmm.", "mmmhmm", "Mm-hmm.",
                                  "MM-HMM", "mm hmm", "mhm"])
def test_every_spelling_of_mm_hmm_is_one_mhm(text):
    assert count_fillers(text) == count_fillers("mhm"), text


@pytest.mark.parametrize("text", ["uh huh", "Uh huh.", "uh-huh", "uhhuh"])
def test_every_spelling_of_uh_huh_is_one_filler(text):
    assert count_fillers(text) == count_fillers("uhuh"), text


def test_a_space_joins_only_the_backchannels():
    assert sum(count_fillers("um uh").values()) == 2
    assert sum(count_fillers("uh, um").values()) == 2
    assert sum(count_fillers("hmm hmm").values()) == 2


@pytest.mark.parametrize("marked", ["[uh-huh]", "[uh]-huh", "[uh]-[huh]",
                                    "[Mm-hmm].", "[Mm]-[hmm].", "[mmhmm]"])
def test_both_bracketing_forms_count_as_the_bare_backchannel(marked):
    bare = marked.replace("[", "").replace("]", "")
    assert count_fillers(marked) == count_fillers(bare)
    assert sum(count_fillers(marked).values()) == 1


def test_the_unchanged_vocabulary_still_holds():
    for word in ("ahead", "summary", "hermit", "farmer", "erman", "huhu",
                 "well-mannered", "re-erm", "mother-in-law"):
        assert sum(count_fillers(word).values()) == 0, word
    assert sum(count_fillers("um uh er erm uhm hm hmm mm mhm ah").values()) == 10


# ---------------------------------------------------------------------------
# XREF-08: marked and unmarked fillers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, marked", [
    ("so [uh] then [um] right", 2),
    ("so uh then [um] right", 1),
    ("[Mm-hmm].", 1),        # a backchannel bracketed whole
    ("[Mm]-[hmm].", 1),      # element by element, as dumps before T1-18 hold
    ("[uh]-huh", 0),         # half marked is not marked
    ("Mmm.", 0),
    ("]uh[ ok", 0),          # stray brackets enclose nothing
    ("[inaudible] uh", 0),
    ("", 0),
    (None, 0),
])
def test_marked_fillers_are_those_wholly_inside_brackets(text, marked):
    assert count_marked(text) == marked


def test_a_marked_filler_is_counted_once_and_as_itself():
    """Marking may not change what or how many fillers are counted."""
    for text in ("so [uh] then [um] right", "[Mm-hmm].", "[Mm]-[hmm]."):
        assert count_marked(text) == sum(count_fillers(text).values())


def test_a_kept_but_unmarked_filler_is_visible():
    """The bracketing list matches exact spellings, so a lengthened filler
    passes through the composite unmarked; retention alone cannot see it."""
    from evaluation.conditions import get_condition

    bracket = get_condition("filler_bracket")
    for spelling, marked in (("um", 1), ("mm-hmm", 1), ("ummm", 0), ("mmm", 0)):
        text = f"so {spelling} yes"
        s = score_pair(text, text, bracket.transform(text))
        assert (s["retained"], s["output_marked"]) == (1, marked), spelling


# ---------------------------------------------------------------------------
# ESTATS-01: the reference and the utterance set
# ---------------------------------------------------------------------------

def _write(path, rows, legacy):
    fields = (["uid", "condition", "reference", "hypothesis_raw",
               "hypothesis_transformed", "wer"] if legacy else
              ["uid", "condition", "reference_raw", "reference_transformed",
               "hypothesis_raw", "hypothesis_transformed", "wer"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def _rows(legacy):
    """A dump shaped as benchmark_wer writes it.

    u1 holds five transcriber fillers, of which the model heard two. u2 is
    a filler-only reference that the Whisper normaliser empties, so the
    benchmark skipped it under whisper_norm.
    """
    ref1, hyp1 = "um so uh we mm er agreed uh", "um so we uh agreed"
    rows = [
        {"uid": "u1", "condition": "raw", "hypothesis_raw": hyp1,
         "hypothesis_transformed": hyp1},
        {"uid": "u1", "condition": "pipeline_full", "hypothesis_raw": hyp1,
         "hypothesis_transformed": "[Um] so we [uh] agreed."},
        {"uid": "u1", "condition": "whisper_norm", "hypothesis_raw": hyp1,
         "hypothesis_transformed": "so we agreed"},
        {"uid": "u2", "condition": "raw", "hypothesis_raw": "uh",
         "hypothesis_transformed": "uh"},
        {"uid": "u2", "condition": "pipeline_full", "hypothesis_raw": "uh",
         "hypothesis_transformed": "[Uh]"},
    ]
    refs = {"u1": ref1, "u2": "uh"}
    for row in rows:
        transformed = ("so we agreed" if row["condition"] == "whisper_norm"
                       else refs[row["uid"]])
        if legacy:
            row["reference"] = transformed
        else:
            row["reference_raw"] = refs[row["uid"]]
            row["reference_transformed"] = transformed
    return rows


@pytest.mark.parametrize("legacy", [True, False])
def test_recall_divides_by_the_transcriber_fillers(tmp_path, legacy):
    path = tmp_path / "dump.csv"
    _write(path, _rows(legacy), legacy)
    sets = score_dump_sets(path)
    norm = sets["conditions"]["whisper_norm"]
    # The transformed reference held no fillers at all; the transcriber's
    # held five, and the normalised output keeps none of them.
    assert norm["reference_fillers"] == 5
    assert norm["reference_recall"] == 0.0
    # Over its own utterances the composite recovers two of u1's five and
    # u2's one; over the utterance the normaliser also holds, two of five.
    assert sets["conditions"]["pipeline_full"]["reference_recall"] == \
        pytest.approx(3 / 6)
    assert sets["conditions_shared_set"]["pipeline_full"]["reference_recall"] == \
        pytest.approx(2 / 5)
    assert sets["reference_source"].startswith(
        "reference column" if legacy else "reference_raw")


def test_each_condition_keeps_its_own_utterances_and_the_shared_set_is_common(tmp_path):
    path = tmp_path / "dump.csv"
    _write(path, _rows(False), False)
    sets = score_dump_sets(path)
    assert sets["n_utterances"] == 2
    assert sets["n_shared_utterances"] == 1
    assert {s["n_utterances"] for s in sets["conditions_shared_set"].values()} == {1}
    own = sets["conditions"]
    assert own["raw"]["n_utterances"] == 2
    assert own["raw"]["n_utterances_dropped"] == 0
    assert own["whisper_norm"]["n_utterances"] == 1
    assert own["whisper_norm"]["n_utterances_dropped"] == 1


def test_the_normaliser_discard_is_measurable_from_the_primary_block(tmp_path):
    """The size and the fillers of the discard follow from ``conditions``
    alone, as the manuscript computes them; a block in which every
    condition held the same utterances would make the discard read as 0."""
    path = tmp_path / "dump.csv"
    _write(path, _rows(False), False)
    block = score_dump_sets(path)["conditions"]
    raw, norm = block["raw"], block["whisper_norm"]
    assert raw["n_utterances"] - norm["n_utterances"] == \
        norm["n_utterances_dropped"] == 1
    # u2's single filler is the one the discard takes from the model's three.
    assert (raw["raw_fillers"], norm["raw_fillers"]) == (3, 2)


def test_a_conditions_figures_do_not_depend_on_the_others_scored(tmp_path):
    """Scoring the composite alone or beside the normaliser, which lacks
    u2, gives the composite the same figures."""
    path = tmp_path / "dump.csv"
    _write(path, _rows(False), False)
    alone = score_dump_sets(path, conditions=("pipeline_full",))
    beside = score_dump_sets(path, conditions=("pipeline_full", "whisper_norm"))
    assert alone["conditions"]["pipeline_full"] == \
        beside["conditions"]["pipeline_full"]
    assert alone["conditions_shared_set"]["pipeline_full"] != \
        beside["conditions_shared_set"]["pipeline_full"]


def test_an_unknown_reference_is_left_out_not_counted_as_empty(tmp_path):
    """A legacy row with no reference-preserving row for its utterance."""
    path = tmp_path / "dump.csv"
    _write(path, [{"uid": "u9", "condition": "whisper_norm",
                   "reference": "so yes", "hypothesis_raw": "so uh yes",
                   "hypothesis_transformed": "so yes"}], True)
    summary = score_dump_sets(path)["conditions"]["whisper_norm"]
    assert summary["n_reference_unknown"] == 1
    assert summary["reference_recall"] is None
    assert summary["retention"] == 0.0


def test_the_json_records_the_detector_and_both_sets(tmp_path):
    path = tmp_path / "dump.csv"
    _write(path, _rows(False), False)
    out = tmp_path / "summary.json"
    table = tmp_path / "summary.csv"
    assert disfluency.main([str(path), "--json", str(out),
                            "--csv", str(table)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["detector_pattern"] == disfluency._FILLER_PATTERN.pattern
    assert payload["n_shared_utterances"] == 1
    assert "git_commit" in payload["run_metadata"]
    assert set(payload["conditions_shared_set"]) == set(payload["conditions"])
    assert payload["conditions"]["whisper_norm"]["n_utterances_dropped"] == 1
    assert payload["conditions_selected"] is None
    with open(table, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["set"] for r in rows} == {"shared", "own"}
    own = {r["condition"]: r for r in rows if r["set"] == "own"}
    assert own["pipeline_full"]["output_marked"] == "3"
    assert own["raw"]["output_marked"] == "0"


# ---------------------------------------------------------------------------
# Scoring a chosen set of conditions from a sweep dump
#
# A sweep dump holds all seventeen conditions and the committed summary
# covers three, so the selection must not change what the three score.
# ---------------------------------------------------------------------------

def test_the_shared_set_is_taken_over_the_selected_conditions(tmp_path):
    """whisper_norm lacks u2; leaving it out must not drop u2 elsewhere."""
    path = tmp_path / "dump.csv"
    _write(path, _rows(False), False)
    sets = score_dump_sets(path, conditions=("raw", "pipeline_full"))
    assert set(sets["conditions"]) == {"raw", "pipeline_full"}
    assert sets["n_shared_utterances"] == sets["n_utterances"] == 2
    assert sets["conditions"]["raw"]["n_utterances_dropped"] == 0
    assert sets["conditions_shared_set"] == {
        name: {k: v for k, v in s.items() if k != "n_utterances_dropped"}
        for name, s in sets["conditions"].items()}


def test_a_selection_leaves_the_selected_figures_unchanged(tmp_path):
    """Scoring three of a dump's conditions equals scoring the whole dump
    when the conditions left out drop no utterance, as in the AMI sweep."""
    path = tmp_path / "dump.csv"
    rows = _rows(False)
    # A fourth condition holding every utterance, as the sweep's do.
    rows += [dict(r, condition="filler_strip",
                  hypothesis_transformed="so we agreed")
             for r in rows if r["condition"] == "raw"]
    _write(path, rows, False)
    three = ("raw", "pipeline_full", "whisper_norm")
    whole = score_dump_sets(path)
    chosen = score_dump_sets(path, conditions=three)
    for block in ("conditions", "conditions_shared_set"):
        assert chosen[block] == {k: whole[block][k] for k in three}


def test_a_selection_keeps_recall_on_the_transcriber_reference(tmp_path):
    """In an older dump the reference comes from raw's row, even when raw
    is not among the conditions scored."""
    path = tmp_path / "dump.csv"
    _write(path, _rows(True), True)
    norm = score_dump_sets(path, conditions=("whisper_norm",))
    assert norm["conditions"]["whisper_norm"]["reference_fillers"] == 5
    assert norm["conditions"]["whisper_norm"]["n_reference_unknown"] == 0


def test_a_condition_the_dump_lacks_is_refused(tmp_path):
    """A misspelt name must not pass for a condition that scored nothing."""
    path = tmp_path / "dump.csv"
    _write(path, _rows(False), False)
    with pytest.raises(ValueError, match="pipline_full"):
        score_dump_sets(path, conditions=("raw", "pipline_full"))
    out = tmp_path / "summary.json"
    assert disfluency.main([str(path), "--conditions", "raw,pipline_full",
                            "--json", str(out)]) == 2
    assert not out.exists()


def test_the_json_records_the_selection_and_the_dump_digest(tmp_path):
    from provenance import sha256_file

    path = tmp_path / "dump.csv"
    _write(path, _rows(False), False)
    out = tmp_path / "summary.json"
    table = tmp_path / "summary.csv"
    assert disfluency.main([str(path), "--conditions",
                            " raw, pipeline_full ,", "--json", str(out),
                            "--csv", str(table)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["conditions_selected"] == ["raw", "pipeline_full"]
    assert payload["source"] == path.as_posix()
    assert payload["source_sha256"] == sha256_file(path)
    assert set(payload["conditions"]) == {"raw", "pipeline_full"}
    with open(table, encoding="utf-8") as fh:
        assert {r["condition"] for r in csv.DictReader(fh)} == \
            {"raw", "pipeline_full"}
