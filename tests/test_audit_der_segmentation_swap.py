"""--segmentation-model must change the model the pipeline segments with.

In pyannote.audio 3.4.0 ``SpeakerDiarization.segmentation_model`` holds the
string it was built from and is never read again; segmentation runs
through ``_segmentation``, an ``Inference`` built from the released model.
Pipeline.__setattr__ files any nn.Module assigned to an attribute in a
model registry, so assigning the fine-tuned model to
``segmentation_model`` changed nothing and the benchmark scored the
released model under the checkpoint's name (DER-1).

pyannote is not installed on every test host, so a stand-in module is
put in ``sys.modules``. Its ``Pipeline.__setattr__``/``__getattr__`` repeat
pyannote.audio 3.4.0's (core/pipeline.py), its pipeline builds
``_segmentation`` as SpeakerDiarization.__init__ does, and its
``Inference`` keeps the constructor arguments for inspection.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
nn = torch.nn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation import benchmark_der as bd


class _Spec(types.SimpleNamespace):
    """The Specifications fields the pipeline and Inference read."""


class _FakeModel(nn.Module):
    def __init__(self, tag, powerset=True, resolution="frame", duration=10.0):
        super().__init__()
        self.tag = tag
        self.specifications = _Spec(powerset=powerset, resolution=resolution,
                                    duration=duration)


class _BaseInference:
    pass


class _Inference(_BaseInference):
    def __init__(self, model, duration=None, step=None, skip_aggregation=False,
                 batch_size=32, device=None, **kwargs):
        self.model = model
        self.duration = duration
        self.step = step
        self.skip_aggregation = skip_aggregation
        self.batch_size = batch_size
        self.device = device
        self.extra = kwargs

    def to(self, device):
        self.device = device
        return self


class _Pipeline:
    """pyannote.audio 3.4.0 Pipeline attribute semantics, nothing more."""

    def __init__(self):
        object.__setattr__(self, "_models", {})
        object.__setattr__(self, "_inferences", {})

    def __getattr__(self, name):
        d = self.__dict__
        if name in d.get("_models", {}):
            return d["_models"][name]
        if name in d.get("_inferences", {}):
            return d["_inferences"][name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        def remove_from(*dicts):
            for dd in dicts:
                dd.pop(name, None)

        if isinstance(value, nn.Module):
            remove_from(self.__dict__, self._inferences)
            self._models[name] = value
            return
        if isinstance(value, _BaseInference):
            remove_from(self.__dict__, self._models)
            self._inferences[name] = value
            return
        object.__setattr__(self, name, value)

    def to(self, device):
        for inference in self._inferences.values():
            inference.to(device)
        return self


class _SpeakerDiarization(_Pipeline):
    """The parts of SpeakerDiarization.__init__ that matter here (l. 129-149)."""

    def __init__(self, released):
        super().__init__()
        self.segmentation_model = "pyannote/segmentation-3.0"
        self.segmentation_step = 0.1
        duration = released.specifications.duration
        self._segmentation = _Inference(
            released, duration=duration, step=self.segmentation_step * duration,
            skip_aggregation=True, batch_size=32)


@pytest.fixture
def fake_pyannote(monkeypatch, tmp_path):
    state = {"released": _FakeModel("released"),
             "fine_tuned": _FakeModel("fine-tuned"),
             "loaded_with": None}

    class Pipeline:
        @staticmethod
        def from_pretrained(model_id, use_auth_token=None):
            state["pipe"] = _SpeakerDiarization(state["released"])
            return state["pipe"]

    class Model:
        @staticmethod
        def from_pretrained(checkpoint, map_location=None, **kwargs):
            state["loaded_with"] = (checkpoint, map_location)
            return state["fine_tuned"]

    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline, audio.Model, audio.Inference = Pipeline, Model, _Inference
    audio.__version__ = "3.4.0"
    package = types.ModuleType("pyannote")
    package.audio = audio
    monkeypatch.setitem(sys.modules, "pyannote", package)
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)

    ckpt = tmp_path / "segmentation-ami-best.ckpt"
    ckpt.write_bytes(b"not read by the stand-in")
    state["ckpt"] = str(ckpt)
    return state


def test_the_pipeline_segments_with_the_checkpoint(fake_pyannote):
    pipe = bd.load_pipeline(segmentation_model=fake_pyannote["ckpt"])
    inference = pipe._segmentation
    assert inference.model is fake_pyannote["fine_tuned"]
    # Built as the pipeline's constructor builds it.
    assert inference.duration == 10.0
    assert inference.step == pytest.approx(1.0)
    assert inference.skip_aggregation is True
    assert inference.batch_size == 32
    # The attribute the old code assigned is still the unused spec string.
    assert pipe.segmentation_model == "pyannote/segmentation-3.0"
    assert fake_pyannote["loaded_with"][0] == fake_pyannote["ckpt"]


def test_assigning_segmentation_model_is_the_no_op_it_was(fake_pyannote):
    """Pins the stand-in's semantics: the old assignment left the weights."""
    pipe = _SpeakerDiarization(fake_pyannote["released"])
    pipe.segmentation_model = fake_pyannote["fine_tuned"]
    assert pipe._segmentation.model is fake_pyannote["released"]


def test_a_checkpoint_with_another_chunk_duration_gets_its_own_windows(
        fake_pyannote):
    fake_pyannote["fine_tuned"] = _FakeModel("fine-tuned", duration=5.0)
    pipe = bd.load_pipeline(segmentation_model=fake_pyannote["ckpt"])
    assert pipe._segmentation.duration == 5.0
    assert pipe._segmentation.step == pytest.approx(0.5)


@pytest.mark.parametrize("change", [{"powerset": False},
                                    {"resolution": "chunk"}])
def test_a_checkpoint_of_another_kind_is_refused(fake_pyannote, change):
    fake_pyannote["fine_tuned"] = _FakeModel("other", **change)
    with pytest.raises(SystemExit, match="kind of output"):
        bd.load_pipeline(segmentation_model=fake_pyannote["ckpt"])


def test_an_unloadable_checkpoint_is_refused(fake_pyannote):
    fake_pyannote["fine_tuned"] = None
    with pytest.raises(SystemExit, match="could not load"):
        bd.load_pipeline(segmentation_model=fake_pyannote["ckpt"])


def test_a_pipeline_without_a_segmentation_inference_is_refused(
        fake_pyannote, monkeypatch):
    pipe = _Pipeline()
    monkeypatch.setattr(sys.modules["pyannote.audio"].Pipeline,
                        "from_pretrained",
                        staticmethod(lambda model_id, use_auth_token=None: pipe))
    with pytest.raises(SystemExit, match="segmentation inference"):
        bd.load_pipeline(segmentation_model=fake_pyannote["ckpt"])


def test_a_swap_that_does_not_stick_is_refused(fake_pyannote, monkeypatch):
    class Stubborn(_SpeakerDiarization):
        def __setattr__(self, name, value):
            if name == "_segmentation" and "_segmentation" in self._inferences:
                return
            super().__setattr__(name, value)

    monkeypatch.setattr(
        sys.modules["pyannote.audio"].Pipeline, "from_pretrained",
        staticmethod(lambda model_id, use_auth_token=None:
                     Stubborn(fake_pyannote["released"])))
    with pytest.raises(SystemExit, match="did not take effect"):
        bd.load_pipeline(segmentation_model=fake_pyannote["ckpt"])


def test_no_checkpoint_leaves_the_released_model(fake_pyannote):
    pipe = bd.load_pipeline()
    assert pipe._segmentation.model is fake_pyannote["released"]
    assert fake_pyannote["loaded_with"] is None
