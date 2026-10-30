"""Tests for the verbatim hypothesis dump in the word error rate benchmark.

The per-condition reports carry metrics and nothing else, so a claim such
as "the production composite preserves disfluencies" cannot be checked
against them: the aggregate rate says a condition changed the score, not
what it did to the words. Recovering the text meant transcribing the
corpus again, which is the GPU cost the run had already paid. This dump
records the text as each pair is scored.

Nothing here needs a model, a GPU or the corpus.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.benchmark_wer import HypothesisDump, _build_parser


def _read(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestHypothesisDump:
    def test_a_row_carries_the_text_behind_the_score(self, tmp_path):
        path = tmp_path / "hyp.csv"
        with HypothesisDump(path) as dump:
            dump.write("utt-1", "raw", "the cat sat", "the cat sat uh",
                       "the cat sat uh", 0.25)
        row, = _read(path)
        assert row["uid"] == "utt-1"
        assert row["condition"] == "raw"
        assert row["reference_raw"] == "the cat sat"
        assert row["hypothesis_raw"] == "the cat sat uh"
        assert row["hypothesis_transformed"] == "the cat sat uh"
        assert float(row["wer"]) == pytest.approx(0.25)

    def test_both_references_are_kept_for_a_reference_transform(self, tmp_path):
        """EWER-22: the transcriber's text and the normalised one, apart."""
        path = tmp_path / "hyp.csv"
        with HypothesisDump(path) as dump:
            dump.write("utt-1", "whisper_norm", "So, um, yes.", "so um yes",
                       "so yes", 0.0, reference_transformed="so yes")
            dump.write("utt-1", "raw", "So, um, yes.", "so um yes",
                       "so um yes", 0.0)
        norm, raw = _read(path)
        assert norm["reference_raw"] == "So, um, yes."
        assert norm["reference_transformed"] == "so yes"
        # A condition that leaves the reference alone repeats it.
        assert raw["reference_transformed"] == raw["reference_raw"]
        assert "reference" not in norm

    def test_the_raw_and_transformed_hypotheses_are_kept_apart(self, tmp_path):
        """The whole point: what the model said, and what the condition did."""
        path = tmp_path / "hyp.csv"
        with HypothesisDump(path) as dump:
            dump.write("utt-1", "filler_strip", "the cat sat",
                       "the uh cat sat", "the cat sat", 0.0)
        row, = _read(path)
        assert "uh" in row["hypothesis_raw"]
        assert "uh" not in row["hypothesis_transformed"]

    def test_one_row_per_condition_for_the_same_utterance(self, tmp_path):
        path = tmp_path / "hyp.csv"
        with HypothesisDump(path) as dump:
            dump.write("utt-1", "raw", "ref", "hyp", "hyp", 0.1)
            dump.write("utt-1", "pipeline_full", "ref", "hyp", "hyp!", 0.2)
        rows = _read(path)
        assert [r["condition"] for r in rows] == ["raw", "pipeline_full"]
        assert {r["uid"] for r in rows} == {"utt-1"}
        assert dump.rows == 2

    def test_rows_are_readable_before_the_run_ends(self, tmp_path):
        """A job killed at the wall-clock limit must leave usable data."""
        path = tmp_path / "hyp.csv"
        dump = HypothesisDump(path)
        dump.write("utt-1", "raw", "ref", "hyp", "hyp", 0.5)
        assert len(_read(path)) == 1      # still open
        dump.close()

    def test_text_containing_commas_quotes_and_newlines_round_trips(self, tmp_path):
        """Transcript text is arbitrary; the CSV must survive it."""
        path = tmp_path / "hyp.csv"
        awkward = 'she said, "well, yes"\nand then stopped'
        with HypothesisDump(path) as dump:
            dump.write("utt-1", "raw", awkward, awkward, awkward, 0.0)
        row, = _read(path)
        assert row["reference_raw"] == awkward
        assert row["hypothesis_raw"] == awkward

    def test_non_ascii_text_survives(self, tmp_path):
        path = tmp_path / "hyp.csv"
        with HypothesisDump(path) as dump:
            dump.write("utt-1", "raw", "wszędzie", "wszędzie",
                       "wszedzie", 0.5)
        row, = _read(path)
        assert row["reference_raw"] == "wszędzie"
        assert row["hypothesis_transformed"] == "wszedzie"

    def test_a_missing_parent_directory_is_created(self, tmp_path):
        path = tmp_path / "nested" / "deeper" / "hyp.csv"
        with HypothesisDump(path) as dump:
            dump.write("utt-1", "raw", "ref", "hyp", "hyp", 0.0)
        assert path.exists()

    def test_closing_twice_is_harmless(self, tmp_path):
        dump = HypothesisDump(tmp_path / "hyp.csv")
        dump.close()
        dump.close()

    def test_an_empty_dump_still_has_its_header(self, tmp_path):
        """So a consumer can read it without special-casing an empty run."""
        path = tmp_path / "hyp.csv"
        HypothesisDump(path).close()
        assert path.read_text(encoding="utf-8").strip() == \
            ",".join(HypothesisDump.FIELDNAMES)


class TestCommandLine:
    def test_the_flag_is_off_by_default(self):
        """The dump holds transcript text, so it is opt-in."""
        assert _build_parser().parse_args(
            ["--report", "r.csv", "--summary", "s.json"]).dump_hypotheses is None

    def test_the_flag_takes_a_path(self):
        args = _build_parser().parse_args(["--dump-hypotheses", "out/h.csv",
                                         "--report", "r.csv", "--summary", "s.json"])
        assert args.dump_hypotheses == Path("out/h.csv")
