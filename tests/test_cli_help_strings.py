"""Every argparse help string must survive argparse's own %-formatting.

argparse expands each argument's ``help`` as ``help % params``, where
``params`` holds the action's attributes (``default``, ``choices``,
``prog`` and so on), so a bare ``%`` in a help string makes ``--help``
raise ValueError. ``python -m evaluation.bootstrap_ci --help`` failed this
way on the ``95% CI`` of its ``--compare`` help until release 2.1.1. A
``usage`` string is always formatted the same way, and a ``description``,
``epilog`` or ``version`` text is formatted only when it contains
``%(prog)``.

The scan reads the source with :mod:`ast` and imports nothing, so it
covers transcription.py and the benchmark modules without the ML stack.
An f-string's interpolated values are unknown before run time and are
replaced by a neutral stand-in, so only its literal text is checked.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SCANNED_DIRS = (".", "evaluation", "tools", "setup", "local_app")
_SOURCES = sorted(path for folder in _SCANNED_DIRS for path in (ROOT / folder).glob("*.py"))

#: Keywords argparse always formats, and those it formats only when the
#: text contains "%(prog)".
_ALWAYS_FORMATTED = ("help", "usage")
_PROG_FORMATTED = ("description", "epilog", "version")


class _AnyParams(dict):
    """Stands in for argparse's params: any named field formats as 0."""

    def __missing__(self, key):
        return 0


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound to a plain string, for help=NAME."""
    strings = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    strings[target.id] = node.value.value
    return strings


def _template(node: ast.expr, strings: dict[str, str]) -> str | None:
    """The text *node* evaluates to, or None when it cannot be read statically."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(value.value)
            else:
                parts.append("0")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _template(node.left, strings)
        right = _template(node.right, strings)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Name):
        return strings.get(node.id)
    return None


def _format_error(text: str) -> str | None:
    """The error argparse would raise formatting *text*, or None."""
    try:
        text % _AnyParams()
    except (ValueError, TypeError, KeyError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _scan() -> tuple[list[str], list[str], int]:
    """Failures, unreadable help expressions and the count of strings checked."""
    failures, unreadable, checked = [], [], 0
    for path in _SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        strings = _module_strings(tree)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            for keyword in call.keywords:
                if keyword.arg not in _ALWAYS_FORMATTED + _PROG_FORMATTED:
                    continue
                where = f"{path.relative_to(ROOT).as_posix()}:{keyword.value.lineno}"
                text = _template(keyword.value, strings)
                if text is None:
                    # argparse.SUPPRESS is a sentinel, not formatted text.
                    if keyword.arg == "help" and ast.unparse(keyword.value) != "argparse.SUPPRESS":
                        unreadable.append(f"{where}: {ast.unparse(keyword.value)}")
                    continue
                if keyword.arg in _PROG_FORMATTED and "%(prog)" not in text:
                    continue
                checked += 1
                error = _format_error(text)
                if error:
                    failures.append(f"{where} ({keyword.arg}=): {error}")
    return failures, unreadable, checked


def test_the_checker_catches_a_bare_percent():
    """The check rejects the 2.1.0 string and accepts its escaped form."""
    assert _format_error("with its 95% CI.") is not None
    assert _format_error("with its 95%% CI (default: %(default)s).") is None


def test_no_help_string_has_an_unescaped_percent():
    failures, _, checked = _scan()
    assert checked > 200, f"only {checked} help strings found; is the scan reading the source?"
    assert not failures, "unescaped % in an argparse string:\n" + "\n".join(failures)


def test_every_help_string_can_be_read_statically():
    """A help expression the scan cannot read would escape the check above."""
    _, unreadable, _ = _scan()
    assert not unreadable, (
        "help= expressions the scan cannot evaluate; extend _template:\n"
        + "\n".join(unreadable)
    )


def test_bootstrap_ci_help_renders():
    pytest.importorskip("numpy")
    from evaluation.bootstrap_ci import _build_parser

    text = " ".join(_build_parser().format_help().split())
    assert "with its 95% CI." in text
