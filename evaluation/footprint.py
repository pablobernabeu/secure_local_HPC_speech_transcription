#!/usr/bin/env python3
"""
Estimate the energy and carbon footprint of the experimental programme.

Every benchmark in this paper ran as a SLURM job on the Oxford ARC ``htc``
cluster.  The scheduler's accounting database records the wall-clock
runtime and the allocated resources (GPU count and model, CPU cores,
memory) of each job, but the site does not run an energy-accounting plugin:
``sacct``'s ``ConsumedEnergy`` field is zero for every job.  This module
therefore *estimates* the footprint from the recorded runtimes and
allocations using the transparent, fully parameterised model of the Green
Algorithms project (Lannelongue, Grealey & Inouye, 2021,
*Advanced Science* 8:2100707).

For each job the operating energy is

    E_device = runtime_h * ( n_gpu * P_gpu * u_gpu
                           + n_cores * P_core * u_cpu
                           + mem_GB * P_mem )

and the drawn energy after data-centre overhead is ``E = E_device * PUE``.
The associated emissions are ``C = E * carbon_intensity``.  The utilisation
factors ``u_gpu`` and ``u_cpu`` default to 1.0. The
assumed GPU and CPU power is sustained for the whole allocation. The
resulting figures are model estimates: onsite power, PUE and carbon
intensity were not measured, so a total upper bound is not established.

All physical constants are parameters with documented defaults (see
:class:`FootprintParams`), so a reader who knows the site's true PUE, the
GPU board variant, or a different grid-intensity figure can substitute it
and re-run.  The command line exposes PUE, grid intensity, GPU
utilisation, per-model GPU board power and per-core CPU power; the
remaining constants (CPU utilisation, memory power, the car-emission
factor) are substituted by constructing :class:`FootprintParams` in
Python and passing it to :func:`estimate_job` and :func:`summarise`.
A GPU job whose model has no board-power entry is refused, not costed
at 0 W.  The input is a committed snapshot of the scheduler ledger
(``output/evaluation/arc_job_ledger.csv``), so the estimate is reproducible
offline without any cluster access.

Building the ledger
-------------------
``--from-sacct RAW.psv`` turns a raw ``sacct -P`` dump into that ledger
(ESTATS-13): it keeps this project's jobs, parses ``AllocTRES`` with
:func:`parse_alloc_tres`, takes the runtime from ``ElapsedRaw`` and the
GPU model from the job's node (``NodeList``, through :data:`ARC_NODE_GPU`
and the boards in :data:`NODE_GPU_VARIANT`), because ``AllocTRES`` on ARC
names no GPU type unless the job asked for one, and then only its GRES
label, which covers boards of different power. It writes the ledger and a
``*_provenance.json`` beside it, which the estimate then carries into its
summary. The dump needs the columns
``JobID|JobName|State|ElapsedRaw|End|AllocTRES|NodeList``, and
``WorkDir`` for the checks below; the query::

    sacct -M htc --starttime 2026-05-16 --endtime now -X -P \\
        --format=JobID,JobName,Account,State,ElapsedRaw,Start,End,Partition,AllocTRES,NodeList,WorkDir

The window opens on the day of the evaluation's first job, a test-suite
run from this project's clone (7662519, 2026-05-16), the day the WER
benchmark was added (62198b2). Its first runs followed until 2026-05-19,
before the pilot, and the window of the ledger captured in June, which
opened on 2026-05-20, missed them. Earlier jobs belong to the workflow
and not to its evaluation: its set-up, development and transcription
jobs ran from ``~/speech_transcription`` between August 2025 and January
2026, on htc and on the ``arc`` cluster, which has run no job of the
evaluation (both checked in the scheduler's records on 2026-10-04).

Which jobs the ledger counts (OUTPUTS-05):

* This project's jobs, since the ARC account is shared with unrelated
  projects. A job is recognised by its name: a name in :data:`_CATEGORY`,
  or a name of the audit's re-run wave, ``au_<stage>`` or ``pf_<stage>``,
  whose stage :data:`_STAGE_CATEGORY` knows (:func:`job_category`). With
  ``WorkDir`` in the dump, the job must also have run from one of this
  project's directories (:data:`_PROJECT_DIR`), unless its name is one of
  the few documented to have run elsewhere (:data:`_RUN_ELSEWHERE`). A job
  of a recognised name that ran from any other directory may be another
  project's, since names such as ``pytest_suite`` or ``au_wer`` are
  generic; it is left out and listed in the provenance
  (:func:`left_out_elsewhere`). A finished job that ran from one of this
  project's directories under a name no rule knows stops the build, so a
  new name cannot drop out of the ledger unnoticed. Without ``WorkDir``
  the name alone decides.
* Every such job that finished after holding an allocation, whatever its
  state. Failed, cancelled and timed-out jobs drew power while they ran
  and are reported as overhead beside the completed ones. A job cancelled
  while pending (no ``AllocTRES``, zero ``ElapsedRaw``) drew none and is
  left out, as are jobs still pending or running. The provenance lists
  each job of this project left out, by ID under the reason
  (:func:`left_out_never_allocated`, :func:`left_out_unfinished`,
  :func:`left_out_elsewhere`); a job under a name no rule knows counts as
  this project's there when it ran from one of its directories.
* Pre-flights, probes, diagnostics and test-suite runs, which also ran on
  the cluster, under categories of their own, so that the breakdown keeps
  them apart from the runs that produced results.

The committed ledger was captured with the query above on 2026-10-04 at
13:45 BST, after every job of the evaluation had finished, the last to
end (8978760) at 11:38. It holds 197 jobs, 7662519 (2026-05-16) to
8983112 (2026-10-04), and its provenance holds the query, the dump's
SHA-256 and the seven jobs of this project left out, all cancelled while
pending. The dump is not committed, since it lists the shared account's
other projects.

It replaced a 38-job ledger captured on 2026-06-27 (06f2fa7), which
recorded ``a100`` for every GPU job. The nodes those jobs ran on are P100,
V100 and H100 nodes (sacct NodeList against the 2026-09-26 node listing),
so that label was wrong. From a dump whose window opens on 2026-05-20,
as that ledger's query did, ``--until 2026-06-27 --assume-gpu-type a100``
rebuilds it byte for byte; from a dump of the committed ledger's window,
which opens on 2026-05-16, the same options give its 38 jobs and the 18
of 16 to 19 May (both checked on 2026-10-04). The two options serve that
comparison and not a refresh. The label most likely came from the
batch-step rows that sacct adds without ``-X``: on ARC their AllocTRES
reads ``gres/gpu:a100`` for every job that asked for an untyped GPU,
whatever card it got (checked on 2026-10-04 for jobs on P100, RTX 8000,
A100, H100 and L40S nodes), so the step rows say nothing about the card.
With ``-X`` sacct gives one row per job, its allocation, and no step
rows.

Usage::

    python -m evaluation.footprint
    python -m evaluation.footprint --pue 1.4 --carbon-intensity 162
    python -m evaluation.footprint --ledger output/evaluation/arc_job_ledger.csv
    python -m evaluation.footprint --from-sacct sacct_dump.psv \\
        --captured 2026-10-04 --ledger output/evaluation/arc_job_ledger.csv
    python -m evaluation.footprint --gpu-tdp h100=700

Outputs
-------
``output/evaluation/footprint_report.csv``
    One row per job: identifiers, the GPU model and the board power it
    was costed at, runtime, GPU-hours, total energy, and emissions.

``output/evaluation/footprint_summary.json``
    Machine-readable totals consumed by the Quarto manuscript: the
    parameters used, programme-wide GPU-hours / energy / emissions, the
    split between productive (COMPLETED) and failed/cancelled jobs, a
    breakdown by experiment category, and a car-travel equivalence.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_DEFAULT_LEDGER = Path("output/evaluation/arc_job_ledger.csv")
_DEFAULT_OUTPUT_DIR = Path("output/evaluation")

# Provenance of the 38-job ledger captured on 2026-06-27 and committed in
# 06f2fa7, which had no *_provenance.json beside it; the capture of
# 2026-10-04 replaced it. main() gives this record to the summary of any
# ledger without such a file, so it is right only for that ledger (git
# show 06f2fa7:output/evaluation/arc_job_ledger.csv); a ledger built by
# --from-sacct has its own. The cluster does not gather energy
# accounting, so ``ConsumedEnergy`` is zero for every job and the figures
# below are model estimates, not meter readings.
PROVENANCE: dict[str, object] = {
    "cluster": "htc",
    "login_node": "arc-login02",
    "captured": "2026-06-27",
    "sacct_query": (
        "sacct -M htc --starttime 2026-05-20 --endtime now -X -P "
        "--format=JobID,JobName,State,ElapsedRaw,Partition,AllocTRES"
    ),
    # Corrected (ESTATS-13): the recorded query has -X, which returns the
    # allocation rows only, and on ARC their AllocTRES reads gres/gpu=1
    # with no model. How "a100" was assigned was not recorded, and the
    # NodeList of the same jobs in a 2026-09-26 dump names P100, V100 and
    # H100 nodes. The batch-step rows of the same jobs read gres/gpu:a100
    # whatever the node (see the module docstring), the likely source.
    "gpu_model_source": (
        "not recorded: the ledger gives a100 for every GPU job, but the "
        "query's AllocTRES carries no GPU model and the jobs' NodeList "
        "names P100, V100 and H100 nodes"),
    "measured_energy_available": False,
    "note": (
        "sacct ConsumedEnergy is 0 for every job (no site energy-accounting "
        "plugin); figures are Green-Algorithms model estimates."
    ),
}

# Board power (W) by GPU model, the maximum each manufacturer data sheet
# gives. Where the ledger names only a family whose boards differ, the
# largest is used for that family's assumed GPU power.
#   a100      NVIDIA A100 data sheet: SXM4 400 W; the PCIe 40 GB card
#             250 W and the 80 GB 300 W. The site does not publish which.
#   p100      NVIDIA Tesla P100 data sheet (Oct 2016): SXM2 300 W; the
#             PCIe card 250 W (Tesla P100 PCIe data sheet, Oct 2016).
#   v100      NVIDIA Tesla V100 data sheet (Mar 2018): SXM2 300 W, PCIe
#             250 W.
#   rtx8000   NVIDIA Quadro RTX 8000 data sheet (Mar 2019): total board
#             power 295 W; the passive card 250 W (PNY data sheet, Dec 2019).
#   rtx-titan NVIDIA TITAN RTX data sheet (2019, document
#             titan-rtx-for-creators-us-nvidia-1011126-r6): power
#             consumption 280 W.
#   a6000     NVIDIA RTX A6000 data sheet (May 2022): total board power
#             300 W.
#   l40s      NVIDIA L40S product page: maximum power consumption 350 W.
#   h100-nvl  NVIDIA H100 NVL product brief PB-11773-001_v01 (Mar 2024),
#             Table 1: 400 W maximum (default).
#   h100-pcie NVIDIA H100 PCIe product brief PB-11133-001_v02 (Nov 2022):
#             350 W maximum.
#   h100-sxm  NVIDIA H100 Tensor Core GPU data sheet (SXM5 form factor):
#             up to 700 W maximum thermal design power.
# A bare "h100" has no entry on purpose: ARC labels every H100 node
# "h100", and the family runs from the 350 W PCIe card to the 700 W SXM5
# module, so an upper bound would double the cost of a PCIe or NVL card.
# A ledger that records "h100" needs --gpu-tdp h100=W.
GPU_TDP_W: dict[str, float] = {
    "a100": 400.0,
    "a100-sxm4": 400.0,
    "a100-pcie": 250.0,   # A100 40 GB PCIe; the 80 GB PCIe card is 300 W
    "p100": 300.0,
    "p100-pcie": 250.0,
    "v100": 300.0,
    "v100-pcie": 250.0,
    "v100-sxm2": 300.0,
    "rtx8000": 295.0,
    "rtx-titan": 280.0,
    "a6000": 300.0,
    "l40s": 350.0,
    "h100-nvl": 400.0,
    "h100-pcie": 350.0,
    "h100-sxm": 700.0,
}

#: GPU model of each ARC htc GPU node: the GRES label in the node listing
#: ``sinfo -M htc -N -o "%N %G"`` of 2026-10-04 (``gpu:<label>:<n>``, the
#: same label ``scontrol show node`` gives as Gres). Used to give a job its
#: GPU model from its NodeList; ``--nodes`` replaces it with a fresher
#: listing. The listing adds 19 nodes to the 2026-09-26 one this map held
#: before and changes none; two audit jobs ran on nodes that one lacked
#: (htc-g015 and htc-g066). Every GPU node of the ``short`` partition, where
#: this project's jobs run, is here, so a job placed anywhere there has a
#: model.
ARC_NODE_GPU: dict[str, str] = {
    **{f"htc-g{n:03d}": "v100" for n in (3, 4, 35, 37, 38, 47, 48, 49)},
    **{f"htc-g{n:03d}": "rtx8000" for n in range(9, 15)},
    **{f"htc-g{n:03d}": "a100" for n in range(15, 19)},
    **{f"htc-g{n:03d}": "p100" for n in (32, 33, 34)},
    **{f"htc-g{n:03d}": "rtx" for n in (41, 42, 43)},
    **{f"htc-g{n:03d}": "a6000" for n in (50, 51, 52)},
    **{f"htc-g{n:03d}": "h100" for n in (53, 54, 55, 58, 59, 60)},
    **{f"htc-g{n:03d}": "l40s" for n in range(61, 85)},
}

#: Board of each node whose GRES label covers boards of different power,
#: where a record names the board. Each variant is named
#: ``<GRES label>-<board>``, so :func:`_gres_label` reads back the label it
#: refines, and a listing or a typed allocation that contradicts it is
#: refused. A node with no such record keeps its label, priced at the
#: family's largest board (:data:`GPU_TDP_W`).
#:
#: The records are the card that nvidia-smi names in each job's log, and
#: since hpc/common/arc_common.sh in its environment record, joined to the
#: node through sacct NodeList (read 2026-10-04); every log on a node names
#: the same card:
#:
#: * htc-g003, g004: "Tesla V100-PCIE-32GB" (eight logs each, e.g. 8688725_0
#:   on g003 and 8679910_4 on g004). htc-g035: "Tesla V100-PCIE-16GB"
#:   (8174224_1).
#: * htc-g037, g038: "Tesla V100-SXM2-32GB" (7741099, 7819552).
#: * htc-g032 to g034: "Tesla P100-PCIE-16GB" (7742188, 7737895, 7746222;
#:   also 7737896 on g032 and 7746221 on g033, the jobs ESTATS-13 asked
#:   about, whose batch-step rows read gres/gpu:a100).
#: * htc-g015, g016: "NVIDIA A100-PCIE-40GB" (8917984_1, 8556730).
#: * htc-g053 to g055: "NVIDIA H100 PCIe" (8400084, 8556620, 7746139).
#: * htc-g058: "NVIDIA H100 NVL" (8556661; also
#:   output/evaluation/determinism/gpu.txt, written by 8554985).
#: * htc-g059, g060: "NVIDIA H100 80GB HBM3", the SXM5 module's name
#:   (7741154, 7746140).
#:
#: htc-g041 to g043, labelled "rtx", have run no job of this project; their
#: ``scontrol show node`` features name the card (gpu_gen Titan, gpu_sku
#: RTX, 24 GB), and the TITAN RTX has one board. The identification is
#: provisional until a log names the card: the same features give gpu_cc
#: 10.0, which is not the TITAN RTX's compute capability (7.5, Turing),
#: whereas on each of the other 53 GPU nodes that list gpu_cc it is the
#: card's (6.0 on P100, 7.0 on V100, 7.5 on RTX 8000, 8.0 on A100, 8.6 on
#: A6000, 8.9 on L40S, 9.0 on H100; read 2026-10-04). The GRES label and
#: the other features agree on the TITAN RTX, so the 10.0 is taken as the
#: error. Features are not used to tell boards of one family apart:
#: htc-g037 and g038 run SXM2 cards but list no nvlink feature, so htc-g017
#: and g018, which match htc-g015 in every feature, stay "a100" until a log
#: names their card.
NODE_GPU_VARIANT: dict[str, str] = {
    "htc-g003": "v100-pcie", "htc-g004": "v100-pcie", "htc-g035": "v100-pcie",
    "htc-g037": "v100-sxm2", "htc-g038": "v100-sxm2",
    "htc-g032": "p100-pcie", "htc-g033": "p100-pcie", "htc-g034": "p100-pcie",
    "htc-g015": "a100-pcie", "htc-g016": "a100-pcie",
    "htc-g041": "rtx-titan", "htc-g042": "rtx-titan", "htc-g043": "rtx-titan",
    "htc-g053": "h100-pcie", "htc-g054": "h100-pcie", "htc-g055": "h100-pcie",
    "htc-g058": "h100-nvl",
    "htc-g059": "h100-sxm", "htc-g060": "h100-sxm",
}

# Productive jobs are those that ran to completion; FAILED and CANCELLED
# jobs still drew power and are reported separately as overhead.
_PRODUCTIVE_STATE = "COMPLETED"

# States of a job that has not finished. Its ElapsedRaw is zero or still
# growing, so it has no place in a ledger yet.
_UNFINISHED_STATES = frozenset({"PENDING", "RUNNING", "REQUEUED", "SUSPENDED",
                                "RESIZING"})

#: Category of each of this project's job names, for the breakdown in the
#: summary. The names are also how --from-sacct recognises this project's
#: jobs, since the ARC account is shared with unrelated projects; the names
#: of the audit's re-run wave are recognised by rule instead
#: (:func:`job_category`). A category names the experiment a job served;
#: runs that produce no result by design (pre-flights, probes, diagnostics
#: and tests) have categories of their own, so the breakdown keeps them
#: apart. The condition sweep alone is split by pass: it was run in full
#: three times, each pass superseding the last, and those passes are the
#: largest items in the ledger. Every other experiment is one category
#: across its passes, which the job names in footprint_report.csv tell
#: apart.
#:
#: Jobs of the account examined and left out (the 2026-10-04 dumps, with
#: WorkDir and job scripts read on ARC): render, docchecks, checkdocs and
#: one wrap job rendered and checked another project's Quarto manuscript in
#: September 2026, and a one-minute cat job of 2026-09-03, submitted from
#: the home directory, was cancelled before it started. None of these names
#: is here. Neither are the workflow's own jobs from before the evaluation
#: (``~/speech_transcription``, see the module docstring), except
#: ``transcription``, which a committed script still uses; those jobs fall
#: outside the query's window and their directory is not one of
#: :data:`_PROJECT_DIR`.
_CATEGORY: dict[str, str] = {
    # The names of the 38-job ledger of June 2026, with the categories its
    # footprint_summary.json gave them, which stay as they were.
    "pilot_benchmark_wer": "WER (pilot)",
    "wer_sweep": "WER condition sweep",
    "sweep_aggregate": "Aggregation (CPU only)",
    "benchmark_der": "Diarisation (DER)",
    "benchmark_timestamps": "Timestamp accuracy",
    "pyannote_probe": "Diarisation probe",
    "pyannote_probe2": "Diarisation probe",
    # Later jobs before the audit (.hpc-plan.yaml, hpc/runs/*.env).
    "wer_sweep_pre": "Pre-flight runs",
    "wer_sweep_postfix": "WER condition sweep (post-fix re-run)",
    "wer_sweep_pf_med": "WER condition sweep (post-fix re-run)",
    "wer_sweep_pf_dis": "WER condition sweep (post-fix re-run)",
    "wer_fleurs_ml": "WER multilingual (FLEURS)",
    "lang_probe": "Language-detection probe",
    "ami_cache": "AMI reconstruction (CPU only)",
    "der_sweep": "Diarisation sweep (DER)",
    "case_study": "Case study",
    "disfluency": "Disfluency evaluation",
    "determinism": "Determinism check",
    "determinism_gpu": "Determinism check",
    "anonymisation": "Voice anonymisation",
    "anon_multimeeting": "Voice anonymisation",
    # Submitted by hand, so named by no committed script or record. Both
    # ran from this project's clone (sacct WorkDir) on 2026-08-10, just
    # before the AMI cache and DER jobs of the rebuilt diarisation protocol.
    "ami_smoke": "Diarisation probe",
    "diar_probe": "Diarisation probe",
    # Checks run during the audit, and the test-suite runs since the first
    # day of the evaluation.
    "pytest_suite": "Test suite and smoke tests",
    "finetune_smoke": "Test suite and smoke tests",
    "diag_diar": "Diarisation probe",
    "diag_diar2": "Diarisation probe",
    # The WER benchmark's first runs, 2026-05-16 to 2026-05-19, from the
    # scripts of 0e3650c (hpc/submit_benchmark_wer_gpu.sh, renamed
    # benchmark_wer when de13451 made it an array, and
    # submit_benchmark_wer_cpu_full.sh, deleted in 355a90c). The last of
    # them, array 7682561, is the most likely source of what
    # output/evaluation/README.md calls the May 2026 pilot matrix
    # (pilot_may2026/), so they share the pilot's category. A wer_postproc
    # job of 2026-05-17 was cancelled before it started and needs no entry.
    "benchmark_wer": "WER (pilot)",
    "benchmark_wer_gpu": "WER (pilot)",
    "benchmark_wer_cpu_full": "WER (pilot)",
    # Names of committed submit scripts not seen in the ledger so far.
    "finetune_pyannote": "Segmentation fine-tuning",
    "wer_eval": "WER evaluation",
    "transcription": "Transcription",
    # The determinism check on a processor without a GPU
    # (hpc/submit_determinism_cpu.sh), first run as job 8978759 (2026-10-04).
    "determinism_cpu": "Determinism check (CPU only)",
}

#: Names of this project's jobs that ran from outside its directories, each
#: attributed to it on other evidence (read on ARC, 2026-10-04).
#: pyannote_probe and pyannote_probe2 ran from the home directory on
#: 2026-05-31 and wrote their logs into this project's clone. One job under
#: the name of hpc/submit_benchmark_der.sh, 7740690 (2026-05-29), also ran
#: from the home directory, where it failed after 3 s, leaving no log; the
#: other fourteen benchmark_der jobs ran from the clone.
#: diag_diar and diag_diar2 ran from ~/diag_diar, but their scripts change
#: into the audit's clone and load this project's diarisation pipeline, to
#: find why it failed to load. A job of any other name that ran from
#: outside this project's directories is left out
#: (:func:`left_out_elsewhere`).
_RUN_ELSEWHERE = frozenset({"benchmark_der", "pyannote_probe", "pyannote_probe2",
                            "diag_diar", "diag_diar2"})

#: Category of every pre-flight: a short run that checks a job's
#: configuration before the full run, limited to a handful of utterances
#: (5 to 12 in the audit's wave, by the LIMIT settings its environment
#: records give).
_PREFLIGHT = "Pre-flight runs"

#: Stages of the audit's re-run wave. Its jobs were named at submission
#: ``au_<stage>`` for a full run and ``pf_<stage>`` for the pre-flight before
#: it (hpc/runs/sweep.env: 8913987 to 8913989 were the pre-flights of the
#: sweep jobs 8917985 to 8917987). A stage is recognised by its start, up
#: to an underscore, a digit or the end, and the longest match wins, so
#: ``ts`` covers ``ts_vad``, ``anon`` covers ``anon1`` and ``der_sweep``
#: covers ``der_sweep2`` before ``der`` can. A wave job whose stage is not
#: here is not recognised; once it has finished, the WorkDir check of
#: :func:`build_ledger` stops the build until its stage is added.
_STAGE_CATEGORY: dict[str, str] = {
    "wer": "WER condition sweep (audit re-run)",
    "ml": "WER multilingual (FLEURS)",
    "fleurs": "WER multilingual (FLEURS)",
    "ts": "Timestamp accuracy",
    "der": "Diarisation (DER)",
    "der_sweep": "Diarisation sweep (DER)",
    "recon": "AMI reconstruction (CPU only)",
    "anon": "Voice anonymisation",
    "case": "Case study",
    "det": "Determinism check",
    "determinism": "Determinism check",
    "disfluency": "Disfluency evaluation",
}

#: The directories this project's jobs run from: a clone of the repository
#: (``paper_speech_transcription``, and the audit's clones beside it with a
#: suffix) or the environment on project storage. ``~/speech_transcription``,
#: where the workflow ran before its evaluation, is deliberately not one.
_PROJECT_DIR = re.compile(
    r"(?:^|/)(?:paper_speech_transcription[^/]*|speech_transcription_env)(?:/|$)")


def job_category(name: str) -> str | None:
    """Return the category of this project's job *name*, or ``None``.

    ``None`` means the name is not this project's: neither in
    :data:`_CATEGORY` nor a wave name ``au_<stage>`` or ``pf_<stage>`` with
    a stage in :data:`_STAGE_CATEGORY`.
    """
    category = _CATEGORY.get(name)
    if category is not None:
        return category
    wave, sep, stage = name.partition("_")
    if not sep or wave not in ("au", "pf"):
        return None
    matches = [key for key in _STAGE_CATEGORY
               if re.fullmatch(re.escape(key) + r"(?:[_0-9].*)?", stage)]
    if not matches:
        return None
    return _PREFLIGHT if wave == "pf" else _STAGE_CATEGORY[max(matches, key=len)]


def is_project_workdir(workdir: str) -> bool:
    """Whether a job's sacct ``WorkDir`` lies in one of this project's
    directories (:data:`_PROJECT_DIR`)."""
    return bool(_PROJECT_DIR.search(workdir or ""))


def _counted_where_it_ran(raw: dict[str, str]) -> bool:
    """Whether a job whose name :func:`job_category` recognises counts,
    given where it ran.

    A recognised name is evidence enough only without ``WorkDir``, when the
    dump cannot tell. Otherwise the job must have run from one of this
    project's directories, or carry a name of :data:`_RUN_ELSEWHERE`.
    """
    if "WorkDir" not in raw:
        return True
    return (is_project_workdir(raw["WorkDir"] or "")
            or raw["JobName"] in _RUN_ELSEWHERE)


def _is_projects_job(raw: dict[str, str]) -> bool:
    """Whether a sacct row is one of this project's jobs, finished or not.

    It is when it ran from one of this project's directories, whatever its
    name, or when :func:`job_category` recognises its name and
    :func:`_counted_where_it_ran` lets it count. Without ``WorkDir`` the
    name alone decides. Used to list the jobs the ledger leaves out
    (:func:`left_out_never_allocated`, :func:`left_out_unfinished`).
    """
    return (is_project_workdir(raw.get("WorkDir") or "")
            or (job_category(raw["JobName"]) is not None
                and _counted_where_it_ran(raw)))


@dataclass(frozen=True)
class FootprintParams:
    """Physical constants for the energy/carbon model, with sourced defaults.

    Attributes
    ----------
    gpu_tdp_w:
        Mapping of GPU model to board TDP in watts (see :data:`GPU_TDP_W`).
    cpu_power_w_per_core:
        Per-core power draw in watts.  ``12.0`` is a representative
        server-CPU TDP-per-core; the CPU term is small relative to the GPU
        term, so the exact value has little leverage on the total.
        TODO: justify (source unknown).  An audit noted that the value
        matches the Green Algorithms calculator's generic-CPU figure;
        confirm that against the calculator's constants before citing it.
    mem_power_w_per_gb:
        Power per gigabyte of allocated memory, ``0.3725`` W/GB after
        Green Algorithms (Lannelongue et al., 2021).
    pue:
        Power Usage Effectiveness, the data-centre overhead multiplier.
        ``1.67`` is the Green Algorithms global default; many modern
        facilities report lower values (1.1-1.4).
    carbon_intensity_g_per_kwh:
        Grid carbon intensity in gCO2e per kWh.  ``207`` is the UK 2023
        location-based generation factor (DESNZ/DEFRA GHG conversion
        factors, "electricity generated"); transmission and distribution
        losses would add a further ~9% (~18 gCO2e/kWh).
    gpu_util, cpu_util:
        Fraction of board power assumed drawn over the allocation.  Both
        default to ``1.0`` (sustained assumed power). The complete estimate
        also depends on unmeasured memory, PUE and carbon assumptions.
    car_g_per_km:
        Emissions of an average passenger car in gCO2e per km, used only
        for the human-readable equivalence.  ``170`` after UK DESNZ 2023.
    """

    gpu_tdp_w: dict[str, float] = field(default_factory=lambda: dict(GPU_TDP_W))
    cpu_power_w_per_core: float = 12.0
    mem_power_w_per_gb: float = 0.3725
    pue: float = 1.67
    carbon_intensity_g_per_kwh: float = 207.0
    gpu_util: float = 1.0
    cpu_util: float = 1.0
    car_g_per_km: float = 170.0


@dataclass
class JobFootprint:
    """Estimated footprint of a single scheduler job."""

    job_id: str
    job_name: str
    category: str
    state: str
    productive: bool
    gpu_type: str
    tdp_w: float
    runtime_h: float
    gpu_hours: float
    energy_gpu_kwh: float
    energy_cpu_kwh: float
    energy_mem_kwh: float
    energy_kwh: float
    carbon_g: float


def parse_alloc_tres(alloc_tres: str) -> dict[str, object]:
    """Parse a SLURM ``AllocTRES`` string into resource counts.

    Recognises ``cpu=``, ``mem=`` (with a ``G``/``M``/``T`` suffix), and the
    GPU entries ``gres/gpu=N`` and the typed ``gres/gpu:<model>=N``.
    :func:`build_ledger` derives the ledger's ``gpus``, ``cpus`` and
    ``mem_gb`` columns with it; ARC's allocation rows carry no typed entry,
    so the GPU model comes from the node instead.

    Returns
    -------
    dict
        ``{"cpus": int, "mem_gb": float, "gpus": int, "gpu_type": str|None}``.
    """
    cpus = 0
    mem_gb = 0.0
    gpus = 0
    gpu_type: str | None = None
    for tok in alloc_tres.split(","):
        tok = tok.strip()
        if not tok or "=" not in tok:
            continue
        key, _, value = tok.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "cpu":
            cpus = int(float(value))
        elif key == "mem":
            mem_gb = _mem_to_gb(value)
        elif key == "gres/gpu":
            gpus = int(float(value))
        elif key.startswith("gres/gpu:"):
            gpu_type = key.split(":", 1)[1]
            gpus = int(float(value))
    return {"cpus": cpus, "mem_gb": mem_gb, "gpus": gpus, "gpu_type": gpu_type}


def _mem_to_gb(value: str) -> float:
    """Convert a SLURM memory token such as ``32G`` or ``62.50G`` to GB."""
    value = value.strip()
    if not value:
        return 0.0
    unit = value[-1].upper()
    scale = {"T": 1024.0, "G": 1.0, "M": 1.0 / 1024.0, "K": 1.0 / 1024.0 ** 2}
    if unit in scale:
        return float(value[:-1]) * scale[unit]
    return float(value)  # bare bytes count is not expected here


def load_ledger(path: Path) -> list[dict[str, str]]:
    """Read the committed job-ledger CSV into a list of row dicts."""
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# Building the ledger from sacct (ESTATS-13, REGEN-07)
# ---------------------------------------------------------------------------

#: Columns of arc_job_ledger.csv, in order.
LEDGER_FIELDS = ["job_id", "job_name", "state", "elapsed_s", "gpus",
                 "gpu_type", "cpus", "mem_gb"]
_SACCT_REQUIRED = ("JobID", "JobName", "State", "ElapsedRaw", "AllocTRES")

#: Why the jobs of this project under each ``left_out_*`` key of a ledger's
#: provenance are not in the ledger (:func:`ledger_provenance`).
_LEFT_OUT_REASONS = {
    "left_out_outside_project_dirs": (
        "run under one of this project's job names from another directory, "
        "so possibly another project's job"),
    "left_out_never_allocated": (
        "cancelled while pending: no allocation, so it ran on no node and "
        "drew no power"),
    "left_out_unfinished": (
        "still pending or running when the dump was taken, so its runtime "
        "was not final"),
}


def read_sacct(path: Path) -> list[dict[str, str]]:
    """Read ``sacct -P`` output (``|``-separated, with a header row).

    Raises
    ------
    ValueError
        When a column the ledger needs is missing.
    """
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="|")
        missing = [c for c in _SACCT_REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: sacct output lacks column(s) {missing}; "
                             "run sacct with -P and --format including them")
        return list(reader)


def read_node_gpus(path: Path) -> dict[str, str]:
    """Read a node listing into ``{node: GRES label}``.

    Takes ``node|Gres=gpu:<label>:<n>...`` lines, or the output of
    ``sinfo -M htc -N -o "%N %G"`` as it stands (``node
    gpu:<label>:<n>(S:0-1)``, after a CLUSTER and a NODELIST header line).
    Lines whose GRES names no GPU (a CPU node's ``(null)``, an empty field,
    a header) are left out, so a GPU job placed on such a node is reported
    as unmapped.
    """
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            node, sep, gres = line.partition("|")
            if not sep:
                node, _, gres = line.partition(" ")
            match = re.search(r"gpu:([A-Za-z0-9_.-]+):\d+", gres)
            if node and match:
                out[node.strip()] = match.group(1).lower()
    return out


def expand_nodelist(nodelist: str) -> list[str]:
    """Expand a Slurm NodeList such as ``htc-g[053-054,060]`` into names.

    Handles a single bracket group per name, which is the form the htc
    cluster reports; anything else is returned as given.
    """
    nodes: list[str] = []
    for part in re.findall(r"[^,\[]+(?:\[[^\]]*\])?", nodelist):
        match = re.fullmatch(r"(.*)\[([^\]]*)\]", part.strip())
        if not match:
            if part.strip():
                nodes.append(part.strip())
            continue
        prefix, ranges = match.groups()
        for item in ranges.split(","):
            lo, _, hi = item.partition("-")
            if hi:
                width = len(lo)
                nodes.extend(f"{prefix}{n:0{width}d}"
                             for n in range(int(lo), int(hi) + 1))
            else:
                nodes.append(f"{prefix}{lo}")
    return nodes


def _format_number(value: float) -> str:
    """Write 32.0 as ``32`` and 62.5 as ``62.5``, as the ledger does."""
    return f"{value:g}"


def build_ledger(
    sacct_rows: list[dict[str, str]],
    node_gpu: dict[str, str] | None = None,
    until: str | None = None,
    assume_gpu_type: str | None = None,
    job_names=None,
) -> list[dict[str, str]]:
    """Turn parsed ``sacct -P`` rows into ledger rows.

    Parameters
    ----------
    sacct_rows:
        Rows from :func:`read_sacct`, in sacct's order, which the ledger
        keeps.
    node_gpu:
        ``{node: GRES label}``; defaults to :data:`ARC_NODE_GPU`. A node in
        :data:`NODE_GPU_VARIANT` takes its recorded board instead, provided
        the board refines the node's label.
    until:
        ``YYYY-MM-DD``: keep only jobs that ended on or before that day,
        so a ledger captured on that day can be rebuilt from a later dump.
    assume_gpu_type:
        Record this model for every GPU job instead of the node's. Only
        for reproducing the ledger of June 2026, which assumed ``a100``.
    job_names:
        Job names to keep, wherever the jobs ran. By default, every name
        :func:`job_category` recognises, with the directory rule of the
        module docstring and the check described under Raises.

    Returns
    -------
    list of dict
        One row per kept job with the :data:`LEDGER_FIELDS` keys, whatever
        its final state; a state such as ``CANCELLED by 8707`` is recorded
        as ``CANCELLED``. Jobs still pending or running (``End`` is
        ``Unknown``) are left out, and so are jobs that ended without ever
        being allocated (no ``AllocTRES``, zero ``ElapsedRaw``: cancelled
        while pending), which drew no power; :func:`left_out_unfinished`
        and :func:`left_out_never_allocated` list this project's. With the
        default *job_names*, so are the jobs :func:`left_out_elsewhere`
        lists.

    Raises
    ------
    ValueError
        When a GPU job ran on a node with no known GPU model and AllocTRES
        names none, on nodes of different models, or on a node that
        contradicts the GPU type in its AllocTRES; when *node_gpu* labels a
        node differently from its board in :data:`NODE_GPU_VARIANT`; when
        *until* is given and the dump has no ``End`` column; and, with the
        default *job_names* and a ``WorkDir`` column, when a finished job
        that ran from one of this project's directories has a name
        :func:`job_category` does not recognise, so that a new job name
        cannot drop out of the ledger unnoticed.
    """
    nodes = ARC_NODE_GPU if node_gpu is None else node_gpu
    names = None if job_names is None else set(job_names)
    rows: list[dict[str, str]] = []
    unrecognised: list[dict[str, str]] = []
    for raw, state in _finished_jobs(sacct_rows, until):
        name = raw["JobName"]
        if names is None:
            if job_category(name) is None:
                if is_project_workdir(raw.get("WorkDir") or ""):
                    unrecognised.append(raw)
                continue
            if not _counted_where_it_ran(raw):
                continue
        elif name not in names:
            continue
        tres = parse_alloc_tres(raw["AllocTRES"] or "")
        gpu_type = ""
        if tres["gpus"]:
            if assume_gpu_type:
                gpu_type = assume_gpu_type.lower()
            else:
                gpu_type = _job_gpu_model(raw, tres["gpu_type"], nodes)
        rows.append({
            "job_id": raw["JobID"],
            "job_name": raw["JobName"],
            "state": state,
            "elapsed_s": str(int(raw["ElapsedRaw"])),
            "gpus": str(tres["gpus"]),
            "gpu_type": gpu_type,
            "cpus": str(tres["cpus"]),
            "mem_gb": _format_number(float(tres["mem_gb"])),
        })
    if unrecognised:
        shown = ", ".join(f"{r['JobName']} ({r['JobID']})" for r in unrecognised[:8])
        more = f" and {len(unrecognised) - 8} more" if len(unrecognised) > 8 else ""
        raise ValueError(
            f"{len(unrecognised)} finished job(s) ran from this project's "
            f"directories under a name job_category does not recognise: "
            f"{shown}{more}. Give the name a category in _CATEGORY, or its "
            "stage one in _STAGE_CATEGORY for an au_ or pf_ job, so that it "
            "is counted")
    return rows


def left_out_elsewhere(sacct_rows: list[dict[str, str]],
                       until: str | None = None) -> list[str]:
    """IDs of the jobs :func:`build_ledger` leaves out for where they ran.

    These are finished jobs that held an allocation under a name
    :func:`job_category` recognises but ran from outside this project's
    directories under a name not in :data:`_RUN_ELSEWHERE`, so they may be
    another project's. The list is empty for a dump without ``WorkDir``.
    """
    return [raw["JobID"] for raw, _ in _finished_jobs(sacct_rows, until)
            if job_category(raw["JobName"]) is not None
            and not _counted_where_it_ran(raw)]


def left_out_never_allocated(sacct_rows: list[dict[str, str]],
                             until: str | None = None) -> list[str]:
    """IDs of this project's jobs that ended without holding an allocation.

    They were cancelled while pending (:func:`_never_allocated`), so they
    ran on no node and drew no power, and :func:`build_ledger` leaves them
    out. A job is this project's by :func:`_is_projects_job`, so one under
    a name no rule knows is listed when it ran from one of this project's
    directories. Jobs that ended after *until* are outside the ledger's
    window and are not listed.
    """
    return [raw["JobID"] for raw, _ in _ended_jobs(sacct_rows, until)
            if _never_allocated(raw) and _is_projects_job(raw)]


def left_out_unfinished(sacct_rows: list[dict[str, str]]) -> list[str]:
    """IDs of this project's jobs still pending or running in the dump.

    Their runtime is not final, so :func:`build_ledger` leaves them out. A
    dump taken once every job of the evaluation has finished gives none.
    """
    return [raw["JobID"] for raw in sacct_rows
            if _unfinished(raw) and _is_projects_job(raw)]


def _state(raw: dict[str, str]) -> str:
    """The first word of sacct's State: ``CANCELLED`` for ``CANCELLED by 8707``."""
    return (raw["State"] or "").strip().split(" ")[0].upper()


def _unfinished(raw: dict[str, str]) -> bool:
    """Whether a job had not finished when the dump was taken."""
    # sacct writes End=Unknown for a job that has not finished.
    return (_state(raw) in _UNFINISHED_STATES
            or (raw.get("End") or "").strip() == "Unknown")


def _ended_jobs(sacct_rows: list[dict[str, str]], until: str | None):
    """Yield ``(row, state)`` for each job of the dump that has finished,
    by *until* when it is given, whether or not it held an allocation.

    *state* is the first word of sacct's State (:func:`_state`).

    Raises
    ------
    ValueError
        When *until* is not a ``YYYY-MM-DD`` date, or is given for a dump
        without the ``End`` column.
    """
    if until is not None:
        _dt.date.fromisoformat(until)            # refuse a malformed date
        if sacct_rows and "End" not in sacct_rows[0]:
            raise ValueError("--until needs the sacct End column")
    for raw in sacct_rows:
        if _unfinished(raw):
            continue
        if until is not None and (raw.get("End") or "").strip()[:10] > until:
            continue
        yield raw, _state(raw)


def _finished_jobs(sacct_rows: list[dict[str, str]], until: str | None):
    """Yield ``(row, state)`` for each job of the dump that has finished,
    by *until* when it is given, after holding an allocation.

    *state* is the first word of sacct's State, so ``CANCELLED by 8707``
    gives ``CANCELLED``.

    Raises
    ------
    ValueError
        As :func:`_ended_jobs`.
    """
    for raw, state in _ended_jobs(sacct_rows, until):
        if not _never_allocated(raw):
            yield raw, state


def _never_allocated(raw: dict[str, str]) -> bool:
    """Whether a finished job never held an allocation.

    sacct gives a job cancelled while pending an empty ``AllocTRES``, a
    zero ``ElapsedRaw`` and the NodeList ``None assigned``; it ran on no
    node and drew no power, so it is not a job of the ledger.
    """
    return (not (raw.get("AllocTRES") or "").strip()
            and int(raw.get("ElapsedRaw") or 0) == 0)


def _gres_label(model: str) -> str:
    """The GRES label *model* refines: ``h100`` for ``h100-pcie``.

    Relies on the naming of :data:`NODE_GPU_VARIANT`'s boards; a label
    such as ``rtx8000`` or ``l40s`` is returned as it is.
    """
    return model.split("-", 1)[0]


def _node_model(node: str, nodes: dict[str, str]) -> str | None:
    """Return *node*'s GPU model, or ``None`` when nothing records it.

    The model is the board :data:`NODE_GPU_VARIANT` records for the node,
    otherwise the node's GRES label in *nodes*.

    Raises
    ------
    ValueError
        When *nodes* labels the node's GPU with a label its recorded board
        does not refine: the node has been refitted since the record, and
        the board would misprice it.
    """
    listed = nodes.get(node)
    board = NODE_GPU_VARIANT.get(node)
    if board is None:
        return listed
    if listed is not None and _gres_label(board) != listed:
        raise ValueError(
            f"node {node}: the node listing labels its GPU {listed!r} but "
            f"NODE_GPU_VARIANT records a {board!r} board; the node has "
            "changed since that record, so correct NODE_GPU_VARIANT")
    return board


def _job_gpu_model(raw: dict[str, str], typed: str | None,
                   nodes: dict[str, str]) -> str:
    """Return the GPU model a GPU job is priced at.

    The model is that of the node(s) the job ran on. A typed AllocTRES
    entry (``gres/gpu:<label>=N``, written when the job asked for a GPU
    type) gives only the GRES label: it must agree with the node, whose
    recorded board then refines it, and it stands alone only when the node
    is unknown. Taking the label alone would price a V100 PCIe card at the
    300 W of the SXM2 module.

    Raises
    ------
    ValueError
        When the job's nodes are unknown and AllocTRES names no type, when
        the nodes hold different models, or when they contradict the typed
        entry; guessing would misprice the job in each case.
    """
    job_nodes = expand_nodelist(raw.get("NodeList") or "")
    typed = typed.lower() if typed else None
    models = {node: _node_model(node, nodes) for node in job_nodes}
    unknown = [node for node, model in models.items() if model is None]
    if not job_nodes or unknown:
        if typed:
            return typed
        raise ValueError(
            f"job {raw['JobID']}: GPU job on node(s) {unknown or job_nodes} "
            "with no known GPU model; pass a current node listing with --nodes")
    distinct = set(models.values())
    if len(distinct) > 1:
        raise ValueError(f"job {raw['JobID']}: nodes {job_nodes} hold "
                         f"different GPU models {sorted(distinct)}")
    model = distinct.pop()
    if typed and _gres_label(model) != typed:
        raise ValueError(
            f"job {raw['JobID']}: AllocTRES names a {typed!r} GPU but node(s) "
            f"{job_nodes} hold {model!r}; pass a current node listing with --nodes")
    return model


def write_ledger(rows: list[dict[str, str]], path: Path) -> None:
    """Write ledger rows to *path* (LF line endings, as committed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def provenance_path(ledger: Path) -> Path:
    """Where the provenance of *ledger* is written: ``<stem>_provenance.json``."""
    return ledger.with_name(ledger.stem + "_provenance.json")


def ledger_provenance(sacct_path: Path, captured: str, until: str | None,
                      assume_gpu_type: str | None, nodes_path: Path | None,
                      sacct_query: str | None, workdir_checked: bool = False,
                      counted_elsewhere: list[str] | None = None,
                      left_out: list[str] | None = None,
                      never_allocated: list[str] | None = None,
                      unfinished: list[str] | None = None,
                      ) -> dict[str, object]:
    """Describe how a ledger was built, for the summary's ``provenance``.

    Records everything :func:`build_ledger` was given, so the ledger can
    be rebuilt from the named files and checked against their digests.
    *workdir_checked* says whether the dump had the ``WorkDir`` column the
    directory rule and the coverage check need. *counted_elsewhere* lists
    the kept jobs that ran from outside this project's directories, counted
    by their names in :data:`_RUN_ELSEWHERE`. The jobs of this project the
    ledger leaves out are listed by ID with the reason
    (:data:`_LEFT_OUT_REASONS`): *left_out*, those of its names that ran
    from elsewhere (:func:`left_out_elsewhere`); *never_allocated*, those
    cancelled while pending (:func:`left_out_never_allocated`); and
    *unfinished*, those still pending or running
    (:func:`left_out_unfinished`). Jobs that ended after *until* are
    outside the window and are not listed.
    """
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    nodes_source = (Path(nodes_path).name if nodes_path
                    else "ARC_NODE_GPU (built-in 2026-10-04 listing)")
    return {
        "cluster": "htc",
        "captured": captured,
        "until": until,
        "sacct_file": Path(sacct_path).name,
        "sacct_sha256": digest(sacct_path),
        "sacct_query": sacct_query,
        "nodes_file": Path(nodes_path).name if nodes_path else None,
        "nodes_sha256": digest(nodes_path) if nodes_path else None,
        "assume_gpu_type": assume_gpu_type,
        "gpu_model_source": (
            f"assumed {assume_gpu_type} for every GPU job (--assume-gpu-type)"
            if assume_gpu_type else
            f"job NodeList mapped through {nodes_source}; boards from "
            f"NODE_GPU_VARIANT ({', '.join(sorted(NODE_GPU_VARIANT))}); a "
            "typed AllocTRES entry checked against the node"),
        "job_selection": (
            "this project's job names (evaluation.footprint.job_category), "
            + ("run from its directories, or from elsewhere under a name of "
               "_RUN_ELSEWHERE" if workdir_checked else
               "by name alone, since the dump has no WorkDir")
            + "; every finished job that held an allocation, whatever its "
              "state"),
        "workdir_checked": workdir_checked,
        "counted_outside_project_dirs": counted_elsewhere,
        "left_out_outside_project_dirs": left_out,
        "left_out_never_allocated": never_allocated,
        "left_out_unfinished": unfinished,
        "left_out_reasons": dict(_LEFT_OUT_REASONS),
        "measured_energy_available": False,
        "note": PROVENANCE["note"],
    }


def estimate_job(row: dict[str, str], params: FootprintParams) -> JobFootprint:
    """Estimate the footprint of one ledger row under *params*.

    The Green Algorithms operating-energy model is applied to the recorded
    runtime and allocation; emissions are the drawn energy times the grid
    carbon intensity.

    Raises
    ------
    ValueError
        If the job holds GPUs whose ``gpu_type`` has no entry in
        ``params.gpu_tdp_w``. Pricing such a job at 0 W would drop its GPU
        term and yield a smaller, plausible total with an uncosted device.
    """
    runtime_h = float(row["elapsed_s"]) / 3600.0
    gpus = int(row["gpus"] or 0)
    cpus = int(row["cpus"] or 0)
    mem_gb = float(row["mem_gb"] or 0.0)
    gpu_type = (row.get("gpu_type") or "").strip().lower()

    if gpus and gpu_type not in params.gpu_tdp_w:
        raise ValueError(
            f"job {row.get('job_id', '?')}: GPU type {gpu_type!r} has no "
            f"board power in gpu_tdp_w (known: {sorted(params.gpu_tdp_w)}). "
            "Add it with --gpu-tdp MODEL=W instead of letting it cost 0 W."
        )
    gpu_tdp = params.gpu_tdp_w[gpu_type] if gpus else 0.0
    gpu_hours = runtime_h * gpus

    e_gpu_wh = gpu_hours * gpu_tdp * params.gpu_util
    e_cpu_wh = runtime_h * cpus * params.cpu_power_w_per_core * params.cpu_util
    e_mem_wh = runtime_h * mem_gb * params.mem_power_w_per_gb

    device_wh = e_gpu_wh + e_cpu_wh + e_mem_wh
    total_wh = device_wh * params.pue
    energy_kwh = total_wh / 1000.0
    carbon_g = energy_kwh * params.carbon_intensity_g_per_kwh

    name = row["job_name"]
    state = row["state"].strip().upper()
    return JobFootprint(
        job_id=row["job_id"],
        job_name=name,
        category=job_category(name) or name,
        state=state,
        productive=(state == _PRODUCTIVE_STATE),
        gpu_type=gpu_type if gpus else "",
        tdp_w=gpu_tdp,
        runtime_h=runtime_h,
        gpu_hours=gpu_hours,
        energy_gpu_kwh=e_gpu_wh * params.pue / 1000.0,
        energy_cpu_kwh=e_cpu_wh * params.pue / 1000.0,
        energy_mem_kwh=e_mem_wh * params.pue / 1000.0,
        energy_kwh=energy_kwh,
        carbon_g=carbon_g,
    )


def _totals(jobs: list[JobFootprint]) -> dict[str, float]:
    """Sum the headline quantities over *jobs*."""
    return {
        "n_jobs": len(jobs),
        "gpu_hours": sum(j.gpu_hours for j in jobs),
        "runtime_h": sum(j.runtime_h for j in jobs),
        "energy_kwh": sum(j.energy_kwh for j in jobs),
        "carbon_g": sum(j.carbon_g for j in jobs),
    }


def summarise(jobs: list[JobFootprint], params: FootprintParams,
              provenance: dict | None = None) -> dict:
    """Aggregate per-job footprints into the manuscript-facing summary.

    *provenance* describes the ledger (see :func:`ledger_provenance`);
    :data:`PROVENANCE`, the record of the June 2026 ledger, is used when
    it is ``None``.
    """
    productive = [j for j in jobs if j.productive]
    overhead = [j for j in jobs if not j.productive]

    by_category: dict[str, dict[str, float]] = {}
    for j in jobs:
        bucket = by_category.setdefault(
            j.category,
            {"n_jobs": 0, "gpu_hours": 0.0, "energy_kwh": 0.0, "carbon_g": 0.0},
        )
        bucket["n_jobs"] += 1
        bucket["gpu_hours"] += j.gpu_hours
        bucket["energy_kwh"] += j.energy_kwh
        bucket["carbon_g"] += j.carbon_g

    overall = _totals(jobs)
    carbon_kg = overall["carbon_g"] / 1000.0
    car_km = overall["carbon_g"] / params.car_g_per_km if params.car_g_per_km else 0.0

    return {
        "provenance": PROVENANCE if provenance is None else provenance,
        "parameters": asdict(params),
        "overall": {
            **overall,
            "carbon_kg": carbon_kg,
            "energy_gpu_kwh": sum(j.energy_gpu_kwh for j in jobs),
            "energy_cpu_kwh": sum(j.energy_cpu_kwh for j in jobs),
            "energy_mem_kwh": sum(j.energy_mem_kwh for j in jobs),
        },
        "productive": _totals(productive),
        "overhead": {
            **_totals(overhead),
            "states": sorted({j.state for j in overhead}),
        },
        "by_category": dict(sorted(
            by_category.items(),
            key=lambda kv: kv[1]["gpu_hours"],
            reverse=True,
        )),
        "equivalence": {
            "car_km_average_passenger": car_km,
            "car_g_per_km": params.car_g_per_km,
        },
    }


def write_csv(jobs: list[JobFootprint], out_path: Path) -> None:
    """Write the per-job footprint table to *out_path* as CSV.

    ``gpu_type`` and ``tdp_w`` show the board power each job was costed
    at, so the mapping from model to watts can be audited row by row
    (ESTATS-05).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "job_id", "job_name", "category", "state", "productive",
            "gpu_type", "tdp_w",
            "runtime_h", "gpu_hours", "energy_kwh", "carbon_g",
        ])
        for j in jobs:
            writer.writerow([
                j.job_id, j.job_name, j.category, j.state, j.productive,
                j.gpu_type, f"{j.tdp_w:g}",
                f"{j.runtime_h:.4f}", f"{j.gpu_hours:.4f}",
                f"{j.energy_kwh:.5f}", f"{j.carbon_g:.2f}",
            ])


def write_json(summary: dict, out_path: Path) -> None:
    """Write the machine-readable footprint summary to *out_path*."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)


def print_summary(summary: dict) -> None:
    """Print a console summary of the footprint estimate."""
    o = summary["overall"]
    p = summary["productive"]
    h = summary["overhead"]
    params = summary["parameters"]
    print(f"\n{'─' * 72}")
    print("  Estimated computational footprint (Green Algorithms model)")
    print("  " + "─" * 70)
    print(f"  Jobs:              {o['n_jobs']}  "
          f"({p['n_jobs']} completed, {h['n_jobs']} failed/cancelled)")
    print(f"  GPU-hours:         {o['gpu_hours']:.1f}  "
          f"(productive {p['gpu_hours']:.1f}, "
          f"overhead {o['gpu_hours'] - p['gpu_hours']:.1f})")
    print(f"  Energy:            {o['energy_kwh']:.1f} kWh  "
          f"(PUE {params['pue']}, GPU {o['energy_gpu_kwh']:.1f} / "
          f"CPU {o['energy_cpu_kwh']:.1f} / mem {o['energy_mem_kwh']:.2f} kWh)")
    print(f"  Emissions:         {o['carbon_kg']:.2f} kgCO2e  "
          f"(grid {params['carbon_intensity_g_per_kwh']:.0f} gCO2e/kWh)")
    print(f"  Equivalence:       ~{summary['equivalence']['car_km_average_passenger']:.0f} km "
          "by an average car")
    print("  " + "─" * 70)
    width = max([26, *map(len, summary["by_category"])])
    print(f"  {'Category':<{width}}  {'jobs':>4}  {'GPU-h':>7}  {'kgCO2e':>7}")
    for cat, b in summary["by_category"].items():
        print(f"  {cat:<{width}}  {b['n_jobs']:>4}  {b['gpu_hours']:>7.1f}  "
              f"{b['carbon_g'] / 1000.0:>7.3f}")
    print(f"{'─' * 72}")
    print("  Model estimate uses the recorded allocations and assumed power, "
          "utilisation, PUE and carbon intensity; no measured upper bound.")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.footprint",
        description=(
            "Estimate the energy and carbon footprint of the experimental "
            "programme from the committed SLURM job ledger, using the "
            "parameterised Green Algorithms model."
        ),
    )
    p.add_argument("--ledger", type=Path, default=_DEFAULT_LEDGER,
                   help="Job-ledger CSV to read, or with --from-sacct to "
                        "write (default: %(default)s).")
    p.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR,
                   help="Destination for the report/summary (default: %(default)s).")
    p.add_argument("--pue", type=float, default=None,
                   help="Override Power Usage Effectiveness (default: 1.67).")
    p.add_argument("--carbon-intensity", type=float, default=None,
                   dest="carbon_intensity",
                   help="Override grid intensity in gCO2e/kWh (default: 207).")
    p.add_argument("--gpu-util", type=float, default=None, dest="gpu_util",
                   help="Override GPU utilisation factor (default: 1.0).")
    p.add_argument("--gpu-tdp", action="append", default=[], dest="gpu_tdp",
                   metavar="MODEL=W",
                   help=("Set the board power of one GPU model in watts, "
                         "adding or replacing its entry (repeatable), e.g. "
                         "--gpu-tdp a100=250."))
    p.add_argument("--cpu-power", type=float, default=None, dest="cpu_power",
                   help="Override per-core CPU power in watts (default: 12.0).")

    build = p.add_argument_group(
        "building the ledger",
        "With --from-sacct the ledger is built from a raw sacct dump and "
        "written to --ledger (with <stem>_provenance.json beside it); no "
        "estimate is made.")
    build.add_argument("--from-sacct", type=Path, default=None,
                       dest="from_sacct", metavar="RAW.psv",
                       help="sacct -P output with JobID, JobName, State, "
                            "ElapsedRaw, End, AllocTRES and NodeList, and "
                            "WorkDir, by which jobs of this project's names "
                            "that ran elsewhere are left out and no job of "
                            "this project is missed.")
    build.add_argument("--captured", default=None, metavar="YYYY-MM-DD",
                       help="Date the dump was taken (default: today).")
    build.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                       help="Keep only jobs that ended on or before this day.")
    build.add_argument("--nodes", type=Path, default=None, metavar="NODES.psv",
                       help="node|Gres=gpu:<label>:<n> lines, or the output "
                            "of sinfo -M htc -N -o '%%N %%G', to map NodeList "
                            "to GPU models (default: the built-in 2026-10-04 "
                            "listing, ARC_NODE_GPU).")
    build.add_argument("--assume-gpu-type", default=None, dest="assume_gpu_type",
                       metavar="MODEL",
                       help="Record MODEL for every GPU job instead of its "
                            "node's. Only to reproduce the June 2026 ledger "
                            "(a100); not for a refresh.")
    build.add_argument("--sacct-query", default=None, dest="sacct_query",
                       help="The sacct command that produced the dump, "
                            "recorded in the provenance.")
    return p


def _build_from_sacct(args) -> int:
    """Write the ledger and its provenance from ``--from-sacct``.

    Returns 0, or 2 when the dump or node listing cannot be read, a GPU
    job cannot be given a model, or a job that ran from this project's
    directories has a name :func:`job_category` does not recognise.
    """
    try:
        sacct_rows = read_sacct(args.from_sacct)
        nodes = read_node_gpus(args.nodes) if args.nodes else None
        rows = build_ledger(sacct_rows, nodes, until=args.until,
                            assume_gpu_type=args.assume_gpu_type)
    except (OSError, ValueError) as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print("  Error: no job of this project in the dump.", file=sys.stderr)
        return 2
    workdir_checked = "WorkDir" in sacct_rows[0]
    counted_elsewhere = left_out = None
    if workdir_checked:
        workdir = {raw["JobID"]: raw.get("WorkDir") or "" for raw in sacct_rows}
        counted_elsewhere = [row["job_id"] for row in rows
                             if not is_project_workdir(workdir.get(row["job_id"], ""))]
        left_out = left_out_elsewhere(sacct_rows, args.until)
    never_allocated = left_out_never_allocated(sacct_rows, args.until)
    unfinished = left_out_unfinished(sacct_rows)
    captured = args.captured or _dt.date.today().isoformat()
    provenance = ledger_provenance(
        args.from_sacct, captured, args.until, args.assume_gpu_type,
        args.nodes, args.sacct_query, workdir_checked, counted_elsewhere,
        left_out, never_allocated, unfinished)
    write_ledger(rows, args.ledger)
    prov_path = provenance_path(args.ledger)
    write_json(provenance, prov_path)
    types: dict[str, int] = {}
    for row in rows:
        types[row["gpu_type"] or "(CPU)"] = types.get(row["gpu_type"] or "(CPU)", 0) + 1
    print(f"Ledger: {args.ledger}  ({len(rows)} jobs; GPU models {types})")
    print(f"Provenance: {prov_path}")
    if not workdir_checked:
        print("  Note: the dump has no WorkDir column, so jobs are kept by "
              "name alone: another project's job under one of this "
              "project's names would be counted, and a job of this project "
              "under a name job_category does not recognise would be "
              "missed; add WorkDir to sacct's --format.")
    else:
        if counted_elsewhere:
            print(f"  Note: {len(counted_elsewhere)} kept job(s) ran from "
                  "outside this project's directories and are counted by "
                  f"their names (_RUN_ELSEWHERE): {', '.join(counted_elsewhere)}.")
        if left_out:
            shown = ", ".join(left_out[:12])
            more = f" and {len(left_out) - 12} more" if len(left_out) > 12 else ""
            print(f"  Note: {len(left_out)} job(s) under this project's job "
                  "names ran from other directories and are left out, as "
                  f"possibly another project's: {shown}{more}. Add a name to "
                  "_RUN_ELSEWHERE if its jobs are this project's.")
    if never_allocated:
        print(f"  Note: {len(never_allocated)} job(s) of this project were "
              "cancelled while pending, drew no power and are left out: "
              f"{', '.join(never_allocated)}.")
    if unfinished:
        print(f"  Note: {len(unfinished)} job(s) of this project are still "
              f"pending or running and are left out: {', '.join(unfinished)}. "
              "Capture again once they have finished.")
    if "h100" in types:
        print("  Note: 'h100' marks H100 nodes whose board variant is not on "
              "record; the estimate needs --gpu-tdp h100=W.")
    return 0


def _parse_gpu_tdp(values: list[str]) -> dict[str, float]:
    """Parse repeated ``MODEL=W`` values into a ``{model: watts}`` dict.

    Model names are lower-cased to match how :func:`estimate_job` reads
    ``gpu_type`` from the ledger.

    Raises
    ------
    ValueError
        If a value is not of the form ``MODEL=W`` with a numeric ``W``.
    """
    out: dict[str, float] = {}
    for value in values:
        model, sep, watts = value.partition("=")
        if not sep or not model.strip():
            raise ValueError(f"--gpu-tdp expects MODEL=W, got {value!r}")
        try:
            out[model.strip().lower()] = float(watts)
        except ValueError:
            # float()'s own message names neither the option nor the value.
            raise ValueError(f"--gpu-tdp expects MODEL=W with a numeric W, "
                             f"got {value!r}") from None
    return out


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface.

    Parameters
    ----------
    argv:
        Argument list; ``None`` reads ``sys.argv``.

    Returns
    -------
    int
        ``0`` on success; ``2`` when the ledger is missing or empty, a
        ``--gpu-tdp`` value is malformed, a GPU job's model has no
        board-power entry, or (with ``--from-sacct``) the dump cannot be
        turned into a ledger.

    Side effects
    ------------
    Writes ``footprint_report.csv`` and ``footprint_summary.json`` into
    ``--output-dir`` (overwriting them) and prints a summary; with
    ``--from-sacct`` writes the ledger and its provenance instead.
    Reconfigures stdout to UTF-8 where the stream allows it.
    """
    args = _build_parser().parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.from_sacct is not None:
        return _build_from_sacct(args)

    overrides: dict[str, float] = {}
    if args.pue is not None:
        overrides["pue"] = args.pue
    if args.carbon_intensity is not None:
        overrides["carbon_intensity_g_per_kwh"] = args.carbon_intensity
    if args.gpu_util is not None:
        overrides["gpu_util"] = args.gpu_util
    if args.cpu_power is not None:
        overrides["cpu_power_w_per_core"] = args.cpu_power
    if args.gpu_tdp:
        try:
            overrides["gpu_tdp_w"] = {**GPU_TDP_W,
                                      **_parse_gpu_tdp(args.gpu_tdp)}
        except ValueError as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            return 2
    params = FootprintParams(**overrides)

    try:
        rows = load_ledger(args.ledger)
    except FileNotFoundError:
        print(f"  Error: ledger not found: {args.ledger}", file=sys.stderr)
        return 2

    try:
        jobs = [estimate_job(row, params) for row in rows]
    except ValueError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 2
    if not jobs:
        print("  Error: ledger is empty.", file=sys.stderr)
        return 2

    prov_path = provenance_path(args.ledger)
    provenance = (json.loads(prov_path.read_text(encoding="utf-8"))
                  if prov_path.exists() else None)
    summary = summarise(jobs, params, provenance)
    print(f"Ledger: {args.ledger}  ({len(jobs)} jobs)", flush=True)
    print_summary(summary)

    csv_path = args.output_dir / "footprint_report.csv"
    json_path = args.output_dir / "footprint_summary.json"
    write_csv(jobs, csv_path)
    write_json(summary, json_path)
    print(f"  report:  {csv_path}")
    print(f"  summary: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
