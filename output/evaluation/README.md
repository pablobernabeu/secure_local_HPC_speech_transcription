# Evaluation results: which files are current

This directory holds the committed results the manuscript renders from.
Some are current, some are superseded runs kept as history, and the names
do not tell them apart: the unsuffixed `sweep_aggregate.*` is current,
while the unsuffixed `sweep_reports/` and `condition_ci.csv` are
superseded. This file is the record of which is which. Read it before
building anything on a file here.

Superseded runs are kept because a repair needs a before and an after
(53378ba): the manuscript reads the pre-repair files to show the defect
they carried, and `tests/test_benchmark_results.py` pins several
superseded values as regression anchors. A re-run of a current result
usually replaces its files in place, and git keeps the versions it
replaced (`git log -- <file>` lists them). The GPU runs came from Oxford
ARC. `hpc/runs/*.env` holds the exact invocation behind the results
whose script defaults do not reproduce them, and `hpc/README.md` maps
each job script to its outputs. `arc_job_ledger.csv` is the scheduler's
record of every job of the evaluation, captured for the footprint
estimate on 2026-10-04, after the last of them had finished. No job
before `hpc/common/arc_common.sh` recorded the code commit it ran, so the
"Committed in" column of each table gives the commit that last changed
the row's files, which is not always the code that produced them. Where
a run recorded its code commit, its row says so.

## Pending regeneration

The September 2026 audit changed code behind most of the current files
below. Its re-run wave has regenerated most of them, the GPU results on
ARC and the CPU ones locally. Until a file is regenerated it is the
latest committed run, not necessarily what the code at HEAD would
produce. The audit's commits name what they leave stale in a `Stale:`
paragraph of their messages, which `git log --grep='^Stale:'` finds, and
a file is current again once a later commit regenerates it. Later
commits named what three of those paragraphs missed, none of it a
result: c713055 for e3cb675, d7b7df9 for 567cfd9 and 06d5a53 for
3efc8c8. The case study in `output/case_study/` was stale too, until
ac08cdc replaced the August run's summary, review and manifest with
those of ARC job 8983112, run at c4c7b38, and added its report; job
9124852, run at fc652ab on 18 October 2026, has since replaced them.
`ep05_raw_text.txt` stays the August run's text on purpose, because
`ner_false_positive_test.md` measured the NER stage on it, as that
directory's README says. The job ledger and the footprint
(`arc_job_ledger.csv`, `footprint_report.csv` and
`footprint_summary.json`) were stale from da8f1ca and a1e7933 until
e3e436d rebuilt them from a capture of the scheduler ledger taken once
every job of the evaluation had finished. The next two paragraphs name
what is still stale, one group of files here and one outside this
directory, and what each waits on.

The two anonymisation summaries have been stale since 66f2f2f, which
names them for their `sampling` field. It describes the sample as the
code they ran at, 6f9bf56, worded it, and 66f2f2f corrected that
wording: the single-meeting summary's "in stream order" holds for the
order of the meetings only, since each meeting is read in start-time
order. No number depends on that field. The summaries wait on the next
anonymisation run, and none is queued.

Outside this directory, the four transcripts in
`example_output/transcripts/` are the output of release 1.0.0 in November
2025. 12275ed labelled them as such, and five of the audit's commits name
them as stale, 748ae6b the first. They wait on a GPU run that transcribes
Codex Mentis episodes one to four again (audit finding REGEN-08), which
has not been done.

The superseded files are not regenerated: they record the code that
carried a defect, and a re-run would erase what they show.

## Current results

| Files | What they hold | Produced by | Committed in |
| --- | --- | --- | --- |
| `sweep_aggregate.csv`, `.json` | WER matrix, 3 models x 5 corpora x 17 conditions at code 6f9bf56 (`pipeline_version` column), with pooled WER and the alignment counts; the JSON holds the SHA-256 of each of the 255 summaries | ARC sweeps 8917985 (Large v3), 8917986 (Whisper Medium) and 8917987 (distil-large-v3) (`hpc/runs/sweep.env`), aggregated locally by `evaluation.sweep_aggregate` at 7214e77 | 2e36bf9 |
| `sweep_reports_postfix/` | Per-utterance reports for all 17 conditions, Large v3 on LibriSpeech test-clean | ARC sweep 8917985, task 0, at 6f9bf56. Twelve of the seventeen are byte for byte the post-fix sweep's reports, so git last changed them in 53378ba | 53378ba, 2e36bf9 |
| `condition_ci_postfix.csv`, `condition_ci_postfix_provenance.json` | Paired bootstrap intervals over `sweep_reports_postfix/` (10,000 replicates, seed 42, recorded in the file); the sidecar holds the inputs' digests and the commit it ran at | `python -m evaluation.condition_ci --reports output/evaluation/sweep_reports_postfix ...`, locally | 9cb43e3 |
| `sweep_reports_postfix_ami/` | Per-utterance reports for `raw` and `whisper_norm`, Large v3 on the AMI test split, under the sweep's own names: 12,643 utterances and 11,653, the second without the 990 whose reference the normaliser empties. They are ARC's files with LF line endings where ARC's copies have CRLF, and their rows are the `per_file` entries of the two summaries whose SHA-256 `sweep_aggregate.json` records. AMI is the only corpus they are needed for: on the other four, `whisper_norm` scores every utterance `raw` does, so the gain the matrix gives there is already over one set of utterances | ARC sweep 8917985, task 1, at 6f9bf56 (`hpc/runs/sweep.env`) | 9507e0c |
| `normaliser_gain_ami.csv`, `normaliser_gain_ami_provenance.json` | The relative reduction in WER that `whisper_norm` gives over `raw`, Large v3 on AMI, over the 11,653 utterances both scored (macro 6.82%), beside the figure over each condition's own utterances (12.06%), which mixes the normaliser with the removal of the other 990 (audit finding EWER-09). The pooled columns divide by each condition's own reference words, which the normaliser also changes. The sidecar holds the inputs' digests and the commit it ran at | `python -m evaluation.condition_ci --reports output/evaluation/sweep_reports_postfix_ami --prefix wer_report_ami_whisper-large-v3 --primary-condition raw --bootstrap 10000 --seed 42 --output <scratch>/condition_ci_ami.csv --gains-output output/evaluation/normaliser_gain_ami.csv`, locally at 9507e0c. The paired intervals that `--output` requires are not kept, and the replicate count and seed in the sidecar shape only them | 81d8054 |
| `wer_report.csv`, `wer_summary.json` | Large v3, raw, on LibriSpeech test-clean: the headline table's input. They are the sweep's raw report and summary for that cell: the report is the same file as `sweep_reports_postfix/wer_report.csv`, and `sweep_aggregate.json` records the summary's SHA-256 | ARC sweep 8917985, task 0, at 6f9bf56 (`hpc/runs/sweep.env`) | e3cb675 |
| `wer_ci.csv`, `wer_ci_provenance.json` | Bootstrap interval for `wer_report.csv` (10,000 replicates, seed 42, recorded in the file); the sidecar holds the report's digest and the commit it ran at. The lower bound sits on the 0.0575 rounding threshold, so its third decimal depends on the seed | `python -m evaluation.bootstrap_ci --report output/evaluation/wer_report.csv --bootstrap 10000 --seed 42`, locally | 27cb15c |
| `speaker_cluster_sensitivity.json` | Exploratory whole-reader bootstrap of raw LibriSpeech test-clean macro WER and the pre-repair contraction and composite costs: 2,620 utterances from 40 readers, 10,000 replicates, seed 42. It preserves the original utterance intervals and records the inputs' SHA-256 with CSV line endings normalised to LF | `python -m evaluation.speaker_cluster_ci`, locally from the committed raw and pre-repair reports; full command below | 309f1d0 |
| `scorer_sensitivity.csv`, `.json` | Exploratory comparison of the declared scorer with symmetric removal of token-edge apostrophes, on the retained raw and `whisper_norm` strings in all 15 suite/model pairs. It verifies the original metrics, preserves internal contractions, reports both macro and pooled rates and pairs gains over common utterances. Edge elisions and terminal possessive marks also change; no gold scorer or sampling interval is claimed | `python -m evaluation.scorer_sensitivity`, locally from hash-verified ARC summaries and hypothesis dumps; reproduction below requires the separate input bundle | 1f9f22e |
| `fleurs_multilingual_summary.json` | Six non-English FLEURS languages in four arms (before the repairs, after the Unicode repair, with the language gate, and the re-run at the audited code 6f9bf56), with each arm's code, jobs and GPUs, the unrounded rates and ratios, and each language's diacritic share measured over its whole test split | ARC jobs 8166513/8166514, 8174224/8174225, 8245204/8245205 and 8917984 (`audit2026/fleurs_ml/`), assembled from their 48 summaries by `python -m evaluation.fleurs_multilingual` at 0f5b13e with `--diacritics output/evaluation/fleurs_diacritic_shares.json --exact --record-inputs`. The prose `finding` block is carried, not computed, and a rebuild that carries it over from this file reproduces the file apart from `benchmark.assembled_by`. The three-arm version it replaced is in git at 6f8d3f6 | 51e6d47 |
| `fleurs_diacritic_shares.json` | Share of reference words holding a letter outside ASCII, per FLEURS language, over each whole test split (google/fleurs at 70bb2e8); read into `fleurs_multilingual_summary.json` | ARC job 8918340 at 2fd96a9, `python -m evaluation.fleurs_diacritics` | 08d06a8 |
| `der_summary.json`, `der_report.csv` | Diarisation error on the AMI test split, timeline protocol, shipped settings | ARC job 8976354 at 9cb43e3 on an NVIDIA L40S (`hpc/runs/der_default.env`) | 70933b4 |
| `der_oracle/` | The same with the true speaker count given | ARC job 8976355 at 9cb43e3 on an NVIDIA L40S (`hpc/runs/der_oracle.env`) | 70933b4 |
| `der_tuned/` | The development-selected configuration (threshold 0.70, no minimum pause) scored once on test | ARC job 8976356 at 9cb43e3 on an NVIDIA L40S (`hpc/runs/der_tuned.env`) | 70933b4 |
| `der_concat/` | The shipped settings under the old concatenation protocol, kept as the comparison that shows the protocol, not the code, moved the figure | ARC job 8976357 at 9cb43e3 on an NVIDIA L40S (`hpc/runs/der_concat.env`). Its report is byte for byte the August run's, so git last changed it in aaffb81 | 70933b4, aaffb81 |
| `der_sweep.csv`, `der_sweep_summary.csv`, `der_sweep_selection.json` | First stage of the development-split sweep: the pipeline-default cell and five clustering thresholds | ARC job 8976358 at 9cb43e3 on an NVIDIA L40S (`hpc/runs/der_sweep.env`) | 70933b4 |
| `der_sweep2.csv`, `der_sweep2_summary.csv`, `der_sweep2_selection.json` | Second stage: the pipeline-default cell and a 3 x 3 grid of threshold and minimum pause | ARC job 8976362 at 9cb43e3 on an NVIDIA L40S (`hpc/runs/der_sweep2.env`) | 70933b4 |
| `timestamp_report.csv`, `timestamp_summary.json`, `timestamp_skipped.csv` | Segment-boundary error on the first 500 rows of the AMI test split (all EN2002a), 499 scored. The report holds each hypothesis, and the skipped file names the one utterance not scored and why (an untimed tail) | ARC job 8917980 at 6f9bf56 on an H100 80GB HBM3 (`hpc/runs/timestamps.env`). It reproduces the first run, job 7737896 on a Tesla P100 (committed in 95413ea, its summary recomputed in ec91a66), in every row and in every column that run wrote. The ARC copies in `output/evaluation/` are not that run's but job 7746137's, an H100 PCIe run that put one start 20 ms later | 567cfd9 |
| `../evaluation_vad_refine/` | The timestamp benchmark with its benchmark-only `--vad-refine` option, which extends segment ends with Silero VAD (tag v6.2.1). The pipeline does not ship it and the manuscript does not report it. It moves 52 of the 499 ends later and changes no word, so its error rates describe ends, not truncated transcripts | ARC job 8917981 at 6f9bf56 on an H100 80GB HBM3 (`hpc/runs/timestamps_vad.env`). It reproduces the first committed run (4bbed5f) in every row and in every column that run wrote: job 7746221, at code bb32915 on a Tesla P100 PCIe card (htc-g033), which had written over the files of an earlier attempt on an H100 PCIe, job 7746138 | 567cfd9, d7b7df9 |
| `disfluency_report.csv`, `disfluency_summary.json` | Filler preservation on the AMI test split, Large v3, under `raw`, `pipeline_full` and `whisper_norm`: retention, marked fillers and reference recall, recall always against the transcriber's reference. `conditions` scores each condition over its own utterances (12,643; 11,653 for `whisper_norm`, which drops the 990 filler-only references), `conditions_shared_set` over the 11,653 all three hold | The AMI hypothesis dump of ARC sweep 8917985 (task 1, Large v3, code 6f9bf56; its SHA-256 in `source_sha256`), scored locally by `python -m evaluation.disfluency ... --conditions raw,pipeline_full,whisper_norm` at e7dadbd, as the module docstring gives it | 9732ac0 |
| `determinism/determinism_repeat.json`, `determinism_seeds.json`, `gpu.txt` | Run-to-run and cross-seed agreement on the first 200 AMI test utterances on an NVIDIA H100 NVL: 200 of 200 identical | ARC job 8554985 (`hpc/runs/determinism.env`), code 754594d by the ARC clone's reflog | aeaecf5 |
| `determinism/l40s_8781724/` | The same check repeated on an NVIDIA L40S: 200 of 200 identical under a repeated seed and across seeds, the four hypothesis files byte-identical; `wer_seed0_run1.csv` is the run's per-utterance WER report, stored with LF line endings where ARC's copy has CRLF | ARC job 8781724 (`hpc/runs/determinism.env`), code 1bb68ba by the ARC clone's reflog | 3efc8c8 |
| `determinism/cpu_8978759/` | The same check on a processor without a GPU, an AMD EPYC 9634 (`cpu.txt`), in float32 with 16 threads: 200 of 200 identical under a repeated seed and across seeds, the three hypothesis files byte-identical; `wer_seed0_run1.csv` is the run's per-utterance WER report, stored with LF line endings where ARC's copy has CRLF | ARC job 8978759 (`hpc/runs/determinism_cpu.env`), code f2578b8 as its WER summaries and environment record, which stay on ARC, give it | ddb37e6 |
| `determinism/v100_8978760/` | The same check on a Tesla V100-PCIE-32GB (`gpu.txt`) under seed 0, on htc-g004, the node of the sweep's V100 pass: 200 of 200 identical under a repeated seed and across seeds, the three hypothesis files byte-identical, and they and the WER reports byte-identical to the CPU run's; `wer_seed0_run1.csv` is the run's per-utterance WER report, stored with LF line endings where ARC's copy has CRLF | ARC job 8978760 (`hpc/runs/determinism_v100.env`), code f2578b8 as its WER summaries and environment record, which stay on ARC, give it | 203d3ba |
| `determinism/determinism_cross_accelerator.json`, `determinism_cross_accelerator_runs.json` | The same 200 utterances decoded by five runs in four hardware configurations, three cards with their nodes and a processor without a GPU, which decoded in float32 where the cards used float16. The sweep's V100 pass and the check's own V100 run, under seed 0, share a node. Word for word, the two V100 runs and the CPU run agree on all 200 utterances, and each differs from the L40S on the same 2, the V100 run under seed 0 included, which shares the L40S run's seed and process; the H100 enters through its logged per-utterance WER (it differs from each of the others on 1 of 200, a lower bound); each run's second decode where one exists (200 of 200 for the CPU, the L40S and the V100 run under seed 0; 10 of 10 for the sweep's V100 pass, on the first 10 only); each run's WER on the subset. The second file says what each run was and how that is known | `python -m evaluation.determinism_cross`, locally at 203d3ba, from ARC jobs 8554985, 8781724, 8917985 task 1 (Slurm job 8923478) and its preflight 8913987 task 1 (Slurm job 8922107), 8978759 and 8978760; inputs named by the SHA-256 of their bytes and with CRLF read as LF | 203d3ba, c813fe5 |
| `anonymisation_report.csv`, `anonymisation_summary.json` | Voice anonymisation, privacy against intelligibility: 400 AMI test utterances (the first 25 usable ones, in start-time order, of each of the 16 test meetings; 14 speakers) at alphas 0.5, 0.7, 0.8 and 0.9, with linkage and its chance level over four candidate sets (all, within-meeting, cross-meeting, cross-meeting on another headset channel), the untransformed ceiling, the guarded WER cost with its per-utterance loop screen, and the level checks | ARC job 8917989 at 6f9bf56, multi-meeting preset (`hpc/runs/anonymisation.env`). Its speaker embeddings came from `pyannote/wespeaker-voxceleb-resnet34-LM` loaded directly, after a test had overwritten the cached pyannote pipeline configuration on ARC, and ARC job 8976304 found that route bit-identical to the diarisation pipeline's own | 8b6144c |
| `anonymisation_single_meeting/` | The single-meeting configuration at the same code: 200 utterances of EN2002a (four speakers) at the same alphas, with the same fields. It repeats the configuration of the August runs (jobs 8556951 and 8573363, which drew the same 200 utterances) on a different sample with 36 utterances in common, because each meeting is now read in start-time order; its `sampling` field still says stream order | ARC job 8917988 at 6f9bf56, single-meeting preset (`hpc/runs/anonymisation_single_meeting.env`); embeddings as in the row above | 8b6144c |
| `masking_report*.csv`, `masking_summary*.json` | Name-masking benchmark: dictionary, case-insensitive, NER and NER case-insensitive arms | `python -m evaluation.benchmark_masking` (seed 42), locally; each summary records the commit it ran at, and all but the dictionary arm's record a modified working tree. A rebuild with the code of f2578b8 reproduces every report byte for byte and every summary apart from `run_metadata` | a08265c |
| `arc_job_ledger.csv`, `arc_job_ledger_provenance.json`, `footprint_report.csv`, `footprint_summary.json` | The ARC job ledger, the 197 jobs of the evaluation from 2026-05-16 to 2026-10-04 with the board of the node each GPU job ran on, and the compute footprint estimated from it. The provenance holds the sacct query, the dump's SHA-256 and the jobs of the project left out, each under its reason | The ledger by `python -m evaluation.footprint --from-sacct` from a read-only sacct dump of 2026-10-04, 13:45 BST, which is not committed because it lists the shared account's other projects (`hpc/README.md`); the estimate by `python -m evaluation.footprint`; both locally | e3e436d |
| `reconstruction_audit_test.json`, `reconstruction_audit_validation.json` | Check that each reconstructed AMI meeting (the full-length timeline caches the DER results were scored from) carries signal where its annotation says and none elsewhere: per-meeting speech coverage, silence purity, exact-zero share of silence and best alignment shift. Every meeting of both splits has a best shift of 0 ms, silence purity 1.0 and exact-zero share 1.0 | `python -m evaluation.audit_reconstruction` on `$DATA/ami_cache/<split>_timeline_full`, read-only, ARC job 8918334 at 6f9bf56 (audit finding EDER-13) | 942d2c1 |
| `artefact_audit.csv`, `.json` | Residual-name audit of `example_output/` | `python -m evaluation.audit_artefacts --dir example_output`, locally | 12275ed |

The matrix, the reports and the paired intervals replaced in place those
of the post-fix sweep (ARC jobs 8688725, 8708134 and 8708135, 16
conditions), which are in git at aa6e61d. That sweep's own outputs are
on ARC in `postfix/`. The new sweep reproduces its raw cells exactly,
all fifteen, and the raw test-clean report byte for byte. Only the stages
the September 2026 audit changed moved: `unicode_strip` (T1-02),
`whisper_norm` (EWER-05), `filler_bracket` (EWER-03), `repetition_fix`
(T1-05) and `pipeline_full`, which composes them. `repetition_fix` moved
on three cells: Whisper Medium on AMI, and distil-large-v3 and Whisper
Medium on VoxPopuli, these two by less than 0.00003 in macro WER.
`pronoun_i_fix` (EWER-13) is new and scores as raw, since the normaliser
folds case.

`wer_report.csv` and `wer_summary.json` held the May 2026 decode until
audit finding OUTPUTS-03 replaced them with the sweep's raw Large v3
test-clean cell, so the corpus table and the paired intervals now rest
on one decode. `pilot_may2026/` keeps the May pair, which cefaac0
committed at the top level and 7214e77 copied there, and its interval is
in git at 642e4dd. The two decodes read the same model and dataset
revisions with the same torch and transformers and differ in the card,
an L40S in May and a V100 in the sweep (`hpc/legacy/README.md`). They
give five utterances different hypotheses, which moved the macro WER
from 0.062210 to 0.062132, the micro WER from 0.038630 to 0.038611 and
the interval from [0.057521, 0.067064] to [0.057458, 0.067001]. The
printed lower bound moves from 0.058 to 0.057 at seed 42, but the data
move it by only about 0.000076 and leave it on the rounding threshold
(0.057500 pooled over 2,000,000 replicates, `tests/test_headline_wer.py`),
so its third decimal is set by the seed and the change is not a
substantive one.

The anonymisation files replaced in place those of job 8573363
(2026-08-22), which are in git at 472ac19 and on ARC in
`output/evaluation/` itself. Job 8556951, the first committed result
(0c4055d, 2026-08-12), had the same configuration and drew the same 200
utterances. Both predate the fixes to the overlap-add (EPRIV-02), the
chance level (EPRIV-04), the candidate sets (EPRIV-15) and the loop
screen (EPRIV-16), and both read EN2002a in the order the dataset
streams it, so the single-meeting re-run is a different sample of the
same meeting. On the 36 utterances the two samples share, the original
arm scores identically and the embeddings barely move, so the change in
the baseline comes from the sample, and so, very largely, does the
change in linkage. The warped word error rate and the cost also move
with the transform, because decoder loops appear and disappear with it
(`hpc/runs/anonymisation_single_meeting.env`). The multi-meeting output
of job 8781723 on ARC (`anon_multimeeting/`) broke the per-meeting cap
(EPRIV-03) and was never committed.

The filler-preservation pair replaced in place the August 2026 pair (ARC
job 8555165, a separate decode on an H100 PCIe, scored before the fixes
for audit findings ESTATS-01 and ESTATS-08). That pair is in git at
a923427, and on ARC in the evaluation directory beside its dump,
`wer_hypotheses_ami.csv`. Of the 12,643 raw hypotheses, 56 differ
between the two decodes, and one of them moves a figure.

The diarisation files replaced in place those of the August 2026 runs
(ARC jobs 8534772, 8534775, 8535638, 8534773, 8534758 and 8534792, code
not recorded), which are in git at aaffb81 and 3645869. Those ran on L40S
nodes too. The re-run moved two meetings only, the two in which two
speakers share a turn exactly, whose reference kept one of them until
2bb4224 (audit finding EDER-02): EN2002c on the test split, by 5e-6 in
DER, and IB4002 on the validation split, by at most 3.7e-4 in a sweep
cell. No rate in any summary moved by more than 4.4e-5, and the
concatenation run reproduced every figure. The first sweep now opens with the
pipeline-default cell, which the August job predated, so it has six
cells where it had five, and both sweeps still select the configuration
`der_tuned/` scores.

`der_concat/` uses the superseded protocol on purpose and stays current
as a comparison.

`tools/verify_regeneration.py` rebuilds the files above that are derived
from other committed files or from a seeded synthetic benchmark (the
footprint, `condition_ci_postfix.csv`, `normaliser_gain_ami.csv`,
`wer_ci.csv`, `speaker_cluster_sensitivity.json`, the artefact audit and
the dictionary arm of the masking
benchmark) into a temporary directory and compares them with these
copies. It rebuilds the historical `condition_ci.csv` too, from
`sweep_reports/`.

### Reader-cluster sensitivity

`speaker_cluster_sensitivity.json` examines how the intervals change when
all utterances from a sampled reader stay together. Each replicate pools
per-utterance WER sums and utterance counts across the sampled readers,
retaining the corpus macro estimand. The paired comparisons retain the
same utterance differences on both sides. The raw interval is 5.08% to
7.36%, compared with 5.75% to 6.70% under utterance resampling; the
historical composite and contraction costs remain positive. This is an
exploratory sensitivity within the observed reader sample. It measures
neither uncertainty from corpus selection or reference errors nor
coverage for a wider speaker population.

From the repository root, regenerate it to a separate path for comparison:

```bash
python -m evaluation.speaker_cluster_ci \
    --report output/evaluation/wer_report.csv \
    --baseline output/evaluation/sweep_reports/wer_report.csv \
    --condition output/evaluation/sweep_reports/wer_report_contraction_fix.csv \
                output/evaluation/sweep_reports/wer_report_pipeline_full.csv \
    --bootstrap 10000 --seed 42 \
    --output my_check/speaker_cluster_sensitivity.json
```

The original intervals and report files remain the inputs to their
existing manuscript tables.

### Apostrophe-scoring sensitivity

`scorer_sensitivity.csv` and `.json` compare the declared scorer with an
exploratory rule that replaces with a space every apostrophe not standing
between two Unicode word characters, symmetrically on the reference and hypothesis after the
existing scoring normalisation. It preserves internal contractions and
also removes edge elisions and terminal possessive marks. It therefore
measures dependence on a scoring convention; it does not establish a
gold reference or correct the model's recognition.

The analysis first reproduces every original raw and `whisper_norm`
per-utterance metric and aggregate from the retained transformed strings.
It reports gains on common scored utterances and on a fixed sample shared
by both scoring rules, with each condition's own reference-word denominator
for pooled WER. Historical exclusions and any newly empty references are
reported separately. No sampling confidence interval is estimated.

The 270-file checksum receipt is committed as `sweep_input_manifest.json`.
It records the exact recovered ARC file digests, source decoder commit,
jobs and corpus notices, without copying private deployment locators.
The corresponding summaries and corpus text dumps remain under ignored
`build/recovered_arc_sweep/inputs` pending a reviewed public deposit.
The recipe below therefore needs that external bundle; the eleven-file
CPU gate cannot regenerate this report from the checkout alone.

```bash
python -m evaluation.scorer_sensitivity \
    --inputs build/recovered_arc_sweep/inputs \
    --aggregate output/evaluation/sweep_aggregate.json \
    --input-manifest output/evaluation/sweep_input_manifest.json \
    --output-csv my_check/scorer_sensitivity.csv \
    --output-json my_check/scorer_sensitivity.json
```

Use separate output paths and compare the scientific records. The JSON
records exact digests of the ARC files and explicitly normalises text line
endings to LF for the committed aggregate, checksum receipt and code.
Invocation paths and current run metadata change between environments.
The new scorer's tests run in the focused CPU workflow; the production
`evaluation/wer.py` and all canonical WER results remain intact.

### Recorded sweep decode and environment

`sweep_decode_provenance.json` extracts the recorded dataset/model revisions,
decode device and precision, GPU, CUDA/cuDNN and package versions from all
255 source summaries. Its fifteen suite/model profiles each agree across
all seventeen conditions. The receipt links every summary by exact digest
to the committed aggregate and public input inventory. It contains no
corpus text or private deployment locator and does not infer settings
missing from the original summaries. This is recorded historical metadata,
not a new model run or a direct inspection of the earlier runtime.

The deterministic extraction needs the recovered summaries:

```bash
python tools/extract_sweep_decode_provenance.py \
    --inputs build/recovered_arc_sweep/inputs \
    --aggregate output/evaluation/sweep_aggregate.json \
    --input-manifest output/evaluation/sweep_input_manifest.json \
    --output my_check/sweep_decode_provenance.json
```

Independent comparison checked every extracted field and type against
each source. Controls reject duplicate or incomplete cells, unreceipted
paths, hash drift, an unconfirmed or different decoder, and an environment
that changes between conditions. It is outside the eleven-artefact gate
because its original inputs await a separate deposit.

## Superseded, kept as history

| Files | What they hold | Produced by | Committed in | Superseded by |
| --- | --- | --- | --- | --- |
| `sweep_reports/` (7 files) | Per-utterance reports, Large v3 on LibriSpeech test-clean, from the pipeline that still carried the `contraction_fix` defect. The manuscript reads the raw and `contraction_fix` reports for the defect's signature | ARC sweep 7729882 (`docs/conditions_audit.md`) | 41659d7 | `sweep_reports_postfix/` |
| `condition_ci.csv` | Paired intervals over `sweep_reports/`. Its `whisper_norm` rows were scored with an empty spelling map (audit finding EWER-05), which the current normaliser no longer uses | `python -m evaluation.condition_ci --reports output/evaluation/sweep_reports ...`, locally; re-run with the replicate and seed columns in 642e4dd | 642e4dd | `condition_ci_postfix.csv` |
| `sweep_aggregate_prefix.csv`, `.json` | The WER matrix from the pipeline before the repair | ARC sweeps 7729882, 7995593 and 7995594, aggregated by job 7995595 on 2026-06-19 (the `generated` time in the JSON) | 53378ba | `sweep_aggregate.*` |
| `pilot_may2026/`: `wer_report_librispeech_{whisper-large-v3,whisper-medium,distil-large-v3}_{raw,postprocessed}.csv`, the matching `wer_summary_*.json`, and `wer_report_fleurs_whisper-medium_raw.csv` with its summary (14 files; the Large v3 raw pair is a copy of the top-level `wer_report.csv` and `wer_summary.json` as they stood before OUTPUTS-03 replaced them) | The May 2026 pilot matrix. "postprocessed" was the benchmark's name, at that commit, for the repetition repair alone (`detect_and_fix_repetitions`). The raw and postprocessed files are byte-identical for distil-large-v3 and for Large v3, because the repetition repair genuinely changed nothing for those two models on test-clean; the current sweep shows the same | The legacy GPU benchmark, most likely ARC array 7682561, whose task 0 decoded Large v3 on an L40S; the Large v3 raw report is identical, up to line endings, to the one job 7668730 wrote on 2026-05-17 (`hpc/legacy/README.md`) | 7214e77, which moved or copied them here from the top level, where cefaac0 had committed them | the sweep's `raw` and `repetition_fix` cells in `sweep_aggregate.*` |
| `../evaluation_clustering_0.60/` | Diarisation at clustering threshold 0.60 on the old concatenation protocol, which built each meeting from 25 utterances with no overlapping speech (973 s of reference) | ARC job 7746222 on a Tesla P100 PCIe card (htc-g034), code bb32915 | 4bbed5f, c6b4eaf | the timeline protocol (fde27c5) and the development sweeps above |

The manuscript reads none of the pilot files, so they were moved out of
the top level into `pilot_may2026/`, where their obsolete
`postprocessed` condition can no longer be mistaken for a current one
(audit finding OUTPUTS-10). `tests/test_headline_wer.py` pins the Large
v3 raw pair by its digests, as the May decode the headline pair
replaced.

The two directories outside `output/evaluation/` are kept apart because
their files have the names of current files here (`timestamp_*` and
`der_*`). `tests/test_benchmark_results.py` pins both (the
`TestVadRefine*` and `TestClustering060PinnedValues` classes).
