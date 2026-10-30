"""Objective tests of the committed voice-anonymisation results.

These tests make no network calls, need no GPU and run no model. They read
the two committed runs of ``evaluation.benchmark_anonymisation``:

  output/evaluation/anonymisation_summary.json and anonymisation_report.csv
      the multi-meeting sample, ARC job 8917989 (hpc/runs/anonymisation.env)
  output/evaluation/anonymisation_single_meeting/
      the single-meeting sample, ARC job 8917988
      (hpc/runs/anonymisation_single_meeting.env)

Three kinds of assertion are made. The summary must be what the benchmark's
own functions make of its per-utterance report: the word error rates, the
loop screen and the level checks re-pool from the counts, and the chance
level, trials and exclusions of every candidate set follow from the speaker,
meeting and channel labels alone. The sample must be the one the summary
and the run record describe. And the headline figures are pinned, so that
replacing either file is a deliberate change that updates this module too.

The linkage rates themselves cannot be re-derived here: they need the
speaker embeddings, which the benchmark does not write out.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evaluation import benchmark_anonymisation as ba
from evaluation.revisions import revision_for

_EVAL = _ROOT / "output" / "evaluation"
_RUNS = {
    # name: (directory, run record, preset)
    "multi_meeting": (_EVAL, "anonymisation.env", "multi-meeting"),
    "single_meeting": (_EVAL / "anonymisation_single_meeting",
                       "anonymisation_single_meeting.env", "single-meeting"),
}
# What hpc/submit_anonymisation.sh sets for each preset.
_PRESETS = {"multi-meeting": {"limit": 400, "per_meeting": 25},
            "single-meeting": {"limit": 200, "per_meeting": None}}
_ALPHAS = ["0.5", "0.7", "0.8", "0.9"]
_COMMIT = "6f9bf56a0d5839920537f23d73a166dc0f1e478b"
_WESPEAKER = "pyannote/wespeaker-voxceleb-resnet34-LM"
_INTEGER_COLUMNS = (
    "reference_words", "hypothesis_words_original", "hypothesis_words_control",
    "hypothesis_words_anonymised", "insertions_original",
    "insertions_anonymised", "insertions_control", "errors_original",
    "errors_control", "errors_anonymised", "degenerate_baseline",
    "knee_samples")
_FLOAT_COLUMNS = ("alpha", "self_similarity", "wer_original", "wer_control",
                  "wer_anonymised", "level_ratio")


def _load(name):
    directory, record, preset = _RUNS[name]
    summary = json.loads((directory / "anonymisation_summary.json")
                         .read_text(encoding="utf-8"))
    with (directory / "anonymisation_report.csv").open(
            newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for column in _INTEGER_COLUMNS:
            row[column] = int(row[column])
        for column in _FLOAT_COLUMNS:
            row[column] = float(row[column])
    by_alpha = {a: [r for r in rows if r["alpha"] == float(a)] for a in _ALPHAS}
    return SimpleNamespace(name=name, summary=summary, rows=rows,
                           by_alpha=by_alpha, record=_ROOT / "hpc" / "runs" / record,
                           preset=preset)


@pytest.fixture(scope="module", params=sorted(_RUNS))
def run(request):
    return _load(request.param)


def _labels(rows):
    """Speakers, meetings and channels of the sample, in report order."""
    return ([r["speaker"] for r in rows], [r["meeting"] for r in rows],
            [r["channel"] for r in rows])


def _arm(rows, arm):
    """One arm of the report as the scored pairs summarise() expects.

    The report keeps each pair's total errors, not their split into
    substitutions, deletions and insertions, which is all a pooled rate
    needs; the loop screen reads the hypothesis length.
    """
    return [SimpleNamespace(substitutions=r[f"errors_{arm}"], deletions=0,
                            insertions=0, reference_words=r["reference_words"],
                            hypothesis_words=r[f"hypothesis_words_{arm}"])
            for r in rows]


# ---------------------------------------------------------------------------
# The sample is the one described
# ---------------------------------------------------------------------------

class TestSample:
    def test_every_alpha_scores_the_same_utterances_in_the_same_order(self, run):
        assert sorted(run.summary["by_alpha"]) == _ALPHAS
        assert len(run.rows) == len(_ALPHAS) * run.summary["n_utterances"]
        first = [r["uid"] for r in run.by_alpha[_ALPHAS[0]]]
        assert len(set(first)) == run.summary["n_utterances"]
        for a in _ALPHAS:
            assert [r["uid"] for r in run.by_alpha[a]] == first
            assert run.summary["by_alpha"][a]["n_utterances"] == len(first)

    def test_the_labels_agree_with_the_utterance_ids(self, run):
        # AMI IHM ids read AMI_<meeting>_<channel>_<speaker>_<begin>_<end>.
        for r in run.rows:
            _, meeting, channel, speaker, _, _ = r["uid"].split("_")
            assert (r["meeting"], r["channel"], r["speaker"]) == \
                (meeting, channel, speaker)

    def test_the_per_meeting_counts_are_the_reports(self, run):
        rows = run.by_alpha[_ALPHAS[0]]
        speakers, meetings, _ = _labels(rows)
        counts = Counter(meetings)
        s = run.summary
        # Insertion order is the order the meetings were drawn in.
        assert list(s["accepted_by_meeting"].items()) == list(counts.items())
        assert s["n_meetings"] == len(counts)
        assert s["meetings"] == sorted(counts)
        assert s["n_speakers"] == len(set(speakers))
        assert s["per_meeting_cap"] == s["requested"]["per_meeting"]
        if s["per_meeting_cap"] is not None:
            # EPRIV-03: the cap is enforced on what is accepted.
            assert max(counts.values()) <= s["per_meeting_cap"]

    def test_each_meeting_is_read_in_start_time_order(self, run):
        """group_rows_by_meeting sorts a meeting by begin time (since 7527331)."""
        begins: dict = {}
        for r in run.by_alpha[_ALPHAS[0]]:
            begins.setdefault(r["meeting"], []).append(int(r["uid"].split("_")[4]))
        for meeting, times in begins.items():
            assert times == sorted(times), meeting

    def test_the_run_record_names_the_preset_the_summary_records(self, run):
        text = run.record.read_text(encoding="utf-8")
        assert re.search(rf"^ANON_PRESET={re.escape(run.preset)}$", text, re.M)
        assert not re.search(r"^ANON_(LIMIT|ALPHAS|PER_MEETING)=", text, re.M)
        requested = run.summary["requested"]
        assert requested["limit"] == _PRESETS[run.preset]["limit"]
        assert requested["per_meeting"] == _PRESETS[run.preset]["per_meeting"]
        assert requested["alphas"] == [float(a) for a in _ALPHAS]
        assert requested["model"] == run.summary["asr_model"]


# ---------------------------------------------------------------------------
# The summary is what the benchmark's functions make of the report
# ---------------------------------------------------------------------------

_WER_FIELDS = ("wer_original", "wer_resynthesis_control", "wer_anonymised",
               "wer_cost", "wer_cost_baseline", "wer_baseline_name",
               "wer_cost_sign_anomaly", "n_degenerate_baselines",
               "degenerate_baseline_error_share", "wer_baseline_guarded",
               "wer_original_guarded", "wer_anonymised_guarded",
               "wer_cost_guarded", "wer_averaging")


class TestRepooled:
    def test_the_word_error_rates_re_pool_from_the_counts(self, run):
        for a in _ALPHAS:
            rows = run.by_alpha[a]
            got = ba.summarise([r["self_similarity"] for r in rows],
                               _arm(rows, "original"), _arm(rows, "anonymised"),
                               {}, results_control=_arm(rows, "control"))
            expected = run.summary["by_alpha"][a]
            for field in _WER_FIELDS:
                assert got[field] == expected[field], (a, field)
            # The report keeps six decimals of each similarity.
            assert got["mean_self_similarity"] == pytest.approx(
                expected["mean_self_similarity"], abs=1e-4)

    def test_the_loop_screen_column_is_the_screen(self, run):
        """EPRIV-16: one definition, written per utterance."""
        first = run.by_alpha[_ALPHAS[0]]
        screened = set(ba.degenerate_baselines(_arm(first, "control")))
        assert [r["degenerate_baseline"] for r in first] == \
            [int(i in screened) for i in range(len(first))]
        for a in _ALPHAS:
            assert [r["degenerate_baseline"] for r in run.by_alpha[a]] == \
                [r["degenerate_baseline"] for r in first]
        criterion = run.summary["degenerate_baseline_criterion"]
        assert criterion == ba.degenerate_baseline_criterion("resynthesis control")

    def test_the_control_transcribes_exactly_as_the_original(self, run):
        """The resynthesis control is the identity below the limiter knee."""
        for r in run.rows:
            assert r["errors_control"] == r["errors_original"]
            assert r["hypothesis_words_control"] == r["hypothesis_words_original"]

    def test_chance_and_trials_follow_from_the_labels(self, run):
        """EPRIV-04 and EPRIV-15: chance over each probe's own candidates.

        Chance, trials and exclusions depend on the labels only, so random
        embeddings reproduce them; only the linkage rate needs the real ones.
        """
        speakers, meetings, channels = _labels(run.by_alpha[_ALPHAS[0]])
        rng = np.random.default_rng(0)
        emb = list(rng.standard_normal((len(speakers), 8)))
        sets = ba.linkage_by_candidate_set(emb, emb, speakers, meetings, channels)
        assert set(sets) == set(ba.CANDIDATE_SETS) == \
            set(run.summary["linkage_candidate_sets"])
        keys = ("chance", "trials", "n_singleton_excluded", "distinct_speakers")
        for name, got in sets.items():
            expected = {k: got[k] for k in keys}
            assert {k: run.summary["linkage_ceiling"][name][k] for k in keys} == expected
            for a in _ALPHAS:
                per_alpha = run.summary["by_alpha"][a]["linkage_by_candidates"][name]
                assert {k: per_alpha[k] for k in keys} == expected, (a, name)
        for a in _ALPHAS:
            s = run.summary["by_alpha"][a]
            assert s["chance"] == sets["all"]["chance"]
            assert s["trials"] == sets["all"]["trials"]
            assert s["chance_within_meeting"] == sets["within_meeting"]["chance"]
            assert s["chance_cross_meeting"] == sets["cross_meeting"]["chance"]
            assert s["linkage_rate"] == \
                s["linkage_by_candidates"]["all"]["linkage_rate"]

    def test_the_channel_check_follows_from_the_labels(self, run):
        speakers, meetings, channels = _labels(run.by_alpha[_ALPHAS[0]])
        assert run.summary["speaker_channels"] == \
            ba.speaker_channel_check(speakers, meetings, channels)

    def test_the_level_checks_re_pool(self, run):
        """EPRIV-02: the level ratio and the knee count, per utterance."""
        for a in _ALPHAS:
            rows = run.by_alpha[a]
            s = run.summary["by_alpha"][a]
            # Each row keeps four decimals of its own ratio.
            assert s["level_ratio"] == pytest.approx(
                np.mean([r["level_ratio"] for r in rows]), abs=1e-4)
            assert s["n_knee_compressed_samples"] == sum(r["knee_samples"] for r in rows)
            assert s["level_matched"] is (0.8 <= s["level_ratio"] <= 1.25)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_the_code_and_models_are_recorded(self, run):
        s = run.summary
        assert s["git_commit"] == s["run_metadata"]["git_commit"] == _COMMIT
        assert s["run_metadata"]["git_dirty"] is False
        assert s["corpus"] == "edinburghcstr/ami/ihm/test"
        assert s["asr_model"] == ba.DEFAULT_ASR_MODEL
        # Loaded directly after the pipeline failed on a corrupted cache;
        # ARC job 8976304 found its embeddings bit-identical to the
        # pipeline's own (hpc/runs/anonymisation.env).
        assert s["embedding_model"] == _WESPEAKER
        assert s["revisions"] == {
            ba.DEFAULT_ASR_MODEL: revision_for(ba.DEFAULT_ASR_MODEL),
            _WESPEAKER: revision_for(_WESPEAKER),
            "edinburghcstr/ami": revision_for("edinburghcstr/ami")}
        assert s["revisions_not_enforced"] == [_WESPEAKER]


# ---------------------------------------------------------------------------
# Pinned figures
# ---------------------------------------------------------------------------

def _field(summary, field, candidates=None):
    if candidates is None:
        return [summary["by_alpha"][a][field] for a in _ALPHAS]
    return [summary["by_alpha"][a]["linkage_by_candidates"][candidates][field]
            for a in _ALPHAS]


@pytest.fixture(scope="module")
def multi():
    return _load("multi_meeting").summary


@pytest.fixture(scope="module")
def single():
    return _load("single_meeting").summary


class TestMultiMeetingPinned:
    """The main result (job 8917989), which the manuscript reads."""

    def test_the_sample(self, multi):
        assert (multi["n_utterances"], multi["n_meetings"],
                multi["n_speakers"]) == (400, 16, 14)
        assert set(multi["accepted_by_meeting"].values()) == {25}
        # Only the EN2002 speakers change headset channel between sessions,
        # so only their 100 probes have a cross-channel candidate.
        assert multi["speaker_channels"]["change_channel"] == [
            "FEO070", "FEO072", "MEE071", "MEE073"]

    def test_linkage_and_chance_in_every_candidate_set(self, multi):
        expected = {
            "all": ([0.1955, 0.5664, 0.787, 0.9173], 0.1411, 399, 0.9524),
            "within_meeting": ([0.6439, 0.8434, 0.9066, 0.9545], 0.6305, 396,
                               0.9596),
            "cross_meeting": ([0.1679, 0.5138, 0.7368, 0.8947], 0.1101, 399,
                              0.9373),
            "cross_meeting_cross_channel": ([0.12, 0.48, 0.57, 0.79], 0.0374, 100,
                                            0.87),
        }
        for name, (rates, chance, trials, ceiling) in expected.items():
            assert _field(multi, "linkage_rate", name) == rates, name
            assert set(_field(multi, "chance", name)) == {chance}, name
            assert set(_field(multi, "trials", name)) == {trials}, name
            assert multi["linkage_ceiling"][name]["linkage_rate"] == ceiling, name

    def test_linkage_rises_as_the_warping_weakens_in_every_set(self, multi):
        for name in ba.CANDIDATE_SETS:
            rates = _field(multi, "linkage_rate", name)
            assert rates == sorted(rates), name

    def test_the_intelligibility_cost(self, multi):
        assert _field(multi, "wer_cost_guarded") == [0.6745, 0.4328, 0.1953, 0.1498]
        assert set(_field(multi, "wer_baseline_guarded")) == {0.1765}
        assert set(_field(multi, "n_degenerate_baselines")) == {3}
        assert set(_field(multi, "degenerate_baseline_error_share")) == {0.475}
        assert _field(multi, "mean_self_similarity") == [0.0807, 0.2604, 0.4089,
                                                         0.6967]

    def test_the_level_is_matched(self, multi):
        assert _field(multi, "level_ratio") == [0.9975, 0.9984, 0.999, 0.9995]
        assert all(_field(multi, "level_matched"))


class TestSingleMeetingPinned:
    """The single-meeting comparison (job 8917988)."""

    def test_the_sample(self, single):
        assert (single["n_utterances"], single["n_meetings"],
                single["n_speakers"]) == (200, 1, 4)
        assert single["accepted_by_meeting"] == {"EN2002a": 200}

    def test_linkage_and_chance(self, single):
        assert _field(single, "linkage_rate") == [0.48, 0.755, 0.865, 0.92]
        assert set(_field(single, "chance")) == {0.2937}
        assert single["linkage_ceiling"]["all"]["linkage_rate"] == 0.935
        # One meeting: no probe has a candidate from another.
        assert set(_field(single, "trials", "cross_meeting")) == {0}

    def test_the_intelligibility_cost(self, single):
        # Not monotone: two utterances the baseline transcribed without
        # looping (word error rates 0.33 and 0.6) loop when warped at alpha
        # 0.9, and a warp-provoked loop counts.
        assert _field(single, "wer_cost_guarded") == [2.4086, 0.2788, 0.1757,
                                                      0.3355]
        assert set(_field(single, "wer_baseline_guarded")) == {0.1871}
        assert set(_field(single, "n_degenerate_baselines")) == {5}
        assert _field(single, "level_ratio") == [1.0, 1.0, 1.0, 1.0]
