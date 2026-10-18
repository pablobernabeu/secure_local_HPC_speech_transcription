"""The pipeline passes the source recording and its derivation to the manifest (CORE-04)."""

from __future__ import annotations

import ast
from pathlib import Path

import provenance

REPO = Path(__file__).resolve().parents[1]


def _calls(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", None)) == name]


def test_pipeline_wires_source_audio_through_to_the_manifest():
    tree = ast.parse((REPO / "transcription.py").read_text(encoding="utf-8"))
    options = {a.value for c in _calls(tree, "add_argument") for a in c.args
               if isinstance(a, ast.Constant)}
    assert {"--source-audio", "--source-derivation"} <= options
    (manifest_call,) = _calls(tree, "write_manifest")
    kw = {k.arg: ast.unparse(k.value) for k in manifest_call.keywords}
    assert kw["source_audio"] == "source_audio"
    assert kw["derivation"] == "source_derivation"
    (process_call,) = [c for c in _calls(tree, "process_audio_file")]
    kw = {k.arg: ast.unparse(k.value) for k in process_call.keywords}
    assert kw["source_audio"] == "args.source_audio"
    assert kw["source_derivation"] == "args.source_derivation"


def test_manifest_records_the_source_recording_and_its_digest(tmp_path):
    source = tmp_path / "episode.m4a"
    source.write_bytes(b"original bytes")
    derived = tmp_path / "episode_16k.wav"
    derived.write_bytes(b"derived bytes")
    art = tmp_path / "episode_transcript.txt"
    art.write_text("text", encoding="utf-8")
    manifest = provenance.build_manifest(
        [art], tmp_path, audio_path=derived, source_audio=source,
        derivation="ffmpeg -i episode.m4a -ar 16000 -ac 1 episode_16k.wav")
    assert manifest["source_audio"]["sha256"] == provenance.sha256_file(source)
    assert manifest["source_audio"]["derivation"].startswith("ffmpeg")
    assert manifest["input_audio"]["sha256"] == provenance.sha256_file(derived)
