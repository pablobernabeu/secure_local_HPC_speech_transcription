"""Unit tests for ``evaluation.footprint``.

The energy/carbon model is pure arithmetic, so these tests pin it down on a
hand-built job with round constants (no cluster access, no optional
dependency).  They check three things:

* ``parse_alloc_tres`` recovers CPU/GPU/memory counts from real SLURM
  ``AllocTRES`` strings, including the typed ``gres/gpu:a100`` form;
* ``estimate_job`` reproduces the Green-Algorithms operating-energy formula
  exactly for a one-GPU, one-hour job; and
* ``summarise`` splits productive (COMPLETED) from failed/cancelled jobs and
  conserves the headline totals.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.footprint import (  # noqa: E402
    FootprintParams,
    estimate_job,
    load_ledger,
    parse_alloc_tres,
    summarise,
    _mem_to_gb,
)

# Round constants so the expected energy is exact and easy to verify.
_PARAMS = FootprintParams(
    gpu_tdp_w={"a100": 400.0},
    cpu_power_w_per_core=10.0,
    mem_power_w_per_gb=0.5,
    pue=1.0,
    carbon_intensity_g_per_kwh=100.0,
    gpu_util=1.0,
    cpu_util=1.0,
    car_g_per_km=100.0,
)


def _row(job_id, name, state, elapsed_s, gpus, gpu_type, cpus, mem_gb):
    return {
        "job_id": job_id, "job_name": name, "state": state,
        "elapsed_s": str(elapsed_s), "gpus": str(gpus),
        "gpu_type": gpu_type, "cpus": str(cpus), "mem_gb": str(mem_gb),
    }


def test_parse_alloc_tres_generic_and_typed_gpu():
    generic = parse_alloc_tres("billing=4,cpu=4,gres/gpu=1,mem=32G,node=1")
    assert generic == {"cpus": 4, "mem_gb": 32.0, "gpus": 1, "gpu_type": None}

    typed = parse_alloc_tres("cpu=4,gres/gpu:a100=1,gres/gpu=1,mem=32G,node=1")
    assert typed["gpu_type"] == "a100"
    assert typed["gpus"] == 1
    assert typed["cpus"] == 4

    cpu_only = parse_alloc_tres("billing=2,cpu=2,mem=8G,node=1")
    assert cpu_only["gpus"] == 0
    assert cpu_only["gpu_type"] is None


def test_mem_to_gb_handles_suffixes():
    assert _mem_to_gb("32G") == pytest.approx(32.0)
    assert _mem_to_gb("62.50G") == pytest.approx(62.5)
    assert _mem_to_gb("512M") == pytest.approx(0.5)
    assert _mem_to_gb("") == 0.0


def test_estimate_job_matches_hand_computed_energy():
    # One hour on one A100: GPU 400 Wh + CPU 2*10 Wh + mem 10*0.5 Wh = 425 Wh.
    job = estimate_job(
        _row("1", "wer_sweep", "COMPLETED", 3600, 1, "a100", 2, 10),
        _PARAMS,
    )
    assert job.gpu_hours == pytest.approx(1.0)
    assert job.energy_kwh == pytest.approx(0.425)
    assert job.carbon_g == pytest.approx(42.5)
    assert job.productive is True


def test_cpu_only_job_has_no_gpu_energy():
    job = estimate_job(
        _row("2", "sweep_aggregate", "COMPLETED", 3600, 0, "", 2, 8),
        _PARAMS,
    )
    assert job.gpu_hours == 0.0
    assert job.energy_gpu_kwh == 0.0
    # CPU 2*10 Wh + mem 8*0.5 Wh = 24 Wh.
    assert job.energy_kwh == pytest.approx(0.024)


def test_summarise_splits_productive_from_overhead():
    done = estimate_job(
        _row("3", "wer_sweep", "COMPLETED", 3600, 1, "a100", 4, 32), _PARAMS)
    cancelled = estimate_job(
        _row("4", "wer_sweep", "CANCELLED", 3600, 1, "a100", 4, 32), _PARAMS)
    summary = summarise([done, cancelled], _PARAMS)

    assert summary["overall"]["n_jobs"] == 2
    assert summary["productive"]["n_jobs"] == 1
    assert summary["overhead"]["n_jobs"] == 1
    assert "CANCELLED" in summary["overhead"]["states"]
    # The two sub-totals must conserve the overall GPU-hours.
    assert (summary["productive"]["gpu_hours"]
            + summary["overhead"]["gpu_hours"]) == pytest.approx(
        summary["overall"]["gpu_hours"])


def test_committed_ledger_is_consistent():
    """The shipped ledger loads and its sub-totals conserve the whole.

    Costed with the parameters the committed summary records, so a
    refreshed ledger whose H100 jobs needed ``--gpu-tdp h100=W`` is read
    at the wattage that produced the summary.
    """
    import json

    ledger = PROJECT_ROOT / "output" / "evaluation" / "arc_job_ledger.csv"
    summary_path = ledger.with_name("footprint_summary.json")
    params = FootprintParams()
    if summary_path.exists():
        recorded = json.loads(summary_path.read_text(encoding="utf-8"))
        params = FootprintParams(**recorded["parameters"])
    rows = load_ledger(ledger)
    assert rows, "committed ledger should not be empty"
    jobs = [estimate_job(r, params) for r in rows]
    summary = summarise(jobs, params)

    assert summary["overall"]["n_jobs"] == len(rows)
    assert (summary["productive"]["n_jobs"]
            + summary["overhead"]["n_jobs"]) == len(rows)
    assert (summary["productive"]["gpu_hours"]
            + summary["overhead"]["gpu_hours"]) == pytest.approx(
        summary["overall"]["gpu_hours"])
    # Sanity: the programme used a non-trivial but modest amount of GPU time.
    assert 10.0 < summary["overall"]["gpu_hours"] < 500.0


def test_the_committed_summary_follows_from_the_committed_ledger():
    """Every total and category of the committed summary is what the code
    makes of the committed ledger under the parameters the summary records.

    A change that would move a committed footprint figure or rename a
    category of the committed jobs fails here, and so does a ledger
    re-captured without regenerating the summary from it.
    """
    import json

    ledger = PROJECT_ROOT / "output" / "evaluation" / "arc_job_ledger.csv"
    recorded = json.loads(ledger.with_name("footprint_summary.json")
                          .read_text(encoding="utf-8"))
    params = FootprintParams(**recorded["parameters"])
    again = summarise([estimate_job(r, params) for r in load_ledger(ledger)],
                      params)
    for block in ("overall", "productive", "overhead", "by_category",
                  "equivalence"):
        assert again[block] == recorded[block], block
