"""The control decode of one FLEURS split against the multilingual arms (NEW-05).

evaluation/fleurs_control.py pairs the control's per-utterance records with
each arm's, refuses arm summaries whose digest is not the one the committed
multilingual summary records, and reports whether the control reproduces
the arm it is meant to match. The summaries here are made up, three
utterances long, with the layout benchmark_wer writes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import fleurs_control as fc

_RUN = {"git_commit": "6f9bf56a0d5839920537f23d73a166dc0f1e478b", "git_dirty": False,
        "python": "3.12.12", "platform": "Linux",
        "packages": {"torch": "2.5.1+cu121", "transformers": "4.57.1"}}


def _record(name, hits, subs, cer):
    words = hits + subs
    return {"name": name, "wer": subs / words, "mer": subs / words, "wil": 0.0,
            "cer": cer, "hits": hits, "substitutions": subs, "deletions": 0,
            "insertions": 0, "reference_words": words, "hypothesis_words": words}


def _summary(records, gpu=None, run=None):
    bench = {"dataset": "google/fleurs", "config": "es_419", "split": "test",
             "model": "openai/whisper-large-v3", "utterances": len(records),
             "seed": 42, "condition": "raw", "language": "spanish"}
    if gpu is not None:
        bench["decode"] = {"device": "cuda", "dtype": "torch.float16", "gpu": gpu}
    payload = {"benchmark": bench,
               "summary": {"files": len(records),
                           "macro_wer": sum(r["wer"] for r in records) / len(records)},
               "per_file": records}
    if run is not None:
        payload["run_metadata"] = run
    return payload


# The third arm's decode, which predates the repeat suffix; the control
# writes the second "1701" as "1701__2".
_ARM3 = [_record("1700", 20, 1, 0.01), _record("1701", 30, 0, 0.0),
         _record("1701", 25, 2, 0.03)]
_CONTROL = copy.deepcopy(_ARM3)
_CONTROL[2]["name"] = "1701__2"
# The fourth arm departs from the third on the first utterance.
_ARM4 = copy.deepcopy(_CONTROL)
_ARM4[0] = _record("1700", 21, 0, 0.0)


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _setup(tmp_path, control=_CONTROL, arm4=_ARM4):
    paths = {
        "control": _write(tmp_path, "ctl.json", _summary(control, "Tesla V100-PCIE-32GB", _RUN)),
        "3_after_gate": _write(tmp_path, "wer_summary_fleurs_es_419.json", _summary(_ARM3)),
        "4_after_audit": _write(tmp_path, "wer_summary_fleurs_es_419_whisper-large-v3.json",
                                _summary(arm4, "NVIDIA L40S", _RUN)),
    }
    multilingual = {
        "benchmark": {
            "arms": {"3_after_gate": {"code": "c0f58c5", "arc_jobs": ["8245204"],
                                      "gpus": {"es_419": "Tesla V100-SXM2-32GB"}},
                     "4_after_audit": {"code": "6f9bf56", "arc_jobs": ["8917984"],
                                       "gpus": {"es_419": "NVIDIA L40S"}}},
            "inputs": [{"arm": arm, "file": paths[arm].name,
                        "sha256": hashlib.sha256(paths[arm].read_bytes()).hexdigest()}
                       for arm in ("3_after_gate", "4_after_audit")]},
        "languages": {"es_419": {"utterances": 3}}}
    arms = {k: v for k, v in paths.items() if k != "control"}
    return paths["control"], arms, multilingual


def test_a_control_with_the_targets_records_reproduces_it(tmp_path):
    control, arms, ml = _setup(tmp_path)
    result = fc.build(control, arms, "3_after_gate", ml, run_meta={})
    target = result["comparisons"]["3_after_gate"]
    assert (target["identical"], target["differing"]) == (3, 0)
    # The repeat suffix is not a difference.
    assert target["summary_identical"] is True
    # The first three arms record no decode or run metadata to compare.
    assert target["provenance_differences"] is None
    fourth = result["comparisons"]["4_after_audit"]
    assert fourth["differing"] == 1
    assert fourth["differing_utterances"][0]["uid"] == "1700"
    assert set(fourth["differing_utterances"][0]["fields"]) == {
        "wer", "mer", "cer", "hits", "substitutions"}
    assert fourth["target_differs_on_the_same_utterances"] is True
    # Code, packages and precision agree, so the card alone differs.
    assert list(fourth["provenance_differences"]) == ["benchmark/decode/gpu"]
    assert result["finding"]["reproduces_target"] is True
    assert result["finding"]["differs_from_others_where_target_does"] is True
    assert result["finding"]["transcripts_compared"] is False


def test_recordings_that_share_a_sentence_id_are_told_apart(tmp_path):
    """Positions 1 and 2 are two recordings of sentence 1701.

    The fourth arm departs from the target on the second recording and from
    the control on the first, so the two sets of differing ids are both
    {"1701"} while the recordings differ; compared by position the check
    fails, as it should.
    """
    arm4 = copy.deepcopy(_ARM3)
    arm4[2] = _record("1701", 26, 1, 0.02)
    control = copy.deepcopy(arm4)
    control[1] = _record("1701", 29, 1, 0.01)
    control[2]["name"] = "1701__2"
    control_path, arms, ml = _setup(tmp_path, control=control, arm4=arm4)
    result = fc.build(control_path, arms, "3_after_gate", ml, run_meta={})
    fourth = result["comparisons"]["4_after_audit"]
    assert [(d["position"], d["uid"]) for d in fourth["differing_utterances"]] == [(1, "1701")]
    assert fourth["target_differs_on_the_same_utterances"] is False
    assert result["finding"]["differs_from_others_where_target_does"] is False


def test_a_control_that_differs_leaves_the_attribution_open(tmp_path):
    control, arms, ml = _setup(tmp_path, control=_ARM4)
    result = fc.build(control, arms, "3_after_gate", ml, run_meta={})
    assert result["comparisons"]["3_after_gate"]["differing"] == 1
    assert result["finding"]["reproduces_target"] is False
    assert "unresolved" in result["finding"]["outcome"]


def test_an_arm_summary_other_than_the_recorded_one_is_refused(tmp_path):
    control, arms, ml = _setup(tmp_path)
    ml["benchmark"]["inputs"][0]["sha256"] = "0" * 64
    with pytest.raises(SystemExit, match="SHA-256"):
        fc.build(control, arms, "3_after_gate", ml, run_meta={})


def test_decodes_of_other_utterances_are_refused(tmp_path):
    shuffled = [_CONTROL[1], _CONTROL[0], _CONTROL[2]]
    control, arms, ml = _setup(tmp_path, control=shuffled)
    with pytest.raises(SystemExit, match="streamed different orders"):
        fc.build(control, arms, "3_after_gate", ml, run_meta={})
    with pytest.raises(SystemExit, match="utterances"):
        fc.compare_records(_CONTROL, _CONTROL[:2])


def test_an_unknown_target_is_refused(tmp_path):
    control, arms, ml = _setup(tmp_path)
    with pytest.raises(SystemExit, match="--target"):
        fc.build(control, arms, "2_after_fix", ml, run_meta={})


def test_the_environment_record_is_read(tmp_path):
    record = (
        "# Environment record written by hpc/common/arc_common.sh\n"
        "date:            2026-10-19T11:31:49+0100\nhost:            htc-g004\n"
        "slurm_job_id:    9124863\nslurm_account:   <project-b>\n"
        "git_commit:      6f9bf56a0d5839920537f23d73a166dc0f1e478b\n"
        "git_modified_tracked_files: 0\n\n## Loaded modules\n\n"
        "Currently Loaded Modules:\n  1) Anaconda3/2025.06-1   2) CUDA/13.0.2\n\n"
        "## GPU\nTesla V100-PCIE-32GB, 580.65.06, 32768 MiB\nMon Oct 19\n\n"
        "## pip list --format=freeze\ntorch==2.5.1+cu121\naccelerate==1.11.0\n")
    path = tmp_path / "env.txt"
    path.write_text(record, encoding="utf-8")
    env = fc.read_environment(path)
    assert env["host"] == "htc-g004" and env["slurm_job_id"] == "9124863"
    assert env["git_modified_tracked_files"] == "0"
    assert env["gpu"] == "Tesla V100-PCIE-32GB, 580.65.06, 32768 MiB"
    assert env["modules"] == ["Anaconda3/2025.06-1", "CUDA/13.0.2"]
    assert env["packages"] == ["accelerate==1.11.0", "torch==2.5.1+cu121"]
    # Two jobs with the same packages are reported as such.
    control, arms, ml = _setup(tmp_path)
    other = tmp_path / "other.txt"
    other.write_text(record.replace("htc-g004", "htc-g081"), encoding="utf-8")
    result = fc.build(control, arms, "3_after_gate", ml,
                      environments={"control": path, "4_after_audit": other},
                      run_meta={})
    assert result["jobs"]["4_after_audit"]["packages_identical_to_control"] is True
    assert result["jobs"]["control"]["n_packages"] == 2
    assert "packages" not in result["jobs"]["control"]


def test_the_committed_control_record_is_consistent():
    """The committed record says what its comparisons show."""
    path = PROJECT_ROOT / "output" / "evaluation" / "fleurs_es419_v100_control.json"
    if not path.exists():
        pytest.skip("no committed control record")
    record = json.loads(path.read_text(encoding="utf-8"))
    target = record["comparisons"][record["target"]]
    assert record["finding"]["reproduces_target"] == (
        target["differing"] == 0 and target["summary_identical"])
    for cmp in record["comparisons"].values():
        assert cmp["identical"] + cmp["differing"] == cmp["utterances_compared"]
        assert cmp["differing"] == len(cmp["differing_utterances"])
    # A control equal to the target at every position differs from each
    # other arm at the positions the target does, so the check by position
    # (release 2.1.1) cannot reverse the committed record's by-id result.
    if target["differing"] == 0:
        assert all(cmp["target_differs_on_the_same_utterances"]
                   for arm, cmp in record["comparisons"].items() if arm != record["target"])
    ml = json.loads((path.parent / "fleurs_multilingual_summary.json").read_text(
        encoding="utf-8"))
    recorded = {(i["arm"], i["file"]): i["sha256"] for i in ml["benchmark"]["inputs"]}
    for item in record["inputs"]:
        if item["role"] == "arm":
            assert recorded[(item["arm"], item["file"])] == item["sha256"]
