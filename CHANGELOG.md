# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Finding identifiers
such as `T1-01` refer to the September 2026 codebase audit; the findings that
were not resolved in code are listed, with their reasons, in `ISSUES.md`.

## [2.1.0] - 2026-10-30

Two passes after release 2.0.0. The first, on 20 and 21 October 2026, was
made without access to the cluster: it edited the manuscript's prose, checked
the user documentation against the code and reviewed the code changed since
the last verified audit. The second, on 29 and 30 October, resolved what the
first had held back and the open items the cluster's return allowed: the
Spanish V100 control (NEW-05) and the scheduler ledger's recapture. Every
finding of either pass is resolved in `ISSUES.md` (CR-06 in code; see
DOCS-14 for its deposit).

No word error rate, diarisation, timestamp, filler, multilingual, masking
or anonymisation figure changed. The footprint's totals did, with the
recaptured ledger, and some result files changed in rows or provenance
fields only, as listed under Results. `tools/verify_regeneration.py`
regenerates all eleven CPU artefacts identically from the committed inputs.

### Fixed

- The name masker's honorific rule read any "miss" or "ms" before a name as
  a title ("I miss Sarah" gave "I [TITLE] [NAME]"), and from the first pass
  joined a sentence ending in "ms." (the unit) or "MS." (the disease) to the
  next. "Miss" now needs its capital and "Ms" its spelling; "Mr.", "Mrs.",
  "Dr." and "Prof." join the next sentence in any case, as at 2.0.0 (CR-01).
  A title before a possessive name ("Dr. Smith's") is masked with it (CR-02),
  and `case_insensitive` also relaxes the gate on the name after a title.
- An exception the NER stage raised after the model call was swallowed
  uncounted; it is now counted in `n_failures` (SC-17).
- `audio_redaction` left a word audible in a recording it reported as
  redacted when the name masker failed on it; that failure now stops the run
  with exit 2 and no output (SC-03). It also left a name audible when its
  word had no timestamps; it now refuses with exit 3 unless
  `--allow-untimed-names` is given, and reports the count on stderr either
  way (SC-18). A transcript it cannot read, in any encoding or shape, exits
  2, and `--languages-for-name-masking` with no language exits 2, as in
  `transcription.py` (SC-04).
- The residual-PII audit (`evaluation.audit_artefacts`) reported a file it
  could not read, or the transcripts of a recording whose masking log it
  could not read in full, as clean. It now marks them not checked, decodes
  logs with replacement, scans the `_review.json` files the pipeline writes
  (which copy the text of flagged segments), reports unreadable logs and
  skipped files on the console and in its JSON (`audit_complete`,
  `files_not_checked`), and exits 3 when the audit is incomplete (SC-06,
  SC-07).
- `setup/Dockerfile` did not copy `versions.csv`, so files written in the
  container would have recorded the version as "Unknown" (SC-09).
- `evaluation.wer` dropped a pair it could not score from a directory run
  without a trace; the summary now records `n_skipped_pairs` and
  `skipped_pairs` (SC-19).
- `confidence` and `tools/build_input_deposit.py` exit 2, as documented,
  for an unusable input, where they ended in a traceback. The fine-tuning
  script ends through `exit_without_finalising`, as the other streaming
  jobs do (SC-24).
- `evaluation.disfluency --audit-conditions` dropped a misspelt condition
  silently and ignored `--conditions`; it now names the condition with the
  list of valid names, and honours `--conditions` (SC-08).
- The Hugging Face token readers, `preflight.resolve_hf_token` and the HPC
  jobs' `arc_load_hf_token`, now read a file with a UTF-8 byte-order mark or
  saved as UTF-16, where the mark or the encoding made the token fail.
- `hpc/evaluate_wer.sh` refused a directory of `.vtt` transcripts, which
  `evaluation.wer` scores.
- `tools/build_input_deposit.py` passed `compresslevel=9`, which never
  reached its members, each written at zlib's default level as the deposited
  archive was. The argument is gone, the digest is documented as
  reproducible only under the same deflate implementation, and the detached
  record names the Python and zlib (compile-time and run-time) that built
  the archive (CR-03, CR-04). The archive's README gives the aggregate's
  rebuild command with its arguments (CR-06).

### Added

- The Spanish V100 control of the multilingual wave's fourth arm (NEW-05).
  ARC jobs 9124739 and 9124863 decoded es_419 again at 6f9bf56 on V100
  cards, and `evaluation.fleurs_control` compares the decode record by
  record with the four arms' Spanish summaries.
  `output/evaluation/fleurs_es419_v100_control.json` shows it matching the
  third arm on all 908 utterances and differing from the fourth on the same
  four, so the card, with its node, accounts for the fourth arm's Spanish
  drift. `hpc/runs/fleurs_es419_v100.env` records the jobs, and
  `docs/next_control.md` is now the record of the control.
- `.shellcheckrc`, so that `shellcheck -x` follows the job scripts' shared
  helpers; it reports nothing for the 24 tracked shell scripts (SC-01).
- Tests that `setup.py`, `CITATION.cff` and `versions.csv` agree on the
  release (SC-10), and that the Dockerfile copies the runtime data and
  modules `setup.py` ships (SC-09).

### Changed

- The manuscript was edited for coherence, concision and paragraphing,
  section by section against a document-level map of its argument, and
  checked against its earlier text for any change of meaning: claims stated
  in several sections are now stated in full once, and the share of
  sentences over 35 words fell from 24% to 11%. The determinism results are
  reported in Results (Reproducibility Across Hardware), the literature
  comparisons have moved from Results to the Discussion, and the Discussion
  has subheadings and a conclusion. The Methods and the Evaluation Protocol
  have subheadings, the appendices are lettered in the order the text first
  cites them (A, the atomic stages; B, the numeric results; C, the
  per-utterance dispersion), and the availability statements are merged,
  with every reproduction command in `manuscript/README.md`. Corrected on
  the way: the diarisation headline is described as the shipped, untuned
  settings; the AMI series are no longer said to share headsets; the
  Methods' stage descriptions match `transcription.py`, and the origin of
  the `undefined` artefact is no longer asserted; the Introduction says
  which test supports the null on which corpus; and the abstract writes its
  counts under ten as words, as APA 7 asks. No inline value, citation or
  chunk computation changed except as listed under Results, and the
  claims-check passes.
- The user documentation was checked against the code twice and its prose
  polished. Among the corrections: the common-word filter drops short names
  only from the Facebook lists, with "An" and "Ai" the curated exceptions;
  `--fix-spurious-repetitions` acts only on long runs;
  `requirements-lock.txt` is the frozen cluster environment, not the record
  of each result's versions; and a rebuild command in `docs/evaluation.md`
  no longer writes over a committed result.
- `requirements-dev.txt` lists ruff, pinned at 0.15.18, in place of flake8,
  black and mypy, which nothing configured or ran (SC-11, SC-22). ruff now
  enforces the line length too, after 198 long lines were wrapped with each
  file's abstract syntax tree checked unchanged (SC-23, LINT-01), and the
  273 `noqa` directives that suppressed nothing are gone, their reasons kept
  as comments (SC-20).
- Docstrings for the command-line entry points that had none, and comments
  that restated their code removed (SC-12, SC-13, SC-15, SC-16).
  `fetch_codex_mentis` uses the shared digest helper (SC-21).

### Results

- `arc_job_ledger.csv`, its provenance and the footprint report and summary
  were recaptured on 30 October 2026 with the same query. They add six jobs
  of 17 to 19 October (three test-suite runs, the case study's re-run 9124852
  and the Spanish control's two jobs) to the 197 of 4 October: 203 jobs,
  157.0 GPU-hours (was 155.7), 96.7 kWh (was 96.0) and 20.02 kg CO2e (was
  19.86).
- The four masking arms were regenerated from a clean tree after the
  honorific fixes: in each report the 66 title-by-possessive rows read
  "[TITLE] [NAME]'s", and 136 lower-case title rows of the two
  case-insensitive arms change; every summary field outside `run_metadata`
  is unchanged, and the NER arms record 1,940 calls and 0 failures.
- `artefact_audit.csv` and `.json` scan the three example review files,
  which are clean, and carry the new completeness fields; every count is
  unchanged.
- `scorer_sensitivity.json` and `sweep_decode_provenance.json` were
  regenerated after SC-19's edits to the files whose digests they record:
  only those digests and the recorded commit changed.

### Removed

- The unused helper `evaluation.fetch_codex_mentis._known_sha` (SC-02).

## [2.0.0] - 2026-10-18

### Follow-up on 6 October 2026

The completed manuscript and small-fix branches and the issue reconciliation
are brought together on `study-followup-2026-10-06`. A new reader-cluster
sensitivity analysis preserves the utterance-weighted macro-WER statistic
while resampling whole LibriSpeech readers. The headline 95% interval widens
from 5.75–6.70% to 5.08–7.36%; the historical contraction and composite
costs remain positive. The original interval artefacts are retained, and
the separate report records its inputs, their digests, seed and resampling
settings. It is included in the CPU regeneration gate. The manuscript
reads the new estimates dynamically and checks their point estimates and
sampling units against the source reports.

The review tool gains optional checks for zero-duration cues and passages
repeated across cue boundaries (NEW-12). Matching retains numerical
differences, marks both occurrences and records the thresholds used.
Existing review behaviour remains the default, and the committed case-study
review and its manifest retain their original contents. The new checks
are advisory: their precision and recall on ordinary long-form speech
have not been estimated.

The scientific prose now distinguishes a rule's tested behaviour from its
empirical value, bounds conclusions about reader dispersion and voice
de-identification to the observed samples, and removes an unsupported
accuracy ranking of cloud services and an extrapolation from general
language models to speech recognition. The anonymisation discussion cites
the current VoicePrivacy 2026 protocol and distinguishes the fixed-model
linkage test here from evaluation against an adapted attacker.

Printed fine-tuning and benchmark commands now quote paths containing
spaces or apostrophes. Regression checks recover the exact checkpoint
and output-directory arguments from both the shell and Python suggestions.

Local verification used Python 3.13.7, NumPy 2.3.2 and jiwer 4.0.0.
The complete test suite returned 2,211 passed, 38 skipped and one expected
failure; the skips concern optional speech dependencies, ffmpeg, platform
permissions and an uncommitted scheduler dump. The final reader-cluster
tests passed separately after an adversarial review strengthened their
unequal-cluster fixture. The regeneration gate matched all eleven CPU
artefacts under its documented comparison rules. HTML and PDF renders
passed all 91 knitting segments, including the claims check, with Quarto
1.10.18 and R 4.6.1; the new text and references were checked in the PDF.
This scoped `/strong-study` follow-up uses the committed ARC results.
Release metadata, dictionary provenance and the full submission-format
review remain to be completed.

### Submission and archive follow-up on 6 October 2026

The installed distribution now includes `data/curated_names.csv` and
`versions.csv` beside `transcription.py`. A wheel previously imported but
failed when the default masker tried to open its dictionary. Three
distribution tests build a wheel and source archive without fetching
dependencies, rebuild from that archive, and install the wheel outside
the checkout to exercise the masker and release stamp.

A pinned CPU GitHub Actions workflow is added to test the statistical
contracts, scoring, masking, review and distribution, and to run the
eleven-artefact regeneration gate. The gate's narrow LF/CRLF dictionary-digest allowance
requires both digests to identify the current input and all remaining
nonvolatile fields to match. Changed names or benchmark measurements
still fail. The benchmark now records the requested `benchmark.limit`
separately from the actual streamed count (XREF-01). The condition audit
also describes GPU precision against the current production request
(EWER-04).

All 255 sweep summaries and 15 hypothesis CSVs have been recovered from
ARC without new decoding. Each of the 270 files matches its remote
SHA-256, and every summary digest matches the committed aggregate.
Strict aggregation reproduces its complete CSV byte for byte and all
scientific JSON fields and types (REGEN-05). These locally recovered
inputs still need a public deposit, attribution and a versioned recipe.
`docs/release_readiness.md` orders the remaining release work so that a
new DOI is reserved before the source tree is frozen.

A separate exploratory scoring analysis reuses the retained raw and
`whisper_norm` strings, reconstructs their original metrics at full
precision, and tests symmetric removal of apostrophes at token edges.
Internal contractions remain, while edge elisions and terminal possessive
marks also lose their edge mark; the alternative is not a validated gold
scorer. On test-clean, Large v3's common-sample macro normaliser gain
falls from 64.43% to 22.42%; on AMI it stays near 6.8%. The original
scorer, grid and headline interval artefacts remain intact. The new
report makes this dependence on scoring conventions measurable (NEW-11).

The dictionary's verified inventory and missing provenance facts are
recorded in `docs/dictionary_provenance.md` (G3). The Git history and
Word-document review is recorded in `docs/privacy_review.md` (G6). All
eight merge-inclusive Gitleaks findings were bibliography keys; this is
not a claim that the history contains no personal information. The
README infographic has been retired to `docs/historical/`, with its
original bytes and a note identifying its unsupported compliance,
replication and performance claims. Transcript/log originals and Git
history remain intact.

The complete collected test suite passed 2,231 tests, with the same
38 environment-dependent skips and one expected failure, in 647 seconds.
The 30 new scorer-sensitivity tests were collected separately after that
run began, and the final focused CPU selection passed all 353 tests.
The final local gate matched all eleven artefacts. Both final renders
passed 45 R code chunks, 91 knitting segments and the claims checks.
The PDF has 100 pages with twelve tables and six figures; all eighteen
display pages and the front matter were visually checked. The HTML has
34 matched references and no unresolved cross-references or broken
fragment links. Submission formatting now uses twelve-point Times,
double spacing, APA display titles/notes and separate title and abstract
pages. Funding and correspondence placeholders remain for the author.

The scorer report was reproduced from clean source commit `41fe712`, with
byte-identical CSV and identical scientific JSON fields and types. Its
JSON now records that clean producer. The submission review's retained
language counts, per-page flags and unavailable-skill limits are recorded
in `docs/release_readiness.md`; unchanged formula counts are not presented
as a whole-manuscript stylistic improvement. An incremental credential
scan of the submission/archive commit returned no findings, within the
bounded scope documented in `docs/privacy_review.md`.

### Follow-up on 10 October 2026

The review command now refuses `--repeated-passage-window` given without
`--repeated-passage-words` and exits with status 2. It previously
accepted the window alone, exited 0 and ran no passage check. The help
text and `docs/local_app.md` say that the passage threshold counts
tokens, so a contraction counts as two.

As committed on 6 October, the CI workflow set `TMPDIR` from the runner
context in the job's `env`, where GitHub does not allow that context, so
the file failed validation and no step could run. A first step now
exports `TMPDIR` through `GITHUB_ENV`. actionlint 1.7.7 passes the
corrected file. The workflow first ran on GitHub on 17 October (below).

### Follow-up on 17 October 2026

The name masker now masks an abbreviated honorific written with a full
stop ("Dr.", "Mr.", "Mrs.", "Ms.", "Prof.") as `[TITLE]` when a name
follows it. It split its text after every full stop, so "Dr." ended one
sentence and the name began the next, and the honorific rule never saw
the name (NEW-09). A piece of text ending in one of those abbreviations is
now joined to the next. The full words, such as "sir", still end a
sentence. The masking benchmark writes its titles without a full stop,
so none of its figures moves; masked transcripts that contain such a
title change, and their masking logs gain a `[TITLE]` row.

`transcription.py` gains `--review-flag-zero-duration`,
`--review-repeated-passage-words` and `--review-repeated-passage-window`,
which run the review's two optional checks (NEW-12) in the review a
timestamped run writes. They are off by default, so a default run writes
the review it always has. They are checked before any audio is read, and
an option that would change nothing, such as a window without its
threshold, exits 2. The run manifest records the settings as
`review_settings` only when a check is on, so a default run's manifest is
unchanged. The case-study job runs both checks at their suggested
settings. The case study was re-run at `fc652ab` (ARC job 9124852, an
NVIDIA L40S, since the RTX A6000 nodes that ran job 8983112 are
reserved), and its summary, report, review and manifest replace job
8983112's. With the masker fix its summary gains one redaction, the
`[TITLE]` of "Dr." in the closing credits, 4 among 5,382 tokens. Its
review flags 13 of 403 cues where job 8983112's flagged 4 of 405: the
same four of high speech rate, and both passages Whisper wrote twice,
the zero-length copy at 189.98 s and the copy crammed into cue 84,
linked to the speech they repeat. The text differs from job 8983112's in
eleven places, with the change of card, and the cue count with it.
`output/case_study/README.md`, `hpc/runs/case_study.env` and
`tests/test_case_study_results.py` describe and pin the new run. The job
ledger, captured on 4 October 2026, does not hold it, and the
manuscript's footprint section now says so.

The CI workflow ran on GitHub for the first time once the author approved
pushing the review branch. Its first run failed four example-variant
tests: the new `review_settings` field had changed every default run's
manifest, and it is now written only when a review check is on. Its
second run passed the tests and failed the regeneration gate on the
artefact audit, whose files were sorted case-insensitively on Windows,
where the committed report was made, and case-sensitively on Linux. The
audit now orders files by their lower-cased path components on every
platform, which reproduces the committed report. The third run (GitHub
run 39053843039) passed all 389 tests of the selection and matched all
eleven gate artefacts on Ubuntu 24.04 with Python 3.12.12.

Release 2.0.0 goes to the public repository that has held the software
since 1.0.0, <https://github.com/pablobernabeu/secure_local_HPC_speech_transcription>,
as one snapshot commit, and is archived at
<https://doi.org/10.5281/zenodo.23442766>. The English sweep's 270
recovered inputs go to a separate data record,
<https://doi.org/10.5281/zenodo.23442874>, with a `git archive` of their
decoder commit `6f9bf56`, which the public repository does not hold.
`tools/build_input_deposit.py`, which writes the input archive, now takes
that snapshot as `--decoder-source`, refuses a ZIP of another commit and
describes the snapshot in the archive's README. It also deposits the
manifest with LF endings on any checkout: built from a Windows working
tree, the deposit had held a manifest that differed from the committed
blob.

### Earlier result-affecting fixes

The changes below predate the audit and explain why release 1.0.0 cannot
reproduce the later evaluated workflow (DOCS-14). `f6e708e` stopped the
Unicode stage destroying diacritics. `c0f58c5` gated English contractions
by language, and `c83162f` corrected language detection to use
`detect_language`. `af3bee0` repaired the English contraction rules.
The audit subsequently found further Unicode and language-gate defects;
their later repairs and re-run results are recorded below.

`5f1a3ea` stopped voice anonymisation from dividing its output by its own
peak, which let one ringing sample set the gain for a whole recording.
In that commit's measurements the output came back twenty times quieter
at an input peak of 0.9, and across input peaks from 0.05 to 0.99 its
loudness ran from 0.03 to 1.09 times the input's. The gain is now set by
matching the input's root-mean-square loudness, samples above a knee of
0.9 are compressed, and the measured ratio lies between 0.49 and 1.00.
`f7c85b0` computed pooled WER from alignment
counts instead of averaging utterance rates. `25068a8` passed hypothesis
dump options through the sweep and corrected teardown, and `f023ddb`
gave each sweep its own output directory. Those output-path repairs
prevented later conditions or runs overwriting retained hypotheses.

### Scope of this release

A codebase audit (`/strong-codebase`) of branch
`phase-2-diarisation-and-lit-review` at `10981d4` verified 330 findings.
Its first pass fixed those whose fix changes no committed number and held
every fix that would move a committed result in `ISSUES.md` until a
deliberate re-run.

A second pass, from 26 September 2026, applied many of the fixes held
there. Some change the transcripts the pipeline writes, in the clean-up
stages and the name masker (see Fixed and Security and privacy). The
others are in the evaluation: the WER conditions and their scoring
(EWER-03, EWER-05, EWER-13), the anonymisation transform, sample and
linkage statistics (EPRIV-02, EPRIV-03, EPRIV-04, EPRIV-15, EPRIV-16), the
filler-preservation measure (ESTATS-01, ESTATS-08), the timestamp benchmark
(ESTATS-02, ESTATS-12, DEPS-06) and the DER scoring (EDER-01, EDER-02,
EDER-06). The benchmarks request the Hub revisions pinned in
`evaluation/revisions.py` and list any that a library could not enforce
(DEPS-04, DEPS-16, EWER-10). The pipeline itself still loads the latest
revision and records the snapshot it loaded.

Most of the results those fixes move were then regenerated. Where no GPU
is needed, this was done locally: the masking benchmark (a08265c), the
example variants (f041d21) and the artefact audit over them (b7fcdd6,
12275ed). The rest came from a re-run wave on the Oxford ARC cluster, at
code `6f9bf56` with a clean tree, on 27 and 28 September 2026. It ran the
WER sweep (jobs 8917985 to 8917987), the timestamp benchmark (8917980,
8917981), the anonymisation benchmark (8917988, 8917989) and the FLEURS
benchmark (8917984), each after a short pre-flight run, and the case study
(8918023), which failed (see Fixed). From these came the WER matrix and its
paired intervals, the headline WER pair and interval, the timestamp
results, the anonymisation curve and the FLEURS summary's fourth arm. The
pre-flights ran at `6f9bf56` too, except the two for the timestamp
benchmark, jobs 8913990 and 8913991, which ran earlier on 27 September at
`76d9489`, also with a clean tree. The filler-preservation results were
rescored locally from the sweep's AMI hypotheses. Two CPU jobs on 27
September added the AMI reconstruction audit (8918334) and the measured
FLEURS diacritic shares (8918340).

Three more waves ran on 4 October 2026, each from a clean clone: the six
diarisation jobs at `9cb43e3` (8976354 to 8976358 and 8976362), the
determinism check on a processor and on a V100 at `f2578b8` (8978759 and
8978760), and the case study at `c4c7b38` (8983112), after a run at
`f2578b8` (8978758) had failed (see Fixed). The DER results and the case
study are now theirs. The determinism check also gained a comparison of
one decode across hardware configurations, built from three GPU runs
already made, which the processor and V100 runs then joined (see Added).
Neither the comparison nor the CPU and V100 runs moved a committed number.
Once every job had finished, the job ledger was captured again and the
footprint estimated from it. Changed gives each regenerated result's moves
and the findings behind them, and the manuscript now reports them.

At 22:00 BST on 2026-10-04 no job of the evaluation was queued or running
(squeue), and every result the evaluation reports is committed. One check
is still open:

- A FLEURS decode that would show whether the GPU explains the fourth
  arm's raw drift (NEW-05). The P100 decode first planned cannot be made:
  ARC's P100 nodes, htc-g032 to htc-g034, have been drained since
  2026-09-04 to be decommissioned, and still were at 23:19 BST on
  2026-10-04 (sinfo). NEW-05 proposes in its place a Spanish decode at
  `6f9bf56` on a V100, the GPU model arm 3 decoded Spanish on, which
  htc-g003 and htc-g004 had in service at that time. It needs one GPU
  job, which has not been submitted.

These decisions are the author's:

- The release. No version has been cut: `versions.csv`, `CITATION.cff` and
  `setup.py` still say 1.0.0, and the repository has no tag (T2-02,
  MS-09). Version 2.0.0 is recommended, because this release removes
  scripts and options (see Removed), stops with an error on masking
  settings it used to accept silently (see Security and privacy), and
  changes the transcripts the pipeline writes (see Fixed). It is to be cut
  once the licence is settled, and the manuscript is then to cite its
  version DOI in place of the 1.0.0 record, as its two PHASE2 notes say.
  `ISSUES.md` gives the steps in order under DOCS-14.
- The licence. `LICENSE` is MIT, as `README.md`, `setup.py` and
  `CITATION.cff` say, while `Licence.md` holds CC BY 4.0, and nothing says
  which paths each covers (XREF-14, DOCS-16).
- The scoring of quotation marks. The scorer keeps the single quotation
  marks Whisper writes around dialogue. Re-scored from the hypotheses of
  sweep job 8917985, which are not committed, with the apostrophes at
  token edges set aside on both sides, Large v3 on LibriSpeech test-clean
  loses 842 of its 2,030 raw errors, nearly all of them quotation marks,
  and with them most of the Whisper normaliser's gain on that corpus. The
  manuscript says which of its claims hold as scored. A change would move
  committed WER figures, so `evaluation/wer.py` and every WER artefact are
  as they were (NEW-11).
- The footprint window. The committed ledger opens on 2026-05-16, the day
  of the evaluation's first job, and holds 197 jobs and 155.70 GPU-hours.
  Opened on 2026-05-20, as the June capture's query was, it would hold 179
  jobs and 134.66 GPU-hours (ESTATS-06).
- The Funding declaration, which the manuscript leaves as a placeholder to
  complete before submission.

`python tools/verify_regeneration.py` is the rebuild-and-compare gate. In
a temporary directory, it rebuilds the ten committed artefacts that need
no GPU: the footprint report and summary, `condition_ci.csv`,
`condition_ci_postfix.csv`, `normaliser_gain_ami.csv`, `wer_ci.csv`, the
artefact audit's CSV and JSON, and the report and summary of the default
masking arm. Each is compared with the committed file byte for byte, then
with CRLF read as LF. A JSON file may also differ in the keys that record
when and from which commit it was written, and `wer_ci.csv` in the path
separator of its `file` column. At `913ad58`, and again at `fb22ece`, on a
Windows checkout, a full run finds the footprint report and summary,
`condition_ci.csv`, `condition_ci_postfix.csv`, `normaliser_gain_ami.csv`,
`wer_ci.csv`, the artefact audit's CSV and JSON and `masking_report.csv`
identical byte for byte, and `masking_summary.json` identical apart from
those keys, so the gate passes. The footprint pair had differed since
da8f1ca and a1e7933, until e3e436d regenerated it from the ledger captured
on 2026-10-04. Line endings follow the checkout, not the code. The files
are stored with LF, a Windows checkout writes them with CRLF, and the CSV
writers emit CRLF on every platform, so on a Linux or macOS checkout the
CSVs match up to line endings only.

The gate rebuilds only the default masking arm. The case-insensitive arm
is rebuilt with `python -m evaluation.benchmark_masking --seed 42
--case-insensitive`, and the two NER arms with `--seed 42 --ner`, with and
without `--case-insensitive`. The NER arms need gliner and a model
download (`python -m ner_masking --download`). All four masking arms were
regenerated on 27 September 2026 (a08265c), at commits that differ only in
tests.

The GPU results cannot be regenerated locally. The summaries of the re-run
waves record the code commit and package versions of their run, except the
case study's, whose run manifest records them, and the determinism runs',
whose commits `determinism_cross_accelerator_runs.json` gives with how each
is known. Every job of those waves wrote an environment record beside its
results on ARC (see Added).

`ISSUES.md`, retitled "Issues and their status" in 72c0d95, opens with
what a Status paragraph means and with status counts that a script makes
from the file. It opens every finding, and each of the six areas the
audit did not cover (G1 to G6), with a Status paragraph written after the
re-run wave (7be798a, 830d290, a5df136, 1d21e29, 2c04943 and 01cde97,
corrected up to d048612) and since brought up to date with the October
runs. It also records the findings made after the audit. NEW-03 to NEW-06
(1d21e29) are three from the re-run wave's results and the case study's
missing manifest, found in the log of its re-run, job 8978758. NEW-07 to
NEW-10 and NEW-12 come from checks of the case study's name masking and
review, and NEW-11, the scoring of quotation marks, from the cross-check
of the rewritten manuscript. Its observations from ARC are brought up to
date, the pyannote cache incident among them (d2938b2).

### Security and privacy

- `audio_redaction.py` read word text under the wrong JSON key, found no
  names in any transcript the pipeline writes, and wrote an unredacted copy
  while exiting 0. It now reads the pipeline's key, takes its decisions from
  the run's own redacted transcript, and exits 3 without writing when a
  masked transcript yields no redaction (EPRIV-01, EPRIV-13, EPRIV-30).
- The review file (`*_review.json`) stored unmasked segment text even under
  `--redacted-timestamps-only`. Flagged segments are now masked when masking
  is on (T3-01).
- The name masker let a capitalised name through when it followed an opening
  quote, bracket or dash. The capitalisation test now reads the token's core,
  a change that alone left the masking benchmark unchanged (T1-03, EPRIV-10,
  masker part).
- The placeholder now keeps a possessive whole ("[SURNAME]'s") and takes a
  name's own apostrophe with it ("O'Brien" becomes "[SURNAME]") (T1-03). The
  23 curated names shorter than three characters, Li, Wu and Al among them,
  were dropped whenever common English words were excluded, as they are by
  default for English, so an English transcript never had them masked. They
  are now masked, and two of them that are also common English tokens, the
  article "an" and the acronym "AI", join the common-word list (T1-07).
- Masking no longer becomes a silent no-op when the curated name list is
  missing or the language list is empty, an ISO code or unknown: these now
  stop with an error, and a capitalised language name is read in lower case
  (T1-06, T3-02).
- NER masking passes its threshold to GLiNER by keyword (it was landing in
  the `flat_ner` slot), masks hyphenated and apostrophised names such as
  O'Brien and Jean-Luc, loads a pinned model revision without network access,
  and fails the benchmark if any NER call failed (EPRIV-08, EPRIV-09,
  EPRIV-12, EPRIV-18).
- `fetch_codex_mentis` verifies downloads against the committed SHA-256 and
  size, and a `--limit` run no longer overwrites the committed checksums
  (EPRIV-06).
- An unreadable or empty `--key-file` now fails signature verification
  instead of silently downgrading it to an integrity check (CORE-03).
- The ffmpeg shim lives in a per-user directory and is rewritten when stale
  (CORE-23). The HuggingFace token is written with mode 0600, is not
  overwritten without `--overwrite-token`, is no longer echoed, and the
  fine-tuning script no longer accepts it on the command line (CORE-14,
  EDER-25).
- The temporary enhanced recording is deleted on every exit path (T3-11).
- `.gitignore` keeps transcripts and name-masking logs out of commits
  (OUTPUTS-07).

### Fixed

- `--save-name-masking-logs` crashed the run on the first masked name
  because the log rows gained a `source` column the CSV writer did not
  declare (T1-01, EPRIV-07).
- The run manifest collected artefacts by filename prefix, so it certified
  other runs' files; it now lists exactly the paths this run wrote, and
  verification escapes the stem (T3-03, CORE-01).
- Speaker attribution gave a zero-length word the previous speaker even
  inside another speaker's turn (T2-05). Checked against the committed
  example variants and the case-study transcript: no speaker changes.
- Speaker-attributed transcripts lost every turn break after cleaning and
  masking (T3-04).
- Untimed words or segments crashed speaker stamping (T3-08); the WebVTT
  formatter could emit `60.000` seconds (T3-18); `.docx` paths were built
  with `str.replace` on the whole path (T3-21).
- The diarisation loader failed to load a local pipeline directory, fell
  through to the Hub after a local failure, and retried the whole pipeline
  when inference (not decoding) failed (T2-03, T2-04, T2-11).
- Requested artefacts that failed to write were swallowed and the job still
  exited 0; the run now fails and lists what is missing (T3-07, T2-08,
  XREF-15).
- The provenance block recorded an assumed English as the detected language,
  and omitted settings that change the output (T3-09, T3-10).
- `preflight` could crash on its own audio check, missed tokens stored by
  `huggingface-cli login`, and named a CUDA wheel index that cannot serve the
  installed torch (CORE-02, CORE-11, CORE-21).
- `audio_io.load_audio(mono=False)` mishandled multichannel audio and
  swallowed the native decode error (CORE-06, CORE-07).
- The local GUI failed on Windows when the pipeline printed non-ASCII text
  (CORE-16).
- `condition_ci` assumed `wer_report.csv` was the baseline even when the
  baseline had its own file; it now reads the primary condition from its
  summary (ESTATS-03). FLEURS utterance ids repeat, so repeats are renamed
  `<id>__<n>` and duplicate keys are refused in alignment (EWER-06).
- The WER benchmark turned import and code errors into silently missing grid
  cells; `sweep_aggregate` now refuses duplicate cells and, unless
  `--allow-incomplete` is given, missing ones (EWER-12, TESTS-09).
- The footprint model charged 0 W to an unrecognised GPU; it now raises
  (ESTATS-05, part).
- A DER cache built with `--limit-meetings` was later treated as complete,
  and cache reuse never checked its settings; the manifest now records and
  validates them, and older manifests are still accepted (EDER-04, EDER-05).
- Interrupted DER runs left a partial report beside the previous summary;
  outputs are now written together at the end (EDER-24).
- The fine-tuning script reused data from a run with different limits, split
  AMI session series across train and dev, called APIs pyannote.audio 3.4.0
  does not have, and was unseeded (EDER-07, EDER-09, EDER-10, EDER-11).
- Import-time `warnings.filterwarnings("ignore")` in `transcription.py` and
  the DER modules silenced every warning in any process that imported them,
  the WER sweep included (T1-09, EDER-16, ESTATS-19).
- SLURM wrapper: `--help` hung, arguments were flattened through `eval`,
  batch arrays were sized from one directory and indexed into another, a
  successful cluster-qualified job id triggered a second submission,
  options transcription.py accepts were rejected, and the `--flag=value`
  spelling of the wrapper's own options slipped past its checks (SHELL-03,
  SHELL-15, SHELL-16, T3-13, XREF-11, SHELL-R3). Each array task now reads
  its recording from a list frozen at submission, which is written
  owner-only and against which failed tasks can be retried.
- Job scripts ignored failures of the steps they ran and exited 0
  (SHELL-12, SHELL-18, SHELL-19, SHELL-21). Multilingual outputs are named by
  model as well as language (SHELL-13).
- The case-study job, `hpc/submit_case_study.sh`, gave its structural
  evaluation `$DATA/codex_mentis/manifest.json`, which does not exist on
  ARC, where the recording was copied by hand. Since 4b22326 the
  evaluation refuses a missing manifest (EPRIV-23), so re-run 8978758
  failed after transcribing. The job now takes `CASE_MANIFEST` when it is
  set, then `$DATA/codex_mentis/manifest.json` when a fetch has written
  one, and otherwise the committed `data/codex_mentis/manifest.json`,
  whose episode 5 entry holds the SHA-256 and size of the recording on
  ARC. It checks the manifest before transcribing, exits 2 when it is
  missing, and names it in the environment record (NEW-06; ca75ced).
- `evaluation.benchmark_podcast` refused a missing manifest but accepted a
  named one that lists no episode duration, and then scored every
  transcript without coverage figures and without a warning, which is the
  loss EPRIV-23 fixed. It now refuses that manifest too. The committed
  manifest lists nine durations, so no result changes. New tests check
  that the case-study job stops before transcribing when a clone has no
  manifest to use, that `CASE_MANIFEST` wins over a fetch manifest as well
  as over the committed one, and that the environment record names the
  manifest used (NEW-06, EPRIV-23; c4c7b38).
- The Dockerfile left out modules `transcription.py` imports (SHELL-04).
  It also named its base image by a tag that can be moved, ran Ubuntu
  22.04's Python 3.10, below the 3.11 floor, and installed packages from
  `requirements.txt`, which gives only floors. It now names
  `nvidia/cuda:12.1.1-devel-ubuntu22.04` by the digest its tag resolved to
  on Docker Hub on 2026-09-26, installs Python 3.12 from the deadsnakes
  PPA in a virtual environment, installs `requirements-lock.txt` with the
  PyTorch cu121 index and runs `python -m preflight --lock` at build time.
  The apt packages are still unpinned. No container runtime was available
  locally or on ARC, so the image has never been built, and its header
  marks it unbuilt and unverified (DEPS-14; 20ee3b6).
- `setup/setup_environment.sh` installed an unpinned torch, torchvision and
  torchaudio from the cu121 index and a short unpinned list, without
  `requirements.txt`, so python-docx, names-dataset, jiwer and datasets
  were missing. It now installs `requirements-lock.txt` with the cu121
  index and checks every pin with `python -m preflight --lock`. It has to
  run on a compute node, since ARC's login nodes cap virtual memory at
  2 GB, under which the CUDA build of torch cannot load (CORE-21, setup
  part; 20ee3b6).
- The clean-up stages changed in the second pass, and with them the
  transcripts the pipeline writes. The Unicode strip deleted whole scripts
  (a Chinese, Japanese or Korean transcript came back empty), typographic
  apostrophes and quotes, currency signs and isolated ASCII symbols. It now
  keeps the letters, marks, digits, punctuation and currency and
  mathematical signs of every script, maps typographic quotes to ASCII, and
  removes only emoji and characters in the Unicode categories So, Sk, Cc,
  Cf, Cs, Co and Cn (T1-02). Punctuation spacing split numbers ("3. 5",
  "1, 000", "10: 30"), dotted abbreviations and host names, removed the
  space before an opening quote and cut an ellipsis to a full stop. It does
  none of these now (T1-04, T2-01). The repetition repair counted each
  repeated phrase about twice, so it cut phrase loops of five or more copies
  where its stated leniency allows ten, and, being case-sensitive, never cut
  a loop whose first copy was capitalised (T1-05). The `undefined` artefact
  is now marked at the edges of the text and in runs (T1-14),
  sentence-initial letters of every script are capitalised (T1-16),
  hyphenated backchannels are bracketed whole, as in "[Uh-huh]" (T1-18), and
  the English-only stages read Whisper's `<|en|>` as English (T2-14).
- `setup/cache_pyannote_arc.py` downloaded the diarisation models into the
  Hugging Face hub cache (`<HF_HOME>/hub`), which pyannote.audio 3.4.0 never
  reads, so pre-caching them did not stop a compute node from downloading.
  It now downloads into pyannote's own cache (`$PYANNOTE_CACHE`, or
  `~/.cache/torch/pyannote`), at `main` so that an offline load resolves.
  When `main` has moved from the revision `evaluation/revisions.py` pins,
  it fetches the pinned snapshot too and exits 2 (REV-01; 20ee3b6). Its
  exit-2 message said that the loaders read `main`. Since d8d620f it says
  that a load at a pinned revision finds the pinned snapshot, which the
  script has just cached, while `transcription.py` loads the pipeline at
  `main` and every pipeline load reads its segmentation and embedding
  models at `main`. The script's docstring has said so since f03f1df,
  whose list of loaders 75e1a58 completed.
- The test suite could reach the machine's real model caches. On ARC, test
  jobs 8913985 and 8917186 ran the pyannote pre-cache test against
  `~/.cache/torch/pyannote`. Its stand-in downloader wrote, through the
  snapshot's link, a config that names no pipeline over the cached
  `pyannote/speaker-diarization-3.1` config. Every later load of the pipeline
  failed with `KeyError: 'name'` until the file was restored on 2026-10-04:
  the re-run wave's case study (8918023) failed, having transcribed without
  the speaker attribution it was asked for, and its anonymisation jobs
  (8913992, 8917988, 8917989) loaded the pipeline's embedding model
  directly. `tests/conftest.py` now redirects every model cache into a
  temporary directory for the session, and the stand-in refuses to write
  outside the test's `tmp_path` or through a link (NEW-INC-01, TESTS-01
  follow-up).
- `preflight --diarisation-required` passed jobs whose cached pipeline config
  was damaged, because with a token it never read the cache. It now fails
  them, naming the file and how to replace it or restore it from an intact
  copy, and an empty pipeline snapshot no longer counts as cached.
  `setup/cache_pyannote_arc.py` exits 3 instead of reporting success over a
  damaged config, since a download keeps a file the cache already holds
  (NEW-INC-01, CORE-R3). Since 463340a the check also covers every file
  in the pipeline's blobs directory whose name is a digest, linked or not,
  and reports one whose git blob id or, for a large-file blob, SHA-256
  differs from its name. The pre-cache script exits 3 over such a blob as
  well. A damaged blob whose snapshot link had been deleted used to pass,
  and the next download would have linked it again (NEW-INC-01,
  follow-up).
- When an offline diarisation load missed the cache, the error named
  `<HF_HOME>/models--pyannote--speaker-diarization-3.1`, which pyannote.audio
  3.x never reads. It now names the pipeline's directory in pyannote's own
  cache (`$PYANNOTE_CACHE`, or `~/.cache/torch/pyannote`), and
  PYANNOTE_SETUP_GUIDE.md now says the same. A failed load is also recorded
  with the exception's type (`KeyError: 'name'`, not `'name'`) (CORE-R3,
  REV-01, DEPS-04).
- When the diarisation pipeline failed to load from a damaged cache,
  `transcription.py`'s error asked for a HuggingFace token and the model's
  terms, or, offline, for pyannote's cache to be populated, and neither
  repairs a damaged file. When `pyannote/speaker-diarization-3.1` fails to
  load from the Hub or from pyannote's cache, `transcription.py` now runs
  preflight's damage check. If that finds a damaged file in the
  pipeline's cache, the error names each damaged file, says that neither a
  token nor a new download repairs it and gives preflight's remedy. For
  any other checkpoint, when nothing is damaged and when the check itself
  fails, the message is as before, and a test runs the last of these cases
  through the load (NEW-INC-01, follow-up; 1bbae87, 142ed15).
- A provenance sidecar beside a committed table regenerated in place
  (`condition_ci`, `bootstrap_ci`) could record `git_dirty: true` for a run
  made from committed code. The git state was read after the table had been
  written, so the run's own output counted against it: whenever the new
  table differed from the committed one, on every regeneration after the
  first, and in `condition_ci`'s gains sidecar. The state is now read before
  anything is written, leaving out the files the run rewrites
  (`provenance.run_metadata(ignore=...)`, `write_sidecar(run_meta=...)`).
  `benchmark_anonymisation` now reads its summary's state the same way
  (OUTPUTS-12, follow-up). Nine more writers now do the same. Before
  ef7da7c, `sweep_aggregate`, `benchmark_timestamps` and `wer` read the
  state after writing their first output. Before 1119a5c,
  `benchmark_masking`, `benchmark_der`, `disfluency`,
  `audit_reconstruction`, `determinism_cross` and `benchmark_wer` read it
  before writing any tracked output but left nothing out, so a second
  regeneration in place recorded a dirty tree whenever the first had left
  an output different from its committed copy (4da9803 brings
  `benchmark_der`'s docstring into line). `evaluation.fleurs_diacritics`
  had the same fault, and since c597599 it reads the state once, before
  measuring, leaving out its `--out`. The keys recorded are unchanged,
  and no committed result changes. `fleurs_multilingual` is left as it
  was, because its `--out` is also its default `--carry-from` input.
- The anonymisation summary called the uncapped sample "in stream order",
  but each meeting is read in start-time order. That is why the
  single-meeting re-run drew a different 200 utterances from the August
  runs, jobs 8556951 and 8573363, with 36 in common (the two August runs
  drew the same 200). The summary's label, the docstrings and the help now
  say so. The committed single-meeting summary, written at `6f9bf56`, keeps
  the old label (EPRIV-03; 66f2f2f, 88679d2).
- `python -m evaluation.footprint --from-sacct` would have mispriced or
  dropped jobs in a current capture. Its node map lacked GPU nodes the
  re-run wave ran on (htc-g015, htc-g066), a typed allocation such as
  `gres/gpu:v100` was priced at the type's largest board whatever card the
  node holds, and the wave's job names were unknown to it. It now maps all
  57 GPU nodes of ARC's 2026-10-04 listing and recognises the wave's
  `au_<stage>` and `pf_<stage>` names. For 16 of the nodes it prices the
  board their job logs name, for htc-g041 to htc-g043 the board their node
  features give, and for the rest the family's largest board. When the
  dump records where a job ran, the job counts only if that was one of
  this project's directories or it is one of five documented to have run
  elsewhere. The documented query now starts on 2026-05-16, the day of the
  evaluation's first job (81d5119, da1a368, 4de52cf, 6ea323d). No
  committed number moved until the final capture, which Changed describes
  (OUTPUTS-05, ESTATS-13, ESTATS-05).
- `tests/test_s1_env_jobs.py` left `hpc/submit_anonymisation.sh` out of
  its job checks through an exclusion that had gone stale. It now checks
  that job's preflight gate, its stop when the preflight fails and that it
  installs nothing, as it does for every other job (SHELL-10; 1496c64).
- Two descriptions in the code were wrong. The notes of `pipeline_full` in
  `evaluation/conditions.py` said the WER benchmark decodes in float32,
  against float16 in `transcription.py` on a GPU. On a GPU the benchmark
  decodes in the checkpoint's own precision, which the re-run sweep's
  summaries record as float16 for Large v3 and distil-large-v3 and float32
  for Whisper Medium, so the two differ in precision only for Whisper
  Medium (NEW-04; 26cfcf3). The header of `hpc/submit_sweep.sh` put
  `default_sweep_conditions()` in `evaluation.sweep`, though
  `evaluation.conditions` defines it (EWER-13; 1b41be0).
- Documentation that the re-run wave had overtaken, or that gave wrong
  facts, was corrected (1265711). Between them, `docs/evaluation.md`,
  `docs/conditions_audit.md` and `docs/expansion_plan.md` describe the
  committed WER matrix as the audit's re-run, with 17 conditions, the
  language gate as the current Unicode strip and four FLEURS arms, and the
  August filler figures as superseded (6c4483b, e818965, 9d9cc55, 1b8ee00,
  1066633, d68bb9d). `setup/cache_pyannote_arc.py`'s docstring,
  `ARC_USAGE_GUIDE.md` and `docs/evaluation.md` say which revision each
  pyannote loader asks for, and `docs/evaluation.md` what
  `revisions_not_enforced` lists (f03f1df, 75e1a58, fc5649e). `README.md`
  says that the ledger's `gpu_type` column is the scheduler's label, not
  the card, and `TROUBLESHOOTING.md` gives the pipeline-failure messages
  of the current code (75f55d1). Job 7746222, behind
  `evaluation_clustering_0.60/`, ran on a Tesla P100, not an H100, and the
  clustering tests compare it with the default-threshold DER summary that
  815b5a7 committed from job 7742188 (a02b8dd, dedac2d). In the tests only
  docstrings and comments changed, and no pinned value moved (ESTATS-13,
  DEPS-04, EWER-03, EWER-05, EWER-13, T1-02, T1-05, ESTATS-01, ESTATS-08,
  NEW-INC-01; documentation only).
- The documentation follows the fixes above (fd7b0a7).
  `TROUBLESHOOTING.md` describes a damaged pipeline cache as preflight and
  each caller now report it, and gives exit 4, not 2, for the case study's
  failed preflight (NEW-INC-01; c948ab8, 5407ba5). `setup/README.md` says
  which pyannote loaders pin a revision and which read `main` (7aaae74).
  `hpc/README.md` gives the case study's choice of manifest, guards its
  example of sourcing a record with `|| exit 1` and says that the LF rule
  reaches only a new checkout (NEW-06, SHELL-08, G4; 2c1c911). It also
  names the five jobs whose preflight passes `--diarisation-required`, the
  anonymisation job among them, and adds `submit_determinism_cpu.sh` to
  the jobs that pass `--lock` (07a72f9, c509213).
  `output/evaluation/README.md` gives the case study's new manifest rule
  (NEW-06; 33caa3c), and the sweep stage of `.hpc-plan.yaml` again has a
  step that rebuilds the committed aggregate on ARC (SHELL-02; e7f7635).
- `output/case_study/ner_false_positive_test.md` counted all three of the
  dictionary masker's redactions on the case-study text as genuine
  personal names. Two of them are the first name and surname of the
  workflow's author, in the closing credits. The third, "Jordan", is in a
  speaker's example of a false positive, the word masked when the talk is
  of the country, so it names no one. The note's genuine-name column now
  reads 2 in each row. This is a hand count, and every redaction count (3,
  18 and 3) is unchanged. The case-study README, `README.md`, a comment in
  `transcription.py`, a test docstring and a dated note in
  `docs/expansion_plan.md` now agree (NEW-07; c3e45e4, 7b83945). The note
  also said that relaxing the capitalisation gate for both stages
  (`--ner --case-insensitive`) costs the false-positive rate it measured,
  but the arm it measured relaxed the gate for the NER stage alone. It now
  says that the relaxed configuration costs at least that arm's false
  positives, since it masks every word that arm masked (NEW-08; a27ac77).
- Four descriptions were wrong. The scorer's comment said that NFKC
  collapses smart quotes and accents. NFKC leaves the curly quotation
  marks as they are and keeps accents, and the replace after it maps the
  two curly single quotation marks to the apostrophe, U+2019 being also
  the typographic apostrophe (3670b89, cb06276). `evaluation/conditions.py`
  and `docs/conditions_audit.md` said that `punct_strip` can differ from
  `raw` only through typographic apostrophes. It runs before every step
  of the scoring normaliser that comes ahead of the normaliser's own
  punctuation strip, so it differs from `raw` on both curly single
  quotation marks, on characters NFKC folds into ones the normaliser
  keeps, on combining accents NFKC joins to their letter, and on a speaker
  tag such as SPEAKER-01, which the normaliser removes whole. In the
  committed matrix it differs from `raw` in the three FLEURS cells alone,
  each by two substitutions that become hits, all on one reference
  sentence that closes a quotation after "Hira" with U+2018. Tests now pin
  each case (a9a296b, fb22ece). `README.md` gave the NER stage's recall on
  names the dictionary has never seen as about a third, the August
  figure, where the regenerated summary gives 0.41, all of it on the
  capitalised half of those names (998b181). The header of
  `hpc/submit_determinism_cpu.sh` said that no CPU decode had been timed
  on ARC. It now gives job 8978759's time, 1 h 17 min on 16 cores
  (51e6071). No transform, artefact or number changes.

### Changed

- The WER matrix (`sweep_aggregate.csv`, `sweep_aggregate.json`; 2e36bf9) is
  the re-run sweep's. ARC jobs 8917985 (Whisper Large v3, on Tesla V100
  cards), 8917986 (Whisper Medium) and 8917987 (distil-large-v3), the last
  two on NVIDIA L40S cards, are aggregated by `evaluation.sweep_aggregate`,
  which now writes the committed files itself (EWER-02, OUTPUTS-04). The
  matrix has 255 cells (five corpora, three models, 17 conditions) with the
  pooled WER beside the macro (EWER-08), and its JSON names every input
  summary by SHA-256. All 15 raw cells equal the post-fix sweep's to the
  last digit, and ten conditions are unchanged in every cell. In percentage
  points against raw, the second pass moves five conditions and adds a
  sixth. `unicode_strip` (T1-02) had LibriSpeech deltas from -0.008 to
  +0.051 and now scores exactly as raw in every cell but Medium on
  test-clean (-0.002). `whisper_norm`, now with the published spelling map
  (EWER-05), moves 0.05 to 0.28 further below raw in every cell, most on
  FLEURS, and for Large v3 on test-clean it goes from -3.88 to -4.00.
  `repetition_fix` (T1-05) moves Medium on AMI from -261.98 to -262.05, and
  two VoxPopuli cells by at most 0.003. `filler_bracket` (EWER-03, T1-18)
  loses its +0.001 to +0.004 in three LibriSpeech cells. `pipeline_full`
  now scores exactly as raw in the six LibriSpeech and VoxPopuli cells of
  Large v3 and distil-large-v3. Five of them moved there, from -0.008 to
  +0.013, and Large v3 on VoxPopuli already scored so. For Medium it moves
  further below raw on test-clean (-1.99 to -2.03), test-other (-0.04 to
  -0.09), AMI (-261.98 to -262.05) and VoxPopuli (-9.7994 to -9.7997).
  `pronoun_i_fix` (EWER-13) is new and scores exactly as raw, since the
  scoring normaliser folds case (EWER-03). `whisper_norm` still scores
  11,653 of the 12,643 AMI utterances. `sweep_reports_postfix/` holds the 17
  Large v3 test-clean reports, and `hpc/runs/sweep.env` records the
  invocation.
- The paired intervals against raw on Large v3 test-clean
  (`condition_ci_postfix.csv`; 9cb43e3) are rebuilt over those reports, with
  10,000 replicates and seed 42 as before, and a sidecar names every input
  by SHA-256. `pipeline_full`, the composite of the clean-up stages, falls
  from +0.009 percentage points [+0.0013, +0.019] (p = 0.034) to 0.000
  [0.000, 0.000]. `unicode_strip` (+0.0054) and `filler_bracket` (+0.0035)
  also fall to 0.000, `whisper_norm` moves from -3.88 [-4.28, -3.49] to
  -4.00 [-4.41, -3.61], and `pronoun_i_fix` is new at 0.000. The other
  eleven rows are unchanged, and `dedup_window` and `filler_strip` still
  exclude zero.
- The headline WER pair, `wer_report.csv` and `wer_summary.json`, is now
  the re-run sweep's raw Large v3 test-clean cell (job 8917985, task 0),
  copied from the sweep (e3cb675). `wer_ci.csv` is rebuilt from it with a
  provenance sidecar (27cb15c), so the corpus table and the paired intervals
  rest on one decode (OUTPUTS-03, MS-12, EWER-11, REGEN-10). The May 2026
  pair it replaces stays in `output/evaluation/pilot_may2026/` (OUTPUTS-10).
  The two decodes score 5 of the 2,620 utterances differently: macro WER
  goes from 0.062210 to 0.062132, micro WER from 0.038630 to 0.038611
  (2,031 to 2,030 errors in 52,576 words), and the interval from [0.057521,
  0.067064] to [0.057458, 0.067001] at seed 42. They differ in the card, an
  NVIDIA L40S in May against a Tesla V100 in the sweep, and
  `hpc/legacy/README.md` sets out what else they share (c713055). The lower
  bound now prints as 0.057, but it sits at the 0.0575 rounding threshold.
  Over seeds 0 to 39, it prints 0.057 at 21 and 0.058 at 19, where the May
  decode's bound printed 0.058 at 38, so which of the two it prints depends
  on the seed.
- The FLEURS summary (`fleurs_multilingual_summary.json`) gains a fourth
  arm, the re-run at the audited code (job 8917984), and is assembled by
  `evaluation.fleurs_multilingual` from its 48 inputs, each named by
  SHA-256 (OUTPUTS-11; 0f6fc5b, 56ce519, 0f5b13e, 51e6d47). In the fourth
  arm, the composite's ratio to raw is exactly 1.0 in all six languages. In
  the third it was 0.9989 for Spanish, and the summary puts that down to the
  first Unicode repair deleting the vulgar fractions of one FLEURS sentence
  (T1-02). Raw WER now varies by up to 0.0003 across the four arms (0.0002
  across three). The summary records the GPU of every arm and language:
  where two arms ran a language on the same card, their raw WER is
  identical, and the fourth arm shares a card with no other (EWER-10). The
  diacritic shares are now measured over every reference word of each test
  split (job 8918340): Polish 88 to 35%, Spanish 60 to 11%, French 56 to
  16%, German 60 to 10%, Italian 50 to 5% and Dutch 0 to 1%. That moves the
  rank correlation the manuscript computes from 0.90 to 0.94, a change
  OUTPUTS-11 leaves to the author's sign-off. The values of the first three
  arms are unchanged, and the assembler reads the file names the job script
  has written since a22a864 (SHELL-13).
- The timestamp results (`timestamp_report.csv`, `timestamp_summary.json` and
  the new `timestamp_skipped.csv`, in `output/evaluation/` and
  `output/evaluation_vad_refine/`) are the re-run's jobs 8917980 (plain) and
  8917981 (`--vad-refine`), both on an NVIDIA H100 80GB HBM3 (567cfd9). They
  reproduce the first runs, jobs 7737896 and 7746221 on Tesla P100 cards, in
  all 499 rows and every column those wrote. ESTATS-02 moved nothing: the
  one untimed tail is the only chunk of its utterance, which the old code
  had already skipped, and it is now listed with its reason. The pinned
  Silero VAD (DEPS-06) reproduced the unpinned first run in every row
  (TESTS-10). The summaries now record the sample, the decode settings and
  card, the pinned revisions and the run (ESTATS-12). The median and 90th
  percentile of absolute end error are computed from unrounded errors,
  still 10 and 150 ms. The VAD summary gains the statistics its first run
  predated: a median of 10 ms, a 90th percentile of 90 ms, and 21 of 499
  ends more than 0.5 s early, against 41 of 499 without the VAD. Each report
  gains the hypothesis and its chunk count. An earlier run on an H100 PCIe,
  job 7746137, put one of the 499 starts 20 ms later, so the recipes
  `hpc/runs/timestamps.env` and `timestamps_vad.env` request the committed
  runs' card, and a test pins that start (d7b7df9, 4b8f115). Commit d7b7df9
  also corrects two statements of 567cfd9. The skipped clip's reference is
  the single word "yeah", which Whisper wrote as "ha" 222 times, and nothing
  shows it is a laugh. The card can move a boundary, as job 7746137 shows.
  The same commit put the H100 on htc-g055 that older records gave job
  7746221 (a P100 run, as 567cfd9 said) down to job 7746138. Commit
  a50ea7a withdrew that attribution: jobs 7746137, 7746138 and 7746139
  all ran on H100 PCIe cards on htc-g055 that afternoon, so the records
  cannot say whose card it was.
- The anonymisation benchmark is the re-run's (8b6144c). The committed
  curve, `anonymisation_summary.json` and `anonymisation_report.csv`, is now
  the multi-meeting configuration, job 8917989: 400 AMI test utterances,
  the first 25 usable ones of each of the 16 test meetings, from 14
  speakers, at alphas 0.5, 0.7, 0.8 and 0.9 (EPRIV-03). It replaces job
  8573363's single-meeting curve of 200 utterances (472ac19). Chance is now
  taken over each probe's candidates (EPRIV-04): 0.1411, where 0.25, one
  over the four speakers, was used before. Linkage is 0.1955, 0.5664, 0.787
  and 0.9173 at the four alphas, against 0.36, 0.655, 0.83 and 0.905 on the
  old sample. The summary adds linkage across meetings (0.1679 to 0.8947
  against a chance of 0.1101), across meetings on another headset channel
  (0.12 to 0.79 against 0.0374, over 100 probes) and within meetings, and
  the untransformed ceiling, 0.9524 (EPRIV-15). The padded overlap-add
  brings the level ratio to 0.9975 to 0.9995, from 0.976 to 0.986
  (EPRIV-02). The summary carries the guarded cost and its per-utterance
  loop screen (EPRIV-16, EPRIV-28): 0.6745, 0.4328, 0.1953 and 0.1498 on a
  screened baseline WER of 0.1765, with three looped baselines left out.
  The single-meeting configuration, job 8917988 (200 utterances of
  EN2002a), is kept in `output/evaluation/anonymisation_single_meeting/`.
  Both jobs loaded the diarisation pipeline's embedding model,
  `pyannote/wespeaker-voxceleb-resnet34-LM`, directly, because the damaged
  pyannote cache (NEW-INC-01) stopped the pipeline loading. Once the cache
  was restored, ARC job 8976304 found the pipeline's embedder and the
  directly loaded model to give identical embeddings on four random
  three-second inputs on CPU. `hpc/runs/anonymisation.env` and
  `anonymisation_single_meeting.env` record the two runs (SHELL-08).
- Filler preservation (`disfluency_summary.json`, `disfluency_report.csv`)
  is rescored locally from the AMI hypotheses of the re-run's Large v3 sweep
  (job 8917985), with recall against the transcriber's reference, the
  dump's `reference_raw` column (ESTATS-01, EWER-22), and a detector that
  no longer counts a standalone "huh" (ESTATS-08; a6dd82f, 9732ac0). The
  August pair came from a separate decode (job 8555165, on an H100 PCIe),
  whose hypothesis differs for 56 of the 12,643 utterances. Over the whole
  split, the composite keeps all 1,195 of the model's fillers (1,203
  before) and marks 1,191 of them, the other four being lengthened or
  repeated spellings outside the bracketing list (XREF-08). The model
  supplies 19.7% of the transcriber's 4,072 fillers, as it supplied 19.7%
  of 4,084 before. Under `whisper_norm`, retention is 0.6% (was 2.2%) and
  reference recall 0.0% (was 12.1%): all seven August recoveries were a
  standalone "huh", and recall now divides by the transcriber's 3,066
  fillers, where it used the 58 left in the normalised reference.
  `conditions` scores each condition over its own utterances and
  `conditions_shared_set` over the 11,653 all three hold. The summary
  records the dump's SHA-256 and the detector pattern, and
  `python -m evaluation.disfluency --conditions` scores a chosen set
  (d359c55).
- The DER results are the audit's re-run (70933b4). ARC jobs 8976354 to
  8976358 and 8976362 ran on 4 October 2026 at `9cb43e3` with a clean
  tree, on NVIDIA L40S cards. They replace the August runs 8534772,
  8534775, 8535638, 8534773, 8534758 and 8534792 (aaffb81, 3645869). Only
  the two meetings in which two speakers share a turn exactly moved
  (EDER-02): EN2002c's DER by 5e-6 on the test split, and IB4002's by at
  most 3.7e-4 in a sweep cell. No rate in any summary moved by more than
  4.4e-5. The concatenation run, now scored on the 16-bit signal
  (EDER-06), reproduced every figure. The summaries record
  `collar_convention` (EDER-01), `audio_signal`, the pinned revisions and
  the run (OUTPUTS-12, DEPS-04), and the sweep selections record their
  grid, argv and commit. The first sweep now scores the pipeline defaults
  first, six cells where it had five. Both sweeps still select threshold
  0.70, minimum cluster size 12 and no minimum pause, the configuration
  `der_tuned/` scored. `hpc/runs/der_*.env` describe the six runs and ask
  for their card (2776541). The DER docstrings, `docs/evaluation.md` and
  the HPC and evaluation READMEs name the re-runs, and
  `docs/advanced_usage.md` gives the oracle run's worst meeting as 45.7%,
  where it said 45.8% (4047ffa, 71b66fb).
- The worked case study (`output/case_study/`) is now ARC job 8983112
  (2026-10-04, code `c4c7b38` with a clean tree, an NVIDIA RTX A6000 on
  htc-g052), which ran after test job 8983111 had passed 2,058 tests from
  the same clone (ac08cdc). It replaces the August run, job 8441879. Its
  summary gains the coverage figures the August run's lacked (EPRIV-23,
  NEW-06): `speech_s` 1,841.08 s, the union of word intervals, beside
  `segment_span_s` 1,880.26 s (EPRIV-32), and `coverage_ratio` 0.95 and
  `segment_coverage_ratio` 0.9702 against the feed's 1,938 s. The review
  has 405 cues where the August run had 408, because a cue lying wholly
  inside the one before it is now merged into it, where the August code
  collapsed it to zero length. It also has four high-speech-rate flags and
  a truncation check. The manifest names the published recording beside
  the WAV it transcribed (CORE-04). It lists nine artefacts and leaves the
  masking log outside (CORE-05), which the comment at `transcription.py`'s
  manifest step now also says (e9c90fc). `podcast_eval_report.csv` is
  committed beside the summary, the README is rewritten from these files
  (T3-06, OUTPUTS-08), and `hpc/runs/case_study.env` records the run. The
  job's header and closing hint now name the review and manifest among the
  files to commit (02f4068), and the HPC README no longer says that the
  job needs a manifest in `$DATA` (c787742). `ep05_raw_text.txt` and the
  NER note stay the August run's, because the note measured that text.
  The note and the case-study README now say so, as do the HPC and
  evaluation READMEs and the masking test (6525932, f2b11f7, 74c4102).
- The footprint ledger is now the final capture of 2026-10-04 (e3e436d).
  It holds the 197 cluster jobs of the evaluation from 2026-05-16 and
  prices each GPU job at its node's board, where the June capture held 38
  jobs and labelled each of its 36 GPU jobs `a100`. The estimate moves
  from 53.79 GPU-hours, 41.31 kWh and 8.55 kgCO2e to 155.70 GPU-hours,
  95.95 kWh and 19.86 kgCO2e. The ledger's provenance records the sacct
  query, the dump's SHA-256 and the seven jobs left out, all cancelled
  while pending (1cb7236). The dump itself is not committed, because it
  lists the shared account's other projects. The READMEs, the footprint
  module's docstring and the tests describe the new capture (e08103e,
  19bf267, 3ca26dc), and `tools/verify_regeneration.py` now passes, with
  the footprint pair identical byte for byte (OUTPUTS-05, MS-11,
  ESTATS-05, ESTATS-06, ESTATS-13, REGEN-07, SHELL-01, G5).
- `manuscript/manuscript.qmd` now reports the regenerated results. 02079b4
  made it render again with the re-run's artefacts and corrected the three
  statements that had stopped its claims check. The rest of its text was
  then revised for the re-run's results (0e90917, then 33a8e13 to
  e515421). Every figure in it is computed from a committed artefact, and
  checks in its setup stop the render when an artefact no longer bears a
  sentence out. It says which of its claims hold only as scored, with the
  quotation marks Whisper writes around dialogue counted as errors (see
  the open list above): the readers' twelvefold spread, the corpus order
  and most of the Whisper normaliser's LibriSpeech gain. It says that
  Large v3 and distil-large-v3 decode in half precision (NEW-04). It
  reports the diarisation results of the October re-runs, of which only
  the missed speech of the 0.70 cell moved at the printed precision (6.39%
  to 6.40%). It also reports the normaliser's AMI gain over the utterances
  both conditions score (6.8%, against the 12.1% the two corpus rates
  imply), the determinism check's five runs in four hardware
  configurations, two genuine names among the dictionary's three
  case-study redactions, and the footprint of the final ledger, about 156
  GPU-hours, 96 kWh and 19.9 kgCO2e. It follows APA 7 and the journal's
  page format. A table starts on a new page when less than 85% of a page
  is left, so that none breaks across pages (e515421), and the PDF draws
  its figures with `pdf()` where R has no cairo (3b17c16).
  `tests/test_bib_sentencecase.py`, which had read a macro of the PDF
  header as a missing citation since f59a0a0, passes again (f9a1013). At
  e515421 the HTML and the 88-page PDF render with no warning and no
  unresolved cross-reference, and the abstract has 250 words.
  `manuscript/README.md` lists every artefact the manuscript reads
  (31aaa39). The manuscript leaves to the author the Funding declaration
  and the citation of the release's version DOI (two PHASE2 notes).
- The masking benchmark is regenerated, all four arms, with seed 42
  (a08265c; T1-03, REGEN-09, OUTPUTS-15). It samples 1,940 cases, up from
  1,164. Its 97 draws, 68 from the curated list and 29 held out, each fill
  20 cells instead of 12, because two new positions put the name directly
  after an opening quote or bracket (EPRIV-10). The curated names under
  three characters are now masked and so join the pool the curated draws
  come from (T1-07). That changes 10 of the 68 curated draws at seed 42,
  but none of the names drawn is shorter than three characters. Held-out
  names are labelled `held_out` and no longer filed under a language
  (EPRIV-19). Recall is unchanged for the dictionary (0.3505) and
  case-insensitive (0.7010) arms, and rises with NER from 0.4562 to 0.4737
  (out of the dictionary 0.3534 to 0.4121) and with case-insensitive NER
  from 0.9072 to 0.9366 (0.6897 to 0.7879). Every summary records its run
  and the curated list's SHA-256, and the NER arms their model's
  provenance.
- The example variants in `example_output/variants/` are generated by
  running the pipeline itself, with the model calls replaced
  (`tools/generate_example_variants.py` calls `transcription.main`), so they
  show what `transcription.py` writes (XREF-03, CORE-19, CORE-20,
  OUTPUTS-13; f041d21). `01_plain` holds the transcript and its manifest,
  the other three add the JSON and captions, their redacted pair and the
  review report, and `03` and `04` also hold the speaker-attributed text. The
  artefact audit is re-run over them (b7fcdd6, 12275ed) and covers 39
  files, up from 25. The same two masked artefacts, the release 1.0.0
  transcript of `behind_the_curtains` as text and as `.docx`, still leak one
  surname (REGEN-08). `example_output/transcripts/README.md` labels those
  transcripts as release 1.0.0 output (OUTPUTS-06).
- The May 2026 pilot matrix, 12 files whose obsolete `postprocessed`
  condition could be taken for current cells, moved from
  `output/evaluation/` to `output/evaluation/pilot_may2026/`, which also
  keeps a copy of the May headline pair (7214e77, OUTPUTS-10).
- The pipeline, the benchmarks and `preflight` share one HuggingFace token
  lookup (`preflight.resolve_hf_token`) and one AMI decoder (CORE-13,
  EDER-15, XREF-04, XREF-07).
- `--exclude-common-english-words-from-name-masking` is a
  `BooleanOptionalAction`, so it can be switched off with `--no-...` (T3-12).
- `--languages-for-name-masking` accepts language names in any case, takes
  its choices from `data/curated_names.csv`, and rejects anything else.
- The enhanced WAV follows `--output-name` (T3-20).
- NER masking needs `python -m ner_masking --download` once before first use.
- `benchmark_anonymisation`'s command-line defaults are the single-meeting
  configuration: 200 utterances from the front of the split, alphas 0.5,
  0.7, 0.8, 0.9 (EPRIV-17). The committed curve also passes
  `--limit 400 --per-meeting 25`, and `hpc/submit_anonymisation.sh` sets
  either configuration from `ANON_PRESET`.
- `hpc/submit_der_sweep.sh` passes `OUTPUT_PREFIX` to the sweep, and a
  fine-tuning pilot writes to its own directory (EDER-11, EDER-14).
- `hpc/submit_determinism.sh` refuses to overwrite an earlier run's results
  unless `OVERWRITE=1`, as the multilingual WER script already did
  (SHELL-R6).
- `pytest.ini` moved to the repository root, where pytest reads it (TESTS-16).
- `requirements.txt` drops 17 unused packages and the duplicate numpy, moves
  development tools to `requirements-dev.txt`, and caps pyannote.audio below
  4 (DEPS-11, CORE-17). `setup.py` installs the top-level modules
  (`py_modules`), so the `transcribe` entry point works from a wheel.

### Added

- `requirements-lock.txt`: a `pip freeze` of the ARC job environment, taken
  on 2026-09-26 after sourcing `activate_project_env_arc.sh` as the jobs do
  (DEPS-01): torch 2.5.1+cu121, transformers 4.57.1, pyannote.audio 3.4.0.
  A first version was taken without the activation script and recorded the
  account's `~/.local` packages (torch 2.8.0+cpu, transformers 4.56.2), which
  shadow the environment outside a job (DEPS-02); it was replaced.
- `tools/verify_regeneration.py`: the rebuild-and-compare gate described
  above.
- `hpc/common/arc_common.sh`: result jobs record `pip list`, `nvidia-smi`,
  the torch and CUDA builds, the git commit and any modified tracked code
  under `<report dir>/environment/` (DEPS-03, part). Every evaluation job
  script calls it. The two WER scripts that do not, `submit_benchmark_wer.sh`
  and `submit_benchmark_wer_gpu.sh`, are retired to `hpc/legacy/`, where
  they refuse to run and are kept as the record of how the May 2026
  headline pair was made. The transcription worker `batch_transcription.sh`
  uses the helper to activate the environment and run the preflight, but
  writes no record.
- `hpc/runs/*.env`: the parameters and job ids behind the committed results
  of the WER sweep (`sweep.env`), the timestamp runs (`timestamps.env`,
  `timestamps_vad.env`), both anonymisation configurations
  (`anonymisation.env`, `anonymisation_single_meeting.env`), the
  determinism check (`determinism.env`) and the DER runs, recovered from
  the ARC logs and environment records (SHELL-08). The six DER records
  now describe the October re-runs and ask for the L40S cards they ran on
  (2776541). `fleurs_ml.env` records the FLEURS summary's fourth arm,
  array job 8917984, with the card each of its six tasks ran on, and asks
  for those card types (4ba44b9). It says that a reproduction meant to
  match exactly runs from a checkout of `6f9bf56`, with the record copied
  in, because `evaluation/benchmark_wer.py` has changed since. Commits
  e3cb675, f0ac4e3 and faa0e29 changed it between `6f9bf56` and
  `f2578b8`, only f0ac4e3 in its code, and 1119a5c has since changed which
  files its dirty-tree check leaves out. `case_study.env` records the case
  study, job 8983112, and asks for the RTX A6000 type it ran on (ac08cdc).
  Two more records hold the invocations of the determinism check's CPU
  arm and V100 run (`determinism_cpu.env`, `determinism_v100.env`). Each
  record sends a reproduction to its own directory under
  `output/evaluation/repro/` on ARC, so it cannot overwrite the original,
  whose directory it notes. The case study's record does so for the
  evaluation alone: the job still writes the transcripts, the review and
  the run manifest into the clone's `output/transcripts/`, over those of
  any earlier run in that clone with the same `CASE_NAME`, as
  `case_study.env` says. Jobs 8978759 and 8978760 wrote into the
  directories their records named before they ran, and those records now
  give them as the originals and send a reproduction to
  `repro/determinism_cpu/` and `repro/determinism_v100/` (3cae28a,
  ba982b9). The commands of all sixteen records source the record with
  `|| exit 1`, because bash carries on past a `.` that cannot find its
  file, and without the guard a command would submit the script with its
  own defaults (a12d689, 95209a6). The aggregation step of `sweep.env` now
  sources the record too. Without it, `SWEEP_OUTPUT_DIR` was unset there,
  and `aggregate_sweep.sh` reads an empty `SWEEP_DIR` as the original's
  directory (95209a6). `.gitattributes` checks the records out with LF
  endings in every new checkout, since a copy with CRLF endings sourced on
  ARC sets every value with a trailing carriage return (G4; 4ba44b9). The
  first three FLEURS arms have no record, but the FLEURS summary names
  each arm's jobs, code commit and GPUs.
- Tests: 1,706 test functions at `fb22ece`, against 1,698 at `913ad58`,
  1,663 at `fd7b0a7`, 1,616 at `f2578b8` and 705 at `10981d4`
  (parametrised cases counted once). Among them are regression tests for
  the fixes above, shell tests that run the SLURM wrappers under bash with
  stubbed `sbatch`, and tests that tie each regenerated result to its
  source and pin its figures. The suite's runs on ARC at `f2578b8` (job
  8978757) and at `c4c7b38` (job 8983111) gave 2,032 and 2,058 passed,
  each with 1 skipped (no raw sacct dump is committed) and 1 expected
  failure. Run on Windows with Python 3.13 at `fb22ece`, it gives 2,128
  passed, 41 skipped and 1 expected failure. One skip is the sacct dump's,
  and the others need what that machine lacks: jiwer, pyannote
  (pyannote.core, pyannote.metrics or pyannote.audio), the Whisper
  normaliser's spelling map, ffmpeg, symbolic links or POSIX file
  ownership.
- `evaluation.determinism_cross` and
  `output/evaluation/determinism/determinism_cross_accelerator.json`, with
  `determinism_cross_accelerator_runs.json` saying what each run was and how
  that is known: the determinism check's first 200 AMI test utterances
  compared across hardware configurations, each with its node, at first
  three cards (0b00a72, 3efc8c8, 7318639, 06d5a53), since 9084c63 a
  processor as well, and since c813fe5 a V100 run of the check itself, so
  that it holds five runs in four configurations (both below). The NVIDIA
  L40S run, job 8781724, whose summaries are committed in
  `determinism/l40s_8781724/`, repeats itself on all 200 utterances, under
  one seed and across seeds, as the H100 NVL run of August did. Its
  transcripts match the sweep's Tesla V100 decode (8917985, task 1) on 198
  of the 200. The H100 run's hypotheses were not kept, so it enters
  through the per-utterance WER its log printed, which differs from each
  of the others on one utterance, a lower bound on the transcripts that
  differ. Pooled WER over the 200 is 0.419869 (L40S), 0.421743 (H100) and
  0.42268 (V100), and the two runs added later also give 0.42268, so the
  span is unchanged. The runs also differ in seed, code commit and node,
  so the comparison does not isolate the card. The V100 run of the check
  parts the card from the seed, but not from the node or the code. Inputs
  are named by SHA-256, and no transcript text is committed. This is the
  comparison of job 8781724 with the August run that `ISSUES.md` asked for
  before either is cited. No committed number moves.
- A CPU arm for the determinism check. `benchmark_wer` takes `--device` and
  `--dtype` and decodes in float32 on a processor, while a GPU run given
  neither makes the call it made before (f0ac4e3).
  `hpc/submit_determinism_cpu.sh` runs the GPU job's decodes on a processor,
  with CUDA hidden and thread counts pinned, and
  `hpc/runs/determinism_cpu.env` records its invocation (bc0702a, fee374a).
  ARC job 8978759 ran it on 2026-10-04 at `f2578b8`, on an AMD EPYC 9634
  (htc-c074) in float32 with 16 threads, decoding the first 200 AMI test
  utterances with seed 0 twice and seed 1 once. Its summaries, `cpu.txt`
  and WER report are in `determinism/cpu_8978759/` (ddb37e6), and the
  comparison above adds it (9084c63), regenerated in 0d16e6c and 4ade07b
  after corrections to its runs record (0952098, f09fc7a).
  `tests/test_determinism_results.py` pins the comparison, which no test
  read before. Within the run, the repeat and the second seed agree with
  the first decode on all 200 utterances. Its words equal the float16 V100
  sweep decode's on all 200 and the L40S run's on 198, the two that differ
  being those on which the L40S and the V100 differ, so its pooled WER
  over the 200 is the V100's, 0.42268 (451 errors in 1,067 reference
  words). The runs also differ in node, seed, code commit and process, so
  the comparison shows which configurations agree without isolating the
  processor, the card or the precision. The figures of the three GPU runs
  are unchanged. `hpc/runs/determinism_v100.env` records a V100 run of the
  check at seed 0, which separates the card from the seed in the
  comparison above, though the code commits still differ (9556c43). It ran
  as job 8978760 on 2026-10-04 (next entry).
- The determinism check's V100 run, ARC job 8978760 at `f2578b8`, ran on
  2026-10-04 on htc-g004, the node of the sweep's V100 pass. Its
  summaries, `gpu.txt` and WER report are in `determinism/v100_8978760/`
  (203d3ba), and it joins `determinism_cross_accelerator.json` as
  `v100_seed0` (c813fe5). `hpc/runs/determinism_v100.env` records it
  (ba982b9). It agreed with itself on all 200 utterances, repeated and
  across seeds. Its words match the sweep's V100 decode (seed 42, `6f9bf56`)
  and the CPU arm's on all 200, and its hypothesis files and WER reports
  are byte-identical to the CPU arm's. Under the L40S run's seed and in
  the same kind of job it still differs from the L40S on the same 2
  utterances, so that difference does not come from the seed or the
  process. The card is still not isolated from its node or from the code
  between `1bb68ba` and `6f9bf56`. No committed number moves.
- The run manifest and the timestamped JSON record the Hub snapshots the
  diarisation load used, read back from pyannote's cache without pinning
  the load: `diarization_settings.model_revision` and `sub_model_revisions`
  in the manifest, and `diarization_model_revision` and
  `diarization_sub_model_revisions` in the JSON `pipeline` block, for the
  pipeline and for the segmentation and embedding models its configuration
  names (DEPS-04, part). `example_output/variants/03_diarisation` and
  `04_diarisation_and_timestamps` were regenerated to show them.
- The anonymisation summary records why the speaker embeddings did not come
  from the diarisation pipeline (`embedding_pipeline_error`, null when they
  did) and why each fallback model tried before the one used failed
  (`embedding_fallback_errors`). The reasons used to go to stderr only, or
  nowhere (OUTPUTS-12, follow-up). The two fields date from 71560ae, so the
  committed summaries, written at `6f9bf56`, do not have them.
- `output/evaluation/reconstruction_audit_test.json` and
  `reconstruction_audit_validation.json`: the check the manuscript cites,
  that each reconstructed AMI meeting carries signal only where its
  annotation says. ARC job 8918334 ran it at code `6f9bf56` over the 16
  test and 18 validation meetings of the timeline caches the DER results
  read. Every meeting aligns best at a shift of 0 ms, and every frame
  outside the annotated speech is exactly zero (EDER-13; 9ecc8ed, 942d2c1).
- `output/evaluation/fleurs_diacritic_shares.json`: the share of reference
  words holding a letter outside ASCII in each FLEURS language, measured
  over each whole test split by `evaluation.fleurs_diacritics` (job
  8918340; 2fd96a9, 08d06a8). The FLEURS summary reads it in place of the
  shares it used to carry (OUTPUTS-11).
- `output/evaluation/normaliser_gain_ami.csv`, with a provenance sidecar
  (81d8054): the Whisper normaliser's (`whisper_norm`) gain on AMI for
  Whisper Large v3. It comes from `condition_ci --gains-output` over the
  re-run sweep's AMI `raw` and `whisper_norm` reports, now committed under
  the sweep's names in `output/evaluation/sweep_reports_postfix_ami/` (ARC
  job 8917985, task 1; 9507e0c). Over the 11,653 utterances both
  conditions score, the normaliser lowers the macro WER by 6.82%. The two
  corpus rates give 12.06%, because the 990 utterances whose references it
  empties average a raw WER of 0.539, against 0.306 for the rest
  (EWER-09). No other corpus loses an utterance to it, for any model.
  `tools/verify_regeneration.py` rebuilds this table too, and the
  docstrings of `evaluation.condition_ci` say that those reports need
  `--prefix wer_report_ami_whisper-large-v3` (3634788).

### Removed

- Dead scripts: `hpc/submit_batch.sh`, `hpc/submit_benchmark_wer_cpu_full.sh`,
  `hpc/setup_arc_structure.sh`, `hpc/verify_arc_upload.sh`,
  `hpc/activate_env_template.sh` (SHELL-20).
- The hidden `--single-file` option of `transcription.py`, the unused
  `force_english` variable, and the no-op line-wrapping helper (T3-14, T3-15,
  T2-10).
- The legacy `--report-postprocessed` and `--summary-postprocessed`
  options of `evaluation.benchmark_wer` (EWER-16; 66be1de). They added a
  `repetition_fix` run under a naming rule of their own, which once let
  its report overwrite the raw one, and nothing in the repository used
  them. `--conditions raw,repetition_fix` does the same job.
- The `sys.path` manipulation and duplicate `NameDataset` load behind the
  Facebook name database (T1-08).

## [1.0.0] - 2025-11-06

Initial release: Whisper large-v3 transcription with audio enhancement,
multilingual name masking, speaker attribution with
pyannote/speaker-diarization-3.1, text clean-up, TXT and DOCX output, and
SLURM job scripts. (From `versions.csv`.)
