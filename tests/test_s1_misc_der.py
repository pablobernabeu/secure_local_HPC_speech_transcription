"""Stage-1 tests for the DER helpers that need no pyannote (EDER-02, EDER-01).

pyannote.core is not installed everywhere the suite runs, so the
track-assignment fix is checked here against a minimal stand-in that
records exactly what is written to it: ``annotation[segment] = label``
and ``annotation[segment, track] = label``, with pyannote.core 5.0's rule
that a bare segment key means track ``'_'``. The real-library behaviour is
covered by tests/test_der_metrics.py where pyannote is installed.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _Segment(tuple):
    def __new__(cls, start, end):
        return super().__new__(cls, (start, end))


class _Annotation:
    """Stores ``(segment, track) -> label`` as pyannote.core 5.0 does."""

    def __init__(self, uri=None):
        self.uri = uri
        self.tracks: dict = {}

    def __setitem__(self, key, label):
        if isinstance(key, _Segment):
            key = (key, "_")
        self.tracks[key] = label


@pytest.fixture
def fake_pyannote(monkeypatch):
    core = types.ModuleType("pyannote.core")
    core.Annotation = _Annotation
    core.Segment = _Segment
    package = types.ModuleType("pyannote")
    package.core = core
    monkeypatch.setitem(sys.modules, "pyannote", package)
    monkeypatch.setitem(sys.modules, "pyannote.core", core)
    return core


def test_identical_spans_get_separate_tracks(fake_pyannote):
    from evaluation.der_metrics import annotation_from_segments

    ann = annotation_from_segments([
        {"start": 543.24, "end": 543.55, "speaker": "MEE071"},
        {"start": 543.24, "end": 543.55, "speaker": "MEE073"},
        {"start": 1.0, "end": 1.0, "speaker": "Z"},        # empty, skipped
    ], uri="EN2002c")
    assert sorted(ann.tracks.values()) == ["MEE071", "MEE073"]
    assert len({track for _, track in ann.tracks}) == 2
    assert ann.uri == "EN2002c"


def test_an_exact_repeat_is_kept_once(fake_pyannote):
    from evaluation.der_metrics import annotation_from_segments

    turn = {"start": 1.0, "end": 2.0, "speaker": "A"}
    ann = annotation_from_segments([turn, dict(turn)])
    assert list(ann.tracks.values()) == ["A"]


def test_rttm_reader_keeps_both_speakers_of_a_shared_span(fake_pyannote, tmp_path):
    pytest.importorskip("soundfile")
    from evaluation.finetune_pyannote_segmentation import (
        _read_annotation_from_rttm, _write_rttm)

    rttm = tmp_path / "IB4002.rttm"
    _write_rttm([
        {"start": 1405.10, "end": 1406.34, "speaker": "FIO093"},
        {"start": 1405.10, "end": 1406.34, "speaker": "MIO091"},
        {"start": 1405.10, "end": 1406.34, "speaker": "MIO091"},
    ], "IB4002", rttm)
    ann = _read_annotation_from_rttm(rttm)
    assert sorted(ann.tracks.values()) == ["FIO093", "MIO091"]
    assert ann.uri == "IB4002"


def test_stream_ami_loads_the_pinned_revision(monkeypatch):
    """The AMI stream names the snapshot the committed runs used."""
    from evaluation import ami_meetings
    from evaluation.revisions import revision_for

    seen = {}

    class _Stream:
        def cast_column(self, name, feature):
            return self

    fake = types.ModuleType("datasets")
    fake.load_dataset = lambda **kwargs: seen.update(kwargs) or _Stream()
    fake.Audio = lambda decode=True: ("Audio", decode)
    monkeypatch.setitem(sys.modules, "datasets", fake)
    ami_meetings.stream_ami("test", None)
    assert seen["revision"] == revision_for("edinburghcstr/ami") is not None
    assert seen["streaming"] is True and "token" not in seen


def test_collar_convention_is_recorded_beside_the_value():
    """EDER-01: 0.25 is the total width in pyannote.metrics, not ±0.25 s."""
    from evaluation import der_metrics

    assert der_metrics.DEFAULT_COLLAR_S == 0.25
    assert "collar_s/2" in der_metrics.COLLAR_CONVENTION
    assert "NIST" not in der_metrics.COLLAR_CONVENTION
