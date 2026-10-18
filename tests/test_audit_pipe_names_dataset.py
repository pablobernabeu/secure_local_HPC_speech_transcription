"""The optional Facebook name lists load once and leave sys.path alone.

Audit finding T1-08: ensure_names_dataset prepended the user site-packages
directory to sys.path for the whole process and built a NameDataset only to
test it, so the tables were loaded twice, behind bare excepts and probes of
APIs no supported release has.
"""

from __future__ import annotations

import contextlib
import io
import sys
import types


def _fake_module(monkeypatch, first, last):
    built = []

    class NameDataset:
        def __init__(self):
            built.append(self)
            self.first_names = {n: {} for n in first}
            self.last_names = {n: {} for n in last}

    module = types.ModuleType("names_dataset")
    module.NameDataset = NameDataset
    monkeypatch.setitem(sys.modules, "names_dataset", module)
    return built


def test_loads_once_without_touching_sys_path(transcription_module,
                                              monkeypatch):
    m = transcription_module
    first = [f"Given{i}" for i in range(150)]
    last = [f"Family{i}" for i in range(150)]
    built = _fake_module(monkeypatch, first, last)
    before = list(sys.path)
    with contextlib.redirect_stdout(io.StringIO()):
        firsts, surnames = m.load_global_names(use_facebook_names=True,
                                               use_facebook_surnames=True)
    assert sys.path == before
    assert len(built) == 1
    assert "given7" in firsts and "family7" in surnames


def test_too_few_names_falls_back_to_the_curated_list(transcription_module,
                                                      monkeypatch):
    m = transcription_module
    _fake_module(monkeypatch, ["Onlyone"], [])
    with contextlib.redirect_stdout(io.StringIO()):
        firsts, surnames = m.load_global_names(use_facebook_names=True)
    assert "sarah" in firsts and "onlyone" not in firsts
    assert surnames


def test_missing_package_is_reported(transcription_module, monkeypatch):
    m = transcription_module
    monkeypatch.setitem(sys.modules, "names_dataset", None)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert m.ensure_names_dataset() is False
    assert "not available" in out.getvalue()
