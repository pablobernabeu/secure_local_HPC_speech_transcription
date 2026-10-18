"""The masking log round-trips through ``save_replacement_log``.

Audit findings T1-01 and EPRIV-07: the masker added a ``source`` key to
every name row, but the CSV writer still declared five columns, so saving
any log that masked a name raised ``ValueError`` and aborted the run before
the masked transcript was written.
"""

from __future__ import annotations

import contextlib
import csv
import io


def _masker(m, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return m.create_enhanced_name_masker(**kwargs)


def test_log_with_title_and_names_round_trips(transcription_module, tmp_path,
                                              monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    mask, get_log = _masker(m)
    masked = mask("Mr Smith met Sarah.", "rec.wav")
    assert "Smith" not in masked and "Sarah" not in masked

    log = get_log()
    assert {row['source'] for row in log} == {'title', 'dictionary'}
    with contextlib.redirect_stdout(io.StringIO()):
        m.save_replacement_log(log, "rec.wav")

    path = tmp_path / "name_masking_logs" / "name_replacements_rec.csv"
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert tuple(reader.fieldnames) == m.REPLACEMENT_LOG_FIELDS
    assert 'source' in reader.fieldnames
    assert [r['original'] for r in rows] == ['Mr', 'Smith', 'Sarah.']
    assert [r['source'] for r in rows] == ['title', 'dictionary', 'dictionary']
    assert not list((tmp_path / "name_masking_logs").glob("*.tmp"))


def test_ner_rows_record_their_stage(transcription_module, tmp_path,
                                     monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)

    class _StubDetector:
        def tokens_in(self, sentence):
            return {"zzyzxq"}

    mask, get_log = _masker(m, ner_detector=_StubDetector())
    mask("We met Zzyzxq today.", "rec.wav")
    log = get_log()
    assert [r['source'] for r in log] == ['ner']
    with contextlib.redirect_stdout(io.StringIO()):
        m.save_replacement_log(log, "rec.wav")
    text = (tmp_path / "name_masking_logs"
            / "name_replacements_rec.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0].endswith(",source")
    assert text.splitlines()[1].endswith(",ner")


def test_failed_write_leaves_no_partial_log(transcription_module, tmp_path,
                                            monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    bad = [{'filename': 'x.wav', 'order': 1, 'original': 'Sarah',
            'replacement': '[NAME]', 'context_sentence': 'Sarah.',
            'source': 'dictionary', 'unexpected': 1}]
    try:
        m.save_replacement_log(bad, "x.wav")
    except ValueError:
        pass
    else:  # pragma: no cover - the unknown key must be refused
        raise AssertionError("an unknown column should fail loudly")
    assert list((tmp_path / "name_masking_logs").iterdir()) == []
