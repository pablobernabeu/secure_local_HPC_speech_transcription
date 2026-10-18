# Systematic Evaluation: Word Error Rate

The `evaluation.wer` module benchmarks hypothesis transcripts against a
human-prepared reference (or "ground truth") corpus and produces a
per-file CSV report and a corpus-level JSON summary. Scoring is built on
[`jiwer`](https://github.com/jitsi/jiwer), which implements the standard
edit-distance alignment used in speech-recognition research.

## Why a normalisation layer is needed

A naïve string comparison would penalise the model for differences that
are immaterial to the meaning of the transcript: smart quotes versus
ASCII apostrophes, capital letters at the start of a sentence, trailing
punctuation, or non-breaking spaces. Before scoring, both reference and
hypothesis are passed through the same normalisation function:

1. Unicode `NFKC` normalisation, then conversion of the curly single
   quotation marks, U+2018 and U+2019, to `'`. U+2019 is also the
   typographic apostrophe. NFKC itself leaves curly quotes unchanged.
2. Optional lower-casing (on by default).
3. Optional removal of all non-word, non-apostrophe characters
   (on by default), so that punctuation does not contribute to the WER.
4. Optional removal of common English fillers (`uh`, `um`, ...), off
   by default, because fillers carry information in some research designs and
   should not be discarded silently.
5. Whitespace collapsing.

The same normaliser is applied to a metadata-header-stripped body, so
that the header written by `save_transcript_file` (filename, model,
timestamp, ...) cannot inflate or deflate the score.

## Metrics reported

For each pair the module records the Word Error Rate (WER), Match Error
Rate (MER), Word Information Lost (WIL), Character Error Rate (CER), and
the raw alignment counts (hits, substitutions, deletions, insertions).
At the corpus level it reports both the macro-averaged WER (mean over
files) and the micro-averaged WER (total errors divided by total
reference words), which behave differently when file lengths are
unbalanced.

$$
\mathrm{WER} = \frac{S + D + I}{N}
$$

where $S$, $D$ and $I$ are substitutions, deletions and insertions
recovered by the alignment, and $N$ is the number of words in the
reference.

## Sampling uncertainty across readers

The headline LibriSpeech report contains 2,620 utterances from 40 readers.
An interval that resamples utterances independently does not preserve the
dependence between utterances from the same person. The separate exploratory
analysis in `evaluation/speaker_cluster_ci.py` resamples whole readers,
retaining every utterance each selected reader supplied. It divides each
resample's total of per-utterance WERs by its utterance count, preserving
the macro-WER estimand even though readers contribute unequal numbers of
utterances. Paired condition differences use the same reader draw for both
conditions, with exact ID matching; missing rows, duplicate IDs and
unusable scores fail explicitly.

The committed `speaker_cluster_sensitivity.json` records 10,000 replicates,
seed 42, the input paths and SHA-256 digests after normalising CSV line
endings to LF. Its headline interval is 5.08% to 7.36%, compared with
5.75% to 6.70% from the original utterance bootstrap. The historical
contraction and composite costs remain positive under reader resampling.
These intervals describe sensitivity to reweighting the observed readers;
they do not measure uncertainty from selecting the corpus, the reference
transcripts or a new participant population. The original interval files
are retained. Rebuild the separate report with:

```bash
python -m evaluation.speaker_cluster_ci \
    --report output/evaluation/wer_report.csv \
    --baseline output/evaluation/sweep_reports/wer_report.csv \
    --condition output/evaluation/sweep_reports/wer_report_contraction_fix.csv \
                output/evaluation/sweep_reports/wer_report_pipeline_full.csv \
    --bootstrap 10000 --seed 42 \
    --output output/evaluation/speaker_cluster_sensitivity.json
```

The module requires LibriSpeech's numeric reader–chapter–utterance IDs.
An arbitrary filename prefix is not sufficient evidence of a sampling unit.
The regeneration gate also rebuilds and compares this report.

## Local usage

```bash
python -m evaluation.wer \
    --hypothesis output/transcripts \
    --reference  <reference_dir> \
    --report     my_evaluation/wer_report.csv \
    --summary    my_evaluation/wer_summary.json
```

`<reference_dir>` holds one human reference per recording. Pass
`--report` and `--summary` to put the results where you want them. Their
defaults are `output/evaluation/wer_report_transcripts.csv` and
`output/evaluation/wer_summary_transcripts.json`: deliberately not
`wer_report.csv` and `wer_summary.json`, the LibriSpeech benchmark
results the manuscript reads, which the defaults once named, so that
scoring your own recordings replaced the paper's headline result (audit
finding EWER-11). The summary records what was compared, the normaliser
settings, and the code commit and package versions of the run.

Hypothesis and reference may be passed either as directories or as two
individual files. In directories, files are paired by stem: a hypothesis
`interview_transcript.txt` is matched to a reference named `interview`
or `interview_transcript`. Either side may be `.txt`, `.json` (the `text`
field that `--timestamps` writes, or failing that the segments' texts) or
`.vtt` (the cue text only: the `WEBVTT` header, cue numbers, timings,
notes and voice tags are dropped, where they used to be scored as words).
`transcription.py` writes a recording's `.txt`, `.json` and `.vtt` side
by side, so each recording is scored once, from one file: `.txt` first,
then `.json`, then `.vtt`, or only the format `--hypothesis-format` names.
Every such choice is printed on stderr. Scoring every format used to
count a recording two or three times in the corpus figure.

## Running on HPC

A ready-made SLURM script lives at [`hpc/evaluate_wer.sh`](../hpc/evaluate_wer.sh).
It submits to a CPU partition with two cores and 8 GB of memory. Word error rate scoring is CPU-bound, so no GPU is requested. The script was developed and tested on the University of Oxford HPC (`--clusters=htc`, `short` partition) and can be adapted to any SLURM-managed cluster by adjusting those directives:

```bash
# Hypotheses, references, report directory (all optional)
sbatch hpc/evaluate_wer.sh output/transcripts path/to/references my_evaluation
```

Submit from the repository root. Without arguments the script reads
hypotheses from `output/transcripts/` in the repository, where the
transcription jobs write them, and references from
`$DATA/speech_transcription_env/reference_transcripts`, and writes
`wer_report_transcripts.csv` and `wer_summary_transcripts.json` to
`$DATA/speech_transcription_env/output/evaluation/inhouse/`. Neither the
names nor the directory are those of a committed result. It once wrote
`wer_report.csv` and `wer_summary.json` into the evaluation directory
itself, which overwrote the manuscript's LibriSpeech result on ARC. The
job refuses to start (exit 3) when the summary it would write already
exists, unless `OVERWRITE=1` is set or a third argument names another
report directory. Its other exits are 1 for a missing environment or
reference directory, 2 for a failed preflight and 4 when the hypothesis
directory holds no `.txt` or `.json`. To produce the hypotheses first,
submit the transcription jobs with `hpc/submit_transcription.sh`, which
run on CPU (see [hpc_usage.md](hpc_usage.md)).

## Output

The report CSV contains one row per file with all metrics and counts.
The summary JSON contains the same per-file data plus a `summary` block
with the corpus-level figures and a `run_metadata` block with the code
commit and package versions. The committed
`output/evaluation/wer_summary.json`, which the Quarto manuscript reads to
populate its tables and figures, is the summary the condition sweep wrote
for its raw Large v3 cell on LibriSpeech test-clean
(`wer_summary_librispeech_whisper-large-v3.json`), copied unchanged with
its report. It therefore carries both blocks, and a `benchmark` block that
names the dataset and model revisions and the decoding device. See the
manuscript in
[`manuscript/manuscript.qmd`](../manuscript/manuscript.qmd) for a worked
example, and [output/evaluation/README.md](../output/evaluation/README.md)
for which committed result files are current.

## The condition sweep

The single-condition `evaluation.wer` interface is sufficient for a
spot check but does not scale to the post-processing ablation that
the manuscript reports. The `evaluation.sweep` driver loads each
audio dataset once, runs the model in a single pass, and then scores
a list of post-processing conditions against the same set of
hypotheses. By default that list is every registered condition,
seventeen with `raw`, read from `transcription.CLEAN_TEXT_STAGES` so that
a new production stage cannot be left out. The committed grid, from the
audit's re-run of the sweep (`hpc/runs/sweep.env`), has all seventeen.
The post-fix grid before it had sixteen, because a hand-typed default
omitted `pronoun_i_fix` (audit finding EWER-13). The pre-repair grid kept
as history, `sweep_aggregate_prefix.csv`, has sixteen as well, because it
was aggregated in June 2026, before the stage was split out of
`sentence_capitalise`.
`--conditions` chooses the list explicitly, and `python -m evaluation.sweep
--list-conditions` prints the registry. The conditions themselves are catalogued in
`evaluation/conditions.py` and documented in detail in
[conditions_audit.md](conditions_audit.md). The registry is
populated by three groups: the production pipeline of the desktop
application, decomposed into atomic stages and exposed as
`unicode_strip`, `repetition_fix`, `undefined_tag`, `filler_bracket`,
`contraction_fix`, `common_phrase_fix`, `whitespace_normalise`,
`sentence_capitalise`, `pronoun_i_fix`, `punct_space_fix` and the
composite `pipeline_full`; a diagnostic ablation set comprising `filler_strip`,
`dedup_window`, `punct_strip` and `case_fold`; and the canonical
`whisper_norm` reference point. `whisper_norm` is Whisper's own English
normaliser from transformers together with the British-to-American
spelling map it is meant to load, `normalizers/english.json` from the
`openai-whisper` package (20250625 in the job environment), checked
against a pinned SHA-256. Without that package the condition stops with
an error. It used to run with an empty map, which standardises nothing,
and every `whisper_norm` result committed before the audit's re-run of
the sweep (2e36bf9) was scored that way, the pre-repair files kept as
history among them (audit finding EWER-05). Conditions for which it is
meaningful to apply the transformation to the reference (currently
`punct_strip`, `case_fold` and `whisper_norm`) are flagged
symmetric; the rest are hypothesis-only. `pipeline_full` is also
flagged `language_aware`, so the benchmark passes its `--language`
through and the composite skips its English-only stages on
non-English corpora; see
[conditions_audit.md](conditions_audit.md#the-language-gate).

The sweep is invoked locally with

```bash
python -m evaluation.sweep \
    --model openai/whisper-large-v3 \
    --output-dir my_sweep
```

`--output-dir` defaults to `output/evaluation`, where the committed
results live, so pass another directory. Every file the sweep writes
names its suite and model: the first condition of a cell writes
`wer_report_<suite>_<model>.csv` and `wer_summary_<suite>_<model>.json`
(the LibriSpeech test-clean suite is spelt `librispeech`, as in
`wer_report_librispeech_whisper-large-v3.csv`), and each further
condition appends `_<condition>`. The canonical cell used to write the
unqualified `wer_report.csv` and `wer_summary.json`, the manuscript's
headline files, so one run could overwrite another's. Those names are now
written only with `--legacy-primary-paths`, which exists to reproduce the
old layout (audit finding EWER-11).

On HPC, `sbatch hpc/submit_sweep.sh` runs the five suites as an array
job, one suite per task. Aggregation into the single
`sweep_aggregate.csv` that the manuscript consumes is a separate job,
which is not scheduled automatically: submit `hpc/aggregate_sweep.sh`
once every task has finished, or chain the two with a dependency, giving
both the same directory:

```bash
OUT=$DATA/speech_transcription_env/output/evaluation/<new sweep>
JID=$(SWEEP_OUTPUT_DIR=$OUT sbatch --parsable hpc/submit_sweep.sh)
SWEEP_DIR=$OUT sbatch --dependency=afterok:${JID%%;*} hpc/aggregate_sweep.sh
```

Without `SWEEP_DIR`, `aggregate_sweep.sh` aggregates the sweep behind the
committed matrix (`hpc/runs/sweep.env`). `python -m evaluation.sweep_aggregate` writes
one row per suite, model and condition: the four macro metrics (the
unweighted mean of per-utterance rates), the reference-word count, the
source summary relative to the sweep directory and a `pipeline_version`
column; then the pooled (micro) WER and MER, errors over reference words,
with the hit, substitution, deletion, insertion and hypothesis-word
totals behind them, and `wer_invisible`, which marks the conditions whose
effect the scoring normaliser erases by construction. On AMI a few
hallucinated hypotheses against one- or two-word references dominate the
macro figure, and the pooled columns are what shows it (audit finding
EWER-08). `pipeline_version` comes from each summary's own record, else
from the commit in its run metadata, else from `--pipeline-version LABEL`
for summaries that record neither. The committed matrix's summaries carry
their commit; the post-fix matrix before it was labelled
`--pipeline-version "post-fix (af3bee0)"`. The aggregator refuses
a grid with a repeated cell, which is what two nested sweeps in one
directory produce, and a grid with a missing cell unless given
`--allow-incomplete`. The JSON carries the input files' digests and the
run metadata.

`python -m evaluation.condition_ci` computes the paired bootstrap
intervals on the difference between each condition and a baseline, from
a directory of per-utterance reports. `--output` is required: it used to
default to `output/evaluation/condition_ci.csv`, the pre-repair intervals
the manuscript quotes as history, so a run on the repaired sweep without
the flag replaced them. `--gains-output PATH` also writes each
condition's relative gain over the baseline computed on the utterances
both scored, beside the all-utterance gain. The two differ where a
condition's normaliser empties some references: `whisper_norm` removes
hesitations, so on AMI it scores fewer utterances than `raw`, and a gain
computed from the two corpus rates mixes the condition's effect with the
loss of those utterances (audit finding EWER-09). The committed
`output/evaluation/normaliser_gain_ami.csv` is that table for Large v3 on
AMI, written from the two reports in
`output/evaluation/sweep_reports_postfix_ami/`. Those keep the sweep's
names, so the run passes `--prefix wer_report_ami_whisper-large-v3`, and
`output/evaluation/README.md` gives the full command.

`python -m evaluation.fleurs_multilingual` builds
`output/evaluation/fleurs_multilingual_summary.json`, which the
manuscript's multilingual section reads, from the per-language FLEURS
summaries of its four arms (before the Unicode-strip repair, after it,
with the language gate, and the re-run of the repaired code after the
September 2026 audit), each passed as `--arm NAME=DIR`. The file was
first assembled by hand. The 48 summaries are on ARC, not in the
repository, and rebuilding from them reproduces every computed value.
The module reads the file names of the first three arms and the names
carrying the model slug that the submit script has written since
a22a864, and refuses an input whose recorded configuration, condition,
model, code commit or GPU contradicts its name or its arm. The share of
words with a diacritic per language is read with `--diacritics` from
`output/evaluation/fleurs_diacritic_shares.json`, which
`evaluation.fleurs_diacritics` measured on every reference word of the
test splits; the first committed shares had been measured outside the
repository on an unrecorded sample. The prose `finding` block is carried
over from the existing file instead of computed. The module docstring
names the directory of each arm, and its `ARMS` registry the code
commit, the ARC jobs and, where the summaries do not record them, the
GPUs.

`evaluation/revisions.py` holds, in one place, the Hugging Face commit
every model and dataset in the evaluation resolved to on ARC, and
`revision_for(repo_id)` returns it for a loader's `revision=` argument.
The identifiers used to be retyped across about ten files and loaded from
`main`, so an upstream push could change what a re-run measured. A
repository not listed there loads `main`, and the summary then records
no revision for it, so an unpinned load is visible. pyannote.audio 3.x
takes no `revision=` argument, so `evaluation.hub_loading.pinned_checkpoint`
spells the pin `<repo>@<commit>` for its loaders. The diarisation
pipeline's configuration names its segmentation and embedding models
without a revision, so those two load from `main` even when the pipeline
is pinned. The summary `benchmark_der.py` writes for that pipeline lists
both under `revisions_not_enforced`, as the committed DER summaries do.
The selection files of the two development sweeps record no revisions,
only the code commit and the pyannote.audio version. The anonymisation
benchmark's summary lists under it only the embedding model it used,
whether taken from the pipeline or loaded alone.

The order of all the evaluation jobs, and the invocation behind each
committed result, are in [hpc/README.md](../hpc/README.md). That page
also lists `hpc/submit_finetune_pyannote.sh`, which fine-tunes the
diarisation segmentation model; it has never been run for a reported
result, and the manuscript's diarisation figures come from the released
model.

## How testing proceeds across the post-processing steps

Because the conditions registered in `evaluation/conditions.py` are
relied upon by the manuscript's headline tables, the test suite is
structured to catch a different class of failure at each layer. A
fuller treatment lives in [conditions_audit.md](conditions_audit.md);
the summary below records the five layers as they are organised in
`tests/test_conditions.py`.

The first layer carries per-condition hand-crafted input/output
assertions that act as the executable specification of each stage.
The second layer carries two bulk invariants, idempotence and
empty-string safety, that apply automatically to every condition
in the registry. The third layer checks coverage: a test
introspects `transcription.CLEAN_TEXT_STAGES` and fails the suite if
any atomic stage of the desktop pipeline lacks a registered
condition. The fourth layer verifies composition equality:
`pipeline_full` is asserted byte-equal both to the chained
application of the registered atomic conditions and to a hand-rolled
call into `transcription`. The fifth layer, in
`tests/test_benchmark_wer_conditions.py`, asserts that the
`apply_to_reference` flag is honoured by the WER benchmark driver
for every symmetric condition.

The local suite is invoked from the project root with
`python -m pytest -q`. Tests whose optional dependencies (`datasets`,
`transformers`, `jiwer`, `pyannote.audio`) are missing are skipped, so
the number that runs depends on the machine. Any change to the
post-processing pipeline must leave every previously passing test
passing before it is committed.
