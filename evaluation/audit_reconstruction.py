#!/usr/bin/env python3
"""
Check that a reconstructed meeting's audio agrees with its reference.

The diarisation benchmark rests on one premise: that each utterance's
audio is written at the position its annotation claims. An error in that
arithmetic, an off-by-one in the sample offset or a systematic shift,
would not raise anything. It would quietly move every boundary and turn
up as diarisation error, where it would be indistinguishable from a
failure of the model.

The check here is deliberately independent of the code that built the
reconstruction: it re-derives speech activity from the waveform by short-
term energy and compares that with the reference annotation. Two figures
follow.

``speech_coverage``
    The proportion of annotated speech time that carries audible signal.
    A low value means audio is missing from where the reference says
    someone is speaking.

``silence_purity``
    The proportion of unannotated time that carries no signal. A low
    value means audio has landed outside its annotation.

``silence_exact_zero``
    The proportion of unannotated frames in which every sample is exactly
    zero. ``silence_purity`` counts a frame as silent when it is below an
    energy floor (2 per cent of the robust peak), which is not the same as
    carrying no signal at all; this figure is what a claim of "no signal
    whatever outside the annotated regions" rests on. The reconstruction
    writes nothing outside a turn, so it should be one, less any frame a
    rounded sample offset reaches into.

Both coverage and purity should be close to one. Energy-based detection
is not a voice activity detector, so neither will reach it exactly: quiet
consonants and pauses inside a turn read as silence, which lowers coverage
without anything being wrong. The check is for gross misalignment, and a
systematic offset is reported directly by ``best_shift_ms``, obtained by
scoring the alignment over a range of candidate shifts. Anything other
than zero means the reconstruction is displaced.

The manuscript cites this audit, so ``--json`` writes a record that can be
archived beside the results (EDER-13): the per-meeting rows, the cache and
manifest audited, the parameters, a summary, and the code commit and
package versions (:func:`provenance.run_metadata`).

Usage::

    python -m evaluation.audit_reconstruction "$DATA/ami_cache/test_timeline_full"
    python -m evaluation.audit_reconstruction CACHE_DIR --meetings EN2002a
    python -m evaluation.audit_reconstruction "$DATA/ami_cache/test_timeline_full" \\
        --json output/evaluation/reconstruction_audit_test.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

#: Frame length for the short-term energy envelope, in seconds.
FRAME_S = 0.01
#: A frame is treated as carrying signal when its root-mean-square exceeds
#: this fraction of the recording's own robust peak. Relative rather than
#: absolute, because the reconstruction applies a per-meeting gain.
#: TODO: justify (source unknown). No calibration of the 2% value is
#: recorded; a sensitivity check (best_shift_ms stable for floors of
#: 0.01-0.05) would support it.
ENERGY_FLOOR = 0.02
#: Candidate shifts scored when looking for a systematic displacement.
#: TODO: justify (source unknown). The grid spans +/-200 ms, one to twenty
#: frames; no record says why a displacement beyond 200 ms was ruled out.
SHIFTS_MS = (-200, -100, -50, -20, -10, 0, 10, 20, 50, 100, 200)


def energy_envelope(audio: np.ndarray, sample_rate: int,
                    frame_s: float = FRAME_S) -> np.ndarray:
    """Return the per-frame root-mean-square amplitude of *audio*.

    Parameters
    ----------
    audio:
        Mono samples, one axis.
    sample_rate:
        Samples per second of *audio*.
    frame_s:
        Frame length in seconds; frames do not overlap, and a trailing
        partial frame is dropped.

    Returns
    -------
    numpy.ndarray
        One float64 RMS value per whole frame; empty when *audio* is
        shorter than one frame.
    """
    frame = max(1, int(round(frame_s * sample_rate)))
    usable = (audio.size // frame) * frame
    if usable == 0:
        return np.zeros(0, dtype=np.float64)
    frames = audio[:usable].reshape(-1, frame).astype(np.float64)
    return np.sqrt(np.mean(frames * frames, axis=1))


def reference_mask(reference, n_frames: int, frame_s: float = FRAME_S) -> np.ndarray:
    """Return a boolean frame mask of annotated speech.

    Parameters
    ----------
    reference:
        Iterable of mappings with ``start`` and ``end`` in seconds.
    n_frames:
        Length of the mask, normally the envelope length.
    frame_s:
        Frame length in seconds, as used for the envelope.

    Returns
    -------
    numpy.ndarray
        Boolean array of length *n_frames*, True where any segment covers
        the frame. Segment edges are widened outwards to whole frames and
        clipped to the mask.
    """
    mask = np.zeros(n_frames, dtype=bool)
    for segment in reference:
        start = int(np.floor(float(segment["start"]) / frame_s))
        end = int(np.ceil(float(segment["end"]) / frame_s))
        start = max(0, min(start, n_frames))
        end = max(0, min(end, n_frames))
        if end > start:
            mask[start:end] = True
    return mask


def audit_meeting(audio: np.ndarray, sample_rate: int, reference) -> dict:
    """Compare energy-derived activity with the reference annotation.

    Parameters
    ----------
    audio:
        Mono samples of one reconstructed meeting.
    sample_rate:
        Samples per second of *audio*.
    reference:
        The meeting's reference segments (``start``/``end`` in seconds).

    Returns
    -------
    dict
        ``{"frames": n, "checked": False}`` when the audio is shorter than
        a frame or the reference is empty. Otherwise ``checked`` (True),
        ``frames``, ``duration_s``, ``speech_coverage``,
        ``silence_purity`` and ``silence_exact_zero`` (each ``None`` when
        there is no speech or no silence to score),
        ``agreement_at_zero_shift``, ``best_shift_ms`` and
        ``agreement_at_best_shift``.
    """
    rms = energy_envelope(audio, sample_rate)
    if rms.size == 0 or not reference:
        return {"frames": int(rms.size), "checked": False}

    # A robust peak rather than the maximum, so one transient cannot set
    # the floor for the whole recording.
    peak = float(np.percentile(rms, 99.5))
    active = rms > (ENERGY_FLOOR * peak) if peak > 0 else np.zeros_like(rms, bool)
    speech = reference_mask(reference, rms.size)

    def _score(shift_frames: int) -> float:
        shifted = np.roll(speech, shift_frames)
        return float(np.mean(shifted == active))

    ms_per_frame = FRAME_S * 1000
    scored = {ms: _score(int(round(ms / ms_per_frame))) for ms in SHIFTS_MS}
    best_shift = max(scored, key=scored.get)

    n_speech = int(speech.sum())
    n_silence = int((~speech).sum())
    return {
        "checked": True,
        "frames": int(rms.size),
        "duration_s": round(rms.size * FRAME_S, 2),
        "speech_coverage": round(float(active[speech].mean()), 4) if n_speech else None,
        "silence_purity": round(float((~active)[~speech].mean()), 4) if n_silence else None,
        # An RMS of exactly zero means every sample in the frame is zero:
        # a float32 sample's square cannot underflow in float64.
        "silence_exact_zero": (round(float((rms[~speech] == 0.0).mean()), 4)
                               if n_silence else None),
        "agreement_at_zero_shift": round(scored[0], 4),
        "best_shift_ms": best_shift,
        "agreement_at_best_shift": round(scored[best_shift], 4),
    }


def audit_cache(cache_dir: Path, meetings=None) -> list[dict]:
    """Audit every reconstruction in *cache_dir*.

    Parameters
    ----------
    cache_dir:
        A reconstruction cache written by evaluation.benchmark_der, holding
        ``manifest.json`` (``manifest.partial.json`` for a build stopped by
        ``--limit-meetings``) and one ``<meeting>.wav`` and
        ``<meeting>.json`` per meeting.
    meetings:
        Optional meeting ids to restrict the audit to.

    Returns
    -------
    list of dict
        One :func:`audit_meeting` row per audited meeting, with
        ``meeting_id`` added.

    Raises
    ------
    SystemExit
        When *cache_dir* holds neither manifest.

    Side effects
    ------------
    Reads the cached audio and prints one line per meeting, and a note
    when the cache is a partial build.
    """
    import soundfile as sf

    from evaluation.benchmark_der import _MANIFEST, _PARTIAL_MANIFEST

    manifest_path = cache_dir / _MANIFEST
    if not manifest_path.exists():
        # The benchmark never reads a partial build as the corpus, but its
        # alignment can still be checked, which is what a smoke-test cache
        # is for; auditing one used to need a full build of every meeting.
        manifest_path = cache_dir / _PARTIAL_MANIFEST
        if not manifest_path.exists():
            raise SystemExit(f"no {_MANIFEST} or {_PARTIAL_MANIFEST} in {cache_dir}")
        print(f"  note: partial cache (built with --limit-meetings), "
              f"auditing the meetings in {_PARTIAL_MANIFEST}", flush=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wanted = set(meetings) if meetings else None

    rows = []
    for mid in manifest["meetings"]:
        if wanted and mid not in wanted:
            continue
        audio, sample_rate = sf.read(cache_dir / f"{mid}.wav", dtype="float32")
        payload = json.loads((cache_dir / f"{mid}.json").read_text(encoding="utf-8"))
        row = audit_meeting(np.asarray(audio, dtype=np.float32), sample_rate,
                            payload["reference"])
        row["meeting_id"] = mid
        rows.append(row)
        print(f"  {mid:<10} coverage={row.get('speech_coverage')}  "
              f"purity={row.get('silence_purity')}  "
              f"best shift={row.get('best_shift_ms')} ms  "
              f"(agreement {row.get('agreement_at_zero_shift')} at zero)",
              flush=True)
    return rows


def summarise(rows: list[dict]) -> dict:
    """Return the corpus-level figures a report of the audit would quote.

    Parameters
    ----------
    rows:
        :func:`audit_meeting` rows with ``meeting_id``.

    Returns
    -------
    dict
        ``n_meetings``, ``n_checked``, ``n_best_shift_zero``, ``displaced``
        (meeting ids whose best shift is not zero), and the minimum over
        checked meetings of ``speech_coverage``, ``silence_purity`` and
        ``silence_exact_zero`` (``None`` when no meeting had the figure).
    """
    checked = [r for r in rows if r.get("checked")]

    def lowest(key):
        values = [r[key] for r in checked if r.get(key) is not None]
        return min(values) if values else None

    return {
        "n_meetings": len(rows),
        "n_checked": len(checked),
        "n_best_shift_zero": sum(1 for r in checked if r["best_shift_ms"] == 0),
        "displaced": [r["meeting_id"] for r in checked if r["best_shift_ms"]],
        "min_speech_coverage": lowest("speech_coverage"),
        "min_silence_purity": lowest("silence_purity"),
        "min_silence_exact_zero": lowest("silence_exact_zero"),
    }


def audit_record(cache_dir: Path, rows: list[dict], run_meta: dict | None = None) -> dict:
    """Return the archivable record of one audit run (EDER-13).

    *run_meta* is the :func:`provenance.run_metadata` a caller about to
    write the record read first, leaving the record's own file out of the
    dirty check (:func:`main` does). ``None`` reads it here, which counts a
    rewritten copy of the record in the checkout as a change.

    Side effects
    ------------
    Reads the cache's manifest and, without *run_meta*, asks git for the
    commit (:func:`provenance.run_metadata`).
    """
    from evaluation.benchmark_der import _MANIFEST, _PARTIAL_MANIFEST
    from provenance import run_metadata

    if run_meta is None:
        run_meta = run_metadata()
    manifest = {}
    for name in (_MANIFEST, _PARTIAL_MANIFEST):
        if (cache_dir / name).exists():
            manifest = json.loads((cache_dir / name).read_text(encoding="utf-8"))
            manifest = {k: v for k, v in manifest.items() if k != "meetings"}
            manifest["file"] = name
            break
    return {
        "cache_dir": Path(cache_dir).as_posix(),
        "manifest": manifest,
        "parameters": {"frame_s": FRAME_S, "energy_floor": ENERGY_FLOOR,
                       "shifts_ms": list(SHIFTS_MS)},
        "summary": summarise(rows),
        "run": run_meta,
        "meetings": rows,
    }


def main(argv=None) -> int:
    """Audit a cache from the command line.

    Returns 0 when every audited meeting's best shift is zero, and 1 when
    any is displaced or nothing was audited. Side effects: reads the
    cache, prints a line per meeting and, with ``--json``, writes the
    record of :func:`audit_record`.
    """
    parser = argparse.ArgumentParser(
        description="Verify reconstructed AMI meetings against their references.")
    parser.add_argument("cache_dir", type=Path,
                        help="a <split>_<mode>_<cap> directory holding wavs, "
                             "per-meeting JSON and manifest.json (or the "
                             "manifest.partial.json of a limited build)")
    parser.add_argument("--meetings", nargs="+", default=None,
                        help="audit only these meeting ids")
    parser.add_argument("--json", dest="json_out", type=Path, default=None,
                        help="also write the audit record (per-meeting rows, "
                             "summary, parameters, manifest and commit) here")
    args = parser.parse_args(argv)

    rows = audit_cache(args.cache_dir, args.meetings)
    if not rows:
        print("nothing audited")
        return 1

    summary = summarise(rows)
    print(f"\n{summary['n_meetings']} meetings audited.")
    print(f"  best shift is zero for {summary['n_best_shift_zero']}/"
          f"{summary['n_checked']}")
    print(f"  lowest silence purity {summary['min_silence_purity']}, "
          f"lowest exact-zero share of silence {summary['min_silence_exact_zero']}")
    if summary["displaced"]:
        print(f"  DISPLACED: {', '.join(summary['displaced'])}")
    if args.json_out:
        from provenance import run_metadata
        # Read before the record is written, leaving it out of the dirty
        # check, as provenance.write_sidecar does for the CSV-only writers.
        # Without the ignore list, a second audit in place counted the
        # first one's record as uncommitted code (audit finding OUTPUTS-12).
        run_meta = run_metadata(ignore=(args.json_out,))
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(audit_record(args.cache_dir, rows, run_meta), indent=2),
            encoding="utf-8")
        print(f"  written to {args.json_out}")
    return 1 if summary["displaced"] else 0


if __name__ == "__main__":
    sys.exit(main())
