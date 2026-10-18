"""The hypothesis dump must not collide between models.

Three models write into one output directory. The reports and summaries
have always carried the model slug; the dump did not, so the last model
to finish silently overwrote the others. It did exactly that once, and
cost the Whisper Large v3 hypothesis text on all five suites.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODELS = ("openai/whisper-large-v3", "openai/whisper-medium",
          "distil-whisper/distil-large-v3")


def _dump_paths_for(monkeypatch, model_id, suite_index=0):
    """Run one suite through run_suite with the benchmark stubbed out."""
    captured = {}

    stub = types.ModuleType("evaluation.benchmark_wer")

    class _ConditionRun:
        def __init__(self, condition_name, report_path, summary_path):
            self.condition_name = condition_name
            self.report_path = report_path
            self.summary_path = summary_path

    stub._ConditionRun = _ConditionRun
    stub.run_benchmark = lambda **kw: captured.update(kw)
    monkeypatch.setitem(sys.modules, "evaluation.benchmark_wer", stub)

    from evaluation.sweep import _all_suite_specs, run_suite

    run_suite(
        spec=_all_suite_specs()[suite_index],
        model_id=model_id,
        conditions=["raw"],
        output_dir=Path("output/evaluation"),
        limit=1,
        dump_hypotheses=True,
    )
    return captured["dump_hypotheses"]


def test_each_model_writes_its_own_dump(monkeypatch):
    paths = {m: _dump_paths_for(monkeypatch, m) for m in MODELS}
    names = [p.name for p in paths.values()]
    assert len(set(names)) == len(names), (
        f"models share a dump filename and would overwrite each other: {names}")


def test_the_dump_name_carries_the_model_slug(monkeypatch):
    for model_id in MODELS:
        slug = model_id.rsplit("/", 1)[-1].lower()
        name = _dump_paths_for(monkeypatch, model_id).name
        assert slug in name, f"{name!r} does not identify {model_id!r}"


def test_the_dump_name_carries_the_suite(monkeypatch):
    from evaluation.sweep import _all_suite_specs
    specs = _all_suite_specs()
    for i in (0, 1):
        name = _dump_paths_for(monkeypatch, MODELS[0], suite_index=i).name
        assert specs[i].name in name, f"{name!r} does not identify {specs[i].name!r}"


def test_no_dump_is_requested_by_default(monkeypatch):
    """The dump holds transcript text, so it stays an explicit choice."""
    captured = {}
    stub = types.ModuleType("evaluation.benchmark_wer")

    class _ConditionRun:
        def __init__(self, condition_name, report_path, summary_path):
            self.condition_name = condition_name
            self.report_path = report_path
            self.summary_path = summary_path

    stub._ConditionRun = _ConditionRun
    stub.run_benchmark = lambda **kw: captured.update(kw)
    monkeypatch.setitem(sys.modules, "evaluation.benchmark_wer", stub)

    from evaluation.sweep import _all_suite_specs, run_suite
    run_suite(spec=_all_suite_specs()[0], model_id=MODELS[0],
              conditions=["raw"], output_dir=Path("output/evaluation"), limit=1)
    assert captured["dump_hypotheses"] is None
