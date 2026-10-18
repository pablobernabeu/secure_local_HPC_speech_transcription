"""Tests for the comparison of one decode across hardware.

The comparison is how a claim that a transcript can be recovered on another
machine becomes a number, so its failure modes are the ones that would
overstate agreement: comparing on the part of a run that survived, reading
the wrong decode out of a log, treating equal error rates as equal words,
taking a repeat's agreement for agreement where it never decoded, or
letting transcript text into a committed result.

The transcripts below are invented. They copy the edit structure of the
two utterances on which the committed comparison's runs differ (two word
edits each, over four and ten words), not their text.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.determinism_cross import (
    build,
    compare_repeat,
    compare_text,
    compare_wer,
    main,
    read_dump,
    read_log,
    read_report,
    subset_wer,
)

_NEW = ["uid", "condition", "reference_raw", "reference_transformed",
        "hypothesis_raw", "hypothesis_transformed", "wer"]
_OLD = ["uid", "condition", "reference", "hypothesis_raw",
        "hypothesis_transformed", "wer"]
_REPORT = ["name", "wer", "mer", "wil", "cer", "hits", "substitutions",
           "deletions", "insertions", "reference_words", "hypothesis_words"]


def _dump(path: Path, rows, layout=_NEW) -> Path:
    """rows: (uid, reference, hypothesis, wer), all condition raw."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=layout)
        writer.writeheader()
        for uid, ref, hyp, wer in rows:
            row = {"uid": uid, "condition": "raw", "hypothesis_raw": hyp,
                   "hypothesis_transformed": hyp, "wer": f"{wer:.6f}"}
            if layout is _NEW:
                row.update(reference_raw=ref, reference_transformed=ref)
            else:
                row["reference"] = ref
            writer.writerow(row)
    return path


def _report(path: Path, rows) -> Path:
    """rows: (uid, errors, reference_words)."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_REPORT)
        writer.writeheader()
        for uid, errors, words in rows:
            writer.writerow({"name": uid, "wer": errors / words, "mer": 0, "wil": 0,
                             "cer": 0, "hits": words - errors, "substitutions": errors,
                             "deletions": 0, "insertions": 0,
                             "reference_words": words, "hypothesis_words": words})
    return path


def _log(path: Path, decodes: dict[str, dict[str, float]]) -> Path:
    """A determinism job log: one block per decode, in insertion order."""
    lines = ["DETERMINISM AND SEED ROBUSTNESS", "Suite:   ami"]
    for name, wers in decodes.items():
        lines += [f"--- {name} ---", "Corpus:     edinburghcstr/ami/ihm  split=test"]
        lines += [f"  {uid}  raw={wer:.3f}" for uid, wer in wers.items()]
        macro = sum(wers.values()) / len(wers)
        lines += ["  skipping x: empty reference after normalisation",
                  f"  [raw]  n={len(wers)}  WER={macro:.4f}  MER=0.1000  ref_words=9"]
    lines += ["  utterances compared:  2", "  identical everywhere: 2 (100.000%)"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def test_both_dump_layouts_give_the_corpus_reference(tmp_path):
    rows = [("u1", "THE CAT", "the cat", 0.0)]
    new = read_dump(_dump(tmp_path / "new.csv", rows))
    old = read_dump(_dump(tmp_path / "old.csv", rows, layout=_OLD))
    assert new == old == {"u1": {"reference": "THE CAT", "hypothesis": "the cat",
                                 "wer": 0.0}}


def test_a_dump_must_name_each_utterance_once(tmp_path):
    path = _dump(tmp_path / "d.csv", [("u1", "a", "a", 0.0), ("u1", "a", "b", 1.0)])
    with pytest.raises(ValueError, match="twice"):
        read_dump(path)


def test_a_report_gives_error_counts(tmp_path):
    report = read_report(_report(tmp_path / "r.csv", [("u1", 2, 8)]))
    assert report == {"u1": {"wer": 0.25, "errors": 2, "reference_words": 8}}


def test_the_first_decode_of_a_log_is_read_by_default(tmp_path):
    path = _log(tmp_path / "job.out", {"seed 0, run 1": {"u1": 0.5, "u2": 0.0},
                                       "seed 0, run 2": {"u1": 0.25, "u2": 0.0}})
    first = read_log(path)
    assert first["block"] == "seed 0, run 1"
    assert first["wer"] == {"u1": 0.5, "u2": 0.0}
    assert first["logged_macro_wer"] == 0.25 and first["logged_n"] == 2
    second = read_log(path, block="seed 0, run 2")
    assert second["wer"]["u1"] == 0.25
    with pytest.raises(ValueError, match="no decode"):
        read_log(path, block="seed 9, run 1")


def test_a_log_without_headers_is_read_whole(tmp_path):
    path = tmp_path / "plain.out"
    path.write_text("ASR model:  m\n  u1  raw=0.500  case_fold=0.250\n"
                    "  u2  raw=0.000  case_fold=0.000\n", encoding="utf-8")
    assert read_log(path)["wer"] == {"u1": 0.5, "u2": 0.0}
    assert read_log(path, condition="case_fold")["wer"]["u1"] == 0.25
    with pytest.raises(ValueError, match="no per-utterance"):
        read_log(path, condition="whisper_norm")


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

def test_text_differences_are_listed_by_id_without_their_text():
    a = {"u1": {"reference": "r", "hypothesis": "The lamp is on.", "wer": 0.0},
         "u2": {"reference": "r", "hypothesis": "same", "wer": 0.0}}
    b = {"u1": {"reference": "r", "hypothesis": "The lamp is?", "wer": 0.25},
         "u2": {"reference": "r", "hypothesis": "same", "wer": 0.0}}
    result = compare_text("a", a, "b", b, ["u1", "u2"])
    assert result["identical"] == 1 and result["differing"] == 1
    assert result["differing_utterances"] == [
        {"uid": "u1", "word_edits": 2, "words_longer": 4, "divergence": 0.5,
         "wer": {"a": 0.0, "b": 0.25}}]
    assert "lamp" not in json.dumps(result)


def test_a_repeat_reports_what_it_covers():
    """A repeat that agrees where it decoded says nothing where it did not."""
    run = {u: {"reference": "R", "hypothesis": f"h {u}", "wer": 0.0}
           for u in ("u1", "u2", "u3", "u4")}
    repeat = {"u1": dict(run["u1"]), "u2": dict(run["u2"], hypothesis="other")}
    result = compare_repeat("v100", run, repeat, ["u1", "u2", "u3", "u4"],
                            differing_across_runs=["u2", "u4"])
    assert result["runs"] == ["v100", "v100_repeat"]
    assert result["identical"] == 1 and result["differing"] == 1
    assert [d["uid"] for d in result["differing_utterances"]] == ["u2"]
    assert result["references_differing"] == 0
    assert result["coverage"] == {
        "utterances_covered": 2, "of_compared": 4, "covers_the_first_n": True,
        "differing_across_runs": 2, "differing_across_runs_covered": 1}
    # Utterances outside the comparison do not count, and a gap in the
    # middle is not the first n.
    later = compare_repeat("v100", run, {"u3": run["u3"], "u9": run["u1"]},
                           ["u1", "u2", "u3", "u4"])
    assert later["identical"] == 1
    assert later["coverage"]["utterances_covered"] == 1
    assert later["coverage"]["covers_the_first_n"] is False
    with pytest.raises(ValueError, match="none of the 4"):
        compare_repeat("v100", run, {"u9": run["u1"]}, ["u1", "u2", "u3", "u4"])


def test_equal_error_rates_are_not_taken_for_equal_words():
    """'gonna' and 'going to' can score alike; only a WER that differs counts."""
    result = compare_wer("a", {"u1": 1 / 3, "u2": 0.0}, "b", {"u1": 0.333, "u2": 0.25},
                         ["u1", "u2"])
    assert result["wer_differs"] == 1
    assert result["differing_utterances"] == [{"uid": "u2", "wer": {"a": 0.0, "b": 0.25}}]
    assert result["is_lower_bound_on_text_differences"] is True


def test_the_pooled_wer_is_exact_from_a_report_and_rebuilt_from_a_log():
    uids = ["u1", "u2"]
    report = {"u1": {"wer": 1 / 9, "errors": 1, "reference_words": 9},
              "u2": {"wer": 0.0, "errors": 0, "reference_words": 4}}
    exact = subset_wer({u: r["wer"] for u, r in report.items()}, uids, report=report)
    assert exact["errors"] == 1 and exact["micro_wer"] == round(1 / 13, 6)
    # Three decimals of 3/9 rebuild three errors exactly.
    rebuilt = subset_wer({"u1": 0.333, "u2": 0.0}, uids,
                         reference_words={"u1": 9, "u2": 4}, places=3)
    assert rebuilt["errors"] == 3 and rebuilt["micro_wer"] == round(3 / 13, 6)
    assert rebuilt["macro_wer"] == round((3 / 9) / 2, 6)
    # With a thousand reference words the rounding could cost a whole error.
    refused = subset_wer({"u1": 0.333, "u2": 0.0}, uids,
                         reference_words={"u1": 1000, "u2": 4}, places=3)
    assert "micro_wer" not in refused


# ---------------------------------------------------------------------------
# The whole comparison
# ---------------------------------------------------------------------------

_REFS = {"u1": "THE LAMP IS ON", "u2": "WE WERE GONNA PAINT THE FENCE BY THE LAKE",
         "u3": "RIGHT"}
_L40S = {"u1": "The lamp is on.", "u2": "we were gonna paint the fence by that lake.",
         "u3": "Right."}


@pytest.fixture()
def three_runs(tmp_path):
    refs = _REFS
    l40s = _dump(tmp_path / "seed0_run1.csv", [
        ("u1", refs["u1"], _L40S["u1"], 0.0),
        ("u2", refs["u2"], _L40S["u2"], 1 / 9),
        ("u3", refs["u3"], _L40S["u3"], 0.0)], layout=_OLD)
    l40s_report = _report(tmp_path / "wer_seed0_run1.csv",
                          [("u1", 0, 4), ("u2", 1, 9), ("u3", 0, 1)])
    # The sweep dump holds more of the split than the check decoded.
    v100 = _dump(tmp_path / "sweep.csv", [
        ("u1", refs["u1"], "The lamp is?", 0.25),
        ("u2", refs["u2"], "we were going to paint the fence by that lake.", 3 / 9),
        ("u3", refs["u3"], "Right.", 0.0),
        ("u4", "MORE", "More.", 0.0)])
    v100_report = _report(tmp_path / "sweep_report.csv",
                          [("u1", 1, 4), ("u2", 3, 9), ("u3", 0, 1), ("u4", 0, 1)])
    h100 = _log(tmp_path / "determinism_1.out",
                {"seed 0, run 1": {"u1": 0.0, "u2": 0.333, "u3": 0.0},
                 "seed 0, run 2": {"u1": 0.0, "u2": 0.333, "u3": 0.0}})
    return {"dumps": {"l40s": l40s, "v100": v100},
            "reports": {"l40s": l40s_report, "v100": v100_report},
            "logs": {"h100": h100}, "tmp": tmp_path}


def test_three_cards_compared_on_the_checks_utterances(three_runs):
    result = build(three_runs["dumps"], three_runs["reports"], three_runs["logs"],
                   subset="l40s")
    assert list(result["runs"]) == ["h100", "l40s", "v100"]
    assert result["subset"]["utterances"] == 3
    assert result["references"]["utterances_whose_reference_differs"] == 0
    pair = result["text"]["l40s_vs_v100"]
    assert pair["identical"] == 1 and pair["differing"] == 2
    # The H100 kept no text, so it is compared on error rates, and only
    # where it is one of the pair.
    assert set(result["wer_level"]) == {"h100_vs_l40s", "h100_vs_v100"}
    assert result["wer_level"]["h100_vs_l40s"]["wer_differs"] == 1
    assert result["wer_level"]["h100_vs_v100"]["wer_differs"] == 1
    assert result["subset_wer"]["l40s"]["errors"] == 1
    assert result["subset_wer"]["v100"]["errors"] == 4
    assert result["subset_wer"]["h100"]["errors"] == 3
    assert result["subset_wer"]["h100"]["logged_macro_wer"] == round(0.333 / 3, 4)
    assert result["runs"]["h100"]["inputs"]["log"]["decode_read"] == "seed 0, run 1"
    # Without a repeat, nothing is claimed about any run repeating itself.
    assert result["within_run"] == {}
    # No transcript text reaches the result.
    text = json.dumps(result)
    assert "lamp" not in text.lower() and "fence" not in text.lower()


def test_each_input_is_named_by_its_bytes_and_by_its_text(three_runs):
    """The raw digest matches the cluster's original, whose CSV rows end in
    CRLF; the LF digest matches a committed copy on any checkout."""
    result = build(three_runs["dumps"], three_runs["reports"], three_runs["logs"],
                   subset="l40s")
    dump = three_runs["dumps"]["l40s"]
    raw = dump.read_bytes()
    assert b"\r\n" in raw
    named = result["runs"]["l40s"]["inputs"]["dump"]
    assert named == {"file": "seed0_run1.csv",
                     "sha256": hashlib.sha256(raw).hexdigest(),
                     "sha256_lf": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()}
    assert named["sha256"] != named["sha256_lf"]
    # The same text with LF endings, as git checks a committed copy out on
    # Linux, has the same LF digest.
    lf_copy = three_runs["tmp"] / "lf" / "seed0_run1.csv"
    lf_copy.parent.mkdir()
    lf_copy.write_bytes(raw.replace(b"\r\n", b"\n"))
    again = build({"l40s": lf_copy, "v100": three_runs["dumps"]["v100"]}, {}, {},
                  subset="l40s")
    assert again["runs"]["l40s"]["inputs"]["dump"]["sha256_lf"] == named["sha256_lf"]
    for run in result["runs"].values():
        for named_input in run["inputs"].values():
            assert {"file", "sha256", "sha256_lf"} <= set(named_input)


def test_a_repeat_is_compared_with_its_runs_text(three_runs):
    t = three_runs
    # A second V100 decode that reached only the first utterance, which the
    # runs differ on, and agrees there.
    repeat = _dump(t["tmp"] / "preflight.csv", [("u1", _REFS["u1"], "The lamp is?", 0.25)])
    result = build(t["dumps"], t["reports"], t["logs"], subset="l40s",
                   repeats={"v100": repeat})
    within = result["within_run"]["v100"]
    assert within["identical"] == 1 and within["differing"] == 0
    assert within["coverage"] == {
        "utterances_covered": 1, "of_compared": 3, "covers_the_first_n": True,
        "differing_across_runs": 2, "differing_across_runs_covered": 1}
    assert result["runs"]["v100"]["inputs"]["repeat"]["file"] == "preflight.csv"
    # The cross-run comparison is untouched by the repeat.
    assert result["text"]["l40s_vs_v100"]["differing"] == 2
    assert "lamp" not in json.dumps(result).lower()


def test_a_repeat_needs_a_run_with_text(three_runs):
    t = three_runs
    with pytest.raises(ValueError, match="no dump"):
        build(t["dumps"], t["reports"], t["logs"], subset="l40s",
              repeats={"h100": t["dumps"]["l40s"]})


def test_a_run_missing_a_compared_utterance_is_refused(three_runs):
    short = _dump(three_runs["tmp"] / "short.csv", [("u1", "R", "h", 0.0)])
    with pytest.raises(ValueError, match="lacks 2 of the 3"):
        build({"l40s": three_runs["dumps"]["l40s"], "cut": short}, {}, {},
              subset="l40s")


def test_disagreeing_references_are_reported(three_runs):
    other = _dump(three_runs["tmp"] / "other.csv", [
        ("u1", "SOMETHING ELSE", _L40S["u1"], 0.0),
        ("u2", _REFS["u2"], "x", 1.0),
        ("u3", _REFS["u3"], _L40S["u3"], 0.0)])
    result = build({"l40s": three_runs["dumps"]["l40s"], "other": other}, {}, {},
                   subset="l40s")
    assert result["references"]["utterances_whose_reference_differs"] == 1


def test_the_command_line_writes_lf_json_with_the_meta(three_runs, tmp_path):
    meta = tmp_path / "runs.json"
    meta.write_text(json.dumps({"runs": {"h100": {"job": "1"}}}), encoding="utf-8")
    out = tmp_path / "out" / "cross.json"
    t = three_runs
    code = main(["--dump", f"l40s={t['dumps']['l40s']}",
                 "--report", f"l40s={t['reports']['l40s']}",
                 "--dump", f"v100={t['dumps']['v100']}",
                 "--log", f"h100={t['logs']['h100']}",
                 "--repeat", f"l40s={t['dumps']['l40s']}",
                 "--subset", "l40s", "--meta", str(meta), "--json", str(out)])
    assert code == 0
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    result = json.loads(raw)
    assert result["meta"] == {"runs": {"h100": {"job": "1"}}}
    assert result["meta_file"]["file"] == "runs.json"
    assert list(result).index("meta_file") == list(result).index("meta") + 1
    # The V100 gave no report here: its pooled WER is rebuilt from its dump
    # with the L40S's reference word counts.
    assert result["subset_wer"]["v100"]["errors"] == 4
    # A decode compared with itself agrees on everything it covers.
    assert result["within_run"]["l40s"]["identical"] == 3
    assert result["within_run"]["l40s"]["coverage"]["differing_across_runs_covered"] == 2


def test_the_command_line_refuses_bad_input(three_runs, tmp_path):
    t = three_runs
    assert main(["--dump", f"l40s={t['dumps']['l40s']}", "--subset", "l40s"]) == 2
    assert main(["--dump", "l40s", "--dump", f"v100={t['dumps']['v100']}",
                 "--subset", "l40s"]) == 2
    assert main(["--dump", f"l40s={t['dumps']['l40s']}",
                 "--dump", f"v100={tmp_path / 'nowhere.csv'}", "--subset", "l40s"]) == 2
    assert main(["--dump", f"l40s={t['dumps']['l40s']}",
                 "--dump", f"v100={t['dumps']['v100']}", "--subset", "cpu"]) == 2
    # A repeat for a run with no text, a missing repeat, and a second
    # repeat of one run.
    pair = ["--dump", f"l40s={t['dumps']['l40s']}", "--log", f"h100={t['logs']['h100']}",
            "--subset", "l40s"]
    assert main([*pair, "--repeat", f"h100={t['dumps']['l40s']}"]) == 2
    assert main([*pair, "--repeat", f"l40s={tmp_path / 'nowhere.csv'}"]) == 2
    assert main([*pair, "--repeat", f"l40s={t['dumps']['l40s']}",
                 "--repeat", f"l40s={t['dumps']['v100']}"]) == 2
