"""Audit fix EPRIV-06: downloads are verified against the manifest.

The fetcher recorded a SHA-256 per episode but never compared a download
with the recorded one, and a ``--limit`` run wrote ``sha256: null`` over
every committed checksum it did not fetch. These tests run the real
``fetch()`` with the network functions replaced.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import fetch_codex_mentis as f  # noqa: E402

_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0">
<channel>
  <item><title>One</title><guid>g1</guid>
    <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    <enclosure url="https://ex.com/1.m4a" length="5" type="audio/x-m4a"/></item>
  <item><title>Two</title><guid>g2</guid>
    <pubDate>Tue, 02 Jan 2024 10:00:00 GMT</pubDate>
    <enclosure url="https://ex.com/2.m4a" length="5" type="audio/x-m4a"/></item>
</channel></rss>"""

_BODIES = {"https://ex.com/1.m4a": b"one..", "https://ex.com/2.m4a": b"two.."}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def offline(monkeypatch, tmp_path_factory):
    bodies = dict(_BODIES)
    # Hermetic: no test reads the repository's committed record unless it
    # points fetch() at one itself.
    monkeypatch.setattr(f, "_COMMITTED_MANIFEST",
                        tmp_path_factory.mktemp("ref") / "absent.json")
    monkeypatch.setattr(f, "resolve_feed_url", lambda pid, opener=None: "u")
    monkeypatch.setattr(f, "_http_get", lambda url: _RSS)

    def fake_download(url, dest):
        data = bodies[url]
        dest.write_bytes(data)
        return len(data), _sha(data)

    monkeypatch.setattr(f, "_download_stream", fake_download)
    return bodies


def _committed(tmp_path):
    """Write a manifest as a full earlier fetch would have left it."""
    episodes = f.parse_feed(_RSS)
    records = []
    for ep, url in zip(episodes, _BODIES, strict=True):
        rec = {**ep.__dict__, "sha256": _sha(_BODIES[url]),
               "bytes": len(_BODIES[url]), "status": "cached"}
        records.append(rec)
    manifest = {"episodes": records, "n_episodes": len(records)}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, path.read_bytes()


def test_limited_run_keeps_the_committed_manifest(tmp_path, offline):
    path, before = _committed(tmp_path)
    manifest = f.fetch(tmp_path, "1", limit=1, list_only=False)
    assert path.read_bytes() == before          # committed record untouched
    limited = json.loads((tmp_path / "manifest.limited.json").read_text("utf-8"))
    assert limited == manifest
    # The episode not fetched keeps its recorded checksum.
    second = manifest["episodes"][1]
    assert second["status"] == "not_downloaded"
    assert second["sha256"] == _sha(_BODIES["https://ex.com/2.m4a"])


def test_matching_download_verifies(tmp_path, offline):
    _committed(tmp_path)
    manifest = f.fetch(tmp_path, "1", limit=None, list_only=False)
    assert [e["status"] for e in manifest["episodes"]] == ["downloaded"] * 2
    # A second run finds the files and verifies them.
    again = f.fetch(tmp_path, "1", limit=None, list_only=False)
    assert [e["status"] for e in again["episodes"]] == ["cached"] * 2


def test_changed_audio_fails_and_keeps_the_record(tmp_path, offline):
    path, before = _committed(tmp_path)
    offline["https://ex.com/1.m4a"] = b"re-encoded"
    with pytest.raises(RuntimeError, match="differs from the recorded"):
        f.fetch(tmp_path, "1", limit=None, list_only=False)
    assert path.read_bytes() == before
    audio = tmp_path / "audio"
    assert list(audio.glob("ep01_*.mismatch"))
    assert not list(audio.glob("ep01_*.m4a"))


def test_accept_new_records_the_change(tmp_path, offline):
    _committed(tmp_path)
    offline["https://ex.com/1.m4a"] = b"re-encoded"
    manifest = f.fetch(tmp_path, "1", limit=None, list_only=False,
                       accept_new=True)
    first = manifest["episodes"][0]
    assert first["sha256"] == _sha(b"re-encoded")
    assert first["sha256_previous"] == _sha(_BODIES["https://ex.com/1.m4a"])


def test_file_without_a_record_is_unverified(tmp_path, offline):
    audio = tmp_path / "audio"
    audio.mkdir()
    name = f.parse_feed(_RSS)[0].filename
    (audio / name).write_bytes(b"whatever")
    manifest = f.fetch(tmp_path, "1", limit=0, list_only=False)
    assert manifest["episodes"][0]["status"] == "cached_unverified"


def test_cli_exits_non_zero_on_mismatch(tmp_path, offline, capsys):
    _committed(tmp_path)
    offline["https://ex.com/2.m4a"] = b"changed"
    assert f.main(["--dest", str(tmp_path)]) == 1
    assert "--accept-new" in capsys.readouterr().err


class TestAFreshDestIsVerifiedAgainstTheCommittedRecord:
    """PRIV-06: a fetch into $DATA compared against nothing."""

    def _reference(self, tmp_path, monkeypatch):
        ref_dir = tmp_path / "repo_data"
        ref_dir.mkdir()
        path, before = _committed(ref_dir)
        monkeypatch.setattr(f, "_COMMITTED_MANIFEST", path)
        return path, before

    def test_changed_audio_in_a_fresh_dest_fails(self, tmp_path, offline,
                                                 monkeypatch):
        ref, before = self._reference(tmp_path, monkeypatch)
        dest = tmp_path / "data_codex"
        offline["https://ex.com/1.m4a"] = b"ad-inserted"
        with pytest.raises(RuntimeError, match="differs from the recorded"):
            f.fetch(dest, "1", limit=None, list_only=False)
        assert not (dest / "manifest.json").exists()
        assert ref.read_bytes() == before

    def test_matching_audio_is_recorded_in_the_dest(self, tmp_path, offline,
                                                    monkeypatch, capsys):
        ref, before = self._reference(tmp_path, monkeypatch)
        dest = tmp_path / "data_codex"
        manifest = f.fetch(dest, "1", limit=None, list_only=False)
        assert [e["status"] for e in manifest["episodes"]] == ["downloaded"] * 2
        assert "Verifying: against" in capsys.readouterr().out
        written = json.loads((dest / "manifest.json").read_text("utf-8"))
        assert [e["sha256"] for e in written["episodes"]] == \
            [_sha(b) for b in _BODIES.values()]
        assert ref.read_bytes() == before          # the record is only read

    def test_a_limited_fetch_into_a_fresh_dest_writes_its_manifest(
            self, tmp_path, offline, monkeypatch):
        self._reference(tmp_path, monkeypatch)
        dest = tmp_path / "data_codex"
        manifest = f.fetch(dest, "1", limit=1, list_only=False)
        assert (dest / "manifest.json").exists()
        assert not (dest / "manifest.limited.json").exists()
        # The episode not fetched keeps the committed checksum.
        assert manifest["episodes"][1]["sha256"] == \
            _sha(_BODIES["https://ex.com/2.m4a"])

    def test_the_dest_manifest_takes_precedence(self, tmp_path, offline,
                                                monkeypatch):
        self._reference(tmp_path, monkeypatch)
        dest = tmp_path / "data_codex"
        dest.mkdir()
        own = {"episodes": [{"guid": "g1", "sha256": _sha(b"re-encoded"),
                             "bytes": len(b"re-encoded")}]}
        (dest / "manifest.json").write_text(json.dumps(own), encoding="utf-8")
        offline["https://ex.com/1.m4a"] = b"re-encoded"
        manifest = f.fetch(dest, "1", limit=None, list_only=False)
        assert manifest["episodes"][0]["status"] == "downloaded"

    def test_the_default_reference_is_the_repository_record(self):
        repo = Path(f.__file__).resolve().parents[1]
        assert repo / "data" / "codex_mentis" / "manifest.json" == f._COMMITTED_MANIFEST
