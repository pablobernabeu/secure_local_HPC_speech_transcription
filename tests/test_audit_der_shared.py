"""The DER entry points share one copy of each AMI helper and constant.

Copies drift: a decoding or token fix applied to one of them leaves the
fine-tuning audio built one way and the benchmark audio another, and a
collar corrected in one entry point leaves development sweeps scored
under a different collar from test-split reports. These tests pin the
single definitions. They need no pyannote, datasets or network.
"""

from __future__ import annotations

import inspect
import io
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation import ami_meetings as am  # noqa: E402
from evaluation import benchmark_der as bd  # noqa: E402
from evaluation import der_metrics as dm  # noqa: E402
from evaluation import sweep_der as sd  # noqa: E402


class TestOneCopyOfEachHelper:
    def test_the_benchmark_reexports_the_shared_helpers(self):
        # benchmark_anonymisation imports these names from benchmark_der.
        assert bd._decode_audio_bytes is am.decode_audio_bytes
        assert bd._load_hf_token is am.load_hf_token
        assert bd._stream_ami is am.stream_ami

    def test_the_dataset_ids_come_from_the_reconstruction_module(self):
        assert bd._AMI_DATASET == am.AMI_DATASET == "edinburghcstr/ami"
        assert bd._AMI_CONFIG == am.AMI_CONFIG == "ihm"

    def test_the_utterance_cap_has_one_default(self):
        default = inspect.signature(am.concat_meeting).parameters[
            "max_utterances"].default
        assert default == am.DEFAULT_UTTERANCES_PER_MEETING
        assert bd._DEFAULT_UTT_PER_MEETING == am.DEFAULT_UTTERANCES_PER_MEETING


class TestOneCollar:
    def test_every_entry_point_defaults_to_the_same_collar(self):
        assert dm.DEFAULT_COLLAR_S == 0.25
        assert bd._COLLAR == dm.DEFAULT_COLLAR_S
        assert inspect.signature(dm.compute_der).parameters[
            "collar"].default == dm.DEFAULT_COLLAR_S
        assert inspect.signature(sd.run_sweep).parameters[
            "collar"].default == dm.DEFAULT_COLLAR_S
        assert sd._parse_args([]).collar == dm.DEFAULT_COLLAR_S
        assert bd._parse_args([]).collar == dm.DEFAULT_COLLAR_S


class TestSweepAxesFollowTheTunableTable:
    def test_the_axes_are_the_benchmark_tunables_in_order(self):
        assert list(bd._TUNABLE) == sd._AXES
        assert sd._SUMMARY_FIELDS[1:4] == list(bd._TUNABLE)
        assert sd._SWEEP_FIELDS[1:4] == list(bd._TUNABLE)

    def test_the_default_cell_has_every_axis(self):
        cells = sd._grid([0.6], [None], [None])
        assert set(cells[0]) == set(bd._TUNABLE)


class TestDecodeAudioBytes:
    def test_a_decoded_array_passes_through(self):
        arr, sr = am.decode_audio_bytes({"array": [0.0, 0.5], "sampling_rate": 8000})
        assert sr == 8000
        assert arr.dtype == np.float32

    def test_encoded_bytes_are_read_with_soundfile(self):
        sf = pytest.importorskip("soundfile")
        buf = io.BytesIO()
        sf.write(buf, np.zeros(160, dtype=np.float32), 16000, format="WAV")
        arr, sr = am.decode_audio_bytes({"bytes": buf.getvalue(), "path": None})
        assert sr == 16000
        assert arr.shape == (160,)

    def test_an_undecodable_field_raises(self):
        with pytest.raises(ValueError, match="cannot decode"):
            am.decode_audio_bytes({"path": "x"})


class TestLoadHfToken:
    def test_the_environment_wins(self, monkeypatch):
        monkeypatch.setenv("HF_TOKEN", "from-env")
        assert am.load_hf_token() == "from-env"

    def test_the_fallback_variable_is_read(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        monkeypatch.setenv("HUGGINGFACE_TOKEN", "fallback")
        assert am.load_hf_token() == "fallback"


class TestNoBlanketWarningsFilter:
    """Importing a DER module must not silence pyannote's warnings."""

    def test_importing_the_der_modules_leaves_warnings_visible(self):
        # A fresh interpreter, because this process has already imported
        # the modules and pytest manages its own filters.
        import subprocess

        code = (
            "import warnings\n"
            "before = list(warnings.filters)\n"
            "import evaluation.benchmark_der, evaluation.sweep_der\n"
            "import evaluation.finetune_pyannote_segmentation\n"
            "added = [f for f in warnings.filters if f not in before]\n"
            # A blanket filter: no message, no module, every category.
            # (Libraries add targeted ones, e.g. numpy's 'size changed'.)
            "print(any(f[0] == 'ignore' and f[1] is None and f[2] is Warning\n"
            "          and f[3] is None for f in added))\n"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "False"
