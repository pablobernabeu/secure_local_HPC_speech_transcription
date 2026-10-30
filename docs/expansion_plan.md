# Expansion plan (v2): toward a stronger, more secure, more reproducible submission

This plan records the development of the study across four tracks. Its
current purpose is to connect each methodological claim to the measurement,
source code and retained artefacts that support it. Earlier measurements
and schedules remain as history where labelled; the current status below
takes precedence over them.

## Current priorities, 6 October 2026

*Note of 30 October 2026.* The Spanish V100 control ran on 19 October
and reproduced the third arm's records ([next_control.md](next_control.md)).
The scheduler ledger was captured again on 30 October, with the six jobs
run since the capture of 4 October, and now gives 203 jobs, 157.0
GPU-hours, 96.7 kWh and 20.02 kgCO2e
(`output/evaluation/footprint_summary.json`). The footprint quoted below
is that of the earlier capture.

The completed ARC wave is integrated with the manuscript and the local
verification suite. Reader-cluster intervals and the separate exploratory
apostrophe-scoring analysis now qualify the original WER findings. All
255 sweep summaries and fifteen hypothesis dumps have been recovered,
with 270 exact input digests verified. The original numerical artefacts
remain intact. The local CPU suite and eleven-artefact regeneration gate
pass; the new hosted workflow awaits explicit approval to push its branch.

The next independent computational task is D2: assess repetition thresholds
from the retained raw hypotheses, using a separate report and the declared
scorer. This checks sensitivity without new recognition or selecting a
threshold on the test data. The proposed Spanish V100 control is prepared
in `docs/next_control.md`, but still requires approval under the HPC plan.
No new GPU job is queued. Further model or language expansion would add
less value at this stage than resolving these inferential and archival gaps.

Submission and release work proceeds in `docs/release_readiness.md`:
finish the authoritative reference audit and concrete archive review,
confirm funding and correspondence details, establish the dictionary's
sources and rights, settle licence scope and retained identifiers, then
reserve the new version DOI before freezing and depositing the final tree.
The recovered text archive has had a bounded content inventory; its
metadata-normalised local candidate preserves every input byte. Neither
that review nor public source availability establishes publication clearance.

Current masking results use 1,940 synthetic cases, not the older 1,164:
dictionary recall is 0.3505, dictionary plus NER 0.4737, case-insensitive
dictionary 0.7010 and case-insensitive dictionary plus NER 0.9366. All
four precision estimates are 1.0 on these injected carriers; that design
does not estimate natural-text precision. The voice-linkage results use
400 utterances from sixteen meetings and a fixed embedding model, with
candidate-weighted chance of 0.1411 in the all-originals comparison.
They do not establish anonymity against an adapted attacker or a privacy
gain for every usable coefficient. The current manuscript and committed
summaries take precedence over the historical B1/B3 figures below.

## Status snapshot (done)

- **WER condition sweep**: three models x seventeen post-processing
  conditions x five corpora (`output/evaluation/sweep_aggregate.*`, which
  had sixteen until the audit's re-run of the sweep added `pronoun_i_fix`);
  model x condition interaction is the headline finding.
- **Diarisation and timestamp benchmarks** on the AMI individual headset
  microphone (IHM) corpus. The diarisation benchmark was rebuilt: it had been scoring twenty-five-utterance
  concatenations, 973 s of audio with no overlapping speech, and now
  reconstructs whole meetings on their original timeline by summing the
  headset channels (`evaluation/ami_meetings.py`). Macro DER on the held-out
  test split is 16.6% against 28.8% under the old arrangement, tuning is
  chosen on the AMI *validation* split, and `evaluation/audit_reconstruction.py`
  verifies the rebuilt audio is not displaced relative to its reference.
- **Masking evaluated as PII detection** (`evaluation/benchmark_masking.py`):
  honest recall 0.35 / leakage 0.65, decomposed into the capitalisation gate
  and the closed dictionary; possessive-clitic fix and case-insensitive
  ablation shipped; residual-artefact audit (`audit_artefacts.py`).
- **Bootstrap CIs** (`bootstrap_ci.py`) and a **compute energy/carbon
  footprint** (`footprint.py`; 155.7 GPU-h, 96.0 kWh and 19.86 kgCO2e over
  the evaluation's 197 cluster jobs, from the ledger captured on 2026-10-04
  and checked against every job the repository names).
- **Reproducible real-world corpus** (`fetch_codex_mentis.py`): the nine
  *Codex Mentis* episodes resolve deterministically from the Apple-Podcasts
  id through the iTunes Lookup API to the RSS feed, download to a
  SHA-256 manifest, and are git-ignored so only the manifest travels with
  the repository. This is the substrate for Track A.

## Guiding principles

1. **Publishability first.** Every item must produce something a reviewer
   can check: a number with a confidence interval, a figure, a released
   artefact, or a reproducible script.
2. **Security as a contribution, not a slogan.** The paper claims a
   privacy advantage from local processing; each Track-B feature turns one
   facet of that claim into a measurable, defensible mechanism.
3. **Reproducibility end to end.** Inputs resolve from public identifiers,
   outputs carry provenance and checksums, and heavy artefacts are
   re-derivable rather than committed.
4. **Preserve ARC capacity.** Front-load CPU-only work; keep GPU waves
   small, pre-flighted, and concurrency-capped; chain aggregates with
   `afterany`.

---

## Track A --- Real-world corpus and evaluation (Codex Mentis)

The existing benchmarks are read speech (LibriSpeech, FLEURS), parliamentary
speech (VoxPopuli), and meetings (AMI). None is long-form, spontaneous-style
podcast audio, and the paper shows no end-to-end run on realistic input.
*Codex Mentis* fills that gap and is uniquely convenient: it is authored by
this project's author, with the retained text and metadata still requiring
the release decisions in `docs/privacy_review.md`. It is
generated by NotebookLM as a two-voice synthetic dialogue (so the
speaker count is known a priori), and episode five, "Beyond the cloud:
Reclaiming data sovereignty in speech transcription", is *about this very
workflow* --- a natural, self-referential worked example.

There is **no gold transcript**, so the evaluation is designed to be
rigorous *without* one, with a small optional gold subset for the metrics
that need a reference.

- **A1. Reference-free structural metrics (CPU/GPU-light).** From the
  pipeline's own outputs:
  - *Diarisation*: predicted speaker count against the known two; turn
    count and turn-length distribution; over- and under-segmentation rate.
    A wrong speaker count is an unambiguous, reference-free error.
  - *Timestamps*: monotonicity (no backward jumps), coverage of the audio
    duration, inter-segment gap and overlap statistics, and end-of-file
    drift. These catch the long-form failure modes (truncation, runaway
    repetition) that corpus WER hides.
  - *Masking*: the false-positive rate on natural technical prose ---
    how often domain terms ("Bayesian", "Whisper", "LPC") are wrongly
    redacted. This is the precision measurement the injection benchmark
    explicitly cannot give (its carriers contain no confusable tokens), so
    the two experiments are complementary.
  - *Stability*: agreement between Whisper Large v3 and Medium, and the
    effect of `pipeline_full` versus `raw` on real audio (does
    post-processing change much when the model is not collapsing?).
- **A2. Worked case study. DONE.** Run the full pipeline on
  episode five end to end --- transcribe, diarise, align timestamps, mask,
  export --- and present the artefacts and a short qualitative analysis.
  This is the paper's missing "here is the tool actually working" section.
  Run on ARC; the artefacts and the qualitative notes are in
  `output/case_study/`.
- **A3. Optional gold subset (manual, small).** Hand-correct a fixed
  window (for example five minutes) of two or three episodes to enable
  true WER, DER, and timestamp MAE on spontaneous-style audio. Flagged as
  optional because it is the only manual step; even a 15-minute gold set
  materially strengthens the claims.
- **A4. `evaluation/benchmark_podcast.py`. DONE.** A scorer
  that consumes transcription outputs and emits A1's metrics plus a JSON
  summary for the manuscript, mirroring the existing benchmark modules.
  Covered by `tests/test_benchmark_podcast.py`; the scores from the A2
  pass are in `output/case_study/podcast_eval_summary.json`.

---

## Track B --- Cutting-edge secure features

These are the substantive product additions. Each is deployable locally and,
where a model is needed, CPU-friendly, so none forces a GPU wave.

- **B1. Offline zero-shot NER fallback for masking. DONE.** `ner_masking.py`
  adds an optional second stage that recognises people from context rather
  than dictionary membership, wired into `create_enhanced_name_masker` as
  `ner_detector` and measured by `benchmark_masking --ner`. It is additive
  by construction (it proposes redactions, never withdraws one), off by
  default, fails clearly when explicitly requested but unavailable, and records a
  `source` per masking-log row so the two stages stay separable.

  Historical initial measurement, superseded by the 1,940-case re-run
  summarised above: with the capitalisation gate (seed 42, n=1164), overall
  recall 0.351 -> 0.456, **out-of-dictionary recall 0.000 -> 0.353** (the
  blind spot no larger list could address), title-case 0.701 -> 0.912,
  leakage 0.649 -> 0.544, precision 1.000.

  Relaxing the gate (`--ner --case-insensitive`, which relaxes it for both
  stages) reaches recall 0.907, out-of-dictionary 0.690 and lower-case
  0.902, leakage 0.093, precision still 1.000 on injected carriers.

  The gate exists because of a measurement, not a hunch. Without it the
  stage added, on the case-study transcript, **fifteen redactions, every
  one a false positive** (`researchers`, `we`, `speaker`, `one`, `user`
  ...) against three genuine names. A model asked for people returns person
  *references*, not personal *names*, and injected carriers cannot show
  this because they contain nothing confusable. Label engineering does not
  fix it: `person name`, `personal name` and `name of a person` all still
  yield "speaker one". Every false positive was lower-case and every real
  name capitalised, so the stage now respects the same gate the dictionary
  uses, `case_insensitive` relaxes both together, and under the gate the
  transcript gains **no** false redaction. Recorded in
  `output/case_study/ner_false_positive_test.md`.

  Corrected 2026-10-04: two genuine names, not three. The other of the
  dictionary's three redactions on that transcript is "Jordan", which a
  speaker gives as an example of a false positive, masking the word when
  the talk is of the country, so it names no one. The note's genuine-name
  column now reads 2 in each row, a hand count, and no redaction count
  changed.

  Running the real model also exposed a bug worth keeping in mind for any
  span-based NER: it returns the whole person span, so "Doctor Kowalczyk"
  yields `doctor` as a person token; titles are excluded, since they have
  their own `[TITLE]` branch.

  *Superseded plan text below, kept for the record.* GLiNER (Zaratiana et al., NAACL 2024) is
  a lightweight, CPU-optimised, zero-shot NER that recognises entity types
  from textual labels alone; the community `gliner-pii-edge` variant is
  trained for PII spans specifically. Wire it in as an *optional*
  second-stage matcher behind the dictionary, guarded like the existing
  optional imports, and re-run `benchmark_masking.py` to quantify the recall
  gain on out-of-dictionary names and the precision cost. This closes the
  loop the manuscript currently leaves open ("requires a named-entity model
  rather than a list, left for future work") and turns it into a measured
  result. Cost: one model dependency (~200 MB), documented and off by
  default; enlarges the offline footprint, which Track A's false-positive
  measurement then bounds.
- **B2. Timestamp-anchored audio redaction. DONE.** The pipeline
  already computes word-level timestamps *and* detects names. Combining the
  two yields something neither gives alone: an audio file in which the spoken
  names are silenced (or tone-bleeped) over exactly the time spans the masker
  flagged. This extends de-identification from the text to the recording ---
  the audit's most important gap, since the raw audio still utters every
  name. Pure signal processing (numpy plus the stdlib `wave` writer for PCM),
  unit-testable now against synthetic tones. Its fidelity is bounded by
  timestamp accuracy, which Track A already measures, so the feature and its
  evaluation are mutually reinforcing.

  Shipped as `audio_redaction.py`, a separate tool rather than a flag on
  the transcriber, so a recording can be redacted from an existing
  transcript without re-transcribing:
  `python -m audio_redaction --audio talk.wav --transcript talk.json
  --out talk_redacted.wav --mode bleep`. Covered by
  `tests/test_audio_redaction.py`. Not yet measured end to end: how much
  of a spoken name a span actually covers depends on timestamp accuracy,
  and that pairing has not been scored.
- **B3. Voice anonymisation. SHIPPED, AND MEASURED AS INADEQUATE.**
  `voice_anonymisation.py` implements the McAdams transformation, the
  VoicePrivacy Challenge baseline: per-frame linear prediction, each pole's
  angle raised to a power, so the formants move while pitch and timing stay.
  CPU-only, no model download, deterministic. `python -m voice_anonymisation
  --audio in.wav --out out.wav --alpha 0.8`.

  **Historical initial linkage test, superseded by the multi-meeting
  re-run below.** Measured on 200 AMI
  utterances against the speaker-embedding model the diarisation pipeline
  already carries (`evaluation/benchmark_anonymisation.py`,
  `hpc/submit_anonymisation.sh`), the linkage rate — does an anonymised
  utterance's nearest neighbour among the *original* recordings still belong
  to the same speaker — stays far above the 0.25 chance level:

  | alpha | self-similarity | linkage (chance 0.25) |
  | --- | --- | --- |
  | 0.5 | 0.10 | 0.36 |
  | 0.7 | 0.29 | 0.66 |
  | 0.8 | 0.45 | 0.83 |
  | 0.9 | 0.70 | 0.91 |

  Only alpha 0.5 approaches chance, and it badly damages the audio. This
  agrees with the published evaluations, which report verification systems
  performing above chance against McAdams. Self-similarity alone would have
  flattered it (0.10 at alpha 0.5 looks like near-total anonymisation), which
  is exactly why the linkage rate is the headline.

  **Disposition:** keep the transform, document it as a disguise that raises
  the cost of identification rather than removing the possibility, and do not
  let a corpus be deposited on the strength of it. The measurement is the
  contribution, not the transform.

  **The intelligibility cost: cause found, figure pending.** Four faults in
  the harness were found and fixed. Three were measurement errors (a mean of
  per-utterance rates that let one-word references dominate; a hardcoded
  embedding-model name; an unmatched baseline). The fourth was a defect in
  the transform itself, and it explains the result that could not be true —
  mildly warped audio transcribing *better* than the original.

  The output was scaled by its own peak. The linear-prediction synthesis
  filter rings at frame boundaries and throws occasional large samples, so a
  single one of those set the gain for the whole file. The attenuation grows
  with how loud the recording is:

  | input peak | alpha 0.9 | alpha 0.8 | alpha 0.7 |
  | --- | --- | --- | --- |
  | 0.05 | x1.09 | x0.89 | x1.01 |
  | 0.30 | x0.20 | x0.32 | x0.40 |
  | 0.90 | x0.09 | x0.05 | x0.03 |

  At a realistic recording level the anonymised audio came back twenty times
  quieter. Whisper hallucinates less on near-silence, so the insertions that
  dominate its error on short utterances disappeared and the anonymised
  condition scored better than its own input. It also explains the
  non-monotonicity across alpha: the accidental gain varied erratically, so
  the word error rate wandered rather than degrading smoothly. This was a
  fault in the shipped feature, not only in its evaluation — anyone running
  `voice_anonymisation` would have received audio far quieter than they gave
  it.

  The intended resynthesis control could not have caught this, because it is
  a mathematical no-op: analysis and synthesis through an unchanged filter
  cancel exactly, so it reproduced the input at full level.

  Gain is now set from the whole signal by matching the input's root-mean-
  square level, with the residual transient compressed above a knee rather
  than allowed to attenuate everything beneath it; the measured ratio moves
  from x0.03–1.09 to x0.49–1.00 across input peaks from 0.05 to 0.99. The
  residual is not assumed away: the benchmark measures the ratio it achieved
  and reports it beside every result with a flag for whether the comparison
  was level-matched, so a loudness change can never again move a word error
  rate unnoticed.

  **The level-matched sweep returned on 2026-08-22 (job 8573363), and the
  level ratio is 0.98–0.99 at every setting: the gain defect is gone. The
  anomaly was not.** At alpha 0.8 and 0.9 the warped audio still scored
  better than the baseline, which meant a second cause, in the estimator
  this time.

  Pooling errors over reference words was adopted to stop a one-word
  reference setting the corpus rate, and it does stop that for
  substitutions and deletions, which the reference length caps. Insertions
  have no ceiling. Two of the 200 utterances have a one-word reference and
  drew a 221-word hypothesis from the recogniser on unmodified audio;
  between them they carry **58.4% of all baseline error**. Warping happens
  to interrupt those two loops, and that alone produced the impossible
  sign. Removing them leaves a monotone cost of **0.03 / 0.28 / 0.82 /
  1.80** at alpha 0.9 / 0.8 / 0.7 / 0.5, against a screened baseline of
  0.20. The screen is insensitive to its own threshold: anything from 4 to
  200 selects exactly those two, the next-worst baseline being 4.0.

  `degenerate_baselines` now finds them and `summarise` reports the cost
  both ways, with the count and the share of error removed. Only the
  baseline arm is screened; a warp that provokes a loop has damaged the
  transcript, and dropping those would hide the cost being measured.
  `wer_cost` is flagged rather than withheld now that the cause is known.
  The August `anonymisation_summary.json` (job 8573363) predated this and
  carried the old `wer_cost_withheld` field, which is why the manuscript
  pools the guarded figures from `anonymisation_report.csv`.

  **Lesson, and the second time this project has hit it:** an estimator
  chosen to fix one failure mode does not thereby fix the family. Pooling
  cures mean-of-rates for the bounded error types only. Check which of the
  terms your denominator actually bounds.

  The privacy finding above is unaffected. Linkage is computed from
  embeddings of the same audio and was stable across four runs.

  Re-run after the codebase audit, 2026-09-28 (ARC jobs 8917988 and
  8917989, code 6f9bf56). The committed curve is now the multi-meeting
  sample: 400 utterances, the first 25 usable ones of each of the 16 AMI
  test meetings, 14 speakers, with chance taken over the candidates each
  probe searched and linkage also reported across meetings (EPRIV-04,
  EPRIV-15). Linkage is 0.20 / 0.57 / 0.79 / 0.92 at alpha 0.5 / 0.7 /
  0.8 / 0.9 against a chance level of 0.14, and across meetings 0.17 /
  0.51 / 0.74 / 0.89 against 0.11. Only alpha 0.5 comes near chance, and
  there the guarded word error rate is 0.85 against a baseline of 0.18.
  The summary now writes the guarded figures itself. The single-meeting
  configuration is kept in `output/evaluation/anonymisation_single_meeting/`;
  it repeats the August configuration on a different 200 utterances of
  EN2002a, as `hpc/runs/anonymisation_single_meeting.env` explains. Both
  jobs took their speaker embeddings from
  `pyannote/wespeaker-voxceleb-resnet34-LM` loaded directly, because a
  corrupted pyannote cache on ARC stopped the diarisation pipeline that
  bundles it from loading. Once the cache was restored, ARC job 8976304
  found the pipeline's embedder and the directly loaded one bit-identical
  (`hpc/runs/anonymisation.env`).
- **D4. `contraction_fix` was corrupting English. FIXED 2026-08-26.**
  The largest post-processing effect in the paper was not a scoring
  artefact, which is what the manuscript claimed. The repair table was keyed
  on misspellings, but **seven keys were ordinary English words**: `were` ->
  "we're", `its` -> "it's", plus `wont`, `cant`, `shed`, `wed`, `id`. On
  LibriSpeech test-clean the stage made **228 utterances worse and none
  better**, entirely through **+265 substitutions with zero insertions and
  zero deletions** -- the signature of a stage replacing correct words, since
  a genuine orthographic mismatch would trade errors both ways.
  The manuscript's stated mechanism (jiwer strips apostrophes, so the
  intermediate form is briefly inconsistent) is doubly wrong: the project's
  own normaliser is `[^\w\s']` and **preserves** the apostrophe, and the
  stated mechanism would predict *zero* cost, not the largest cost measured.
  Whisper Large v3 already writes these contractions correctly, which is why
  no utterance anywhere in the sweep improved under the stage.
  The seven keys are gone under an invariant (**no key may be a word that is
  already correct English**), enforced by
  `test_contraction_table_holds_no_ordinary_english_word` against the table
  itself rather than against samples. One existing test had **codified the
  bug** (it asserted English `its` -> `it's`) and was corrected.
  **The committed sweep therefore measures the defect, not the repair**;
  `contraction_fix` and `pipeline_full` should fall to ~0 on a re-run.
  Re-running is cheap: `benchmark_wer` decodes each utterance **once** and
  applies every condition to that one hypothesis, so one decode pass with
  `--dump-hypotheses` makes all future re-scoring CPU-only.
  **RE-RUN 2026-09-02** (ARC job 8688725, commit 53378ba): on LibriSpeech
  test-clean `contraction_fix` now costs +0.00 percentage points and
  `pipeline_full` +0.01, against +0.43 and +0.40 before the repair
  (`output/evaluation/condition_ci_postfix.csv` against `condition_ci.csv`).
  The repaired pipeline's results are `sweep_aggregate.csv` and
  `sweep_reports_postfix/`; the pre-repair ones are kept as
  `sweep_aggregate_prefix.csv` and `sweep_reports/`.
  The audit's re-run of the sweep (ARC jobs 8917985 to 8917987, code
  6f9bf56) has since replaced `sweep_aggregate.*`, `sweep_reports_postfix/`
  and `condition_ci_postfix.csv` in place (2e36bf9, 9cb43e3), and there
  `pipeline_full` also differs from raw by 0.000 points.
  **Lesson: a lookup table keyed on "wrong spellings" needs an invariant that
  no key is also a right spelling. And a null result nobody can explain is
  worth more scrutiny than one that confirms the design.**
- **B4. Encrypt-at-rest for raw artefacts (CPU).** The audit found that the
  timestamped JSON and WebVTT are written before masking and retain names.
  Rather than only documenting this, encrypt those raw artefacts at rest
  (authenticated symmetric encryption, key from a local file or env var, as
  with the HF token) so the de-identified `.txt`/`.docx` remain the only
  plaintext by default. Closes the audit's concrete finding.
  *Premise partly superseded by D1 below:* a masking run now also writes a
  redacted timestamped pair, and `--redacted-timestamps-only` suppresses
  the raw one. The raw pair is still written by default, and it is not
  encrypted.
- **B5. Confidence and hallucination gating. DONE, with a corrected premise.**
  The plan assumed Whisper's average log-probability and no-speech probability
  were available. They are computed inside `generation_whisper.py` for the
  temperature-fallback logic, but the `transformers` ASR pipeline's
  post-processing returns only the text and the timestamped chunks and
  discards them; reading them would mean bypassing the pipeline and calling
  `model.generate(return_segments=True)`, a larger change to the transcription
  path than this layer warrants. `confidence.py` therefore flags segments from
  what the pipeline does return: verbatim repeats of the preceding segment,
  single-token and repeated-phrase decoding loops, long near-wordless spans
  (the signature of decoding over silence or music), and implausible speech
  rates. The module states plainly that these are heuristics rather than model
  confidence, and names `return_segments=True` as the upgrade path, which
  would not change its interface. Wired into the pipeline, which writes
  `<name>_review.json`; also usable standalone as `python -m confidence`.
  Flags nothing on the committed 21-segment interview, which is the negative
  control that matters: a flag that fires on ordinary speech trains the reader
  to ignore it. Reporting the flag rate on the podcast corpus still needs the
  GPU pass.
- **B6. Output provenance and tamper-evidence. DONE.** `provenance.py` writes
  a `<name>_manifest.json` beside each run's outputs, listing every artefact
  with its SHA-256, the input recording's digest, and the settings that
  produced them, plus a digest of the manifest's own canonical form so that
  editing a recorded digest is itself detectable. `python -m provenance verify`
  reports modified, missing, and unlisted files and exits non-zero. Integrity
  needs no key; authenticity is opt-in through an HMAC keyed by
  `TRANSCRIPTION_SIGNING_KEY` or a key file, and the distinction between the
  two is stated rather than blurred, because a digest anyone can recompute
  proves nothing about authorship. Standard library only. Tested in
  `tests/test_provenance.py`, which is written mostly as attacks: edit an
  artefact, rewrite a recorded digest to match, forge a signature, present an
  unsigned manifest to a reader holding a key (fails closed), delete a file,
  add one.

---

## Track C --- Broader ASR evidence (GPU waves)

- **C1. Multilingual FLEURS WER. DONE.** Scored Large v3 raw against
  `pipeline_full` on six non-English FLEURS splits, over three passes. The
  composite was inflating word error rate on every language tested, from
  1.08x on Dutch to 8.10x on Polish; two English-language assumptions were
  responsible (a blanket non-ASCII strip that deleted diacritics, and
  English-lexical clean-text stages applied to every language), and with
  both repaired the composite is neutral at 1.00x on all six. Written up as
  `@sec-multilingual`; data in `output/evaluation/fleurs_multilingual_summary.json`.
  The audit added a fourth pass, a re-run at code 6f9bf56 (ARC job 8917984,
  September 2026), in which the composite scores every utterance of all six
  languages exactly as raw.
- **C2. Disfluency fidelity. DONE.** Word error rate cannot settle the
  "preserves disfluencies" claim, because it counts how many words differ
  and not which. `benchmark_wer.py --dump-hypotheses` keeps the verbatim
  text and `evaluation/disfluency.py` scores it, separating retention (of
  the fillers the model emitted, how many survive a transform) from
  reference recall (of the fillers the transcriber recorded, how many
  reach the output).

  Full AMI test split, 12,643 utterances: the production composite retains
  **100%** (1,203 of 1,203) of what the model emits, so the claim about the
  post-processing holds exactly. But the model emits only **19.7%** of the
  4,084 fillers in the references, so four fifths of the hesitations are
  lost before post-processing sees them and cannot be restored.

  The scoring normaliser retains **2.2%** and is inconsistent about which
  it drops (removes um/uh/hmm/mm/mhm, keeps er/ah/backchannels). Worse, it
  strips fillers from the *reference* too, so an utterance that is nothing
  but a hesitation normalises to empty and is discarded: **990 utterances,
  7.8% of the corpus, holding 69.7% of the emitted fillers, and all 990
  carried a filler**. `--audit-conditions` reproduces the per-token table
  with no GPU.

  Superseded: the figures above are the August 2026 ones, from a separate
  decode (ARC job 8555165). The committed pair was rescored in October
  2026 from the AMI decode of the audit's sweep (ARC job 8917985), with
  recall always counted against the transcriber's reference and a
  standalone `huh` no longer counted as a filler (audit findings ESTATS-01
  and ESTATS-08); see `output/evaluation/disfluency_summary.json`. There
  the composite keeps 1,195 of 1,195, the model emits 19.7% of the
  transcriber's 4,072 fillers, the scoring normaliser keeps 0.6%, and the
  990 utterances it discards hold 70.1% of the emitted fillers.
- **C3. Determinism and seed robustness. DONE.** 200 AMI utterances
  transcribed twice under a fixed seed and again under a second seed on an
  H100 NVL: all three compared runs agreed on every utterance, character
  for character (`evaluation/determinism.py`, `hpc/submit_determinism.sh`).
  The job decoded a fourth run, seed 1 a second time, which the committed
  comparisons do not include (`hpc/runs/determinism.env`).
  Read with care: decoding is greedy, so the seed governs kernel selection
  rather than sampling. The check was repeated on an L40S (job 8781724,
  `output/evaluation/determinism/l40s_8781724/`), on a processor in
  float32, the desktop path (job 8978759, `cpu_8978759/`), and on a V100
  under seed 0 (job 8978760, `v100_8978760/`), each time with the same
  result, and `determinism_cross_accelerator.json` beside them compares
  these runs with the V100 condition sweep on the same 200 utterances.
  Each run whose decodes were repeated reproduced its own text. The two
  V100 runs and the processor give the same words on all 200, the L40S
  differs from each of them on the same 2, and the H100's error rates
  depart from each of the others' on one. The two V100 runs, on one node,
  show that the seed, the code and the process changed no word there, and
  the V100 run under seed 0 still differs from the L40S, whose seed and
  process it shares. Those two also differ in node and code commit, so the
  comparison shows the text changing between hardware configurations
  without isolating the card.
- **C4. Model coverage (GPU, optional).** Add Whisper Large v3 Turbo and a
  `faster-whisper` (CTranslate2) backend to the sweep to speak to the
  efficiency thesis with an accuracy/throughput trade-off.

---

## Track D --- Fixes and hardening

- **D1. Redacted-parallel outputs. DONE.** `write_timestamped_outputs` now
  emits a `_redacted.json`/`_redacted.vtt` pair beside the raw set whenever
  masking is on, carrying identical timings and speaker labels with the names
  masked, and `--redacted-timestamps-only` suppresses the unredacted pair for
  deployments that must not retain it. Each payload declares its own status
  in a `redacted` field. The manuscript's promise in the masking section is
  updated to describe what the workflow does rather than what a stricter
  deployment would do. Tested in `tests/test_redacted_outputs.py`, whose
  decisive case asserts no name survives anywhere in the serialised
  redacted payload; that assertion caught a real leak during development,
  where word text is stored under `word` rather than `text` and a
  field-by-field redactor missed it.
- **D2. Repetition-threshold sensitivity.** The required hypotheses are
  recovered and hash-verified. Compare thresholds around the production
  default on fixed utterances, report macro and pooled WER with changed,
  improved and worsened utterance counts, and reproduce the original
  baseline and default condition before accepting the sensitivity report.
  The analysis must test the extent of any benefit, without assuming an
  AMI rescue or choosing a new production threshold on these test splits.
- **D3. Container and Zenodo DOI.** One-command reproducible container plus
  an archived release with a DOI and a licensing/ethics table, so the
  artefact is citable and re-runnable.

---

## Historical sequenced timeline (two months, capacity-aware)

The ordering keeps GPU demand low and steady while shipping visible value
early. CPU-only items can run in parallel with GPU waves.

- **Weeks 1-2 (CPU-only, no ARC load).** Corpus fetch (done). B2 audio
  redaction core plus tests. B1 NER fallback plus a re-run of the masking
  benchmark. A4 podcast scorer skeleton with stub tests. D1 redacted
  parallels.
- **Week 3 (first GPU wave).** C1 multilingual FLEURS (pre-flighted, `%2`).
  In parallel on CPU: B4 encrypt-at-rest, B5 confidence gating.
- **Week 4 (GPU wave + case study).** A2 worked case study on episode five
  (one full pipeline pass), which also feeds A1's structural metrics and
  B5's flag-rate; B3 voice anonymisation plus its WER trade-off.
- **Week 5 (small GPU wave).** C2 disfluency (after the hypothesis-dump
  change) and C3 determinism. A3 optional gold subset if time allows.
- **Week 6 (consolidation).** B6 provenance signing, D2 threshold
  sensitivity, D3 container and DOI; fold every new result into the
  manuscript with CIs; final polish pass.

Net new GPU footprint stays within the ~25-35 GPU-h envelope already
planned, since the heavy additions (Track B) are CPU-only.

---

## Honest limitations to keep in view

- The podcast corpus is *synthetic* speech; it complements, and does not
  replace, the human-speech benchmarks. Its value is realism of format and
  reproducibility, not acoustic representativeness of human spontaneous
  speech. State this plainly.
- Without a gold subset, Track A reports structural and reference-free
  metrics, not WER/DER, on the podcast; the optional gold subset (A3) is the
  route to headline accuracy numbers there.
- B1's synthetic recall gains need natural-text precision assessment.
  B3 reduces linkage for the tested fixed model while increasing guarded
  ASR error; adapted-attacker and perceptual-intelligibility evaluations
  are still needed. These measurements bound different claims.
- The footprint figures are modelled, not metered (the cluster has no energy
  accounting). The allocation-based estimate models GPU, CPU and memory
  power with fixed PUE and carbon-intensity assumptions. Without onsite
  measurements, it does not establish an upper bound on total energy
  or emissions.

## Key references for the new features

- Zaratiana et al. (2024), *GLiNER: Generalist Model for Named Entity
  Recognition using Bidirectional Transformer*, NAACL 2024 --- B1.
- Patino et al. (2021), *Speaker Anonymisation Using the McAdams
  Coefficient*, Interspeech 2021; VoicePrivacy Challenge evaluation plans
  (2020/2022/2024) --- B3.
- Lannelongue, Grealey & Inouye (2021), *Green Algorithms*, Adv. Sci. ---
  footprint methodology (already cited in the manuscript).
