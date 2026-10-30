"""Stage-1 fix EPRIV-03: the per-meeting cap on the anonymisation sample.

The cap was passed on doubled and never enforced while decoding, so job
8781723 (400 utterances, cap 25) took up to 42 from one meeting and
reached 13 of the 16 test meetings while its summary recorded a cap of 25.
These tests drive _load_utterances with a stub stream and decoder; no
network, dataset or audio file.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import benchmark_anonymisation as ba

bd = pytest.importorskip("evaluation.benchmark_der")

_SHORT, _GOOD = "short", "good"


def _stream(meetings, rows_per_meeting, short_first=0):
    """Rows for *meetings*, each starting with *short_first* short clips."""
    rows = []
    for m in range(meetings):
        for i in range(rows_per_meeting):
            rows.append({"meeting_id": f"M{m}",
                         "audio_id": f"AMI_M{m}_H0{i % 4}_S{i % 4}_{i:07d}_{i + 1:07d}",
                         "speaker_id": f"M{m}S{i % 4}",
                         "text": "hello there",
                         "begin_time": float(i), "end_time": float(i) + 1.0,
                         "audio": _SHORT if i < short_first else _GOOD})
    return rows


def _decode(kind):
    n = 100 if kind == _SHORT else ba.SAMPLE_RATE
    return np.zeros(n, dtype=np.float32), ba.SAMPLE_RATE


@pytest.fixture
def stub_stream(monkeypatch):
    def install(rows):
        monkeypatch.setattr(bd, "_stream_ami", lambda split, token: iter(rows))
        monkeypatch.setattr(bd, "_decode_audio_bytes", _decode)
    return install


def test_no_meeting_supplies_more_than_the_cap(stub_stream):
    """The doubled cap let one meeting supply 2N; now it is N."""
    stub_stream(_stream(meetings=3, rows_per_meeting=10))
    got = ba._load_utterances(100, None, per_meeting=2)
    counts = Counter(u["meeting"] for u in got)
    assert counts == {"M0": 2, "M1": 2, "M2": 2}


def test_short_rows_do_not_use_up_a_meetings_share(stub_stream):
    """Each meeting opens with two clips under a second; each still gives N."""
    stub_stream(_stream(meetings=3, rows_per_meeting=6, short_first=2))
    skipped = {}
    got = ba._load_utterances(100, None, per_meeting=3, skipped=skipped)
    counts = Counter(u["meeting"] for u in got)
    assert max(counts.values()) <= 3
    assert counts == {"M0": 3, "M1": 3, "M2": 3}
    assert skipped["too_short"] == 6


def test_all_meetings_are_reached_when_the_budget_allows(stub_stream):
    """limit >= N x meetings: every meeting represented, total N x meetings."""
    stub_stream(_stream(meetings=16, rows_per_meeting=50, short_first=5))
    got = ba._load_utterances(400, None, per_meeting=25)
    counts = Counter(u["meeting"] for u in got)
    assert len(counts) == 16
    assert set(counts.values()) == {25}
    assert len(got) == 400


def test_a_meeting_that_runs_out_gives_what_it_has(stub_stream):
    rows = _stream(meetings=2, rows_per_meeting=4, short_first=3)
    stub_stream(rows)
    got = ba._load_utterances(100, None, per_meeting=3)
    assert Counter(u["meeting"] for u in got) == {"M0": 1, "M1": 1}


def test_the_limit_stops_the_walk(stub_stream):
    stub_stream(_stream(meetings=4, rows_per_meeting=10))
    got = ba._load_utterances(5, None, per_meeting=2)
    assert len(got) == 5
    assert Counter(u["meeting"] for u in got) == {"M0": 2, "M1": 2, "M2": 1}


def test_without_a_cap_the_first_meeting_is_read_from_its_start(stub_stream):
    """The single-meeting sample: the first meeting, in start-time order.

    The first meeting's rows arrive newest first here, because the AMI
    stream's own order is not by start time. Job 8573363 took the rows as
    they came, so this configuration repeats its settings but not its
    sample.
    """
    rows = _stream(meetings=3, rows_per_meeting=10, short_first=2)
    stub_stream(rows[:10][::-1] + rows[10:])
    got = ba._load_utterances(6, None)
    assert [u["uid"] for u in got] == [
        f"AMI_M0_H0{i % 4}_S{i % 4}_{i:07d}_{i + 1:07d}" for i in range(2, 8)]


def test_the_summary_names_the_order_within_a_meeting():
    """The uncapped label once said "in stream order", true of meetings only."""
    uncapped = ba.sampling_description(None)
    assert "meetings in stream order" in uncapped
    assert "start-time order" in uncapped
    capped = ba.sampling_description(25)
    assert capped.startswith("meeting by meeting, at most 25 accepted per meeting")
    assert "start-time order" in capped


def test_each_utterance_carries_its_meeting_and_channel(stub_stream):
    stub_stream(_stream(meetings=1, rows_per_meeting=3))
    got = ba._load_utterances(3, None)
    assert [u["channel"] for u in got] == ["H00", "H01", "H02"]
    assert {u["meeting"] for u in got} == {"M0"}
