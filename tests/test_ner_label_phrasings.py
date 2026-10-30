"""tools/ner_label_phrasings.py splits the NER stage's proposals by the gate.

NEW-10: the committed record of what each label set proposes on the case
study. With a fake model, a capitalised proposal is counted as one the
gate lets through, a lower-case one as one it stops, and a title word not
at all, since the masker never lets the NER stage mask one.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT))

import ner_label_phrasings as tool
import ner_masking


def _fake_predict(text, labels, threshold):
    entities = [{"text": "speaker one", "score": 0.9}]
    if "narrow" in labels:
        entities.append({"text": "Jordan", "score": 0.9})
    entities.append({"text": "Dr Ana", "score": 0.9})
    return [e for e in entities if e["text"].split()[-1].lower() in text.lower()]


def test_proposals_are_split_by_the_capitalisation_gate():
    text = "Tag speaker one. Not Jordan, the country. Thanks to Dr Ana."
    result = tool.measure(
        text, _fake_predict, lambda t: t.split(". "),
        lambda w: w[:1].isupper(), ner_masking._masker_form, {"dr"},
        {"wide": ("person",), "narrow": ("narrow",)}, 0.6)
    assert result["n_sentences"] == 3
    wide, narrow = result["label_sets"]["wide"], result["label_sets"]["narrow"]
    assert wide["capitalised"] == {"ana": 1}
    assert wide["lower_case"] == {"one": 1, "speaker": 1}
    assert narrow["capitalised"] == {"ana": 1, "jordan": 1}
    assert wide["labels"] == ["person"] and wide["model_failures"] == 0
