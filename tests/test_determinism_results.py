"""Pins the committed comparison of one decode across hardware.

``output/evaluation/determinism/determinism_cross_accelerator.json``
compares the first 200 AMI test utterances as five runs decoded them: an
NVIDIA H100 NVL (ARC job 8554985), an NVIDIA L40S (8781724), the condition
sweep's Tesla V100 pass (8917985 task 1), the CPU arm, an AMD EPYC 9634
decoding in float32 (8978759), and the check itself on a Tesla V100 under
seed 0 (8978760, labelled v100_seed0), on the node of the sweep's V100
pass. ``determinism_cross_accelerator_runs.json`` beside it says what each
run was, and its ``regenerate`` entry gives the command, whose inputs stay
on ARC. These tests check that the comparison agrees with the files
committed beside it (the runs record it copies, and the WER reports,
summaries and hardware names of the L40S, CPU and v100_seed0 runs), and
they pin the figures each run reports, so that a regenerated file which
moves one of them is noticed and has to say why.

No model, audio or dump is needed: the tests read the committed files only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from pathlib import Path

import pytest

from provenance import sha256_text_file

_DET = Path(__file__).resolve().parents[1] / "output" / "evaluation" / "determinism"
_CROSS = _DET / "determinism_cross_accelerator.json"
_RUNS = _DET / "determinism_cross_accelerator_runs.json"
#: The runs whose WER report is committed, and where.
_COMMITTED = {"cpu": _DET / "cpu_8978759", "l40s": _DET / "l40s_8781724",
              "v100_seed0": _DET / "v100_8978760"}

# The two utterances on which some pair of runs differs, named by the length
# of the longer hypothesis there; the comparison holds no transcript text.
_FOUR_WORDS = "AMI_EN2002a_H03_MEE071_0150042_0150192"
_TEN_WORDS = "AMI_EN2002a_H00_MEE073_0193562_0193757"


@pytest.fixture(scope="module")
def cross() -> dict:
    return json.loads(_CROSS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def runs_record() -> dict:
    return json.loads(_RUNS.read_text(encoding="utf-8"))


def _report(label: str) -> list[dict]:
    with (_COMMITTED[label] / "wer_seed0_run1.csv").open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestProvenance:
    def test_it_copies_the_committed_runs_record(self, cross, runs_record):
        """The comparison carries the record unchanged and names it by the
        digest every checkout reproduces, so neither can move alone."""
        assert cross["meta"] == runs_record
        assert cross["meta_file"] == {"file": _RUNS.name,
                                      "sha256_lf": sha256_text_file(_RUNS)}

    def test_it_was_made_from_a_clean_tree(self, cross):
        meta = cross["run_metadata"]
        assert meta["git_dirty"] is False
        assert len(meta["git_commit"]) == 40

    def test_each_run_is_described_and_compared_on_its_evidence(self, cross):
        assert list(cross["runs"]) == ["cpu", "h100", "l40s", "v100", "v100_seed0"]
        assert set(cross["meta"]["runs"]) == set(cross["runs"])
        evidence = {label: run["evidence"] for label, run in cross["runs"].items()}
        # The H100's hypotheses were lost: only its logged error rates remain.
        assert evidence == {"cpu": "text", "h100": "wer", "l40s": "text", "v100": "text",
                            "v100_seed0": "text"}
        with_text = ["cpu", "l40s", "v100", "v100_seed0"]
        assert cross["references"]["runs_with_text"] == with_text
        assert cross["references"]["runs_with_reports"] == with_text

    def test_each_input_is_named_by_the_digest_of_its_arc_original(self, cross):
        """sha256sum's output on ARC for each input, as read on 2026-10-04."""
        sha = {label: {role: named["sha256"] for role, named in run["inputs"].items()}
               for label, run in cross["runs"].items()}
        assert sha == {
            "cpu": {
                "dump": "bf04c658c1705170b3eeeb564da9b9127010e6ae3c7327ff59eab144c330bd35",
                "report": "f7dabb952e86a61d51db471182e6f0ea8255eb60eb7ed76351df991c7fad08d7",
                "repeat": "bf04c658c1705170b3eeeb564da9b9127010e6ae3c7327ff59eab144c330bd35"},
            "h100": {
                "log": "d9314bf22e89df8d3fde888abbfc352a2808dd55e68aeb0e668ceb7b35b4425c"},
            "l40s": {
                "dump": "11992b8e6554e14947c949e1b7181e032718a09e9586724bef73922407f159f0",
                "report": "c82ce583b08ed6368749e5d36ae87638d921efe5e8de50bce22afb89b693832b",
                "repeat": "11992b8e6554e14947c949e1b7181e032718a09e9586724bef73922407f159f0"},
            "v100": {
                "dump": "3fa3957260f28a3af42ee0deadcda4445a1fd5142b94ba316127e2e4190716bf",
                "report": "c95a697382354e7bca454f3993f11351f652ab076aaceb7385e6dedb5465b71b",
                "repeat": "631ba63ea553f5059db6cd196d17d833d0ed16a4a8b8a784e0c00cb43f07bcd4"},
            "v100_seed0": {
                "dump": "bf04c658c1705170b3eeeb564da9b9127010e6ae3c7327ff59eab144c330bd35",
                "report": "f7dabb952e86a61d51db471182e6f0ea8255eb60eb7ed76351df991c7fad08d7",
                "repeat": "bf04c658c1705170b3eeeb564da9b9127010e6ae3c7327ff59eab144c330bd35"},
        }

    def test_the_cpu_and_v100_runs_of_the_check_wrote_the_same_files(self, cross):
        """At one commit and under the same seeds, the V100 in float16 and
        the processor in float32 wrote byte-identical hypothesis dumps and
        WER reports, so the comparison names both by the same digests."""
        cpu, v100 = cross["runs"]["cpu"]["inputs"], cross["runs"]["v100_seed0"]["inputs"]
        assert cpu == v100
        assert (sha256_text_file(_COMMITTED["cpu"] / "wer_seed0_run1.csv")
                == sha256_text_file(_COMMITTED["v100_seed0"] / "wer_seed0_run1.csv"))

    @pytest.mark.parametrize("label", sorted(_COMMITTED))
    def test_the_committed_report_is_the_one_compared(self, cross, label):
        """git stores the report with LF where ARC's has CRLF, so the
        line-ending-free digest is the one a checkout reproduces."""
        named = cross["runs"][label]["inputs"]["report"]
        assert sha256_text_file(_COMMITTED[label] / "wer_seed0_run1.csv") == named["sha256_lf"]

    def test_no_transcript_text_is_recorded(self, cross):
        """Differing utterances are listed by id, edit counts and error rates."""
        for block in (*cross["text"].values(), *cross["within_run"].values()):
            for row in block["differing_utterances"]:
                assert set(row) == {"uid", "word_edits", "words_longer", "divergence", "wer"}
        for block in cross["wer_level"].values():
            for row in block["differing_utterances"]:
                assert set(row) == {"uid", "wer"}


class TestConsistency:
    @pytest.mark.parametrize("label", sorted(_COMMITTED))
    def test_the_committed_report_lists_the_compared_utterances(self, cross, label):
        names = [row["name"] for row in _report(label)]
        digest = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()
        assert digest == cross["subset"]["uids_sha256"]
        assert (names[0], names[-1]) == (cross["subset"]["first_uid"],
                                         cross["subset"]["last_uid"])

    @pytest.mark.parametrize("label", sorted(_COMMITTED))
    def test_the_subset_wer_follows_from_the_committed_report(self, cross, label):
        rows = _report(label)
        errors = sum(int(r["substitutions"]) + int(r["deletions"]) + int(r["insertions"])
                     for r in rows)
        words = sum(int(r["reference_words"]) for r in rows)
        wer = cross["subset_wer"][label]
        assert (wer["errors"], wer["reference_words"]) == (errors, words)
        assert wer["micro_wer"] == round(errors / words, 6)
        assert wer["macro_wer"] == round(statistics.fmean(float(r["wer"]) for r in rows), 6)
        assert wer["micro_source"] == "report"

    def test_the_differing_utterances_score_as_the_committed_reports_say(self, cross):
        reports = {label: {r["name"]: float(r["wer"]) for r in _report(label)}
                   for label in _COMMITTED}
        checked = set()
        for block in cross["text"].values():
            for row in block["differing_utterances"]:
                for label in set(row["wer"]) & set(_COMMITTED):
                    assert row["wer"][label] == round(reports[label][row["uid"]], 6)
                    checked.add(label)
        # Each run with a committed report is checked on some utterance.
        assert checked == set(_COMMITTED)

    @pytest.mark.parametrize("label", sorted(_COMMITTED))
    def test_the_committed_summaries_agree_with_the_repeat(self, cross, label):
        repeat = json.loads((_COMMITTED[label] / "determinism_repeat.json")
                            .read_text(encoding="utf-8"))
        seeds = json.loads((_COMMITTED[label] / "determinism_seeds.json")
                           .read_text(encoding="utf-8"))
        assert repeat["runs"] == ["seed0_run1", "seed0_run2"]
        assert seeds["runs"] == ["seed0_run1", "seed1_run1"]
        for summary in (repeat, seeds):
            assert (summary["utterances_compared"], summary["identical"],
                    summary["differing"]) == (200, 200, 0)
        within = cross["within_run"][label]
        assert (within["identical"], within["differing"]) == (repeat["identical"],
                                                              repeat["differing"])

    def test_the_cpu_run_names_its_processor(self, cross):
        cpu = (_COMMITTED["cpu"] / "cpu.txt").read_text(encoding="utf-8").strip()
        assert cpu == "AMD EPYC 9634 84-Core Processor"
        assert cross["meta"]["runs"]["cpu"]["host_processor"].startswith(cpu)
        gpu = (_COMMITTED["l40s"] / "gpu.txt").read_text(encoding="utf-8").strip()
        assert cross["meta"]["runs"]["l40s"]["accelerator"] == gpu

    def test_both_v100_runs_name_the_card_the_v100_job_wrote(self, cross):
        gpu = (_COMMITTED["v100_seed0"] / "gpu.txt").read_text(encoding="utf-8").strip()
        assert gpu == "Tesla V100-PCIE-32GB"
        runs = cross["meta"]["runs"]
        assert runs["v100_seed0"]["accelerator"] == runs["v100"]["accelerator"] == gpu
        assert runs["v100_seed0"]["node"] == runs["v100"]["node"] == "htc-g004"


class TestPinnedFigures:
    """The figures as committed; a regeneration that moves one must say why."""

    def test_the_subset(self, cross):
        assert cross["condition"] == "raw"
        assert cross["subset"] == {
            "from_run": "l40s", "utterances": 200,
            "uids_sha256": "cdf00e66a6ec63d50c5ec15f584454fee8f2bf66f4e7da189e08ea33e33bf34d",
            "first_uid": "AMI_EN2002a_H00_MEE073_0019663_0019800",
            "last_uid": "AMI_EN2002a_H02_FEO072_0082966_0083521"}
        assert cross["references"]["utterances_whose_reference_differs"] == 0
        assert cross["references"]["utterances_whose_reference_word_count_differs"] == 0

    def test_what_the_cpu_run_was(self, cross):
        cpu = cross["meta"]["runs"]["cpu"]
        assert (cpu["job"], cpu["date"], cpu["node"]) == ("8978759", "2026-10-04", "htc-c074")
        assert (cpu["precision"], cpu["threads"], cpu["code_commit"]) == ("float32", 16, "f2578b8")
        assert cpu["accelerator"].startswith("none")
        assert cpu["seeds"] == [0, 1]
        assert cpu["decodes"] == ["seed0_run1", "seed0_run2", "seed1_run1"]

    def test_what_the_v100_run_of_the_check_was(self, cross):
        """The check's own decodes on the sweep's card model and node,
        under the L40S run's seed, at the CPU run's commit."""
        v100 = cross["meta"]["runs"]["v100_seed0"]
        assert (v100["job"], v100["date"], v100["node"]) == ("8978760", "2026-10-04", "htc-g004")
        assert ((v100["precision"], v100["threads"], v100["code_commit"])
                == ("float16", 8, "f2578b8"))
        assert (v100["driver"].startswith("580.65.06")
                and v100["cuda_module"].startswith("CUDA/13.0.2"))
        assert v100["seeds"] == [0, 1]
        assert v100["decodes"] == ["seed0_run1", "seed0_run2", "seed1_run1"]

    def test_the_text_pairs(self, cross):
        """The processor and both V100 runs give the same words on all 200
        utterances, and each differs from the L40S on the same two."""
        counts = {pair: (block["identical"], block["differing"])
                  for pair, block in cross["text"].items()}
        assert counts == {"cpu_vs_l40s": (198, 2), "cpu_vs_v100": (200, 0),
                          "cpu_vs_v100_seed0": (200, 0), "l40s_vs_v100": (198, 2),
                          "l40s_vs_v100_seed0": (198, 2), "v100_vs_v100_seed0": (200, 0)}
        for pair in ("cpu_vs_v100", "cpu_vs_v100_seed0", "v100_vs_v100_seed0"):
            assert cross["text"][pair]["differing_utterances"] == []
        for pair, other in (("cpu_vs_l40s", "cpu"), ("l40s_vs_v100", "v100"),
                            ("l40s_vs_v100_seed0", "v100_seed0")):
            rows = {row["uid"]: row for row in cross["text"][pair]["differing_utterances"]}
            assert set(rows) == {_FOUR_WORDS, _TEN_WORDS}
            assert (rows[_FOUR_WORDS]["word_edits"], rows[_FOUR_WORDS]["words_longer"]) == (2, 4)
            assert (rows[_TEN_WORDS]["word_edits"], rows[_TEN_WORDS]["words_longer"]) == (2, 10)
            assert rows[_FOUR_WORDS]["wer"] == {"l40s": 0.0, other: 0.25}
            assert rows[_TEN_WORDS]["wer"] == {"l40s": 0.111111, other: 0.333333}

    def test_each_run_that_repeated_itself_agreed(self, cross):
        """The CPU, L40S and v100_seed0 repeats cover both utterances on
        which runs differ; the sweep's V100 pass was repeated on the first
        10 utterances only, neither of them."""
        coverage = {label: (block["identical"], block["differing"],
                            block["coverage"]["utterances_covered"],
                            block["coverage"]["differing_across_runs"],
                            block["coverage"]["differing_across_runs_covered"])
                    for label, block in cross["within_run"].items()}
        assert coverage == {"cpu": (200, 0, 200, 2, 2), "l40s": (200, 0, 200, 2, 2),
                            "v100": (10, 0, 10, 2, 0), "v100_seed0": (200, 0, 200, 2, 2)}

    def test_the_h100_through_its_logged_error_rates(self, cross):
        """A lower bound on differing text: it scores like the CPU and both
        V100 runs on one utterance and like the L40S on the other."""
        differs = {pair: {row["uid"]: row["wer"] for row in block["differing_utterances"]}
                   for pair, block in cross["wer_level"].items()}
        assert differs == {
            "cpu_vs_h100": {_FOUR_WORDS: {"cpu": 0.25, "h100": 0.0}},
            "h100_vs_l40s": {_TEN_WORDS: {"h100": 0.333, "l40s": 0.111}},
            "h100_vs_v100": {_FOUR_WORDS: {"h100": 0.0, "v100": 0.25}},
            "h100_vs_v100_seed0": {_FOUR_WORDS: {"h100": 0.0, "v100_seed0": 0.25}},
        }
        assert all(block["is_lower_bound_on_text_differences"]
                   for block in cross["wer_level"].values())

    def test_the_subset_wer(self, cross):
        wer = {label: (w["errors"], w["reference_words"], w["micro_wer"], w["macro_wer"])
               for label, w in cross["subset_wer"].items()}
        assert wer == {"cpu": (451, 1067, 0.42268, 1.492826),
                       "h100": (450, 1067, 0.421743, 1.491576),
                       "l40s": (448, 1067, 0.419869, 1.490465),
                       "v100": (451, 1067, 0.42268, 1.492826),
                       "v100_seed0": (451, 1067, 0.42268, 1.492826)}
        assert cross["subset_wer"]["h100"]["logged_macro_wer"] == 1.4916
