"""Importing the pipeline leaves the process's warning filters alone.

Audit finding T1-09: a module-level ``warnings.filterwarnings("ignore")``
silenced every warning in any process that imported ``transcription``,
including the WER benchmark, which imports it lazily.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Libraries imported on the way (numpy, scipy, torch) add narrow filters of
# their own, which are fine; what must not appear is a catch-all ignore.
PROBE = (
    "import warnings\n"
    "import transcription\n"
    "assert not [f for f in warnings.filters if f[0] == 'ignore'\n"
    "            and f[1] is None and f[2] is Warning and f[3] is None]\n"
    "with warnings.catch_warnings(record=True) as caught:\n"
    "    warnings.warn('still visible', RuntimeWarning)\n"
    "assert caught, 'warning was swallowed'\n"
    "print('ok')\n"
)


def test_import_installs_no_warning_filter():
    # The import alone takes about three minutes on a laptop, almost all of
    # it torch and transformers, and passed 600 s on a loaded machine
    # during a full run (10 October 2026). The limit only stops a hang.
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=ROOT, capture_output=True,
        text=True, timeout=1800)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("ok")
