# Maintenance tools

Scripts that are run by hand when the thing they maintain changes. They
are not part of the transcription workflow, and nothing imports them at
run time.

## `generate_example_variants.py`

Regenerates everything under `example_output/variants/` by running the
pipeline itself on a synthetic two-person interview. Each directory holds
what this command writes, with the flags in the table added:

```bash
python transcription.py example.wav --language english \
    --mask-personal-names --fix-spurious-repetitions
```

| Directory | Flags added | Files written |
| --- | --- | --- |
| `01_plain` | neither | `.txt` and the manifest |
| `02_timestamps` | `--timestamps` | as above, plus the raw and redacted `.json`/`.vtt` pairs and the review report |
| `03_diarisation` | `--speaker-attribution` | as `02`, with speaker labels, plus `_with_speakers.txt` |
| `04_diarisation_and_timestamps` | both | the same files as `03` |

`--speaker-attribution` needs word timings to place speakers, so it
switches the timestamps on by itself. That is why `03` and `04` hold the
same files with the same contents, apart from the manifest's
`"timestamps"` field, which records the flag as given, and the manifest's
own digest.

The script calls `transcription.main`, so argument parsing,
`process_audio_file`, segmentation, timeline repair, speaker assignment,
the clean-up stages, name masking and every writer are the pipeline's own
code. What it replaces, and why, is listed in its docstring. In short:

- the two model calls return a synthetic result, and the recording is an
  empty placeholder WAV, so the manifest's `input_audio` digest is of that
  placeholder;
- the Word documents are not written, because a `.docx` is a zip archive
  stamped with the time it was made and never matches between runs. A real
  run also writes `example_transcript.docx` (and, with speaker
  attribution, `example_transcript_with_speakers.docx`) and lists them in
  the manifest;
- the clock, the version string (the release in `versions.csv` alone, as
  an installed copy without git prints it) and the manifest's software
  block (the versions in `requirements-lock.txt`, git fields empty) are
  pinned, and no signing key is used;
- files are written with LF line endings on every platform, so the
  manifests' SHA-256 digests do not depend on the machine.
  `.gitattributes` keeps these files LF on checkout, and
  `python -m provenance verify example_output/variants/02_timestamps/example_manifest.json`
  passes on them.

The masking log is not included: it is written only with
`--save-name-masking-logs`, and into `name_masking_logs/`, not beside the
transcripts. The interview names two fictional people, so the raw `.json`
and `.vtt` keep the names while the `.txt` files and the redacted pair
show placeholders. The interview text quotes no figures. An earlier
version quoted evaluation results that later changed; the paper and
`output/evaluation/` hold those.

Run it from the repository root after editing the interview text or
changing any writer:

```bash
python tools/generate_example_variants.py
```

It replaces every file in the four directories. `tests/test_example_variants.py`
regenerates each variant into a temporary directory and compares the file
set and every file's contents with the committed copy, checks that the
writers it spies on are the ones called, and verifies each committed
manifest. A hand-edit to the examples, or a change to a writer without a
re-run, therefore fails the test suite.

## `verify_regeneration.py`

Checks that the current code still produces the committed results that
need no GPU. Most files in `output/evaluation/` come from GPU jobs on
ARC; eleven are derived on the CPU from other committed files or from a
seeded synthetic benchmark, and this script re-runs their producers and
compares the output with the committed copies:

| Producer | Committed files |
| --- | --- |
| `python -m evaluation.footprint` on `arc_job_ledger.csv` | `footprint_report.csv`, `footprint_summary.json` |
| `python -m evaluation.condition_ci` on `sweep_reports/` | `condition_ci.csv` |
| `python -m evaluation.condition_ci` on `sweep_reports_postfix/` | `condition_ci_postfix.csv` |
| `python -m evaluation.condition_ci --gains-output` on `sweep_reports_postfix_ami/` | `normaliser_gain_ami.csv` |
| `python -m evaluation.bootstrap_ci` on `wer_report.csv` | `wer_ci.csv` |
| `python -m evaluation.speaker_cluster_ci` on the headline and historical condition reports | `speaker_cluster_sensitivity.json` |
| `python -m evaluation.audit_artefacts --dir example_output` | `artefact_audit.csv`, `artefact_audit.json` |
| `python -m evaluation.benchmark_masking --seed 42` (dictionary arm) | `masking_report.csv`, `masking_summary.json` |

The intervals use the recorded 10,000 replicates and seed 42. The gains
in `normaliser_gain_ami.csv` need no bootstrap, but `condition_ci`
requires `--output`, so that run writes the paired intervals as well,
which are neither committed nor compared. Run it from the repository
root on a clean checkout, since it compares with the working tree:

```bash
python tools/verify_regeneration.py                 # everything
python tools/verify_regeneration.py --skip-masking  # without the slowest producer
python tools/verify_regeneration.py --keep          # keep the regenerated files
```

Each producer runs in its own process, with this Python, writing into a
temporary directory, so nothing under `output/` is touched. Every file is
compared byte for byte first. A text file that differs only in CRLF
against LF line endings, which depend on the checkout and not on the
code, is reported as identical "up to line endings". The `file` column
of `wer_ci.csv` spells the report's path with forward slashes on every
platform. A copy written on Windows before a8420df spelt it with
backslashes, so the script accepts that one difference in that column,
and says so when it is what made the file match. The script prints
`IDENTICAL`, `DIFFERS`, `MISSING` or `FAILED` per file and exits 0 only
when every file matches.

The dictionary summary has one additional portable comparison: an LF or
CRLF digest is accepted only when both hashes identify the current
dictionary and all other nonvolatile fields agree. A changed entry or
benchmark measurement still fails. [The CPU workflow](../docs/ci.md)
runs the focused tests and this gate automatically.

`scorer_sensitivity.csv` and `.json` are separate exploratory outputs.
Their producer, `evaluation.scorer_sensitivity`, requires the recovered
ARC hypothesis and summary bundle, which is not part of this checkout.
It therefore remains outside the eleven-artefact gate. Its CPU contracts
are tested in CI; the input-dependent regeneration command and limits
are recorded in [the evaluation README](../output/evaluation/README.md).

A `DIFFERS` means a change moved a result, or the environment differs
from `requirements-lock.txt`. For a file that
[output/evaluation/README.md](../output/evaluation/README.md) lists as
pending regeneration it is expected until that file has been re-run.
The masking benchmark imports `transcription.py`, so on a machine with
transformers installed its first import is slow even though no model is
loaded.

## `extract_sweep_decode_provenance.py`

Extracts the recorded model/dataset revisions, decode and environment from
the 255 recovered summaries into a public metadata receipt. It verifies
the original file hashes and complete grid, and requires all seventeen
conditions of each suite/model to share the same recorded profile. The
output records fifteen profiles and their source digests, with no corpus
text or private deployment locators. Missing historical settings remain
unrecorded. Its [recipe](../output/evaluation/README.md) requires the
external input bundle and an explicit output path separate from the inputs.

## `build_input_deposit.py`

Writes that input bundle for its public data deposit: the 270 recovered
files, each checked against `output/evaluation/sweep_input_manifest.json`
and stored byte for byte, with the manifest, a `SHA256SUMS` file and a
README giving their provenance, corpus licences and use. It stops at a
file that differs from the manifest or that the manifest does not list.
The archive is deterministic, so the same inputs give the same digest,
which a JSON record beside the archive gives. The public repository holds
releases, not the decoder commit `6f9bf56` that wrote the files, so the
deposit also carries a `git archive` of that commit as a second file.
`--decoder-source` checks that the ZIP's comment is the manifest's decoder
commit, and the README then describes the file, gives its digest and warns
against running its older tests on a shared model cache:

```bash
git -c core.autocrlf=false -c core.eol=lf archive --format=zip \
    -o <directory>/decoder_source_6f9bf56.zip 6f9bf56
python tools/build_input_deposit.py \
    --inputs build/recovered_arc_sweep/inputs \
    --output <directory outside the repository>/sweep_inputs.zip \
    --software-doi 10.5281/zenodo.<the software release> \
    --decoder-source <directory>/decoder_source_6f9bf56.zip
```

## `bib_sentencecase.py`

Normalises the capitalisation of `manuscript/references.bib`. It sets
`title`, `shorttitle` and `subtitle` in sentence case, which is what APA 7
requires for article and chapter titles, and `journaltitle`, `booktitle`
and `eventtitle` in title case. In both groups it protects acronyms,
proper nouns and words with distinctive casing by wrapping them in braces,
together with the terms listed in `manuscript/protected_terms.json`.
`booktitle` is set in title case although APA 7 puts book and
proceedings-volume titles in sentence case; the script's docstring leaves
that change to the maintainer, because it would rewrite the committed
bibliography.

```bash
# Print the result for review
python tools/bib_sentencecase.py

# Rewrite the file
python tools/bib_sentencecase.py --in-place
```

The bibliography argument defaults to `manuscript/references.bib` and
`--protected` to `manuscript/protected_terms.json`; pass either to use
another file. It needs `bibtexparser` (in `requirements.txt`). The
conversion is idempotent, and `tests/test_bib_sentencecase.py` asserts
that a second run changes nothing.
