"""The fine-tuning script's corpus, split, seed and pyannote calls.

Nothing here has produced a reported number, but each defect would have
cost a GPU run or trained on the wrong corpus: Phase 2 called APIs
pyannote.audio 3.4 does not have, a pilot's truncated meetings were reused
by a full run, the dev set shared speakers with training, the run was
unseeded, and the HF token could be passed on the command line. The
pyannote and Lightning objects are fakes with the 3.4.0 signatures (read
from the ARC install), so the tests run without either package.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("soundfile")

from evaluation import finetune_pyannote_segmentation as ft  # noqa: E402


def _files(*uris):
    return [{"uri": u} for u in uris]


# ---------------------------------------------------------------------------
# Series-disjoint development split
# ---------------------------------------------------------------------------

class TestSeriesSplit:
    def test_the_series_drops_only_the_session_letter(self):
        assert ft._series_of("ES2002a") == "ES2002"
        assert ft._series_of("EN2001e") == "EN2001"
        assert ft._series_of("IB4001") == "IB4001"

    def test_no_series_is_in_both_sets(self):
        uris = [f"S{s}{c}" for s in range(1, 6) for c in "abcd"]
        train, dev = ft._split_by_series(_files(*uris), 0.1)
        train_series = {ft._series_of(f["uri"]) for f in train}
        dev_series = {ft._series_of(f["uri"]) for f in dev}
        assert not train_series & dev_series
        assert len(train) + len(dev) == len(uris)

    def test_the_old_boundary_case_keeps_a_series_whole(self):
        """First tenth of 20 sorted ids is two meetings, mid-series."""
        uris = [f"S{s}{c}" for s in range(1, 6) for c in "abcd"]
        _, dev = ft._split_by_series(_files(*uris), 0.1)
        assert [f["uri"] for f in dev] == ["S1a", "S1b", "S1c", "S1d"]

    def test_the_split_is_independent_of_input_order(self):
        uris = ["B1a", "A1a", "A1b", "C1a", "B1b"]
        first = ft._split_by_series(_files(*uris), 0.2)
        second = ft._split_by_series(_files(*reversed(uris)), 0.2)
        assert first == second

    def test_a_single_series_leaves_nothing_to_train_on(self):
        with pytest.raises(SystemExit, match="no training"):
            ft._split_by_series(_files("S1a", "S1b"), 0.1)


# ---------------------------------------------------------------------------
# Data manifest
# ---------------------------------------------------------------------------

SR = ft._SR


def _stream(n_meetings=4):
    rows = []
    for m in range(n_meetings):
        mid = f"X{m}00{m}a"
        for u in range(2):
            rows.append({"meeting_id": mid, "speaker_id": f"S{u}",
                         "begin_time": float(u * 30), "end_time": float(u * 30 + 1),
                         "audio": {"array": np.full(SR, 0.1, dtype=np.float32),
                                   "sampling_rate": SR}})
    return rows


@pytest.fixture
def prep(monkeypatch):
    built = []
    real_mix = ft.mix_meeting

    def counting_mix(rows, *a, **k):
        built.append(rows[0]["meeting_id"])
        return real_mix(rows, *a, **k)

    monkeypatch.setattr(ft, "stream_ami", lambda split, token: iter(_stream()))
    monkeypatch.setattr(ft, "mix_meeting", counting_mix)
    # The real one reads the RTTM through pyannote.core.
    monkeypatch.setattr(ft, "_make_protocol_file",
                        lambda uri, wav, rttm: {"uri": uri, "audio": str(wav)})
    return built


def _run(out, **kwargs):
    kwargs.setdefault("limit_meetings", None)
    kwargs.setdefault("max_minutes", None)
    return ft._build_and_save_ami(out, None, dev_fraction=0.25, **kwargs)


def _manifest(out):
    return json.loads((out / "data_manifest.json").read_text(encoding="utf-8"))


class TestDataManifest:
    def test_the_manifest_records_the_cap_and_meetings(self, tmp_path, prep):
        _run(tmp_path, limit_meetings=2, max_minutes=5)
        manifest = _manifest(tmp_path)
        assert manifest["max_minutes"] == 5
        assert manifest["meetings"] == ["X0000a", "X1001a"]
        assert manifest["reconstruction_version"] == ft.RECONSTRUCTION_VERSION

    def test_a_full_run_refuses_a_pilots_truncated_meetings(self, tmp_path, prep):
        _run(tmp_path, limit_meetings=2, max_minutes=5)
        with pytest.raises(SystemExit, match="max_minutes 5"):
            _run(tmp_path)

    def test_audio_without_a_manifest_is_refused(self, tmp_path, prep):
        _run(tmp_path, limit_meetings=2)
        (tmp_path / "data_manifest.json").unlink()
        with pytest.raises(SystemExit, match="cap they were built with"):
            _run(tmp_path)

    def test_meetings_built_with_the_same_cap_are_reused(self, tmp_path, prep):
        _run(tmp_path, limit_meetings=2)
        assert len(prep) == 2
        train, dev = _run(tmp_path, limit_meetings=4)
        assert len(prep) == 4          # only the two new meetings were built
        assert len(train) + len(dev) == 4
        assert len(_manifest(tmp_path)["meetings"]) == 4

    def test_a_smaller_limit_uses_only_that_many_meetings(self, tmp_path, prep):
        _run(tmp_path, limit_meetings=4)
        train, dev = _run(tmp_path, limit_meetings=2)
        assert len(train) + len(dev) == 2
        assert len(_manifest(tmp_path)["meetings"]) == 4


class TestReloadFromDisk:
    def test_the_limit_is_applied(self, tmp_path, prep):
        _run(tmp_path, limit_meetings=4)
        train, dev = ft._reload_from_disk(tmp_path, 0.25, limit_meetings=2)
        assert len(train) + len(dev) == 2

    def test_a_different_cap_is_refused(self, tmp_path, prep):
        _run(tmp_path, limit_meetings=4)
        with pytest.raises(SystemExit, match="max_minutes"):
            ft._reload_from_disk(tmp_path, 0.25, max_minutes=5)

    def test_an_empty_directory_is_refused(self, tmp_path):
        with pytest.raises(SystemExit, match="skip-data-prep"):
            ft._reload_from_disk(tmp_path, 0.25)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

class TestCommandLine:
    def test_the_token_cannot_be_passed_on_the_command_line(self, capsys):
        with pytest.raises(SystemExit):
            ft._parse_args(["--hf-token", "hf_secret"])

    def test_the_seed_defaults_to_42(self):
        assert ft._parse_args([]).seed == 42

    def test_the_description_no_longer_claims_far_field_audio(self, capsys):
        with pytest.raises(SystemExit):
            ft._parse_args(["--help"])
        assert "far-field" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Phase 2 against fakes with the pyannote.audio 3.4.0 signatures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_stack(monkeypatch):
    record = {}

    class SpeakerDiarizationProtocol:
        def __init__(self, preprocessors=None):
            self.preprocessors = dict(preprocessors or {})

        def train(self):
            return iter(self.train_iter())

        def development(self):
            return iter(self.development_iter())

    class SpeakerDiarization:
        # Keyword set of pyannote.audio 3.4.0; no weight_overlap, no **kwargs.
        def __init__(self, protocol, cache=None, duration=2.0,
                     max_speakers_per_chunk=None, max_speakers_per_frame=None,
                     weigh_by_cardinality=False, warm_up=0.0, balance=None,
                     weight=None, batch_size=32, num_workers=None,
                     pin_memory=False, augmentation=None, vad_loss=None,
                     metric=None, max_num_speakers=None, loss=None):
            record["protocol"] = protocol
            record["task_caps"] = (max_speakers_per_chunk, max_speakers_per_frame)

    class Model:  # 3.4.0 has from_pretrained but no save_pretrained
        @classmethod
        def from_pretrained(cls, checkpoint, map_location=None, hparams_file=None,
                            strict=True, use_auth_token=None, cache_dir=None,
                            **kwargs):
            record["from_pretrained"] = (checkpoint, use_auth_token)
            return cls()

    class ModelCheckpoint:
        def __init__(self, dirpath, **kwargs):
            self.dirpath = dirpath
            self.best_model_path = ""

    class Trainer:
        def __init__(self, callbacks, **kwargs):
            record["trainer"] = kwargs
            self._ckpt = callbacks[0]

        def fit(self, model):
            best = Path(self._ckpt.dirpath) / "segmentation-ami-epoch=00.ckpt"
            best.write_bytes(b"weights")
            self._ckpt.best_model_path = str(best)

    pl = types.ModuleType("pytorch_lightning")
    pl.__version__ = "2.5.5"
    pl.seed_everything = lambda seed, workers=False: record.setdefault(
        "seed", (seed, workers))
    pl.callbacks = types.SimpleNamespace(
        ModelCheckpoint=ModelCheckpoint,
        LearningRateMonitor=lambda **k: object())
    pl.Trainer = Trainer

    audio = types.ModuleType("pyannote.audio")
    audio.__version__ = "3.4.0"
    audio.Model = Model
    tasks = types.ModuleType("pyannote.audio.tasks")
    tasks.SpeakerDiarization = SpeakerDiarization
    database = types.ModuleType("pyannote.database")
    protocol = types.ModuleType("pyannote.database.protocol")
    protocol.SpeakerDiarizationProtocol = SpeakerDiarizationProtocol
    pyannote = types.ModuleType("pyannote")
    pyannote.audio, pyannote.database = audio, database
    audio.tasks, database.protocol = tasks, protocol

    for name, module in {"pytorch_lightning": pl, "pyannote": pyannote,
                         "pyannote.audio": audio, "pyannote.audio.tasks": tasks,
                         "pyannote.database": database,
                         "pyannote.database.protocol": protocol}.items():
        monkeypatch.setitem(sys.modules, name, module)
    return record


class TestPhase2:
    def _run(self, tmp_path):
        train = [{"uri": "A1a", "scope": "file", "database": "AMIFinetune"}]
        dev = [{"uri": "B1a", "scope": "file", "database": "AMIFinetune"}]
        return ft._finetune(train, dev, tmp_path, "tok", epochs=1, duration=5.0,
                            seed=7, max_minutes=None, limit_meetings=2)

    def test_it_runs_against_the_3_4_signatures(self, tmp_path, fake_stack):
        exported = self._run(tmp_path)
        assert exported == tmp_path / "segmentation_model" / "segmentation-ami-best.ckpt"
        assert exported.read_bytes() == b"weights"
        # At the pinned revision, spelt as pyannote 3.x parses it (DEPS-04).
        from evaluation.revisions import revision_for
        base = "pyannote/segmentation-3.0"
        assert fake_stack["from_pretrained"] == (f"{base}@{revision_for(base)}", "tok")

    def test_the_protocol_is_a_named_pyannote_protocol(self, tmp_path, fake_stack):
        self._run(tmp_path)
        protocol = fake_stack["protocol"]
        assert protocol.name == "AMIFinetune.SpeakerDiarization.Custom"
        assert protocol.preprocessors == {}
        assert [f["uri"] for f in protocol.train()] == ["A1a"]
        assert [f["uri"] for f in protocol.development()] == ["B1a"]

    def test_the_run_is_seeded_and_deterministic_where_possible(self, tmp_path,
                                                                fake_stack):
        self._run(tmp_path)
        assert fake_stack["seed"] == (7, True)
        assert fake_stack["trainer"]["deterministic"] == "warn"

    def test_the_provenance_records_what_rebuilds_the_run(self, tmp_path, fake_stack):
        exported = self._run(tmp_path)
        prov = json.loads((exported.parent / "finetune_provenance.json")
                          .read_text(encoding="utf-8"))
        assert prov["seed"] == 7
        assert prov["train_meetings"] == ["A1a"] and prov["dev_meetings"] == ["B1a"]
        assert (prov["max_speakers_per_chunk"], prov["max_speakers_per_frame"]) == (3, 2)
        assert prov["limit_meetings"] == 2 and prov["max_minutes"] is None
        assert prov["versions"]["pyannote_audio"] == "3.4.0"
        assert prov["exported_checkpoint"] == str(exported)
        assert fake_stack["task_caps"] == (3, 2)
