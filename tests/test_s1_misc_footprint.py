"""Stage-1 tests for the footprint ledger builder and GPU pricing.

ESTATS-13: no code built arc_job_ledger.csv from sacct. ESTATS-05: an
H100 was priced as the 700 W SXM5 module whatever its variant, and the
report did not say what each job was costed at. REGEN-07: a refresh needs
a reproducible builder. The sacct excerpt below is copied from a
2026-09-26 dump, with one row of another project's job added.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import footprint as fp

_SACCT = """\
JobID|JobName|Account|State|ElapsedRaw|Start|End|Partition|AllocTRES|NodeList
7721017|pilot_benchmark_wer|educ-intract|COMPLETED|761|2026-05-25T23:28:32|2026-05-25T23:41:13|short|billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|htc-g053
7725869_4|wer_sweep|educ-intract|CANCELLED by 8707|26429|2026-05-26T11:50:29|2026-05-26T19:10:58|\
short|billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|htc-g033
7729883|sweep_aggregate|educ-intract|COMPLETED|16|2026-05-27T06:02:17|2026-05-27T06:02:33|short|billing=2,cpu=2,mem=8G,node=1|htc-c068
9000001|claps_databased2|educ-intract|COMPLETED|100|2026-05-27T06:02:17|2026-05-27T06:04:17|short|billing=2,cpu=2,mem=8G,node=1|htc-c068
8554985|determinism|educ-intract|COMPLETED|789|2026-08-12T16:11:55|2026-08-12T16:25:04|short|billing=8,cpu=8,gres/gpu=1,mem=48G,node=1|htc-g058
8781723|anon_multimeeting|educ-intract|COMPLETED|1659|2026-09-12T09:13:35|2026-09-12T09:41:14|short|billing=8,cpu=8,gres/gpu=1,mem=48G,node=1|htc-g062
8800000|disfluency|educ-lift|RUNNING|120|2026-09-26T09:00:00|Unknown|short|billing=8,cpu=8,gres/gpu=1,mem=48G,node=1|htc-g070
"""


def _write(tmp_path, text=_SACCT, name="sacct.psv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_build_keeps_this_projects_finished_jobs(tmp_path):
    rows = fp.build_ledger(fp.read_sacct(_write(tmp_path)))
    assert [r["job_id"] for r in rows] == [
        "7721017", "7725869_4", "7729883", "8554985", "8781723"]
    by_id = {r["job_id"]: r for r in rows}
    assert by_id["7725869_4"]["state"] == "CANCELLED"
    assert by_id["7729883"] == {
        "job_id": "7729883", "job_name": "sweep_aggregate", "state": "COMPLETED",
        "elapsed_s": "16", "gpus": "0", "gpu_type": "", "cpus": "2", "mem_gb": "8"}
    # GPU model from the node, since AllocTRES names none on ARC; the logs of
    # htc-g053 and htc-g033 name an H100 PCIe and a P100 PCIe (NODE_GPU_VARIANT).
    assert by_id["7721017"]["gpu_type"] == "h100-pcie"
    assert by_id["7725869_4"]["gpu_type"] == "p100-pcie"
    assert by_id["8781723"]["gpu_type"] == "l40s"
    # htc-g058 is on record as an H100 NVL (determinism/gpu.txt, job 8554985).
    assert by_id["8554985"]["gpu_type"] == "h100-nvl"


def test_until_keeps_jobs_that_ended_by_that_day(tmp_path):
    rows = fp.build_ledger(fp.read_sacct(_write(tmp_path)), until="2026-06-27")
    assert [r["job_id"] for r in rows] == ["7721017", "7725869_4", "7729883"]


def test_assume_gpu_type_reproduces_the_june_ledgers_convention(tmp_path):
    rows = fp.build_ledger(fp.read_sacct(_write(tmp_path)), until="2026-06-27",
                           assume_gpu_type="a100")
    assert [r["gpu_type"] for r in rows] == ["a100", "a100", ""]


def test_a_gpu_job_on_an_unknown_node_is_refused(tmp_path):
    text = _SACCT.replace("htc-g062", "htc-g999")
    with pytest.raises(ValueError, match="htc-g999"):
        fp.build_ledger(fp.read_sacct(_write(tmp_path, text)))


def test_a_node_listing_replaces_the_built_in_map(tmp_path):
    nodes = tmp_path / "nodes.psv"
    nodes.write_text("htc-g062|Gres=gpu:l40s:4(S:0-1)\nhtc-g046|\n"
                     "htc-g053|Gres=gpu:h100:4(S:0-1)\n"
                     "htc-g033|Gres=gpu:p100:4\n", encoding="utf-8")
    listing = fp.read_node_gpus(nodes)
    assert listing == {"htc-g062": "l40s", "htc-g053": "h100", "htc-g033": "p100"}
    rows = fp.build_ledger(fp.read_sacct(_write(tmp_path)), listing)
    assert {r["job_id"]: r["gpu_type"] for r in rows}["8554985"] == "h100-nvl"


def test_missing_columns_are_refused(tmp_path):
    with pytest.raises(ValueError, match="AllocTRES"):
        fp.read_sacct(_write(tmp_path, "JobID|JobName|State|ElapsedRaw\n1|x|COMPLETED|3\n"))


@pytest.mark.parametrize("nodelist, expected", [
    ("htc-g053", ["htc-g053"]),
    ("htc-g[053-055]", ["htc-g053", "htc-g054", "htc-g055"]),
    ("htc-g[003,010-011]", ["htc-g003", "htc-g010", "htc-g011"]),
    ("htc-g003,htc-c020", ["htc-g003", "htc-c020"]),
    ("", []),
])
def test_expand_nodelist(nodelist, expected):
    assert fp.expand_nodelist(nodelist) == expected


def test_every_built_in_node_resolves_to_a_priced_model():
    resolved = {n: fp._node_model(n, fp.ARC_NODE_GPU) for n in fp.ARC_NODE_GPU}
    assert set(resolved.values()) <= set(fp.GPU_TDP_W)
    assert "h100" not in fp.GPU_TDP_W and fp.GPU_TDP_W["h100-nvl"] == 400.0


def test_a_bare_h100_needs_an_explicit_wattage():
    row = {"job_id": "1", "job_name": "wer_sweep", "state": "COMPLETED",
           "elapsed_s": "3600", "gpus": "1", "gpu_type": "h100", "cpus": "4",
           "mem_gb": "32"}
    with pytest.raises(ValueError, match="--gpu-tdp"):
        fp.estimate_job(row, fp.FootprintParams())
    params = fp.FootprintParams(gpu_tdp_w={**fp.GPU_TDP_W, "h100": 350.0})
    job = fp.estimate_job(row, params)
    assert (job.gpu_type, job.tdp_w) == ("h100", 350.0)


def test_the_report_names_each_jobs_model_and_wattage(tmp_path):
    rows = fp.build_ledger(fp.read_sacct(_write(tmp_path)))
    jobs = [fp.estimate_job(r, fp.FootprintParams(
        gpu_tdp_w={**fp.GPU_TDP_W, "h100": 700.0})) for r in rows]
    out = tmp_path / "report.csv"
    fp.write_csv(jobs, out)
    report = {r["job_id"]: r for r in csv.DictReader(io.StringIO(
        out.read_text(encoding="utf-8")))}
    assert (report["8554985"]["gpu_type"], report["8554985"]["tdp_w"]) == ("h100-nvl", "400")
    assert (report["7729883"]["gpu_type"], report["7729883"]["tdp_w"]) == ("", "0")


def test_cli_writes_the_ledger_and_its_provenance(tmp_path):
    ledger = tmp_path / "arc_job_ledger.csv"
    code = fp.main(["--from-sacct", str(_write(tmp_path)), "--ledger", str(ledger),
                    "--captured", "2026-09-26", "--until", "2026-06-27"])
    assert code == 0
    assert ledger.read_bytes().count(b"\r") == 0
    prov = json.loads(fp.provenance_path(ledger).read_text(encoding="utf-8"))
    assert prov["captured"] == "2026-09-26" and prov["until"] == "2026-06-27"
    assert len(prov["sacct_sha256"]) == 64
    # Every node in the fixture now resolves to a priced variant, so the
    # estimate runs without --gpu-tdp and carries the ledger's provenance.
    out = tmp_path / "out"
    assert fp.main(["--ledger", str(ledger), "--output-dir", str(out)]) == 0
    summary = json.loads((out / "footprint_summary.json").read_text(encoding="utf-8"))
    assert summary["provenance"]["sacct_sha256"] == prov["sacct_sha256"]


def test_a_committed_raw_dump_rebuilds_the_committed_ledger():
    """Once the raw dump is committed beside the ledger, the ledger must
    follow from it byte for byte, built with the --until and --assume-gpu-type
    its provenance records (without one, those of the June ledger)."""
    evaluation = PROJECT_ROOT / "output" / "evaluation"
    dumps = sorted(evaluation.glob("*sacct*.psv"))
    if not dumps:
        pytest.skip("no raw sacct dump committed under output/evaluation")
    committed = (evaluation / "arc_job_ledger.csv").read_bytes().replace(b"\r\n", b"\n")
    prov_path = fp.provenance_path(evaluation / "arc_job_ledger.csv")
    if prov_path.exists():
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
        nodes = (fp.read_node_gpus(evaluation / prov["nodes_file"])
                 if prov.get("nodes_file") else None)
        rows = fp.build_ledger(fp.read_sacct(evaluation / prov["sacct_file"]),
                               nodes, until=prov.get("until"),
                               assume_gpu_type=prov.get("assume_gpu_type"))
    else:
        rows = fp.build_ledger(fp.read_sacct(dumps[-1]), until="2026-06-27",
                               assume_gpu_type="a100")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fp.LEDGER_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    assert buffer.getvalue().encode("utf-8") == committed


# The tests below were added for the audit's re-run wave (OUTPUTS-05). They
# stand after the committed-dump test so that its skip keeps the line that
# hpc/README.md cites.

def test_every_recorded_board_refines_its_nodes_label():
    # _node_model refuses a board that does not refine its node's label,
    # which test_every_built_in_node_resolves_to_a_priced_model relies on
    # to check the two tables against each other. A bare "h100" stays
    # unpriced (the family runs from 350 W to 700 W) because every H100
    # node has a recorded board instead.
    assert set(fp.NODE_GPU_VARIANT) <= set(fp.ARC_NODE_GPU)
    for node, board in fp.NODE_GPU_VARIANT.items():
        assert fp._gres_label(board) == fp.ARC_NODE_GPU[node], node
    assert {n for n, label in fp.ARC_NODE_GPU.items() if label == "h100"} <= set(
        fp.NODE_GPU_VARIANT)


# The board of each node that a record names: the card in its jobs' logs
# (NODE_GPU_VARIANT's comment gives a job for each), or for htc-g041 to g043
# the node features. A board changed here changes the wattage of every job
# on the node, so it must come with a record.
_RECORDED_BOARDS = {
    **dict.fromkeys(["htc-g003", "htc-g004", "htc-g035"], "v100-pcie"),
    **dict.fromkeys(["htc-g037", "htc-g038"], "v100-sxm2"),
    **dict.fromkeys(["htc-g032", "htc-g033", "htc-g034"], "p100-pcie"),
    **dict.fromkeys(["htc-g015", "htc-g016"], "a100-pcie"),
    **dict.fromkeys(["htc-g041", "htc-g042", "htc-g043"], "rtx-titan"),
    **dict.fromkeys(["htc-g053", "htc-g054", "htc-g055"], "h100-pcie"),
    "htc-g058": "h100-nvl",
    **dict.fromkeys(["htc-g059", "htc-g060"], "h100-sxm"),
}


def test_each_node_takes_the_board_its_records_name():
    assert fp.NODE_GPU_VARIANT == _RECORDED_BOARDS
    # A node no record names keeps its label, priced at the family's
    # largest board: htc-g017 and g018 hold A100 40 GB cards whose form no
    # log gives, so they are costed as the 400 W SXM4 module, not 250 W.
    for node in ("htc-g017", "htc-g018"):
        model = fp._node_model(node, fp.ARC_NODE_GPU)
        assert (model, fp.GPU_TDP_W[model]) == ("a100", 400.0)


def test_board_powers_are_the_data_sheet_maxima():
    # The source of each value is cited beside GPU_TDP_W, so a change here
    # needs a new citation there.
    assert fp.GPU_TDP_W == {
        "a100": 400.0, "a100-sxm4": 400.0, "a100-pcie": 250.0,
        "p100": 300.0, "p100-pcie": 250.0,
        "v100": 300.0, "v100-pcie": 250.0, "v100-sxm2": 300.0,
        "rtx8000": 295.0, "rtx-titan": 280.0, "a6000": 300.0, "l40s": 350.0,
        "h100-nvl": 400.0, "h100-pcie": 350.0, "h100-sxm": 700.0,
    }
    # A family label is priced at its largest board, so that a job whose
    # board is not on record is never underestimated.
    for family in ("a100", "p100", "v100"):
        boards = [w for model, w in fp.GPU_TDP_W.items()
                  if fp._gres_label(model) == family]
        assert fp.GPU_TDP_W[family] == max(boards), family


# The GPU nodes of the htc short partition, where this project's jobs run
# (sinfo -M htc -h -o "%P %N", 2026-10-04).
_SHORT_PARTITION = "htc-g[003-004,012-018,032-035,037-038,041-043,050-055,058-084]"


def test_every_gpu_node_of_the_short_partition_is_mapped():
    # A job that asks for any GPU can land on any of them, so a node
    # missing here stops a capture (htc-g015 and htc-g066 did).
    nodes = fp.expand_nodelist(_SHORT_PARTITION)
    assert len(nodes) == 51
    assert [n for n in nodes if n not in fp.ARC_NODE_GPU] == []


# Three tasks of the audit's re-run wave, copied from the 2026-10-04 dump.
_AUDIT_ROWS = """\
JobID|JobName|Account|State|ElapsedRaw|Start|End|Partition|AllocTRES|NodeList|WorkDir
8917984_1|au_ml|educ-lift|COMPLETED|2645|2026-09-28T10:01:40|2026-09-28T10:45:45|short|billing=4,cpu=4,gres/gpu=1,mem=32G,node=1|htc-g015|/home/educ1242/paper_speech_transcription_audit
8917985_0|au_wer_large|educ-intract|COMPLETED|5213|2026-09-28T10:20:55|2026-09-28T11:47:48|short|billing=4,cpu=4,gres/gpu:v100=1,gres/gpu=1,mem=32G,node=1|htc-g003|/home/educ1242/paper_speech_transcription_audit
8917987_1|au_wer_dis|educ-intract|COMPLETED|1163|2026-09-28T10:02:48|2026-09-28T10:22:11|short|billing=4,cpu=4,gres/gpu:l40s=1,gres/gpu=1,mem=32G,node=1|htc-g066|/home/educ1242/paper_speech_transcription_audit
"""
_AUDIT_NAMES = {"au_ml", "au_wer_large", "au_wer_dis"}


def _audit_types(tmp_path, text=_AUDIT_ROWS, nodes=None):
    rows = fp.build_ledger(fp.read_sacct(_write(tmp_path, text)), nodes,
                           job_names=_AUDIT_NAMES)
    return {r["job_id"]: r["gpu_type"] for r in rows}


def test_the_audit_jobs_are_priced_at_their_nodes_boards(tmp_path):
    assert _audit_types(tmp_path) == {
        # htc-g015 was missing from the 2026-09-26 listing; its job log
        # names an NVIDIA A100-PCIE-40GB.
        "8917984_1": "a100-pcie",
        # The typed entry says only "v100"; the node's logs name a PCIe
        # card, which the label alone would price as the 300 W SXM2 module.
        "8917985_0": "v100-pcie",
        # htc-g066 was missing too; the typed label agrees with it.
        "8917987_1": "l40s",
    }


def test_a_typed_allocation_stands_alone_only_on_an_unknown_node(tmp_path):
    text = _AUDIT_ROWS.replace("htc-g066", "htc-g999")
    assert _audit_types(tmp_path, text)["8917987_1"] == "l40s"
    # Without a typed entry an unknown node is still refused.
    with pytest.raises(ValueError, match="htc-g999"):
        _audit_types(tmp_path, _AUDIT_ROWS.replace("htc-g015", "htc-g999"))


def test_a_typed_allocation_that_contradicts_its_node_is_refused(tmp_path):
    text = _AUDIT_ROWS.replace("l40s=1,gres/gpu=1,mem=32G,node=1|htc-g066",
                               "l40s=1,gres/gpu=1,mem=32G,node=1|htc-g003")
    with pytest.raises(ValueError, match="AllocTRES names a 'l40s' GPU"):
        _audit_types(tmp_path, text)


def test_a_listing_that_contradicts_a_recorded_board_is_refused(tmp_path):
    # A node refitted since NODE_GPU_VARIANT was written must not keep
    # its old board's wattage.
    listing = {"htc-g003": "l40s", "htc-g015": "a100", "htc-g066": "l40s"}
    with pytest.raises(ValueError, match="NODE_GPU_VARIANT"):
        _audit_types(tmp_path, nodes=listing)


def test_an_sinfo_node_listing_is_read_as_it_stands(tmp_path):
    path = tmp_path / "nodes.txt"
    path.write_text("CLUSTER: htc\nNODELIST GRES\nhtc-c005 (null)\n"
                    "htc-g003 gpu:v100:2(S:0-1)\nhtc-g032 gpu:p100:4\n"
                    "htc-g041 gpu:rtx:4(S:0-1)\nhtc-g066 gpu:l40s:4(S:0-1)\n",
                    encoding="utf-8")
    assert fp.read_node_gpus(path) == {
        "htc-g003": "v100", "htc-g032": "p100", "htc-g041": "rtx",
        "htc-g066": "l40s"}
