"""Which jobs the footprint ledger counts (OUTPUTS-05, ESTATS-13).

The ledger captured in June 2026 stopped before the jobs behind most of
the reported results, and the builder recognised this project's jobs only
by an explicit list of names, which the audit's re-run wave (au_*, pf_*)
outgrew. That ledger's window also opened on 2026-05-20, four days after
the evaluation's first jobs. These tests pin the policy in
evaluation/footprint.py: which names are this project's, which states
count, the directory rule that leaves out a job of one of these names run
from elsewhere, the WorkDir check that stops a build when a job of this
project carries a name nothing knows, and the provenance's list of the
jobs left out, each under its reason. The sacct rows are copied from the
dumps of 2026-10-04, except where a comment says otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import footprint as fp

# Every job name of this project that ran in the dump of 2026-10-30, from
# 2026-05-16, with its category: the names of the committed ledger. The
# project's jobs were told apart from the shared account's other jobs by
# sacct WorkDir (a clone of this repository) and, for the five jobs run from
# elsewhere (every job of four names, and one benchmark_der job), by their
# scripts and logs on ARC. A fifty-eighth name, wer_postproc, never ran: its
# only job was cancelled while pending. The dump of 2026-10-04 held the
# first 55; the Spanish V100 control added its two.
_PROJECT_NAMES = {
    "benchmark_wer": "WER (pilot)",
    "benchmark_wer_gpu": "WER (pilot)",
    "benchmark_wer_cpu_full": "WER (pilot)",
    "pilot_benchmark_wer": "WER (pilot)",
    "wer_sweep": "WER condition sweep",
    "wer_sweep_postfix": "WER condition sweep (post-fix re-run)",
    "wer_sweep_pf_med": "WER condition sweep (post-fix re-run)",
    "wer_sweep_pf_dis": "WER condition sweep (post-fix re-run)",
    "au_wer_large": "WER condition sweep (audit re-run)",
    "au_wer_med": "WER condition sweep (audit re-run)",
    "au_wer_dis": "WER condition sweep (audit re-run)",
    "wer_sweep_pre": "Pre-flight runs",
    "pf_wer_large": "Pre-flight runs",
    "pf_wer_med": "Pre-flight runs",
    "pf_wer_dis": "Pre-flight runs",
    "pf_ts": "Pre-flight runs",
    "pf_ts_vad": "Pre-flight runs",
    "pf_anon": "Pre-flight runs",
    "pf_ml": "Pre-flight runs",
    "pf_es419_v100": "Pre-flight runs",
    "sweep_aggregate": "Aggregation (CPU only)",
    "wer_fleurs_ml": "WER multilingual (FLEURS)",
    "au_ml": "WER multilingual (FLEURS)",
    "au_fleurs_diac": "WER multilingual (FLEURS)",
    "ctl_es419_v100": "WER multilingual (FLEURS)",
    "lang_probe": "Language-detection probe",
    "disfluency": "Disfluency evaluation",
    "benchmark_der": "Diarisation (DER)",
    "au_der_default": "Diarisation (DER)",
    "au_der_oracle": "Diarisation (DER)",
    "au_der_tuned": "Diarisation (DER)",
    "au_der_concat": "Diarisation (DER)",
    "der_sweep": "Diarisation sweep (DER)",
    "au_der_sweep": "Diarisation sweep (DER)",
    "au_der_sweep2": "Diarisation sweep (DER)",
    "pyannote_probe": "Diarisation probe",
    "pyannote_probe2": "Diarisation probe",
    "ami_smoke": "Diarisation probe",
    "diar_probe": "Diarisation probe",
    "diag_diar": "Diarisation probe",
    "diag_diar2": "Diarisation probe",
    "ami_cache": "AMI reconstruction (CPU only)",
    "au_recon_audit": "AMI reconstruction (CPU only)",
    "benchmark_timestamps": "Timestamp accuracy",
    "au_ts": "Timestamp accuracy",
    "au_ts_vad": "Timestamp accuracy",
    "anonymisation": "Voice anonymisation",
    "anon_multimeeting": "Voice anonymisation",
    "au_anon1": "Voice anonymisation",
    "au_anon2": "Voice anonymisation",
    "case_study": "Case study",
    "au_case": "Case study",
    "determinism": "Determinism check",
    "determinism_gpu": "Determinism check",
    "determinism_cpu": "Determinism check (CPU only)",
    "pytest_suite": "Test suite and smoke tests",
    "finetune_smoke": "Test suite and smoke tests",
}

# Names of other projects' jobs on the same account in that dump, with the
# near misses: render rendered another project's manuscript from the same
# account in the same week, diagvocab shares diag_diar's first letters, and
# ld-surprisal is another project's GPU job.
_OTHER_NAMES = [
    "render", "docchecks", "checkdocs", "wrap", "cat", "diagvocab",
    "ld-surprisal", "ld-bayes", "claps_databased2", "claps_pooled2",
    "bfda_sempri", "p1_fit_erp", "p1_diag_fit", "p2_projpred", "lexpower",
    "lexpower_upper", "lexkr", "fuprod48", "loocmp", "htccheck", "bayes",
    # The workflow's own jobs before the evaluation, from ~/speech_transcription
    # (August 2025 to January 2026, on htc and arc). Its "transcription" jobs
    # carry the name of hpc/batch_transcription.sh, which _CATEGORY keeps;
    # the directory rule leaves those out instead.
    "enhanced_transcription", "batch_transcription_arc",
    "batch_transcription_fixed.sh", "submit_setup.sh", "setup_oxford_arc",
    "test_imports", "test_enhanced_masking", "real_audio_test",
]


def test_the_project_has_57_job_names_that_ran():
    assert len(_PROJECT_NAMES) == 57


def test_the_table_holds_the_names_of_the_committed_ledger():
    # A recapture that brings a new name fails here until the name and its
    # category are added above.
    ledger = PROJECT_ROOT / "output" / "evaluation" / "arc_job_ledger.csv"
    assert {row["job_name"] for row in fp.load_ledger(ledger)} == set(_PROJECT_NAMES)


@pytest.mark.parametrize("name", sorted(_PROJECT_NAMES))
def test_every_job_name_of_this_project_has_its_category(name):
    assert fp.job_category(name) == _PROJECT_NAMES[name]


@pytest.mark.parametrize("name", _OTHER_NAMES)
def test_other_projects_names_are_not_this_projects(name):
    assert fp.job_category(name) is None


@pytest.mark.parametrize("name, category", [
    # Jobs still to come in the audit's wave: a case-study re-run and a
    # determinism run on the CPU, whatever their stage's suffix.
    ("au_case2", "Case study"),
    ("au_case_rerun", "Case study"),
    ("au_det_cpu", "Determinism check"),
    ("au_determinism_cpu", "Determinism check"),
    ("pf_case", "Pre-flight runs"),
    # The longest stage wins: der_sweep2 is a sweep, der_concat a DER run.
    ("au_der_sweep3", "Diarisation sweep (DER)"),
    ("au_der_concat", "Diarisation (DER)"),
])
def test_wave_names_are_recognised_by_their_stage(name, category):
    assert fp.job_category(name) == category


@pytest.mark.parametrize("name", [
    "au_", "pf_", "au", "au_foo", "pf_foo", "au_tsx", "au_dertuned",
    "aux_wer", "xau_wer",
    # A new name without the wave prefix is not guessed from its start:
    # this one would otherwise read as part of the first-pass sweep.
    "wer_sweep_new",
])
def test_other_names_are_not_guessed(name):
    assert fp.job_category(name) is None


@pytest.mark.parametrize("workdir, expected", [
    ("/home/educ1242/paper_speech_transcription", True),
    ("/home/educ1242/paper_speech_transcription_audit", True),
    ("/home/educ1242/paper_speech_transcription_audit_w2/hpc", True),
    ("/data/educ-lift/educ1242/speech_transcription_env/output", True),
    ("/home/educ1242", False),
    ("/home/educ1242/diag_diar", False),
    ("/home/educ1242/my_paper_speech_transcription", False),
    ("/data/educ-lift/educ1242/speech_transcription_env_old", False),
    ("/data/educ-intract/educ1242", False),
    # Where the workflow ran before its evaluation.
    ("/home/educ1242/speech_transcription", False),
    ("/home/educ1242/speech_transcription/HPC_scripts", False),
    ("", False),
])
def test_project_directories(workdir, expected):
    assert fp.is_project_workdir(workdir) is expected


_HEADER = ("JobID|JobName|Account|State|ElapsedRaw|Start|End|Partition|"
           "AllocTRES|NodeList|WorkDir\n")
_ROWS = """\
7746170|pyannote_probe|educ-intract|COMPLETED|288|2026-05-31T15:01:32|2026-05-31T15:06:20|short|billing=2,cpu=2,gres/gpu=1,mem=16G,node=1|htc-g058|/home/educ1242
8895714|render|educ-intract|COMPLETED|563|2026-09-25T20:04:14|2026-09-25T20:13:37|short|billing=4,cpu=4,mem=16G,node=1|htc-c065|/data/educ-intract/educ1242
8913985|pytest_suite|educ-intract|FAILED|707|2026-09-26T23:52:01|2026-09-27T00:03:48|short|billing=2,cpu=2,mem=8G,node=1|htc-c008|/home/educ1242/paper_speech_transcription_audit
8917982|au_case|educ-intract|CANCELLED by 8707|0|2026-09-27T14:56:31|2026-09-27T14:56:31|\
short||None assigned|/home/educ1242/paper_speech_transcription_audit
8918023|au_case|educ-intract|FAILED|963|2026-09-27T18:11:53|2026-09-27T18:27:56|short|billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|htc-g059|/home/educ1242/paper_speech_transcription_audit
8976270|diag_diar|educ-intract|COMPLETED|293|2026-10-03T23:49:31|2026-10-03T23:54:24|short|billing=2,cpu=2,mem=8G,node=1|htc-c071|/home/educ1242/diag_diar
8976354|au_der_default|educ-intract|PENDING|0|Unknown|Unknown|short||None assigned|\
/home/educ1242/paper_speech_transcription_audit_w2
"""
# A finished job of this project under a name no rule knows (made up).
_UNKNOWN = ("8999999|new_benchmark|educ-intract|COMPLETED|600|2026-10-05T10:00:00|"
            "2026-10-05T10:10:00|short|billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|"
            "htc-g064|/home/educ1242/paper_speech_transcription_audit\n")
# The WER benchmark's first runs, before the June ledger's window and inside
# the committed one's: a CPU job cancelled while it ran, a GPU job stopped at
# its time limit, and a job of a name no rule knows, cancelled while pending.
_FIRST_RUNS = """\
7663576|benchmark_wer_cpu_full|educ-lift|CANCELLED by 8707|442|2026-05-16T22:45:54|\
2026-05-16T22:53:16|medium|billing=8,cpu=8,mem=32G,node=1|htc-c059|/home/educ1242/paper_speech_transcription
7663579|benchmark_wer_gpu|educ-lift|TIMEOUT|43222|2026-05-16T22:47:42|2026-05-17T10:48:04|short|billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|htc-g033|/home/educ1242/paper_speech_transcription
7670830|wer_postproc|educ-lift|CANCELLED by 8707|0|2026-05-17T23:13:53|2026-05-17T23:13:53|\
short||None assigned|/home/educ1242/paper_speech_transcription
"""
# Jobs under this project's names that ran from other directories: one of
# the workflow's transcription jobs before its evaluation, copied from the
# htc dump of 2025-01-01 to 2026-05-20, and an audit-wave name run from
# another project's directory (made up: none has run).
_ELSEWHERE = """\
6163646_1|transcription|educ-lift|FAILED|7184|2025-10-21T20:12:46|2025-10-21T22:12:30|short|billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|htc-g054|/home/educ1242/speech_transcription
8999998|au_wer|educ-intract|COMPLETED|900|2026-10-05T09:00:00|2026-10-05T09:15:00|short|billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|htc-g064|/home/educ1242/other_project_audit
"""


# The Spanish V100 control's pre-flight and full split, copied from the dump
# of 2026-10-30: named outside the audit wave's stages, run from a clone of
# their own, on the V100 PCIe cards of htc-g003 and htc-g004.
_CONTROL_ROWS = """\
9124739_2|pf_es419_v100|educ-intract|COMPLETED|592|2026-10-19T11:26:54|2026-10-19T11:36:46|short|billing=4,cpu=4,gres/gpu:v100=1,gres/gpu=1,mem=32G,node=1|htc-g003|/home/educ1242/paper_speech_transcription_ctl_es419
9124863_2|ctl_es419_v100|educ-intract|COMPLETED|3146|2026-10-19T11:28:03|2026-10-19T12:20:29|short|billing=4,cpu=4,gres/gpu:v100=1,gres/gpu=1,mem=32G,node=1|htc-g004|/home/educ1242/paper_speech_transcription_ctl_es419
"""


def _dump(tmp_path, text):
    path = tmp_path / "sacct.psv"
    path.write_text(text, encoding="utf-8")
    return path


def _without_workdir(text):
    """The same dump as sacct gives it when --format lacks WorkDir."""
    text = text.replace("|WorkDir\n", "\n")
    return "\n".join(line.rsplit("|", 1)[0] if line.count("|") == 10 else line
                     for line in text.splitlines()) + "\n"


def test_finished_jobs_that_held_an_allocation_count_whatever_their_state(tmp_path):
    rows = fp.build_ledger(fp.read_sacct(_dump(tmp_path, _HEADER + _ROWS)))
    assert [(r["job_id"], r["state"], r["gpu_type"]) for r in rows] == [
        ("7746170", "COMPLETED", "h100-nvl"),
        ("8913985", "FAILED", ""),
        # The case study's failed run drew power for 963 s and counts as
        # overhead. Its first submission, cancelled while pending, held no
        # allocation and is left out, as is the DER job still pending.
        ("8918023", "FAILED", "h100-sxm"),
        ("8976270", "COMPLETED", ""),
    ]
    params = fp.FootprintParams()
    summary = fp.summarise([fp.estimate_job(r, params) for r in rows], params)
    assert summary["overhead"]["n_jobs"] == 2
    assert summary["by_category"]["Case study"]["n_jobs"] == 1


def test_a_job_of_the_projects_directories_under_an_unknown_name_stops_the_build(tmp_path):
    sacct = fp.read_sacct(_dump(tmp_path, _HEADER + _ROWS + _UNKNOWN))
    with pytest.raises(ValueError, match=r"new_benchmark \(8999999\)"):
        fp.build_ledger(sacct)
    # An explicit selection of names is taken as given.
    assert [r["job_id"] for r in fp.build_ledger(sacct, job_names={"au_case"})] == ["8918023"]


@pytest.mark.parametrize("change", [
    # Run from another project's directory: not this project's job.
    lambda t: t.replace("/home/educ1242/paper_speech_transcription_audit\n",
                        "/home/educ1242/new_LESS\n"),
    # Still running: it will be judged once it has finished.
    lambda t: t.replace("|COMPLETED|600|", "|RUNNING|600|").replace(
        "2026-10-05T10:10:00", "Unknown"),
    # Cancelled while pending: never ran.
    lambda t: t.replace("|COMPLETED|600|", "|CANCELLED by 8707|0|").replace(
        "billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|htc-g064", "|None assigned"),
])
def test_only_a_finished_job_of_the_projects_directories_stops_it(tmp_path, change):
    sacct = fp.read_sacct(_dump(tmp_path, _HEADER + _ROWS + change(_UNKNOWN)))
    assert len(fp.build_ledger(sacct)) == 4


def test_a_dump_without_workdir_cannot_be_checked(tmp_path):
    text = _without_workdir(_HEADER + _ROWS + _UNKNOWN)
    assert len(fp.build_ledger(fp.read_sacct(_dump(tmp_path, text)))) == 4


def test_the_first_runs_of_the_wer_benchmark_count(tmp_path):
    rows = fp.build_ledger(fp.read_sacct(_dump(tmp_path, _HEADER + _FIRST_RUNS)))
    # wer_postproc never ran, so its unknown name does not stop the build.
    assert [(r["job_id"], r["state"], r["gpu_type"]) for r in rows] == [
        ("7663576", "CANCELLED", ""),
        # Twelve hours on a P100 PCIe card until the time limit stopped it.
        ("7663579", "TIMEOUT", "p100-pcie"),
    ]
    params = fp.FootprintParams()
    summary = fp.summarise([fp.estimate_job(r, params) for r in rows], params)
    assert (summary["productive"]["n_jobs"], summary["overhead"]["n_jobs"]) == (0, 2)
    assert summary["overhead"]["states"] == ["CANCELLED", "TIMEOUT"]
    assert summary["by_category"]["WER (pilot)"]["n_jobs"] == 2
    assert summary["overall"]["gpu_hours"] == pytest.approx(43222 / 3600)


def test_the_spanish_control_is_counted_at_its_cards_board(tmp_path):
    rows = fp.build_ledger(fp.read_sacct(_dump(tmp_path, _HEADER + _CONTROL_ROWS)))
    # The typed gres/gpu:v100 entry agrees with the nodes, whose logs name a
    # PCIe card, priced at 250 W, not the 300 W of the SXM2 module.
    assert [(r["job_id"], r["gpu_type"]) for r in rows] == [
        ("9124739_2", "v100-pcie"), ("9124863_2", "v100-pcie")]
    params = fp.FootprintParams()
    jobs = [fp.estimate_job(r, params) for r in rows]
    assert [j.category for j in jobs] == ["Pre-flight runs", "WER multilingual (FLEURS)"]
    assert [j.tdp_w for j in jobs] == [250.0, 250.0]


def test_jobs_of_this_projects_names_run_elsewhere_are_left_out(tmp_path):
    sacct = fp.read_sacct(_dump(tmp_path, _HEADER + _ROWS + _ELSEWHERE))
    # The probe and the diagnostic of _ROWS ran from elsewhere too, but
    # under names of _RUN_ELSEWHERE, so they still count.
    assert [r["job_id"] for r in fp.build_ledger(sacct)] == [
        "7746170", "8913985", "8918023", "8976270"]
    assert fp.left_out_elsewhere(sacct) == ["6163646_1", "8999998"]
    # Without WorkDir the names decide, and both would count.
    bare = fp.read_sacct(_dump(tmp_path, _without_workdir(_HEADER + _ROWS + _ELSEWHERE)))
    assert [r["job_id"] for r in fp.build_ledger(bare)][-2:] == ["6163646_1", "8999998"]
    assert fp.left_out_elsewhere(bare) == []


def test_cli_records_the_jobs_counted_or_left_out_for_where_they_ran(tmp_path, capsys):
    ledger = tmp_path / "arc_job_ledger.csv"
    assert fp.main(["--from-sacct", str(_dump(tmp_path, _HEADER + _ROWS + _ELSEWHERE)),
                    "--ledger", str(ledger), "--captured", "2026-10-04"]) == 0
    prov = json.loads(fp.provenance_path(ledger).read_text(encoding="utf-8"))
    assert prov["workdir_checked"] is True
    # The probe ran from the home directory and the diagnostic from
    # ~/diag_diar: both are counted by their names.
    assert prov["counted_outside_project_dirs"] == ["7746170", "8976270"]
    assert prov["left_out_outside_project_dirs"] == ["6163646_1", "8999998"]
    out = capsys.readouterr().out
    assert "7746170, 8976270" in out and "6163646_1, 8999998" in out
    assert fp.main(["--from-sacct", str(_dump(tmp_path, _HEADER + _ROWS + _UNKNOWN)),
                    "--ledger", str(ledger)]) == 2
    assert "new_benchmark" in capsys.readouterr().err


def test_jobs_that_never_ran_or_had_not_finished_are_listed(tmp_path):
    sacct = fp.read_sacct(_dump(tmp_path, _HEADER + _ROWS + _FIRST_RUNS))
    # The case study's first submission and the wer_postproc job were
    # cancelled while pending; wer_postproc is this project's by its
    # directory alone, since no rule knows its name. The DER job is pending.
    assert fp.left_out_never_allocated(sacct) == ["8917982", "7670830"]
    assert fp.left_out_never_allocated(sacct, until="2026-05-31") == ["7670830"]
    assert fp.left_out_unfinished(sacct) == ["8976354"]
    # Without WorkDir only a recognised name tells, so wer_postproc drops out.
    bare = fp.read_sacct(_dump(tmp_path, _without_workdir(_HEADER + _ROWS + _FIRST_RUNS)))
    assert fp.left_out_never_allocated(bare) == ["8917982"]
    assert fp.left_out_unfinished(bare) == ["8976354"]
    # Another project's jobs are not listed, whatever their state.
    other = _HEADER + _ROWS.replace("/home/educ1242/paper_speech_transcription_audit_w2",
                                    "/home/educ1242/new_LESS").replace(
        "au_der_default", "p1_decoding")
    assert fp.left_out_unfinished(fp.read_sacct(_dump(tmp_path, other))) == []


def test_cli_lists_the_jobs_left_out_with_the_reason(tmp_path, capsys):
    ledger = tmp_path / "arc_job_ledger.csv"
    assert fp.main(["--from-sacct", str(_dump(tmp_path, _HEADER + _ROWS + _FIRST_RUNS)),
                    "--ledger", str(ledger), "--captured", "2026-10-04"]) == 0
    prov = json.loads(fp.provenance_path(ledger).read_text(encoding="utf-8"))
    assert prov["left_out_never_allocated"] == ["8917982", "7670830"]
    assert prov["left_out_unfinished"] == ["8976354"]
    assert prov["left_out_outside_project_dirs"] == []
    # Every list of left-out jobs carries its reason.
    assert set(prov["left_out_reasons"]) == {
        key for key in prov if key.startswith("left_out_") and key != "left_out_reasons"}
    assert "cancelled while pending" in prov["left_out_reasons"]["left_out_never_allocated"]
    out = capsys.readouterr().out
    assert "8917982, 7670830" in out and "8976354" in out


def test_cli_says_when_the_names_alone_decided(tmp_path, capsys):
    ledger = tmp_path / "arc_job_ledger.csv"
    dump = _dump(tmp_path, _without_workdir(_HEADER + _ROWS + _ELSEWHERE))
    assert fp.main(["--from-sacct", str(dump), "--ledger", str(ledger)]) == 0
    prov = json.loads(fp.provenance_path(ledger).read_text(encoding="utf-8"))
    assert prov["workdir_checked"] is False
    assert prov["counted_outside_project_dirs"] is None
    assert prov["left_out_outside_project_dirs"] is None
    assert "by name alone" in prov["job_selection"]
    assert "no WorkDir column" in capsys.readouterr().out
