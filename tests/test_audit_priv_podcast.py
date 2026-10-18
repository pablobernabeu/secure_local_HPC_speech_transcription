"""Audit fixes EPRIV-24 and EPRIV-20 in ``evaluation.benchmark_podcast``.

A masker that failed to load or raised was replaced by the identity, and
the unmasked text then scored a redaction rate of 0.0 that read as a
measurement. The placeholder pattern also counted Whisper's own bracketed
tags as redactions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import benchmark_podcast as bp  # noqa: E402

_T = {"text": "Hello Ada and [MUSIC] Bo."}


def test_raising_masker_is_recorded_not_scored():
    def boom(text):
        raise RuntimeError("no database")

    m = bp.masking_metrics(_T, boom)
    assert m["redaction_rate"] is None and m["n_redacted"] is None
    assert "no database" in m["masking_error"]


def test_missing_masker_is_recorded_not_scored():
    m = bp.masking_metrics(_T, None)
    assert m["redaction_rate"] is None
    assert m["masking_error"] == "masker unavailable"


def test_only_masker_placeholders_count():
    m = bp.masking_metrics(_T, lambda t: t.replace("Ada", "[NAME]"))
    assert m["n_redacted"] == 1          # [MUSIC] is not a redaction
    assert "masking_error" not in m


def test_cli_fails_without_a_masker(tmp_path, monkeypatch):
    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps(_T), encoding="utf-8")
    import transcription

    def broken(*args, **kwargs):
        raise RuntimeError("database missing")

    monkeypatch.setattr(transcription, "create_enhanced_name_masker", broken)
    out = tmp_path / "out"
    assert bp.main(["--transcript", str(transcript),
                    "--output-dir", str(out)]) == 3
    assert not (out / "podcast_eval_summary.json").exists()
    assert bp.main(["--transcript", str(transcript), "--output-dir", str(out),
                    "--allow-no-masker"]) == 0
    summary = json.loads((out / "podcast_eval_summary.json").read_text("utf-8"))
    assert summary["per_file"][0]["masking"]["redaction_rate"] is None


def test_committed_case_study_count_is_unchanged():
    """The committed ep05 text gives the committed n_redacted with the new
    pattern, since it holds no bracketed tags of its own. The text is the
    August run's (job 8441879) and the summary job 9124852's. Their texts
    differ in nine places, none a masked name or title, and the August
    text has 5,384 tokens to the re-run's 5,382, so the redactions agree
    and their rates round alike."""
    import contextlib
    import io
    import transcription

    raw = (PROJECT_ROOT / "output" / "case_study" / "ep05_raw_text.txt")
    committed = json.loads((PROJECT_ROOT / "output" / "case_study"
                            / "podcast_eval_summary.json").read_text("utf-8"))
    with contextlib.redirect_stdout(io.StringIO()):
        mask, _ = transcription.create_enhanced_name_masker()
    m = bp.masking_metrics({"text": raw.read_text(encoding="utf-8")}, mask)
    summary = committed["per_file"][0]["masking"]
    assert (m["n_redacted"], m["redaction_rate"]) == \
        (summary["n_redacted"], summary["redaction_rate"])
    assert (m["n_tokens"], summary["n_tokens"]) == (5384, 5382)
