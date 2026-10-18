"""EDER-13: the reconstruction audit the manuscript cites writes an
archivable record, and measures what "no signal outside the annotated
regions" claims (exact zeros), not only an energy floor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("soundfile")

from evaluation import audit_reconstruction as ar  # noqa: E402
from evaluation import benchmark_der as bd  # noqa: E402

SR = 16_000


def test_exact_zero_share_separates_quiet_from_silent():
    audio = np.zeros(SR * 2, dtype=np.float32)
    audio[: SR // 2] = 0.5                       # the annotated turn
    reference = [{"start": 0.0, "end": 0.5}]
    assert ar.audit_meeting(audio, SR, reference)["silence_exact_zero"] == 1.0

    # A faint hiss outside the turn stays under the 2 % energy floor, so
    # purity still reads 1.0, but the audio is no longer silent there.
    audio[SR:] = 0.001
    row = ar.audit_meeting(audio, SR, reference)
    assert row["silence_purity"] == 1.0
    assert row["silence_exact_zero"] < 1.0


@pytest.fixture
def cache(tmp_path, monkeypatch):
    rows = []
    for m in range(2):
        for u in range(2):
            rows.append({"meeting_id": f"M{m}", "speaker_id": f"S{u}",
                         "begin_time": float(u), "end_time": u + 0.5,
                         "audio": {"array": np.full(SR // 2, 0.2, np.float32),
                                   "sampling_rate": SR}})
    monkeypatch.setattr(bd, "_stream_ami", lambda split, token: iter(rows))
    list(bd.build_corpus(split="test", cache_dir=tmp_path))
    return tmp_path / "test_timeline_full"


def test_json_record_carries_summary_parameters_and_commit(cache, tmp_path, monkeypatch):
    import provenance
    monkeypatch.setattr(provenance, "run_metadata",
                        lambda **_kwargs: {"git_commit": "abc"})
    out = tmp_path / "audit" / "reconstruction_audit_test.json"
    assert ar.main([str(cache), "--json", str(out)]) == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["run"] == {"git_commit": "abc"}
    assert record["manifest"]["split"] == "test"
    assert record["manifest"]["file"] == "manifest.json"
    assert "meetings" not in record["manifest"]
    assert record["parameters"]["energy_floor"] == ar.ENERGY_FLOOR
    assert [r["meeting_id"] for r in record["meetings"]] == ["M0", "M1"]
    summary = record["summary"]
    assert summary["n_meetings"] == summary["n_checked"] == 2
    assert summary["n_best_shift_zero"] == 2 and summary["displaced"] == []
    assert summary["min_silence_exact_zero"] == 1.0
