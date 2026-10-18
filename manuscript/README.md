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
  `readr`, `scales` and `tibble`. The setup chunk attaches eight of them;
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
before anything else runs, that each exists, parses cleanly and carries
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
  point estimates against those reports; the speaker section also
  checks its reader count against the plotted readers
- Scorer sensitivity: `scorer_sensitivity.json` and
  `scorer_sensitivity.csv`, a separate exploratory rescoring of raw and
  canonical-normaliser pairs. The setup checks the original rates and
  counts against the condition aggregate, matches JSON to CSV and checks
  the fixed samples and gain calculations. The alternative replaces
  edge apostrophes on both already-normalised sides; it also removes edge
  elisions and terminal possessive marks. It supplies no sampling interval
  or validated correction of the reference
- Condition sweep: `sweep_aggregate.csv`, `sweep_aggregate_prefix.csv`,
  `condition_ci_postfix.csv`, `condition_ci.csv`, per-utterance reports
  in `sweep_reports_postfix/` (the repaired sweep) and `sweep_reports/`
  (the pre-repair sweep, quoted as history), and
  `normaliser_gain_ami.csv`, the canonical normaliser's gain on AMI over
  the utterances both conditions score
- Multilingual benchmark: `fleurs_multilingual_summary.json`
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

Do not rerun an evaluation with its default output paths to "refresh" the
manuscript: the defaults write into `output/evaluation/` and replace the
committed files the manuscript reads. In particular, `python -m
evaluation.wer` or `sbatch hpc/evaluate_wer.sh` with their outputs in
`output/evaluation/` would overwrite the LibriSpeech benchmark in
`wer_summary.json` with a score of your own transcripts, and the render
now refuses such a summary rather than print it as the headline. Write
any such run elsewhere.

To check that the committed results can be rebuilt, see the README's
section on reproducing the published results and
[hpc/README.md](../hpc/README.md), which maps each GPU job to the files
it produced and records the exact invocation behind them. The intervals
are recomputed locally from committed reports. From the repository root,
these commands rebuild the three original interval files, the separate
reader-cluster sensitivity report and the normaliser's gain on AMI.
Each is shown writing to
`my_check/` so that it can be compared with the committed file instead
of replacing it:

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

# condition_ci.csv: the pre-repair intervals, quoted as history
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
default 2,000, and seed 42, the default. `evaluation.condition_ci`
requires `--output`, so no command can overwrite another's table by
omission. The last command's `--output` holds the paired interval it
computes beside the gain, which the manuscript does not report.

The scorer sensitivity needs the recovered hypothesis dumps and the raw
and canonical-normaliser summaries. Those text inputs have not yet been
deposited in a public archive. The public checksum receipt,
`output/evaluation/sweep_input_manifest.json`, identifies their bytes.
The separate summary reports are sufficient to render, but not to
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
per-utterance metrics before calculating the alternative. The canonical
scorer, benchmark figures and reader-cluster intervals are retained.

## Conventions

The target is *Behavior Research Methods*, as an original research
article. Its [current author guidelines](https://link.springer.com/journal/13428/submission-guidelines)
were checked on 6 October 2026. They require APA 7, double spacing,
one-inch margins, page numbers at the upper right and an abstract of
no more than 250 words. The live guidelines state no overall word,
reference or display limit. They permit tables and figures within the
text for initial submission; separate display pages are required in the
accepted production version.
The verified rules and unstated limits are recorded in
[journal_profile.json](journal_profile.json). The local APA7 skill supplied
the detailed mechanics because the official APA pages returned access
interstitials. This review checked citation formatting and the rendered
reference list; it did not repeat each source's bibliographic field
verification.

The PDF uses a professional title page and running title, a separate
abstract page, 12-point Times New Roman, unnumbered APA headings,
short display titles above each table or figure, and explanatory notes
below. Table bodies remain single-spaced. Appendix tables use explicit
A1 and C1 labels and hyperlinks; their values are generated by the same
R code as the other tables. The bibliography uses the bundled APA 7
CSL, with author–date citations and a hanging-indented reference list.
The text uses British spelling throughout (*optimisation*, *labelling*,
*behaviour*). The bibliography lives in `references.bib` and is normalised
with `tools/bib_sentencecase.py` (see [tools/README.md](../tools/README.md)).
Comments marked `PHASE2` in the source flag prose that describes results
due to be regenerated and must be re-checked against the new artefacts.

The funding statement and the corresponding author's postal address are
the author's, supplied on 17 October 2026; no telephone number is given.
Confirm the existing competing-interest, consent and ethics statements
with the author; formatting checks cannot establish their factual
completeness.
The evaluation also still needs its own persistent archived release:
the manuscript explicitly identifies the current software DOI as an
earlier release that predates these results. The Open Practices Statement
remains immediately before References, as the journal requires.
