#!/usr/bin/env python3
"""
Fetch the *Codex Mentis* podcast as a reproducible real-world test corpus.

The standard ASR benchmarks used elsewhere in this evaluation (LibriSpeech,
FLEURS, VoxPopuli, AMI) are read or meeting speech.  To exercise the
workflow on realistic long-form conversational audio without any consent
or licensing encumbrance, this module downloads *Codex Mentis*
(https://podcasts.apple.com/us/podcast/id1837010092), a cognitive-science
podcast authored by this project's author and generated with NotebookLM.
Because the author owns the material and the episodes are synthetic
two-voice dialogues, the corpus is redistribution-clean, has a known
speaker count for diarisation, and --- via episode five, "Beyond the
cloud: Reclaiming data sovereignty in speech transcription" --- includes
an instalment about this very workflow.

The download is reproducible.  Apple Podcasts only indexes a feed, so the
canonical audio source is resolved deterministically: the iTunes Lookup
API maps the numeric podcast id to its RSS ``feedUrl``, the feed's
``<enclosure>`` elements give the episode audio, and every file is
recorded in a manifest with its byte length and SHA-256 so a re-download
can be verified bit-for-bit.  Only the manifest is committed; the audio
itself is git-ignored (``*.m4a``) and is re-fetched on demand.

No gold transcript exists for these episodes, so the corpus supports
reference-free and structural evaluation (speaker-count accuracy against
the known two voices, timestamp monotonicity and coverage, masking
false-positive rate on natural technical prose, cross-model stability)
and a worked end-to-end case study, rather than corpus WER.  A small
hand-corrected reference subset would enable true WER/DER and is left as
an option.

Usage::

    python -m evaluation.fetch_codex_mentis                 # download all
    python -m evaluation.fetch_codex_mentis --list-only     # enumerate only
    python -m evaluation.fetch_codex_mentis --limit 1       # smoke test
    python -m evaluation.fetch_codex_mentis --dest data/codex_mentis
    python -m evaluation.fetch_codex_mentis --accept-new    # re-baseline

A download whose SHA-256 or size differs from the manifest fails the run
and is kept as ``<file>.mismatch``; ``--accept-new`` records it instead.
The manifest is the one in ``--dest``, or, when ``--dest`` has none (a
first fetch into ``$DATA``), the committed ``data/codex_mentis/manifest.json``.
A ``--limit`` run leaves an existing ``manifest.json`` alone and writes
``manifest.limited.json``.

Dependencies: standard library only (urllib, xml.etree, hashlib).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

_PODCAST_ID = "1837010092"
_LOOKUP_URL = "https://itunes.apple.com/lookup?id={id}"
_DEFAULT_DEST = Path("data/codex_mentis")
# The checksums the case study was run on. A fetch into a directory with no
# manifest of its own (hpc/submit_case_study.sh fetches into $DATA) is
# verified against these, or a fresh account would record whatever the
# host serves today without comparing it with anything.
_COMMITTED_MANIFEST = (Path(__file__).resolve().parents[1]
                       / "data" / "codex_mentis" / "manifest.json")
_USER_AGENT = "codex-mentis-fetch/1.0 (+reproducible ASR evaluation)"
_ITUNES_NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
_CHUNK = 1 << 16
_TIMEOUT = 60
_RETRIES = 3

# Extension by enclosure MIME type; Anchor serves AAC as audio/x-m4a.
_EXT_BY_TYPE = {
    "audio/x-m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/aac": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


@dataclass
class Episode:
    """One podcast episode resolved from the feed (before download)."""

    index: int          # 1-based, chronological (oldest first)
    guid: str
    title: str
    url: str
    bytes_declared: int  # <enclosure length="...">, may be 0 if absent
    mime: str
    duration_s: int
    published: str       # ISO date, or "" if unparseable
    filename: str        # local filename, assigned by the resolver


def resolve_feed_url(podcast_id: str, opener=None) -> str:
    """Resolve a numeric Apple-Podcasts id to its RSS ``feedUrl``.

    Uses the public iTunes Lookup API.  *opener* is an injectable callable
    ``(url) -> bytes`` used by the tests to avoid network access; it
    defaults to :func:`_http_get`.
    """
    opener = opener or _http_get
    payload = json.loads(opener(_LOOKUP_URL.format(id=podcast_id)).decode("utf-8"))
    results = payload.get("results") or []
    if not results or not results[0].get("feedUrl"):
        raise RuntimeError(f"No feedUrl for podcast id {podcast_id}")
    return results[0]["feedUrl"]


def _slugify(title: str, max_len: int = 60) -> str:
    """Return a filesystem-safe, lower-case slug for *title*."""
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_len].strip("-") or "episode"


def _parse_duration(raw: str | None) -> int:
    """Parse an ``<itunes:duration>`` value into whole seconds.

    Accepts ``HH:MM:SS``, ``MM:SS``, or a bare seconds count; returns 0 on
    anything unrecognised.
    """
    if not raw:
        return 0
    raw = raw.strip()
    if ":" in raw:
        parts = raw.split(":")
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return 0
        seconds = 0
        for n in nums:
            seconds = seconds * 60 + n
        return seconds
    try:
        return int(float(raw))
    except ValueError:
        return 0


def _to_iso(pubdate: str | None) -> str:
    """Convert an RFC-822 ``pubDate`` to an ISO date, or ``""`` on failure."""
    if not pubdate:
        return ""
    try:
        return parsedate_to_datetime(pubdate).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse_feed(xml_bytes: bytes) -> list[Episode]:
    """Parse podcast RSS bytes into a chronological list of :class:`Episode`.

    Episodes are de-duplicated by ``<guid>`` and sorted oldest-first by
    ``pubDate`` (feeds list newest-first), so the assigned 1-based index is
    stable across runs regardless of feed ordering.  Items without a usable
    audio ``<enclosure>`` are skipped.
    """
    root = ET.fromstring(xml_bytes)
    seen: set[str] = set()
    raw: list[dict] = []
    for item in root.iter("item"):
        enc = item.find("enclosure")
        if enc is None or not enc.get("url"):
            continue
        guid_el = item.find("guid")
        title_el = item.find("title")
        guid = (guid_el.text if guid_el is not None else None) or enc.get("url")
        guid = guid.strip()
        if guid in seen:
            continue
        seen.add(guid)
        dur_el = item.find("itunes:duration", _ITUNES_NS)
        pub_el = item.find("pubDate")
        raw.append({
            "guid": guid,
            "title": (title_el.text or "").strip() if title_el is not None else "",
            "url": enc.get("url").strip(),
            "bytes_declared": int(enc.get("length") or 0),
            "mime": (enc.get("type") or "").strip().lower(),
            "duration_s": _parse_duration(dur_el.text if dur_el is not None else None),
            "published": _to_iso(pub_el.text if pub_el is not None else None),
        })

    # Oldest first; items with an unparseable date sort last but keep order.
    raw.sort(key=lambda r: (r["published"] == "", r["published"]))

    episodes: list[Episode] = []
    for i, r in enumerate(raw, start=1):
        ext = _EXT_BY_TYPE.get(r["mime"], _guess_ext(r["url"]))
        filename = f"ep{i:02d}_{_slugify(r['title'])}{ext}"
        episodes.append(Episode(index=i, filename=filename, **r))
    return episodes


def _guess_ext(url: str) -> str:
    """Guess an audio extension from a URL path; default to ``.m4a``."""
    path = urllib.parse.urlparse(url).path
    for ext in (".m4a", ".mp3", ".wav", ".flac", ".ogg"):
        if path.lower().endswith(ext):
            return ext
    return ".m4a"


def _http_get(url: str) -> bytes:
    """GET *url* and return the body, with a descriptive User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _download_stream(url: str, dest: Path) -> tuple[int, str]:
    """Stream *url* to *dest*, returning ``(bytes_written, sha256_hex)``.

    The body is written to a temporary sibling and renamed on success so an
    interrupted download never leaves a truncated file in place.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    total = 0
    last_exc: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            digest = hashlib.sha256()
            total = 0
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp, \
                    open(tmp, "wb") as handle:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
            tmp.replace(dest)
            return total, digest.hexdigest()
        except Exception as exc:  # network flakiness: retry then re-raise
            last_exc = exc
            print(f"    attempt {attempt}/{_RETRIES} failed: {exc}", file=sys.stderr)
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"download failed after {_RETRIES} attempts: {url}") from last_exc


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at *path*, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict:
    """Return the manifest at *path*, or ``{}`` when absent.

    Raises
    ------
    RuntimeError
        If the file exists but cannot be read or parsed. Treating a corrupt
        manifest as empty would let the run replace every committed
        checksum with whatever it downloads.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read the existing manifest {path}: {exc}") from exc


def _prior_record(manifest: dict, guid: str) -> dict:
    """Return the manifest entry for *guid*, or ``{}`` when there is none."""
    for ep in manifest.get("episodes", []):
        if ep.get("guid") == guid:
            return ep
    return {}


def _known_sha(manifest: dict, guid: str) -> str | None:
    """Return the recorded SHA-256 for *guid*, or ``None``."""
    return _prior_record(manifest, guid).get("sha256")


def fetch(dest: Path, podcast_id: str, limit: int | None, list_only: bool,
          accept_new: bool = False,
          reference_manifest: Path | None = None) -> dict:
    """Resolve the feed and download episodes, returning the manifest dict.

    Every file is checked against the SHA-256 and byte count the existing
    manifest records for its GUID, which is what makes the corpus
    reproducible rather than merely re-downloadable. The existing manifest
    is ``dest/manifest.json``, or, when *dest* has none, the committed
    record (*reference_manifest*):

    * a file already on disk that matches is left alone (``cached``);
    * a file on disk with no recorded checksum is hashed and recorded, but
      reported as ``cached_unverified``, since nothing vouches for it;
    * a fresh download that differs from the record (a re-encoded or
      ad-inserted episode, which podcast hosts do) is kept as
      ``<file>.mismatch`` and the run fails, unless *accept_new* is set, in
      which case the new checksum is recorded with the old one beside it;
    * an episode not fetched this run (``--limit`` or ``--list-only``)
      keeps its recorded checksum and byte count instead of losing them.

    Parameters
    ----------
    dest:
        Corpus directory; audio goes to ``dest/audio``.
    podcast_id:
        Apple Podcasts numeric id.
    limit:
        Download at most this many episodes. A limited run never rewrites
        an existing ``manifest.json``; it writes ``manifest.limited.json``
        beside it, so a smoke test cannot disturb the committed record.
    list_only:
        Resolve and enumerate without downloading or writing anything.
    accept_new:
        Record a changed checksum instead of failing on it.
    reference_manifest:
        The record to verify against when *dest* holds no manifest;
        ``None`` means the repository's ``data/codex_mentis/manifest.json``.
        The manifest written is always *dest*'s own.

    Returns
    -------
    dict
        The manifest.

    Raises
    ------
    RuntimeError
        On a checksum or size mismatch without *accept_new*; the manifest
        is then not written. Also on an unreadable existing manifest.

    Side effects: network access (iTunes lookup, RSS feed, audio), writes
    audio files and a manifest under *dest*, prints progress.
    """
    feed_url = resolve_feed_url(podcast_id)
    print(f"Feed:      {feed_url}", flush=True)
    # The manifest always describes the whole feed, whatever *limit* says.
    # A limit caps what this run downloads, not what the corpus contains;
    # truncating the episode list here would silently rewrite the manifest
    # to claim the corpus is smaller than it is, and a later smoke test with
    # --limit would destroy the record of a full fetch.
    episodes = parse_feed(_http_get(feed_url))
    if limit is not None:
        print(f"Episodes:  {len(episodes)} in feed; "
              f"downloading at most {limit}", flush=True)
    else:
        print(f"Episodes:  {len(episodes)}", flush=True)

    audio_dir = dest / "audio"
    manifest_path = dest / "manifest.json"
    own = _load_manifest(manifest_path)
    prior = own
    if not own:
        reference = (reference_manifest if reference_manifest is not None
                     else _COMMITTED_MANIFEST)
        prior = _load_manifest(reference)
        if prior:
            print(f"Verifying: against {reference} ({dest} has no manifest)",
                  flush=True)

    records: list[dict] = []
    mismatches: list[str] = []
    total_bytes = 0
    total_secs = 0
    downloads = 0
    for ep in episodes:
        target = audio_dir / ep.filename
        previous = _prior_record(prior, ep.guid)
        known = previous.get("sha256")
        known_bytes = previous.get("bytes")
        # An episode this run does not fetch keeps what the record says.
        status = "listed"
        sha = known
        nbytes = known_bytes if known_bytes is not None else ep.bytes_declared
        extra: dict = {}
        if not list_only:
            audio_dir.mkdir(parents=True, exist_ok=True)
            on_disk = _sha256_file(target) if target.exists() else None
            if on_disk is not None and known is not None and on_disk == known:
                nbytes, status = target.stat().st_size, "cached"
            elif on_disk is not None and known is None:
                # Nothing to verify against: record it, but say so.
                sha, nbytes = on_disk, target.stat().st_size
                status = "cached_unverified"
                print(f"  [{ep.index:02d}] no recorded checksum; "
                      f"{ep.filename} recorded unverified", file=sys.stderr)
            elif limit is not None and downloads >= limit:
                # Beyond this run's download budget: recorded as part of the
                # corpus, with its recorded checksum, but not fetched now.
                status = "not_downloaded"
            else:
                print(f"  [{ep.index:02d}] {ep.title[:56]}", flush=True)
                new_bytes, new_sha = _download_stream(ep.url, target)
                downloads += 1
                changed = known is not None and (
                    new_sha != known
                    or (known_bytes is not None and new_bytes != known_bytes))
                if changed and not accept_new:
                    held = target.with_name(target.name + ".mismatch")
                    target.replace(held)
                    mismatches.append(
                        f"{ep.filename}: recorded sha256 {known[:12]} "
                        f"({known_bytes} bytes), downloaded {new_sha[:12]} "
                        f"({new_bytes} bytes); kept as {held.name}")
                    status = "mismatch"
                else:
                    if changed:
                        extra = {"sha256_previous": known,
                                 "bytes_previous": known_bytes}
                        print(f"  [{ep.index:02d}] checksum changed; recorded "
                              "the new one (--accept-new)", file=sys.stderr)
                    sha, nbytes, status = new_sha, new_bytes, "downloaded"
        total_bytes += nbytes or 0
        total_secs += ep.duration_s
        rec = asdict(ep)
        rec.update({"sha256": sha, "bytes": nbytes, "status": status})
        rec.update(extra)
        records.append(rec)
        print(f"       {ep.filename}  "
              f"{(nbytes or 0) / 1e6:.1f} MB  {ep.duration_s // 60}m  {status}",
              flush=True)

    manifest = {
        "podcast": {
            "id": podcast_id,
            "title": "Codex Mentis: Science and technology to study cognition",
            "author": "Pablo Bernabeu",
            "source": f"https://podcasts.apple.com/podcast/id{podcast_id}",
            "feed_url": feed_url,
            "generator": "NotebookLM (synthetic two-voice dialogue)",
            "note": "Author-owned; redistribution-clean; no gold transcript.",
        },
        "n_episodes": len(records),
        "total_bytes": total_bytes,
        "total_duration_s": total_secs,
        "episodes": records,
    }
    if mismatches:
        raise RuntimeError(
            "downloaded audio differs from the recorded checksums; the "
            "manifest was not rewritten. Rerun with --accept-new to record "
            "the new files.\n  " + "\n  ".join(mismatches))
    if not list_only:
        out_path = manifest_path
        # Only a manifest already in *dest* is protected from a smoke test;
        # the reference record elsewhere is never written.
        if limit is not None and own:
            out_path = dest / "manifest.limited.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nManifest:  {out_path}")
    print(f"Total:     {total_bytes / 1e6:.0f} MB, {total_secs // 60} min "
          f"across {len(records)} episodes")
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.fetch_codex_mentis",
        description="Reproducibly download the Codex Mentis podcast as an ASR "
                    "evaluation corpus (manifest with SHA-256 per episode).",
    )
    p.add_argument("--dest", type=Path, default=_DEFAULT_DEST,
                   help="Destination directory (default: %(default)s).")
    p.add_argument("--podcast-id", default=_PODCAST_ID, dest="podcast_id",
                   help="Apple Podcasts numeric id (default: %(default)s).")
    p.add_argument("--limit", type=int, default=None,
                   help="Download only the first N episodes (smoke test).")
    p.add_argument("--list-only", action="store_true", dest="list_only",
                   help="Resolve and enumerate episodes without downloading.")
    p.add_argument("--accept-new", action="store_true", dest="accept_new",
                   help="Record a download whose checksum differs from the "
                        "manifest instead of failing. Use only after "
                        "deciding that the changed audio is wanted.")
    return p


def main(argv: list[str] | None = None) -> int:
    """Run :func:`fetch` from the command line.

    Parameters
    ----------
    argv:
        Arguments to parse instead of ``sys.argv[1:]``: ``--dest``,
        ``--podcast-id``, ``--limit``, ``--list-only`` and ``--accept-new``.

    Returns
    -------
    int
        0 on success and 1 on any failure, including a checksum mismatch,
        with the reason on stderr.

    Side effects
    ------------
    Downloads episode audio over the network into ``--dest`` and writes the
    manifest there (``manifest.limited.json`` for a ``--limit`` run over an
    existing manifest); see :func:`fetch`. Reconfigures stdout to UTF-8.
    """
    args = _build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 0:
        print("  Error: --limit must be zero or more", file=sys.stderr)
        return 1
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        fetch(args.dest, args.podcast_id, args.limit, args.list_only,
              accept_new=args.accept_new)
    except Exception as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
