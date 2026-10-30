"""Unit tests for ``evaluation.fetch_codex_mentis``.

These exercise the pure feed-parsing logic against an inline RSS fixture
and the lookup resolver against an injected opener, so they run with no
network and no downloads.  The behaviours pinned here are the ones a
reproducible corpus depends on: de-duplication by GUID, chronological
(oldest-first) indexing, correct extension/slug for the local filename,
duration parsing, and skipping items that carry no audio enclosure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.fetch_codex_mentis import (
    parse_feed,
    resolve_feed_url,
    _parse_duration,
    _slugify,
)

_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0">
<channel>
  <title>Test Pod</title>
  <item>
    <title>Newest Episode</title>
    <guid>guid-c</guid>
    <pubDate>Wed, 01 Jan 2025 10:00:00 GMT</pubDate>
    <enclosure url="https://ex.com/c.m4a" length="3000" type="audio/x-m4a"/>
    <itunes:duration>00:30:00</itunes:duration>
  </item>
  <item>
    <title>Oldest Episode: A Study!</title>
    <guid>guid-a</guid>
    <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    <enclosure url="https://ex.com/a.mp3" length="1000" type="audio/mpeg"/>
    <itunes:duration>125</itunes:duration>
  </item>
  <item>
    <title>Duplicate Of Oldest</title>
    <guid>guid-a</guid>
    <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
    <enclosure url="https://ex.com/a.mp3" length="1000" type="audio/mpeg"/>
  </item>
  <item>
    <title>No Enclosure Should Skip</title>
    <guid>guid-x</guid>
  </item>
</channel>
</rss>"""


def test_parse_feed_dedupes_sorts_and_indexes():
    eps = parse_feed(_RSS)
    # guid-a de-duplicated, guid-x (no enclosure) skipped -> two episodes.
    assert len(eps) == 2
    # Oldest first: 2024 episode is index 1, 2025 episode is index 2.
    assert [e.guid for e in eps] == ["guid-a", "guid-c"]
    assert [e.index for e in eps] == [1, 2]


def test_parse_feed_filename_extension_and_slug():
    eps = parse_feed(_RSS)
    first, second = eps
    # audio/mpeg -> .mp3, slug from a punctuated title.
    assert first.filename == "ep01_oldest-episode-a-study.mp3"
    assert first.duration_s == 125
    assert first.bytes_declared == 1000
    assert first.published == "2024-01-01"
    # audio/x-m4a -> .m4a, HH:MM:SS duration.
    assert second.filename == "ep02_newest-episode.m4a"
    assert second.duration_s == 1800
    assert second.mime == "audio/x-m4a"


def test_parse_duration_forms():
    assert _parse_duration("00:30:00") == 1800
    assert _parse_duration("5:00") == 300
    assert _parse_duration("125") == 125
    assert _parse_duration("") == 0
    assert _parse_duration("not-a-time") == 0


def test_slugify_is_filesystem_safe():
    assert _slugify("Beyond the Cloud: Data Sovereignty!") == \
        "beyond-the-cloud-data-sovereignty"
    assert _slugify("") == "episode"


def test_limit_does_not_truncate_the_manifest(tmp_path, monkeypatch):
    """A capped run must record the whole corpus, not just what it fetched.

    Regression: --limit used to slice the episode list before the manifest
    was built, so a two-episode smoke test rewrote a nine-episode manifest
    to claim the corpus held two. The audio stayed on disk; the record of
    it did not.
    """
    from evaluation import fetch_codex_mentis as f

    monkeypatch.setattr(f, "resolve_feed_url", lambda pid, opener=None: "u")
    monkeypatch.setattr(f, "_http_get", lambda url: _RSS)
    downloaded = []

    def fake_download(url, dest):
        downloaded.append(dest.name)
        dest.write_bytes(b"audio")
        return 5, "deadbeef"

    monkeypatch.setattr(f, "_download_stream", fake_download)

    manifest = f.fetch(tmp_path, "123", limit=1, list_only=False)

    # Both feed episodes are described, though only one was fetched.
    assert manifest["n_episodes"] == 2
    assert len(manifest["episodes"]) == 2
    assert len(downloaded) == 1
    statuses = {e["index"]: e["status"] for e in manifest["episodes"]}
    assert statuses[1] == "downloaded"
    assert statuses[2] == "not_downloaded"


def test_resolve_feed_url_uses_injected_opener():
    payload = json.dumps(
        {"results": [{"feedUrl": "https://feed.example/rss"}]}
    ).encode("utf-8")
    got = resolve_feed_url("123", opener=lambda url: payload)
    assert got == "https://feed.example/rss"
