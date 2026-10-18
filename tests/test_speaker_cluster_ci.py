"""The reader bootstrap must preserve the utterance estimand and pairing."""

import csv
import json

import numpy as np
import pytest

from evaluation.speaker_cluster_ci import (
    cluster_interval, main, paired_cluster_interval, read_librispeech_report,
)


def test_unequal_cluster_sizes_preserve_utterance_weighting():
    # One reader supplies one perfect utterance, the other nine all-wrong
    # utterances. The macro estimand is .9, not the .5 reader-mean estimand.
    names = ["1-1-0", *[f"2-1-{n}" for n in range(9)]]
    result = cluster_interval(names, [0, *[1] * 9], bootstrap=10000)
    assert result["estimate"] == pytest.approx(0.9)
    assert result["ci_lo"] == 0
    assert result["ci_hi"] == 1
    assert result["n_readers"] == 2


def test_chapters_of_one_reader_are_one_cluster_and_order_is_irrelevant():
    names = ["1-7-0", "1-9-1", "2-8-0", "3-2-0"]
    values = [0.2, 0.4, 0.7, 1.5]
    result = cluster_interval(names, values, bootstrap=2200, seed=7)
    assert result["n_readers"] == 3
    assert result == cluster_interval(names[::-1], values[::-1], 2200, 7)


def test_matches_explicit_whole_reader_resampling():
    names = ["1-1-0", "2-1-0", "3-1-0", "4-1-0", "4-1-1"]
    values = [0, 0.2, 0.6, 1, 1]
    draw = np.random.default_rng(4).integers(0, 4, (1700, 4))
    readers = [[0], [0.2], [0.6], [1, 1]]
    # Independently concatenate all utterances from each sampled reader.
    # Four clusters keep the bounds away from the extrema: averaging
    # reader means inside replicates would give an upper bound of .8.
    means = [np.mean([v for r in sample for v in readers[r]]) for sample in draw]
    result = cluster_interval(names, values, 1700, 4)
    assert [result["ci_lo"], result["ci_hi"]] == pytest.approx(
        np.quantile(means, [0.025, 0.975]))
    assert result["estimate"] == pytest.approx(0.56)
    assert result["ci_hi"] == pytest.approx(0.8857142857142858)


def test_paired_uniform_shift_is_exact_despite_baseline_dispersion():
    baseline = {"1-1-0": 0.01, "2-1-0": 0.1, "2-1-1": 3}
    condition = {name: value + 0.25 for name, value in reversed(list(baseline.items()))}
    result = paired_cluster_interval(condition, baseline, 1500)
    assert [result[k] for k in ["estimate", "ci_lo", "ci_hi"]] == pytest.approx([0.25] * 3)
    with pytest.raises(ValueError, match="exactly the same"):
        paired_cluster_interval({"1-1-0": 0}, baseline)


@pytest.mark.parametrize("names,values", [
    (["AMI_a_0", "2-1-0"], [0, 1]),
    (["1-1-0", "1-1-0"], [0, 1]),
    (["1-1-0", "1-2-0"], [0, 1]),
    (["1-1-0", "2-1-0"], [0, float("nan")]),
    (["1-1-0", "2-1-0"], [0]),
])
def test_refuses_invalid_or_unidentifiable_sampling_units(names, values):
    with pytest.raises(ValueError):
        cluster_interval(names, values)


def _report(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "wer"])
        writer.writerows(rows)


@pytest.mark.parametrize("rows", [
    [("1-1-0", 0), ("1-1-0", 1)],
    [("1-1-0", ""), ("2-1-0", 0)],
    [("1-1-0", "inf"), ("2-1-0", 0)],
    [("1-1-0", -0.1), ("2-1-0", 0)],
])
def test_loading_never_silently_drops_rows(tmp_path, rows):
    path = tmp_path / "bad.csv"
    _report(path, rows)
    with pytest.raises(ValueError):
        read_librispeech_report(path)


def test_cli_provenance_and_input_preservation(tmp_path):
    raw, post, output = [tmp_path / name for name in ["raw.csv", "post.csv", "ci.json"]]
    _report(raw, [("1-1-0", 0), ("2-1-0", 1.5)])
    _report(post, [("2-1-0", 1.6), ("1-1-0", 0.1)])
    original = raw.read_bytes(), post.read_bytes()
    assert main(["--report", str(raw), "--baseline", str(raw), "--condition", str(post),
                 "--bootstrap", "1200", "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["macro_wer"]["n_readers"] == 2
    assert len(result["macro_wer"]["source"]["sha256"]) == 64
    assert result["paired_deltas"][0]["estimate"] == pytest.approx(0.1)
    assert original == (raw.read_bytes(), post.read_bytes())
    with pytest.raises(SystemExit):
        main(["--report", str(raw), "--output", str(raw)])
    assert original == (raw.read_bytes(), post.read_bytes())


def test_cli_hash_and_results_survive_checkout_line_endings(tmp_path):
    raw, output = tmp_path / "raw.csv", tmp_path / "ci.json"
    raw.write_bytes(b"name,wer\n1-1-0,0\n2-1-0,0.5\n")
    args = ["--report", str(raw), "--bootstrap", "1200", "--output", str(output)]
    main(args)
    first = output.read_bytes()
    raw.write_bytes(raw.read_bytes().replace(b"\n", b"\r\n"))
    main(args)
    assert first == output.read_bytes()


@pytest.mark.parametrize("bootstrap", [True, 0, -1, 1.5])
def test_rejects_unusable_bootstrap_settings(bootstrap):
    with pytest.raises(ValueError, match="positive integer"):
        cluster_interval(["1-1-0", "2-1-0"], [0, 0.5], bootstrap=bootstrap)
