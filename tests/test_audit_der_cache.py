"""The reconstruction cache must never pass a partial or foreign build off
as the corpus.

A ``--limit-meetings`` smoke test used to write ``manifest.json`` into the
same directory an unlimited run reads, so every later benchmark or sweep
scored the smoke test's two meetings under the full corpus's label. The
manifest was also never compared with the request, and the WAV sample
rate was read and discarded. These tests drive the real ``build_corpus``
with a synthetic stream in place of the HuggingFace one.
"""

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

from evaluation import ami_meetings as am  # noqa: E402
from evaluation import benchmark_der as bd  # noqa: E402

SR = am.SAMPLE_RATE


def _rows(n_meetings=4, per_meeting=2):
    rows = []
    for m in range(n_meetings):
        for u in range(per_meeting):
            begin = float(u)
            rows.append({
                "meeting_id": f"M{m}", "speaker_id": f"S{u}",
                "begin_time": begin, "end_time": begin + 0.5,
                "audio": {"array": np.full(SR // 2, 0.1, dtype=np.float32),
                          "sampling_rate": SR},
            })
    return rows


@pytest.fixture
def stream(monkeypatch):
    calls = {"n": 0}

    def fake_stream(split, hf_token):
        calls["n"] += 1
        return iter(_rows())

    monkeypatch.setattr(bd, "_stream_ami", fake_stream)
    return calls


def _build(tmp_path, **kwargs):
    kwargs.setdefault("split", "test")
    kwargs.setdefault("mix_mode", "timeline")
    return [m[0] for m in bd.build_corpus(cache_dir=tmp_path, **kwargs)]


def _cache(tmp_path):
    return tmp_path / "test_timeline_full"


class TestLimitedBuildsAreNotReadAsComplete:
    def test_a_limited_build_writes_only_a_partial_manifest(self, tmp_path, stream):
        assert _build(tmp_path, limit_meetings=2) == ["M0", "M1"]
        assert not (_cache(tmp_path) / "manifest.json").exists()
        partial = json.loads((_cache(tmp_path) / "manifest.partial.json")
                             .read_text(encoding="utf-8"))
        assert partial["complete"] is False
        assert partial["limit_meetings"] == 2

    def test_a_later_full_run_rebuilds_instead_of_reading_two_meetings(
            self, tmp_path, stream):
        _build(tmp_path, limit_meetings=2)
        assert _build(tmp_path) == ["M0", "M1", "M2", "M3"]
        assert stream["n"] == 2

    def test_a_full_build_is_read_back_without_the_stream(self, tmp_path, stream):
        _build(tmp_path)
        manifest = json.loads((_cache(tmp_path) / "manifest.json")
                              .read_text(encoding="utf-8"))
        assert manifest["complete"] is True
        assert manifest["reconstruction_version"] == am.RECONSTRUCTION_VERSION
        assert _build(tmp_path) == ["M0", "M1", "M2", "M3"]
        assert stream["n"] == 1

    def test_a_limited_read_of_a_complete_cache_is_a_slice(self, tmp_path, stream):
        _build(tmp_path)
        assert _build(tmp_path, limit_meetings=1) == ["M0"]
        assert stream["n"] == 1

    def test_a_limited_build_can_still_be_audited(self, tmp_path, stream, capsys):
        """INTEG-05: the alignment audit looked only for manifest.json."""
        from evaluation import audit_reconstruction as ar

        _build(tmp_path, limit_meetings=2)
        rows = ar.audit_cache(_cache(tmp_path))
        assert [r["meeting_id"] for r in rows] == ["M0", "M1"]
        assert "partial cache" in capsys.readouterr().out

    def test_a_directory_without_either_manifest_is_refused(self, tmp_path):
        from evaluation import audit_reconstruction as ar

        with pytest.raises(SystemExit, match="manifest.partial.json"):
            ar.audit_cache(tmp_path)


class TestTheManifestIsCheckedAgainstTheRequest:
    def _rewrite(self, tmp_path, **changes):
        path = _cache(tmp_path) / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(changes)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    @pytest.mark.parametrize("changes, match", [
        ({"split": "validation"}, "split"),
        ({"mix_mode": "concat"}, "mix_mode"),
        ({"max_minutes": 10}, "max_minutes"),
        ({"sample_rate": 8000}, "sample_rate"),
        ({"complete": False, "limit_meetings": 2}, "limit-meetings"),
        ({"reconstruction_version": am.RECONSTRUCTION_VERSION + 1}, "version"),
    ])
    def test_a_mismatch_is_refused(self, tmp_path, stream, changes, match):
        _build(tmp_path)
        self._rewrite(tmp_path, **changes)
        with pytest.raises(SystemExit, match=match):
            _build(tmp_path)

    def test_a_manifest_from_before_versioning_is_still_read(self, tmp_path, stream):
        """The timeline caches behind the committed results carry only these keys."""
        _build(tmp_path)
        path = _cache(tmp_path) / "manifest.json"
        legacy = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items()
                  if k in ("split", "mix_mode", "max_minutes", "sample_rate",
                           "meetings")}
        path.write_text(json.dumps(legacy), encoding="utf-8")
        assert _build(tmp_path) == ["M0", "M1", "M2", "M3"]

    def test_an_integer_cap_matches_a_float_request(self, tmp_path, stream):
        _build(tmp_path, max_minutes=10.0)
        assert _build(tmp_path, max_minutes=10) == ["M0", "M1", "M2", "M3"]


class TestTheCapOnlyAppliesToTimeline:
    """DER-3: a concat cache was refused over a cap concat mode ignores."""

    def _concat(self, tmp_path):
        return tmp_path / f"test_concat_{bd._DEFAULT_UTT_PER_MEETING}utt"

    def test_a_concat_request_with_a_cap_is_refused_up_front(self, tmp_path, stream):
        with pytest.raises(SystemExit, match="timeline only"):
            _build(tmp_path, mix_mode="concat", max_minutes=5)
        assert stream["n"] == 0

    def test_run_benchmark_refuses_it_before_loading_anything(
            self, tmp_path, monkeypatch):
        def never(*args, **kwargs):
            pytest.fail("the run went ahead with a cap concat mode ignores")

        monkeypatch.setattr(bd, "_load_hf_token", never)
        monkeypatch.setattr(bd, "load_pipeline", never)
        out = tmp_path / "out"
        with pytest.raises(SystemExit, match="timeline only"):
            bd.run_benchmark(out, mix_mode="concat", max_minutes=5)
        assert not out.exists()

    def test_the_sweep_refuses_it_too(self, tmp_path, monkeypatch):
        from evaluation import sweep_der
        monkeypatch.setattr(sweep_der, "_load_hf_token",
                            lambda: pytest.fail("the sweep went ahead"))
        with pytest.raises(SystemExit, match="timeline only"):
            sweep_der.run_sweep(tmp_path / "out", mix_mode="concat",
                                max_minutes=5)

    def test_a_concat_manifest_records_no_cap(self, tmp_path, stream):
        _build(tmp_path, mix_mode="concat")
        manifest = json.loads((self._concat(tmp_path) / "manifest.json")
                              .read_text(encoding="utf-8"))
        assert manifest["max_minutes"] is None

    def test_an_older_concat_manifest_with_a_cap_is_still_read(
            self, tmp_path, stream):
        # Older code recorded whatever cap a concat build was given.
        _build(tmp_path, mix_mode="concat")
        path = self._concat(tmp_path) / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["max_minutes"] = 5
        path.write_text(json.dumps(manifest), encoding="utf-8")
        assert _build(tmp_path, mix_mode="concat") == ["M0", "M1", "M2", "M3"]
        assert stream["n"] == 1

    @pytest.mark.parametrize("recorded, requested", [(0, None), (None, 0), (0, 0)])
    def test_zero_minutes_is_the_whole_timeline(self, tmp_path, stream,
                                                recorded, requested):
        _build(tmp_path)
        path = _cache(tmp_path) / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["max_minutes"] = recorded
        path.write_text(json.dumps(manifest), encoding="utf-8")
        assert _build(tmp_path, max_minutes=requested) == ["M0", "M1", "M2", "M3"]
        assert stream["n"] == 1


class TestTheSampleRateIsChecked:
    def test_a_wav_at_another_rate_is_refused(self, tmp_path, stream):
        import soundfile as sf

        _build(tmp_path)
        wav = _cache(tmp_path) / "M0.wav"
        audio, _ = sf.read(wav, dtype="float32")
        sf.write(wav, audio, 8000, subtype="PCM_16")
        with pytest.raises(SystemExit, match="8000 Hz"):
            _build(tmp_path)
