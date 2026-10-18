"""Stage-1 fix to the version stamp (audit finding T2-02).

Transcripts and manifests were stamped with the release in the
hand-maintained versions.csv (1.0.0) however much the code had changed;
the stamp now names the git commit as well.
"""

from __future__ import annotations

import contextlib
import io
import json
import re

import pytest


def _result(duration=None):
    result = {
        'text': 'hello there. goodbye now.',
        'chunks': [
            {'text': 'hello', 'timestamp': (0.0, 0.4)},
            {'text': 'there.', 'timestamp': (0.5, 0.9)},
            {'text': 'goodbye', 'timestamp': (2.0, 2.4)},
            {'text': 'now.', 'timestamp': (2.5, 2.9)},
        ],
    }
    if duration is not None:
        result['audio_duration_s'] = duration
    return result


@pytest.fixture()
def run(transcription_module, tmp_path, monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    (tmp_path / "rec.wav").write_bytes(b"RIFF0000WAVE")

    def _run(result, **kwargs):
        monkeypatch.setattr(m, "transcribe_audio_only",
                            lambda *_a, **_k: result)
        kwargs.setdefault("language", "english")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = m.process_audio_file(str(tmp_path / "rec.wav"), **kwargs)
        return ok, out.getvalue(), tmp_path / "output" / "transcripts"

    return _run


# ---------------------------------------------------------------------------
# T2-02
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+|unreleased)\+g[0-9a-f]{12}(\.dirty)?")


def test_version_names_the_commit_in_a_checkout(transcription_module):
    import provenance
    commit, _ = provenance.git_commit()
    if commit is None:
        pytest.skip("not a git checkout")
    version = transcription_module.get_latest_version()
    assert _VERSION_RE.fullmatch(version), version
    assert commit.startswith(version.split("+g")[1][:12])


def test_latest_release_resolves_same_day_ties_to_the_later_row(
        transcription_module, tmp_path):
    csv_path = tmp_path / "versions.csv"
    csv_path.write_text(
        "version,date,summary,details\n"
        "1.0.0,2025-11-06,a,b\n"
        "1.1.0,2026-09-26,c,d\n"
        "1.1.1,2026-09-26,e,f\n"
        "0.9.0,2025-01-01,g,h\n", encoding="utf-8")
    assert transcription_module._latest_release(csv_path) == "1.1.1"
    assert transcription_module._latest_release(tmp_path / "absent.csv") is None


def test_header_and_manifest_carry_the_same_version(run, transcription_module):
    version = transcription_module.get_latest_version()
    ok, log, out = run(_result(duration=3.0), timestamps=True)
    assert ok is True
    header = (out / "rec_transcript.txt").read_text(encoding="utf-8")
    assert f"Transcription system version: {version}\n" in header
    manifest = json.loads((out / "rec_manifest.json").read_text(encoding="utf-8"))
    software = manifest["provenance"]["software"]
    assert software["version"] == version
    assert "git_commit" in software
