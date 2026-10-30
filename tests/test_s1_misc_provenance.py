"""CORE-04 and CORE-05: the manifest can name the recording a transcribed
file was derived from, and its documentation says what it does not cover."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import provenance


def _run(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    transcript = out / "ep05_transcript.txt"
    transcript.write_text("hello", encoding="utf-8")
    original = tmp_path / "ep05.m4a"
    original.write_bytes(b"m4a bytes")
    derived = out / "ep05_16k.wav"          # beside the outputs on purpose
    derived.write_bytes(b"wav bytes")
    original_copy = out / "ep05.m4a"
    original_copy.write_bytes(b"m4a bytes")
    return out, transcript, original, derived


def test_source_audio_and_its_derivation_are_recorded(tmp_path):
    out, transcript, original, derived = _run(tmp_path)
    manifest_path = out / "ep05_manifest.json"
    manifest = provenance.write_run_manifest(
        [transcript], out, manifest_path, audio_path=derived,
        source_audio=original,
        derivation="ffmpeg -i ep05.m4a -ar 16000 -ac 1 -c:a pcm_s16le ep05_16k.wav")
    assert manifest["input_audio"]["sha256"] == provenance.sha256_file(derived)
    assert manifest["source_audio"] == {
        "name": "ep05.m4a", "bytes": original.stat().st_size,
        "sha256": provenance.sha256_file(original),
        "derivation": "ffmpeg -i ep05.m4a -ar 16000 -ac 1 -c:a pcm_s16le ep05_16k.wav"}
    report = provenance.verify_manifest(manifest_path)
    assert report["ok"], report
    # Neither recording counts as an unlisted artefact of the run.
    assert report["unlisted"] == []


def test_the_source_block_is_covered_by_the_manifest_digest(tmp_path):
    out, transcript, original, derived = _run(tmp_path)
    manifest_path = out / "ep05_manifest.json"
    provenance.write_run_manifest([transcript], out, manifest_path,
                                  audio_path=derived, source_audio=original)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source_audio"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not provenance.verify_manifest(manifest_path)["manifest_digest_ok"]


def test_without_a_source_the_manifest_is_as_before(tmp_path):
    out, transcript, _, derived = _run(tmp_path)
    manifest = provenance.build_manifest([transcript], out, audio_path=derived)
    assert "source_audio" not in manifest
    missing = provenance.build_manifest([transcript], out, audio_path=derived,
                                        source_audio=tmp_path / "absent.m4a")
    assert "source_audio" not in missing


def test_the_docstring_names_what_the_manifest_does_not_cover():
    doc = provenance.__doc__
    assert "every file emitted for a run" not in doc
    assert "name_masking_logs" in doc and "not covered" in doc
