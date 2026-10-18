"""Audit fixes for the statistics helpers: loud failures on bad input.

Covers evaluation.bootstrap_ci (repeated names, non-finite WER),
evaluation.condition_ci (establishing which condition the unsuffixed
primary report holds), evaluation.determinism (malformed dumps, repeated
uids, colliding labels) and evaluation.footprint (unmapped GPU models).
Hermetic: tmp_path only, no network, fixed seeds.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from evaluation import bootstrap_ci, condition_ci, determinism, footprint  # noqa: E402


def _report(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "wer"])
        w.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# bootstrap_ci
# ---------------------------------------------------------------------------

class TestBootstrapInputs:
    def test_repeated_names_are_refused(self):
        with pytest.raises(ValueError, match="repeats"):
            bootstrap_ci.align_reports(
                ["a", "a", "b"], [0.1, 0.2, 0.3], ["a", "b"], [0.1, 0.2])

    def test_non_finite_wer_is_refused(self, tmp_path):
        p = _report(tmp_path / "r.csv", [("a", "0.1"), ("b", "nan")])
        with pytest.raises(ValueError, match="non-finite"):
            bootstrap_ci.read_wer_report(p)

    def test_skipped_rows_are_counted_on_stderr(self, tmp_path, capsys):
        p = _report(tmp_path / "r.csv", [("a", "0.1"), ("b", ""), ("c", "x")])
        names, _ = bootstrap_ci.read_wer_report(p)
        assert names == ["a"]
        assert "skipped 2 row(s)" in capsys.readouterr().err

    def test_written_columns_do_not_depend_on_field_positions(self, tmp_path):
        out = tmp_path / "ci.csv"
        bootstrap_ci.write_ci_csv(
            [{"file": "f", "n": 3, "macro_wer": 0.1, "ci_lo": 0.0,
              "ci_hi": 0.2}], out, b=10, seed=1)
        with open(out, encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row == {"file": "f", "n": "3", "macro_wer": "0.1",
                       "ci_lo": "0.0", "ci_hi": "0.2", "bootstrap": "10",
                       "seed": "1"}


# ---------------------------------------------------------------------------
# condition_ci: identity of the primary report
# ---------------------------------------------------------------------------

_BASE = [(f"u{i:02d}", 0.1) for i in range(20)]


def _cell(tmp_path: Path, primary_wer: float, named: dict) -> Path:
    d = tmp_path / "cell"
    _report(d / "wer_report.csv", [(n, primary_wer) for n, _ in _BASE])
    for cond, w in named.items():
        _report(d / f"wer_report_{cond}.csv", [(n, w) for n, _ in _BASE])
    return d


class TestPrimaryIdentity:
    def test_primary_is_kept_under_its_name_when_baseline_has_a_file(
            self, tmp_path):
        """--conditions pipeline_full,raw,... once dropped pipeline_full."""
        d = _cell(tmp_path, 0.5, {"raw": 0.1, "whisper_norm": 0.05})
        rows = condition_ci.compare_all(d, baseline="raw", b=50,
                                        primary_condition="pipeline_full")
        by = {r["condition"]: r for r in rows}
        assert set(by) == {"pipeline_full", "whisper_norm"}
        assert by["pipeline_full"]["delta"] == pytest.approx(0.4)

    def test_unknown_primary_with_a_baseline_file_is_refused(self, tmp_path):
        d = _cell(tmp_path, 0.5, {"raw": 0.1, "whisper_norm": 0.05})
        with pytest.raises(ValueError, match="primary-condition"):
            condition_ci.compare_all(d, baseline="raw", b=50)

    def test_sibling_summary_names_the_primary(self, tmp_path):
        d = _cell(tmp_path, 0.5, {"raw": 0.1})
        (d / "wer_summary.json").write_text(json.dumps(
            {"benchmark": {"condition": "pipeline_full"}}), encoding="utf-8")
        rows = condition_ci.compare_all(d, baseline="raw", b=50)
        assert [r["condition"] for r in rows] == ["pipeline_full"]

    def test_a_mistyped_baseline_is_not_pinned_on_the_primary(self, tmp_path):
        d = _cell(tmp_path, 0.5, {"whisper_norm": 0.05})
        with pytest.raises(ValueError, match="not a registered condition"):
            condition_ci.compare_all(d, baseline="Raw", b=50)

    def test_the_committed_layout_still_assumes_raw(self, tmp_path, capsys):
        d = _cell(tmp_path, 0.1, {"whisper_norm": 0.05})
        rows = condition_ci.compare_all(d, baseline="raw", b=50)
        assert [r["condition"] for r in rows] == ["whisper_norm"]
        assert rows[0]["macro_baseline"] == pytest.approx(0.1)
        assert "assuming wer_report.csv holds 'raw'" in capsys.readouterr().err

    def test_a_baseline_file_is_never_compared_with_itself(self, tmp_path):
        d = _cell(tmp_path, 0.5, {"raw": 0.1, "whisper_norm": 0.05})
        rows = condition_ci.compare_all(
            d, baseline="raw", baseline_file=d / "wer_report_raw.csv", b=50,
            primary_condition="pipeline_full")
        assert {r["condition"] for r in rows} == {"pipeline_full",
                                                  "whisper_norm"}

    def test_primary_name_clashing_with_a_named_file_is_refused(self, tmp_path):
        d = _cell(tmp_path, 0.5, {"whisper_norm": 0.05})
        with pytest.raises(ValueError, match="also exists"):
            condition_ci.compare_all(d, baseline="raw", b=50,
                                     primary_condition="whisper_norm")

    def test_no_shared_utterances_aborts(self, tmp_path):
        d = tmp_path / "cell"
        _report(d / "wer_report.csv", [("a", 0.1)])
        _report(d / "wer_report_whisper_norm.csv", [("b", 0.1)])
        with pytest.raises(ValueError, match="share no utterance"):
            condition_ci.compare_all(d, baseline="raw", b=50)


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------

def _dump(path: Path, rows, fields=("uid", "condition", "hypothesis_raw")):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fields))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


class TestDeterminismInputs:
    def test_missing_hypothesis_column_is_refused(self, tmp_path):
        p = _dump(tmp_path / "a.csv", [{"uid": "u1", "condition": "raw"}],
                  fields=("uid", "condition"))
        with pytest.raises(ValueError, match="hypothesis_raw"):
            determinism.read_hypotheses(p, "raw")

    def test_repeated_uid_is_refused(self, tmp_path):
        rows = [{"uid": "u1", "condition": "raw", "hypothesis_raw": "a"},
                {"uid": "u1", "condition": "raw", "hypothesis_raw": "b"}]
        with pytest.raises(ValueError, match="more than once"):
            determinism.read_hypotheses(_dump(tmp_path / "a.csv", rows))

    def test_colliding_stems_are_refused(self, tmp_path):
        row = [{"uid": "u1", "condition": "raw", "hypothesis_raw": "a"}]
        a = _dump(tmp_path / "a100" / "seed0_run1.csv", row)
        b = _dump(tmp_path / "h100" / "seed0_run1.csv", row)
        with pytest.raises(ValueError, match="share the label"):
            determinism.compare_files([a, b])

    def test_nothing_compared_exits_non_zero_without_json(self, tmp_path):
        row = [{"uid": "u1", "condition": "raw", "hypothesis_raw": "a"}]
        a = _dump(tmp_path / "s0.csv", row)
        b = _dump(tmp_path / "s1.csv", row)
        out = tmp_path / "out.json"
        code = determinism.main([str(a), str(b), "--condition", "absent",
                                 "--json", str(out)])
        assert code == 1
        assert not out.exists()

    def test_malformed_dump_exits_2(self, tmp_path):
        a = _dump(tmp_path / "s0.csv", [{"uid": "u1", "condition": "raw"}],
                  fields=("uid", "condition"))
        b = _dump(tmp_path / "s1.csv", [{"uid": "u1", "condition": "raw"}],
                  fields=("uid", "condition"))
        assert determinism.main([str(a), str(b)]) == 2


# ---------------------------------------------------------------------------
# footprint
# ---------------------------------------------------------------------------

def _job(gpu_type, gpus=1):
    return {"job_id": "1", "job_name": "wer_sweep", "state": "COMPLETED",
            "elapsed_s": "3600", "gpus": str(gpus), "gpu_type": gpu_type,
            "cpus": "4", "mem_gb": "32"}


class TestFootprintGpuTypes:
    def test_an_unmapped_gpu_type_is_refused(self):
        # A bare "h100" is unresolved: the variant (PCIe 350 W, NVL 400 W,
        # SXM5 700 W) decides the wattage, so it must be supplied, never guessed.
        with pytest.raises(ValueError, match="h100"):
            footprint.estimate_job(_job("h100"), footprint.FootprintParams())

    def test_a_cpu_only_job_needs_no_gpu_type(self):
        job = footprint.estimate_job(_job("", gpus=0),
                                     footprint.FootprintParams())
        assert job.energy_gpu_kwh == 0.0

    def test_mapped_types_are_priced_as_before(self):
        job = footprint.estimate_job(_job("a100"), footprint.FootprintParams())
        # 1 h x 400 W x PUE 1.67 = 0.668 kWh
        assert job.energy_gpu_kwh == pytest.approx(0.668)

    def test_cli_refuses_an_unmapped_ledger_and_accepts_an_override(
            self, tmp_path):
        ledger = tmp_path / "ledger.csv"
        with open(ledger, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(_job("h100")))
            w.writeheader()
            w.writerow(_job("h100"))
        out = tmp_path / "out"
        assert footprint.main(["--ledger", str(ledger),
                               "--output-dir", str(out)]) == 2
        assert not (out / "footprint_summary.json").exists()
        assert footprint.main(["--ledger", str(ledger), "--output-dir",
                               str(out), "--gpu-tdp", "h100=250"]) == 0
        summary = json.loads((out / "footprint_summary.json").read_text(
            encoding="utf-8"))
        assert summary["parameters"]["gpu_tdp_w"]["h100"] == 250.0

    @pytest.mark.parametrize("value", ["p100", "=250", "p100=abc"])
    def test_malformed_gpu_tdp_is_refused(self, tmp_path, capsys, value):
        # A valid ledger, so that only the --gpu-tdp check can end the run:
        # a missing ledger also returns 2, and once masked a regression here.
        ledger = tmp_path / "ledger.csv"
        with open(ledger, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(_job("", gpus=0)))
            w.writeheader()
            w.writerow(_job("", gpus=0))
        out = tmp_path / "out"
        assert footprint.main(["--ledger", str(ledger), "--output-dir",
                               str(out)]) == 0
        (out / "footprint_summary.json").unlink()
        assert footprint.main(["--ledger", str(ledger), "--output-dir",
                               str(out), "--gpu-tdp", value]) == 2
        assert "--gpu-tdp expects MODEL=W" in capsys.readouterr().err
        assert not (out / "footprint_summary.json").exists()
