"""Stage-1 fixes to the name-masking benchmark.

EPRIV-19: held-out names were reported under the curated language they had
been filed under (Polish names as "polynesian", Japanese as "chinese"); they
are now labelled "held_out", with the seeded sample unchanged.
EPRIV-10/T1-03: quoted and bracketed carrier templates are new cells, after
the original cases, which keep their order; and a placeholder that keeps
the possessive clitic ("[SURNAME]'s") still scores as a hit.
"""

from __future__ import annotations

import csv
import random
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


def _old_cases(seed, n_per_cell, csv_path):
    """The case list as build_cases produced it before these changes."""
    rng = random.Random(seed)
    by_cell: dict = {}
    for name, kind, lang in bm.load_in_db_names(csv_path):
        by_cell.setdefault((lang, kind), []).append(name)
    selected = []
    for (lang, _kind), pool in sorted(by_cell.items()):
        for name in rng.sample(pool, min(n_per_cell, len(pool))):
            selected.append((name, lang))
    by_lang: dict = {}
    for name, lang in bm._partition_out_of_db_names(csv_path):
        by_lang.setdefault(lang, []).append(name)
    for lang, pool in sorted(by_lang.items()):
        for name in rng.sample(pool, min(n_per_cell, len(pool))):
            selected.append((name, lang))
    out = []
    for name, lang in selected:
        for template in bm._BASE_TEMPLATES:
            for casing in bm._CASINGS:
                for morphology in bm._MORPHOLOGIES:
                    base = bm._apply_casing(name, casing)
                    token = base + "'s" if morphology == "possessive" else base
                    out.append((name, lang, template.position, casing,
                                morphology, template.text.format(name=token)))
    return out


def test_the_original_cases_keep_their_sample_and_order():
    """Neither the held-out label nor the new templates changes the sample
    or the order of the original cases; only the held-out language label
    differs. (The pool itself now includes the curated names under three
    characters, T1-07, which does change the sample from the committed
    run's; that is a separate, accepted change.)"""
    csv_path = bm._DEFAULT_CSV
    old = _old_cases(bm._DEFAULT_SEED, bm._DEFAULT_N_PER_CELL, csv_path)
    new = bm.build_cases(bm._DEFAULT_SEED, bm._DEFAULT_N_PER_CELL, csv_path)
    head = new[:len(old)]
    assert [(c.name, c.position, c.casing, c.morphology, c.sentence)
            for c in head] == [(n, p, ca, m, s) for n, _, p, ca, m, s in old]
    for c, (_, lang, *_rest) in zip(head, old, strict=True):
        assert c.language == (lang if c.in_db else "held_out")
    # The rest are the new punctuated cells, one per original name setting.
    tail = new[len(old):]
    assert {c.position for c in tail} == {"quoted", "bracketed"}
    assert len(tail) == len(old) * 2 // 3


def test_held_out_names_are_not_filed_under_a_curated_language(tmp_path):
    path = _csv(tmp_path, [("Aaron", "first", "english")])
    cases = bm.build_cases(seed=1, n_per_cell=2, csv_path=path)
    held_out = [c for c in cases if not c.in_db]
    assert held_out and {c.language for c in held_out} == {"held_out"}
    assert {c.language for c in cases if c.in_db} == {"english"}
    summary = bm.summarise(cases, 1, 2)
    assert "held_out" in summary["by_language"]
    assert "polynesian" not in summary["by_language"]
    assert summary["by_language"]["held_out"]["n"] == \
        summary["by_in_db"]["out_of_db"]["n"]


def test_curated_names_under_three_characters_are_sampled(tmp_path):
    """T1-07: the masker holds them now, so the benchmark tests them."""
    path = _csv(tmp_path, [("Li", "last", "chinese"), ("Aaron", "first",
                                                        "english")])
    names = {n for n, _, _ in bm.load_in_db_names(path)}
    assert names == {"Li", "Aaron"}
    cases = [c for c in bm.build_cases(1, 1, csv_path=path) if c.name == "Li"]
    assert cases and all(c.in_db and c.in_effective_dict for c in cases)


def test_the_gold_token_includes_the_opening_mark(tmp_path):
    path = _csv(tmp_path, [("Aaron", "first", "english")])
    cases = [c for c in bm.build_cases(1, 1, csv_path=path)
             if c.name == "Aaron" and c.casing == "title"]
    by_position = {(c.position, c.morphology): c.gold_token for c in cases}
    assert by_position[("quoted", "bare")] == '"Aaron'
    assert by_position[("bracketed", "possessive")] == "(Aaron's"
    assert by_position[("mid", "bare")] == "Aaron"


def test_a_kept_clitic_or_opening_mark_still_scores_as_a_placeholder():
    for token in ("[SURNAME]'s", "[SURNAME]'s.", "[NAME]’s,", "[NAME]'.",
                  '"[NAME]', "([NAME]", '"[NAME]\'s', "[TITLE]"):
        assert bm._PLACEHOLDER_RE.fullmatch(bm._strip_marker(token)), token
    # A name that was not masked stays a name.
    assert not bm._PLACEHOLDER_RE.fullmatch(bm._strip_marker("Aaron's"))


def test_scoring_a_punctuated_case_with_a_stub_masker():
    case = bm._Case(name="Aaron", language="english", in_db=True,
                    kind="first", casing="title", position="quoted",
                    morphology="possessive",
                    template=bm._PUNCTUATED_TEMPLATES[0].text,
                    gold_token='"Aaron\'s',
                    sentence=bm._PUNCTUATED_TEMPLATES[0].text.format(
                        name="Aaron's"))

    def keeps_clitic(text):
        return text.replace("\"Aaron's", "\"[NAME]'s")

    bm._score_case(case, keeps_clitic)
    assert case.hit and case.false_positives == 0


def test_the_real_masker_catches_quoted_and_bracketed_names(tmp_path):
    path = _csv(tmp_path, [("Aaron", "first", "english")])
    cases = [c for c in bm.build_cases(1, 1, csv_path=path)
             if c.name == "Aaron" and c.position in ("quoted", "bracketed")]
    bm.score_cases(cases, bm._build_masker())
    title = [c for c in cases if c.casing == "title"]
    assert title and all(c.hit for c in title), [
        (c.sentence, c.masked) for c in title if not c.hit]
    assert all(c.false_positives == 0 for c in cases)
