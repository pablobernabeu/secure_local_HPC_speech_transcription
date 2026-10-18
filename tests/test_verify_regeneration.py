"""Cross-platform allowances must still reject changed scientific inputs."""

import hashlib
import json

import pytest

from tools import verify_regeneration as gate


def _hash(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def summaries(tmp_path):
    dictionary = tmp_path / "curated_names.csv"
    lf = b"name,language,type\nAhmed,arabic,first\nAlice,english,first\n"
    dictionary.write_bytes(lf)
    paths = []
    for folder, data in [("produced", lf), ("committed", lf.replace(b"\n", b"\r\n"))]:
        path = tmp_path / folder / "masking_summary.json"
        path.parent.mkdir()
        path.write_text(json.dumps({
            "seed": 42, "overall": {"recall": 0.5, "hits": 1},
            "curated_names_sha256": _hash(data),
            "run_metadata": {"commit": folder},
        }), encoding="utf-8")
        paths.append(path)
    return *paths, dictionary


@pytest.mark.parametrize("checkout_ending", [b"\n", b"\r\n"])
def test_same_dictionary_accepts_both_checkout_endings(summaries, checkout_ending):
    produced, committed, dictionary = summaries
    dictionary.write_bytes(dictionary.read_bytes().replace(b"\n", checkout_ending))
    assert not gate.same_but_volatile(produced, committed)
    assert gate.same_masking_but_dictionary_endings(produced, committed, dictionary)
    assert gate.same_masking_but_dictionary_endings(committed, produced, dictionary)


@pytest.mark.parametrize("edit", [
    lambda data: data.replace(b"Ahmed", b"Ahmad"),
    lambda data: data.replace(b"arabic", b"english"),
    lambda data: data + b"Bob,english,first\n",
    lambda data: b"\n".join(reversed(data.rstrip(b"\n").split(b"\n"))) + b"\n",
])
def test_real_dictionary_changes_are_not_line_ending_changes(summaries, edit):
    produced, committed, dictionary = summaries
    dictionary.write_bytes(edit(dictionary.read_bytes()))
    # Simulate a producer that records the new input hash while its counts
    # happen to remain the same: the original archived hash must fail.
    value = json.loads(produced.read_text(encoding="utf-8"))
    value["curated_names_sha256"] = _hash(dictionary.read_bytes())
    produced.write_text(json.dumps(value), encoding="utf-8")
    assert not gate.same_masking_but_dictionary_endings(produced, committed, dictionary)


@pytest.mark.parametrize("invalid_hash", [None, [], {}, "not-a-hash", "0" * 64])
def test_missing_or_unrelated_dictionary_hashes_fail(summaries, invalid_hash):
    produced, committed, dictionary = summaries
    value = json.loads(produced.read_text(encoding="utf-8"))
    if invalid_hash is None:
        value.pop("curated_names_sha256")
    else:
        value["curated_names_sha256"] = invalid_hash
    produced.write_text(json.dumps(value), encoding="utf-8")
    assert not gate.same_masking_but_dictionary_endings(produced, committed, dictionary)


def test_changed_measurement_is_not_excused_by_dictionary_endings(summaries):
    produced, committed, dictionary = summaries
    value = json.loads(produced.read_text(encoding="utf-8"))
    value["overall"]["hits"] = 2
    produced.write_text(json.dumps(value), encoding="utf-8")
    assert not gate.same_masking_but_dictionary_endings(produced, committed, dictionary)


def test_allowance_is_limited_to_dictionary_masking_summary(summaries):
    produced, committed, dictionary = summaries
    other = produced.with_name("masking_summary_ner.json")
    other.write_bytes(produced.read_bytes())
    assert not gate.same_masking_but_dictionary_endings(other, committed, dictionary)


def test_missing_dictionary_or_invalid_json_fails(summaries):
    produced, committed, dictionary = summaries
    assert not gate.same_masking_but_dictionary_endings(
        produced, committed, dictionary.with_name("missing.csv"))
    produced.write_text("{broken", encoding="utf-8")
    assert not gate.same_masking_but_dictionary_endings(produced, committed, dictionary)


def test_gate_reports_the_specific_allowance(summaries, monkeypatch, capsys):
    produced, committed, dictionary = summaries
    monkeypatch.setattr(gate, "REPO", dictionary.parent)
    data_dir = dictionary.parent / "data"
    data_dir.mkdir()
    (data_dir / dictionary.name).write_bytes(dictionary.read_bytes())
    monkeypatch.setattr(gate, "COMMITTED", committed.parent)
    monkeypatch.setattr(gate, "_jobs", lambda out, skip: [
        ("masking", [], {"masking_summary.json": produced}),
    ])
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs:
                        type("Result", (), {"returncode": 0})())
    assert gate.main([]) == 0
    assert "dictionary LF/CRLF digest" in capsys.readouterr().out
