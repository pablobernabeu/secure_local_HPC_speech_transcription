"""Cross-platform local desktop application for the transcription workflow.

The package wraps :mod:`transcription` in a small Tk GUI so that users
without HPC access can run the same pipeline on Windows, macOS and Linux.
Tk is part of the Python standard library, which keeps the install
footprint minimal — there is no additional dependency beyond what the
core workflow already requires.
"""
