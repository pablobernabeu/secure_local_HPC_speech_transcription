"""Tests for the run manifest and its verification.

The manifest exists to make later alteration detectable, so most of these
tests are attacks: change an artefact, change a recorded digest, forge a
signature, delete a file, add one. A manifest that only passed the happy
path would be decoration, so each check is paired with the tamper it is
supposed to catch.

Everything here is pure standard library, so the suite runs anywhere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from provenance import (  # noqa: E402
    MANIFEST_SUFFIX,
    build_manifest,
    canonical_json,
    load_key,
    sha256_bytes,
    verify_manifest,
    write_manifest,
)

_KEY = b"a-test-signing-key"


def _run(tmp_path, name="demo"):
    """Create a small artefact set and return (files, audio, manifest path)."""
    (tmp_path / f"{name}_transcript.txt").write_text("Hello there", encoding="utf-8")
    (tmp_path / f"{name}_transcript.json").write_text('{"text": "Hello there"}',
                                                     encoding="utf-8")
    audio = tmp_path / f"{name}.wav"
    audio.write_bytes(b"RIFFfake-audio-bytes")
    files = [tmp_path / f"{name}_transcript.txt", tmp_path / f"{name}_transcript.json"]
    return files, audio, tmp_path / f"{name}{MANIFEST_SUFFIX}"


def test_canonical_json_is_order_independent():
    """Digests must not depend on dictionary ordering."""
    a = canonical_json({"b": 1, "a": [1, 2], "c": {"y": 2, "x": 1}})
    b = canonical_json({"c": {"x": 1, "y": 2}, "a": [1, 2], "b": 1})
    assert a == b
    assert sha256_bytes(a) == sha256_bytes(b)


def test_manifest_records_artefacts_and_audio(tmp_path):
    files, audio, mpath = _run(tmp_path)
    m = write_manifest(files, tmp_path, mpath, provenance={"asr_model": "whisper"},
                       audio_path=audio)
    assert m["manifest_version"] >= 1
    assert {e["path"] for e in m["artefacts"]} == {
        "demo_transcript.txt", "demo_transcript.json"}
    assert all(len(e["sha256"]) == 64 for e in m["artefacts"])
    assert m["input_audio"]["name"] == "demo.wav"
    assert m["provenance"]["asr_model"] == "whisper"
    assert mpath.exists()


def test_manifest_excludes_itself(tmp_path):
    """A manifest cannot contain its own digest, so it must be skipped."""
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio)
    m2 = build_manifest(list(tmp_path.glob("*")), tmp_path)
    assert all(not e["path"].endswith(MANIFEST_SUFFIX) for e in m2["artefacts"])


def test_clean_run_verifies(tmp_path):
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio)
    report = verify_manifest(mpath)
    assert report["ok"] is True
    assert report["manifest_digest_ok"] is True
    assert len(report["verified"]) == 2
    assert report["modified"] == [] and report["missing"] == []


def test_modified_artefact_is_detected(tmp_path):
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio)
    # The kind of edit this exists to catch: the text is changed after the fact.
    (tmp_path / "demo_transcript.txt").write_text("Hello there!", encoding="utf-8")
    report = verify_manifest(mpath)
    assert report["ok"] is False
    assert report["modified"] == ["demo_transcript.txt"]


def test_missing_artefact_is_detected(tmp_path):
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio)
    (tmp_path / "demo_transcript.json").unlink()
    report = verify_manifest(mpath)
    assert report["ok"] is False
    assert report["missing"] == ["demo_transcript.json"]


def test_unlisted_artefact_is_reported(tmp_path):
    """A file added to the run afterwards changes what an exporter carries."""
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio)
    (tmp_path / "demo_transcript_extra.txt").write_text("added later",
                                                        encoding="utf-8")
    report = verify_manifest(mpath)
    assert report["ok"] is False
    assert report["unlisted"] == ["demo_transcript_extra.txt"]


def test_editing_a_recorded_digest_is_detected(tmp_path):
    """Rewriting a digest to match an edited file must not pass.

    Without the manifest's own digest, an attacker could edit an artefact
    and update its recorded hash. The self-digest is what closes that.
    """
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio)
    target = tmp_path / "demo_transcript.txt"
    target.write_text("Tampered", encoding="utf-8")

    m = json.loads(mpath.read_text(encoding="utf-8"))
    for entry in m["artefacts"]:
        if entry["path"] == "demo_transcript.txt":
            entry["sha256"] = sha256_bytes(b"Tampered")
    mpath.write_text(json.dumps(m, indent=2), encoding="utf-8")

    report = verify_manifest(mpath)
    # The artefacts now agree with their digests, but the manifest does not
    # agree with itself.
    assert report["modified"] == []
    assert report["manifest_digest_ok"] is False
    assert report["ok"] is False


def test_signature_round_trip_and_forgery(tmp_path):
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio, key=_KEY)

    good = verify_manifest(mpath, key=_KEY)
    assert good["signed"] is True
    assert good["signature_ok"] is True and good["ok"] is True

    # The wrong key must not verify.
    assert verify_manifest(mpath, key=b"not-the-key")["signature_ok"] is False

    # Nor may a signature be forged by editing the manifest body.
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["provenance"]["asr_model"] = "something-else"
    mpath.write_text(json.dumps(m, indent=2), encoding="utf-8")
    assert verify_manifest(mpath, key=_KEY)["signature_ok"] is False


def test_unsigned_manifest_with_key_fails_closed(tmp_path):
    """A reader who expects a signature must not accept a manifest lacking one."""
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio)  # no key
    report = verify_manifest(mpath, key=_KEY)
    assert report["signed"] is False
    assert report["signature_ok"] is False
    assert report["ok"] is False


def test_unsigned_manifest_without_key_is_integrity_only(tmp_path):
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio)
    report = verify_manifest(mpath)
    assert report["signed"] is False
    assert report["signature_ok"] is None   # not claimed either way
    assert report["ok"] is True


def test_load_key_prefers_file_then_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_SIGNING_KEY", "from-env")
    assert load_key() == b"from-env"
    kf = tmp_path / "signing.key"
    kf.write_text("from-file\n", encoding="utf-8")   # trailing newline stripped
    assert load_key(kf) == b"from-file"
    monkeypatch.delenv("TRANSCRIPTION_SIGNING_KEY")
    assert load_key() is None


def test_key_never_appears_in_the_manifest(tmp_path):
    files, audio, mpath = _run(tmp_path)
    write_manifest(files, tmp_path, mpath, audio_path=audio, key=_KEY)
    assert _KEY.decode() not in mpath.read_text(encoding="utf-8")
