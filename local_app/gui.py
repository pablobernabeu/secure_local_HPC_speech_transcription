#!/usr/bin/env python3
"""
Cross-platform Tkinter GUI that wraps `transcription.py`.

Design notes
------------
* Uses only the Python standard library (Tk ships with CPython on
  Windows, macOS and Linux), so installing the GUI adds no extra
  dependency to the project.
* The transcription pipeline is invoked as a subprocess. This isolates
  long-running CPU/GPU work from the Tk event loop and lets us stream
  log output to the UI in real time.
* The same command-line flags that the HPC scripts accept are exposed
  here, so behaviour is identical across local and HPC execution.

Run with::

    python -m local_app.gui
"""

from __future__ import annotations

import os
import queue
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTION_SCRIPT = PROJECT_ROOT / "transcription.py"


def child_io_kwargs() -> dict:
    """Return the Popen keyword arguments that fix the child's text encoding.

    On Windows a piped child's stdout defaults to the ANSI code page
    (cp1252), and transcription.py prints emoji, so the child died with
    UnicodeEncodeError on its first status line (audit finding CORE-16).
    The child is put in UTF-8 mode and the parent decodes UTF-8, replacing
    anything undecodable instead of killing the reader thread.

    Returns a dict with ``env`` (a copy of ``os.environ`` plus
    ``PYTHONIOENCODING=utf-8`` and ``PYTHONUTF8=1``), ``encoding`` and
    ``errors``. No side effects: ``os.environ`` itself is not changed.
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    return {"env": env, "encoding": "utf-8", "errors": "replace"}


class TranscriptionApp(ttk.Frame):
    """Main application frame."""

    LANGUAGES = ("auto-detect", "english", "spanish", "french",
                 "german", "chinese", "hindi", "portuguese", "italian")

    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        master.title("Secure speech transcription — local")
        master.minsize(720, 540)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self._process: subprocess.Popen | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()

        # ---- Variables ----
        self.audio_path = tk.StringVar()
        self.output_name = tk.StringVar()
        self.model = tk.StringVar(value="openai/whisper-large-v3")
        self.language = tk.StringVar(value="auto-detect")
        self.enhance_audio = tk.BooleanVar(value=False)
        self.mask_names = tk.BooleanVar(value=False)
        self.fix_repetitions = tk.BooleanVar(value=False)
        self.timestamps = tk.BooleanVar(value=True)
        self.speaker_attribution = tk.BooleanVar(value=False)
        self.diarization_model_path = tk.StringVar()

        self._build_widgets()
        self.after(120, self._drain_log)

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        row = 0
        ttk.Label(self, text="Audio file").grid(row=row, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.audio_path).grid(
            row=row, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(self, text="Browse…", command=self._browse_audio).grid(
            row=row, column=2, sticky="ew")

        row += 1
        ttk.Label(self, text="Output name (optional)").grid(
            row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(self, textvariable=self.output_name).grid(
            row=row, column=1, columnspan=2, sticky="ew",
            padx=(6, 0), pady=(8, 0))

        row += 1
        ttk.Label(self, text="Model").grid(row=row, column=0, sticky="w",
                                           pady=(8, 0))
        ttk.Entry(self, textvariable=self.model).grid(
            row=row, column=1, columnspan=2, sticky="ew",
            padx=(6, 0), pady=(8, 0))

        row += 1
        ttk.Label(self, text="Language").grid(row=row, column=0, sticky="w",
                                              pady=(8, 0))
        ttk.Combobox(self, textvariable=self.language, values=self.LANGUAGES,
                     state="readonly").grid(
            row=row, column=1, columnspan=2, sticky="ew",
            padx=(6, 0), pady=(8, 0))

        row += 1
        options = ttk.LabelFrame(self, text="Options", padding=8)
        options.grid(row=row, column=0, columnspan=3, sticky="ew",
                     pady=(12, 0))
        options.columnconfigure((0, 1), weight=1)
        ttk.Checkbutton(options, text="Audio enhancement",
                        variable=self.enhance_audio).grid(
            row=0, column=0, sticky="w")
        ttk.Checkbutton(options, text="Mask personal names",
                        variable=self.mask_names).grid(
            row=0, column=1, sticky="w")
        ttk.Checkbutton(options, text="Fix spurious repetitions",
                        variable=self.fix_repetitions).grid(
            row=1, column=0, sticky="w")
        ttk.Checkbutton(options, text="Emit JSON/VTT timestamps",
                        variable=self.timestamps).grid(
            row=1, column=1, sticky="w")
        ttk.Checkbutton(options, text="Speaker attribution (needs HF token)",
                        variable=self.speaker_attribution).grid(
            row=2, column=0, columnspan=2, sticky="w")

        # Optional local model path for diarisation (the pipeline falls back
        # to the HuggingFace cache / Hub automatically when left blank).
        ttk.Label(options, text="Diarisation model path").grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(options, textvariable=self.diarization_model_path).grid(
            row=3, column=1, sticky="ew", padx=(6, 6), pady=(8, 0))
        ttk.Button(options, text="Browse…",
                   command=self._browse_diarization_model).grid(
            row=3, column=2, sticky="ew", pady=(8, 0))

        row += 1
        buttons = ttk.Frame(self)
        buttons.grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        buttons.columnconfigure(0, weight=1)
        self.run_button = ttk.Button(buttons, text="Run transcription",
                                     command=self._start_run)
        self.run_button.grid(row=0, column=1, padx=(0, 8))
        self.stop_button = ttk.Button(buttons, text="Stop", state="disabled",
                                      command=self._stop_run)
        self.stop_button.grid(row=0, column=2)

        row += 1
        ttk.Label(self, text="Log").grid(row=row, column=0, sticky="w")
        row += 1
        self.log = tk.Text(self, height=14, wrap="word", state="disabled")
        self.log.grid(row=row, column=0, columnspan=3, sticky="nsew")
        self.rowconfigure(row, weight=1)
        scrollbar = ttk.Scrollbar(self, command=self.log.yview)
        scrollbar.grid(row=row, column=3, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

    # ---------------------------------------------------------------- actions
    def _browse_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an audio file",
            filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac *.ogg *.aac"),
                       ("All files", "*.*")])
        if path:
            self.audio_path.set(path)

    def _browse_diarization_model(self) -> None:
        """Let the user point at a local pyannote pipeline.

        Pyannote pipelines are usually a directory containing
        ``config.yaml`` plus weight files; we therefore ask for a
        directory first and fall back to a file picker for users who
        keep the config as a single file.
        """
        path = filedialog.askdirectory(
            title="Choose a pyannote diarisation model directory")
        if not path:
            path = filedialog.askopenfilename(
                title="…or pick the model's config.yaml",
                filetypes=[("YAML config", "*.yaml *.yml"),
                           ("All files", "*.*")])
        if path:
            self.diarization_model_path.set(path)

    def _build_command(self) -> list[str]:
        path = self.audio_path.get().strip()
        if not path:
            raise ValueError("Please choose an audio file.")
        if not os.path.isfile(path):
            raise ValueError(f"Audio file not found: {path}")

        cmd: list[str] = [sys.executable, str(TRANSCRIPTION_SCRIPT), path]
        if self.output_name.get().strip():
            cmd += ["--output-name", self.output_name.get().strip()]
        if self.model.get().strip():
            cmd += ["--model", self.model.get().strip()]
        if self.language.get() and self.language.get() != "auto-detect":
            cmd += ["--language", self.language.get()]
        if self.enhance_audio.get():
            cmd.append("--enhance-audio")
        if self.mask_names.get():
            cmd.append("--mask-personal-names")
        if self.fix_repetitions.get():
            cmd.append("--fix-spurious-repetitions")
        if self.timestamps.get():
            cmd.append("--timestamps")
        if self.speaker_attribution.get():
            cmd.append("--speaker-attribution")
        diar_path = self.diarization_model_path.get().strip()
        if diar_path:
            cmd += ["--diarization-model-path", diar_path]
        return cmd

    def _start_run(self) -> None:
        try:
            cmd = self._build_command()
        except ValueError as e:
            messagebox.showerror("Cannot start", str(e))
            return

        self._clear_log()
        self._append_log("$ " + " ".join(shlex.quote(c) for c in cmd) + "\n")
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        thread = threading.Thread(target=self._run_in_background,
                                  args=(cmd,), daemon=True)
        thread.start()

    def _run_in_background(self, cmd: list[str]) -> None:
        try:
            self._process = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                **child_io_kwargs(),
            )
        except Exception as e:  # pragma: no cover
            self._log_queue.put(f"\nFailed to start process: {e}\n")
            self._log_queue.put("__DONE__")
            return

        # try/finally so the Run button is always re-enabled, even if reading
        # the child's output raises (CORE-16).
        try:
            assert self._process.stdout is not None
            for line in self._process.stdout:
                self._log_queue.put(line)
            self._process.wait()
            rc = self._process.returncode
            self._log_queue.put(f"\n[process exited with code {rc}]\n")
        except Exception as e:  # pragma: no cover - defensive
            self._log_queue.put(f"\n[log reader stopped: {e}]\n")
        finally:
            self._log_queue.put("__DONE__")

    def _stop_run(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._append_log("\n[stop requested by user]\n")

    # ----------------------------------------------------------------- log
    def _drain_log(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                if line == "__DONE__":
                    self.run_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    continue
                self._append_log(line)
        except queue.Empty:
            pass
        self.after(120, self._drain_log)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")


def main() -> int:
    """Open the window and run the Tk event loop until it is closed.

    Returns 1, before any window opens, when ``transcription.py`` is not
    beside this package, and 0 once the window is closed. Side effects:
    opens a Tk window, and on each run starts ``transcription.py`` as a
    child process in the repository root, which writes its outputs there.
    """
    if not TRANSCRIPTION_SCRIPT.is_file():
        sys.stderr.write(
            f"Cannot find transcription.py at {TRANSCRIPTION_SCRIPT}. "
            "Run this command from inside the project tree.\n")
        return 1
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        # Use a theme that looks reasonable across platforms.
        for theme in ("vista", "aqua", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
    except tk.TclError:
        pass
    TranscriptionApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
