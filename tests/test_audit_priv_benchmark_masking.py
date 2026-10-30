"""Direct tests for masking-benchmark case construction (EPRIV-11, TESTS-11).

The existing benchmark tests drive only ``_score_case`` and ``summarise`` on
hand-built cases. Case construction, the out-of-dictionary partition, the
placeholder stripping and the effective-dictionary labelling set the numbers
in masking_summary*.json, so they are pinned here, including one scoring
run with the real masker.
"""

from __future__ import annotations

import contextlib
import csv
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import benchmark_masking as bm


def _csv(tmp_path: Path, rows) -> Path:
    path = tmp_path / "names.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "type", "language"])
        writer.writerows(rows)
    return path


def test_build_cases_crosses_every_factor(tmp_path):
    path = _csv(tmp_path, [("Aaron", "first", "english"),
                           ("Smith", "last", "english"),
                           # A held-out name that is in this CSV must be
                           # treated as in-dictionary, not out_of_db.
                           ("Kenji", "first", "chinese")])
    cases = bm.build_cases(seed=1, n_per_cell=1, csv_path=path)
    in_db = [c for c in cases if c.in_db]
    out_db = [c for c in cases if not c.in_db]
    per_name = len(bm._TEMPLATES) * len(bm._CASINGS) * len(bm._MORPHOLOGIES)
    assert len(in_db) == 3 * per_name
    assert {c.name for c in in_db} == {"Aaron", "Smith", "Kenji"}
    # No held-out name that is in the CSV survives into out_of_db.
    assert "Kenji" not in {c.name for c in out_db}
    assert {c.casing for c in cases} == {"title", "lower"}
    for c in cases:
        assert c.gold_token in c.sentence.split()
        assert c.gold_token.endswith("'s") == (c.morphology == "possessive")
        if c.casing == "lower":
            assert c.gold_token == c.gold_token.lower()


def test_build_cases_is_seeded(tmp_path):
    path = _csv(tmp_path, [(n, "first", "english")
                           for n in ("Aaron", "Bruno", "Carla", "Delia")])
    a = [c.name for c in bm.build_cases(7, 2, csv_path=path)]
    b = [c.name for c in bm.build_cases(7, 2, csv_path=path)]
    assert a == b


def test_filtered_common_word_names_get_their_own_cell(tmp_path):
    path = _csv(tmp_path, [("Grace", "first", "english")])
    cases = bm.build_cases(seed=1, n_per_cell=1, csv_path=path)
    grace = [c for c in cases if c.name == "Grace"]
    assert grace and all(c.in_db and not c.in_effective_dict for c in grace)
    summary = bm.summarise(cases, 1, 1)
    assert "in_csv_filtered_common_word" in summary["by_in_db"]
    assert "in_db" not in summary["by_in_db"]


def test_default_seed_samples_no_filtered_name():
    cases = bm.build_cases(bm._DEFAULT_SEED, bm._DEFAULT_N_PER_CELL)
    assert all(c.in_effective_dict for c in cases)


def test_effective_dictionary_excludes_common_words(transcription_module):
    with contextlib.redirect_stdout(io.StringIO()):
        kept = transcription_module.filter_problematic_names(
            {"grace", "aaron", "will", "jo"})
    assert kept == {"aaron"}


def test_strip_helpers():
    assert bm._strip_marker("[NAME]'.") == "[NAME]"
    assert bm._strip_marker("[SURNAME],") == "[SURNAME]"
    assert bm._strip_marker("[TITLE]") == "[TITLE]"
    assert bm._PLACEHOLDER_RE.fullmatch(bm._strip_marker("[TITLE]"))
    assert bm._strip_token("Dr.") == "dr"
    assert bm._apply_casing("aaron", "title") == "Aaron"
    assert bm._apply_casing("Aaron", "lower") == "aaron"


def test_score_cases_with_the_real_masker(tmp_path):
    path = _csv(tmp_path, [("Aaron", "first", "english")])
    cases = [c for c in bm.build_cases(1, 1, csv_path=path)
             if c.name == "Aaron"]
    mask = bm._build_masker()
    bm.score_cases(cases, mask)
    by_casing = {}
    for c in cases:
        by_casing.setdefault(c.casing, []).append(c.hit)
    assert all(by_casing["title"])          # capitalised dictionary names hit
    assert not any(by_casing["lower"])      # the capitalisation gate
    assert all(c.false_positives == 0 for c in cases)
