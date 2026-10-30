# Manuscript

This directory contains the reproducible Quarto source for the
methodological paper that accompanies the workflow.

## Rendering

The manuscript reads the committed results under `output/evaluation/` and
renders its tables, figures and inline numbers from them. No evaluation
has to be run first.

Rendering needs:

- Quarto 1.4 or later. The committed render was checked with Quarto
  1.10.18.
- R 4.1 or later, because the source uses the native pipe `|>` and the
  `\(x)` lambda. The committed render was checked with R 4.6.1.
  Windows needs R 4.2 or later for its UTF-8 character locale. The setup
  selects that locale when necessary, preventing negative table values
  from being printed as literal Unicode escape labels. On other systems,
  a UTF-8 locale must be available.
- The ten R packages the source calls: `jsonlite`, `knitr`, `rmarkdown`,
  `yaml`, `dplyr`, `tidyr`, `ggplot2` (3.4 or later, for `linewidth`),
  `readr`, `scales` and `tibble`. The setup chunk attaches eight of them.
  `rmarkdown` and `yaml` are called through `::`, and Quarto's R engine
  needs `rmarkdown` in any case.
- For the PDF output, a LaTeX installation, for example TinyTeX
  (`quarto install tinytex`), and the Times New Roman font. The source
  uses LuaLaTeX through Quarto so that this installed font is embedded.

The APA citation style (`apa.csl`) is bundled, so rendering does not
depend on network access.

```bash
cd manuscript
quarto render manuscript.qmd --to pdf
quarto render manuscript.qmd --to html
```

### The R environment

`renv.lock` records the exact versions of those ten packages and of
everything they depend on, as installed for the committed render, with
the R version. It was written by

```r
renv::snapshot(project = "<scratch directory>",
               lockfile = "<scratch directory>/renv.lock",
               packages = c("jsonlite", "knitr", "rmarkdown", "yaml",
                            "dplyr", "tidyr", "ggplot2", "readr",
                            "scales", "tibble"),
               prompt = FALSE)
```

and copied here. It is a record, not an active project library: the
directory has no `.Rprofile` and no `renv/` folder, so rendering uses
whatever library R already has. To render against the recorded versions,
restore them with renv into a library outside this directory (see the
`lockfile` and `library` arguments of `renv::restore()`) and put that
library first on `.libPaths()`. Activating renv in this directory with
`renv::init()` would instead write an `.Rprofile` that switches every
later render to an empty project library until it is restored.

## What the manuscript reads

The setup chunk loads every artefact through one manifest and checks,
before anything else runs, that each exists, parses without error and carries
every field the text quotes. A missing or malformed artefact stops the
render with its path and the field named. There is no fallback: the
paper does not print a typed-in number in place of one it could not
read. A final `claims-check` chunk re-derives the numbers typed into the
abstract, which is YAML and cannot hold inline R, and a few claims the
body makes in words, and stops the render when they no longer match the
artefacts.

Under `output/evaluation/`:

- Headline WER: `wer_summary.json` and `wer_report.csv`, the condition
  sweep's raw Large v3 cell on LibriSpeech test-clean (its report is the
  same file as `sweep_reports_postfix/wer_report.csv`), and `wer_ci.csv`,
  the bootstrap interval over that report
- Reader-cluster sensitivity: `speaker_cluster_sensitivity.json`, an
  exploratory whole-reader bootstrap of the same raw macro WER and the
  historical contraction and composite deltas, computed from the raw
  and pre-repair per-utterance reports. The setup checks its counts and
  point estimates against those reports, and the speaker section also
  checks its reader count against the plotted readers
- Scorer sensitivity: `scorer_sensitivity.json` and
  `scorer_sensitivity.csv`, a separate exploratory rescoring of raw and
  canonical-normaliser pairs. The setup checks the original rates and
  counts against the condition aggregate, matches JSON to CSV and checks
  the fixed samples and gain calculations. The alternative replaces
  edge apostrophes on both already-normalised sides. It also removes edge
  elisions and terminal possessive marks. It supplies no sampling interval
  or validated correction of the reference
- Condition sweep: `sweep_aggregate.csv`, `sweep_aggregate_prefix.csv`,
  `condition_ci_postfix.csv`, `condition_ci.csv`, per-utterance reports
  in `sweep_reports_postfix/` (the repaired sweep) and `sweep_reports/`
  (the pre-repair sweep, quoted as history), and
  `normaliser_gain_ami.csv`, the canonical normaliser's gain on AMI over
  the utterances both conditions score
- Multilingual benchmark: `fleurs_multilingual_summary.json`, and
  `fleurs_es419_v100_control.json`, the Spanish V100 control of its
  fourth arm
- Filler preservation: `disfluency_summary.json`
- Diarisation: `der_summary.json`, `der_report.csv`,
  `der_sweep_summary.csv`, `der_sweep2_summary.csv`, `der_sweep2.csv`,
  `der_sweep_selection.json`, `der_sweep2_selection.json`,
  `der_summary.json` in `der_tuned/`, `der_oracle/` (with its
  `der_report.csv`) and `der_concat/`, and the checks of the
  reconstructed meetings, `reconstruction_audit_test.json` and
  `reconstruction_audit_validation.json`
- Timestamps: `timestamp_summary.json`, `timestamp_report.csv`,
  `timestamp_skipped.csv`
- Name masking: `masking_summary.json`,
  `masking_summary_caseinsensitive.json`, `masking_summary_ner.json`
- Voice anonymisation: `anonymisation_summary.json`,
  `anonymisation_report.csv`, and the single-meeting configuration's
  `anonymisation_single_meeting/anonymisation_summary.json`
- Compute footprint: `footprint_summary.json`, `footprint_report.csv`,
  and the scheduler ledger it is estimated from, `arc_job_ledger.csv`,
  with `arc_job_ledger_provenance.json`
- Determinism: `determinism/determinism_repeat.json`,
  `determinism/determinism_seeds.json` and `determinism/gpu.txt` (the
  H100 run); the same two summaries with `gpu.txt` in
  `determinism/l40s_8781724/`, which also holds the per-utterance
  `wer_seed0_run1.csv`, and in `determinism/v100_8978760/`, and with
  `cpu.txt` in `determinism/cpu_8978759/`; and the comparison of the
  runs, `determinism/determinism_cross_accelerator.json`

Elsewhere in the repository: `output/case_study/ner_false_positive_test.md`
(the NER stage's false positives on the case study's transcript, a
podcast episode whose two voices were generated with NotebookLM),
`requirements.txt` and `requirements-lock.txt` (the dependency floors
and the locked cluster environment the Methods quote), `CITATION.cff`
(the archived release) and `evaluation/bootstrap_ci.py` (the module's
default replicate count).

## Regenerating the inputs

The manuscript's Data and Code Availability section points here for the
commands. Every command below writes to `my_check/` or to a directory of
its own, so that its output can be compared with the committed file
instead of replacing it.

Do not rerun an evaluation with its default output paths to "refresh" the
manuscript. Several modules write into `output/evaluation/` by default,
under the names of the committed files the manuscript reads:
`evaluation.benchmark_masking`, `evaluation.bootstrap_ci`,
`evaluation.footprint` (whose `--from-sacct` build also writes the ledger,
`arc_job_ledger.csv`) and `evaluation.fleurs_multilingual`. Pass
`--output-dir`, `--output`, `--ledger` or `--out` to write elsewhere.
`evaluation.condition_ci` and `evaluation.speaker_cluster_ci` require
`--output`, so neither can overwrite a table by omission.
`evaluation.sweep` also writes into `output/evaluation/` by default, under
names that carry the suite and model.

The two entry points for scoring your own transcripts leave the headline
pair, `wer_report.csv` and `wer_summary.json`, alone. By default,
`python -m evaluation.wer` writes `wer_report_transcripts.csv` and
`wer_summary_transcripts.json` under `output/evaluation/`, and
`sbatch hpc/evaluate_wer.sh` writes the same two names to
`$DATA/speech_transcription_env/output/evaluation/inhouse/` on the
cluster, refusing to start when the summary is already there unless
`OVERWRITE=1`. Either would replace the headline pair only if its report
and summary paths were set to those names, and the render would then
refuse the summary, because one written by `evaluation.wer` has no
benchmark block.

Corpus audio is not in the repository or in either archive. The
benchmarks stream it through the Hugging Face `datasets` library at
evaluation time.

### Intervals and sensitivity analyses, without a GPU

The intervals are recomputed locally from the per-utterance reports
committed under `output/evaluation/`. From the repository root, these
commands rebuild the three original interval files, the separate
reader-cluster sensitivity report and the normaliser's gain on AMI.
`wer_report.csv`, the report the first command reads, is the condition
sweep's raw report on test-clean, the same file as
`sweep_reports_postfix/wer_report.csv`.

```bash
# wer_ci.csv: the interval on the headline corpus estimate
python -m evaluation.bootstrap_ci \
    --report output/evaluation/wer_report.csv \
    --bootstrap 10000 --output my_check/wer_ci.csv

# condition_ci_postfix.csv: the paired intervals of the condition table
python -m evaluation.condition_ci \
    --reports output/evaluation/sweep_reports_postfix \
    --baseline raw --bootstrap 10000 \
    --output my_check/condition_ci_postfix.csv

# condition_ci.csv: the pre-repair intervals, quoted as history, from the
# reports the first sweep kept
python -m evaluation.condition_ci \
    --reports output/evaluation/sweep_reports \
    --baseline raw --bootstrap 10000 \
    --output my_check/condition_ci.csv

# speaker_cluster_sensitivity.json: whole-reader sensitivity of macro WER
# and the two historical paired costs, retaining the original intervals
python -m evaluation.speaker_cluster_ci \
    --report output/evaluation/wer_report.csv \
    --baseline output/evaluation/sweep_reports/wer_report.csv \
    --condition output/evaluation/sweep_reports/wer_report_contraction_fix.csv \
                output/evaluation/sweep_reports/wer_report_pipeline_full.csv \
    --bootstrap 10000 --seed 42 \
    --output my_check/speaker_cluster_sensitivity.json

# normaliser_gain_ami.csv: the canonical normaliser's gain on AMI over the
# utterances both conditions score
python -m evaluation.condition_ci \
    --reports output/evaluation/sweep_reports_postfix_ami \
    --prefix wer_report_ami_whisper-large-v3 \
    --primary-condition raw --bootstrap 10000 \
    --gains-output my_check/normaliser_gain_ami.csv \
    --output my_check/ami_paired_ci.csv
```

Every committed interval used 10,000 bootstrap replicates, not the
default 2,000, and seed 42, the default. Each of the three interval
commands reproduces its committed table exactly, and given the
committed path as `--output` (`output/evaluation/wer_ci.csv`,
`output/evaluation/condition_ci_postfix.csv` or
`output/evaluation/condition_ci.csv`) it writes over that table. Beside
its table, each also writes a provenance file, named after the table
with `_provenance.json` in place of `.csv`, that records the command's
arguments, the digest of every report it read and the commit it ran at.
The reader-cluster command is the one `output/evaluation/README.md`
gives, and its separate JSON report records the input paths and
digests, the replicate count and the seed. The last command's
`--output` holds the paired interval it computes beside the gain. The
manuscript does not report that interval, so it goes to a scratch path
even when `--gains-output` is `output/evaluation/normaliser_gain_ami.csv`.

The scorer sensitivity needs the recovered hypothesis dumps and the raw
and canonical-normaliser summaries of the English sweep. Those text
inputs are not in the repository. They are deposited at
<https://doi.org/10.5281/zenodo.23442874>, and the checksum receipt,
`output/evaluation/sweep_input_manifest.json`, identifies their bytes.
The committed summary reports are sufficient to render, but not to
reproduce this analysis. With the recovered bundle in the paths shown
below, run:

```bash
python -m evaluation.scorer_sensitivity \
    --inputs build/recovered_arc_sweep/inputs \
    --input-manifest output/evaluation/sweep_input_manifest.json \
    --aggregate output/evaluation/sweep_aggregate.json \
    --output-csv my_check/scorer_sensitivity.csv \
    --output-json my_check/scorer_sensitivity.json
```

The module checks source digests and reproduces the original
per-utterance metrics before calculating the alternative. The CSV and
JSON it writes preserve the original scores, identify the shared samples
and record the source digests. The canonical scorer, benchmark figures
and reader-cluster intervals are retained.

### Other results rebuilt without a GPU

The filler-preservation figures are scored from the hypotheses that the
condition sweep wrote for its Whisper Large v3 decoding of AMI,
`wer_hypotheses_ami_whisper-large-v3.csv`. The sweep writes such a dump
only when submitted with `DUMP_HYPOTHESES=1`, as `hpc/runs/sweep.env`
sets it. It is not committed, so `disfluency_summary.json` records the
digest of the file it scored (`source_sha256`), and the checksum receipt
of the deposited inputs, which include it, gives the same digest. With
the dump at `<inputs>/wer_hypotheses_ami_whisper-large-v3.csv`:

```bash
python -m evaluation.disfluency \
    <inputs>/wer_hypotheses_ami_whisper-large-v3.csv \
    --conditions raw,pipeline_full,whisper_norm \
    --json my_check/disfluency_summary.json \
    --csv  my_check/disfluency_report.csv
```

The rebuild differs from the committed pair in `run_metadata` and in
`source`, which records the path given.

The masking figures come from the injection benchmark, which needs no
audio. The dictionary-only arm is the default, and `--case-insensitive`
and `--ner` give the other two arms the manuscript reports:

```bash
python -m evaluation.benchmark_masking --output-dir my_check/masking
python -m evaluation.benchmark_masking --case-insensitive --output-dir my_check/masking
python -m evaluation.benchmark_masking --ner --output-dir my_check/masking
```

The footprint estimate is made from the committed scheduler ledger by
`python -m evaluation.footprint --output-dir my_check/footprint`. The
ledger itself was built by `python -m evaluation.footprint --from-sacct`
from a read-only `sacct` dump, with the query and options that
[hpc/README.md](../hpc/README.md) gives. Its provenance,
`arc_job_ledger_provenance.json`, records the query, the dump's SHA-256
digest and each job of the evaluation the ledger leaves out, with the
reason. The dump is not distributed, because it lists other projects'
jobs on the shared account. A rebuild from a dump of your own should pass
`--ledger` with a path outside `output/evaluation/`.

Three results are assembled locally from job outputs copied off the
cluster. `python -m evaluation.fleurs_multilingual`, with the options its
docstring gives and `--out` pointing outside `output/evaluation/`,
assembles the summaries of the multilingual wave's arms into the
committed one. `python -m evaluation.fleurs_control`, with its
docstring's options and `--out` pointed elsewhere in the same way,
compares the Spanish V100 control with those arms' Spanish summaries.
`python -m evaluation.determinism_cross` compares the
determinism runs with one another and with the condition sweep, from the
inputs that `determinism/determinism_cross_accelerator_runs.json` names
together with the command.

### Results that need a GPU cluster

On a Slurm-managed cluster that can allocate a GPU, submit each job
below with the record of its committed run in `hpc/runs/`, since that
record gives the settings and the hardware. A bare submission runs a
script's defaults, and for some experiments those are not the settings
behind the committed results. Decoded text can also change across
hardware, as the determinism comparison documents. Source each record
before submission, as [hpc/README.md](../hpc/README.md) shows. That page
also maps each job to the files it produced:

```bash
( set -a; . hpc/runs/anonymisation.env || exit 1; set +a
  sbatch --account='<your-project>' --gres=gpu:l40s:1 hpc/submit_anonymisation.sh )
```

- Condition sweep: `hpc/submit_sweep.sh`, once per model, with the
  settings and the cards recorded in `hpc/runs/sweep.env`, and then
  `hpc/aggregate_sweep.sh`. Locally, `python -m evaluation.sweep --limit
  500 --output-dir my_check/sweep` repeats the recognition runs against a
  smaller subset.
- Diarisation: `sbatch hpc/submit_ami_cache.sh` first builds the
  reconstructed meetings on disk, without a GPU, and the
  reconstruction audit, `python -m evaluation.audit_reconstruction`,
  re-checks that the rebuilt audio is aligned with its reference. Then
  `hpc/submit_der_sweep.sh` scores the hyperparameter grids on the
  development split (`hpc/runs/der_sweep.env`, `der_sweep2.env`) and
  `hpc/submit_benchmark_der.sh` scores the held-out test split
  (`der_default.env`, with `der_tuned.env`, `der_oracle.env` and
  `der_concat.env` for the comparisons, the last of them giving the
  utterance-concatenation figures).
- Timestamps: `hpc/submit_benchmark_timestamps.sh`, with the settings
  and the card recorded in `hpc/runs/timestamps.env`, which also records
  a run on other hardware that moved one boundary.
- Multilingual wave: `hpc/submit_benchmark_wer_multilingual.sh`, whose
  latest arm was submitted with `hpc/runs/fleurs_ml.env`, and then the
  assembly above. The Spanish V100 control ran the same script with
  `hpc/runs/fleurs_es419_v100.env`, from a checkout of the fourth arm's
  code as that record explains.
- Voice anonymisation: `hpc/submit_anonymisation.sh`, with
  `hpc/runs/anonymisation.env` (and `anonymisation_single_meeting.env`
  for the single-meeting configuration).
- Determinism: `hpc/submit_determinism.sh`, with
  `hpc/runs/determinism.env` for the H100 and L40S runs and
  `hpc/runs/determinism_v100.env` for the V100 run, and
  `hpc/submit_determinism_cpu.sh`, with `hpc/runs/determinism_cpu.env`,
  for the processor run. The comparison above then joins them.

### Provenance records

The condition sweep, the multilingual wave, the diarisation,
filler-preservation, timestamp, masking and anonymisation benchmarks and
the reconstruction audit record in their artefacts the commit they ran
at. Three masking arms recorded a working tree with uncommitted changes
until all four were regenerated from a clean tree in October 2026
(d6a5746). The record counts any changed tracked file, and those arms
had run after an earlier arm rewrote the committed results. The render
stops if an arm the manuscript reads records such a tree again, so that
the text can say so. The
intervals drawn on the condition sweep record their commit in the
provenance file beside each table. For the jobs that recorded no commit,
`hpc/runs/` and the commit that added each artefact identify the run it
came from.

## Conventions

The target is *Behavior Research Methods*, as an original research
article. Its [current author guidelines](https://link.springer.com/journal/13428/submission-guidelines)
were checked on 6 October 2026. They require APA 7, double spacing,
one-inch margins, page numbers at the upper right and an abstract of
no more than 250 words. The live guidelines state no overall word,
reference or display limit. They permit tables and figures within the
text for initial submission, but separate display pages are required in
the accepted production version.
The verified rules and unstated limits are recorded in
[journal_profile.json](journal_profile.json). The local APA7 skill supplied
the detailed mechanics because the official APA pages returned access
interstitials. This review checked citation formatting and the rendered
reference list. It did not repeat each source's bibliographic field
verification.

The PDF uses a professional title page and running title, a separate
abstract page, 12-point Times New Roman, unnumbered APA headings,
short display titles above each table or figure, and explanatory notes
below. Table bodies remain single-spaced. Appendix tables use explicit
B1 and C1 labels and hyperlinks, and their values are generated by the
same R code as the other tables. The bibliography uses the bundled APA 7
CSL, with author–date citations and a hanging-indented reference list.
The text uses British spelling throughout (*optimisation*, *labelling*,
*behaviour*). The bibliography lives in `references.bib` and is normalised
with `tools/bib_sentencecase.py` (see [tools/README.md](../tools/README.md)).

The funding statement and the corresponding author's postal address are
the author's, supplied on 17 October 2026, and no telephone number is given.
Confirm the existing competing-interest, consent and ethics statements
with the author, since formatting checks cannot establish their factual
completeness.
The availability statements cite the release the manuscript is
rendered from, whose version they read from `CITATION.cff`, archived at
<https://doi.org/10.5281/zenodo.23442766>, and the recovered inputs,
deposited at <https://doi.org/10.5281/zenodo.23442874> in two archives:
the English sweep's (`sweep_inputs_2026-10.zip`, with the decoder
commit's source) and those of the multilingual comparison, its Spanish
control and the cross-hardware comparison
(`multilingual_hardware_inputs_2026-10.zip`)
([docs/release_readiness.md](../docs/release_readiness.md) records the
release). The Declarations give the formal statements on data and code,
and a short Data and Code Availability section says what each archive
is needed for and points here for the commands. The Open Practices
Statement remains immediately before References, as the journal
requires.
