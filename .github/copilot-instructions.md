# Repository conventions for GitHub Copilot

These instructions codify the conventions that have been agreed
across the project. They apply to all generated prose, generated
code, and generated configuration. They are written in narrative
form so that the reasoning behind each rule remains visible.

## House style for prose

All prose, whether in the manuscript, in the README, in audit
documents, in bibliographic entries or in commit messages, is
written in British English. Words such as "behaviour", "analyse",
"organise", "fibre" and "metre" are preferred over the American
spellings. The exception is when quoting a published source or the
verbatim text of an error message, where the original orthography
is preserved.

Prose is written as continuous narrative. Bullet lists and numbered
lists are not used in the manuscript, in the audit documents, in
the literature mapping, or in long-form sections of the README.
Where structure is needed, it is provided through sub-headings and
through clearly signalled topic sentences rather than through
typographic enumeration. The bold sentence-lead, in which the first
few words of a paragraph are set in bold to act as a label, is also
avoided. Section and sub-section headings carry the structural
weight that those devices would otherwise carry.

## Privacy contract for diarisation

The privacy guarantee of this project is that audio recordings and
transcriptions never leave the institution under which the recording was
made. Downloading model weights is an outbound-only operation that carries
no user data and does not require an explicit flag. The resolution order,
planned by `_resolve_diarization_strategy` and followed by
`perform_speaker_diarization`, is, first, a local YAML configuration
passed through `--diarization-config`; second, a local pipeline passed
through `--diarization-model-path`, either a `config.yaml` or a directory
holding one; and third, the standard HuggingFace loader for the
configured `model_id`, which checks the local cache first and downloads
from the Hub only when the weights are absent, or reads the cache only
when `HF_HUB_OFFLINE` or `TRANSFORMERS_OFFLINE` is set. When either local
option was given and fails, the Hub is not tried. A HuggingFace token is
required for gated models such as `pyannote/speaker-diarization-3.1`. A
run with speaker attribution records which path was taken in the
top-level `pipeline` block of its timestamped JSON, under the keys
`diarization_model_source` (`'local_config'`, `'local_path'`,
`'hf_loader'`, `'hf_loader_offline'` or `'unavailable'`),
`diarization_model_id`, `diarization_model_revision`,
`diarization_sub_model_revisions`, `diarization_model_path`,
`diarization_offline_mode` and, when loading failed, `diarization_error`.
The two revision keys hold the Hub snapshots the load used, read back from
pyannote's cache. The load itself is not pinned to them.
The authoritative list of these labels is in `docs/glossary.md`. Code that
exposes a new way for the pipeline to acquire model weights must update
the resolution function, the provenance block and the glossary together.

## Naming, masking and timestamped artefacts

The text-level transcript is subject to name masking through the
curated database in `data/curated_names.csv`. The masked text is
the artefact that is intended for distribution. The timestamped
artefacts that `write_timestamped_outputs` produces come in two sets.
The raw `*_transcript.json` and `*_transcript.vtt` files contain the
unmasked model output and are intended as auditable local records.
When masking is on, a parallel `*_transcript_redacted.json` and
`*_transcript_redacted.vtt` carry the same timings with the names
masked, and `--redacted-timestamps-only` suppresses the raw set. Any
change that would propagate masked text into the raw set, or unmasked
text into the redacted one, must be flagged in the pull request
description, because it breaks the contract that downstream evaluation
and the privacy guarantee depend on.

## Word error rate evaluation

The evaluation pipeline lives in `evaluation/wer.py`. Its default
outputs are `output/evaluation/wer_report_transcripts.csv` and
`output/evaluation/wer_summary_transcripts.json`, deliberately not the
committed benchmark files that `manuscript/manuscript.qmd` reads, and
`evaluation.benchmark_wer` requires its `--report` and `--summary`
paths; `hpc/evaluate_wer.sh` writes the `_transcripts` names into its
own directory and refuses to overwrite one.
The manuscript reads `output/evaluation/wer_report.csv` and
`wer_summary.json`, the condition sweep's raw Large v3 cell on
LibriSpeech test-clean, and `wer_ci.csv`, the interval over that
report. It stops the render when one of them is missing or lacks a
field the text quotes, or when the summary describes another run;
there is no fallback location. The WER normaliser strips speaker
tags of the form `[SPEAKER_00]` before scoring, and the
`tests/test_wer_normalisation.py` module exercises this invariant
through `jiwer`.

## Cloud and local execution boundaries

The pipeline is designed so that audio never leaves the institution
under which the recording was made. The desktop entry point in
`local_app/gui.py` and the command-line entry point in
`transcription.py` both operate purely locally. The SLURM batch
interface in `hpc/` runs on the University of Oxford's ARC facility,
on the `htc` cluster's `short` partition; the job scripts in `hpc/`
encode the relevant module loads, and `activate_project_env_arc.sh`
the environment and cache locations. Generated code that introduces a new
dependency on a remote inference API, a cloud transcription service
or a public model registry without an explicit `--allow-...` flag
and a corresponding entry in the pipeline provenance block is to
be rejected at review. The same applies to introduced telemetry,
analytics, or any outbound network call that is not strictly
required for the current operation.

## Test suite and execution discipline

The test suite is invoked from the project root with
`python -m pytest -q`, which picks up the settings in `pytest.ini`.
Tests that depend on optional packages such as `jiwer` or
`pyannote.audio` use `pytest.importorskip` rather than hard imports,
so that the suite remains green in environments that lack those
packages; which tests skip therefore depends on the machine. The rule
is that no previously passing test may fail, and any test removed or
newly skipped must be justified in the pull request.

When executing commands, independent read-only operations may be
parallelised, but commands that mutate the workspace are executed
sequentially. Destructive operations on the filesystem, on git
history, or on shared infrastructure are not initiated without an
explicit instruction from the user. The standard guard rails apply:
no `git push --force`, no `rm -rf` on directories outside the build
output tree, no amendment of published commits, and no bypass of
test hooks through `--no-verify`.

## Bibliography hygiene

The BibLaTeX file at `manuscript/references.bib` is maintained
under the sentence-case-with-protected-tokens convention enforced by
`tools/bib_sentencecase.py`. The tool is idempotent: a second
invocation must produce a byte-identical file, and the
`tests/test_bib_sentencecase.py` module asserts that property. New
entries added to the file should be passed through the tool before
commit, and any token that must keep its original casing (a proper
noun, an acronym such as HPC or ASR or GPU, or a piece of
typewriter text such as `Raspberry Pi`) should be added to the
protected list in `manuscript/protected_terms.json` rather than encoded by
hand in the bib entry.
