"""Where and in what precision the WER benchmark decodes.

The determinism job's CPU arm runs the same decode on a processor, so the
benchmark has to put the model there on request, in float32, seeded as on a
GPU, and has to leave the GPU path exactly as the committed results ran it:
the pipeline called with no dtype, which loads the checkpoint's own.

No audio, model or network: the corpus, the ASR pipeline and the scorer are
stubbed, and transformers is replaced by a module that records the call.
"""

from __future__ import annotations

import json
import random
import sys
import types

import pytest

np = pytest.importorskip("numpy")

from evaluation import benchmark_wer as b
from evaluation import wer


# ---------------------------------------------------------------------------
# Resolving the device and the precision
# ---------------------------------------------------------------------------

def test_auto_and_none_keep_the_committed_device_choice(monkeypatch):
    for seen in ("cuda", "cpu"):
        monkeypatch.setattr(b, "_device", lambda seen=seen: seen)
        assert b._resolve_device(None) == seen
        assert b._resolve_device("auto") == seen


def test_cpu_is_honoured_on_a_gpu_node(monkeypatch):
    """A CPU job placed on a GPU node must not decode on that node's GPU."""
    monkeypatch.setattr(b, "_device", lambda: "cuda")
    assert b._resolve_device("cpu") == "cpu"


def test_cuda_never_falls_back_to_the_processor(monkeypatch):
    monkeypatch.setattr(b, "_device", lambda: "cpu")
    with pytest.raises(SystemExit, match="no GPU"):
        b._resolve_device("cuda")
    monkeypatch.setattr(b, "_device", lambda: "cuda")
    assert b._resolve_device("cuda") == "cuda"


def test_an_unknown_device_or_dtype_is_refused():
    with pytest.raises(ValueError, match="device"):
        b._resolve_device("tpu")
    with pytest.raises(ValueError, match="dtype"):
        b._resolve_dtype("float64", "cpu")


def test_the_default_precision_depends_on_the_device():
    # The GPU default is the checkpoint's dtype, as every committed GPU
    # result decoded; a processor decodes in float32, as transcription.py.
    assert b._resolve_dtype(None, "cuda") == "auto"
    assert b._resolve_dtype(None, "cpu") == "float32"
    # An explicit value wins on either device.
    assert b._resolve_dtype("float32", "cuda") == "float32"
    assert b._resolve_dtype("auto", "cpu") == "auto"


# ---------------------------------------------------------------------------
# The pipeline call
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_transformers(monkeypatch):
    captured: dict = {}
    fake = types.ModuleType("transformers")
    fake.pipeline = lambda *args, **kwargs: captured.update(kwargs) or "asr"
    monkeypatch.setitem(sys.modules, "transformers", fake)
    return captured


def test_the_gpu_call_passes_no_dtype(monkeypatch, fake_transformers):
    """The default GPU call is the one behind the committed results."""
    monkeypatch.setattr(b, "_device", lambda: "cuda")
    for dtype in (None, "auto"):
        fake_transformers.clear()
        assert b._build_asr_pipeline("openai/whisper-large-v3",
                                     device="cuda", dtype=dtype) == "asr"
        assert fake_transformers["device"] == "cuda"
        assert "dtype" not in fake_transformers
        assert "torch_dtype" not in fake_transformers
    fake_transformers.clear()
    b._build_asr_pipeline("openai/whisper-large-v3")
    assert fake_transformers["device"] == "cuda"
    assert "dtype" not in fake_transformers


def test_the_cpu_call_asks_for_float32(fake_transformers):
    torch = pytest.importorskip("torch")
    b._build_asr_pipeline("openai/whisper-large-v3", device="cpu",
                          dtype="float32")
    assert fake_transformers["device"] == "cpu"
    assert fake_transformers["dtype"] is torch.float32
    # Everything else is the GPU call's.
    assert fake_transformers["return_timestamps"] is True
    assert fake_transformers["generate_kwargs"] == {"language": "english",
                                                    "task": "transcribe"}


# ---------------------------------------------------------------------------
# A run on the processor
# ---------------------------------------------------------------------------

def _fake_metrics(ref: str, hyp: str) -> dict:
    r, h = ref.split(), hyp.split()
    errors = sum(1 for x, y in zip(r, h, strict=False) if x != y) + abs(len(r) - len(h))
    return {"wer": errors / len(r), "mer": 0.0, "wil": 0.0, "cer": 0.0,
            "hits": len(r) - errors, "substitutions": errors, "deletions": 0,
            "insertions": 0, "reference_words": len(r),
            "hypothesis_words": len(h)}


@pytest.fixture()
def stubbed_run(monkeypatch):
    events: list = []

    def fake_iter(dataset_name, config, split, limit, ref_field=None,
                  uid_field=None):
        yield "u1", np.zeros(10, dtype="float32"), 16_000, "hello world"

    def fake_build(model_id, language="english", device=None, dtype=None):
        events.append(("build", device, dtype))
        return lambda audio: {"text": "hello world"}

    monkeypatch.setattr(b, "_iter_samples", fake_iter)
    monkeypatch.setattr(b, "_apply_seed", lambda seed: events.append(("seed", seed)))
    monkeypatch.setattr(b, "_build_asr_pipeline", fake_build)
    monkeypatch.setattr(wer, "compute_metrics", _fake_metrics)
    monkeypatch.setattr(wer, "require_jiwer", lambda: None)
    return events


def _summary(tmp_path):
    return json.loads((tmp_path / "wer_summary.json").read_text("utf-8"))


def test_a_cpu_run_on_a_gpu_node_decodes_on_the_processor(
        stubbed_run, monkeypatch, tmp_path):
    monkeypatch.setattr(b, "_device", lambda: "cuda")
    runs = b._build_runs(["raw"], tmp_path / "wer_report.csv",
                         tmp_path / "wer_summary.json")
    b.run_benchmark("d", "c", "s", "m", None, runs, seed=1, device="cpu")
    # Seeded first, with the requested seed, exactly as on a GPU.
    assert stubbed_run == [("seed", 1), ("build", "cpu", "float32")]
    decode = _summary(tmp_path)["benchmark"]["decode"]
    assert decode["device"] == "cpu"
    assert decode["dtype_requested"] == "float32"
    assert decode["gpu"] is None
    assert {"cpu", "torch_threads"} <= set(decode)


def test_the_default_run_keeps_the_gpu_path(stubbed_run, monkeypatch, tmp_path):
    monkeypatch.setattr(b, "_device", lambda: "cuda")
    runs = b._build_runs(["raw"], tmp_path / "wer_report.csv",
                         tmp_path / "wer_summary.json")
    b.run_benchmark("d", "c", "s", "m", None, runs, seed=0)
    assert stubbed_run == [("seed", 0), ("build", "cuda", "auto")]
    decode = _summary(tmp_path)["benchmark"]["decode"]
    assert decode["device"] == "cuda"
    assert decode["dtype_requested"] == "auto"


def test_cuda_without_a_gpu_stops_before_the_model_loads(
        stubbed_run, monkeypatch, tmp_path):
    monkeypatch.setattr(b, "_device", lambda: "cpu")
    runs = b._build_runs(["raw"], tmp_path / "wer_report.csv",
                         tmp_path / "wer_summary.json")
    with pytest.raises(SystemExit):
        b.run_benchmark("d", "c", "s", "m", None, runs, device="cuda")
    assert stubbed_run == []
    assert not (tmp_path / "wer_summary.json").exists()


def test_the_command_line_passes_device_and_dtype(monkeypatch, tmp_path):
    captured: dict = {}
    monkeypatch.setattr(b, "run_benchmark", lambda **kw: captured.update(kw))
    b.main(["--suite", "ami", "--limit", "2", "--device", "cpu", "--dtype",
            "float32", "--report", str(tmp_path / "r.csv"),
            "--summary", str(tmp_path / "s.json")])
    assert captured["device"] == "cpu" and captured["dtype"] == "float32"
    captured.clear()
    b.main(["--report", str(tmp_path / "r.csv"), "--summary",
            str(tmp_path / "s.json")])
    assert captured["device"] == "auto" and captured["dtype"] is None
    with pytest.raises(SystemExit):
        b.main(["--device", "tpu", "--report", "r.csv", "--summary", "s.json"])


# ---------------------------------------------------------------------------
# The seeding itself runs on a machine without CUDA
# ---------------------------------------------------------------------------

def test_seeding_runs_on_a_processor_and_repeats(monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.delenv("CUBLAS_WORKSPACE_CONFIG", raising=False)
    saved = (random.getstate(), np.random.get_state(), torch.get_rng_state(),
             torch.backends.cudnn.deterministic, torch.backends.cudnn.benchmark)
    try:
        b._apply_seed(7)
        first = (random.random(), np.random.rand(), torch.rand(1).item())
        b._apply_seed(7)
        assert (random.random(), np.random.rand(), torch.rand(1).item()) == first
    finally:
        random.setstate(saved[0])
        np.random.set_state(saved[1])
        torch.set_rng_state(saved[2])
        torch.backends.cudnn.deterministic = saved[3]
        torch.backends.cudnn.benchmark = saved[4]


def test_the_decode_record_names_the_processor_and_threads():
    model = types.SimpleNamespace(dtype="torch.float32",
                                  config=types.SimpleNamespace(_commit_hash="abc"))
    env = b._decode_environment(types.SimpleNamespace(model=model),
                                device="cpu", dtype_requested="float32")
    assert env["device"] == "cpu" and env["gpu"] is None
    assert env["dtype"] == "torch.float32" and env["model_commit"] == "abc"
    assert env["cpu"] is None or isinstance(env["cpu"], str)
    if b._HAS_TORCH:
        assert isinstance(env["torch_threads"], int) and env["torch_threads"] >= 1
