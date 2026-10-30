# Issues and their status

This file records the findings of the September 2026 `/strong-codebase` audit that
its first pass did not resolve in code, each with the reason it was held. The audit
verified 330 findings, four of which were refuted, and the rest were resolved on
branch `strong-codebase-audit`, as `CHANGELOG.md` summarises. A fix that would move
a committed number or change an end product was held here until a deliberate re-run,
so that the committed results stay reproducible from the archived commit. Some were
held instead for the author's decision or an ARC run, or because the rest of the fix
needed files or tests outside that pass. Identifiers such as `T1-02` are the
audit's. `REV-` items came from the adversarial review of the fix branch, NEW-01 and
NEW-02 from the documentation pass, NEW-03 to NEW-06 from checks made during the
re-run wave, NEW-07 to NEW-10 and NEW-12 from checks of the case study's name masking
and review once its re-run was committed, and NEW-11 from the cross-check of the
rewritten manuscript.

Each entry gives the file and line in the audited commit `10981d4`, the severity
(BLOCKING, MAJOR, MINOR), whether it is high-risk (it touches code behind a
committed result), and whether fixing it would change numbers or an end product. A
second pass from 26 September 2026, a re-run wave on the Oxford ARC cluster, the
manuscript's rewrite for that re-run, the follow-up of 6 October 2026 and the author's
decisions of 17 October 2026 have since worked through most of the entries.
Each now carries a paragraph labelled Status, after its location line or, for the
areas G1 to G6, after its description. Its opening words say where the entry stands:
Resolved, Partly resolved, Open, Pending re-run (it waits on ARC jobs whose results
are not yet committed, or on the final scheduler capture) or Withdrawn. The Status
takes precedence over the entry's Why deferred paragraph, which stays as the record
of the state when the entry was written. Line numbers in a Status are those of
commit `f2578b8`, against which the statuses were written or, for G1 to G6,
rewritten, unless the Status names another commit.

The counts below were made by a script that reads the opening words of every Status
paragraph in this file, section by section, and checks that each entry has exactly
one. In the Blocking section, 36 are Resolved and 1 Partly resolved. In the Major
section, 81 are Resolved and 3 Partly resolved, and in the Minor section all 35 are
Resolved, NEW-05 and LINT-01 since 30 October 2026. Of the areas the audit did not cover, 2 are
Resolved and 4 Partly resolved. No entry is Pending re-run, since every ARC job
and the scheduler capture the statuses waited on have finished and their results are
committed, and none is Withdrawn. The same script sorts the 146 Why deferred
paragraphs by their first sentence. Of these, 133 give a committed number, artefact
or end product as the reason, 8 the author's decision or an ARC run, and 5 the files
or tests outside what that pass changed. NEW-03 to NEW-12 and the areas G1 to G6
have no such paragraph. What is left of the release, which is the author's, is set
out as a checklist under DOCS-14. The section on observations from ARC records what
read-only checks on the cluster found, the incident NEW-INC-01 among them.

The pass of 20 October 2026, made after release 2.0.0 and without access to the
cluster, has a section of its own below the Minor section, so that the counts above
stay those of the audit. It holds ten entries: CR-02 and CR-06 from a correctness
review of the 49 commits after `1f9f22e`, and SC-17 to SC-24 from a code pass. A
second pass on 29 and 30 October 2026, with the cluster reachable again, resolved
nine of them and CR-06 in code, as each Status records, together with NEW-05 and
LINT-01 above. `CHANGELOG.md` summarises both passes; line numbers are those of the
commit each entry names.

The pre-publication gate of 30 October 2026 has the last section before the
observations from ARC. Its eight read-only audits of the release 2.1.0 tag found
31 entries, PG-01 to PG-31, and the release found a 32nd, PG-32; release 2.1.1 resolves them apart from the three
whose Status says Open; `CHANGELOG.md` summarises them.

## Blocking (37)

### T1-02: Unicode strip still deletes whole scripts (CJK, kana, Hangul, Arabic presentation forms) and typographic apostrophes, contradicting its docstring and the manuscript

`transcription.py:799` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 748ae6b removes emoji by explicit blocks, maps typographic quotes to ASCII, drops only the So, Sk, Cc, Cf, Cs, Co and Cn categories and no longer deletes isolated ASCII symbols, and tests/test_s1_txt_unicode_strip.py covers CJK, Hangul, Arabic presentation forms, Arabic-Indic digits, "It’s", "£5" and "¿Qué?". ea2f478, d850f07 and 70926fa correct the conditions.py docstring, docs/conditions_audit.md and Appendix B of the manuscript. In the re-run sweep at 6f9bf56 (2e36bf9, intervals 9cb43e3), unicode_strip's LibriSpeech deltas against raw are 0.000 in every cell but Medium test-clean (-0.002 pp), and its paired delta went from +0.000054 to 0.0. The FLEURS fourth arm (56ce519) is exactly neutral in all six languages, and the strip used in arms 2 and 3 had deleted the vulgar fractions of FLEURS sentence 1682, so "not hit" below holds for the CJK deletion only. docs/conditions_audit.md describes the four arms (e818965), and 80dc57c (merged in 0e90917) has the manuscript's multilingual section report all four and the stage as it now is (manuscript.qmd:3437-3542 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A Mandarin, Japanese or Korean interview transcribed with --language chinese (or with that language detected) yields an empty or near-empty transcript with no warning. For hypotheses containing U+2019 ('It’s', French 'l’homme'), the stage outputs 'Its'/'lhomme'. evaluation/wer.py:93 maps the typographic apostrophe to "'", which its punctuation strip keeps, so raw scores "it's", a hit against IT'S, while the stripped form scores 'its', one substitution. unicode_strip and pipeline_full WER therefore shift whenever the model emits typographic apostrophes. Currency amounts lose their £ or € symbol.

**Proposed fix.** Replace the 24C2-1F251 range with explicit emoji blocks: U+1F000-1FAFF, U+2600-27BF, U+2B00-2BFF, U+24C2 alone, U+FE0F and U+200D. In step 2, keep categories L, M and N (digits of every script), plus Sc and ASCII. First map U+2018/U+2019 to ' and U+201C/U+201D to ". Then drop only So, Sk, Cs, Co, Cn and Cf. Reconsider step 3's deletion of isolated ASCII symbols, or document it. Add tests for CJK, Hangul, Arabic presentation forms, Arabic-Indic digits, 'It’s', '£5' and '¿Qué?'. Correct the docstring, evaluation/conditions.py:_unicode_strip, docs/conditions_audit.md:295 and manuscript 3138-3141 (sign-off). After sign-off, re-run unicode_strip and pipeline_full on the five corpora; the six affected utterances show that the numbers can move.

**Committed results affected.** output/evaluation/sweep_reports_postfix: wer_report_unicode_strip and pipeline_full, which the manuscript cites through cci_pp('unicode_strip') at manuscript.qmd:1120 and :1181. Deleting U+2019 and '£' adds a small amount of WER; the commit message of 53378ba records a 0.035 pp move. The manuscript at 3138-3141 says the stage 'leaves the orthographic content untouched', which this contradicts. FLEURS arms (pl/es/fr/de/it/nl) are not hit by the CJK deletion.

### T1-03: Name masker leaks capitalised names that follow an opening quote or parenthesis, and the cleaner glues quotes onto the previous word before masking runs

`transcription.py:635` · BLOCKING · HIGH-RISK · changes numbers · verified confirmed, panel upheld

**Status.** Resolved. c5f85f4 makes the capitalisation gate and the title lookahead read the token's core, ab76633 keeps a possessive clitic after the placeholder ("[SURNAME]'s"), and 5080964 stops _punct_space_fix deleting the space before an opening quote. A name after a quote or a bracket is therefore masked and logged, after the cleaner too (tests/test_s1_txt_masking.py, tests/test_audit_pipe_masker_punctuation.py and tests/test_s1_txt_punct_space.py), and audio bleeping inherits the fix because audio_redaction.word_is_name passes each word through the same masker. 04c01b3 makes benchmark_masking._strip_marker remove a trailing clitic and adds quoted and bracketed carriers, and a08265c regenerated all four masking arms (1,940 cases). In the dictionary arm each new position scores the arm's overall recall, 0.3505, and the manuscript's masking prose is followed up under EPRIV-10.

**Why deferred.** The complete fix would change a committed number or artefact. The masker part is fixed (c5f85f4): the capitalisation gate and title lookahead test the token core, so names after quotes, brackets and dashes are masked, with the masking benchmark byte-identical. Two parts remain. Keeping "'s" as a placeholder suffix flips possessive hits in benchmark scoring, and _punct_space_fix still glues an opening quote to the previous word.

**Failure scenario.** Transcript text: She said "Sarah was there" and (John) agreed, run with --mask-personal-names. Both names survive verbatim in the 'redacted' .txt/.docx, and no log row is written. The same token shapes in word-level chunks are not bleeped by audio_redaction.

**Proposed fix.** As proposed: take core = re.sub(r'^\W+|\W+$', '', stem), test core[:1].isupper(), and emit leading punctuation + placeholder + trailing punctuation, keeping "'s" as a suffix. Apply the same to the title lookahead at 694-695. In _punct_space_fix, stop deleting the space before an opening quote. That changes punct_space_fix and pipeline_full hypothesis text, but not WER, because the normaliser replaces quotes with spaces. Re-check the composition regression fixture in tests/test_conditions.py. Add quoted and parenthesised unit tests. Extending the benchmark templates and re-running needs sign-off.

**Committed results affected.** None of the committed numbers. The masking benchmark templates contain no quoted or parenthesised carriers, and the committed case-study raw text (output/case_study/ep05_raw_text.txt) has no capitalised word directly after '"', '(' or a smart opening quote, so this leak did not occur there. Future masked outputs and audio bleeping (word_is_name) are exposed.

**Diff proposed by the implementer.**

    transcription._wrap_placeholder: clit = re.search(r"['’]s?(?=\W*$)", rest); if clit: return leading + placeholder + clit.group() + ''.join(re.findall(r'[^\w]', rest[clit.end():])).
    evaluation/benchmark_masking._strip_marker: return re.sub(r"[^\w\[\]]", "", re.sub(r"['’]s?(?=\W*$)", "", tok)).
    Re-run benchmark_masking (default, --case-insensitive, --ner, both) with seed 42 and commit the regenerated masking_report*.csv.

### T1-04: _punct_space_fix splits decimals, thousands and times ('3.5' to '3. 5', '1,000' to '1, 000') in every language; committed example transcripts already show it

`transcription.py:1141` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 5080964 stops _punct_space_fix putting a space after a . , or : between two digits, so "3.5", "1,000", "10:30" and "3,5" stay whole, and tests/test_s1_txt_punct_space.py pins them. WER cannot move, and in the re-run grid (2e36bf9) punct_space_fix still equals raw in all 15 cells. The committed example transcripts were not regenerated: architecture_of_meaning and behind_the_curtains still carry "3, 000", "1, 200", "0. 05" and the other splits listed below, and 12275ed labels all four transcripts in example_output/transcripts/README.md as release 1.0.0 output. On 17 October 2026 the author decided to keep them as the labelled record of release 1.0.0 and not to re-transcribe them; example_output/variants holds the current code's output.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Any transcript mentioning figures: '3.5 percent' is delivered as '3. 5 percent' (a sentence break followed by 5), '£1,000' as '1, 000' (reads as a list), '10:30' as '10: 30', and French decimals '3,5' as '3, 5'. The committed example transcripts show exactly this.

**Proposed fix.** Use a callback so the regex stays readable. Keep re.sub(r'([.,!?;:])(?=[^\s.,!?;:])', f, text), where f returns m.group(1) with no space when the mark is one of '.,:' and both text[m.start()-1] and text[m.start()+1] are digits, and m.group(1)+' ' otherwise. Leave line 1098 as it is (it only touches letters) or add an abbreviation and URL guard; dropping it changes whitespace_normalise output, though not WER. Add tests for '3.5', '1,000', '10:30', '3,5', '0.05' and 'e.g.'. Regenerate example_output transcripts only with sign-off.

**Committed results affected.** Committed example_output/transcripts. architecture_of_meaning has about 9 split numbers ('3, 000' x2, '1, 200' x2, '1, 500' x2, '2, 000', '0. 1', '0, 4'), and behind_the_curtains has 3 ('0. 05', '1, 000' x2). In modular_mini_grammar the three pattern hits are a genuine list ('codes 10, 11, 12, 13'), so none are split numbers. WER, and so every manuscript number, is unaffected because the normaliser maps . , : to spaces.

### T2-01: _punct_space_fix splits decimals, thousands separators, clock times and URLs, and glues opening quotes to the previous word

`transcription.py:1141` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 5080964 keeps decimals, thousands separators and clock times whole, keeps the space before an opening quote by pairing double quotes, and keeps an unspaced "..." as an ellipsis. 4d60a0a protects the full stops of dotted abbreviations (i.e., e.g., U.S.) and of lower-case host names in a listed domain in whitespace_normalise, sentence_capitalise, pronoun_i_fix and punct_space_fix. tests/test_s1_txt_punct_space.py covers 3.5, 10:30, 1,000, i.e., quoted speech and the ellipsis, d850f07 and 4d60a0a describe the stage in docs/conditions_audit.md, and punct_space_fix equals raw in all 15 cells of the re-run grid (2e36bf9). The 6 October 2026 manuscript pass adds abbreviation and lower-case host-name protection to Appendix B, closing that documentation remainder. The historical example transcripts keep their split numbers, as the record of release 1.0.0 that the author decided on 17 October 2026 to keep (T1-04).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Any transcript containing a decimal, a time, a thousands separator, a URL or a quotation. For example, a spoken 'p equals 0.05' is delivered as 'p equals 0. 05', and '$1,000' as '$1, 000'. A researcher coding numbers or quotes from the delivered .txt/.docx gets corrupted values, and nothing warns them. The example transcripts shipped with the paper already contain such corruptions.

**Proposed fix.** Restrict the space insertion so it never fires between two digits (for example `(?<!\d)([.,!?;:])(?=[^\s.,!?;:])` plus `(?<=\d)([.,:])(?=[^\s\d.,!?;:])`). Do not adopt the proposed blanket exemption for `\w+(\.\w+)+` tokens: it would also suppress the stage's real job of separating sentences glued at chunk joins ('end.Next'). Limit that exemption to single-letter dotted abbreviations (i.e., e.g., U.S.) and lower-case dotted hostnames. Stop stripping whitespace before an opening quote (pair the quotes), and leave '...' intact. Add regression tests for 3.5, 10:30, 1,000, i.e., 'said "hello"' and '...'. Update manuscript.qmd:3175 and docs/conditions_audit.md to describe the stage accurately. Re-running the sweep is only a confirmation, since `_PUNCT_RE` makes WER invariant. Regenerating example_output needs maintainer sign-off.

**Committed results affected.** example_output/transcripts/{architecture_of_meaning,behind_the_curtains}/transcript.txt and .docx (numbers split: 3, 000 / 1, 200 / 1, 500 / 2, 000 / 0. 05 / 1, 000). Not the committed WER/CER tables (pipeline_full and punct_space_fix scores are invariant under normalise_text). The manuscript's stage description at qmd:3175-3176 is inaccurate.

### T2-02: Version stamp comes from a hand-maintained versions.csv that still says 1.0.0 (2025-11-06), while results and transcripts come from much later code

`transcription.py:1936` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 5b15a6a stamps transcripts and the run manifest with the newest release in versions.csv followed by the git commit as a PEP 440 local label, with ".dirty" for a modified tree, and tests/test_s1_txt_version.py covers it. The committed case-study manifest, for example, records "1.0.0+gfc652ab87144", the stamp of code that preceded the 2.0.0 row, so output from later code no longer claims to be 1.0.0. versions.csv now names release 2.0.0 (DOCS-14), and the stamp follows it with no change of code, so output from the release's code is stamped 2.0.0 with its commit. The example transcripts keep their 1.0.0 stamp, which is correct for them.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reviewer or replicator checks out the 1.0.0 release the manuscript and Zenodo DOI point to. They re-run the sweep and get different numbers, because that release predates the unicode-strip, language-gate, pooled-WER and contraction fixes. Separately, every transcript produced today is stamped 'Transcription system version: 1.0.0' although the code differs materially from 1.0.0.

**Proposed fix.** As proposed: derive the version and commit (importlib.metadata or `git describe --always --dirty`) and write it into transcript headers, provenance manifests and every output/evaluation summary JSON. Before submission, cut and tag a release containing the code behind the committed results, mint a new Zenodo version DOI, update versions.csv, CITATION.cff and setup.py, and cite that tag or commit at manuscript.qmd:604 (maintainer sign-off). Do not regenerate the example transcripts for this reason alone, because their 1.0.0 stamp is correct for their 2025-11-10 processing date.

**Committed results affected.** The manuscript.qmd:603-604 provenance claim and the Data/code availability statement (qmd:2991-3004), which point to the 1.0.0 archive. versions.csv, CITATION.cff and setup.py version fields. No numerical result changes. The example_output transcript stamps are correct for their 2025-11-10 processing date.

### EWER-01: sweep_aggregate recursively ingests every summary under the canonical ARC directory, mislabelling non-English FLEURS as English and emitting duplicate grid cells without warning

`evaluation/sweep_aggregate.py:208` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 6cd70c7 makes sweep_aggregate refuse a repeated (suite, model, condition) cell, announce every skipped file and look for the pilot marker only below the sweep directory, and 4a6256b skips, with a warning naming it, any summary that records a corpus outside the sweep instead of matching its file stem. Both landed before this file was written (a387654), so a non-English FLEURS summary can no longer become an English cell, and a second AMI cell, such as the disfluency job's, stops the run. hpc/aggregate_sweep.sh now defaults to the re-run sweep's own directory (ea0ddd3, then 2e36bf9), and the committed 255-row aggregate was written by the script (2e36bf9, see EWER-02). tests/test_audit_eval_sweep.py covers the refusal, the skip and the pilot rule.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Running `sbatch hpc/aggregate_sweep.sh` as documented yields up to six rows for (librispeech_clean, whisper-large-v3, raw): the top-level file, wer_summary_gpu.json with its condition defaulted to raw, and postfix/, preflight_postfix/, prefix_baseline/ and afterfix_pregate/. Pre-fix and post-fix values are mixed. It also yields seven (fleurs, whisper-large-v3, raw) rows, six of them German, French, Spanish, Italian, Dutch and Polish labelled as English FLEURS, and duplicate AMI rows from the disfluency job. The script exits 0 with no warning. In the manuscript, mw() and n_utt() return NA when length(v) != 1, while the figure chunks filter() and plot the duplicates.

**Proposed fix.** As proposed, plus: skip (with a warning) any summary whose benchmark.language is not English or whose (dataset, config) is not in the registry, instead of stem matching; raise on a duplicate (suite, model_slug, condition) key; test the pilot marker on path.relative_to(sweep_dir).parts. Regenerating the committed CSV needs maintainer sign-off.

**Committed results affected.** None committed. output/evaluation/sweep_aggregate.csv has 240 rows and 240 unique (suite, model_slug, condition) keys, all sourced from the hand-curated C:\tmp\pf2, with no non-English FLEURS rows. The defect bites on the documented regeneration path (hpc/aggregate_sweep.sh), which is the only scripted route to rebuild the grid.

### EWER-02: Committed sweep_aggregate.csv/json cannot be regenerated by the committed script (extra pipeline_version column, different JSON shape, hand-curated temp input)

`evaluation/sweep_aggregate.py:60` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 66959fd makes evaluation.sweep_aggregate write the committed schema itself: pipeline_version from each summary's recorded commit, source_file relative to the sweep directory, typed JSON rows, the pooled columns beside the macro ones, and the SHA-256 of every input summary in the JSON's provenance. 2e36bf9 replaced the hand-assembled 240-row files with the script's 255-row output from the re-run sweep (ARC jobs 8917985 to 8917987 at 6f9bf56), and 9cbd1d9 makes the regeneration gate compare JSON apart from run_metadata and generated. Run at HEAD on the fetched copies of those 255 summaries, which stay on ARC under audit2026/sweep, the script rebuilds sweep_aggregate.csv identical to the committed file up to line endings (byte for byte against a Windows checkout) and the JSON's rows and input digests exactly (checked locally on 2026-10-04). tests/test_audit_eval_sweep.py guards the header, the typed JSON with its input digests and the version taken from the recorded commit (test_the_committed_aggregate_has_the_writer_header, test_the_json_keeps_types_and_records_its_inputs and test_pipeline_version_prefers_the_recorded_commit). Two parts of the proposed fix are not done: a summary that records no version is aggregated with an empty pipeline_version unless --pipeline-version supplies a label, instead of being refused, and the script does not read the digests back to check a rebuild's inputs.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reviewer or maintainer running `python -m evaluation.sweep_aggregate` (or hpc/aggregate_sweep.sh) gets a CSV with no pipeline_version column and a JSON in a different shape, built from a different input set (EWER-01). The artefact behind the manuscript therefore has no reproducible build path, and the provenance column that commit aa6e61d relies on was added outside version control. Even a correct re-run is never byte-identical, because of `generated` and the absolute source paths.

**Proposed fix.** Carry pipeline_version from the benchmark block into SweepRow/_CSV_FIELDS: record the git SHA in benchmark_wer._write_summary, and fail if it is absent. Write source_file relative to sweep_dir. Commit a manifest of the 240 input summaries (relative path plus sha256) and have aggregate_sweep optionally consume it. Keep `generated` out of any byte comparison. Regenerate both committed files with the script only with maintainer sign-off, and verify that the macro values are unchanged.

**Committed results affected.** output/evaluation/sweep_aggregate.csv and sweep_aggregate.json, the grid behind fig-conditions, fig-suites, normaliser-gains, Appendix A and the inline mw()/n_utt() values (manuscript.qmd L78). No value is wrong, but none of it can be rebuilt from the repository.

### EWER-03: The scoring normaliser erases case, punctuation and bracket changes, so seven 'production' conditions are identical to raw by construction; filler_bracket's description and the manuscript's 'bounded null' are wrong

`evaluation/conditions.py:601` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. c4f3133 flags the seven conditions the scoring normaliser cannot see as wer_invisible and drops filler_bracket's claim of one insertion per filler, 66959fd carries the flag into the aggregate, b8a8c55 stops _filler_bracket bracketing inside elisions such as "o'er", and 70926fa drops the manuscript's "bounded null" framing. In the re-run grid (2e36bf9) all seven flagged conditions, pronoun_i_fix now among them, equal raw in every cell, and filler_bracket's paired delta went from +0.000035 to 0.0 (9cb43e3). 94eb6d1 and 8e1b7ff (merged in 0e90917) read the seven from the wer_invisible column and say that case folding and punctuation stripping leave every score alone while filler removal and the deduplication window cost a little. They also name the visible production stages, none of which changes a score on test-clean (manuscript.qmd:1968-2031, 2235-2246 and 2499-2514 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Any hypothesis in which the pipeline brackets a filler, capitalises a word or respaces punctuation scores exactly like raw, because normalise_text lowercases and strips punctuation on both sides after the transform. The benchmark therefore cannot detect a cost from these stages, whatever they do to the transcript. The manuscript reads the filler_bracket interval of +0.00 as a supported claim that marking fillers does no measurable damage, but the method guaranteed that result for the bracket insertion being tested.

**Proposed fix.** As proposed. Also fix transcription._filler_bracket so it does not match fillers adjacent to an apostrophe (e.g. add (?<!') and (?!') guards). That changes production output and the filler_bracket/pipeline_full cells, so it needs a rescore and maintainer sign-off. Any orthographic scoring pass should be an additional column set, not a replacement for the normalised WER.

**Committed results affected.** The manuscript's interpretation, not its numbers. L1136-1146 calls the filler_bracket result 'a bounded null... supported, not merely unrefuted... a null result was not guaranteed by the method'. L991-996 blames the corpus for the inert diagnostic conditions. The conditions.py filler_bracket description (L601-610) and docs/conditions_audit.md repeat the framing. The committed WER values are correct as normalised WER.

### EWER-05: whisper_norm passes an empty spelling mapping, so British and American spellings are NOT treated as equivalent; this is not the published Whisper normaliser the manuscript compares against

`evaluation/conditions.py:262` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. c4f3133 makes whisper_norm load openai-whisper's published spelling map, checks its SHA-256 and stops the run when the map is missing or altered, so "colour" against "color" now scores as a match, and tests/test_s1_wer_conditions.py covers it. The re-run sweep (2e36bf9) rescored every whisper_norm cell with the map: all 15 fell, by 0.047 to 0.277 pp (most on FLEURS), the Large v3 figures of 2.3% and 4.4% became 2.2% and 4.3% (0.0221 and 0.0434), and the test-clean delta against raw moved from -3.88 to -4.00 pp (9cb43e3). a995d84 and 94eb6d1 (merged in 0e90917) rewrite the manuscript's whisper_norm passages for that grid, with the comparison with Radford et al. computed inline and checked against both the macro and the pooled rates (manuscript.qmd:2577-2627 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reference containing 'colour', 'honour' or 'favour' (common in LibriSpeech's Gutenberg texts) against a hypothesis spelling 'color' scores a substitution under whisper_norm. The canonical Whisper normaliser maps both to 'color' and scores a hit. The 2.3% and 4.4% figures therefore come from a stricter normaliser than the one they are compared with, and the stated rationale says the opposite of what the code does.

**Proposed fix.** As proposed. If the empty mapping is kept deliberately, rename the rationale ('spelling variants are scored as errors, which makes this stricter than the published normaliser') and drop 'reproduces'/'implements' from the description and manuscript. Canonical rescoring for Large v3 needs a re-decode, because its dumps were overwritten (aa6e61d), and maintainer sign-off.

**Committed results affected.** All whisper_norm cells in sweep_aggregate.csv (fig-conditions, fig-suites, normaliser-gains) and the inline 2.3%/4.4% Large v3 figures at manuscript L1216-1222. Fixing it could only lower them, by an unquantified but likely small amount. The descriptive claims at manuscript L812-814 ('implements the normalisation used in the original Whisper evaluation tables') and conditions.py L252-255/L437-447 are inaccurate.

### EWER-07: evaluation.wer accepts .vtt references but reads them as raw text, so WEBVTT headers and cue timestamps are scored as reference words

`evaluation/wer.py:182` · BLOCKING · changes numbers · verified confirmed, panel upheld

**Status.** Resolved. a5fa9c1 makes evaluation.wer read a .vtt file as its cue text only, dropping the WEBVTT header, cue timings and identifiers, NOTE, STYLE and REGION blocks and markup, and tests/test_s1_wer_scoring.py::test_a_vtt_reference_scores_like_its_text checks that a VTT reference scores like the equivalent .txt. No committed result came from this path.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A user whose hand-corrected references are .vtt files (the format the tool emits) runs hpc/evaluate_wer.sh. Every cue adds 8 numeric reference tokens plus 'webvtt', so each counts as a deletion. The reported WER is inflated by a large but plausible-looking amount, with no warning.

**Proposed fix.** As proposed (parse VTT, or drop .vtt from accepted reference suffixes), plus a regression test comparing a VTT reference with the equivalent .txt.

**Committed results affected.** None committed, because committed WER summaries come from benchmark_wer, not wer._read_text. It affects any user of the published evaluation.wer CLI or hpc/evaluate_wer.sh with .vtt references.

### EDER-01: The 0.25 s collar is ±0.125 s in pyannote.metrics, not the NIST RT ±0.25 s collar the code and manuscript claim

`evaluation/benchmark_der.py:86` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 2bb4224 keeps the collar at 0.25 s (option a) and describes it in evaluation/benchmark_der.py, der_metrics.py and sweep_der.py as pyannote.metrics' total width, ±0.125 s around each reference boundary (md-eval -c 0.125). 70926fa rewrote the manuscript's collar sentences and the DER table caption the same way. 70933b4 commits the DER artefacts of wave 2a (ARC jobs 8976354 to 8976358 and 8976362, at 9cb43e3), and every summary and both sweep selections record collar_convention. The collar value is unchanged, so no DER figure moved for this reason. Rescoring at the NIST ±0.25 s (option b) remains open to the author and would need per-meeting hypothesis dumps, which the benchmark still does not write.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader or reviewer compares the 16.6% macro DER with published AMI results at the NIST 0.25 s collar, or reproduces it with md-eval -c 0.25 or dscore. The scored region then differs: pyannote excluded only ±0.125 s around each reference boundary, so the reported DER is scored under a stricter collar than the one stated, and the method description is wrong. The benchmark does not save the hypotheses, so the figures cannot be re-scored under the stated convention without re-running diarisation on a GPU.

**Proposed fix.** Fix (a) is enough and needs no GPU. Describe the collar everywhere (benchmark_der _COLLAR comment, der_metrics module and compute_der docstrings, sweep_der, manuscript 654/1821-1825/2053-2056, table caption) as 'a 0.25 s collar in the pyannote.metrics convention, i.e. ±0.125 s around each reference boundary (equivalent to md-eval -c 0.125)'. Drop the NIST and pyannote-benchmark claims, and add collar_convention to the summary JSONs. Option (b), re-scoring at collar=0.5, needs a GPU re-run for every DER output unless hypotheses are dumped first, so add per-meeting RTTM dumping before any re-score. Both options need maintainer sign-off because they edit the manuscript.

### EDER-02: annotation_from_segments drops a speaker whenever two turns share an identical span

`evaluation/der_metrics.py:60` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 2bb4224 stores each turn of annotation_from_segments on its own track, so two speakers on an identical span both survive (an exact same-speaker repeat is kept once), fixes the fine-tuning RTTM reader the same way and adds tests in tests/test_der_metrics.py and tests/test_s1_misc_der.py. 70933b4 commits every DER artefact from wave 2a's re-runs at 9cb43e3 (ARC jobs 8976354 to 8976358 and 8976362, on L40S cards, 2026-10-04), and against the August files only the two meetings this entry names moved. EN2002c gained 0.06 s of scored reference and moved by 5e-6 in DER, IB4002 by at most 3.7e-4 in a sweep cell, and the test macro and micro DER by at most 2.8e-7 and 5.9e-7, inside the bounds of the der_metrics docstring. Every other meeting of every run is identical to six decimals, so the hypothesis side, still not saved, changed nothing measurable, and 4047ffa records these moves in that docstring. Both sweeps still select threshold 0.70, minimum cluster size 12 and no minimum pause, and of the DER rates the manuscript prints only that cell's missed speech moved, from 6.39% to 6.40% (ea7c483).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** In EN2002c, two reference turns with the same begin and end times but different speakers keep only the later speaker, so 0.31 s of overlapped reference speech is removed before scoring. Whenever pyannote emits two speakers over exactly the same frame span, the hypothesis loses one of them in the same way, which changes missed-speech and confusion totals silently. The committed reference-side effect is small, around 1e-4 on one meeting. The hypothesis-side effect has not been measured.

**Proposed fix.** As proposed: `seg_ = Segment(start, end); ann[seg_, i] = speaker` (enumerate index) in annotation_from_segments, and the same in finetune `_read_annotation_from_rttm`. Add a two-speakers-identical-span unit test. Re-scoring the reference side alone is cheap. The hypothesis side needs diarise() to return pyannote's Annotation (or RTTM dumps) and therefore a GPU re-run. Needs sign-off because it changes committed result files.

**Committed results affected.** output/evaluation/der_report.csv row EN2002c (test) and der_summary.json aggregate; validation sweeps der_sweep.csv / der_sweep2.csv (IB4002 rows) and the hyperparameter selection read by manuscript.qmd. Reference-side loss is about 0.31 s (EN2002c) and 1.24 s (IB4002) of overlapped speech, roughly 0.06 s and 0.99 s after the collar. Expected DER shift is 1e-5 to 5e-4 on one meeting per split, which shows at the 6-decimal precision. Direction: the denominator shrinks, and whether DER goes up or down depends on the hypothesis. The hypothesis-side frequency is unmeasured because hypotheses are not saved.

### EDER-03: --segmentation-model silently has no effect: the replacement weights go to an attribute inference never reads

`evaluation/benchmark_der.py:273` · BLOCKING · HIGH-RISK · changes numbers · verified confirmed, panel upheld

**Status.** Resolved. 8ed667a, which landed before this file was written (a387654), rebuilds the pipeline's segmentation Inference (pipe._segmentation) from the checkpoint the way SpeakerDiarization builds it, and stops the run when the checkpoint fails to load, when its output kind or frame resolution differs from the released model's, or when the swap does not stick. tests/test_audit_der_segmentation_swap.py covers these cases. No committed result used --segmentation-model, so nothing needs regenerating.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** `python -m evaluation.benchmark_der --segmentation-model /path/best.ckpt` (or finetune Phase 3 once it runs) loads the checkpoint, prints 'segmentation weights replaced', diarises with the stock segmentation-3.0 weights, and writes a der_summary.json labelled with the fine-tuned model. The resulting 'fine-tuned' DER equals the baseline and would be read as 'fine-tuning does not help'. This is the outcome the error message at 278-280 says it prevents.

**Proposed fix.** As proposed, but also check the powerset/specifications match. Assign `pipe._segmentation.model = fine_tuned` (with .eval() on the pipeline device), assert identity, and check that `fine_tuned.specifications` equals the original's (duration, powerset classes), otherwise raise. Remove the segmentation_model branch. Add a fake-pipeline test that has both attributes.

**Committed results affected.** None committed. No DER json has a segmentation_model key, and the manuscript makes no claim about pyannote fine-tuning. Any future --segmentation-model / SEGMENTATION_MODEL / finetune Phase 3 run would report stock-model DER labelled as fine-tuned.

### ESTATS-01: Disfluency reference recall is scored against the condition-transformed reference, and conditions are aggregated over different utterance sets

`evaluation/disfluency.py:216` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. a986262 scores reference recall for every condition against the transcriber's reference, d359c55 and a6dd82f rescore filler preservation from the re-run sweep's AMI dump (ARC job 8917985), and e7dadbd and 9732ac0 report each condition over its own utterances, with n_utterances_dropped (990 for whisper_norm) and the shared 11,653-utterance set beside them. The whisper_norm row moved from 58 reference fillers and 12.1% recall to 3,066 and 0.0%, and raw and pipeline_full from 804 of 4,084 (19.69%) to 802 of 4,072 (19.70%). b2cf23c (merged in 0e90917) rewrites tbl-disfluency, its caption and the prose around it for the rescored summary (manuscript.qmd:3125-3289 at e515421): each row is scored over the utterances its condition keeps, recall always against the reference as the transcriber wrote it, and the caption says so.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** For any apply_to_reference condition, the denominator becomes the fillers that survived normalising the reference: 58, where the transcriber recorded 4,084. The published table therefore shows 12.1% 'reference recall' for the Whisper normaliser, and that number means something different from the 19.7% two rows above it. Retention for whisper_norm (2.2%, manuscript:1489-1490) is computed over the 364 fillers left in the 11,653 surviving utterances, not over the 1,203 the model emitted. The per-row figures look plausible and are not comparable across rows.

**Proposed fix.** No new dump column and no re-decoding are needed. The dump already holds the untransformed reference in each uid's raw row, and in its pipeline_full row, since that condition has apply_to_reference=False. In score_dump, first build {uid: reference} from rows of a condition with apply_to_reference=False, then score reference_recall for every condition against that reference. Emit reference_recall=None if no such row exists. Keep the per-condition utterance sets, since the manuscript deliberately reports the discard, but add n_utterances_dropped relative to raw. Re-run only `python -m evaluation.disfluency` (CPU) on the existing ARC dump wer_hypotheses_ami.csv, then update the whisper_norm row of tbl-disfluency with maintainer sign-off. Fix the TestScoreDump fixture to write the transformed reference, as benchmark_wer does.

**Committed results affected.** output/evaluation/disfluency_summary.json and disfluency_report.csv, whisper_norm row (reference_fillers 58, reference_recovered 7, reference_recall 0.1207). manuscript.qmd tbl-disfluency (1518-1537): the 'Whisper normaliser' row's Reference fillers (58) and Reference recall (12.1%) cells, under a caption (1520) that defines recall over 'the fillers the human transcriber recorded'. The raw and pipeline_full rows and the prose at 1434-1456 and 2781 are unaffected, because pipeline_full has apply_to_reference=False. The whisper_norm retention of 2.2% (1490) does not depend on the reference, and its smaller utterance set is disclosed at 1495-1507.

### ESTATS-02: Timestamp benchmark silently drops a final chunk with no end timestamp, reading it as a truncation or skipping the utterance

`evaluation/benchmark_timestamps.py:201` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified plausible, panel upheld

**Status.** Resolved. a36b1d4 excludes an untimed final chunk from the boundary metrics instead of reading it as a truncation, and writes every skipped utterance with its reason to timestamp_skipped.csv, with skip_reasons and n_missing_end_timestamp in the summary. The re-run at 6f9bf56 (ARC job 8917980, 567cfd9) found that the one untimed tail, AMI_EN2002a_H01_FEO070_0147251_0147568 (its reference is "YEAH" and Whisper wrote "ha" 222 times, d7b7df9), is the only chunk of its utterance, which the old code had already skipped as its single n_skipped. No committed figure moved: truncation_rate is still 0.0822 (41 of 499), and the median and 90th-percentile end errors are now computed from unrounded errors, the same 10 and 150 ms. TestTimestampSkipped in tests/test_benchmark_results.py checks the skip file against the summary.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** An utterance whose last segment is decoded without an end token has text that the model did emit. The filter throws that chunk away. If earlier chunks exist, pred_end becomes the previous chunk's end, so end_error is large and positive and the row counts toward truncation_rate as though the model stopped early. If it was the only chunk, the utterance is silently skipped, which biases the scored sample. The logs bound this to about one utterance per 500-utterance run, probably the single n_skipped. So the committed 8.2% moves by at most about 0.2 percentage points. The code cannot distinguish the two causes, though, and a model or corpus that omits end tokens more often would inflate the reported truncation rate without any sign.

**Proposed fix.** As proposed, but do not impute pred_end as the clip duration by default, since that would bias end error toward zero. Flag rows whose final chunk end is None, exclude them from the boundary metrics, and record n_missing_end_timestamp and the skip reason in the summary, plus a has_untimed_tail column in the report. Before regenerating anything, read logs/benchmark_timestamps_7737896.err on ARC to identify which audio_id triggered the warning and whether it is the skipped row. If it is, no committed number changes.

**Committed results affected.** Potentially output/evaluation/timestamp_summary.json and timestamp_report.csv (truncation_rate and gross_end_error_rate 0.0822 = 41/499, mae_end, rmse_end) and manuscript.qmd 2155-2174 and tbl-ts-summary (2232-2245). Bounded by at most one utterance per run.

### EPRIV-02: McAdams OLA divides by a near-zero window weight on the last frame, and the ringing it amplifies sets the RMS gain for the whole file

`voice_anonymisation.py:218` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 9bee687 pads the signal with a frame of zeros at each end before overlap-add, so every sample is divided by at least 0.5, and computes the loudness gain over fully overlapped samples (tests/test_voice_anonymisation.py), and 16c1298 reports level_ratio_body, n_knee_compressed_samples and a per-utterance level ratio. The re-run at 6f9bf56 (8b6144c, ARC jobs 8917989 and 8917988) moved the whole-file level ratio from 0.976 to 0.986 (job 8573363) to 0.9975 to 0.9995 in the committed multi-meeting run and 1.0 in the single-meeting run. 0565bbb (merged in 0e90917) rewrites the anonymisation section for that run: the level ratio prints once, the one value it takes at every setting, followed by how much quieter single utterances come back in the meetings where the limiter compressed samples (manuscript.qmd:5140-5158 at e515421). Both jobs loaded the embedding model directly because of NEW-INC-01, and the section says so and cites job 8976304, which found the two routes give identical embeddings (5080-5085), so the author may accept the run as made or have it repeated through the pipeline.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Any input whose final 20 ms frame contains voiced speech (a clip cut mid-word, an utterance segment ending on a vowel, a CLI user's file) comes back several times quieter, with a click at the end. This is the same defect 5f1a3ea claims to have fixed, reached through RMS instead of peak. The benchmark's level_ratio (committed at 0.976-0.986) is a whole-file RMS that includes the knee-compressed transient's energy, so it can partly hide the attenuation of the speech body. The committed AMI numbers may be only mildly affected, but that cannot be confirmed without re-running on AMI.

**Proposed fix.** Pad the signal by `frame` samples (two hops, which keeps the frame grid) at both ends, with zeros or reflect padding, and trim after overlap-add, so every real sample has weight >= 0.5. Compute the loudness gain over fully overlapped samples only. Fix the comment at 215-217 and the docstring at 155-157. Add a regression test whose last frame is voiced, asserting body RMS within 1 dB of the input. Re-run the anonymisation benchmark to a separate path and compare before promoting. Add a body-only level check or a count of knee-compressed samples to the summary.

**Committed results affected.** output/evaluation/anonymisation_summary.json and anonymisation_report.csv (level_ratio, wer_anonymised, linkage for any affected utterance); manuscript tbl-anonymisation / sec-anonymisation. Upper bound from level_ratio: a few per cent of utterances; direction is quieter output for those utterances.

### EPRIV-04: Linkage chance level is 1/distinct speakers, and speakers with a single utterance are counted as trials that can never succeed

`evaluation/benchmark_anonymisation.py:109` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 05ebce8 computes chance as the mean, over the scored probes, of the share of each probe's candidates that are its own speaker, excludes probes whose speaker has no other candidate (n_singleton_excluded) and reports the untransformed rate as linkage_ceiling, with tests in tests/test_s1_anon_linkage.py. The re-run (8b6144c, ARC job 8917989) is the first committed result under the corrected rule: chance 0.1411 over all candidates (399 trials, one singleton excluded), 0.6305 within meetings and 0.1101 across meetings, which tests/test_anonymisation_results.py recomputes from the report labels. 0565bbb and b6236f0 (merged in 0e90917) rewrite the anonymisation section and the Discussion for that run, and the limits paragraph now gives the within-meeting chance of 63% as the reason a comparison confined to one meeting would be a weak test (manuscript.qmd:5212-5226 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Per-meeting sample in which one speaker contributes 9 of 10 utterances in a meeting and another 1: reported chance 0.5, true random-neighbour chance (9*8+0)/(10*9)=0.8. A transform that fully anonymises then shows 'linkage 0.8 vs chance 0.5' and looks like re-identification. Conversely, many singleton speakers deflate linkage (their trials are forced failures) and make McAdams look more protective than it is.

**Proposed fix.** Compute chance as sum_s n_s(n_s-1)/(n(n-1)) over the candidate set actually searched. If candidates are later restricted (EPRIV-15), compute it over that restricted set. Exclude trials whose speaker has no other candidate and report n_singleton_excluded. Report original-vs-original linkage as a ceiling. Update the test at 81-85, the docstrings and CLI help, and the manuscript caption wording.

**Committed results affected.** anonymisation_summary.json 'chance' (0.25 vs correct 0.2495, negligible; manuscript %.2f value unchanged). Material for the pending multi-meeting anonymisation run.

### EPRIV-10: Capitalisation gate reads the raw token's first character, so any name preceded by a quote, bracket or dash is never masked, and the benchmark does not probe this

`transcription.py:635` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. c5f85f4 makes the capitalisation gate and the title lookahead read the token's own first letter, so names after a quote, a bracket or a dash are masked (tests/test_s1_txt_masking.py::test_punctuation_before_a_name_does_not_hide_it), and audio_redaction inherits the fix because it passes each word through the same masker. 04c01b3 adds quoted and bracketed carriers to benchmark_masking, and a08265c regenerated the four arms with them: in the dictionary arm each new position (388 cases) scores the arm's overall recall, 0.3505. 70926fa qualified the manuscript's "if and only if", and 33acbc5 and 381253a (merged in 0e90917) check the masking design sentence and section against the regenerated summaries, which a check in load-masking holds position by position (manuscript.qmd:4429-4455 and 4551-4598 at e515421).

**Why deferred.** The complete fix would change a committed number or artefact. The gate itself is fixed (c5f85f4). Only the manuscript's 'if and only if' description of the gate remains to qualify, which needs the author.

**Failure scenario.** Reported speech in a transcript: `She said, "Aaron, can you hear me?"` or `(Aaron was late)`. The dictionary name Aaron is left verbatim in the .txt/.docx, in the _redacted JSON/VTT, and (via audio_redaction's per-word call) in the audio. The benchmark's leakage figure cannot register this leak.

**Proposed fix.** As proposed: test capitalisation on the first letter (m = re.search(r'[^\W\d_]', word); is_capitalized = bool(m) and m.group().isupper()), and do the same for next_is_capitalized. Add quoted and bracketed morphologies to benchmark_masking as new cells. Qualify the manuscript's if-and-only-if statement.

**Committed results affected.** Manuscript claim at manuscript.qmd:2315-2316 and 2885-2886 (needs qualifying); masking_summary*.json unchanged since benchmark never probes punctuation-prefixed names.

### SHELL-01: GPU jobs reinstall an unpinned CUDA torch into the shared results environment at run time, and no committed artefact records which torch, transformers, CUDA or GPU produced the WER matrix

`hpc/submit_sweep.sh:104` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. No job installs or reinstalls packages any more: 53254ff and ea0ddd3 replace the self-heal with a preflight gate that exits 2, 76d9489 moves the anonymisation job onto the same helper, and the retired legacy scripts exit 1 before running. Each result job records pip list and nvidia-smi beside its results (ee2cc14), each new summary records the torch, transformers, CUDA, cuDNN and GPU it ran on (66be1de, fa6bf45), and the headline wer_summary.json (e3cb675) records torch 2.5.1+cu121, transformers 4.57.1, CUDA 12.1 and a Tesla V100-PCIE-32GB. The final ledger (e3e436d) names the board of every GPU job, V100 PCIe for sweep 8917985 and L40S for 8917986 and 8917987, and the manuscript's Methods now say so (b3c5717, 3302975). The 6 October 2026 recovery makes all 255 original summaries locally verifiable. tools/extract_sweep_decode_provenance.py now publishes their recorded model/dataset revisions, decode and package environment in output/evaluation/sweep_decode_provenance.json, without corpus text or private deployment locators. Every source hash matches both receipts, all seventeen conditions share each of the fifteen recorded profiles, and independent comparison verifies every extracted field and type. Full text-input publication remains the separate REGEN-05 availability gap.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The next sweep is `sbatch --array=0-4 hpc/submit_sweep.sh` against the current CPU-torch environment. All five tasks start together, each fails preflight, and each runs pip uninstall and force-reinstall into $DATA/speech_transcription_env at the same moment. One task imports torch while another has just deleted it and crashes. The survivors run on whatever the cu121 index serves today (2.5.1), with freshly upgraded numpy and sympy, and with torchaudio gone, which breaks pyannote.audio 3.4.0 for the next DER or anonymisation job. The torch, CUDA and GPU behind the committed matrix are recorded nowhere in the repository, so the desktop-versus-cluster reproducibility claim compares against an unknown stack.

**Proposed fix.** As proposed (lock file, no in-job reinstall, per-summary torch/transformers/CUDA/device fields, per-job pip freeze and nvidia-smi records). Additions: extend arc_job_ledger.csv to 8688725/8708134/8708135, or recover their GPU from sacct, and qualify manuscript.qmd:606-609 until then. Recover the versions from the job logs before the environment is rebuilt, because once rebuilt the current environment no longer shows what ran.

**Committed results affected.** Provenance of output/evaluation/sweep_aggregate.csv (post-fix jobs 8688725/8708134/8708135), wer_summary.json and timestamp_summary.json. No number is shown to have moved. manuscript.qmd:593-609 environment paragraph: floors only, and the claim that the ledger's A100 covers 'the condition sweep included' is stale for the post-fix matrix.

### SHELL-02: aggregate_sweep.sh defaults to the shared evaluation directory that every other job writes into; sweep_aggregate searches it recursively without de-duplication and mislabels multilingual and disfluency summaries as sweep cells

`hpc/aggregate_sweep.sh:60` · BLOCKING · HIGH-RISK · changes numbers · verified confirmed, panel upheld

**Status.** Resolved. hpc/aggregate_sweep.sh no longer aggregates the shared evaluation directory: ea0ddd3 pointed SWEEP_DIR at the post-fix sweep and 2e36bf9 at the re-run's own directory (audit2026/sweep), and a missing directory fails (tests/test_s1_env_jobs.py, test_aggregate_defaults_to_the_committed_sweep and test_aggregate_of_a_missing_directory_fails). Wherever it is pointed, sweep_aggregate refuses repeated cells (6cd70c7, tests/test_audit_eval_sweep.py::test_a_duplicate_cell_is_refused), skips summaries of corpora outside the sweep with a warning (4a6256b) and takes pipeline_version from each summary's recorded commit (66959fd). The committed 255-row aggregate rebuilds from the fetched copies of the 255 summaries it records, identical up to line endings (checked locally on 2026-10-04, see EWER-02). 8a72580 moved the plan's wer_sweep stage off postfix/, giving audit2026/sweep as its done_when path with min_count 255. e7f7635 gives the stage a proceed step that rebuilds the committed aggregate there from a clone at f2578b8 with no PIPELINE_VERSION, so following the plan, like the job's default, aggregates the re-run sweep alone.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Following the plan's proceed step, or the usage line `sbatch hpc/aggregate_sweep.sh`, aggregates the canonical ARC directory. For whisper-large-v3 the output then has: pre-fix and post-fix copies of all 80 cells (canonical plus postfix/); fleurs raw and pipeline_full rows carrying French, German, Spanish, Italian, Dutch and Polish WER under the English FLEURS suite; and a second ami raw/pipeline_full/whisper_norm row from the disfluency run. The job exits 0. R code that groups by suite, model and condition then averages or picks among the duplicates, giving plausible but wrong table cells.

**Proposed fix.** As proposed. Also restrict aggregation to the sweep's own naming pattern, or to one pipeline-tagged directory. Exclude summaries whose benchmark (dataset, config) is not in _CORPUS_TO_SUITE, instead of falling back to the stem. Raise on duplicate (suite, model_slug, condition). Emit pipeline_version from code, so the committed 240-row file can be rebuilt and diffed.

**Committed results affected.** Any future regeneration of output/evaluation/sweep_aggregate.{csv,json} via the plan's proceed command. The committed 240-row file is unaffected: 0 duplicate (suite, model_slug, condition) keys, 5 English suites only, and source_file paths under C:\tmp\pf2, so it was assembled outside the documented job.

### DEPS-04: No model, dataset or GLiNER revision is pinned, and result artefacts record no revisions, package versions or git commit

`evaluation/benchmark_wer.py:267` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Partly resolved. evaluation/revisions.py (fa6bf45) records the single snapshot of each model and dataset that the ARC cache held, which the evaluation loaders pass as revision= (66be1de, a36b1d4, 37f4e46, 6f9bf56), and GLiNER loads at a pinned revision offline (ad6b74c). The segmentation and embedding models that the diarisation pipeline loads by name take no revision and resolve to the cache's main, so the summaries list them as revisions_not_enforced, and f064a8a tests that every Hub id the code names is pinned or listed with its reason. Benchmark summaries now record their revisions and run_metadata, among them the four DER summaries of the October re-runs (70933b4), and transcription manifests record the Whisper and diarisation snapshots they loaded (486783b, 365af36), as the committed case-study manifest does, that of job 9124852 since the re-run of 18 October 2026 (ac08cdc had committed job 8983112's). Since release 2.1.1 the manuscript's software paragraph and README.md say that the diarisation sub-models were not pinned. The two DER sweep selections record only the git commit and the pyannote.audio version, and the proposed check of refs/convert/parquet was not made.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Hub repos are mutable. edinburghcstr/ami, google/fleurs, facebook/voxpopuli and librispeech_asr have had parquet conversions and fixes, and openai/whisper-large-v3 has had generation_config updates. A re-run on a fresh HF cache, or after `huggingface-cli delete-cache`, silently scores different audio or references or decodes with different defaults. The result is a plausible but different WER/DER/masking recall, and no field in any committed summary could reveal the change.

**Proposed fix.** As proposed. When recovering SHAs from $HF_HOME, also read `datasets--*/refs/convert%2Fparquet` (or the refs directory the cache actually holds), because that is what the streaming loads resolve to. Record, not guess, which SHA each committed artefact used. Where that is unrecoverable, state it in the README/manuscript rather than back-filling the result files.

**Committed results affected.** None at present. Future re-runs of the WER sweep, DER, timestamp, anonymisation and NER-masking benchmarks would silently follow any later Hub change.

### DEPS-05: Manuscript's software-environment paragraph makes claims the repo contradicts (requirements.txt 'specifies' the env; preflight runs in every job; results came from release 1.0.0)

`manuscript/manuscript.qmd:594` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 70926fa and the Stage 4 rewrite (0e90917) correct the software paragraph (manuscript.qmd:1602-1653 at e515421): requirements.txt gives floors read inline, and requirements-lock.txt records the cluster environment, taken on 2026-09-26, which the outputs of the jobs run after it, the sweep re-run among them, match package for package. The preflight is said to have run at the head of the jobs behind the sweep, the diarisation, timestamp and anonymisation benchmarks, the determinism check and the last multilingual pass, which d3fb54a and ea7c483 bring into line with the re-runs, and release 1.0.0 is said to predate the evaluation. The Methods and Data availability now cite release 2.0.0, which holds it (DOCS-14, MS-09).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader follows the paper, downloads the Zenodo v1.0.0 archive and installs from requirements.txt. That gets a codebase that predates the 16-condition module, the AMI timeline reconstruction and the post-fix pipeline, on an arbitrary package stack. The committed numbers cannot be reproduced, and the paper points at the wrong artefact. The preflight claim also overstates the safeguards for the DER and timestamp jobs.

**Proposed fix.** As proposed, with maintainer sign-off on the manuscript wording. Also create a git tag for the commit that produced the reported results before minting the new Zenodo version, since the repo currently has no tags. Say whether the DOI cited is the concept DOI or a version DOI.

**Committed results affected.** Manuscript methods and availability text at manuscript.qmd:594-604, :2991-2992, :2999-3004 and :3007-3011, plus CITATION.cff, README.md:371-387, versions.csv and setup.py version. These are claims, not numbers.

### DEPS-06: Silero VAD is loaded via torch.hub from an unpinned GitHub branch with trust_repo=True; a failed load silently yields unrefined results labelled vad_refine=true

`evaluation/benchmark_timestamps.py:101` · BLOCKING · HIGH-RISK · changes numbers · verified confirmed, panel upheld

**Status.** Resolved. a36b1d4 loads Silero VAD from the tag snakers4/silero-vad:v6.2.1, stops the run when --vad-refine was requested but the load fails, records vad_applied and vad_source in the summary, and says in the docstrings and help that the VAD only extends an end. The re-run at 6f9bf56 (ARC job 8917981, 567cfd9) loaded that tag, applied it with no VAD exception and reproduced the earlier VAD run (job 7746221) row for row. 567cfd9 also records that the untagged snapshot job 7746221 loaded, a clone of the silero-vad repository at its commit 980b17e, has the same model files as v6.2.1. tests/test_benchmark_results.py pins vad_source and checks the refinement against the plain run (TestVadRefineAgainstPlain).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** (a) On first run torch.hub downloads whatever snakers4/silero-vad master holds (the v4 to v5 models differ in behaviour) and executes its hubconf.py unreviewed, inside a job that has HF_TOKEN in its environment. The refined boundaries depend on an unrecorded snapshot. (b) On a compute node without internet and without a warm cache, the load throws, the job completes, and it writes unrefined boundaries to evaluation_vad_refine with `"vad_refine": true`. That is a plausible-looking wrong label.

**Proposed fix.** As proposed: pin `snakers4/silero-vad:v5.1.2`, or the silero-vad PyPI package. Record `vad_applied = vad_model is not None` plus the silero tag, and exit non-zero when --vad-refine was requested but loading failed. Fix both docstrings and the help text to say that VAD only extends the end boundary. Leave the committed summary as it is (its numbers show refinement was applied), or annotate it only with sign-off.

**Committed results affected.** None reported. output/evaluation_vad_refine/timestamp_summary.json was correctly refined, and the manuscript does not use it.

### XREF-01: Unreferenced legacy WER scripts write to the manuscript's canonical result paths, and the manuscript never checks that the summary covers the full split

`hpc/submit_benchmark_wer.sh:105` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. ea0ddd3 retires the two legacy benchmark scripts, makes a limited sweep require its own output directory, and keeps transcript evaluation away from the canonical benchmark paths. 63be123 requires explicit benchmark report and summary paths. The committed headline pair is tied to the sweep's raw cell and its recorded digest by tests/test_headline_wer.py. The manuscript checks the summary's corpus, split, model and condition, its utterance count against the interval's, and its macro WER against the grid's cell, and that wer_report.csv is identical to the sweep's raw report. On 6 October 2026, evaluation.benchmark_wer also gained benchmark.limit: it records the requested cap, including null for an uncapped stream, separately from the actual n_streamed. Tests exercise a capped stream shorter than the requested limit and an uncapped stream, for two conditions. Existing summaries retain their original metadata and values.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Someone follows the script's own sanity-check advice (`BENCHMARK_LIMIT=200 sbatch hpc/submit_benchmark_wer.sh`), or re-runs submit_benchmark_wer_gpu.sh. The ARC canonical wer_summary.json becomes a 200-utterance summary, or the raw/repetition_fix/whisper_norm cells of the sweep matrix are overwritten at a different code version while the other 13 conditions stay. After the usual fetch, the manuscript renders the headline macro WER from 200 utterances with no warning, and aggregate_sweep.sh silently mixes provenance across conditions. This class of silent collision has already cost a hypothesis dump (.hpc-plan.yaml wer_sweep notes, fixed in 25068a8/f023ddb).

**Proposed fix.** Retiring submit_benchmark_wer.sh and submit_benchmark_wer_gpu.sh (to hpc/legacy/ or deleted) is right. submit_benchmark_wer_cpu_full.sh and submit_pilot_benchmark.sh write non-canonical paths (wer_summary_cpu_full.json, pilot/), so they are dead code, not a collision risk. Give hpc/evaluate_wer.sh a non-canonical default output dir, since it is the documented route to the same file. Have benchmark_wer/sweep write the limit into benchmark.limit, and refuse to write canonical paths when --limit is set unless --output-dir is given. In manuscript.qmd, check the utterance count against a value derived from the data rather than a literal: stopifnot(wer_summary$benchmark$utterances == mw_n('whisper-large-v3','librispeech_clean','raw')), or at least check it against the split size recorded by the sweep aggregate. Manuscript edit needs sign-off.

**Committed results affected.** Latent only: manuscript.qmd tbl-corpus-summary (:715-729, rows 'Utterances scored', macro/micro WER), inline headline macro WER at :998, perfile-dispersion (:743, reads wer_report.csv), wer_ci.csv if bootstrap_ci is re-run on the overwritten report; sweep_aggregate cells for large-v3 LibriSpeech raw/repetition_fix/whisper_norm and challenge-suite raw/whisper_norm if submit_benchmark_wer_gpu.sh is re-run into the canonical directory. No committed number is currently wrong.

### OUTPUTS-01: Appendix B says the reported English sweep predates the Unicode and language-gate repairs, and reads the superseded pre-fix reports; the reported sweep is the post-fix re-run

`manuscript/manuscript.qmd:3116` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 70926fa rewrote Appendix B for the post-fix sweep: it no longer says the sweep predates the repairs, drops the -0.0003 figure, the bound and the typed fallbacks, describes the strip as it now is, and counts the test-clean utterances the strip touches from sweep_reports_postfix/ joined by utterance id. The same commit corrected the Limitations and selection paragraphs (MS-04, MS-02). The re-run (2e36bf9) regenerated those reports, so the count is now none of 2,620 (two before), and the stage's paired effect in @sec-wer is 0.0 (9cb43e3). 4ae5710 (merged in 0e90917) rewrote the appendix for the re-run and removed the PHASE2 note that asked for that repointing (manuscript.qmd:6173-6229 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Rendered Appendix B tells readers that every reported English WER predates two repairs and that unicode_strip moves WER by −0.0003. @sec-wer in the same paper reports +0.01 pp [0.00, +0.01] for that stage from the post-fix intervals. A reviewer sees two opposite-signed effects for one stage and a false statement about which code produced the headline numbers. The '6 of 2,620' bound is also computed from the superseded pre-fix per-utterance reports.

**Proposed fix.** The finding's fix is right but covers too little. It also needs: (a) :3141-3143, which describe the diacritic-stripping form as the one the sweep scored; (b) :1148-1160, which say only seven per-utterance reports survived, when cci now has 15 rows from 16 reports; (c) the inline fallbacks at :3125-3129 ('6', '2,620', '0.0004'). Either repoint the chunk at sweep_reports_postfix, which gives 2 utterances and 0.0001, or label the bound explicitly as the pre-fix prediction that the re-run confirmed. Rewording the Appendix B paragraph needs author sign-off.

**Committed results affected.** Rendered Appendix B at manuscript.qmd:3090-3096, 3116-3136 and 3141-3143 (the '6 of 2,620' touched count, the 0.0004 bound, and the hard-coded -0.0003 against a baseline of 0.0621 for unicode_strip). The same stale claim is also in the Limitations paragraph at :2911-2921 and in the R comment at :202-205. None of these changes a table or the WER grid. They misstate which pipeline produced sweep_aggregate.csv and condition_ci_postfix.csv, and they give a unicode_strip effect of the opposite sign to the one @sec-wer reports at :1120.

### OUTPUTS-02: The documented command for condition_ci_postfix.csv omits --output, so it overwrites the retained pre-fix condition_ci.csv, which the manuscript prints as the pre-repair cost

`manuscript/manuscript.qmd:1009` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. c03c37f makes condition_ci's --output required, so the documented command can no longer overwrite condition_ci.csv (unchanged since 642e4dd), and corrects the CLI docstring. The manuscript names --reports output/evaluation/sweep_reports_postfix with --output output/evaluation/condition_ci_postfix.csv as the source of @tbl-condition-ci, in the chunk comment and in Data availability, and keeps the sweep_reports command as history, and since e3cb675 the bootstrap_ci baseline, wer_report.csv, is the same file as sweep_reports_postfix/wer_report.csv. 687555a (merged in 0e90917) replaces the Data availability sentence about running without --output and drops the PHASE2 note (manuscript.qmd:5987-6009 at e515421). The 2026-10-06 follow-up corrects the remaining chunk comment: it now states that an explicit output path is required, instead of describing a default that does not exist (the stale sentence was at 2266-2269 in e515421; see REGEN-01).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A maintainer refreshes the post-fix intervals by running the comment verbatim. condition_ci.csv is overwritten with post-fix values (contraction_fix delta 0.0 [0.0, 0.0]; pipeline_full +0.00009). The next render prints the pre-repair cost as "+0.00 percentage points, 95% CI [+0.00, +0.00]" inside prose describing a +0.43 pp defect. No error is raised, and condition_ci_postfix.csv silently stays at its old contents.

**Proposed fix.** Everything in the proposed fix, plus correcting the Data availability text at :3013-3023, which is rendered and needs author sign-off. It should name --reports output/evaluation/sweep_reports_postfix with --output output/evaluation/condition_ci_postfix.csv as the source of @tbl-condition-ci, keep the sweep_reports command as the pre-fix history, and name sweep_reports_postfix/wer_report.csv as the baseline in place of the May wer_report.csv (see OUTPUTS-03). Changing the default --output in condition_ci.py changes nothing already computed, but the CLI docstring at :26-29 should change with it.

**Committed results affected.** output/evaluation/condition_ci.csv (feeds cci_pre_fmt('pipeline_full') and cci_pre_fmt('contraction_fix') at manuscript.qmd:1128/1130, and boot_b at :158), and the rendered Data availability recipe at :3013-3023, which names @tbl-condition-ci (drawn from condition_ci_postfix.csv, 15 rows).

### DOCS-14: No CHANGELOG, and versions.csv and CITATION.cff still say 1.0.0 after 202 commits that include result-changing fixes

`versions.csv:2` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. CHANGELOG.md records the audit and re-run changes, and now also identifies the earlier result-affecting fixes f6e708e, c0f58c5, c83162f, af3bee0, 5f1a3ea, f7c85b0, 25068a8 and f023ddb. Transcript stamps carry the release and source commit (5b15a6a). The release order below was corrected on 6 October 2026 to reserve the new DOI before freezing the cited source tree, and release 2.0.0 followed it. On 17 October 2026 the version DOI 10.5281/zenodo.23442766 was reserved in the existing record family (concept DOI 10.5281/zenodo.17592924) and the DOI 10.5281/zenodo.23442874 in a separate data record for the inputs, and the two drafts were cross-linked. versions.csv, CITATION.cff, setup.py, the README citation and the changelog's heading then gave 2.0.0, dated 18 October 2026, and the new DOI, before the tree was frozen and tagged v2.0.0. The author settled the licence scope and the dictionary's rights the same day (DOCS-16, G3). docs/release_readiness.md records the archives and their digests; the author publishes the two records from this tree. Release 2.1.0 (30 October 2026) followed the same order: the version moved in setup.py, CITATION.cff, versions.csv, the software reference and the README together (34fca36), the example variants were restamped (3c13116), and docs/release_readiness.md records its checks and the rebuilt input deposit (fa45a403..., README only, for CR-06).

**Release checklist.** The steps left to the author, written on 2026-10-04 at fb22ece and rewritten on 2026-10-06 (41fe712):

Settle the licence scope and dictionary rights first, and finish the reviewed content. Version 2.0.0 remains the proposal under semantic versioning: `--single-file` was removed from `transcription.py` in 0eaa742, and `--report-postprocessed` and `--summary-postprocessed` were removed from `evaluation.benchmark_wer` in 66be1de. The repaired text stages also change transcripts. No version or date should be labelled released before the final tree is ready.

Create an unpublished new-version draft under concept DOI `10.5281/zenodo.17592924` and reserve its version DOI before the source tree is frozen. The currently cited `10.5281/zenodo.17624830` identifies the historic v1.0.0 archive. Zenodo's DOI reservation procedure permits a reserved DOI to be included in files before they are uploaded. The new-version draft needs access to the author's record; no new DOI has been invented or reserved locally.

Update the version and release date together in `versions.csv`, `CITATION.cff`, `setup.py` and `CHANGELOG.md`. `CITATION.cff` gives `date-released` 2025-11-12, whereas Zenodo published the cited v1.0.0 record on 2025-11-16, the date `references.bib` uses (Zenodo API, 2026-10-04), so take the new release's date from the record actually published. Carry the reserved version DOI into the `doi` and `url` fields of `CITATION.cff`, both still 10.5281/zenodo.17624830, into the software record `bernabeuSecureScalableSpeech2025` in `manuscript/references.bib`, into the README's badge and citation, and into the places the manuscript's two PHASE2 notes mark. The availability statements currently say that the cited archive predates the evaluation; revise that wording only for an archive containing the evaluated materials. Check any `.zenodo.json` against the citation file, because Zenodo gives the JSON priority.

Run the required tests, gate and renders, then freeze the final source commit and tag that exact tree. Prepare the archive from it with the reviewed inputs and attribution notices, and record the commit, tree, input digests and archive SHA-256 in a detached manifest. Publish the exact reviewed file, download it again and verify its digest. A source ZIP alone does not make the recovered sweep inputs available unless they are included or linked through a separate versioned data deposit. `docs/release_readiness.md` gives the primary Zenodo guidance and the full inventory.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Someone downloads Zenodo 1.0.0 as cited and runs it on French or German audio. Diacritics are deleted, and 'were' becomes 'we're' in English, with no changelog to warn them. A reader can't tell which version produced the post-fix sweep the manuscript reports.

**Proposed fix.** Add CHANGELOG.md listing every result-affecting fix with its commit (f6e708e, c0f58c5/c83162f, af3bee0, 5f1a3ea, f7c85b0, 25068a8/f023ddb, among others). Bump the version in setup.py, CITATION.cff and versions.csv (or retire versions.csv), tag the commit that produced the committed outputs, and archive it as a new Zenodo version. With maintainer sign-off, change manuscript.qmd:603-604 to cite that new version or tag and its DOI in place of 1.0.0, and give the new release date in CITATION.cff.

**Committed results affected.** No computed number changes. What is wrong is the manuscript's provenance and availability claims for every reported result: manuscript.qmd:603-604 (the results were produced by release 1.0.0), manuscript.qmd:2991-2992 (archived release) and manuscript.qmd:2999-3008 (the evaluation module, Slurm scripts and manuscript source are archived at the DOI, and the WER can be reproduced with sbatch hpc/submit_sweep.sh). The same citation appears in CITATION.cff:8-11, versions.csv:2, setup.py:17 and README.md:375/385.

### MS-01: Multiplicity paragraph calls a +0.00, p = 1.000 contraction repair 'well clear of zero'

`manuscript/manuscript.qmd:1176` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 8e1b7ff (merged in 0e90917) rewrites the multiplicity paragraph for the regenerated intervals (manuscript.qmd:2525-2555 at e515421). The rows that exclude zero are now the canonical normaliser, the deduplication window and filler removal, each with its p value read inline, and every other row, the contraction repair and the whole production layer among them, is an exact null with p = 1.000. The paragraph on @fig-conditions no longer credits the repaired stage with the composite's excess and gives its cost before the repair as history, from the preserved pre-fix aggregate (2177-2233), and the pre-repair intervals are quoted from condition_ci.csv (2480-2497). Checks in load-condition-ci stop the render if the rows stop bearing these sentences out (2345-2382).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The current committed artefacts render: "the contraction repair at +0.00 percentage points, p = 1.000, both sit well clear of zero and would clear a Bonferroni threshold". That is a self-contradictory statistical claim in the submitted paper.

**Proposed fix.** Rewrite the multiplicity sentence for the post-fix table. Either name the effects that clear Bonferroni from cci (whisper_norm, and dedup_window with p < .0002) or quote the pre-repair contraction effect through cci_pre, explicitly as history. Add stopifnot(all(cci$excludes_zero[cci$condition %in% named] == 1)). Fix the same staleness at lines 936-938 in the same pass.

**Committed results affected.** Section 4.1 multiplicity paragraph (qmd 1170-1180) and fig-conditions paragraph (qmd 930-938); @tbl-condition-ci interpretation.

### MS-02: Selection paragraph still describes the pre-fix six-row CI table ('only seven reports', 'three of five')

`manuscript/manuscript.qmd:1151` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 8e1b7ff (merged in 0e90917) rewrites the selection paragraph (manuscript.qmd:2516-2523 at e515421): every condition the sweep scored kept its report, so all sixteen non-baseline conditions are paired, which a check against the aggregate holds (2398), and the seven-report limitation is kept for the first sweep's intervals alone. The count of production stages that move the score is now said in words from the rows: none does, each having an interval of zero width and a difference of zero (2468-2478), and a check holds that to the table (2371-2382).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The current render reads "only seven such reports were kept from the sweep, the raw baseline together with `case_fold`, `common_phrase_fix`, ... and `whitespace_normalise`", listing fifteen conditions after the word seven. It then says the other conditions' reports were not retained, and that three of five production conditions move the score, when one of ten does.

**Proposed fix.** Rewrite the selection paragraph around the post-fix table: nrow(cci) + 1 reports, every registered condition paired, and the survival narrative dropped or attributed only to the pre-fix cci_pre. Compute the production count inline with sum(condition_layer(cci$condition) %in% c("Production atomic", "Production composite") & cci$excludes_zero == 1).

**Committed results affected.** Section 4.1 selection paragraph (qmd 1144-1160) describing @tbl-condition-ci.

### MS-04: Limitations paragraph says the English figures still contain the defects and await a re-run

`manuscript/manuscript.qmd:2917` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 70926fa rewrote the Limitations paragraph (manuscript.qmd:3568-3574): the English word error rates come from a sweep run after the contraction repair and both multilingual repairs, at the code its aggregate records, read inline as sweep_version, and the setup chunk stops the render unless sweep_aggregate.csv carries exactly one pipeline_version (339-342). The re-run aggregate (2e36bf9) carries one, 6f9bf56, so the sentence now names the re-run's code.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader or reviewer is told that the reported composite cost measures a defect and that no re-run exists. Section 3.1 says the opposite, and so does the artefact the tables are drawn from.

**Proposed fix.** Rewrite the paragraph to state that the English grid is from the repaired pipeline. Read the version string inline from `unique(sweep_agg$pipeline_version)` and add stopifnot(length(...) == 1) so the claim tracks the artefact.

**Committed results affected.** Discussion/Limitations paragraph (qmd 2911-2921); provenance of all English WER figures and Appendix A.

### MS-05: Appendix B describes the pre-fix sweep and quotes a -0.0003 Unicode-strip change that Appendix A no longer shows

`manuscript/manuscript.qmd:3132` · BLOCKING · HIGH-RISK · changes numbers · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 70926fa rewrote Appendix B for the post-fix sweep: the typed -0.0003, the staleness bound and its fallbacks are gone, the strip is described as it now is, and Appendix A is said to score the repaired contraction stage. The count of test-clean utterances the strip touches is computed from sweep_reports_postfix/ joined by utterance id (MS-17), none of 2,620 since the re-run (2e36bf9). 4ae5710 (merged in 0e90917) rewrites the appendix again for the re-run, and its sentence that the sweep did not score pronoun_i_fix now says that the sweep scores each of the ten steps, the pronoun rule included (manuscript.qmd:6164-6171 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Appendix B tells the reader that Appendix A scores the ASCII-only strip and the unrepaired contraction table, and quotes -0.0003. Appendix A, printed a page earlier, shows 0.0622 against 0.0621 for the repaired stage.

**Proposed fix.** Rewrite Appendix B for the post-fix sweep. Compute the Unicode-strip delta inline from sweep_agg. Either remove the staleness bound, or recast it as a pre/post comparison of sweep_reports/ against sweep_reports_postfix/ joined by `name`.

**Committed results affected.** Appendix B (qmd 3090-3163): the typed -0.0003, the rendered 6-utterance and 0.0004 bound from pre-fix reports, and provenance claims about Appendix A.

### MS-06: Model-scaling prose says the composite costs Whisper Medium 'a little on FLEURS'; post-fix delta is exactly zero

`manuscript/manuscript.qmd:1574` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 2cdcb76 and 3aeb77d (merged in 0e90917) drop the claim that the composite costs Whisper Medium a little on FLEURS, where its delta is exactly zero in the regenerated grid. The model-scaling paragraph now rests the argument that difficulty does not predict where the layer earns its place on test-other, where Medium's raw rate is the higher and the composite lowers it by only 0.001 against 0.020 on test-clean, each computed inline and held by checks (manuscript.qmd:2848-2880 and 2959-2979 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The paper argues that difficulty does not predict where the layer earns its place, citing a FLEURS cost that disappeared once the defect was repaired. The argument's second leg is now unsupported, and the table beside it shows 0.051 in both columns.

**Proposed fix.** Compute the medium-FLEURS delta inline, as is already done for med_lsc_gain, and rewrite the argument to match the post-fix values.

**Committed results affected.** Section on model scaling (qmd 1571-1576), adjacent to @tbl-models.

### MS-07: Data-availability recompute command regenerates the pre-fix six-row table, not @tbl-condition-ci

`manuscript/manuscript.qmd:3019` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 70926fa replaced the Data availability recipe: the command behind @tbl-condition-ci reads output/evaluation/sweep_reports_postfix and writes output/evaluation/condition_ci_postfix.csv, and the sweep_reports command is kept, labelled as giving the pre-repair intervals quoted in @sec-wer. 687555a (merged in 0e90917) drops the clause about running without --output, stale since c03c37f made --output required, and says instead that a check is better written to another path and compared with the committed table (manuscript.qmd:5987-6009 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader follows the Data availability section and gets the six-row pre-fix table (pipeline_full +0.40 [0.33, 0.48], contraction_fix +0.43). The paper's table shows fifteen rows with pipeline_full +0.01, so the reproduction appears to fail.

**Proposed fix.** Document the post-fix command (reports in sweep_reports_postfix/, output written to condition_ci_postfix.csv) as the one behind @tbl-condition-ci. Keep the sweep_reports/ command, explicitly labelled as reproducing the pre-repair intervals quoted as history.

**Committed results affected.** Data and code availability section (qmd 3013-3023); reproducibility of @tbl-condition-ci.

### MS-08: 'Exceeds the whole span of the tuning grid' is false against der_sweep_summary.csv

`manuscript/manuscript.qmd:2842` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 70926fa compares the reconstruction effect with what tuning gained, computed inline as der_tune_gain_dev (development split) and der_tune_gain_test (held-out split) and checked by stopifnot, in the Discussion and in the abstract's claims-check, instead of with the span of the grid. The DER artefacts these read are now the October re-runs (70933b4), and the checks hold on them (manuscript.qmd:3871-3922 at e515421). Tuning gained 0.065 of a point on the development split and lost 0.0024 on the test split, against a reconstruction effect of 12.27 points (4120-4134), the same figures as in August at the precision printed.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The Discussion claims the reconstruction effect (12.27 pp) is larger than anything the tuning grid spans. Three paragraphs earlier the paper reports a 33.6 pp span across that grid, so a reviewer can refute the claim from the paper alone.

**Proposed fix.** Compare against the tuning gain, which is the quantity the argument needs (sweep2_default − sw(der_sweep2, 0.7, 0), or der_tuned − der_summary on test). Alternatively compare against the span of the ten-cell refinement grid. Compute it inline and name which quantity is meant.

**Committed results affected.** Discussion paragraph on protocol vs parameters (qmd 2833-2846).

### MS-09: Methods attribute the results to release 1.0.0, which predates and contains the repaired defects

`manuscript/manuscript.qmd:604` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 70926fa removed the claim, and the manuscript then said in the Methods (manuscript.qmd:1646-1649 at e515421), under Code availability (5937-5943) and in Data and code availability (5952-5960) that the archived release, its version read from CITATION.cff, predates the evaluation and produced none of the results. The Methods read the WER grid's commit inline as sweep_version, which the setup chunk requires to be a single value, and the diarisation summaries' as der_commit, and Data and code availability says which other artefacts record their commit. Release 2.0.0 (DOCS-14) holds the evaluation, and the Methods, Code availability, Data and code availability and the Open practices statement now cite it (bernabeuSecureScalableSpeech2026, 10.5281/zenodo.23442766), naming 1.0.0 only as the first release, which predates the evaluation. The two PHASE2 notes that marked those places are gone.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader uses the Zenodo 1.0.0 record to reproduce the WER grid. That code has the seven bad contraction keys and the ASCII-only unicode strip, so pipeline_full costs about +0.40 pp on test-clean and FLEURS ratios reach 8.1, not the +0.01 pp and 1.00 the paper reports.

**Proposed fix.** Before submission, cut a tagged release and Zenodo version after the last committed artefact. Record it in versions.csv and CITATION.cff, and cite that version DOI rather than 1.0.0. In the Methods, read the WER-grid commit inline from unique(sweep_agg$pipeline_version) with a stopifnot on length 1. Also acknowledge that the other artefacts carry their own code commits.

**Committed results affected.** Methods provenance sentence (qmd 603-604); Open practices and Data availability DOI statements (qmd 2991-2992, 3000-3004); CITATION.cff and versions.csv.

### MS-10: Every inline number silently falls back to a typed literal, several already stale, and loaders swallow parse errors

`manuscript/manuscript.qmd:938` · BLOCKING · HIGH-RISK · touches end product · verified confirmed, panel upheld

**Status.** Resolved. 70926fa loads every artefact through one manifest in the setup chunk (manuscript.qmd:63-166), stops the render with the path when a file is missing, does not parse cleanly, has no rows or lacks a field the text quotes, removes every typed fallback and error-swallowing tryCatch, and makes the accessors refuse a lookup that finds no row or several. dc8e951 brings manuscript/README.md in line. At f2578b8 the render stopped on checks this fix added (the condition list at manuscript.qmd:494 and the claims-check chunk), because the regenerated artefacts no longer matched the text, which is the loud failure this item asked for. 02079b4 brings the condition list and three claims into line with the artefacts, and its message records that the HTML and PDF renders then complete with no warning.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** If sweep_aggregate.csv fails to parse (e.g. a truncated archive copy or a new column type), `have_sweep`/`have_cd` go FALSE silently. The paper then renders "costs 0.43 points on its own and so accounts for the whole of the composite's 0.40-point excess" followed by "the contraction stage now costs 0.00": pre-fix values presented as current, with Appendix A and the figures dropped and no error.

**Proposed fix.** Add a setup-chunk manifest of required artefacts that calls stop() when any is missing or unparsable. Remove the error-swallowing tryCatch wrappers. Replace the literal fallbacks with a visible marker such as "[missing: path]", or remove them. Update the README claim to match.

**Committed results affected.** None of the committed renders. Potentially every inline number if an artefact goes missing or is truncated. manuscript/README.md:25-26 is inaccurate.

### ESTATS-05: Footprint model charges 0 W to any unmapped GPU type, and prices every H100 as the 700 W SXM5 board although the programme used an H100 NVL

`evaluation/footprint.py:246` · BLOCKING · HIGH-RISK · verified confirmed, panel upheld

**Status.** Resolved. 24975d5 makes a GPU job whose type has no board power a ValueError instead of 0 W, and da8f1ca, a1e7933 and 81d5119 build the ledger from sacct and price each GPU by its node's board, dropping the bare 700 W "h100" entry. The committed ledger (e3e436d) prices the H100 NVL at 400 W, the H100 PCIe at 350 W and the H100 SXM5 at 700 W, and no job carries a bare h100 or a100. footprint_report.csv gives gpu_type and tdp_w for every job, and jobs 7737896 and 7746221 are p100-pcie at 250 W. e3e436d's Findings line omits ESTATS-05, and 19bf267 records that e3e436d resolves it.

**Why deferred.** The complete fix would change a committed number or artefact. An unmapped GPU type now raises instead of costing 0 W, and --gpu-tdp overrides a wattage. The H100 NVL wattage is unchanged because it moves the footprint figures.

**Failure scenario.** Re-capture the ledger to cover the determinism, disfluency and anonymisation jobs. An H100 NVL allocation reported as gres/gpu:h100 is charged 700 W instead of about 400 W, overstating its GPU term by 75%. Any type not in the dict (for example an rtx8000 or l40 variant string) is charged 0 W. The summary then reports a smaller, plausible total with no warning.

**Proposed fix.** Raise ValueError (or, at minimum, collect the types and write them to summary['unmapped_gpu_types'] and exit non-zero) when a GPU job's type is not in gpu_tdp_w. Add an 'h100-nvl' entry at 400 W and document the ARC gres strings that map to it. Write gpu_type and tdp_w per job into footprint_report.csv. Before any refresh, re-derive gpu_type for jobs 7737896 and 7746221 from sacct, because the test docstrings contradict the ledger.

**Committed results affected.** None committed. output/evaluation/arc_job_ledger.csv has 38 rows: 36 with gpu_type=a100 (400 W, a mapped type) and 2 CPU-only rows with gpus=0. footprint_summary.json and tbl-footprint (manuscript 2645-2710) are therefore untouched by the 0 W default and the h100 mapping.

**Diff proposed by the implementer.**

    GPU_TDP_W add "h100-nvl": 400.0; footprint.write_csv add gpu_type and tdp_w columns. Before refreshing the ledger, re-derive gpu_type for jobs 7737896 (P100) and 7746221 (P100) from sacct, then regenerate footprint_report.csv and footprint_summary.json.

## Major (84)

### T1-05: Phrase-repetition count is double-counted, so phrases are collapsed at 5 occurrences instead of the stated lenient threshold, while case-variant loops are never collapsed

`transcription.py:879` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 2c42aa8 counts a phrase's copies case-insensitively with re.findall, reads the shortest repeating unit, keeps the trailing whitespace and cuts a phrase only from its eleventh copy (more than PHRASE_REPETITION_LENIENCY, 2, times max_repetitions), the threshold the docstring and code comment already gave. Tests in tests/test_s1_txt_repetitions.py cover five, ten and eleven copies and a capitalised first copy. In the re-run sweep at 6f9bf56 (2e36bf9), which regenerated repetition_fix and pipeline_full, three of repetition_fix's 15 cells moved. Whisper Medium on AMI went from a macro WER of 0.750855 to 0.750169 (its delta against raw from -261.98 to -262.05 percentage points), and the two VoxPopuli cells moved by at most 0.003 points. The paired intervals were rebuilt from the re-run's reports (9cb43e3), the disfluency figures were rescored from its AMI decode (a6dd82f), and the FLEURS fourth arm shows the composite changing no utterance in any language (56ce519). The manuscript gives the threshold as more than ten repeats (manuscript.qmd:3826-3831, from 70926fa).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A speaker who says 'thank you' five times in a row loses four real repetitions under repetition_fix and pipeline_full, adding deletions against a verbatim reference. A genuine decoding loop that starts with a capital ('Okay so okay so okay so ...') is left intact. The committed repetition_fix and pipeline_full rows were computed with this behaviour.

**Proposed fix.** Count with len(re.findall(re.escape(phrase), full_match, flags=re.IGNORECASE)). Decide the intended phrase threshold with the maintainer: '>10' collapses fewer loops than now, while case-insensitive counting collapses more, so the net WER direction is unknown. Preserve trailing whitespace, e.g. return f"{repeated_phrase} [...] " and let later whitespace normalisation tidy it. Name the sentence-path thresholds (5, 10). Add tests for 5x and 11x phrase loops and for a capitalised first occurrence. Re-run repetition_fix and pipeline_full on all corpora and models after sign-off.

### T1-07: Undocumented length filter silently removes all 23 curated names under three characters (Chinese surnames Li, Wu, Xu, Hu, Yu, Lu; English Al, Ed, Jo), and the benchmark excludes them from recall

`transcription.py:446` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 48337aa exempts the curated dictionary from the three-character rule (filter_problematic_names with drop_short=False), so Li, Wu, Al and the other 20 short curated names are masked, and adds "an" and "AI" to the common-word list, and tests/test_s1_txt_short_names.py guards the masker, including the length rule the Facebook sets keep. dbff14f lets load_in_db_names sample the short names, and a08265c regenerated all four masking arms with this and the other masking fixes (seed 42, 1,940 cases), overall recall staying at 0.3505 for the dictionary and 0.7010 case-insensitively and rising to 0.4737 with NER and 0.9366 with both. The seed-42 sample drew none of the short names, though, its shortest injected name having three letters, so the benchmark does not measure them. The Stage 4 rewrite (381253a, d882fc8, bd5d563) checks the masking prose against the regenerated summaries and says in the load-masking comment that the sample omits the short names (manuscript.qmd:4408-4417 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** An English-language research interview that names a participant 'Li' or 'Wu' leaves the name unmasked with no log row, although the name ships in the dictionary. The benchmark's in-dictionary recall cannot reveal this because those names are removed from the pool before sampling.

**Proposed fix.** Either exempt names explicitly listed in the curated CSV from the length rule, keeping it for Facebook-derived sets only, or keep the rule and document it in filter_problematic_names, README, docs and the manuscript's masking description. If short names become maskable, include them in load_in_db_names so recall reflects them, and re-run the masking benchmark with sign-off. Otherwise state the number of names that can actually be masked.

### T1-14: _undefined_tag misses sentence-final, text-edge and consecutive occurrences and does not implement the pattern the manuscript states

`transcription.py:936` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. a445ebe replaces the four whitespace-anchored substitutions with one whole-word pattern for undefined, undefine, undefin and undefining that skips an already bracketed token, so occurrences at the text edges, before punctuation and in runs are marked and words such as "undefinable" are left alone. An ordinary "undefined" is still marked, as the proposed fix specified and the new docstring says. Tests in tests/test_s1_txt_undefined_tag.py cover each case and idempotence. 70926fa rewrote the manuscript's description (now manuscript.qmd:3838-3843) to these four literals in place of `\bundefin\w*`. In the re-run sweep (2e36bf9) undefined_tag scores exactly as before in all 15 cells, so no committed number moved.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A truncated-word artefact at the end of a sentence ('... the value was undefin.') or two in a row is left unmarked, defeating the stated purpose of drawing the reader's eye to it. Meanwhile an ordinary 'the limit is undefined here' is bracketed. The manuscript describes a different regex from the one that ran.

**Proposed fix.** Lowest-risk option: correct manuscript 3150 to the four literals actually matched (sign-off). If the code changes, use re.sub(r'(?<!\[)\b(?:undefined|undefine|undefin|undefining)\b(?!\])', '[undefined]', text, flags=re.IGNORECASE) instead of \bundefin\w*, so that words like 'undefinable' are left alone. Keep it idempotent, add sentence-final and consecutive tests, and re-run undefined_tag and pipeline_full with sign-off.

### T2-07: enhance_audio's 'dynamic range compression' is a per-sample waveshaper applied after a fixed +11 dB gain, and the noise profile assumes the first 0.5 s is silence

`transcription.py:1452` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. The descriptions are corrected. cfe5736 rewrites the enhance_audio docstring and comments to give the steps in the order the code applies them (the fixed 3.61x gain, +11.2 dB, first), the half-second noise profile assumed to be silent, the static soft-clipping curve and the up to 511 samples lost at the end. 70926fa gives the manuscript's Methods (manuscript.qmd:683-691) the same order and curve. The signal processing is unchanged, as cfe5736 records, because changing it is a versioned behaviour change that would alter the l3_learning example, so a recording that opens with speech still uses speech as its noise profile. On 17 October 2026 the author decided to leave the algorithm unchanged, so the l3_learning example stands. No committed number depends on it: the enhancement is off by default and no benchmark calls it.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A recording that starts with speech, such as a trimmed interview clip, uses speech as its 'noise' profile. Subtracting twice that profile attenuates speech bins by up to 20 dB across the whole file. Normal-level speech is also harmonically distorted by the waveshaper. Whisper still returns a plausible transcript of the degraded audio, with nothing to indicate the enhancement hurt it. Separately, up to 511 samples (32 ms) are dropped from the end.

**Proposed fix.** Correct the manuscript Methods first (order, the +11.2 dB gain, and that the compression step is a static per-sample curve), with sign-off. Treat any algorithm change as a versioned behaviour change: pass n_fft/hop_length explicitly and length=len(audio) to istft, estimate noise from low-energy frames or skip subtraction when the first 0.5 s is not quieter than the median frame, and either implement an envelope-following compressor or rename the step. Document the source of every constant, and record that the l3_learning example predates the change (or regenerate it with maintainer sign-off).

### T3-05: The early-truncation check never runs without --speaker-attribution, because audio duration is only measured inside the diarisation block

`transcription.py:2882` · MAJOR · HIGH-RISK · changes numbers · verified confirmed

**Status.** Resolved. 898bdfe has transcribe_audio_only record audio_duration_s, the length of the audio it has already decoded, and process_audio_file gives that length to the review whenever the speaker path measured none. A --timestamps run without diarisation now checks for early truncation, a run with no known duration says the check could not be made, and speaker labelling keeps its own measurement. Tests in tests/test_s1_txt_truncation.py cover a timestamps-only run and an unknown duration, and README.md says the review is written with --timestamps or --speaker-attribution (c3a3041). No committed number moved, because the committed case-study review came from a --speaker-attribution run.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** `python transcription.py interview.wav --timestamps` (the documented route into audio redaction), where Whisper stops at 40% of the recording. The review JSON has truncation {checked: false}, no warning is printed, and the short transcript is taken as complete.

**Proposed fix.** Measure the duration of audio_file_for_transcription outside the speaker block, for example return len(audio_array)/sr from transcribe_audio_only, which avoids a second decode. Keep the existing `and audio_duration` gate at 3130 behaving the same. Print a warning when the duration is still unknown, and change README.md:226 to say the review is written when --timestamps or --speaker-attribution is active.

### T3-06: The committed case-study review and manifest predate the current timeline repair and review layer

`output/case_study/codex_mentis_ep05_review.json:1` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. ac08cdc replaces the committed review, manifest and podcast_eval_summary.json with those of ARC job 8983112 (2026-10-04, code c4c7b38 with a clean tree, an NVIDIA RTX A6000 on htc-g052), which ran the current timeline repair and review layer. Its review has 405 cues, four high_speech_rate flags, the rate_flags_skipped and redacted keys and a truncation block (2.53 s short of 1,938.87 s, not truncated), and its transcript JSON records timeline_repairs word_retimed 64, segment_overlap_clamped 4 and segment_merged 3. output/case_study/README.md is rewritten from those files and names the producing run and commit, and hpc/runs/case_study.env records the invocation. The "positives." cue was not merged: it lasts 0.02 s in the August run and in both re-runs and ends after its predecessor, so the repair keeps it, and the README says why the review flags it. a3f67c4 corrects two docstrings that told the August story, and 02f4068 makes the job's header and closing hint name the review and manifest among the files a new result commits.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Re-running hpc/submit_case_study.sh at HEAD gives a review with a truncation block and plausibly a different flag set (three crammed cues are merged into one, which the review then flags, while the "positives." cue, 0.02 s long in every run, is kept). It also gives different artefact digests and timeline_repairs counts. A reader checking the archived evidence against the archived code cannot reproduce it.

**Proposed fix.** Needs maintainer sign-off. Re-run hpc/submit_case_study.sh at HEAD, recommit the review, manifest and podcast_eval_summary, and rewrite the README's timeline_repairs figures and third-flag explanation from the new outputs. Until then, add a dated note to output/case_study/README.md naming commit 25c2582 as the producer and listing 4d95124 and ec91a66 as changes the evidence does not reflect.

### EWER-04: pipeline_full is not what ships: it always applies repetition repair, which is off by default in the CLI and GUI, and it is scored on a different decode configuration

`evaluation/conditions.py:224` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. c4f3133 makes pipeline_full call transcription.postprocess_transcript_text with fix_repetitions=True, the function transcription.py runs itself, and describes it as the --fix-spurious-repetitions configuration, not what a default run delivers. tests/test_conditions.py checks it against the production function and checks that a default run differs on a looping hypothesis, and docs/conditions_audit.md (d850f07) and the manuscript (70926fa, manuscript.qmd:2001-2008 at e515421) say the same. The re-run decoded Large v3 and distil-large-v3 in float16 and Whisper Medium in float32, so on a GPU only Medium's decode differs from production in precision, as the pipeline_full notes have said since 26cfcf3 and the Methods now say (ae8a21f, 1580-1587). On 6 October 2026, docs/conditions_audit.md was clarified against both decoders: the benchmark uses checkpoint-native GPU precision (float16 for Large v3 and distil-large-v3, float32 for Medium), while production requests float16 on a GPU and float32 on a CPU. Only Medium's recorded GPU precision differs from that request, and the differences between whole-utterance and chunked decoding and in the forced language remain. On 17 October 2026 the author decided not to register a default-configuration composite, so the grid keeps its seventeen conditions and pipeline_full stays described as the --fix-spurious-repetitions configuration.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A user on default settings transcribing AMI-like meeting audio gets no repetition repair. The manuscript's 'production composite' figures, including the AMI gain over raw and the Whisper Medium rescue at 337% raw error, describe an opt-in configuration, decoded differently from the shipped pipeline. A change to the fix_repetitions gating in process_audio_file would pass every parity test.

**Proposed fix.** Minimum, text-only: state in the pipeline_full description and docstring, docs/conditions_audit.md and the manuscript that the composite corresponds to running with --fix-spurious-repetitions, and that the default configuration omits repetition repair. Structural: extract the post-processing block of process_audio_file into postprocess_text(text, language, fix_repetitions), have pipeline_full call it with fix_repetitions=True, optionally register pipeline_default (fix_repetitions=False), and make the parity test call the extracted function. Either document the float32/no-chunk benchmark decode against the float16/chunked production decode, or align them; aligning requires re-decoding and sign-off.

### EWER-08: The aggregate carries only macro (mean-of-rates) metrics and discards the pooled WER and alignment counts every summary contains; the f7c85b0 fix reached only the anonymisation benchmark

`evaluation/sweep_aggregate.py:164` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 66959fd adds micro_wer, micro_mer and the hit, substitution, deletion, insertion and hypothesis-word totals to SweepRow as additive columns, leaving every macro value as it was, and the re-run aggregate (2e36bf9) carries them in all 255 rows. On AMI, for example, Large v3 raw now shows a macro WER of 0.3243 beside a pooled 0.2044. Tests in tests/test_audit_eval_sweep.py cover the columns. On 17 October 2026 the author decided that Appendix A stays macro-averaged, with the pooled figures in the committed aggregate.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** On AMI, where many references are one or two words, a few hallucinated utterances dominate macro WER. The raw-vs-pipeline_full delta on AMI, and the Medium-vs-Large comparison, are then driven by a handful of utterances. Readers of the grid cannot check this against the pooled rate, even though the input JSONs already carry it. The manuscript's own methods (L533-536) promise pooled averages 'where utterance length would otherwise drive the figure'.

**Proposed fix.** Add micro_wer, micro_mer, total_hits, total_substitutions, total_deletions, total_insertions and total_hypothesis_words to SweepRow/_CSV_FIELDS as additive columns. Whether Appendix A also reports pooled figures, at least for AMI, is an estimator decision for the maintainer. Do not replace macro.

### EWER-09: Utterances with empty references are dropped per condition, so whisper_norm on AMI is scored on 11,653 utterances against raw's 12,643; the code comment claims the opposite

`evaluation/benchmark_wer.py:482` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 66be1de corrects the comment, records the three skip counts and n_streamed in every summary, and adds condition_ci.normaliser_gain with --gains-output, which computes a condition's gain over the baseline on the utterances both scored, and tests/test_s1_wer_benchmark.py covers both. 9507e0c commits the re-run's Large v3 AMI raw and whisper_norm per-utterance reports (ARC job 8917985, task 1) in output/evaluation/sweep_reports_postfix_ami/, each reproducing its sweep_aggregate cell exactly, and 81d8054 commits normaliser_gain_ami.csv, with its sidecar, from condition_ci --gains-output over them. On the 11,653 utterances both conditions score, the normaliser lowers the AMI macro WER from 0.306127 to 0.285246, by 6.82%, while the two corpus rates give 12.06%, because the 990 utterances raw alone scores average a raw WER of 0.539. 3bf90ed has the manuscript print 6.8% for AMI from that table and give 12.1% as what the two plotted rates would imply (manuscript.qmd:2753-2831 at e515421), and tools/verify_regeneration.py rebuilds the table (G5). No other corpus loses an utterance to the normaliser, for any model, so the other gains stand.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The 990 filler-only AMI references are scored under raw, where they carry high per-utterance WER, and silently excluded under whisper_norm. The AMI 'gain' from the canonical normaliser mixes the effect of normalisation with the removal of a hard subset, and the direction and size of that bias are unknown.

**Proposed fix.** As proposed. Record skipped_empty_reference and skipped_transform counts per condition in the summary, correct the comment, and compute the AMI normaliser gain on the intersection of scored uids from the per-utterance reports. Changing the quoted gain needs maintainer sign-off.

### EWER-10: Dataset and model revisions are unpinned and the summary records no library versions; raw decodes already differ between committed runs

`evaluation/benchmark_wer.py:267` · MAJOR · HIGH-RISK · changes numbers · verified confirmed

**Status.** Partly resolved. fa6bf45 and 66be1de pin the dataset and model revisions at load (evaluation/revisions.py) and make every summary record them with the decode device, dtype, GPU, CUDA and cuDNN versions, the model commit transformers resolved and the package versions, and 0897495 corrected requirements-lock.txt to the job environment. tests/test_s1_wer_benchmark.py checks the pins. The drift between the committed raw decodes is now attributed: the May and sweep decodes of Large v3 test-clean differ in nothing recorded but the card, an L40S against a V100 (c713055). On FLEURS the six pairs among the first three arms that ran a language on the same GPU architecture wrote byte-identical raw summaries, while their pairs on different architectures differ on 0 to 4 utterances (56ce519). The 6 October 2026 recovery and output/evaluation/sweep_decode_provenance.json close the missing public environment-record gap: every extracted field and type agrees with all 255 hash-verified summaries. The complete text inputs are deposited at 10.5281/zenodo.23442874 (REGEN-05). FLEURS arm 4's raw Spanish drift is now isolated: the V100 control of 19 October 2026 (NEW-05, output/evaluation/fleurs_es419_v100_control.json) matched the third arm on all 908 utterances, so the card, with its node, accounts for it in Spanish; the other five languages were not re-decoded. The recorded card difference alone does not establish a causal hardware effect in general.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A hub-side dataset revision (re-sharding, parquet conversion, transcript correction) or a model repo update (generation_config), or a transformers upgrade, changes the hypotheses. The run-to-run determinism shown above means the observed drift is environmental. No summary JSON can say which datasets, transformers or torch version, or which model commit, produced it, so the drift cannot be attributed and an archived result cannot be reproduced.

**Proposed fix.** As proposed, plus: record the GPU name, CUDA/cuDNN versions and the torch dtype in the summary (determinism/gpu.txt shows this is already captured ad hoc), and commit the ARC environment freeze as a lock file.

### EWER-11: Three entry points share the canonical output/evaluation/wer_summary.json path, and the committed copy is a May decode that disagrees with the post-fix grid the manuscript also reports

`evaluation/sweep.py:200` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. The entry points no longer share the headline names. benchmark_wer requires --report and --summary (63be123), evaluation.wer and hpc/evaluate_wer.sh write wer_report_transcripts.csv and wer_summary_transcripts.json (a5fa9c1, ea0ddd3), and the sweep writes the bare names only with --legacy-primary-paths (0d77156). The manuscript stops on a wer_summary.json that is not the raw Large v3 run on LibriSpeech test-clean (70926fa). e3cb675 replaced the committed wer_report.csv and wer_summary.json with the re-run sweep's raw Large v3 test-clean cell (job 8917985 task 0), and 27cb15c rebuilt wer_ci.csv over it: macro WER 0.062210 to 0.062132, micro 0.038630 to 0.038611 and the interval [0.057521, 0.067064] to [0.057458, 0.067001]. The report is byte-identical to sweep_reports_postfix/wer_report.csv and the summary's SHA-256 is the one sweep_aggregate.json records, which tests/test_headline_wer.py checks.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The headline level and CI in the manuscript come from a different decode and environment than Appendix A and the condition deltas (0.0622 vs 0.0621 at four decimals; 5 utterances differ). Separately, running hpc/evaluate_wer.sh on a user corpus with default paths overwrites the canonical summary with a file that has no benchmark block, and the manuscript (reading only $summary) would render that corpus as the LibriSpeech headline.

**Proposed fix.** As proposed. Also have the manuscript setup chunk stop with an error (or have_data=FALSE) when benchmark$dataset/config/model differ from librispeech_asr/clean/openai/whisper-large-v3, or when condition is present and not 'raw'. Regenerating wer_summary.json and wer_ci.csv from the post-fix report needs maintainer sign-off.

### EDER-06: The run that builds the cache scores float32 audio, while every later run scores its 16-bit copy

`evaluation/benchmark_der.py:228` · MAJOR · HIGH-RISK · changes numbers · verified confirmed

**Status.** Resolved. 2bb4224 has build_corpus yield the audio it reads back from the 16-bit WAV it wrote, gives the no-cache path the same PCM_16 round trip in memory and records audio_signal in the summaries. It also lets finetune's _evaluate take the baseline's cache (--eval-cache-dir, which hpc/submit_finetune_pyannote.sh passes since 53254ff), and tests/test_s1_misc_der_signal.py covers it. Of the August results only der_concat (job 8534773) had scored the float mix, because it built its corpus in that run. Its re-run, au_der_concat (job 8976357 at 9cb43e3), built the meetings afresh into a new cache and so scored the 16-bit signal, and 70933b4 commits its summary, which records audio_signal. Every figure it reports is the August one to six decimals, and its der_report.csv is byte for byte the one it replaces.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** `python -m evaluation.benchmark_der --split test --cache-dir NEW_DIR` scores float audio on its first invocation and quantised audio on the second, so the same command gives different per-meeting DER on two runs. The fine-tuning Phase 3 comparison mixes the two paths, so part of the reported 'Change: macro ±x' is quantisation noise rather than the model.

**Proposed fix.** Make every scoring path use the same signal. After writing a WAV, yield the audio re-read from disk (or quantise in memory with `np.round(audio*32767)/32767`), or store the cache as subtype='FLOAT'. Pass the cache_dir used for the baseline into finetune's _evaluate, and record the audio path ('cache PCM_16' or 'float') in der_summary.json.

### EDER-13: The reconstruction audit the manuscript cites has no committed output and no pipeline step

`evaluation/audit_reconstruction.py:169` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 9ecc8ed makes the reconstruction audit's --json output an archivable record (per-meeting rows, the audited manifest, parameters, a summary and run metadata) and adds silence_exact_zero, the share of unannotated frames that are exactly zero, which is what the manuscript's claim needs. 53254ff runs the audit in hpc/submit_ami_cache.sh after each split is built. 942d2c1 commits the audit of the full-length timeline caches the DER results were scored from (job 8918334, code 6f9bf56): 16 test and 18 validation meetings, best shift 0 ms for all 34, silence purity and exact-zero share 1.0. cd8578b has the manuscript read these records instead of asserting the claim. tests/test_s1_misc_audit_reconstruction.py and tests/test_s1_env_jobs.py guard the record and the job step.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reviewer or a reproduction attempt cannot find the per-meeting coverage, purity and best_shift_ms values behind two manuscript claims, or the command, cache and commit that produced them. If mix_meeting changes, nothing re-runs the audit, and the claim stays in the paper unverified.

**Proposed fix.** As proposed, and reword :2049-2051 to state what the audit measured (frames below the energy floor), or note that the gaps are zeros by construction.

### ESTATS-06: Footprint ledger predates the jobs that produced the reported sweep and DER results, yet the manuscript attributes its 38 jobs to those benchmarks

`evaluation/footprint.py:72` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. The footprint builder's --from-sacct mode prices each GPU by its node and counts every job of this project from the evaluation's first job on 2026-05-16 (da8f1ca, a1e7933, 81d5119, da1a368, 4de52cf). The ledger and estimate it built on 2026-10-04 (e3e436d) cover all 197 cluster jobs of the evaluation, the post-fix and audit sweep passes, the timeline DER and the anonymisation jobs among them. b3c5717 and 67abf67 rewrite the manuscript's attribution: the ledger holds every cluster job that held an allocation, the sweep's three passes with an earlier run of part of the first take 61% of the GPU time, and the total errs high instead of being called a floor. The raw dump is not committed, because it lists the shared account's other projects, and arc_job_ledger_provenance.json records its query and SHA-256. The window stays as captured, and its 18 jobs of 16 to 19 May add 21.04 GPU-hours, 12.28 kWh and 2.54 kgCO2e against a window opening on 2026-05-20.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader takes 38 jobs, about 54 GPU-hours and 8.6 kgCO2e as the cost of the benchmarks whose numbers appear in the paper. Those numbers came from later post-fix decodes, dev-split DER sweeps and anonymisation runs that the ledger does not contain. The stated 'floor' framing holds, but the attribution sentence and the exclusion list are wrong.

**Proposed fix.** With maintainer sign-off, choose one of two routes. Either correct manuscript 2678-2706 to say the ledger covers the jobs up to 2026-06-27, which produced the pre-fix sweep and the original DER and timestamp runs, and list the post-fix sweep re-runs, the DER development-split tuning and the anonymisation benchmark among the excluded jobs. Or re-capture the ledger with a scripted sacct export (ESTATS-13) after fixing ESTATS-05, and regenerate footprint_report.csv and footprint_summary.json.

### ESTATS-08: Filler detector counts standalone 'huh' and misses unhyphenated 'mmhmm', contrary to its own comments

`evaluation/disfluency.py:93` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. a986262 allows huh only as a later element of a compound, adds mm+hm+ as an opening stem, counts the spaced "uh huh" and "mm hmm" as one backchannel each and records the detector pattern in the summary. tests/test_s1_wer_disfluency.py covers the detector, and tests/test_disfluency_results.py fails if it changes without a rescore. The committed disfluency_summary.json was rescored from the re-run sweep's AMI decode (a6dd82f, 9732ac0), and on AMI the detector's only effect is that a token beginning with huh no longer counts. Reference fillers fell from 4,084 to 4,072 (11 standalone HUH and one HUH-HUH), raw fillers from 1,203 to 1,195 (seven standalone huh, and one filler through the re-decode) and whisper_norm's output fillers from 19 to 2 (17 huh). Reference recall still prints 19.7 per cent, the raw rows of the re-run's Large v3 AMI dump hold no "mmhmm" and no spaced backchannel on either side, and b2cf23c (merged in 0e90917) rewrote the manuscript's filler section for the rescored file (ESTATS-01).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Every standalone 'huh' (a question tag or interjection, not a hesitation) in the AMI references or hypotheses inflates reference_fillers and raw_fillers. A model writing 'Mmhmm' against AMI's 'MM-HMM' scores that backchannel as not recovered, which understates reference_recall. 'Uh huh' written with a space counts as two fillers. Retention for marking-only stages is unaffected because the errors are symmetric, but the reference-side figures shift by an amount not measured here.

**Proposed fix.** As proposed. Restrict huh to non-initial compound elements, e.g. build the pattern as FIRST_STEM(?:-ANY_STEM)*, with huh excluded from FIRST_STEM, unless standalone huh is deliberately chosen as a filler, in which case fix the comment. Add m+h?m+ or mm+hm+ so unhyphenated backchannels match. Decide how space-separated 'uh huh' and 'mm hmm' are treated. Count the affected spellings in wer_hypotheses_ami.csv on ARC first, and regenerate disfluency_summary.json (CPU only) only if the counts move, with sign-off.

### ESTATS-12: Timestamp benchmark scores the first N streamed rows (one meeting) and records neither the sample nor the decoding environment

`evaluation/benchmark_timestamps.py:355` · MAJOR · HIGH-RISK · changes numbers · verified confirmed

**Status.** Resolved. a36b1d4 writes the sample (limit, order, meetings and utterances per meeting), the decode (device, GPU, dtype, chunk and stride), the pinned model and dataset revisions and the run metadata into timestamp_summary.json, passes revision= to load_dataset and the pipeline, and adds --per-meeting, off by default. The re-run (job 8917980, code 6f9bf56, committed in 567cfd9) reproduces the first run row for row. Its summary now says that the 500 utterances all come from EN2002a and were decoded on an NVIDIA H100 80GB HBM3 in float16 with 30 s chunks and a 5 s stride. Only the median and 90th-percentile end errors changed representation, from 0.01 and 0.15 to 0.009999999999999787 and 0.15000000000000036, the same observations computed unrounded. The card matters: job 7746137, on an H100 PCIe, put one utterance's start at 0.22 s where the P100 and the H100 80GB HBM3 give 0.20 s, which d7b7df9 documents and 4b8f115 pins in tests/test_benchmark_results.py.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The summary JSON on its own claims the whole AMI IHM test split, and a reader of the artefact (the Zenodo archive) cannot tell that it covers one four-speaker meeting. A CPU re-run uses float32 instead of float16 and can move timestamp tokens, and a later transformers release or dataset revision changes rows, all without a trace in the output.

**Proposed fix.** Write limit, the meeting IDs covered, the dataset and model revisions, the transformers, torch and datasets versions, device, dtype, chunk_length_s and stride_length_s into timestamp_summary.json. Add a meeting-spread sampling option, off by default so the committed results remain reproducible, and pin revision= on load_dataset and the pipeline.

### ESTATS-13: No script builds arc_job_ledger.csv from sacct; parse_alloc_tres is test-only, and the recorded query contradicts the provenance note

`evaluation/footprint.py:177` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. da8f1ca adds --from-sacct, which builds the ledger from a `sacct -P` dump with parse_alloc_tres and ElapsedRaw, and later commits extend it to every GPU node, every job of this project, a WorkDir check and a list of the jobs left out with their reasons (81d5119, da1a368, 4de52cf, 1cb7236). The committed ledger is built that way from a read-only dump of 2026-10-04 (e3e436d), and arc_job_ledger_provenance.json records the query and the dump's SHA-256. Rebuilt at fb22ece on 2026-10-04 from a local copy of that dump, whose digest matches, the ledger and its provenance came out as the committed ones, byte for byte. The dump lists the shared account's other projects and is not committed, so of the tests of the build in tests/test_s1_misc_footprint.py and tests/test_footprint_job_scope.py, test_a_committed_raw_dump_rebuilds_the_committed_ledger still skips (line 159 at fb22ece). The GPU types are settled: jobs 7737896 and 7746221 ran on Tesla P100-PCIE-16GB cards, and the June ledger's a100 was the label sacct gives the batch step of an untyped request.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The ledger-to-CSV step was done by hand, so the 38-row ledger cannot be regenerated or audited from a raw sacct dump. The provenance note describes rows the recorded command does not return, which leaves unclear where gpu_type came from. A refresh (see ESTATS-06) would have to repeat an undocumented manual transformation.

**Proposed fix.** As proposed: add a --from-sacct mode that parses `sacct -P` output with parse_alloc_tres and ElapsedRaw, and commit the raw dump beside the ledger. In addition, run a query without -X, or check the batch-step rows, for jobs 7737896 and 7746221 to settle their GPU types. Regenerate footprint_summary.json and correct manuscript 607-609 only if they differ, with sign-off.

### EPRIV-03: --per-meeting cap is silently doubled, so the in-flight multi-meeting run neither caps at N nor spreads over all meetings, yet records per_meeting_cap=N

`evaluation/benchmark_anonymisation.py:353` · MAJOR · HIGH-RISK · changes numbers · verified plausible

**Status.** Resolved. 05ebce8 replaces the doubled over-draw with sample_by_meeting, which decodes each meeting in start-time order until N rows pass the decode, rate and length filters or the meeting runs out, stops at the limit and records accepted_by_meeting. The committed multi-meeting run (job 8917989, code 6f9bf56, committed in 8b6144c) accepted exactly 25 utterances from each of the 16 AMI test meetings, and tests/test_anonymisation_results.py checks the cap against the report. Job 8781723's output, drawn with the doubled cap, stays uncommitted. Its report on ARC holds 400 utterances from 13 of the 16 meetings, up to 42 from one (IS1009d), so it reached more meetings than the estimate above. 05ebce8 also said that the uncapped walk reproduces the August single-meeting sample, which is wrong (the two samples share 36 of 200 utterances), and 66f2f2f and 88679d2 correct the description, on which no number depends.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** limit=400 with per_meeting=25 gives over=800 and chosen = up to 50 rows from each of the 16 meetings. The decode loop fills 400 from the first ~8 meetings at up to 50 each (a few more meetings only if rows are dropped as <1 s). The summary says per_meeting_cap 25 and the plan expects 16 meetings, but the sample covers roughly half the meetings and speakers. Chance is higher than intended and the linkage test weaker, while the recorded cap misstates the design.

**Proposed fix.** Decode meeting by meeting, accepting rows until N pass the decode and length filters or the meeting runs out, instead of a fixed 2x over-draw. Stop at `limit`. Record per-meeting accepted counts and rows skipped (short, undecodable, wrong rate) in the summary. Add a _load_utterances test with a stub stream that includes short rows, asserting max per meeting <= N. Before using job 8781723's output, check its n_utterances against 400 and its per-meeting counts.

### EPRIV-15: Linkage candidates include same-meeting, same-headset recordings, so the rate can key on the IHM channel rather than the voice

`evaluation/benchmark_anonymisation.py:95` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified plausible

**Status.** Resolved. 05ebce8 reports linkage per candidate set (all, within a meeting, across meetings, and across meetings on another headset channel), each with its own chance, and records each speaker's channels. The committed multi-meeting run (job 8917989, 8b6144c) gives cross-meeting linkage of 0.1679, 0.5138, 0.7368 and 0.8947 at alpha 0.5, 0.7, 0.8 and 0.9 against a chance of 0.1101, and across meetings on another channel, which only the four EN2002 speakers allow, 0.12, 0.48, 0.57 and 0.79 against 0.0374, which tests/test_anonymisation_results.py checks. 0565bbb, bd5d563, b6236f0 and 0b93ede (merged in 0e90917) rewrite the Methods sample sentence, the anonymisation section's table and limits paragraph, the Discussion and the abstract for that run (manuscript.qmd:5063-5256 at e515421). The section reports that the run loaded the speaker model directly, because of NEW-INC-01, and that job 8976304 found that route bit-identical to the pipeline's embedder, so whether to repeat it through the pipeline is the author's choice.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A transform that removed voice identity but left each headset's frequency response and noise floor would still link at a high rate within EN2002a, because the nearest other-utterance original comes from the same microphone. The reported linkage then mixes channel matching with speaker re-identification, and its direction as a bound is unknown.

**Proposed fix.** Report linkage with candidates restricted to other meetings (same speaker in another session) alongside within-meeting linkage. First check whether a speaker keeps the same headset channel across a-d sessions; if so, also report a channel-mismatched restriction. Compute chance over the restricted set (EPRIV-04) and revise the manuscript's lower-bound paragraph to match what is measured.

### EPRIV-16: Committed anonymisation artefacts predate the current harness; the manuscript re-derives the loop screen in R with a criterion that differs from degenerate_baselines

`evaluation/benchmark_anonymisation.py:183` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 16c1298 writes the screen into the artefacts: the report gains a per-utterance degenerate_baseline column and the error counts the screen needs, and the summary gains degenerate_baseline_criterion and the guarded fields, wer_baseline_guarded and wer_cost_guarded among them. In the committed runs (8b6144c) the column picks the same utterances as the manuscript's former R screen, three in the multi-meeting run, and every WER field re-pools exactly, which tests/test_anonymisation_results.py checks. 0565bbb (merged in 0e90917) has the manuscript read the mark and the guarded figures from the artefacts, in place of its own screen, and check that the mark is the summary's criterion applied to the control arm (manuscript.qmd:4831-4899 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The two definitions differ. An utterance with ref=10, S=D=0, I=45 is degenerate in Python (hyp 55 > 50) but not in the manuscript (WER 4.5 is not > 5). One with ref=3, S=3, I=14 has WER 5.67, hyp_o 23 (looped in R) but hypothesis 17 < 20 (not degenerate in Python). On the committed 200 utterances the plan reports the same two selected, but a re-run or the multi-meeting result can diverge, and the paper's guarded cost will not match the harness's wer_cost_guarded.

**Proposed fix.** Regenerate the single-meeting artefacts with the current harness to a separate directory and compare before promoting. Have the manuscript read wer_cost_guarded and wer_original_guarded from the summary, or apply hyp = hypothesis_words_original (fallback reference_words + insertions - deletions) with the Python thresholds exactly. Correct the R comment.

### EPRIV-19: Held-out names are assigned to the wrong languages (Polish as 'polynesian', Japanese as 'chinese'), mislabelling the committed by_language breakdown

`evaluation/benchmark_masking.py:117` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 04c01b3 labels every held-out case held_out and keeps the curated-language cells to in-dictionary names, using the old language labels only as sampling strata, and a08265c regenerated the four masking summaries. In masking_summary.json the Polynesian cell went from n 96 and recall 0.25 to n 80 and 0.5, every language cell now reads 0.5, and the 580 held-out cases form a cell of their own with recall 0.0. tests/test_s1_wer_masking.py covers the labelling, and the manuscript does not read the by_language breakdown.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader of masking_summary.json concludes the masker (or the NER stage in masking_summary_ner.json) performs worse on Polynesian or Chinese names, when the drop comes from out-of-dictionary Polish or Japanese names filed under those labels.

**Proposed fix.** Label held-out names 'held_out' (or by true origin) and keep the curated-language breakdown to in_db cases. Fix the comment, then regenerate the four masking summaries to a separate path and compare before promoting.

### EPRIV-23: benchmark_podcast duration matching fails silently (the committed case-study summary has no coverage_ratio), and an empty audio_file matches the first episode

`evaluation/benchmark_podcast.py:214` · MAJOR · HIGH-RISK · changes numbers · verified confirmed

**Status.** Resolved. 4b22326 makes benchmark_podcast stop with exit 2 when --manifest names a missing file, give an empty audio_file no duration, match the exact stem or else a unique episode number, warn otherwise and record duration_source, and tests/test_s1_misc_podcast.py covers it. With the job reading the committed corpus manifest (ca75ced, c4c7b38), job 8983112's structural evaluation matched episode 5 by its number (duration_source "episode") and recorded audio_duration_s 1938.0, coverage_ratio 0.95, segment_coverage_ratio 0.9702 and end_drift_s 1.66. ac08cdc commits that summary with podcast_eval_report.csv, and the README now reports coverage of the recording where it gave the August run's speech-over-span 97.2 per cent.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** (a) The case-study job's manifest path was missing or the stem did not match, so the coverage metrics were silently dropped, and output/case_study/README.md reports speech/span (97.2%) instead of coverage of the recording. (b) A transcript JSON without audio_file (from another tool, or hand-edited) returns ep01's 2305 s for any episode: coverage_ratio and end_drift_s for ep05 come out plausible but wrong.

**Proposed fix.** As proposed: warn (or exit non-zero) when --manifest is given but missing. Return None for an empty audio_file. Match exact stem, then a unique epNN prefix, and warn when ambiguous or absent. Record duration_source per file.

### CORE-09: Review flags assume whitespace-delimited words: normal Chinese and Japanese speech is flagged low_speech_rate

`confidence.py:59` · MAJOR · HIGH-RISK · changes numbers · verified confirmed

**Status.** Resolved. 8bd6fd0 counts speech-rate units by script in confidence.py: a token runs through combining marks, each Han character or kana counts as one unit against a new max_char_rate of 14 per second, and Thai, Lao, Khmer and Myanmar are not rate-flagged but counted in rate_flags_skipped. tests/test_s1_txt_review.py checks the CJK and Devanagari cases and that English is flagged as before, the case study's flagged cues included, so no committed flag moves. The committed case-study review is now job 8983112's (ac08cdc), with rate_flags_skipped 0, the truncation and redacted keys and four flags, which the same test re-flags identically. The bound of 14 per second is reasoned and not validated on a CJK corpus, as 8bd6fd0 records.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A researcher transcribes a Mandarin interview with --timestamps. Nearly every segment of 2.5 s or more is flagged as 'decoding over silence or music', and the console reports a large flagged percentage, pointing them at many correct segments. In the same script high_speech_rate can never fire, so real timing errors go unflagged. The output looks like a real diagnosis of a bad transcript.

**Proposed fix.** As proposed. Script-aware unit counting, or pass the effective language to review_transcript and skip the rate flags (recording that) for unvalidated languages. Add a regression test showing the English case-study flags are unchanged.

### CORE-19: Example-output transcript hard-codes evaluation results that contradict the committed results (DER level, dominant error, sign of the end-boundary bias)

`tools/generate_example_variants.py:133` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. f041d21 makes the generator run transcription.main on a number-free synthetic interview that points to the paper for error rates, and regenerated example_output/variants, so no example transcript quotes a DER, a dominant error or an end-boundary bias. tests/test_example_variants.py regenerates each variant, compares the files and checks that the interview text holds no digits.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader or reviewer opens example_output/variants/*/example_transcript.txt, which README.md links as a demonstration. They read a DER of ~29% (the manuscript headline is 16.6%), confusion described as the dominant error (the committed breakdowns show missed speech dominating), and end-boundary bias attributed to Whisper running long when the metric's sign means it stops early. That contradicts the manuscript and the confidence module's rationale. test_example_variants cannot catch this, because it only checks the files against the generator.

**Proposed fix.** As proposed. With maintainer sign-off, make the three passages number-free or consistent with der_summary.json, der_report.csv and timestamp_summary.json, then regenerate and commit example_output/variants so tests/test_example_variants.py stays green.

### SHELL-05: The manuscript says a preflight runs at the head of every job, but the scripts behind the DER and timestamp results never run it and continue on CPU when CUDA is missing

`hpc/submit_benchmark_der.sh:77` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 53254ff makes hpc/submit_benchmark_der.sh run the GPU gate with --diarisation-required (arc_require_gpu, exit 2 on a failure) and hpc/submit_benchmark_timestamps.sh the GPU gate, so neither continues on the CPU, and both have written an environment record with the nvidia-smi output since ee2cc14. tests/test_s1_env_jobs.py checks that both scripts gate with the right flags, stop at a failed preflight and start their benchmark only after it. The timestamp results come from jobs 8917980 and 8917981, run under the gate (567cfd9), and the DER results from wave 2a's six jobs at 9cb43e3, whose logs all show the preflight passing with --diarisation-required (70933b4). ea7c483 rewrites the manuscript's sentence to match: the preflight ran at the head of the jobs behind the diarisation and timestamp results, and in the diarisation jobs it also required pyannote.audio and its gated model (manuscript.qmd:1633-1641 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** benchmark_der lands on a node where the module stack shadows the CUDA build (the failure the sweep comment describes). The log shows `CUDA: False` and pyannote diarises 8.9 h of AMI on CPU inside a GPU allocation. Either it hits the 12 h wall and fails, or it finishes and writes a der_summary.json that is indistinguishable from a GPU run. Either way, the manuscript's statement that such a job would have been aborted is false.

**Proposed fix.** As proposed. Also either record the device in der_summary.json and timestamp_summary.json, or narrow the manuscript sentence to the jobs that call preflight, and note that the DER and timestamp artefacts predate it.

### SHELL-06: Job scripts pip-install unpinned or conflicting packages into the shared environment that produces results

`hpc/run_tests.sh:62` · MAJOR · HIGH-RISK · changes numbers · verified confirmed

**Status.** Resolved. 53254ff removes every in-job pip install, uninstall and torch reinstall, and hpc/run_tests.sh now runs python -m preflight --lock requirements-lock.txt and exits 2 when an installed version differs from the lock. a63d1cb sets the 4.56 transformers floor and gives the preflight its origin and lock checks. The two retired legacy WER scripts still contain installs but exit 1 before reaching them (ea0ddd3). tests/test_s1_env_jobs.py checks that no live job script or helper installs a package, that run_tests.sh checks the lock before pytest and that the retired scripts refuse to run, and tests/test_s1_env_preflight.py tests the lock check itself. The re-run's headline summary records torch 2.5.1+cu121, transformers 4.57.1, pyannote.audio 3.4.0, jiwer 4.0.0, datasets 4.8.5 and numpy 2.3.3, the versions requirements-lock.txt holds.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** After a torch self-heal has removed torchaudio (SHELL-01), `sbatch hpc/run_tests.sh` sees `import pyannote.audio` fail and installs the newest pyannote.audio from PyPI. That drags a PyPI torch and a new major pyannote into $DATA/speech_transcription_env. The next benchmark_der or anonymisation run then uses a different pyannote from the 3.4.0 the manuscript and der_summary.json report. The job logs show only `--quiet`.

**Proposed fix.** As proposed. Remove the in-job installs and fail against the lock or preflight. If an install must stay, pin exact versions and align the floors with requirements.txt and preflight._TRANSFORMERS_FLOOR.

### SHELL-07: activate_project_env_arc.sh puts a hard-coded python3.11 site-packages ahead of a Python 3.12 conda environment and silently falls back to any module Python

`activate_project_env_arc.sh:62` · MAJOR · HIGH-RISK · changes numbers · verified plausible

**Status.** Resolved. 63e3fb6 removes the PYTHONPATH entry for lib/python3.11/site-packages, exports PYTHONNOUSERSITE=1, replaces the silent Python-module cascade with the one module the venv is built with (ARC_PYTHON_MODULE), stops at activation when Python is missing or below 3.11, and prints sys.path in every job log. tests/test_s1_env_activation.py sources the real script against a fake $DATA. On ARC the environment's lib/ holds python3.12 and python3.1 but no python3.11 (listed read-only on 2026-10-04), so the entry was dead and no committed result was affected.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** PYTHONPATH entries are searched before site-packages. If $DATA/speech_transcription_env/lib/python3.11/site-packages survives from the earlier 3.11 environment (not verifiable: ARC SSH timed out), pure-Python packages there (transformers, jiwer, datasets, pyannote.*) shadow the 3.12 copies. A job then silently runs a different transformers from the one `pip freeze` and preflight report. If the directory is absent, the entry is dead and misleading. With conda-meta missing, a job can run under Python 3.10 with no warning.

**Proposed fix.** As proposed. Delete the export, or derive it from sysconfig, and log sys.path. Check on ARC whether lib/python3.11 exists before assuming results were affected.

### SHELL-09: Three scripts measuring different things all write the manuscript's canonical wer_report.csv and wer_summary.json

`hpc/evaluate_wer.sh:78` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. ea0ddd3 retires hpc/legacy/submit_benchmark_wer.sh and submit_benchmark_wer_gpu.sh, each of which now exits 1 before doing anything, and makes hpc/evaluate_wer.sh write wer_report_transcripts.csv and wer_summary_transcripts.json into .../output/evaluation/inhouse/ and refuse to overwrite a summary without OVERWRITE=1. evaluation.wer writes those names by default (a5fa9c1), benchmark_wer requires its output paths (63be123), and the sweep writes the bare names only with --legacy-primary-paths (0d77156). tests/test_s1_env_jobs.py checks the job's output names, its refusal to overwrite and the retired scripts' refusal to run, and tests/test_s1_wer_scoring.py and tests/test_audit_eval_sweep.py check the default names of evaluation.wer and the sweep. The manuscript reads the bare names, which now hold the sweep's raw cell (e3cb675), and stops on a summary of any other run (70926fa). manuscript/README.md's warning, which still described the old defaults, now matches them (06e7b46).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A user follows the manuscript's hint and runs `sbatch hpc/evaluate_wer.sh` on their own transcripts. It overwrites the ARC copy of the LibriSpeech large-v3 canonical summary with in-house WER in the same schema. The next rsync of output/evaluation then silently replaces the manuscript input with a different corpus's number. Separately, `sbatch hpc/submit_benchmark_wer.sh` runs full LibriSpeech on CPU and is killed at 12 h, after truncating nothing but having burned the allocation.

**Proposed fix.** As proposed. Include sweep.py's legacy-path branch (sweep.py:199-203) in the rename, and update the manuscript read paths and missing-file message together, with the old file kept until the manuscript is switched.

### DEPS-07: Committed sweep_aggregate.{csv,json} (headline table) was not produced by committed code: hand-added pipeline_version, a local C:\tmp path, and a different JSON schema

`evaluation/sweep_aggregate.py:80` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 66959fd has evaluation.sweep_aggregate write the committed schema itself: pipeline_version from each summary's run metadata, source_file relative to the sweep directory, and a typed provenance-and-rows JSON that holds the SHA-256 of every input summary. Its message records that it reproduced every cell of the then-committed grid from the 240 post-fix summaries. The committed aggregate was then rebuilt by the module from the re-run sweep (2e36bf9): 255 rows, one pipeline_version (6f9bf56) and relative source paths, with no hand edit. tests/test_audit_eval_sweep.py covers the schema. The per-cell summaries it was built from are on ARC, not in the repository, so a rebuild can be checked against the recorded digests only there.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Running the documented regeneration path (`sbatch hpc/aggregate_sweep.sh`, i.e. `python -m evaluation.sweep_aggregate`) produces a CSV without pipeline_version, a JSON with a different schema and ARC paths in source_file. A rebuild-and-compare gate would fail. Nothing ties the per-row label to the commit that actually produced each per-suite summary, so a mislabelled row cannot be detected.

**Proposed fix.** The post-fix per-suite wer_summary JSONs are not committed (only sweep_reports_postfix/*.csv), so 'regenerate and diff' must be done either on ARC from the original summaries or by recomputing macro metrics from the committed per-utterance CSVs. Do that before touching the committed file. If the column is kept, add pipeline_version to SweepRow and populate it from a commit field in the per-suite summaries, which do not carry one yet (DEPS-04). Replacing the committed aggregate needs maintainer sign-off.

### DEPS-15: Case-study provenance breaks at the ffmpeg decode, and fetch_codex_mentis silently rewrites corpus hashes

`hpc/submit_case_study.sh:90` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. A fetch is checked against the committed manifest's checksums, into a fresh directory too (5660b06, e9da5b3), and the case study passes --source-audio and the exact ffmpeg command so that its run manifest names the original recording (73c2f96). A cached decode is reused only when the stamp beside it names the recording's SHA-256 (a2a24bb), and tests/test_audit_shell_job_exit_status.py covers the job script. The committed case-study manifest is now job 8983112's (ac08cdc). It names the .m4a with the SHA-256 the corpus manifest records (a1f08233...), and its derivation records that the WAV was a decode cached by an earlier run and reused because its stamp matched.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The podcast host (anchor.fm/CloudFront) re-encodes episode 5. A later fetch replaces the audio and silently overwrites the committed hash. The re-run case study then transcribes different audio, and neither manifest can show which corpus file or decoder produced the WAV. A different ffmpeg resampler version likewise changes the WAV bytes (and potentially the transcript) without a trace.

**Proposed fix.** As proposed. Also make the cached-decode branch (submit_case_study.sh:99) verify the .m4a hash, or store the source hash beside the _16k.wav and re-decode on mismatch. Linking the committed case-study manifest to the corpus hash retroactively needs sign-off, since it edits a committed artefact or its README.

### DEPS-17: Segmentation fine-tuning runs with no seed (no seed_everything or manual_seed)

`evaluation/finetune_pyannote_segmentation.py:419` · MAJOR · changes numbers · verified plausible

**Status.** Resolved. bd24b7b (2026-09-25), which predates this entry (a387654), adds --seed (default 42), calls pl.seed_everything(seed, workers=True), sets deterministic="warn" on the Trainer and records the seed in finetune_provenance.json. tests/test_audit_der_finetune.py checks the default. No committed result came from this script.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Two runs of hpc/submit_finetune_pyannote.sh on the same data draw different training chunks and dropout masks. They pick different best checkpoints and give a different DER when passed to benchmark_der --segmentation-model, with no way to tell run-to-run variance from a real effect.

**Proposed fix.** As proposed: add --seed (default 42), call pl.seed_everything(seed, workers=True), which also sets PL_GLOBAL_SEED and so fixes pyannote's sampler seed explicitly, and set Trainer(deterministic=True) where kernels allow. Record the seed in the checkpoint metadata. Do not claim that the training chunks currently differ between runs unless that has been checked.

### XREF-03: Example outputs come from a reimplementation of the JSON/VTT writers that has drifted from what transcription.py actually emits

`tools/generate_example_variants.py:272` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. f041d21 makes tools/generate_example_variants.py run transcription.main on a synthetic interview with only the model calls replaced, so every file in example_output/variants comes from the pipeline's own writers (timeline_repairs and redacted keys, the redacted pair, review and manifest, and no hf_cache label), and regenerated the four variants. tests/test_example_variants.py regenerates each variant, compares the files and checks that the real writers are called. 63be123 corrected the write_timestamped_outputs docstring, which had listed hf_cache.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A researcher writes a parser or provenance audit against the README-linked examples. Real sidecars carry `timeline_repairs` and `redacted` keys the examples lack, and never carry `hf_cache`, so a check such as `source == 'hf_cache'` classifies every real diarised transcript as unexpected. The example suite keeps passing whatever the real writer does, so the drift stays hidden.

**Proposed fix.** Have the generator call transcription.write_timestamped_outputs (and the txt writer) on a synthetic `transcription_result` whose chunks come from TURNS, pinning `generated_at` (inject it, or monkeypatch datetime) so the output stays deterministic. Keep tests/test_example_variants.py comparing against the committed files, and add a test asserting that the example JSON key set equals the real writer's. Fix the docstring at transcription.py:2664. Regenerate example_output/variants (needs maintainer sign-off).

### XREF-08: Four different filler vocabularies: the production stage, the ablation condition, the retention metric and the WER normaliser

`transcription.py:949` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. The inventories are documented, not unified: the table of filler vocabularies and the reason for each difference is in evaluation/conditions.py (c4f3133) and docs/conditions_audit.md (d850f07), and a986262 corrects disfluency.py's docstring and has the summary record its detector pattern. The rescored disfluency_summary.json (a6dd82f, 9732ac0) carries detector_pattern beside filler_tokens, and its output_marked count shows pipeline_full marking 1,191 of the 1,195 fillers in its output, as tests/test_disfluency_results.py checks. b2cf23c (merged in 0e90917) qualifies the manuscript's sentence with that count: the bracketing stage marks all but four of the tokens, spellings its list does not cover, such as a drawn-out mmm (manuscript.qmd:3151-3191 at e515421). On 17 October 2026 the author decided to keep the declared scorer and conditions (NEW-11), so the vocabularies stay documented and not unified, and the filler_strip cells stand.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** "erm" and "umm" are removed by filler_strip but not bracketed by the shipped filler_bracket stage, because `\b(er)\b` cannot match "erm". The ablation condition and the production stage therefore act on different vocabularies although they are reported as counterparts. disfluency.py counts "huh"/"uh-huh" as fillers that no removal condition touches, so retention under a removing condition is held above zero by tokens outside that condition's scope. `python -m evaluation.wer --remove-fillers` strips "eh", which neither the pipeline nor the retention metric recognises.

**Proposed fix.** Do not unify the lists as a code cleanup: disfluency.py:83-85 already records that doing so moves published WERs, so unifying is a maintainer decision requiring a re-score from the dumps and sign-off. Minimum fix: move the four-inventory table into docs/conditions_audit.md with the reason for each difference. Correct disfluency.py's module docstring. Make the summary JSON record the detector pattern (_FILLER_STEM) alongside FILLER_TOKENS, which needs a regenerated artefact with sign-off. Either qualify manuscript.qmd:1441-1443, or count how many retained fillers fall outside FILLER_TOKENS (a CPU re-score of the AMI dump) before keeping the 'marks these tokens' wording.

### XREF-12: manuscript/README.md render instructions are stale: two R packages missing, and an evaluation step that points at a non-existent corpus

`manuscript/README.md:8` · MAJOR · touches end product · verified confirmed

**Status.** Resolved. 1a3c021 removed the evaluation step that pointed at a data/ground_truth that does not exist and wrote into the committed files, and says the manuscript renders from the committed artefacts with no evaluation run. dc8e951 lists all ten R packages the source calls, tidyr among them, gives the R and Quarto versions of the checked render and records the packages in manuscript/renv.lock. One sentence under "Regenerating the inputs" now overstates the risk: since a5fa9c1 and ea0ddd3, evaluation.wer and hpc/evaluate_wer.sh write wer_summary_transcripts.json by default, so they overwrite wer_summary.json only when told to write that name.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reviewer on a clean R install follows manuscript/README.md, and `quarto render` stops with "there is no package called 'tidyr'". Following the evaluation step either fails on the missing directory or, pointed at other transcripts, overwrites the committed headline wer_summary.json with a different evaluation.

**Proposed fix.** As proposed. Also state in the README that evaluate_wer.sh and evaluation.wer write the canonical wer_summary.json and must not be run into output/evaluation (XREF-01).

### OUTPUTS-03: The headline corpus table, bootstrap interval and micro-WER line read a May 2026 pilot decode, not the sweep they are presented alongside

`manuscript/manuscript.qmd:71` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. e3cb675 replaced wer_report.csv and wer_summary.json with the re-run sweep's raw Large v3 test-clean cell (job 8917985 task 0), the decode the paired intervals use, and 27cb15c rebuilt wer_ci.csv over it with a provenance sidecar. The macro WER moved from 0.062210 to 0.062132, the micro WER from 0.038630 to 0.038611 and the interval from [0.057521, 0.067064] to [0.057458, 0.067001], so the printed lower bound falls from 0.058 to 0.057, a third decimal that a181a9e shows is the seed's, and tests/test_headline_wer.py ties the pair to the sweep. The Stage 4 rewrite (0e90917) reads them as the sweep's raw cell and checks that in the setup chunk (manuscript.qmd:585-613 at e515421), drops the PHASE2 notes that called them the May decode and names the re-run's card. Data availability calls wer_report.csv the raw report of the repaired sweep (5987-5993).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The paper's headline interval and micro WER come from a third decode, neither the pre-fix nor the post-fix sweep, and cci_width_ratio divides that May interval's width by the post-fix paired widths. Regenerating from the reported sweep changes the rendered lower bound from 0.058 to 0.057, and a reader cannot tell from the artefacts that the table and the condition analysis rest on different decodes.

**Proposed fix.** The proposed fix is right. Also update the Data availability sentence at :3014-3017, which names the top-level wer_report.csv as the baseline, and the results-summary-empty message at :733-735. Doing so changes the rendered lower bound from 0.058 to 0.057, and the micro WER shifts by 2e-5, which is invisible at 3 dp. Both need author sign-off.

### OUTPUTS-04: The committed sweep_aggregate.csv/json, the manuscript's primary grid, has a schema no code in the repo writes: hand-added pipeline_version, a bare-list JSON, and source paths in a local temp directory

`evaluation/sweep_aggregate.py:60` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 66959fd has the module write the committed schema: pipeline_version from each summary, relative source_file, and a typed JSON written by write_aggregate_json with the inputs' SHA-256 and the aggregation's run metadata. 2e36bf9 replaced the committed files with its output over the re-run sweep: 255 rows, pipeline_version 6f9bf56 in every row and relative source paths. The fifteen raw cells reproduce the post-fix sweep's macro WER to the last digit, the conditions no fix touched are unchanged in all fifteen cells, and hpc/aggregate_sweep.sh now defaults to the re-run's directory. tests/test_audit_eval_sweep.py covers the schema.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The next `sbatch hpc/aggregate_sweep.sh`, or `python -m evaluation.sweep_aggregate --sweep-dir .../postfix`, writes an 11-column CSV without pipeline_version and a dict-shaped JSON. The provenance column the commit says must stay disappears, and any consumer of the list-shaped JSON breaks. The committed artefact cannot be regenerated from the repository, and its source_file paths point at a local C:\tmp directory that no longer holds the inputs.

**Proposed fix.** The proposed fix is right. When regenerating, write the JSON through write_aggregate_json so numbers stay numbers, and record the commit in provenance. The regeneration must reproduce the committed macro_wer values exactly. Check that with a diff before replacing the file.

### OUTPUTS-05: The footprint ledger stops in June 2026, before the jobs that produced the reported sweep and DER results, yet the manuscript says it covers those benchmarks

`manuscript/manuscript.qmd:2678` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. e3e436d recaptures arc_job_ledger.csv from a read-only sacct dump taken on 2026-10-04 at 13:45 BST, after the last job of the evaluation to end (8978760) had finished: 197 jobs from 7662519 (2026-05-16), among them every job behind the reported WER, DER, timestamp, FLEURS, anonymisation, case-study and determinism results. footprint_report.csv and footprint_summary.json are regenerated from it, at 155.70 GPU-hours, 95.95 kWh and 19.86 kgCO2e where the June capture gave 38 jobs and 53.79 GPU-hours, and the provenance lists the seven jobs left out, all cancelled while pending (1cb7236). e08103e and 19bf267 bring the READMEs, docs/expansion_plan.md and the module docstring to the new capture. b3c5717, 3302975, 67abf67 and 8dabb78 rewrite the manuscript's footprint section and Methods ledger sentences for it, with checks that the ledger holds every job the multilingual summary and the determinism comparison name (manuscript.qmd:5267-5466 at e515421). The window opens on 2026-05-16, with the evaluation's first job, as captured, and a window opening on 2026-05-20 would give 179 jobs and 134.66 GPU-hours.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The paper attributes 38 jobs and about 54 GPU-hours to the sweep and diarisation benchmarks it reports. Those jobs actually produced the superseded pre-fix sweep and the concat-mode DER. The jobs behind the reported numbers are uncounted, and the exclusion caveat does not mention them, so the stated 'floor' is described as covering runs it does not include.

**Proposed fix.** The proposed fix is right. Recapturing the ledger changes fp_njobs, GPU-hours, kWh and kg, and tbl-footprint. If the June ledger is kept, the minimal edit is to say it covers the first-pass sweep and the superseded concat-protocol DER, and to add the post-fix sweep re-runs, the timeline DER and the anonymisation job to the list of exclusions.

### OUTPUTS-06: The example transcripts presented in the README as showing transcription quality were made by v1.0.0 and contain the contraction_fix defect and a leaked masked surname

`example_output/transcripts/architecture_of_meaning/transcript.txt:14` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 12275ed labels the four transcripts in example_output/transcripts as release 1.0.0 output of 10 November 2025, in a new README that names the three defects fixed since, the contraction rewrite and the possessive surname that survived masking among them. README.md no longer presents them as current output quality, and the current code's output is the regenerated example_output/variants (f041d21). The transcripts are not re-transcribed, which needs the recordings and a GPU run, so output/evaluation/artefact_audit.json (re-run in b7fcdd6 and 12275ed) still reports two masked artefacts leaking the surname, the behind_the_curtains .txt and .docx, kept as the record of that release's defect. On 17 October 2026 the author decided to keep the four transcripts as that record, not re-transcribed.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reviewer opening the showcase examples reads "People we're significantly faster" and a leaked surname, both defects the paper says are fixed, presented as current output quality. artefact_audit.json keeps reporting 2 leaking masked artefacts that come from an obsolete masker.

**Proposed fix.** The proposed fix is right. The cheaper option, a README note in example_output/transcripts plus rewording README.md:20, is enough to stop the misrepresentation until re-transcription is possible. Re-running audit_artefacts afterwards changes artefact_audit.json counts.

### OUTPUTS-08: The case-study artefacts describe the 2026-08-05 run, but ARC holds a later run of the same job under the current retiming code with different figures; the README also wrongly says no transcript is committed

`output/case_study/README.md:41` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. ac08cdc commits job 8983112's summary, report, review and manifest and rewrites output/case_study/README.md against them: 405 cues, the repair counts in the current vocabulary, the history of jobs 8400094, 8441879, 8918023, 8978758 and 8983112, and an account of each of the four flags. The "positives." cue is a word Whisper wrote twice and lasts 0.02 s in both runs, and the third flag is a passage written twice whose three crammed cues were merged. The files section lists what is committed, with ep05_raw_text.txt kept byte for byte as the August run's text because the NER note measured it, which f2b11f7 and 74c4102 also say in the HPC and evaluation READMEs and in the masking test. 6525932 makes the NER note name job 8441879 as the source of its text and list the ten places where 8983112's text differs, and 4b582e1 counts the README's words in the review's unit. The README's remark that the note counted "Jordan" as a genuine name (97e8c97) is taken up as NEW-07.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The case-study README presents 408 segments, 7 clamped overlaps and a cue it calls clamp-generated and of zero length, which in the committed review lasts 0.02 s, as definitive pipeline behaviour. The latest run of the same job under current code gives 405 segments. Nothing in the committed JSON identifies the producing code, so the two runs cannot be told apart, and the claim that no transcript is committed is false.

**Proposed fix.** The proposed fix is right. If the 2026-08-06 run is adopted, also update the repair-count vocabulary (word_retimed, segment_merged) and rewrite the paragraph on the "positives." cue, which lasts 0.02 s in every run and which the repair at HEAD keeps.

### OUTPUTS-09: output/evaluation_clustering_0.60 and output/evaluation_vad_refine hold results from the superseded concat reconstruction, are unlabelled, and are pinned by tests

`tests/test_benchmark_results.py:938` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. c6b4eaf keeps both directories in place, so the tests that pin them are untouched, and gives each a README: output/evaluation_clustering_0.60/ is labelled history from the concatenation protocol that fde27c5 replaced, which the manuscript does not report, and output/evaluation_vad_refine/ an unreported benchmark-only --vad-refine run. The second was never a concatenation-protocol result, since the timestamp benchmark streams AMI utterances, and it was re-run as job 8917981 with its README rewritten (567cfd9, d7b7df9). a02b8dd corrects the clustering README, which gave job 7746222 an H100, to the Tesla P100-PCIE-16GB that the job's log names on htc-g034, where sacct puts it.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Someone browsing output/ finds evaluation_vad_refine/timestamp_summary.json with mae_end 0.064, half the reported 0.127 s, and evaluation_clustering_0.60 with macro DER 0.319 against the reported 0.166, and takes them for current alternative configurations. Tests keep these concat-protocol numbers pinned, so archiving the files fails the suite rather than flagging the files as stale.

**Proposed fix.** The proposed fix is right. Moving the directories needs the test paths updated in the same commit. Alternatively, keep them in place and add a README, which avoids churning the tests.

### OUTPUTS-11: fleurs_multilingual_summary.json was assembled by hand from six ARC jobs across three commits; no script in the repo produces it

`output/evaluation/fleurs_multilingual_summary.json:1` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. evaluation/fleurs_multilingual.py (5a119fa) builds the summary and records each input's SHA-256, tests/test_s1_wer_fleurs.py covers the assembly and its refusals, and the committed file was assembled with it at 0f5b13e from four arms, the fourth being ARC array 8917984 (56ce519, 51e6d47). The diacritic shares are measured over each whole test split (2fd96a9, 08d06a8, ARC job 8918340). 80dc57c (merged in 0e90917) has the manuscript describe them as such, correct the comparison of French with Spanish and compute Spearman's rho from the unrounded shares and ratios, so that rounding cannot create ties (manuscript.qmd:3344-3355 and 3452-3467 at e515421). The measured shares move that rho from 0.90 to 0.94, which the author accepted on 17 October 2026.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The ratios and rank correlation in @sec-multilingual cannot be regenerated from the repository. A slip in hand assembly, such as swapping two languages' ratios, would render as a plausible number with no check against it, and rounding ratios to 2 dp before the Spearman computation can introduce ties.

**Proposed fix.** The proposed fix is right. A regenerated file must reproduce the committed rounded values before it replaces them, and any change in rho from unrounded inputs has to be signed off, because it is a manuscript statistic.

### OUTPUTS-13: The example variant JSON no longer matches what transcription.py writes: no timeline_repairs field and no redacted parallel outputs

`tools/generate_example_variants.py:1` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. f041d21 makes tools/generate_example_variants.py run transcription.main on a synthetic interview, replacing only the model calls, and regenerates example_output/variants from it, a regeneration its message records as approved by the author. Every transcript JSON now carries timeline_repairs and redacted, 01_plain holds only the transcript and its manifest, and variants 02 to 04 gain the redacted JSON and VTT, the review file and the manifest. 365af36 regenerated variants 03 and 04 for the diarisation snapshot keys, and b7fcdd6 re-ran the artefact audit over the new examples. The tests in tests/test_example_variants.py regenerate every variant and fail if the committed file set or any file's contents differ from what the pipeline writes.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A user writes a parser against example_output/variants and does not handle timeline_repairs or the *_redacted.json/.vtt files the current pipeline writes when masking and timestamps are both on. The test suite stays green because nothing compares the generator with transcription.py.

**Proposed fix.** Beyond the proposed fix: add the 'redacted' key to every JSON, drop the JSON/VTT from 01_plain or state that the plain run writes only .txt/.docx, add *_redacted.json/.vtt to variants 02-04 since the header says masking is on, and derive the example's key sets from transcription.write_timestamped_outputs run on a synthetic result instead of from a hand template. Regenerate with sign-off.

### OUTPUTS-14: Superseded and current result pairs live side by side with conflicting names and no retention note outside commit messages and R comments

`output/evaluation/sweep_reports/wer_report.csv:1` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. c6b4eaf makes output/evaluation/README.md the retention record, naming the job or command behind each current file and what replaced each superseded one, and labels output/evaluation_clustering_0.60/ and output/evaluation_vad_refine/ in place with READMEs of their own. 7214e77 moved the May 2026 pilot files, whose obsolete postprocessed condition could pass for a current cell, into pilot_may2026/, and 70926fa makes the manuscript stop unless the three interval files share one replicate count. At f2578b8 the record still described the runs the audit's re-runs replaced, said job 8781724 was not committed and gave jobs 7746221 and 7746222 an H100, and 8dc47ed and c9f4839 bring it up to date. Its rows for the headline pair, wer_ci.csv, FLEURS, the timestamps, filler preservation, anonymisation and output/evaluation_vad_refine/ describe the re-run wave's results, job 8781724 has a row of its own, and its pending list names only what is still to be regenerated. Both old jobs are now given the Tesla P100-PCIE-16GB that their logs on ARC show, on htc-g033 and htc-g034, as output/evaluation_clustering_0.60/README.md gives it for 7746222 since a02b8dd. On 17 October 2026 the author decided not to rename the superseded files, so output/evaluation/README.md remains the retention record.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A new analysis picks up sweep_reports/wer_report_contraction_fix.csv, the obvious unsuffixed name, and gets defect-era per-utterance data (228 utterances worse, +265 substitutions). This is the same mistake Appendix B already makes. Nothing in the directory says which member of a pair is current.

**Proposed fix.** The proposed fix is right. Renaming superseded artefacts must update manuscript.qmd :158, :909, :1032 and :3104-3107 in the same commit. Also point boot_b at condition_ci_postfix.csv.

### DOCS-03: HPC docs describe GPU transcription, preflight checks and a working --time-limit, but the worker forces CPU, skips preflight and kills Python after 3 h

`docs/hpc_usage.md:252` · MAJOR · touches end product · verified confirmed

**Status.** Resolved. e77a553 removed the worker's fixed three-hour timeout and the wrapper's sinfo probe and GPU branch, and 53254ff makes hpc/batch_transcription.sh run the CPU preflight with the GPU hidden and stop with exit 2 when it fails. 81306c1 rewrites docs/hpc_usage.md, hpc/README.md and the ARC guides to describe a CPU-only worker whose only time limit is --time-limit. The tests in tests/test_audit_shell_transcription_wrapper.py run both scripts under stubs, including a worker that stops when its preflight fails. The manuscript part is settled as well: the diarisation and timestamp results now come from jobs that ran the preflight (wave 2a, 70933b4, and jobs 8917980 and 8917981, 567cfd9), and ea7c483 says so in place of the sentence that they did not (manuscript.qmd:1633-1641 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** For a 5-hour interview, `hpc/submit_transcription.sh --single-file audio_input/long.wav --time-limit 10:00:00` gets a 10 h SLURM allocation, but the worker kills Python at 3 h and no transcript is written. A default submission on a cluster where sinfo lists GPU nodes takes the 'GPU' branch and gets 2 h and 16G for a CPU-only large-v3 run that never requested a GPU, so long files time out.

**Proposed fix.** As proposed: decide CPU or GPU for the transcription worker and make docs/hpc_usage.md, README.md:181-183 and the ARC guide match. Derive the internal timeout from the SLURM limit (e.g. `squeue -h -j $SLURM_JOB_ID -o %L`) or drop `timeout 10800`. Remove the GPU/CPU branch in submit_transcription.sh if the worker stays CPU-only, and add `python -m preflight` to batch_transcription.sh. In addition, with maintainer sign-off, correct manuscript.qmd:599-601 to name the jobs that actually run preflight, or add preflight to submit_benchmark_der/der_sweep/benchmark_timestamps/ami_cache. Even then, the sentence must not claim that the committed DER and timestamp runs were gated by preflight, because they were not.

### DOCS-15: CITATION.cff fails CFF 1.2.0 schema validation and has no repository URL; setup.py, README and manuscript each give a different repository URL

`CITATION.cff:14` · MAJOR · touches end product · verified confirmed

**Status.** Resolved. d0edd03 removed the BibTeX preferred-citation, which the CFF 1.2.0 schema rejects, and added repository-code with the URL setup.py gives. cffconvert's validator (Citation.validate) accepts the file at HEAD and rejects the one at 10981d4. setup.py (f5943b2), README.md (c3a3041), hpc/HPC_SETUP_GUIDE.md (8c0665c) and the manuscript's Data availability section (cd8578b) gave that one URL. Since release 2.0.0 every tracked file names the public repository, https://github.com/pablobernabeu/secure_local_HPC_speech_transcription, and none names the development repository. The tests in tests/test_citation_metadata.py check that any preferred-citation is a reference object and that repository-code matches setup.py.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** `cffconvert --validate` fails, and GitHub's 'Cite this repository' widget and Zenodo's CITATION.cff import either reject the file or drop the preferred citation. The redirect from the old repository name stops working if a repository with that name is ever created again, and pip metadata (setup.py project_urls) points at a different repository.

**Proposed fix.** As proposed: replace preferred-citation with a CFF reference object (type: software, authors, title, doi, year, version), or remove it. Add `repository-code:` with the canonical remote, unify setup.py url/project_urls, the README clone commands and HPC_SETUP_GUIDE.md:26, and (with sign-off) manuscript.qmd:3002. Validate with `cffconvert --validate`.

### MS-03: 'Roughly N times narrower' ratio is inflated to 59 by zero-width intervals of inert conditions

`manuscript/manuscript.qmd:1052` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 70926fa takes the ratio over the conditions whose intervals have any width, leaving out the canonical normaliser too, states how many intervals have zero width and why, and removes the fallback literal. With the regenerated intervals (9cb43e3) and the headline interval over the sweep's raw report (27cb15c), only dedup_window and filler_strip have width and 13 of the 16 intervals are zero-width, so the ratio renders as 10 (10.395). 8e1b7ff (merged in 0e90917) rewrites the paragraph for that: the average is over the two conditions besides the canonical normaliser whose intervals have any width, and the other thirteen record the absence of any change (manuscript.qmd:2456-2466 at e515421). The PHASE2 note that said the interval on the level rests on the May decode is gone.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The paper states the paired intervals are "roughly 59 times narrower than the interval on the level, which is what makes the test sharp". Most of that factor comes from averaging in intervals that are zero-width by construction (identical hypotheses), not from paired-bootstrap variance reduction. It is a plausible-looking but inflated number.

**Proposed fix.** Report the ratio over conditions with ci_hi > ci_lo, or for a named comparison such as pipeline_full. State in the prose that nine stages have zero-width intervals because they alter no hypothesis. Remove the fallback literal. The printed number will change from 59, to about 21 if the non-degenerate mean is used.

### MS-11: Hardware and footprint claims rest on a ledger that predates the post-fix re-runs behind the reported grid

`manuscript/manuscript.qmd:608` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. The ledger recaptured in e3e436d records each GPU job's board, read from the node it ran on, and no job is labelled a100. In the sweep re-run, Large v3 (8917985) ran on V100 PCIe cards and Whisper Medium and distil-large-v3 (8917986, 8917987) on L40S cards, as hpc/runs/sweep.env and wer_summary.json say. b3c5717 and 3302975 rewrite the Methods ledger and hardware sentences from it (manuscript.qmd:1655-1697 at e515421), naming the determinism check's processor run (8978759, 16 cores, 32 GB) as the one job running a model for a reported result that held no GPU. The footprint section's scope paragraph, totals and caption describe the final ledger, and its PHASE2 notes are gone. The window stays as captured, opening on 2026-05-16, which the builder documents and the manuscript states.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The GPU that decoded the published grid is unrecorded, even though the raw baseline itself moved between decodes (FLEURS 0.04730 to 0.04724, test-other 0.08388 to 0.08400). The footprint section implies its 38 jobs cover the reported sweep, and its 'floor' omits roughly half the sweep GPU time.

**Proposed fix.** Query sacct AllocTRES for 8688725, 8708134, 8708135 and the anonymisation jobs before changing the Methods claim, because the card may not be an A100. Regenerate arc_job_ledger.csv and footprint_summary.json. This changes the printed footprint figures (fp_njobs, GPU-hours, kWh, kgCO2e and @tbl-footprint), and the sign-off request should say so. Update the scope sentences at lines 607-609 and 2702-2704.

### MS-12: Headline table, dispersion, speaker and Appendix C figures read a third decode of the raw condition

`manuscript/manuscript.qmd:71` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. e3cb675 replaced wer_report.csv and wer_summary.json with the sweep's raw Large v3 test-clean cell (job 8917985, task 0), the same file as sweep_reports_postfix/wer_report.csv, and 27cb15c rebuilt wer_ci.csv over it, so the headline table, dispersion, speaker figures and Appendix C read the decode the paired intervals use, which tests/test_headline_wer.py checks. The printed lower bound went from 0.058 to 0.057, a third decimal that a181a9e shows is set by the seed, and the filler figures now come from the same sweep's AMI decode (a6dd82f, 9732ac0). The Stage 4 rewrite (0e90917) drops the PHASE2 notes that called the headline files the May decode and ties them to the grid's cell in the setup chunk (manuscript.qmd:585-613 at e515421). Its Methods say that filler preservation is scored from the hypotheses the sweep kept for its AMI decode (1730-1733).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** At line ~995 the paper quotes "the corpus macro average at 0.062 with a 95% interval" from one decode, directly beside paired deltas whose baseline is another decode. If the top-level files are ever refreshed, the headline table and the sweep can disagree visibly, and nothing in the document records that they come from different runs.

**Proposed fix.** Repointing summary_path, report_path and wer_ci at sweep_reports_postfix/wer_report.csv changes the printed corpus CI in @tbl-corpus-summary and possibly the micro WER and reference totals, so it needs sign-off. sweep_reports_postfix has no summary JSON, so the micro-average and totals must be computed from the report. The alternative is to state in the caption which decode each block uses. Correct line 639 to say the disfluency figures come from the pre-repair sweep's AMI dump, because the post-fix Large v3 dump was overwritten (aa6e61d).

### MS-15: Numbers typed in abstract, Methods, captions and prose that could be read from committed artefacts

`manuscript/manuscript.qmd:659` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 70926fa reads the Methods, caption and design numbers from the artefacts and adds a claims-check chunk that re-derives each number the YAML abstract types and stops the render when one disagrees, and 02079b4 corrected the three claims that had stopped holding at f2578b8. The Stage 4 rewrite (0e90917) computes the remaining figures of the prose inline, among them the shift between the two decodings (decode_shift) and MS-06's Medium delta, and resolves every PHASE2 note but the two that wait for the release. What the prose still types, by a scan of e515421's text outside code, are design constants and figures quoted from the literature, and the claims-check holds the abstract (manuscript.qmd:6357 onwards at e515421). The HTML and PDF renders of fb22ece, made for this status on 2026-10-04, complete with no error or warning.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Job 8781723 (anon_multimeeting: 400 utterances across 16 meetings, recorded in .hpc-plan.yaml at 10981d4) is in flight. If the anonymisation section is re-pointed at its artefact, the computed linkage rows update while the caption and prose still say one meeting, four speakers and chance 0.25. The same drift applies to any regenerated artefact behind the literals above.

**Proposed fix.** As proposed, with one addition: fix line 1134 now, since it is already false for four of five corpora. Either restrict it to test-clean, or compute the maximum absolute raw difference across suites from sweep_aggregate_prefix.csv against sweep_aggregate.csv and state that value.

### REGEN-01: The in-chunk regeneration command for the post-fix intervals has no --output, so running it overwrites the pre-fix condition_ci.csv

`manuscript/manuscript.qmd:1009` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. c03c37f makes --output required in evaluation/condition_ci.py, so no invocation can fall back on condition_ci.csv, and gives the post-fix command, with --bootstrap 10000 and --output condition_ci_postfix.csv, in the module docstring. The chunk comment records both committed invocations, each with its own --output (manuscript.qmd:2262-2290 at e515421), and in place of new columns 5a85147 writes a provenance sidecar beside each interval table, so condition_ci_postfix_provenance.json (9cb43e3) records the arguments and the digest of every input report. No committed number moved. The comment's stale assertion that the module defaulted to condition_ci.csv (2266-2269 at e515421) was corrected on 2026-10-06: it now says an explicit output path is required and omitting it cannot overwrite the pre-repair record.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A maintainer or reader runs the documented command to refresh the post-fix intervals. It exits 0, writes the 15 post-fix rows into output/evaluation/condition_ci.csv and leaves condition_ci_postfix.csv untouched. On the next render cci_pre_fmt("contraction_fix") reports the pre-fix cost of the defect as about +0.00 percentage points [+0.00, +0.00] instead of the committed +0.43 [+0.37, +0.50]. The "before" half of the repair narrative silently becomes the "after", and nothing in the file shows which sweep it came from.

**Proposed fix.** Add `--output output/evaluation/condition_ci_postfix.csv` to the comment at manuscript.qmd:1009-1011, and add a second line recording the pre-fix producer: `--reports output/evaluation/sweep_reports --bootstrap 10000 --output output/evaluation/condition_ci.csv`. In condition_ci.py, make --output required (or remove the default) so that no documented invocation can land on another sweep's file by accident. Fix the docstring usage at 26-29 to show the two exact committed invocations, including --bootstrap 10000. Adding reports_dir or baseline_file columns to _FIELDS is optional hardening. It changes the schema of both committed CSVs, so both files need regenerating (numbers unchanged) and the maintainer should sign off.

### REGEN-02: The published Data-availability recipe for @tbl-condition-ci points at the pre-fix sweep_reports/ directory, so it cannot reproduce the table

`manuscript/manuscript.qmd:3018` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 70926fa rewrote the Data availability paragraph to name sweep_reports_postfix/ as the source of @tbl-condition-ci and to give the full post-fix command, with the pre-repair command beside it as history, and c03c37f put the post-fix command, with --bootstrap 10000, in condition_ci.py's docstring. 687555a (merged in 0e90917) brings the paragraph in line with the required --output and gives the bootstrap_ci command over wer_report.csv, which it calls the raw report of the repaired sweep and the same file as sweep_reports_postfix/wer_report.csv (manuscript.qmd:5987-6009 at e515421). Each of the three commands reproduces its committed table, as tools/verify_regeneration.py shows (G5).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reviewer follows the Data-availability paragraph. They get the 6-row pre-fix file, in which contraction_fix has delta +0.004301 and CI [0.003676, 0.00496], and compare it with @tbl-condition-ci, which shows 15 rows and contraction_fix at +0.00 [+0.00, +0.00]. The published recipe appears not to reproduce the table. Following the module docstring instead gives 2000-replicate bounds that differ from every committed interval in the fourth decimal.

**Proposed fix.** Change the paragraph to name sweep_reports_postfix/ as the source of @tbl-condition-ci and to give `python -m evaluation.condition_ci --reports output/evaluation/sweep_reports_postfix --baseline raw --bootstrap 10000 --output output/evaluation/condition_ci_postfix.csv`. Optionally add the pre-fix command (`--reports output/evaluation/sweep_reports ... --output output/evaluation/condition_ci.csv`) as the record of the defect. Replace the docstring usage at condition_ci.py:26-29 with the two exact committed invocations, including --bootstrap 10000. This edits published manuscript text, so it needs maintainer sign-off.

### REGEN-03: The @tbl-condition-ci caption takes its replicate count from the pre-fix artefact, not the post-fix one the table is drawn from

`manuscript/manuscript.qmd:158` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 70926fa builds the caption's replicate count from condition_ci_postfix.csv itself (cci_b) and stops the render unless that file holds one count, and the setup chunk stops it unless wer_ci.csv, condition_ci.csv and condition_ci_postfix.csv share one count, so the single figure the Methods quote holds for every interval. All three files record 10,000 replicates and seed 42 at HEAD, so no number moved.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The post-fix intervals are regenerated at a different replicate count, for example with the module default of 2000 (bootstrap_ci.py:62), or the pre-fix file is overwritten as in REGEN-01. The table and its p-value floor then reflect 2000 replicates while the caption still prints "10,000 replicates" from condition_ci.csv. The caption is a plausible-looking wrong statement, and the check the code comment promises does not happen.

**Proposed fix.** In load-condition-ci, build the caption's count from `cci$bootstrap` after cci is loaded, and stop() (or at least warn) if `length(unique(cci$bootstrap)) != 1`. For the Methods sentence at 622, which claims one replicate count for every interval in the paper, check that wer_ci.csv, condition_ci.csv and condition_ci_postfix.csv all carry the same bootstrap value, and stop() if they differ, so that the single number quoted is true for all of them.

### REGEN-04: The text beside @tbl-condition-ci still says only seven per-utterance reports were kept, contradicting the 15-condition post-fix artefact it renders

`manuscript/manuscript.qmd:1151` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 70926fa rewrote the selection paragraph for the post-fix artefact and keeps the seven-report limitation for the pre-repair intervals only, and the num_word helper spells numbers up to 999. 8e1b7ff (merged in 0e90917) rewrites the multiplicity paragraph and the one on the paired intervals for the regenerated table (manuscript.qmd:2456-2555 at e515421). In it the contraction repair, the composite and every other production stage are exact nulls with intervals of zero width, and only the canonical normaliser, the deduplication window and filler removal exclude zero. The checks in load-condition-ci stop the render if the table stops bearing that out.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** On render the paragraph reads "only seven such reports were kept ..., the raw baseline together with `case_fold`, `common_phrase_fix`, ... and `whitespace_normalise`" (15 names), then "The 15 that can be paired" and "per-utterance output of the other conditions was not retained". The text is self-contradictory and describes a selection constraint that no longer applies to the table beneath it.

**Proposed fix.** Rewrite 1148-1160 for the post-fix artefact: all 15 non-baseline conditions are paired, and no condition was left out for lack of files. Keep the seven-report limitation only where the pre-fix condition_ci.csv is quoted as history. Also rewrite 1170-1180, since contraction_fix is now a zero-width null (p = 1.000) and can no longer be cited as a large effect clearing Bonferroni. Its pre-fix counterpart (cci_pre) could be cited as history instead. Re-check 1145-1146 ('Three of the five production conditions') against the post-fix rows. Make num_word handle numbers above ten, or avoid starting a sentence with a numeral. All of this is manuscript text and needs maintainer sign-off.

### REGEN-05: The committed sweep_aggregate.csv/.json cannot be produced by evaluation/sweep_aggregate.py; a manual post-processing step is uncommitted

`evaluation/sweep_aggregate.py:60` · MAJOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 6cd70c7 and 66959fd make evaluation/sweep_aggregate.py write the committed schema itself: pipeline_version from each summary's run metadata, source paths relative to the sweep directory, the pooled columns, and a JSON whose provenance block holds the SHA-256 of every input summary. 2e36bf9 regenerated both files with it from the 255 summaries of sweeps 8917985 to 8917987, replacing the grid built from C:\tmp\pf2, and tests/test_audit_eval_sweep.py checks the committed header against the writer's. A rebuild into a scratch directory from those summaries reproduces the CSV byte for byte apart from line endings, and the JSON rows exactly. The summaries were not copied into the repository, as the proposed fix asked, so only the 17 rows of Large v3 on test-clean can be checked against committed per-utterance reports (sweep_reports_postfix/). The other 238 rows rest on the copies in audit2026/sweep on ARC, whose SHA-256 match the digests sweep_aggregate.json records (all 255, checked read-only on 2026-10-04). On 6 October 2026, all 255 source summaries and 15 retained hypothesis CSVs were recovered locally through read-only SSH. Every one of the 270 files matches its remote SHA-256, and all summary digests match sweep_aggregate.json. Strict aggregation, with no incomplete-grid allowance or fallback version, reproduces the complete CSV byte for byte and every scientific JSON field and type; only aggregation time, local input path and current run metadata differ. output/evaluation/sweep_input_manifest.json (41fe712) records the name, size and SHA-256 of all 270 files and the digests of the recovery receipt and the remote checksum list. The recovery receipt (build/recovered_arc_sweep/recovery_manifest.json, whose SHA-256 the committed manifest records) and the record of the aggregation comparison (build/recovered_arc_sweep/verification_manifest.json) are kept locally, outside version control. tools/build_input_deposit.py checks the 270 files against that manifest and writes them byte for byte into one deterministic archive, with the manifest, a SHA256SUMS file and a README giving their provenance, corpus licences and use, and a git archive of decoder commit 6f9bf56 goes beside it. The two files form the data record 10.5281/zenodo.23442874, which the README, the manuscript and the software record cite: sweep_inputs_2026-10.zip, 62,808,787 bytes with SHA-256 6474ba29de744cf989328427313d377b631891892dbafd5a07f472adbe86fa51, and decoder_source_6f9bf56.zip, 8,589,655 bytes with SHA-256 b66a511905b7e648987ef2f577105cd5b95e7d6556aa4ce398dda605875c5ccb. With them, every row of the grid can be rebuilt away from ARC.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Following the documented pipeline (hpc/aggregate_sweep.sh:74-77, or the manuscript's `sbatch hpc/aggregate_sweep.sh`) produces a 12-column CSV with no pipeline_version and a provenance-dict JSON. That differs in schema from the committed files, so a rebuild-and-compare gate fails. The step that stamped `post-fix (af3bee0)` and flattened the JSON is not recorded anywhere, and 224 of the 240 rows (every non-LibriSpeech-clean or non-Large-v3 cell) cannot be checked against any committed input.

**Proposed fix.** Add a --pipeline-version option to sweep_aggregate.py (or read a version field from each wer_summary JSON if sweep.py can write one), add the field to _CSV_FIELDS and SweepRow, and keep the provenance-dict JSON format. Copy the 240 summaries out of C:\tmp\pf2 into the repository (for example output/evaluation/sweep_summaries_postfix/) before that temp directory is lost. Then regenerate both aggregates with the committed command, and record that command in hpc/aggregate_sweep.sh or docs. Write source_file as a repo-relative POSIX path. Regeneration changes the bytes of committed results files (numbers unchanged), so it needs maintainer sign-off.

### REGEN-07: The footprint ledger (captured 2026-06-27) omits the jobs that produced the WER and DER results now reported, and the manuscript lists the wrong exclusions

`evaluation/footprint.py:72` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. e3e436d recaptures the ledger after every job had finished, the last of them 8978760 at 11:38:34 on 2026-10-04, so it includes the jobs behind the WER and DER results now reported, and footprint_report.csv and footprint_summary.json are regenerated from it. tools/verify_regeneration.py rebuilds the pair byte for byte (G5). b3c5717 rewrites the manuscript's caption, scope and totals paragraphs, drops the PHASE2 notes, and replaces the check that stopped the render on the new summary, which prices each H100 by its board. The caption now charges each GPU job the maximum board power of the card in its node, 250 to 700 W, instead of an A100 SXM4's, and the only jobs left out are the seven cancelled while queued (manuscript.qmd:5378-5388 and 5417-5466 at e515421).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader takes @tbl-footprint as the cost of the sweep and diarisation results the paper reports. Those results come from jobs after 2026-06-27 that are not in the ledger: at least 13.5 GPU-hours for 8688725 alone, about a quarter of the 53.8 GPU-hours total. The stated 38 jobs and 54 GPU-hours therefore describe superseded runs, and the list of excluded work is incomplete. Regenerating from a fresh sacct ledger would change every figure in the table.

**Proposed fix.** The fix proposed in the finding is sound. Recapture the ledger with the documented sacct query up to the last reported job and add the new job names (der_sweep, submit_ami_cache jobs, anon_*, determinism_gpu, disfluency and so on) to _CATEGORY. Update PROVENANCE['captured'] and regenerate footprint_report.csv and footprint_summary.json. At minimum, correct manuscript.qmd:2678-2706 to say that the ledger covers the original (pre-fix) sweep and the original diarisation protocol, and that the post-fix WER re-runs and the rebuilt DER evaluation are excluded. Either change alters reported statistics or manuscript text, so it needs maintainer sign-off.

### DEPS-08: Manuscript R environment is unlocked: no renv.lock, no sessionInfo, and the README's package list is incomplete

`manuscript/manuscript.qmd:54` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. dc8e951 commits manuscript/renv.lock, which records R 4.6.1 and the ten packages the source calls with their dependencies, 60 in all, written by renv::snapshot in a scratch project so that manuscript/ has no .Rprofile or renv/ folder and nothing is activated. The manuscript README now lists all ten packages, R 4.1 or later, ggplot2 3.4 or later and Quarto 1.4 or later, and names R 4.6.1 and Quarto 1.10.18 for the checked render. The sessionInfo chunk the proposed fix mentioned was not added, since it would edit manuscript.qmd, and remains the author's choice.

**Why deferred.** manuscript is an end product

**Failure scenario.** Rendering on ggplot2 3.5.x (pre-S7) or a different scales/dplyr/readr release changes figure output, number formatting in inline statistics (scales::percent/number rounding) and CSV column type guessing. The submitted PDF cannot be re-rendered identically, and following the README on a clean machine fails for the missing tidyr and tibble.

**Proposed fix.** Do not run `renv::init(bare = TRUE)` in manuscript/ without care. It writes an .Rprofile that activates an empty project library, which breaks the maintainer's next render until renv::restore() is run. Either snapshot without activating (e.g. `renv::snapshot(project = 'manuscript', packages = c(...), prompt = FALSE)` and then check that no .Rprofile activation was added), or init and immediately restore/hydrate. Record `quarto --version`. A sessionInfo-writing chunk edits manuscript.qmd, so it needs sign-off. Complete the README package list.

### MS-13: No renv.lock or R version pin; README package list omits tidyr and tibble

`manuscript/manuscript.qmd:57` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. dc8e951 commits manuscript/renv.lock (R 4.6.1, 60 packages, tidyr and tibble among them) and makes the manuscript README list all ten packages the source calls, R 4.1 or later and the Quarto version, as DEPS-08 describes. The lock is a record, not an active library: rendering uses the library R already has unless the recorded versions are restored into one.

**Why deferred.** manuscript is an end product

**Failure scenario.** A reviewer renders with R 4.0: the parser fails on `\(k)`. With ggplot2 3.3, `linewidth` is ignored with a warning (hidden by `warning: false`), so figure line weights differ. A user who installs only the README list hits "there is no package called 'tidyr'".

**Proposed fix.** Commit an renv.lock (renv::init(); renv::snapshot()) with R and Quarto versions recorded. List all eight packages, R >= 4.1 and the Quarto version in manuscript/README.md.

### MS-16: Replicate count for the post-fix CI caption is read from the pre-fix CSV

`manuscript/manuscript.qmd:158` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 70926fa reads the caption's replicate count from condition_ci_postfix.csv (cci_b) and stops the render unless that file holds a single count, and the setup chunk stops it unless wer_ci.csv, condition_ci.csv and condition_ci_postfix.csv agree, so the corpus interval's count is the paired table's (see REGEN-03). All three files hold 10,000 replicates at HEAD.

**Why deferred.** manuscript is an end product

**Failure scenario.** If condition_ci_postfix.csv is regenerated with --bootstrap 20000, the table's p floors switch to <.0001 while the caption and Methods still say 10,000 replicates, taken from a file the table no longer uses.

**Proposed fix.** Read B from condition_ci_postfix.csv, stopifnot(length(unique(cci$bootstrap)) == 1), and quote wer_ci's own B for the corpus interval (or assert the two are equal).

### MS-17: Appendix B bound compares two CSVs by row position; guard tests an undefined 'sweep_dir'

`manuscript/manuscript.qmd:3110` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 70926fa joins the raw and Unicode-strip reports by utterance id with inner_join(by = "name") and stops the render unless the join keeps every row of both, and the exists("sweep_dir") guard is gone. 4ae5710 (merged in 0e90917) applies the same join to the first sweep's reports as well, and on the regenerated reports (2e36bf9) the repaired strip changes the score of none of the 2,620 utterances, which the paragraph now says in words (manuscript.qmd:6173-6229 at e515421).

**Why deferred.** manuscript is an end product

**Failure scenario.** If this chunk is re-pointed at other reports (as MS-05 requires) and one file is ordered differently or drops an utterance, element-wise comparison pairs different utterances and prints a plausible bound with no warning. In an interactive knit, a global `sweep_dir` makes have_stale TRUE even when the directory is absent, and sr() then errors.

**Proposed fix.** Join s_raw and s_uni with inner_join(by = "name") and stopifnot(nrow(joined) == nrow(s_raw), nrow(s_raw) == nrow(s_uni)). Remove `exists("sweep_dir")`.

### EWER-13: Sweep default condition lists are two identical hand-typed strings that omit the registered pronoun_i_fix stage, with docstrings describing a difference that does not exist

`evaluation/sweep.py:81` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 6cd70c7 left one default condition list, c4f3133 defines evaluation.conditions.default_sweep_conditions(), which builds it from transcription.CLEAN_TEXT_STAGES, and 0d77156 makes the sweep use it and corrects the run_sweep docstring, so pronoun_i_fix is scored. tests/test_audit_eval_sweep.py checks that the defaults are every registered condition in production order, and 1b41be0 has the submit_sweep.sh header name evaluation.conditions as the function's module. The re-run sweep (2e36bf9) added 15 pronoun_i_fix cells, each equal to raw because the scoring normaliser folds case, and 9cb43e3 its interval, 0.00 [0.00, 0.00]. 02079b4 adds the stage to the manuscript's condition list, and the Stage 4 rewrite (bd5d563, 4ae5710) drops the Methods exception for it and has Appendix B say that the sweep scores each of the ten steps, the pronoun rule included (manuscript.qmd:1431-1441 and 6164-6171 at e515421).

**Why deferred.** The complete fix would change a committed number or artefact. One default condition list now exists, and a test pins the omission of pronoun_i_fix. Adding it would add cells to the committed grid.

**Failure scenario.** Re-running the sweep with defaults after the July pronoun split still never scores pronoun_i_fix on its own. pipeline_full then includes a stage whose contribution the atomic layer cannot show, and test_registry_covers_production_stages passes while sweep coverage lags. Anyone reading run_sweep's docstring or submit_sweep.sh gets the wrong condition set.

**Proposed fix.** As proposed. Derive the condition names from transcription.CLEAN_TEXT_STAGES (strip the leading underscore) inside one default constant, fix both docstrings and the submit_sweep.sh header, and correct the manuscript R comment to say the post-fix re-run used defaults that omitted the stage. The comment edit is non-rendered, but it is still manuscript text.

**Diff proposed by the implementer.**

    evaluation/sweep.py _DEFAULT_CONDITIONS: add pronoun_i_fix after sentence_capitalise; update tests/test_audit_eval_sweep.py. Rescore every suite and model from the hypothesis dumps, then sweep_aggregate and condition_ci on sweep_reports_postfix.

### EWER-15: Duplicated helpers and retyped registries across benchmark_wer, sweep, sweep_aggregate, wer and conditions, with filler inventories that have already drifted

`evaluation/sweep.py:359` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 6cd70c7 gives evaluation/sweep_aggregate.py the sweep's own model_slug and builds its corpus-to-suite map from the suite registries, so a newly registered suite is labelled without a retyped table. tests/test_audit_eval_sweep.py checks that the slug has one definition and that the sweep's parsing and path helpers agree with benchmark_wer's. c4f3133 sets the five filler inventories side by side in evaluation/conditions.py, with the reason each differs, but does not reconcile them. filler_strip (conditions._FILLER_RE) still removes erm, uhm, hm and lengthened spellings that the production list (transcription.FILLER_TOKENS) never brackets, and leaves uhuh, uhhuh and the hyphenated backchannels alone. Reconciling them would move the filler_strip cells, and on 17 October 2026 the author decided to keep the declared scorer and conditions (NEW-11), so the inventories stay cross-referenced and unreconciled.

**Why deferred.** The complete fix would change a committed number or artefact. Registries and helpers are consolidated with parity tests. The three filler lists are cross-referenced but not reconciled, because reconciling them moves the filler_strip cells.

**Failure scenario.** A change to the path convention in one module (e.g. fixing EWER-11) leaves the other writing old names. Adding a suite to challenge_suites leaves sweep_aggregate unable to label it (it falls back to stem matching, EWER-01). filler_strip removes 'erm', 'uhm' and 'hm' that the pipeline never brackets, so the filler_strip vs filler_bracket contrast the docs describe compares different vocabularies.

**Proposed fix.** As proposed. When unifying the filler lists, decide explicitly whether filler_strip should match the production inventory, because changing _FILLER_RE changes the filler_strip cells and needs a rescore and sign-off.

**Diff proposed by the implementer.**

    Build conditions._FILLER_RE from transcription.FILLER_TOKENS, or document the differences as intended. Rescore filler_strip from the dumps, then sweep_aggregate and condition_ci_postfix.

### TESTS-10: The VAD end-boundary refinement behind the committed evaluation_vad_refine result has no unit test, and its caller's docstring contradicts it

`evaluation/benchmark_timestamps.py:112` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 396e7e8 adds unit tests for _refine_end_with_vad in tests/test_audit_eval_timestamps.py (a later end extends the boundary, an earlier one never pulls it in, no speech and a raising VAD keep Whisper's end), beb9cd3 and a36b1d4 make the docstrings say the later end is kept, and a36b1d4 pins Silero to snakers4/silero-vad:v6.2.1, which tests/test_s1_misc_timestamps.py checks. ARC job 8917981 re-ran the VAD-refined benchmark with the pinned tag (567cfd9): every value already in output/evaluation_vad_refine/timestamp_summary.json is unchanged, and the summary now records vad_source and vad_applied. TestVadRefineAgainstPlain in tests/test_benchmark_results.py checks the committed reports row by row: the VAD extends 52 of 499 ends, pulls none earlier and changes no start or word, so a max-to-min regression would fail on regenerated data.

**Why deferred.** The complete fix would change a committed number or artefact. Unit tests for the VAD refinement are added. Pinning the Silero torch.hub tag could change the refinement behind the committed evaluation_vad_refine result.

**Failure scenario.** Someone 'fixes' the code to match the _predict_boundaries docstring by switching max to min, which is the pre-4bbed5f behaviour. No unit test fails, and the next --vad-refine run reports a very different MAE_end. The pins then fail only after the new output is committed, and they would be re-pinned as they were in aaffb81.

**Proposed fix.** As proposed, and also correct the _load_silero_vad docstring. Separately, _load_silero_vad calls torch.hub.load('snakers4/silero-vad') with no tag, so the model version behind the committed vad_refine numbers is unrecorded. Pin a release tag (for example 'snakers4/silero-vad:v5.1') and record it in the summary.

**Diff proposed by the implementer.**

    Pin torch.hub.load('snakers4/silero-vad:<tag>') in _load_silero_vad and re-run the VAD-refined timestamp benchmark.

### ESTATS-14: Inconsistent empty-input and error-handling conventions across the stats modules; timestamp aggregation reports 0.0 error at n=0

`evaluation/timestamp_metrics.py:135` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 396e7e8 makes benchmark_timestamps exit non-zero when no utterance is scored, and a36b1d4 makes timestamp_metrics.aggregate_boundary_errors return None for every metric at n = 0, which tests/test_timestamp_metrics.py checks. a8420df makes the readers in bootstrap_ci and condition_ci.compare_all raise ValueError, which each main() reports with exit status 2. 7be67a7 and c03c37f update the tests that expected SystemExit, and 0f351dd documents the exceptions. No committed number moved: every committed timestamp run scored 499 utterances.

**Why deferred.** The remaining part needs files or tests outside what this pass changed. benchmark_timestamps exits non-zero at n=0 and the zeros are documented as placeholders. Returning None at n=0 and raising ValueError in the library functions breaks existing tests that pin the old behaviour.

**Failure scenario.** If a transformers change makes the pipeline return no 'chunks', every utterance is skipped. benchmark_timestamps then prints 'MAE start : 0.0000 s' and writes a summary with perfect error figures and truncation_rate 0.0 (only n=0 signals the problem). Library callers such as tests or the manuscript's helper scripts cannot catch SystemExit from read_wer_report in the normal way.

**Proposed fix.** As proposed, and update the two tests that pin the zero dictionary. Return None for undefined metrics at n=0, have benchmark_timestamps exit non-zero when n == 0, and move SystemExit out of library functions into main().

**Diff proposed by the implementer.**

    timestamp_metrics.aggregate_boundary_errors: return None per metric at n==0 (update tests/test_timestamp_metrics.py:58,179). bootstrap_ci.read_wer_report/align_reports and condition_ci.compare_all: raise ValueError and map to exit codes in main (update tests/test_bootstrap_ci.py:127,184 and tests/test_condition_ci.py:92).

### DEPS-10: Declared version ranges admit releases the code cannot run on (pyannote.audio 4, bibtexparser 2, transformers <4.56 for the dtype kwarg)

`evaluation/benchmark_timestamps.py:166` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. f6c65da caps pyannote.audio below 4, and a63d1cb caps bibtexparser below 2 and raises the transformers floor to 4.56 in requirements.txt and preflight._TRANSFORMERS_FLOOR together, which tests/test_audit_core_fixes.py checks. 9586a63 and 6f9bf56 choose the token keyword from the loader's signature in one helper, evaluation/hub_loading.token_kwargs, which benchmark_der, benchmark_anonymisation, the fine-tuning script and setup_pyannote.py call, and 53254ff removed the in-job installs from submit_benchmark_timestamps.sh. The pyannote.audio floor stays at 3.1.0, not the proposed 3.4, and whether 3.1 to 3.3 accept the `<repo>@<sha>` revision spelling, which 6f9bf56 checked against 3.4.0 only, is unverified. The job environment's transformers 4.57.1 and pyannote.audio 3.4.0 lie inside every new bound, so no committed result changed.

**Why deferred.** The remaining part needs files or tests outside what this pass changed. benchmark_timestamps refuses transformers older than 4.56, and requirements.txt caps pyannote.audio below 4. Still open: raising the transformers floor to 4.56 in requirements.txt and preflight together, one token-keyword helper for the pyannote loaders, and dropping the in-job transformers install in hpc/submit_benchmark_timestamps.sh (an environment change).

**Failure scenario.** A fresh `pip install -r requirements.txt` resolves pyannote.audio 4.x, and benchmark_der.load_pipeline raises TypeError on `use_auth_token`. When bibtexparser 2.0 final ships, bib_sentencecase exits with code 2. On any transformers 4.45-4.55 env that passes preflight, the ASR pipeline's _sanitize_parameters rejects `dtype` with a TypeError. All three failures are loud, but each wastes a GPU queue slot.

**Proposed fix.** As proposed, minus the finetune script, which already falls back. Put the token-kwarg fallback in one helper, reusing the transcription.py:1814-1829 pattern, and call it from benchmark_der and benchmark_anonymisation. Bound pyannote.audio>=3.4,<4 and bibtexparser>=1.4,<2. Either raise the transformers floor to 4.56 (and preflight's _TRANSFORMERS_FLOOR) or use torch_dtype consistently.

**Diff proposed by the implementer.**

    requirements.txt transformers floor 4.56 with preflight _TRANSFORMERS_FLOOR=(4,56); a shared token-kwarg helper (the transcription.py inspect.signature pattern) used at benchmark_der.py and benchmark_anonymisation.py; remove the transformers install from submit_benchmark_timestamps.sh.

### OUTPUTS-12: Committed evaluation artefacts record no code commit and almost no package versions

`evaluation/sweep_aggregate.py:253` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Partly resolved. fa6bf45 adds provenance.run_metadata() (git commit, dirty flag, Python and package versions), now recorded in wer_summary.json, sweep_aggregate.json, the timestamp, anonymisation, disfluency, FLEURS, reconstruction-audit and masking summaries, the four DER summaries of the re-runs at 9cb43e3 (70933b4), the cross-hardware determinism comparison and each interval table's provenance sidecar (5a85147). ce2f1ff, 2ed5f28, ef7da7c, 1119a5c and c597599 read the git state before the first output and leave a writer's own outputs out of the dirty check, fleurs_diacritics included since c597599, which tests/test_provenance_in_place.py and tests/test_provenance_in_place_writers.py check. Two writers can still count their own output as a change, fleurs_multilingual on purpose and evaluation.sweep under --legacy-primary-paths from its second suite on (1119a5c), and sweep_der.py records only the commit and the pyannote.audio version. determinism.py, footprint.py, audit_artefacts.py and benchmark_podcast.py record neither, though the case study's runs can now be told apart, since its committed run manifest records the commit, a clean tree and the package versions: c4c7b38 for job 8983112 (ac08cdc), and fc652ab for job 9124852, whose manifest replaced it on 18 October 2026. The torch 2.8.0+cpu and transformers 4.56.2 named in the failure scenario below are the account's ~/.local packages (DEPS-02), and the re-run wave's environment records show torch 2.5.1+cu121 and transformers 4.57.1.

**Why deferred.** The complete fix would change a committed number or artefact. Adding a code-version and package-version record to each artefact changes the bytes of every regenerated summary, so it waits for the next re-run. Jobs now write an environment/ record beside their results (hpc/common/arc_common.sh), and the transcription manifest records the git commit and package versions.

**Failure scenario.** This has already caused trouble: the aa6e61d message says a missing version field cost a fortnight. The committed case-study summary (408 segments) and ARC's later one (405) cannot be distinguished by content (OUTPUTS-08). The versions actually used (torch 2.8.0+cpu, transformers 4.56.2, pyannote.audio 3.4.0) cannot be reconciled with the README's torch 2.5.1 from the artefacts, and a future re-run under a different transformers version would look identical.

**Proposed fix.** Add one helper, e.g. provenance.run_metadata(), returning the git commit and dirty flag (git rev-parse HEAD, git status --porcelain), Python version, and versions of torch, transformers, pyannote.audio, jiwer, datasets and numpy via importlib.metadata. Embed it in every evaluation JSON summary, and as a sidecar *_provenance.json or constant columns for CSV-only writers (condition_ci, bootstrap_ci, footprint). Add a test that each writer includes it. Existing artefacts gain the field as they are regenerated.

**Diff proposed by the implementer.**

    provenance.run_metadata() returning git commit, dirty flag, Python and torch/transformers/pyannote.audio/jiwer/datasets/numpy versions; call it from benchmark_wer._write_summary, the benchmark_timestamps summary and the sweep_aggregate provenance block; give condition_ci, bootstrap_ci and footprint a *_provenance.json sidecar.

### EDER-24: An interrupted run leaves a new partial report beside the previous run's summary in the same directory

`evaluation/benchmark_der.py:439` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 5722c7b makes benchmark_der write der_report.csv and der_summary.json, and sweep_der its three files, under .partial names and move them into place together only when the run finishes. It also stops a run that scored no meeting instead of writing a macro DER of 0.0, and tests/test_audit_der_outputs.py checks that an interrupted run or sweep leaves the previous set in place. On the manuscript side, 70926fa added stopifnot(nrow(der_report) == der_summary$n_meetings) at manuscript.qmd:2278. The shared run_id the proposed fix also asked for was not added, and the atomic replace and that row check stand in for it. Final file contents are unchanged, and every committed DER report has as many rows as its summary's n_meetings (16).

**Why deferred.** The complete fix would change a committed number or artefact. Partial reports are now written as .partial and moved into place together. The manuscript-side consistency check is in manuscript.qmd, which only the author edits.

**Failure scenario.** A `sbatch hpc/submit_benchmark_der.sh` job hits its 12 h walltime or an OOM after 9 of 16 meetings. REPORT_DIR then holds a 9-row der_report.csv from the new configuration beside der_summary.json from the previous configuration. If they are copied into output/evaluation, the manuscript computes the per-meeting range and overlap correlations from one run and the headline from another, silently, with nothing flagging the mismatch.

**Proposed fix.** Write to der_report.csv.partial and der_summary.json.partial and os.replace both only after the loop completes, or delete the old summary before truncating the report. Record a shared run_id and n_meetings in both files, and have the manuscript's R chunk assert nrow(der_report) == der_summary$n_meetings. Do the same for the sweep outputs.

**Diff proposed by the implementer.**

    manuscript.qmd R chunk (~1774): stopifnot(nrow(der_report) == der_summary$n_meetings).

### DEPS-16: Model and dataset IDs are retyped across ~10 files, so pinning a revision in one place is not enough

`evaluation/benchmark_der.py:88` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. fa6bf45 adds evaluation/revisions.py, one registry giving each Hub model and dataset a pinned commit, and the loaders take their revision from it: the benchmarks (66be1de), setup's Whisper download and pre-cache (5882007) and every pyannote caller through evaluation/hub_loading.py (6f9bf56). setup/cache_pyannote_arc.py checks the snapshot it caches against the registry (20ee3b6), so the cache script and the benchmarks can no longer ask for different revisions. The ids stay typed in their files by choice, and tests/test_revision_registry_coverage.py (f064a8a) fails unless every Hub id quoted in the Python sources is pinned in the registry or listed with its reason. On ARC each cached repository holds one snapshot, the pinned commit (checked read-only for the three Whisper models, AMI and the three pyannote repositories), so no committed number changed.

**Why deferred.** The remaining part needs files or tests outside what this pass changed. Within the DER files the AMI dataset and segmentation model are single constants. A repository-wide registry of model and dataset revisions needs about ten files and a Hub lookup to fill in the revisions.

**Failure scenario.** When DEPS-04 is fixed by adding `revision=` in benchmark_der.py but not in benchmark_anonymisation.py or cache_pyannote_arc.py, the cache script downloads main while the benchmark asks for a pinned SHA. The offline compute node then either fails, or the anonymisation benchmark silently uses a different pyannote revision from the DER benchmark it is compared with.

**Proposed fix.** Create one registry (e.g. evaluation/revisions.py or a models.toml) mapping each logical model and dataset to `(repo_id, revision)`. Import it in the Python modules and read it in the shell scripts via `python -c`. Delete the duplicated literals.

**Diff proposed by the implementer.**

    evaluation/revisions.py mapping logical names to (repo_id, revision); import it in benchmark_der, benchmark_anonymisation, benchmark_timestamps, challenge_suites, sweep_aggregate, transcription.py and setup/*; read it from shell via python -c.

### XREF-07: Audio decoding, resampling and WAV I/O are duplicated across modules, and the copies behave differently

`evaluation/ami_meetings.py:116` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. One AMI decoder, ami_meetings.decode_audio_bytes, now serves benchmark_der, benchmark_timestamps, the anonymisation benchmark and the fine-tuning script (f952e78, 0e81629), and voice_anonymisation reads and writes WAV through audio_redaction's helpers, which raise ValueError on anything but 16-bit PCM (bdeb957). ami_meetings warns whenever it has to resample a clip that is not 16 kHz (3f2db7e), and 1ee01a4 rounds the output length of benchmark_wer's numpy fallback resampler. tests/test_audit_der_shared.py, tests/test_audit_priv_wav_io.py and the TestResamplingIsAnnounced tests in tests/test_audit_der_reconstruction.py guard the shared decoder, the shared WAV reader and the warning. The WER harness keeps its own librosa decoder, but every corpus scored is 16 kHz and the job environment has librosa, so no committed number came through either path.

**Why deferred.** The complete fix would change a committed number or artefact. The AMI decoder is now shared by benchmark_der, sweep_der, finetune and benchmark_timestamps, and the WAV helpers by audio_redaction and voice_anonymisation. benchmark_wer's numpy resampling fallback still truncates the output length.

**Failure scenario.** Feed a corpus or AMI cache that is not 16 kHz (e.g. a 44.1 kHz podcast for the case study, or a future 48 kHz split). The DER/anonymisation harnesses (ami_meetings, linear interpolation with no anti-aliasing) and the WER harness (librosa soxr on ARC's librosa 0.11.0) then feed the model different waveforms for the same audio, so cross-harness comparisons move for reasons unrelated to the model. A 24-bit WAV raises a catchable ValueError in audio_redaction but terminates the process in voice_anonymisation. Today's corpora are all 16 kHz, so no committed number is affected yet.

**Proposed fix.** Share one decode helper and one WAV reader with one exception type, as proposed. For resampling, either import audio_io's resampler, or keep ami_meetings' dependency-free interpolation and have it warn or raise on sr_in != 16000, so a non-16 kHz AMI cache cannot be silently resampled differently from the WER harness. Change benchmark_wer's fallback to round(), matching the other two.

**Diff proposed by the implementer.**

    benchmark_wer.py resample fallback: new_len = int(round(len(arr) * ratio)). It only runs without librosa; re-run is needed only if a committed run used the fallback.

### CORE-21: Preflight's CUDA remedy hard-codes the cu121 wheel index, which cannot serve the torch/torchaudio versions installed on ARC

`preflight.py:173` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. c273a61 derives preflight's CUDA remedy from the installed torch, naming torch and torchaudio (and torchvision when present) at matching versions and the index that publishes that torch series, or describing the constraint when no index is known, and tests/test_audit_core_fixes.py checks the 2.8.0+cpu and 2.5.1+cu121 cases. 53254ff removed three of the four torch self-heals from the live hpc/ scripts and ea0ddd3 the sweep job's, and the GPU jobs now stop when their preflight fails instead of reinstalling torch. Only a retired script in hpc/legacy/, which exits before doing anything, keeps the old block. 20ee3b6 makes setup/setup_environment.sh install requirements-lock.txt with the cu121 index instead of an unpinned torch. tests/test_s1_env_jobs.py fails if a live job or helper installs a package, and since 1496c64 removed a stale _OTHER_BRANCH entry from c0f2258 the check covers hpc/submit_anonymisation.sh too.

**Why deferred.** The complete fix would change a committed number or artefact. preflight now derives the correct CUDA wheel index. The hpc self-heal blocks still reinstall from the cu121 index, and changing what jobs install is an environment change.

**Failure scenario.** On a node where CUDA is unavailable, a user or submit_sweep.sh follows the remedy. pip installs the newest torch on the cu121 index (2.5.1+cu121) over 2.8.0, leaving torchaudio 2.8.0 and torchvision 0.23.0. torchaudio then refuses to import against the mismatched torch, and pyannote.audio 3.4.0 fails with it. Following the diagnostic turns a CPU-only environment into a broken one.

**Proposed fix.** As proposed. Derive the pins from the installed torch version, or name the constraint without a runnable command, keeping one shared constant for preflight and the hpc scripts. Update tests/test_preflight.py:72 to match. In the hpc self-heal blocks, reinstall torch, torchaudio and torchvision together at matching versions from an index that publishes them.

**Diff proposed by the implementer.**

    In hpc/submit_sweep.sh, submit_benchmark_timestamps.sh, submit_benchmark_wer_gpu.sh, submit_pilot_benchmark.sh, submit_finetune_pyannote.sh and setup/setup_environment.sh, reinstall torch and torchaudio together at the installed version from the index preflight.cuda_reinstall_remedy names, or drop the self-heal (see DEPS-03).

### SHELL-10: The environment boilerplate is copied into 18 scripts in four drifted variants; one sourced helper would remove the drift

`hpc/submit_der_sweep.sh:55` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 53254ff gathers activation, the pinned module loads, the GPU and CPU preflight gates and the token lookup into hpc/common/arc_common.sh (arc_activate, arc_require_gpu, arc_preflight, arc_load_hf_token), moves ten job scripts onto it and removes three of the four torch self-heals in the same documented commit. ea0ddd3 moves the sweep, aggregation and WER-scoring jobs onto it, removing the sweep's self-heal, c0f2258 the case-study and determinism jobs and 76d9489 the anonymisation job. bc0702a writes the CPU determinism arm on the helper, which ee2cc14 had created to write each result-producing job's environment record beside its results. All 17 job scripts in hpc/ now call arc_activate (the 18th, submit_transcription.sh, is the login-node wrapper), and the re-run wave's environment records name the pinned Anaconda3/2025.06-1 and CUDA/13.0.2 modules. tests/test_s1_env_jobs.py checks that every job uses the shared gate and stops when it fails, submit_anonymisation.sh included since 1496c64 removed a stale _OTHER_BRANCH entry from c0f2258 that left it out.

**Why deferred.** The complete fix would change a committed number or artefact. hpc/common/arc_common.sh exists and records each job's environment. Consolidating activation and GPU checks would remove the torch self-heal in four scripts, which changes the environment those jobs run in.

**Failure scenario.** Fixes land in one copy and not the others. The 25068a8 and preflight changes reached submit_sweep.sh, but the DER jobs still run without preflight (SHELL-05), and the timestamp job still force-reinstalls torch. The next CUDA or token fix must be applied 18 times, and a missed copy fails differently from the rest.

**Proposed fix.** As proposed. Land the helper first with behaviour equal to the preflight-abort variant, and remove the self-heal in the same change, documented, so the environment change is deliberate rather than a refactoring side effect.

**Diff proposed by the implementer.**

    Add arc_activate, arc_require_gpu and arc_load_hf_token to hpc/common/arc_common.sh; replace the module/activation/GPU/token blocks in the 18 scripts; delete the pip uninstall/force-reinstall blocks in the same documented commit. Verify with one SWEEP_LIMIT=10 pre-flight per GPU script into a scratch directory, diffing its environment/ record against a pre-change job.

### DEPS-02: ~/.local user site on ARC shadows the job env (torch 2.8.0+cpu, transformers 4.56.2) unless PYTHONUSERBASE is set; the audit's own ARC freeze is wrong because of it

`activate_project_env_arc.sh:14` · MAJOR · verified plausible

**Status.** Resolved. 63e3fb6 exports PYTHONNOUSERSITE=1 in activate_project_env_arc.sh, which tests/test_s1_env_activation.py checks, 40b5846 stops ensure_names_dataset putting the user site on sys.path, and 355a90c deleted hpc/activate_env_template.sh. a63d1cb adds a preflight check that torch, transformers and pyannote load from the environment, which the test_isolation_* tests in tests/test_s1_env_preflight.py check, and 0897495 re-took requirements-lock.txt inside the job environment. Every job sources the activation script, and on ARC test job 8978757 (2026-10-04) passed that check and matched all 178 pins of the lock, while all 45 environment records read from the re-run wave show the user site disabled and torch 2.5.1+cu121 and transformers 4.57.1. A shell that has not sourced the script still meets the failure scenario, since ~/.local on ARC still holds torch 2.8.0+cpu and transformers 4.56.2 and the environment's Python imports both from there (checked read-only on 2026-10-04). On 17 October 2026 the author decided to leave ~/.local as it is, since every job sources the activation script that disables it.

**Why deferred.** The complete fix would change a committed number or artefact. Changes the Python path of every job. The new environment record already writes where torch and transformers load from, so the next job shows whether ~/.local shadows the environment.

**Failure scenario.** Any ARC shell that does not source the activation script silently imports CPU torch 2.8.0 and transformers 4.56.2 from ~/.local instead of the env's 2.5.1+cu121 / 4.57.1. That covers an interactive rescoring of dumped hypotheses, a lockfile regeneration, an ssh one-liner, or an audit freeze. CPU-only work such as whisper_norm rescoring (transformers EnglishTextNormalizer) then runs on a different stack and produces plausible numbers. This has already happened once: the ARC freeze supplied to this audit records the wrong environment.

**Proposed fix.** Add `export PYTHONNOUSERSITE=1` to activate_project_env_arc.sh and hpc/activate_env_template.sh. Delete the ensure_names_dataset sys.path block, because it re-adds the user site precisely when PYTHONNOUSERSITE is set. Add a preflight check that torch/transformers/pyannote __file__ lie under sys.prefix. Treat the ~/.local contents as unverified until re-checked with `python -m pip list` versus `python -s -m pip list`.

**Diff proposed by the implementer.**

    activate_project_env_arc.sh: export PYTHONNOUSERSITE=1; delete the PYTHONPATH line naming a non-existent python3.11 site-packages. preflight: FAIL when torch/transformers/pyannote load from outside sys.prefix.

### DEPS-03: SLURM jobs change the shared env at runtime: unpinned pip installs and a self-healing force-reinstall of torch

`hpc/submit_benchmark_wer_gpu.sh:112` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 53254ff and ea0ddd3 remove every in-job pip install, uninstall and torch force-reinstall from the live job scripts, and with c0f2258 and 76d9489 they move the jobs onto the shared helper, which loads Anaconda3/2025.06-1 (and CUDA/13.0.2 for GPU jobs) by version and stops a job whose preflight fails. ee2cc14 has each result-producing job write its environment record, with pip list --format=freeze and nvidia-smi output, beside its results. The re-run wave ran this way, and the record of timestamp job 8917980, for example, names the pinned modules, an H100 80GB HBM3 and torch 2.5.1+cu121, while test job 8978757 found every one of the 178 locked versions installed. tests/test_s1_env_jobs.py fails if a live job or helper installs a package, hpc/submit_anonymisation.sh included since 1496c64 removed a stale _OTHER_BRANCH entry from c0f2258 that left it out.

**Why deferred.** The complete fix would change a committed number or artefact. Every result job now records pip list, nvidia-smi, the torch and CUDA builds and the git commit. Removing the in-job installs and the torch self-heal changes the job environment.

**Failure scenario.** One array task finds CUDA shadowed by the unversioned `module load CUDA` and uninstalls and reinstalls torch while sibling tasks in the same env are importing it. That gives mid-run library swaps or a torchaudio/torch ABI mismatch, which the finetune script even anticipates. Every later job then runs on a different torch build. Committed results end up spanning torch builds with no record of which produced which. An import failure also silently pulls the latest datasets/transformers plus their fsspec/pyarrow upgrades into the env.

**Proposed fix.** As proposed: remove every in-job pip install/uninstall and make the preflight failure exit non-zero. Pin or drop `module load CUDA`, since the cu121 wheels bundle the runtime, and pin Anaconda3. Write `python -s -m pip list --format=freeze` and nvidia-smi output into each job's output directory. Also add preflight to the scripts that lack it (see DEPS-05).

**Diff proposed by the implementer.**

    Delete the `python -c 'import X' || pip install ...` lines in the GPU submit scripts and replace the torch reinstall blocks with `python -m preflight --gpu-required || exit 2`. Re-run a pre-flight per script type.

### DEPS-14: Dockerfile: mutable base tag, unpinned apt and pip, Python 3.10 below the >=3.11 floor, and most modules missing, so features silently degrade

`setup/Dockerfile:1` · MAJOR · verified confirmed

**Status.** Partly resolved. ef99ffd copies every module the container needs and stops setup reporting false success, and 20ee3b6 pins the base image nvidia/cuda:12.1.1-devel-ubuntu22.04 by the manifest-list digest its tag resolved to on 2026-09-26, installs Python 3.12 in a virtual environment, installs requirements-lock.txt with the cu121 index and runs python -m preflight --lock at build time. The apt packages are still unpinned, a TODO in the Dockerfile header, and the image has never been built, because no container runtime exists locally or on ARC, so whether the file builds is unverified. No committed result came from the container.

**Why deferred.** The complete fix would change a committed number or artefact. The Dockerfile header and missing modules are fixed. Pinning the base image by digest needs a registry lookup, and changing its Python version or pins changes the image contents; no container runtime exists locally or on ARC to verify a build.

**Failure scenario.** `docker build -f setup/Dockerfile .` then running on a recording completes "successfully" but produces no *_manifest.json and no review.json, and it cannot open .m4a. Rebuilding later pulls a different CUDA base, apt packages and PyPI versions, so two images from the same Dockerfile are different experiments.

**Proposed fix.** Pin `FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04@sha256:<digest>`, or a `python:3.12-slim-bookworm@sha256:<digest>` base with cu121 wheels. Install Python 3.12. `COPY` all top-level modules (or `COPY . .` with a .dockerignore). Install from requirements-lock.txt. Pin apt via snapshot.ubuntu.com or explicit `=version`. Run `python -m preflight` at build time. Pass the image digest into the provenance block.

**Diff proposed by the implementer.**

    docker buildx imagetools inspect nvidia/cuda:12.1.1-devel-ubuntu22.04, then FROM ...@sha256:<digest>; install Python 3.12; pip install -r requirements-lock.txt; pin apt via snapshot.ubuntu.com; RUN python3 -m preflight as a smoke test.

### TESTS-01: hpc/run_tests.sh last ran on 2026-05-16, so the jiwer and pyannote tests that guard committed results have no recorded run

`hpc/run_tests.sh:4` · MAJOR · verified plausible

**Status.** Resolved. 7dc96aa makes hpc/run_tests.sh run pytest with -rs, so every remaining skip is printed with its reason. The suite has since run to completion on ARC four times, each with one skip, tests/test_s1_misc_footprint.py:159, which needs a committed sacct dump, and one expected failure. Jobs 8917831 at eaef44a (1,649 passed) and 8918061 at d0edd03 (1,658), which 9cca826 records in hpc/README.md, ran in September, and 8978757 at f2578b8 (2,032) and 8983111 (2,058), from a clone that includes ca75ced, ran on 2026-10-04. Two earlier runs, 8913985 and 8917186, overwrote the cached pyannote pipeline config on ARC (NEW-INC-01), and efa2962, d41cd96 and 109e7ab now keep the tests out of every real model cache. d63aa57 makes the preflight fail a diarisation job whose cached config cannot load, and after both October runs the config's blob still hashed to its own name (git hash-object on ARC, read-only). Later runs are recorded in hpc/README.md: 9124851 (fc652ab; one expected failure, the case-study count) and 9134598 (c17367b, the release tree: 2,367 passed, 1 skipped, 1 xfailed).

**Why deferred.** The next step needs the author's decision or an ARC run. hpc/run_tests.sh now reports every skip. The last ARC run of the suite was 2026-05-16; submitting it on ARC, where the 24 locally skipped tests can run, needs the author's go-ahead.

**Failure scenario.** Pooled micro_wer in evaluation/wer.py aggregate, or DER component normalisation in der_metrics.compute_der, regresses. The local suite stays green because those tests skip without jiwer or pyannote. Nothing runs them on ARC either, so the regression reaches the next committed sweep and the manuscript unnoticed.

**Proposed fix.** As proposed. Also make the gate record which tests skipped (for example `pytest -rs` output archived next to the results commit), not just the pass count.

### TESTS-02: run_tests.sh changes the shared ARC env that produces the results: unconditional pip upgrade and unpinned installs

`hpc/run_tests.sh:62` · MAJOR · HIGH-RISK · verified plausible

**Status.** Resolved. 53254ff removes the pip upgrade and the jiwer, pyannote.audio and bibtexparser installs from hpc/run_tests.sh, which now runs python -m preflight --lock requirements-lock.txt and stops with exit 2 if any installed version differs from the lock, and with ea0ddd3 it removes every other in-job install from the live job scripts. In tests/test_s1_env_jobs.py, test_run_tests_checks_the_lock_instead_of_installing checks run_tests.sh, and test_no_live_job_or_helper_installs_packages checks every live job, hpc/submit_anonymisation.sh included since 1496c64 removed a stale _OTHER_BRANCH entry from c0f2258. On ARC, test job 8978757 (2026-10-04) passed the lock check, all 178 pins matching, before pytest started.

**Why deferred.** The complete fix would change a committed number or artefact. hpc/run_tests.sh still pip-installs missing packages into the shared results environment; removing that changes the environment.

**Failure scenario.** The env is rebuilt without pyannote, or the import fails and the package is later uninstalled. Running the test job then installs the newest pyannote.audio matching >=3.1 (a 4.x release with different torch requirements) and a newer jiwer. The next benchmark_der or benchmark_wer job on that env runs under different library versions than the pinned committed results, with no error. Separately, `--upgrade pip` alters the env on every test run.

**Proposed fix.** Remove the install lines from run_tests.sh and fail fast on version mismatch, as proposed. Do the same in every hpc/submit_*.sh that installs into the shared env (datasets, soundfile, transformers, pyannote.audio, and the torch force-reinstall). Pin exact versions from the recorded ARC freeze in a lock/constraints file (pip install -c constraints.txt) instead of lower bounds in requirements.txt.

**Diff proposed by the implementer.**

    Replace the installs with a version check against requirements-lock.txt that exits non-zero on a mismatch.

### EPRIV-25: Artefact audit's case-sensitive verbatim scan cannot see the masker's main measured leak (lower-case names)

`evaluation/audit_artefacts.py:240` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 790c3bd strips a trailing possessive from each logged name and adds a case-insensitive pass, which tests/test_s1_misc_audit_artefacts.py covers. Its matches go to a separate leaked_names_casefold column and count as masked_artefacts_casefold_only without setting residual_pii_found. b7fcdd6 regenerated the committed audit over example_output, and 12275ed again after adding a README there. The new column is empty for all 39 files, and the finding is unchanged, with two behind_the_curtains transcripts leaking a name and no raw artefact leaking.

**Why deferred.** The complete fix would change a committed number or artefact. A case-insensitive leak column changes the bytes of artefact_audit.json (every new list is empty on example_output).

**Failure scenario.** A transcript says "Pablo introduced the talk ... thanks, pablo". The log records 'Pablo' (masked), the masked .txt still contains 'pablo', and the audit prints 'clean: no logged original name found'. The committed audit of example_output may likewise undercount leaking files.

**Proposed fix.** Add a case-insensitive pass reported in a separate leaked_names_casefold column, so common-word false alarms stay distinguishable, and strip trailing possessives from logged originals. No regeneration of the committed audit is needed, since the result is unchanged.

**Diff proposed by the implementer.**

    audit_artefacts: add leaked_names_casefold per file and strip possessives in _strip_name_token; regenerate artefact_audit.json.

### EWER-16: Dead code: `if False:` type-checking block, the test-only _postprocess_hypothesis alias, the legacy --report-postprocessed/--summary-postprocessed path, the test-only _SLUG_RE, and unused package re-exports

`evaluation/benchmark_wer.py:65` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. d8cb7c8 replaces the if False block with TYPE_CHECKING, e06fcea makes condition and suite registration enforce the documented slug pattern, and 66be1de removes the --report-postprocessed and --summary-postprocessed flags with their second naming rule, together with the _postprocess_hypothesis alias that the Why deferred paragraph below still describes as kept. The tests in tests/test_audit_eval_wer.py check that the flags and the alias are gone and that a name such as 'Pipeline-Full' is refused. The evaluation package's re-exports stay, now resolved lazily, as the proposed fix allows until the author confirms that no external user depends on them.

**Why deferred.** The remaining part needs files or tests outside what this pass changed. if-False, the legacy summary path and slug checks are fixed. The test-only _postprocess_hypothesis alias stays because tests/test_benchmark_wer_conditions.py still uses it.

**Failure scenario.** The legacy branch keeps a second output-naming contract alive (report_pp defaults to primary_report when only --summary-postprocessed is given, L707-708, so the repetition_fix CSV overwrites the raw CSV). A future edit can reintroduce that collision unnoticed because no pipeline exercises it. A condition registered with an invalid slug such as 'Pipeline-Full' is accepted despite the documented constraint.

**Proposed fix.** As proposed. If the legacy flags are kept, at minimum fix L707-708 to derive a distinct report path (e.g. via _derive_condition_paths). Keep the __init__ shim unless the maintainer confirms that no external users depend on it.

### SHELL-08: Script defaults do not reproduce the committed anonymisation, determinism or DER-sweep results, and the values actually used are recorded nowhere in the repo

`hpc/submit_anonymisation.sh:67` · MAJOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 86543a0 records the invocation behind each committed result in hpc/runs/*.env and points each script header at its record, and c988b47 gives every record its own directory under repro/, which tests/test_audit_shell_review_fixes.py checks. 5b66fda runs each published anonymisation configuration from one preset (ANON_PRESET), e960d83 gives sweep_der an --output-prefix and writes its grid and argv into the selection JSON, and c0f2258 decodes repeats of the first determinism seed only. The two determinism runs of 2026-10-04 wrote into the directories their records named, and determinism_v100.env (ba982b9) and determinism_cpu.env (3cae28a) now give those as the originals and send a reproduction to repro/determinism_v100/ and repro/determinism_cpu/, neither of which existed on ARC. 95209a6 gives the commands of all 16 records the "|| exit 1" guard of hpc/README.md's example and has sweep.env's aggregation step source the record, and the test runs each record's commands against a stub sbatch. The scripts' own defaults are unchanged, as their headers say, so a bare sbatch hpc/submit_anonymisation.sh still runs 300 utterances at alphas 0.7, 0.8 and 0.9, and aligning them with the published runs remains the author's option.

**Why deferred.** The next step needs the author's decision or an ARC run. Defaults are unchanged; hpc/runs/*.env records the parameters behind each committed run. benchmark_anonymisation's CLI defaults now match the published run (200 utterances, alphas 0.5/0.7/0.8/0.9) but hpc/submit_anonymisation.sh keeps its own defaults (300, 0.7/0.8/0.9); aligning them changes what a bare sbatch runs.

**Failure scenario.** A reviewer runs `sbatch hpc/submit_anonymisation.sh` to reproduce the privacy curve and gets 300 utterances at three coefficients, with no alpha 0.5 row. The linkage and WER-cost figures differ from the paper and nothing says why. Running `sbatch hpc/submit_der_sweep.sh` writes an 11-configuration der_sweep_summary.csv that matches neither committed grid.

**Proposed fix.** As proposed: record the invocation per artefact (hpc/runs/*.env or a README table), add --output-prefix to sweep_der, write argv into the JSONs, and repeat only the first seed. Do not change the defaults to published values without also recording that the next run differs from them.

### EDER-FT: Fine-tuning Phase 2 is untested against a real pyannote

`evaluation/finetune_pyannote_segmentation.py:1` · MAJOR · verified observed after the audit

**Status.** Resolved. The CPU smoke test passed twice on ARC, job 8913986 and job 8918331, the second loading the base model at its pinned revision: each streamed the AMI train split (Phase 1) and fine-tuned the segmentation model for one epoch under pyannote.audio 3.4.0 (Phase 2), reaching a development DER of 0.157, as their logs show. 9cca826 records both in hpc/README.md, which asks for the same CPU run again before any GPU submission of submit_finetune_pyannote.sh.

**Why deferred.** The next step needs the author's decision or an ARC run. evaluation/finetune_pyannote_segmentation.py Phase 2 was rewritten against the pyannote.audio 3.4.0 source on ARC and tested locally against fakes only. It needs a CPU smoke test on ARC (command in the module docstring) before any GPU run.

**Failure scenario.** A GPU job fails or trains on the wrong data because the rewritten Phase 2 was checked only against fakes.

**Proposed fix.** Run the module docstring's CPU smoke test on ARC before any GPU submission.

### XREF-14: Two root licence files state incompatible terms: LICENSE is MIT, Licence.md is CC BY 4.0

`Licence.md:2` · MAJOR · verified confirmed

**Status.** Resolved. The author settled the scope on 17 October 2026. LICENSE stays MIT and covers the software, with the name dictionary it installs. Licence.md, the CC BY 4.0 legal code, is renamed LICENSE-docs.md and opens with a header naming the paths it covers: manuscript/, docs/, output/ and example_output/. The header also names the material by others that keeps its own terms: manuscript/apa.csl is CC BY-SA 3.0, and the corpus text in output/ keeps the corpora's licences. README.md's Licence section and docs/release_readiness.md state the split, and a comment in CITATION.cff says why it names only the software's licence. Every record under the Zenodo concept 10.5281/zenodo.17592924 still gives CC BY 4.0 alone (Zenodo API, 2026-10-04), so the next version should list both licences (DOCS-14).

**Why deferred.** The next step needs the author's decision or an ARC run. LICENSE is MIT, as README, setup.py and CITATION.cff say, while Licence.md holds the full CC BY 4.0 text and no split between code and documentation is stated anywhere. Either delete Licence.md, or rename it (e.g. LICENSE-docs.md), name the paths it covers, and state the split in README and CITATION.cff. The licence text was left untouched.

**Failure scenario.** GitHub's licence detector, Zenodo's metadata, or a downstream reuser sees both an MIT and a CC BY 4.0 licence at the root with no scope statement. CC BY 4.0 lacks MIT's warranty and permission-notice terms and is not designed for software, so it is unclear which licence governs the code, which the manuscript and data, and which the next Zenodo release carries.

**Proposed fix.** Decide and state the split explicitly. If the software is MIT and the manuscript and docs are CC BY, rename Licence.md to e.g. LICENSE-docs.md with a header naming the covered paths (manuscript/, docs/, example_output/). Add that to the README Licence section and CITATION.cff. Otherwise delete Licence.md. Carry the change into the next Zenodo version.

### DOCS-16: A CC BY 4.0 Licence.md still sits beside the MIT LICENSE that README and CITATION.cff declare

`Licence.md:2` · MAJOR · verified confirmed

**Status.** Resolved. With XREF-14, on 17 October 2026 Licence.md became LICENSE-docs.md, whose header states that CC BY 4.0 covers manuscript/, docs/, output/ and example_output/ and that everything else is MIT, and README.md's Licence section now names both licences.

**Why deferred.** The next step needs the author's decision or an ARC run. Same decision as XREF-14.

**Failure scenario.** A downstream user or repository scanner finds two top-level licence files with different terms. It is ambiguous whether code, docs or data fall under MIT or CC BY 4.0, and Zenodo or GitHub licence detection may report either.

**Proposed fix.** Ask the maintainer which terms they intend. Either delete Licence.md, or rename it (e.g. LICENSE-docs.md) and state the split explicitly in README 'Licence' and in CITATION.cff.

### NEW-01: evaluation.wer pairs and scores both the .txt and the .json transcript of one recording

`evaluation/wer.py:1` · MAJOR · verified observed after the audit

**Status.** Resolved. a5fa9c1 makes evaluation.wer read one hypothesis per stem, .txt first, then .json, then .vtt, or only the format --hypothesis-format names, pair each reference with one hypothesis and say on stderr which file it scored. tests/test_s1_wer_scoring.py covers a stem written in all three formats, an explicit format and two hypothesis stems for one reference. No committed report came through this path: the headline wer_report.csv is the sweep's raw cell, which benchmark_wer scored and e3cb675 copied in, so no committed number moved.

**Why deferred.** The complete fix would change a committed number or artefact. Found by the documentation pass after the audit; the docs now warn about it. Not verified by a second agent.

**Failure scenario.** A hypothesis directory written by transcription.py holds <stem>_transcript.txt and <stem>_transcript.json. _match_files pairs both with the same reference, so the recording is scored twice and weighs double in the corpus WER.

**Proposed fix.** Match one hypothesis format per stem (prefer .txt, or add --hypothesis-format), and warn when both are present. Check whether any committed wer_report.csv was produced from a directory holding both; if so, re-score.

### NEW-04: The manuscript says the benchmark decodes in single precision, but Large v3 and distil-large-v3 decoded in float16

`manuscript/manuscript.qmd:581` · MAJOR · touches end product · verified observed after the audit

**Status.** Resolved. Found while the determinism and FLEURS re-runs were checked, and confirmed against the recorded summaries on 2026-10-04. The code documents the precision in the `_DTYPES` comment of evaluation/benchmark_wer.py and, since 26cfcf3, in the pipeline_full notes of evaluation/conditions.py. ae8a21f and 4065ca8 (merged in 0e90917) correct both sentences. The Methods now say that on a GPU the pipeline loads each checkpoint in the precision it is stored in: half precision for Large v3, as the headline summary records, and for distil-large-v3, and single precision for Whisper Medium (manuscript.qmd:1581-1587 at e515421). The footprint section no longer speaks of single precision.

**Failure scenario.** The Methods (manuscript.qmd:883-884 at f2578b8) say that nothing overrides the pipeline defaults for precision, "so the model runs in single precision", and the footprint discussion (3345-3346) says "The benchmark runs the `transformers` pipeline in single precision". Under transformers 4.57.1 the pipeline, given no dtype, loads the checkpoint's own, and the runs recorded it. The re-run sweep's summaries on ARC give `torch.float16` for Large v3 and distil-large-v3 and `torch.float32` for Whisper Medium (85 summaries each), the committed `wer_summary.json` gives float16, and all 12 summaries of the FLEURS fourth arm give float16. A reader who follows the text and forces float32 for Large v3 is not running the decode behind the results.

**Proposed fix.** State the precision per model, half precision for Large v3 and distil-large-v3 (the precision their checkpoints store) and single precision for Whisper Medium, or read it from each summary's `benchmark.decode.dtype`. The passage on the transcription path (manuscript.qmd:704-705, half precision on a CUDA device) is already right.

**Committed results affected.** None; only the text is wrong.

### NEW-11: The scoring normaliser keeps single quotation marks, so the marks Whisper writes around dialogue are scored as errors (842 of 2,030 on LibriSpeech test-clean)

`evaluation/wer.py:97` · MAJOR · HIGH-RISK · changes numbers · touches end product · verified observed after the audit

**Status.** Resolved. On 17 October 2026 the author decided to keep the declared scorer and disclose its sensitivity, so the rule below is not adopted and every committed figure stays on one scorer. The manuscript reports error rates as scored, quotation marks included, beside the exploratory rescoring. evaluation/wer.py is unchanged, and every committed WER artefact still counts the marks, apart from the exploratory arm of scorer_sensitivity.{csv,json}, which sets them aside. On 6 October 2026, evaluation.scorer_sensitivity reconstructed the original raw and whisper_norm metrics in all 30 cells of suite, model and condition from 160,446 retained rows, then applied the proposed symmetric edge-apostrophe rule as a separate exploratory analysis. output/evaluation/scorer_sensitivity.csv and .json record the transform, exact input hashes, counts and fixed common samples; sweep_input_manifest.json publishes the 270-file checksum inventory without deployment locators. No new reference exclusions or inclusions occur. Large v3 test-clean normaliser gain falls from 64.43% to 22.42%, while its paired AMI gain stays near 6.8%. Independent standard-library word alignment reproduces the headline cell and its 842-error reduction. Thirty focused tests cover lexical marks, pairing, denominators, empty references, a change in a metric or a hash, and output scope. The manuscript now reads and checks the sensitivity dynamically. The original scorer and the canonical grid and interval artefacts remain intact. The underlying text inputs still await a reviewed public deposit (REGEN-05).

**Failure scenario.** `normalise_text` keeps `'` so that a contraction stays one token (wer.py:52 and 97 at 10981d4). It also maps the curly single marks U+2018 and U+2019 to `'` (line 93), so a single quotation mark survives too, while double quotation marks, straight or curly, become spaces. Whisper Large v3 opens a line of dialogue with `"'` and usually closes it with `'`, of which the scorer keeps the single mark, and LibriSpeech's references hold no apostrophe at a word edge (none of test-clean's 52,576 reference words). So `"'Now what have you to say, Cynthia Sprague?'` against NOW WHAT HAVE YOU TO SAY CYNTHIA SPRAGUE is scored as `'now` for NOW plus a stray `'`, two errors in eight words, both from the marks. On the raw test-clean cell of Large v3, setting aside every apostrophe that is not between two word characters, on both sides, removes 842 of its 2,030 errors: 836 quotation marks (404 standing alone as tokens and 432 opening a word), the apostrophes of two possessive plurals (hours', Anders') and the leading apostrophes of four elided forms ('Tis three times, 'Twasn't once), which the references write without one. The pooled WER falls from 0.0386 to 0.0226 and the macro WER from 0.0621 to 0.0285, the gap between them from 2.35 to 0.59 points and the readers' max/min ratio from 12.4 to 8.7, and the share of utterances scored exactly right rises from 62% to 72%. The charge depends on the model: on the same audio the rule removes 711 errors for Distil-Large v3 and 176 for Whisper Medium (706 and 169 of them quotation marks), and on test-other 839, 601 and 95 for Large v3, Distil-Large v3 and Medium.

**Proposed fix.** In `normalise_text`, after `_PUNCT_RE`, replace with a space every `'` that is not between two word characters (`re.compile(r"(?<!\w)'|'(?!\w)")`), on both sides alike. An apostrophe inside a word stays, so don't, o'clock and 1990's remain one token and a wrongly restored apostrophe still counts as an error. A letters-only rule gives the same totals in all fifteen cells but splits 1990's into two tokens, which is why the word-character rule is proposed. The diff below makes the change at fb22ece: it rewrites step 6 of the docstring and the comment on the curly marks, replaces the two pins of the stray token in tests/test_audit_eval_wer.py, and moves the FLEURS sentence of tests/test_s1_wer_conditions.py from the inputs on which punct_strip scores differently from raw to those on which it scores alike, since the rule removes that sentence's edge apostrophe on both sides. It applies cleanly (`git apply --check` at fb22ece), and the earlier re-score checked the same function on every raw string of the fifteen cells, but the test suite has not been run with it. The prose to follow it is the Methods sentence on the apostrophe (manuscript.qmd:1499-1507 at e515421), docs/conditions_audit.md and the punct_strip notes in evaluation/conditions.py and docs/conditions_audit.md (fb22ece). Those notes give the FLEURS sentence as punct_strip's only committed difference from raw, and with the rule punct_strip scores exactly as raw in all three FLEURS cells (checked on the dumps), and so in all fifteen.

**Re-score needed.** No GPU is needed. The hypothesis dumps `wer_hypotheses_<suite>_<model>.csv` of ARC jobs 8917985, 8917986 and 8917987 hold the transformed reference and hypothesis of every condition in all fifteen cells, and re-scoring them with the current normaliser reproduces every per-utterance count of the 255 reports and every total of sweep_aggregate.csv. Adopting the rule then takes four steps:

1. Re-score the dumps into reports and summaries, keeping each summary's benchmark, decode and run_metadata blocks and recording the scorer's commit.
2. Rebuild sweep_aggregate.{csv,json}, the headline pair (wer_summary.json, wer_report.csv) and sweep_reports_postfix/, wer_ci.csv (evaluation.bootstrap_ci), and condition_ci_postfix.csv and normaliser_gain_ami.csv, with the AMI reports behind it (evaluation.condition_ci). Rebuild speaker_cluster_sensitivity.json (evaluation.speaker_cluster_ci), which the regeneration gate rebuilds and whose macro_wer block reads wer_report.csv; its paired deltas read the pre-repair sweep_reports/, which have no retained hypotheses. Regenerate scorer_sensitivity.{csv,json} or mark them superseded, since their original arm would then be the superseded scorer.
3. Re-derive and render the manuscript passages that the speaker-dispersion chunk lists (manuscript.qmd:3034-3041 at e515421): the abstract's last sentence and its claims-check entry, the Methods sentence on the apostrophe, the per-utterance paragraph of @sec-wer, the whisper_norm, cross-corpus and normaliser-gain paragraphs with the suite-order check and the order of @fig-suites and @tbl-models, the caption of @tbl-models, Appendix C and the Discussion's paragraph on the readers. The 6 October 2026 manuscript adds the Methods paragraph on reader-cluster resampling and the Methods sentence on the exploratory rescoring, the reader-cluster paragraph of @sec-wer with its setup checks and its claims-check entry reader_cluster, which compares the reader interval with wer_ci.csv's, the scorer-sensitivity paragraph after the normaliser-gain paragraph, the Discussion's sentence on the rescoring, and the setup and claims checks of scorer_sensitivity.
4. Archive the dumps with the result, since no other file holds the hypotheses.

No committed artefact holds the hypotheses of the multilingual wave (job 8917984), the anonymisation benchmark, the pre-repair sweep (condition_ci.csv and sweep_aggregate_prefix, behind the abstract's 0.40 points) or the May pilot, so those figures keep the old scorer unless they are decoded again on a GPU, and the paper would then have to say which scorer each figure used. How far those figures would move is unmeasured, and in the sweep the rule moved AMI by at most four errors. The determinism comparison scores AMI from dumps that stay on ARC, and could be re-scored from them.

**Diff proposed by the implementer.**

```diff
diff --git a/evaluation/wer.py b/evaluation/wer.py
--- a/evaluation/wer.py
+++ b/evaluation/wer.py
@@ -83,6 +83,14 @@
 # pins committed numbers, and neither may move without the other being
 # rescored.
 _PUNCT_RE = re.compile(r"[^\w\s']", flags=re.UNICODE)
+# An apostrophe that is not between two word characters: a single
+# quotation mark typed as an apostrophe ("'Yes,' she said"), or an
+# apostrophe at a word edge (the possessive plural "boys'", the elision
+# "'tis"). Whisper writes such marks around dialogue and LibriSpeech's
+# references carry none, so keeping them scored each mark as an error
+# (ISSUES.md NEW-11). An apostrophe between two word characters is kept,
+# so "don't", "o'clock" and "1990's" each stay one token.
+_EDGE_APOSTROPHE_RE = re.compile(r"(?<!\w)'|'(?!\w)")
 _WS_RE = re.compile(r"\s+")
 # Used only by the --remove-fillers flag of this module's CLI. It is not
 # the production list (transcription.FILLER_TOKENS) nor the filler_strip
@@ -131,10 +139,13 @@
     4. Map the curly single quotation marks U+2018 and U+2019 to ``'``.
     5. With *lowercase*, lower-case.
     6. With *strip_punctuation*, replace every character that is not a
-       word character, whitespace or ``'`` with a space. Apostrophes are
-       kept, so ``don't`` stays one token, but so are quotation marks
-       typed as apostrophes: ``'Yes,' she said`` gives ``'yes ' she
-       said``, with a stray ``'`` token.
+       word character, whitespace or ``'`` with a space, and then every
+       ``'`` that is not between two word characters. An apostrophe
+       inside a word is kept, so ``don't`` stays one token, while a
+       quotation mark typed as an apostrophe goes: ``'Yes,' she said``
+       gives ``yes she said``. An apostrophe at a word edge goes too, on
+       both sides alike, so ``boys'`` and ``'tis`` are scored as ``boys``
+       and ``tis``.
     7. With *remove_fillers*, drop the tokens in :data:`_FILLER_WORDS`.
     8. Collapse whitespace and strip.
 
@@ -153,15 +164,17 @@
     # of an accented word score alike. It keeps accents, and it leaves the
     # curly quotation marks unchanged. The replace that follows maps the
     # single ones, U+2018 and U+2019, to "'", which punctuation stripping
-    # keeps. U+2019 is also the typographic apostrophe, so a contraction
-    # typed with it stays one token. The double ones, U+201C and U+201D,
-    # are left to punctuation stripping.
+    # keeps only between two word characters. U+2019 is also the
+    # typographic apostrophe, so a contraction typed with it stays one
+    # token. The double ones, U+201C and U+201D, are left to punctuation
+    # stripping.
     text = unicodedata.normalize("NFKC", text)
     text = text.replace("\u2019", "'").replace("\u2018", "'")
     if lowercase:
         text = text.lower()
     if strip_punctuation:
         text = _PUNCT_RE.sub(" ", text)
+        text = _EDGE_APOSTROPHE_RE.sub(" ", text)
     if remove_fillers:
         tokens = [t for t in text.split() if t not in _FILLER_WORDS]
         text = " ".join(tokens)
diff --git a/tests/test_audit_eval_wer.py b/tests/test_audit_eval_wer.py
--- a/tests/test_audit_eval_wer.py
+++ b/tests/test_audit_eval_wer.py
@@ -27,10 +27,14 @@
 
 @pytest.mark.parametrize("text,expected", [
     ("Hello, World!", "hello world"),
-    # A quotation typed with apostrophes leaves a stray token. Pinned, not
-    # endorsed: changing it moves every committed WER.
-    ("'Yes,' she said.", "'yes ' she said"),
-    ("‘Yes’", "'yes'"),
+    # A quotation typed with apostrophes goes with the other punctuation,
+    # and so does an apostrophe at a word edge, on both sides alike. One
+    # between two word characters stays (ISSUES.md NEW-11).
+    ("'Yes,' she said.", "yes she said"),
+    ("‘Yes’", "yes"),
+    ("\"'It is you,' he said.", "it is you he said"),
+    ("the boys' books, 'tis late", "the boys books tis late"),
+    ("o'clock in the 1990's", "o'clock in the 1990's"),
     ("don't stop", "don't stop"),
     ("[NAME] said hi", "name said hi"),
     ("well-known 3.5 km", "well known 3 5 km"),
diff --git a/tests/test_s1_wer_conditions.py b/tests/test_s1_wer_conditions.py
--- a/tests/test_s1_wer_conditions.py
+++ b/tests/test_s1_wer_conditions.py
@@ -174,12 +174,12 @@
 # punct_strip runs before the scoring normaliser, so it can score
 # differently from raw only on a character that the normaliser would have
 # rewritten or removed before its own punctuation strip (the module
-# docstring of evaluation.conditions). One input per case it names; the
-# second is the FLEURS reference sentence behind the only punct_strip cells
-# of the committed grid that differ from raw.
+# docstring of evaluation.conditions). One input per case it names. The
+# scorer keeps an apostrophe only between two word characters, so a
+# curly single mark moves the score only inside a word (ISSUES.md NEW-11).
 _PUNCT_STRIP_MOVES = (
     "don’t stop",                    # U+2019, the typographic apostrophe
-    "a cave known as Hira‘” on",     # U+2018, written as a closing mark
+    "O‘Brien said so",               # U+2018, written inside a word
     "Brand™ name",                   # NFKC folds U+2122 into TM
     "café au lait",            # NFKC joins U+0301 to its letter
     "SPEAKER-01 hello",              # the normaliser drops the whole tag
@@ -189,6 +189,7 @@
 # word characters already, so the strip leaves them for it.
 _PUNCT_STRIP_AS_RAW = (
     "\"'Now what,' he said.\"",      # the marks Whisper writes
+    "a cave known as Hira‘” on",     # U+2018 as a closing mark (FLEURS)
     "“Yes,” she said (twice)… fine!",
     "don't stop at o'clock",
     "[SPEAKER_00]: hello SPEAKER_01: hi",
```

**Committed results affected.** The English sweep's WER artefacts, and every figure the manuscript draws from them, including the reader-cluster interval on the raw corpus rate in speaker_cluster_sensitivity.json and the original arm of scorer_sensitivity.{csv,json}, both added on 6 October 2026. The table gives, for each of the fifteen cells, the errors the raw condition makes as scored, how many the rule removes, the raw WER as scored and with the rule, both macro-averaged and pooled over words, and the change that pipeline_full and whisper_norm make against raw under each rule, as differences of macro averages, the way the manuscript takes them. All are proportions, so 0.0100 is one percentage point. No utterance scores worse under the rule in any cell or condition of the table.

| Corpus | Model | Raw errors | Removed by the rule | Raw macro WER | With the rule | Raw pooled WER | With the rule | pipeline_full minus raw | With the rule | whisper_norm minus raw | With the rule |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| LibriSpeech test-clean | Whisper Large v3 | 2,030 | 842 | 0.0621 | 0.0285 | 0.0386 | 0.0226 | 0.0000 | 0.0000 | -0.0400 | -0.0064 |
| LibriSpeech test-clean | Whisper Medium | 2,617 | 176 | 0.0655 | 0.0610 | 0.0498 | 0.0464 | -0.0203 | -0.0201 | -0.0123 | -0.0078 |
| LibriSpeech test-clean | Distil-Large v3 | 2,154 | 711 | 0.0609 | 0.0337 | 0.0410 | 0.0274 | 0.0000 | 0.0000 | -0.0331 | -0.0059 |
| LibriSpeech test-other | Whisper Large v3 | 2,892 | 839 | 0.0840 | 0.0512 | 0.0553 | 0.0392 | 0.0000 | 0.0000 | -0.0406 | -0.0078 |
| LibriSpeech test-other | Whisper Medium | 4,028 | 95 | 0.0945 | 0.0923 | 0.0770 | 0.0751 | -0.0009 | -0.0009 | -0.0103 | -0.0080 |
| LibriSpeech test-other | Distil-Large v3 | 3,499 | 601 | 0.0947 | 0.0705 | 0.0668 | 0.0554 | 0.0000 | 0.0000 | -0.0321 | -0.0079 |
| AMI | Whisper Large v3 | 18,428 | 4 | 0.3243 | 0.3242 | 0.2044 | 0.2044 | -0.0220 | -0.0220 | -0.0391 | -0.0390 |
| AMI | Whisper Medium | 70,485 | 3 | 3.3706 | 3.3706 | 0.7819 | 0.7819 | -2.6205 | -2.6205 | -0.1754 | -0.1754 |
| AMI | Distil-Large v3 | 17,861 | 1 | 0.2846 | 0.2846 | 0.1981 | 0.1981 | -0.0010 | -0.0010 | -0.0472 | -0.0472 |
| VoxPopuli accented | Whisper Large v3 | 39,071 | 48 | 0.1818 | 0.1816 | 0.1708 | 0.1705 | 0.0000 | 0.0000 | -0.0115 | -0.0113 |
| VoxPopuli accented | Whisper Medium | 77,626 | 44 | 0.3785 | 0.3783 | 0.3393 | 0.3391 | -0.0980 | -0.0980 | -0.0094 | -0.0092 |
| VoxPopuli accented | Distil-Large v3 | 34,265 | 51 | 0.1618 | 0.1616 | 0.1497 | 0.1495 | 0.0000 | 0.0000 | -0.0119 | -0.0117 |
| FLEURS en_us | Whisper Large v3 | 667 | 6 | 0.0472 | 0.0469 | 0.0461 | 0.0457 | 0.0000 | 0.0000 | -0.0069 | -0.0066 |
| FLEURS en_us | Whisper Medium | 718 | 5 | 0.0509 | 0.0506 | 0.0496 | 0.0493 | 0.0000 | 0.0000 | -0.0071 | -0.0067 |
| FLEURS en_us | Distil-Large v3 | 924 | 6 | 0.0653 | 0.0649 | 0.0639 | 0.0635 | 0.0000 | 0.0000 | -0.0078 | -0.0074 |

Of the composite's deltas only Whisper Medium's on test-clean moves, from -0.0203 to -0.0201. The whisper_norm cells do not move, since no apostrophe survives the Whisper normaliser, so the comparison with Radford et al. stands, although whisper_norm's gain over raw on test-clean falls from 4.00 to 0.64 points.

On the reference side the rule changes no word count in any cell, and no reference token of test-clean, whose references write possessive plurals and elisions without the apostrophe (HOURS SLEEP, ANDERS FACE, TIS). It changes one token of test-other (YO' becomes yo), 269 of AMI, all but one of them the leading apostrophe of an elision ('cause 160 times, 'kay 89, 'em 15, 's 3 and 'til once, beside one mm'), three of VoxPopuli (possessive plurals) and eight of FLEURS (hira', course', conservatives' and others', twice each, closing quotation marks or possessive plurals). Because the rule applies to both sides, a form written alike on both still matches, and a pair that differs only in such an apostrophe now matches, which is a change of convention and not a repair. Outside LibriSpeech the errors it removes are therefore not quotation marks: 1 to 4 on AMI (the reference's 'CAUSE against cause), 44 to 51 on VoxPopuli (possessive plurals such as states' against references written without the apostrophe) and 5 or 6 on FLEURS (the reference-side marks and possessives above). On test-clean it touches the hypotheses alone.

In the manuscript the rule would move these figures, re-derived on 2026-10-04 from the sweep's test-clean dump and the table above:

- Table 1: the macro WER from 0.062 to 0.028 and the pooled from 0.039 to 0.023, with the interval.
- The per-utterance paragraph and Figure 1: the share of the macro average carried by the 615 utterances under ten words from 52% to 41%, r from -.28 to -.12, and the utterances scored exactly right from 62% to 72%.
- Appendix C: the 90th and 95th percentiles from 2/9 and 1/3 to 0.094 and 0.154, and the files above 0.5 from 26 to 8.
- Section 4.2, Figure 4, the abstract's last sentence and the Discussion: the readers' range from 0.7% to 9.0% to 0.5% to 4.7%, so that twelve to one becomes about nine to one.
- The whisper_norm paragraph: a factor of about three on test-clean becomes about 1.3.
- The normaliser-gain paragraph: 64.4% and 48.3% become 22.4% and 15.3%, so the check that the LibriSpeech gains exceed twice any other fails against FLEURS's 14.0%.
- The corpus order: test-clean becomes the lowest (0.028 against FLEURS's 0.047), so the suite-order check, @fig-suites and the model table reorder.
- The model table's test-clean rows: Large v3 from 0.062 to 0.028, Distil-Large v3 from 0.061 to 0.034 and Medium from 0.066 to 0.061.
- The diagnostic deltas on test-clean: filler_strip from +0.030 to +0.049 points and dedup_window from +0.098 to +0.123.

## Minor (35)

### T2-20: _speaker_count_kwargs docstring hard-codes measured DER figures, one of which no longer matches the committed report

`transcription.py:1618` · MINOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. 9fd0199 replaced the figures in the `_speaker_count_kwargs` docstring with a pointer to `output/evaluation/der_summary.json`, `output/evaluation/der_oracle/der_summary.json` and the manuscript's diarisation section. 70926fa removed every typed fallback from the manuscript, the "45.8%" at qmd:1972 among them, so the worst oracle meeting is printed only from `der_oracle/der_report.csv` (TS3003b, 0.45745). The one other copy, in `docs/advanced_usage.md:61-63`, gave 45.8% too, and 71b66fb corrects it to 45.7%. Its other figures, 16.6%, 25.0%, ten of sixteen meetings and 7.2%, are those of the DER re-runs that 70933b4 commits, which left all four unchanged.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The docstring and the manuscript's no-data fallback quote 45.8% while the rendered manuscript prints 45.7%. The next DER re-run will change all four numbers and the docstring will silently drift further.

**Proposed fix.** Replace the figures in the docstring with a pointer to output/evaluation/der_summary.json, der_oracle/der_summary.json and the manuscript section, or correct 45.8% to 45.7%. Correct the manuscript fallback literal at qmd:1972 from "45.8%" to "45.7%" with maintainer sign-off. The rendered output does not change.

### EWER-22: HypothesisDump 'reference' column holds the condition-transformed reference, and the dump is not closed if the loop raises

`evaluation/benchmark_wer.py:505` · MINOR · HIGH-RISK · changes numbers · verified confirmed

**Status.** Resolved. 66be1de gave the hypothesis dump two reference columns, `reference_raw` (the corpus text) and `reference_transformed` (the text the condition scored against), and a986262 made `evaluation.disfluency` read `reference_raw` while still reading dumps of the old layout. The committed `disfluency_summary.json` was rescored from the re-run sweep's Large v3 AMI dump (job 8917985) in a6dd82f and 9732ac0 and records `reference_source` "reference_raw column". With ESTATS-08, this moved the whisper_norm row's reference fillers from 58 to 3,066 and its recall from 0.1207 to 0.0. The scoring loop still closes the dump only on a normal exit, which the proposed fix judged unnecessary for data safety, since every row is flushed as it is written; tests/test_hypothesis_dump.py and tests/test_disfluency_results.py guard the columns and the source.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Someone rescoring a revised whisper_norm from its own dump rows applies the normaliser to an already-normalised reference, which is not idempotent for number and currency rewriting. When a condition raises outside the per-utterance try (e.g. in aggregate), the file handle is left to interpreter teardown, which sweep.py bypasses with os._exit.

**Proposed fix.** Add reference_raw (reference) alongside reference_transformed (ref_t), and keep the existing 'reference' column name only if disfluency.score_dump is updated to choose the intended one explicitly. Wrapping the loop in `with HypothesisDump(...)` is tidy but not needed for data safety. Changing which column disfluency reads changes the whisper_norm row of disfluency_summary.json and needs sign-off.

### ESTATS-07: The manuscript's recorded condition_ci command overwrites the pre-fix artefact because the default output is condition_ci.csv

`evaluation/condition_ci.py:170` · MINOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. c03c37f made `--output` a required argument of `evaluation.condition_ci`, so no run can fall back on `condition_ci.csv`, and the manuscript (manuscript.qmd:2262-2290 at e515421) and manuscript/README.md name `condition_ci_postfix.csv` explicitly and keep the command behind the pre-repair `condition_ci.csv` as history. Both tables still regenerate byte for byte (tools/verify_regeneration.py at fb22ece, run on 2026-10-04). The remaining R comment's false description of a default output (manuscript.qmd:2266-2269 at e515421) was corrected on 2026-10-06. It now states that an explicit output path is required, matching the CLI; the comment is not rendered and no committed interval changed.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader or maintainer re-runs the documented command to verify the postfix table. It writes postfix intervals over output/evaluation/condition_ci.csv, destroying the pre-fix artefact (six rows, including contraction_fix +0.43 pp). On the next render, cci_pre_fmt('contraction_fix') quotes post-fix values as the historical defect.

**Proposed fix.** Add `--output output/evaluation/condition_ci_postfix.csv` to the comment at manuscript.qmd:1009-1011 (sign-off needed), and record beside it the command that produced the history file (`--reports output/evaluation/sweep_reports --output output/evaluation/condition_ci.csv`). Make --output required in condition_ci, or refuse to overwrite an existing file without --force.

### ESTATS-16: _percentile says 'nearest-rank' but uses round((n-1)*p) with banker's rounding, so ties break inconsistently

`evaluation/timestamp_metrics.py:58` · MINOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. a36b1d4 corrected the `_percentile` docstring to describe the estimator as it is, the observation nearest the linear-interpolation position (numpy's `method="nearest"`), and tests/test_timestamp_metrics.py pins its even-length behaviour and the 449th value as the 90th percentile of 499. The estimator is unchanged, as proposed. The re-run (ARC job 8917980 at 6f9bf56, committed in 567cfd9) gives the same observations as before, a median of 10 ms and a 90th percentile of 150 ms, now computed from unrounded errors. Moving to the textbook nearest-rank estimator (the 450th value, 0.16 s) remains the author's call.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** On even-length inputs the reported median swings between the lower and upper middle value depending on n's parity, because Python rounds .5 to even. p90 is one rank lower than the textbook nearest-rank definition. With the committed n=499 the values (0.01, 0.15) are almost certainly unchanged, but the docstring misstates the estimator.

**Proposed fix.** Do not change the estimator, since doing so would alter the published 90th-percentile value. Correct the docstring to say 'nearest observation to the linear-interpolation position (numpy method="nearest"; index = round((n-1)*p), ties to even)', and add an even-length test pinning the current behaviour. Changing to ceil nearest-rank would need maintainer sign-off and a manuscript table update.

### EPRIV-32: 'speech_s' and coverage sum whole segment spans, so they count intra-segment pauses and double-count overlaps

`evaluation/benchmark_podcast.py:91` · MINOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. 4b22326 computes `speech_s` as the merged union of the timed words' intervals, keeps the segment measure as `segment_span_s` (merged, so an overlap counts once), adds `coverage_ratio` and `segment_coverage_ratio` and takes the median with `statistics.median`, and tests/test_s1_misc_podcast.py covers the union and the median. ac08cdc commits job 8983112's summary, with a `speech_s` of 1,841.08 s and a `segment_span_s` of 1,880.26 s, a `coverage_ratio` of 0.95 and a `segment_coverage_ratio` of 0.9702 against the feed's 1,938 s. The README defines both measures and reports them against the recording, and the August run's 1,881.7 s and 97.2 per cent are gone.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** On ep05, pauses inside caption segments are counted as speech, so the 97.2% 'speech coverage' overstates voiced time. For a transcript with overlapping cues (the first case-study run had five), the figure can exceed the true span.

**Proposed fix.** As proposed: compute speech_s from the merged union of word intervals, keep the segment sum as segment_span_s, use statistics.median, and relabel the README figure as segment coverage of the span (or update it to the word-union value).

### CORE-04: The manifest's input_audio digest covers whatever path was transcribed, so the committed case-study manifest attests a derived 16 kHz WAV rather than the recording whose SHA-256 the README cites

`provenance.py:142` · MINOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. d55f13c lets a run manifest carry `source_audio`, the original recording's name, size and SHA-256 and how the transcribed file was derived from it, d19eb31 fills it from transcription.py's `--source-audio` and `--source-derivation`, and 73c2f96 makes the case-study job pass the .m4a and its ffmpeg command. The committed manifest is now job 8983112's (ac08cdc). Its `input_audio` is the 16 kHz WAV that was transcribed (ee52c7ba..., 62,043,798 bytes, the WAV the August run transcribed too), and its `source_audio` names the published .m4a (a1f08233..., 31,357,663 bytes, as data/codex_mentis/manifest.json records) with the ffmpeg derivation. output/case_study/README.md says which digest is which, `python -m provenance verify` passed in the job, and tests/test_case_study_results.py checks `source_audio` against the corpus manifest.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A reader holding the published episode file (sha a1f0...) cannot link it to the manifest, which names only an intermediate WAV (sha ee52...) that is not archived. The ffmpeg conversion (resampling, downmix, s16 quantisation) is recorded nowhere. The manifest therefore cannot establish that the transcripts came from the recording the README names, which is the chain of custody the feature exists to provide.

**Proposed fix.** The proposal's 'pass --original-filename's file' does not work as written. original_filename only changes naming (transcription.py:2949, 3119) and need not be an existing path. Add an explicit source-audio argument that records name, bytes and sha256 plus a derivation note. Do not switch the case study to decoding the m4a directly: audio_io's ffmpeg float path differs from the s16le WAV, so re-running would change the transcripts and podcast metrics. With sign-off, add a one-line note to output/case_study/README.md that the manifest's input_audio is the 16 kHz derivative of the cited recording, rather than regenerating the manifest.

### CORE-05: Manifest docstring claims it lists every file emitted for a run, but name-masking logs (which hold the unmasked names) are neither listed nor checked as unlisted

`provenance.py:14` · MINOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. d55f13c took the proposal's second option: the `provenance.py` docstring says the manifest covers only the files the caller lists and names the two outputs left outside it, the name-masking log, which holds the original names, and kept enhanced audio. e9c90fc corrects the comment above transcription.py's manifest step, which said the manifest lists every artefact the run wrote. output/case_study/README.md (ac08cdc, 4b582e1) now says that transcription.py wrote eleven files, ten in output/transcripts/ and the masking log in name_masking_logs/, and that the manifest lists nine of them and not the log, so a change to the log would go unnoticed. tests/test_case_study_results.py checks that the committed manifest lists nine artefacts and no masking log.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** After a run with --mask-personal-names --save-name-masking-logs, the replacement log mapping placeholders back to real names can be edited, replaced or exfiltrated, and `python -m provenance verify` still reports OK. A user who trusts the docstring believes the most sensitive artefact of the run is covered by tamper evidence, and it is not.

**Proposed fix.** Either pass the masking-log path (and any kept enhanced audio) to write_manifest with base_dir set to the project output root, or correct the docstring to name the covered directory and the exclusions. With sign-off, fix the case-study README's artefact count (eleven listed, nine in the manifest).

### CORE-20: Example JSON variants have drifted from the real output schema

`tools/generate_example_variants.py:284` · MINOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. f041d21 replaced the generator's templates: `tools/generate_example_variants.py` now runs `transcription.main` on a synthetic interview with only the model calls stood in. The variants therefore carry the real writers' keys (`timeline_repairs` among them), the redacted pair, the review report and the run manifest, and tools/README.md says what they leave out (the .docx files and the masking log). The variants were regenerated with the author's approval, and again by the same generator in 486783b and 365af36 when the manifests gained the model snapshots. tests/test_example_variants.py regenerates each variant and compares the files and their contents.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A user writes a parser against example_transcript.json and does not handle `timeline_repairs`, or expects exactly the example's key set. They are also never shown the review and manifest files that accompany every real run, and so cannot learn from the examples that those files exist.

**Proposed fix.** As proposed. Add timeline_repairs in the real writer's shape and either emit illustrative review and manifest files or state their omission in tools/README.md, then regenerate with sign-off.

### OUTPUTS-10: Fourteen May 2026 pilot-matrix files remain in output/evaluation with an obsolete 'postprocessed' condition, byte-identical raw/postprocessed pairs and a mislabelled canonical file

`output/evaluation/wer_report_librispeech_distil-large-v3_raw.csv:1` · MINOR · touches end product · verified confirmed

**Status.** Resolved. 7214e77 moved the twelve suffixed pilot files, with a copy of the May Large v3 raw pair, into `output/evaluation/pilot_may2026/` (14 files, contents unchanged). The `output/evaluation/README.md` row for that folder says that "postprocessed" meant the repetition repair alone and that the identical pairs are a genuine null for that stage. The canonical pair is now the re-run sweep's raw Large v3 test-clean cell, whose summary records `benchmark.condition` "raw" (e3cb675, under OUTPUTS-03), and `.github/copilot-instructions.md` names no pilot file. The folder has no README of its own; the evaluation README's row stands in for one.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The identical distil raw/postprocessed pair reads as a finding that post-processing changes nothing, when it comes from an obsolete dual-scoring path. Readers cannot tell whether the canonical wer_report.csv is raw or repetition_fix, and the stale canonical copy is what the headline table renders.

**Proposed fix.** Move the 12 suffixed files to a legacy folder with a README, with sign-off. The README should say that 'postprocessed' means repetition_fix only, and that the identical pairs are a genuine null for that stage on distil and Large v3, not an artefact. Handle wer_report.csv and wer_summary.json through OUTPUTS-03. Update .github/copilot-instructions.md:62.

### OUTPUTS-15: masking_summary_caseinsensitive.json lacks the ner_stage key its writer now emits; the numbers otherwise regenerate identically

`output/evaluation/masking_summary_caseinsensitive.json:205` · MINOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. a08265c regenerated all four masking arms with the current module, so `masking_summary_caseinsensitive.json` now carries `ner_stage` (false) like the other three, together with its run metadata and the SHA-256 of the curated list. It was not the key-only regeneration the entry proposed: the fixed benchmark samples 1,940 cases instead of 1,164 (T1-07, EPRIV-10), and this arm's overall recall is unchanged at 0.7010 (1,360 of 1,940, against 816 of 1,164). The NER arms moved for other reasons: overall recall went from 0.456 to 0.474 with NER, and from 0.907 to 0.937 with case folding and NER.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Code that selects masking arms by ner_stage, e.g. `ms$ner_stage == FALSE` in R, gets NULL for this arm and silently drops it or errors, while the other three summaries carry the key.

**Proposed fix.** Regenerate with sign-off, and diff the regenerated file against the committed one before replacing it to confirm that only ner_stage is added.

### MS-19: Five bibliography entries are never cited; the software record is hard-coded as a URL instead of cited

`manuscript/references.bib:31` · MINOR · touches end product · verified confirmed

**Status.** Resolved. 3c48f8a removed the four entries cited nowhere (bredin2023pyannote, brunilaWhatCompanyWords2022, connellLanguageModelsCognition2024 and linTruthfulQAMeasuringHow2022), and 70926fa cites the software record, @bernabeuSecureScalableSpeech2025, where the archive is named (manuscript.qmd lines 923, 3646 and 3658). Each of the 34 entries left in references.bib now appears as a citation key in manuscript.qmd (checked on 2026-10-04), and tests/test_bib_sentencecase.py checks that every cited key resolves.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** The archived software never appears in the reference list, so the journal's data-citation requirement is not met through the bibliography. Dead entries also keep drifting as the bib is sentence-cased and pruned.

**Proposed fix.** Cite @bernabeuSecureScalableSpeech2025 where the archive DOI is given, and delete the other four uncited entries (or cite them where intended).

### REGEN-08: The committed shipped example transcripts still fail the artefact audit (masked .txt/.docx contain "Bernabeu") after the clitic fix

`output/evaluation/artefact_audit.csv:9` · MINOR · HIGH-RISK · changes numbers · touches end product · verified confirmed

**Status.** Resolved. The proposal's first option was taken: 12275ed labels the four example transcripts as release 1.0.0 output in `example_output/transcripts/README.md`, and README.md no longer presents them as current output. The new README names the possessive leak ("Bernabeu's thesis" in behind_the_curtains), says that `artefact_audit.csv` still reports that episode's .txt and .docx as leaking it, and points to `example_output/variants/` for what the current code writes. b7fcdd6 re-ran the audit over the regenerated examples: the two release 1.0.0 leaks remain as the record of the defect, and the variants leak nothing. The audit still regenerates byte for byte (tools/verify_regeneration.py at f2578b8, run on 2026-10-04). Re-transcribing the four episodes with the current code has not been done, since it needs the original WAV files, which are not in the repository, and a GPU run.

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A user inspects the shipped de-identified example transcript, or runs `python -m evaluation.audit_artefacts` as its docstring shows. They see a masked-by-design artefact leaking a name, even though the paper says the gap is closed. The shipped examples show pre-fix behaviour, not what the current pipeline emits.

**Proposed fix.** Do not overwrite the committed artefact_audit.* or the example transcripts in place. The manuscript cites that audit as the measurement that found the defect, so it serves as evidence. Either label them as the pre-fix state (in a README under example_output, and in the audit's docstring or file name), or add a post-fix re-masked copy of the examples with a second audit file (for example artefact_audit_postfix.*) that shows zero leaks. Both options change committed outputs and need maintainer sign-off.

### REGEN-09: masking_summary_caseinsensitive.json is schema-stale: it lacks the ner_stage key the current module writes

`output/evaluation/masking_summary_caseinsensitive.json:1` · MINOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. As for OUTPUTS-15, a08265c regenerated `masking_summary_caseinsensitive.json` with the current module, which added `ner_stage` (false), run metadata and the curated list's SHA-256. Its overall recall stays 0.7010 on the fixed benchmark's larger sample (1,940 cases instead of 1,164). tools/verify_regeneration.py still rebuilds only the dictionary arm, so this file and the two NER arms remain outside the gate (G5).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** A rebuild-and-compare gate over output/evaluation reports this file as not reproducing although every metric matches, and code that reads msci$ner_stage to label the arm gets NULL for this file only.

**Proposed fix.** Regenerate masking_summary_caseinsensitive.json with the current module and commit it. Metrics are unchanged and one key is added. The maintainer should acknowledge this, since it is a committed results file.

### REGEN-10: wer_ci.csv stores an OS-specific relative path in its file column, so the artefact's bytes depend on the platform

`evaluation/bootstrap_ci.py:369` · MINOR · HIGH-RISK · touches end product · verified confirmed

**Status.** Resolved. a8420df makes `bootstrap_ci` write the `file` column with forward slashes, and 27cb15c committed `wer_ci.csv` in that form, regenerated over the new headline report; tools/verify_regeneration.py rebuilds it byte for byte at f2578b8 and at fb22ece (both run on 2026-10-04). Its numbers moved, but through OUTPUTS-03, not through this fix: e3cb675 made the headline report the re-run sweep's raw cell, the re-pointing this entry asked to keep apart. The macro WER went from 0.062210 to 0.062132 and the interval from [0.057521, 0.067064] to [0.057458, 0.067001] at seed 42, which moves the printed lower bound from 0.058 to 0.057. The manuscript's PHASE2 notes on the headline pair, which OUTPUTS-03 tracked, went with the Stage 4 rewrite (0e90917).

**Why deferred.** Fixing it would change a committed number or an end product, so it waits for a deliberate re-run under the sign-off policy.

**Failure scenario.** Regenerating wer_ci.csv on ARC or any POSIX machine changes the file column, so `cmp` against the committed file fails although every number is identical. A byte-level reproduction gate therefore cannot tell platform noise from a real change.

**Proposed fix.** In bootstrap_ci.main only, write `Path(path).as_posix()` (optionally relative to the repository root), then regenerate wer_ci.csv. The numbers stay the same. Do not bundle in the optional re-pointing of the corpus-level interval at the post-fix raw report. That changes the decode the interval describes (macro 0.062210 against 0.062132) and could move the reported bounds, so it is a separate, sign-off-level change to a reported statistic.

### MS-18: `pct` redefined mid-document with a different signature and output format

`manuscript/manuscript.qmd:2270` · MINOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 70926fa renamed the masking section's helper to `pct0` (manuscript.qmd:2849), so `pct` is defined once, in the setup chunk at line 279, and the DER section's helpers keep their own names, `pct1` and `pct2`.

**Why deferred.** manuscript is an end product

**Failure scenario.** Moving the DER section after the masking section, or quoting a DER figure with pct() in the Discussion, prints "17" where "16.6%" was meant. Any pct(x, accuracy = 1) call there errors with an unused argument.

**Proposed fix.** Rename the masking helper (e.g. `pct0`) and keep a single `pct` definition in the setup chunk.

### MS-20: protected_terms.json lists Slurm as both acronym and proper noun; the acronym wins

`manuscript/protected_terms.json:56` · MINOR · verified confirmed

**Status.** Resolved. 3c48f8a removed "SLURM" from `acronyms` in manuscript/protected_terms.json, leaving "Slurm" in `proper_nouns`, so tools/bib_sentencecase.py now keeps the manuscript's spelling. The optional guard, `_load_protected` refusing a term listed under both keys, was not added.

**Why deferred.** manuscript is an end product

**Failure scenario.** Adding a reference whose title mentions Slurm and re-running tools/bib_sentencecase.py emits {SLURM} in the reference list, inconsistent with the manuscript's spelling.

**Proposed fix.** Remove "SLURM" from `acronyms`, keeping "Slurm" in proper_nouns. Optionally make _load_protected reject terms that appear in both lists.

### T1-16: _sentence_capitalise claims to be language-general but only capitalises ASCII a-z

`transcription.py:1116` · MINOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 21e19b8 capitalises the first letter of a sentence in any script, title-casing it so that a caseless script passes through, and still leaves a sentence that opens with a bracket, a quotation mark or a digit as it is. tests/test_s1_txt_capitalise.py covers accented, Polish, Cyrillic, Georgian and Chinese cases and a French pipeline run. The re-run sweep at 6f9bf56, which contains the fix, produced the committed WER matrix (2e36bf9), and the FLEURS fourth arm (56ce519) found the composite changing no utterance's score in any of its six languages. No WER could move through this fix, because the scoring normaliser folds case.

**Why deferred.** The complete fix would change a committed number or artefact. The stage feeds sentence_capitalise and pipeline_full in the WER sweep. Its docstring now states the ASCII-only limit.

**Failure scenario.** French, German, Spanish or Polish transcripts whose sentences begin with an accented letter (e.g. 'à', 'é', 'ü', 'ł') keep a lower-case initial, and a sentence opening with a bracketed filler is never capitalised. The non-English output quality the pipeline claims to preserve is inconsistent.

**Proposed fix.** The proposed ^(\W*)(\w) would reach past '[' and quotes (turning '[um]' into '[Um]'), changing current English output beyond the stated goal. Use re.sub(r'^(\s*)([^\W\d_])', lambda m: m.group(1) + m.group(2).upper(), s), which keeps today's semantics and covers non-ASCII letters. Add French and German cases and re-check the composition fixture.

**Diff proposed by the implementer.**

    _sentence_capitalise: re.sub(r'^(\s*)([^\W\d_])', lambda m: m.group(1) + m.group(2).upper(), sentences[i]). Re-run sentence_capitalise and pipeline_full and the FLEURS multilingual run; scores should not move (the normaliser lower-cases) but hypothesis dumps will.

### T1-18: Filler bracketing half-brackets hyphenated backchannels ('uh-huh' to '[uh]-huh', 'mm-hmm' to '[mm]-[hmm]')

`transcription.py:952` · MINOR · HIGH-RISK · verified confirmed

**Status.** Resolved. b8a8c55 brackets the hyphenated backchannels whole ("Mm-hmm" becomes "[Mm-hmm]", and likewise uh-huh, uh-uh and mm-mm), leaves a filler joined to a word by a hyphen or an apostrophe alone ("uh-oh", "o'er"), and keeps the stage idempotent. tests/test_s1_txt_fillers.py checks this and that a bracketed backchannel counts as one filler, and the `disfluency._unbracket` docstring now describes both forms. The committed WER matrix (2e36bf9) and the filler figures in `disfluency_summary.json` (a6dd82f, 9732ac0) come from the re-run sweep at 6f9bf56, which contains the fix. The four release 1.0.0 example transcripts were left as they are (REGEN-08).

**Why deferred.** The complete fix would change a committed number or artefact. The stage produced the committed filler_bracket and disfluency results. Its docstring now documents the per-element bracketing.

**Failure scenario.** English conversational transcripts, where Whisper commonly writes 'Mm-hmm' and 'Uh-huh', show malformed tokens such as '[mm]-[hmm]' and '[uh]-huh'. Any disfluency count that tokenises on whitespace sees a hybrid token instead of one filler.

**Proposed fix.** If it is changed, bracket whole hyphenated backchannels first, e.g. r'(?<![\[\w-])((?:uh-huh|mm-hmm|uh-uh|mm-mm))(?![\]\w-])' to '[\1]', and exclude already-bracketed compounds from _FILLER_RE. Confirm that disfluency._unbracket and _canonical still count '[mm-hmm]' as one filler, and update the _unbracket docstring.

**Diff proposed by the implementer.**

    Add _BACKCHANNEL_RE = re.compile(r'(?<![\[\w-])((?:uh-huh|mm-hmm|uh-uh|mm-mm))(?![\]\w-])', re.I), apply it first in _filler_bracket with '[\1]', and change _FILLER_RE's lookarounds to (?<![\[-]) / (?![\]-]). Re-run filler_bracket, pipeline_full and the disfluency benchmark.

### T2-14: _language_is_english does not normalise Whisper special tokens, so an English '<|en|>' silently disables the English-only stages

`transcription.py:1301` · MINOR · verified plausible

**Status.** Resolved. a9a25db reduces Whisper's special-token form and ISO codes to a language before `_language_is_english` compares them, and `_detected_language` now returns a full name, so `--language "<|en|>"` runs the English-only stages; tests/test_s1_txt_language.py covers both. No committed result depended on it: the English sweep passes "english", and the FLEURS fourth arm (56ce519), run at 6f9bf56 with the fix, found the composite changing no utterance's score in any of its six languages.

**Why deferred.** The complete fix would change a committed number or artefact. _language_is_english gates the clean-up stages the WER benchmark runs. The limitation is documented.

**Failure scenario.** `--language "<|en|>"` transcribes English correctly, but clean_transcription_text treats it as non-English and skips contraction, filler-bracket, common-phrase and pronoun-i repair. The user receives a less-cleaned transcript with no warning, because the warning at 2922-2934 fires only when --language is omitted.

**Proposed fix.** As proposed: normalise at the top of _language_is_english via `_normalise_language_token` (return True when it yields None), map ISO codes to full names in `_detected_language` using the same LANGUAGES table, and add tests for '<|en|>' and the chunk fallback.

**Diff proposed by the implementer.**

    _language_is_english: normalise Whisper special tokens ('<|en|>') and ISO codes before the comparison. Re-run the FLEURS gate check and confirm the English sweep hypotheses are byte-identical.

### T2-19: _apply_vad_thresholds candidate paths target pyannote 2.x attributes that no supported version exposes

`transcription.py:1532` · MINOR · verified plausible

**Status.** Resolved. efa4d5e cut the candidate paths to the ones pyannote 3.x has: `segmentation.threshold` and a top-level `onset` for the onset, and a top-level `offset` for the offset. `--vad-offset` is therefore reported as having no effect on a SpeakerDiarization pipeline instead of appearing to be tried. `--vad-offset` stays, for VoiceActivityDetection-style pipelines loaded through `--diarization-config`, as proposed. tests/test_vad_thresholds.py now models the 3.x pipelines and checks that the 2.x names are no longer tried. No committed result goes through `_apply_vad_thresholds`, since the DER benchmark refuses the VAD overrides.

**Why deferred.** The remaining part needs files or tests outside what this pass changed. The comment and --vad-offset help are corrected for pyannote 3.x, but pruning the 2.x candidate paths needs tests/test_vad_thresholds.py's fixture changed first.

**Failure scenario.** Maintainers keep testing for and documenting --vad-offset as possibly effective. The five dead candidates obscure the fact that only the onset threshold on non-powerset models is real.

**Proposed fix.** Keep 'segmentation.threshold' (SpeakerDiarization, non-powerset) and the top-level 'onset'/'offset' (VoiceActivityDetection-style pipelines). Drop the 2.x-only names, and rewrite the comment to cite the 3.x pipeline classes. Do not deprecate --vad-offset; say in its help that it applies only to binary-segmentation VAD-style pipelines loaded via --diarization-config.

**Diff proposed by the implementer.**

    candidates = {'onset': ('segmentation.threshold', 'onset'), 'offset': ('offset',)} in _apply_vad_thresholds, after changing the test fixture to model a top-level 'offset'.

### EPRIV-28: wer_original_guarded holds the resynthesis control's WER whenever a control is supplied

`evaluation/benchmark_anonymisation.py:290` · MINOR · HIGH-RISK · verified confirmed

**Status.** Resolved. 16c1298 makes the summary say which arm its guarded baseline comes from: it emits `wer_baseline_guarded` and `wer_baseline_name` ("resynthesis control" whenever a control is supplied), and keeps `wer_original_guarded` as an older name for the same value, as its docstring says. The re-run's committed summaries (jobs 8917989 and 8917988, 8b6144c) carry both, at 0.1765 in the canonical run and 0.1871 in the single-meeting one. 0565bbb (merged in 0e90917) has the manuscript read `wer_baseline_guarded` from the summary, where its R chunk had run its own screen and named the original arm's rate `wer_original_guarded` (manuscript.qmd:4881-4899 at e515421).

**Why deferred.** The complete fix would change a committed number or artefact. The Python field is documented and wer_baseline_guarded added. The manuscript's R variable of the same name holds a different quantity; renaming it is the author's call.

**Failure scenario.** In the next summary, wer_original (raw) and wer_original_guarded (control) come from different arms. A reader or the manuscript comparing them attributes any difference to the loop screen. They are currently near-identical only because the control is the identity (EPRIV-14).

**Proposed fix.** Emit wer_baseline_guarded with a wer_baseline_name field, or emit wer_original_guarded and wer_control_guarded separately, and align the R variable name.

### NEW-02: hpc/evaluate_wer.sh defaults to a hypothesis directory the worker never writes

`hpc/evaluate_wer.sh:1` · MINOR · verified observed after the audit

**Status.** Resolved. ea0ddd3 makes `HYPOTHESIS_DIR` default to the repository's `output/transcripts`, where `hpc/batch_transcription.sh` writes, and the job now stops with exit 4 when that directory holds no .txt or .json transcript. It also writes `wer_report_transcripts.csv` and `wer_summary_transcripts.json`, by default into `$DATA/speech_transcription_env/output/evaluation/inhouse/` and never over the canonical files, and refuses to overwrite a summary without OVERWRITE=1 (exit 3). tests/test_s1_env_jobs.py checks the default, the exit status and the names.

**Why deferred.** The complete fix would change a committed number or artefact. Found by the documentation pass; the docs tell users to pass directories explicitly. Not verified by a second agent.

**Failure scenario.** Run without arguments, the script reads $DATA/speech_transcription_env/output/transcripts, but hpc/batch_transcription.sh writes to the repository's output/transcripts, so it scores an empty or stale directory.

**Proposed fix.** Default HYPOTHESIS_DIR to $REPO_DIR/output/transcripts, and fail when it holds no transcripts. It is a default of a script behind committed results, so the change waits for sign-off.

### REV-01: cache_pyannote_arc.py pre-caches pyannote into the Hub cache, which pyannote.audio 3.4.0 does not read

`setup/cache_pyannote_arc.py:1` · MINOR · verified observed after the audit

**Status.** Resolved. 20ee3b6 made `setup/cache_pyannote_arc.py` download into `preflight.pyannote_cache_dir()`, the directory pyannote.audio 3.x reads ($PYANNOTE_CACHE, or ~/.cache/torch/pyannote when it is unset, as in every ARC job), which is the proposed fix. PYANNOTE_CACHE is deliberately not exported, so jobs keep loading from the cache the committed DER runs used. 87a7ab5 and d66f211 corrected the setup guide and the offline error message, which still named the hub cache. Since 3334257 the script also exits 3 instead of reporting success over a damaged pipeline config, the damage of NEW-INC-01 (see Observations from ARC), whose stub this script's own test wrote in two ARC test jobs.

**Why deferred.** The complete fix would change a committed number or artefact. Found by the review of the fix branch; the documentation of the mismatch is in place.

**Failure scenario.** pyannote.audio 3.4.0 loads pipelines from $PYANNOTE_CACHE or ~/.cache/torch/pyannote, not the Hugging Face hub cache, so the pre-caching step does not stop a compute node from downloading. preflight now checks the directory pyannote reads (review finding CORE-R3), so it no longer passes on a hub-only cache.

**Proposed fix.** Download into preflight.pyannote_cache_dir(), or export PYANNOTE_CACHE in activate_project_env_arc.sh. Either changes where jobs load weights from, so it waits for sign-off.

### REV-02: Aggregating ARC's canonical evaluation directory as a whole now fails on genuinely repeated cells

`hpc/aggregate_sweep.sh:1` · MINOR · verified observed after the audit

**Status.** Resolved. ea0ddd3 gave `hpc/aggregate_sweep.sh` a default that names one sweep, and since 2e36bf9 that default is `audit2026/sweep`, the re-run sweep (jobs 8917985 to 8917987 at 6f9bf56) from which the committed 255-row `sweep_aggregate.{csv,json}` was built. A bare `sbatch hpc/aggregate_sweep.sh` therefore rebuilds the committed matrix. A missing directory fails, and repeated cells still stop the job by design (EWER-12). Which run is canonical is now settled by what is committed. tests/test_s1_env_jobs.py checks the default.

**Why deferred.** The next step needs the author's decision or an ARC run. Found by the review of the fix branch.

**Failure scenario.** The canonical directory holds two nested full sweeps (postfix/, 240 summaries; preflight_postfix/, 80) and the August AMI disfluency re-run, which repeats three large-v3 AMI cells. sweep_aggregate now refuses repeated cells (EWER-12) instead of silently picking one, so `sbatch hpc/aggregate_sweep.sh` with the default SWEEP_DIR exits 1. Pointed at postfix/, it reproduces every committed number (checked on a read-only copy of all 615 ARC summaries).

**Proposed fix.** Set the default SWEEP_DIR in hpc/aggregate_sweep.sh to .../output/evaluation/postfix, the directory the committed matrix came from, or document that SWEEP_DIR must name one sweep. Which run is canonical is the author's decision.

### REV-03: The NER false-positive note's reproduction steps omit the model download

`output/case_study/ner_false_positive_test.md:1` · MINOR · verified observed after the audit

**Status.** Resolved. 3f03f6b puts `python -m ner_masking --download` first under "Reproducing" in `output/case_study/ner_false_positive_test.md`, with a sentence saying why the `--ner` runs fail without it. No figure in the note changed.

**Why deferred.** The complete fix would change a committed number or artefact. Found by the review of the fix branch.

**Failure scenario.** NER masking now loads a pinned model revision without network access, so the three commands under 'Reproducing' fail on a fresh machine until `python -m ner_masking --download` has been run.

**Proposed fix.** Add `python -m ner_masking --download` above the three commands. The file is a committed case-study artefact, so the edit needs the author's sign-off.

### REV-04: The case-study job rewrites a tracked file in the ARC clone

`hpc/submit_case_study.sh:1` · MINOR · verified observed after the audit

**Status.** Resolved. c0f2258 makes the case-study job write its structural evaluation and environment record to `$CASE_REPORT_DIR`, by default `$DATA/speech_transcription_env/output/case_study/` outside the clone. The job refuses to overwrite an earlier result unless OVERWRITE=1 (exit 6 since 73c2f96), and prints the `cp` that brings a result into the tracked `output/case_study/` deliberately. Transcripts still go to the git-ignored `output/transcripts/`. tests/test_audit_shell_job_exit_status.py checks the directory and the refusal, and after the re-run (job 8978758, 2026-10-04) `git status` in the ARC clone listed no changed file.

**Why deferred.** The next step needs the author's decision or an ARC run. Found by the review of the fix branch.

**Failure scenario.** The case study writes its evaluation summary to output/case_study/, which is tracked, so after a run the ARC clone has a modified file and a later git pull can conflict. The environment record now excludes output/ from its modified-file count, so the record itself is no longer misleading.

**Proposed fix.** Write the run's summary to an untracked path and copy it into output/case_study/ deliberately when a new result is to be committed.

### LINT-01: 39 lint violations and 74 long lines remain after the safe automatic fixes

`ruff.toml:1` · MINOR · verified observed after the audit

**Status.** Resolved. 87d17fb (with the regeneration of the outputs that record its digests), e378f6d and e4cc39e wrapped every line over 100 characters, and e4cc39e enabled E501 in ruff.toml, so ruff 0.15.18 now reports nothing, line length included. Every file those commits touched parses to the same abstract syntax tree as before, apart from whitespace in docstrings, and tools/verify_regeneration.py passes. The shellcheck sentence is superseded by SC-23 (ed26529). No R or Dockerfile linter has been run, and CI (cpu-verification.yml) still runs no linter (G4).

**Why deferred.** The next step needs the author's decision or an ARC run. Recorded by the lint step.

**Failure scenario.** ruff (E, F, W, B, UP, SIM) leaves 39 violations without a safe fix: 13 B905 zip without strict=, 7 UP031 printf formatting, 3 F841, 2 B007, 2 F821 (string annotations naming np without an import), 2 SIM108, 2 SIM112, 2 SIM115, 2 W293 inside strings, 1 each of E731, SIM102, SIM103, SIM109. E501 (74 lines over 100 characters) is ignored in ruff.toml. No shell, R or Dockerfile linter (shellcheck, shfmt, hadolint, lintr, styler) is installed, so those languages were checked by reading and bash -n only.

**Proposed fix.** Work the remaining rules down by hand, each in its own commit, re-running tools/verify_regeneration.py after any change to code behind committed results. zip(strict=True) in particular can raise where a silent truncation happened before, so check each call site.

### NEW-03: The scoring normaliser joins a vulgar fraction to the number before it, so '29¾' is scored as '293 4'

`evaluation/wer.py:92` · MINOR · HIGH-RISK · changes numbers · touches end product · verified observed after the audit

**Status.** Resolved. On 17 October 2026 the author decided to keep the declared scorer (NEW-11), so a fraction is still scored as below. In the English sweep this touches one utterance: one of the 647 FLEURS English references writes a fraction after a digit, the same utterance in all three models' cells, and no other reference and no hypothesis in any of the fifteen cells holds a vulgar fraction (counted in the recovered hypothesis dumps on 17 October 2026). The multilingual arms kept no transcripts, so their count is not known. Found while the FLEURS re-run was assembled as a fourth arm (56ce519), and reproduced at f2578b8 on 2026-10-04.

**Failure scenario.** `normalise_text` (line 149 at f2578b8) applies NFKC before it strips punctuation. NFKC rewrites '¾' as '3', U+2044 FRACTION SLASH and '4', and the slash then becomes a space. `normalise_text('mide 29¾ pulgadas por 24½ pulgadas')` therefore returns 'mide 293 4 pulgadas por 241 2 pulgadas', and 'about 3½ hours' becomes 'about 31 2 hours'. The whole number and the numerator merge into one wrong token, and the word count of the reference or hypothesis changes with it. The re-run sweep's FLEURS dumps hold one such reference, utterance 1682 ("it measures 29¾ inches by 24½ inches"), in every condition for each of the three models. The Spanish, German and Dutch references of the same sentence in the multilingual arms carry the same fractions.

**Proposed fix.** Before NFKC, set a vulgar fraction that follows a digit apart as its own token, for example '29¾' as '29 ¾', so that the score sees '29 3 4', or map each fraction to a spelled form. Add tests for '29¾', '3½' and '½ cup'. Rescoring the English sweep needs only its kept hypothesis dumps on ARC. The multilingual arms kept no transcripts, so their figures would move only with new decodes. Both need sign-off.

**Committed results affected.** The FLEURS rows of `output/evaluation/sweep_aggregate.{csv,json}`, through utterance 1682, for every model and every condition except whisper_norm, whose published normaliser makes the same fold before this one runs. Two records kept as history were scored with the same fold, which `normalise_text` has made since fbabc7c (May 2026), and would move only if rescored. They are the FLEURS rows of the pre-repair `sweep_aggregate_prefix.{csv,json}`, and the May pilot's Whisper Medium FLEURS pair in `pilot_may2026/`, where utterance 1682 has the folded count of 35 reference words. In `fleurs_multilingual_summary.json` the Spanish, German and Dutch references of sentence 1682 write the fractions, and in arm 3 Whisper's transcript of one French recording held one too, so the figures of all four languages are affected. Arm 4's composite keeps the fractions (748ae6b) and scored every utterance exactly as raw, so the fold cannot have moved its ratios of 1. In arms 1 to 3 the composite's Unicode strip deleted such fractions (`finding.defect_1` and `defect_4`), so the fold may have moved their ratios a little. No arm kept its transcripts, and none can be rescored without a new decode. The sweep's LibriSpeech, AMI and VoxPopuli dumps hold no vulgar fraction.

### NEW-05: The FLEURS fourth arm's raw drift is put down to its GPUs, but no pair of runs isolates the card, and the planned P100 check cannot run

`output/evaluation/fleurs_multilingual_summary.json:1` · MINOR · touches end product · verified observed after the audit

**Status.** Resolved. The Spanish V100 control ran on 19 October 2026 at 6f9bf56 from the clean clone ~/paper_speech_transcription_ctl_es419: ARC jobs 9124739 (pre-flight, five utterances, htc-g003) and 9124863 (the whole split, htc-g004), both on Tesla V100-PCIE-32GB cards, with the same 179 packages, version for version, as the fourth arm's Spanish task (8917984_2); the summaries' decode and run metadata differ from that task's in the card alone. evaluation/fleurs_control.py (ce1ca7f) compares the decode with the four arms' Spanish summaries, each checked against the digest fleurs_multilingual_summary.json records, and 79d1e9c commits output/evaluation/fleurs_es419_v100_control.json with hpc/runs/fleurs_es419_v100.env. The control's records equal the third arm's (V100-SXM2-32GB, c0f58c5) and the first arm's on all 908 utterances, and its summary block equals the third arm's (raw macro WER 0.02937565607283082); against the fourth arm's L40S decode it differs on the same four utterances as the third arm (1735, 2004, 1966, 1785). Under docs/next_control.md's rule the card, with the node that holds it, accounts for the fourth arm's Spanish drift, and the code between the arms does not move the raw decode. The control cannot separate the card from its node, covers Spanish alone and compares scores, not transcripts. 1dde8df reports this in the multilingual section with a check of each claim, and 20df0e6 makes docs/next_control.md the record, including two departures from its commands (the full split ran beside the pre-flight, with a 2 h limit; it took 52 min). The multilingual summary is unchanged.

**Failure scenario.** Arm 4 (ARC job 8917984 at 6f9bf56) decoded on L40S, H100 and A100 cards, none of which arms 1 to 3 used. Its raw scores differ from arm 3's on 1 to 4 utterances per language, so raw WER moves by up to 0.0003 across the four arms against 0.0002 across the first three. The summary's control paragraph attributes the drift to the GPU as the only known difference, while saying that no pair of arms on the same architecture isolates it. Arms 1 to 3 recorded no package versions or dtype, so the attribution rests on the size of the drift and on the earlier arms, where every same-architecture pair wrote a byte-identical raw summary.

**Proposed fix.** Decode Spanish (es_419) at 6f9bf56 on a V100. Arm 3 decoded it on a V100-SXM2-32GB, and two different V100 boards already agree: arms 1 and 2 decoded German on a V100-SXM2-32GB and a V100-PCIE-16GB and wrote byte-identical raw summaries (by the digests in `benchmark.inputs`). If the card explains the drift, the new decode's per-utterance records match arm 3's Spanish ones exactly. On 2026-10-04, htc-g003 and htc-g004 had V100s in service. Until such a check, the manuscript should keep the summary's hedge.

**Committed results affected.** None move. What is open is the attribution of the 0.0003 spread in the control paragraph of `fleurs_multilingual_summary.json`, and in any manuscript sentence that repeats it.

### NEW-06: The case-study job points its structural evaluation at a manifest that does not exist on ARC, so the job fails after transcribing

`hpc/submit_case_study.sh:139` · MINOR · HIGH-RISK · touches end product · verified observed after the audit

**Status.** Resolved. Found on 2026-10-04 in the log of the case-study re-run, ARC job 8978758 at f2578b8. ca75ced and c4c7b38 make the job take CASE_MANIFEST when it is set, then `$DATA/codex_mentis/manifest.json` when that exists, then the committed `data/codex_mentis/manifest.json`, and stop before transcribing when the manifest it chose is missing or gives no durations, with tests in tests/test_audit_shell_job_exit_status.py and tests/test_s1_misc_podcast.py. Re-run 8983112 (wave 2c, from a clean clone at c4c7b38) ended with exit status 0 for the structural evaluation and the provenance verification, after test job 8983111 had passed 2,058 tests, and ac08cdc commits its results. hpc/runs/case_study.env records the run with CASE_MANIFEST written out, so that a later $DATA manifest cannot change a reproduction, and c787742 corrects hpc/README.md's job table, which still said the job needs a manifest in $DATA.

**Failure scenario.** The job (line 192 at f2578b8) passes `--manifest "${DATA}/codex_mentis/manifest.json"` to `evaluation.benchmark_podcast`, but `$DATA/codex_mentis/` on ARC holds only `audio/`; the fetch manifest is the committed `data/codex_mentis/manifest.json`. Until 4b22326 a missing manifest was ignored without a word, which is why the August summary has no coverage figures, and since then `benchmark_podcast` refuses it with exit 2 (EPRIV-23). Job 8978758 therefore transcribed the episode with speaker attribution (two speakers, 243 segments), and its structural evaluation then stopped with "Error: manifest not found: $DATA/codex_mentis/manifest.json" (exit status 2). The provenance check that runs after it, `python -m provenance verify`, passed over nine artefacts, and the job ended with exit 5, leaving only the environment record in its report directory (`audit2026/case_study_w2b`). The job's tests run the script with a stand-in `python`, so none of them could notice the path.

**Proposed fix.** Pass the committed manifest, `"$REPO_DIR/data/codex_mentis/manifest.json"`, which records episode 5's duration (1,938 s), unless a `$DATA` copy exists, and add a test that the job names a manifest present in a fresh clone. Then either run the structural evaluation alone on job 8978758's transcript JSON, which is still in the ARC clone's `output/transcripts/`, or re-run the job into a new `CASE_REPORT_DIR`.

**Committed results affected.** None. ac08cdc commits re-run 8983112's summary, report, review and manifest in place of the August run's (job 8441879), and its summary carries `coverage_ratio` and `segment_coverage_ratio`, which the August one lacked. `ep05_raw_text.txt` stays the August run's text on purpose, because the NER note measured it.

### NEW-07: The NER false-positive note counted the case study's "Jordan", a speaker's example of a false positive, as a genuine name

`output/case_study/ner_false_positive_test.md:18` · MINOR · changes numbers · touches end product · verified observed after the audit

**Status.** Resolved. Found on 2026-10-04 while the case study's README was rewritten for job 8983112, which read the word in its context (97e8c97) where the note had counted it as a name. c3e45e4 corrects the note's genuine-name column from 3 to 2 in each row by a hand count, keeps every redaction count (3, 18 and 3) and says so. It corrects the same count in output/case_study/README.md, README.md, a comment in transcription.py, a docstring in tests/test_ner_masking.py and, by a dated note, docs/expansion_plan.md, and 7b83945 rewords README.md, the comment and the docstring as the note words it. 311e799 brings the manuscript into line: its check requires exactly one false dictionary redaction and the note to name Jordan as the third (manuscript.qmd:4520-4539 at e515421), and the Results say that two of the three were names and Jordan was not (4684-4708). The Methods add that the initial capital does not stop the masker redacting a capitalised word that names something other than a person, such as Jordan for the country (1472-1477).

**Failure scenario.** The dictionary masker's three redactions of output/case_study/ep05_raw_text.txt are the first name and surname of the workflow's author, in the closing credits, and "Jordan" in "or if it masks the word Jordan when the discussion is about the country, not a person", a speaker's example of a problematic false positive. Job 8983112's text gives the same three at the same token positions (3580, 5181 and 5182). The note counted all three as genuine names, and the manuscript printed that count, so a reader took the dictionary's precision on the case study as three of three when it is two of three, and missed that the dictionary made the very error the speaker described.

**Proposed fix.** Count by reference: set the note's genuine-name column to 2 in each row and say what the third redaction is. In the manuscript, compute the dictionary's false redactions from the note's table, check that there is exactly one, and say that two of the three were names and that the third, Jordan, could not be removed by any capitalisation gate, since the word is capitalised.

**Committed results affected.** No measured figure. The note's hand-counted genuine-name column, 3 to 2 in each row, and the manuscript sentences that print it.

### NEW-08: The NER note gave the relaxed configuration the ungated arm's false-positive rate, but the ungated arm kept the dictionary's capitalisation gate

`output/case_study/ner_false_positive_test.md:55` · MINOR · touches end product · verified observed after the audit

**Status.** Resolved. Found while NEW-07 was checked, and reproduced at fb22ece on 2026-10-04. a27ac77 rewords the note: relaxing the gate for both stages costs at least the ungated arm's false positives, because that arm relaxed the gate for the NER stage alone and relaxing the dictionary's as well can only add redactions (lines 66-72 at fb22ece), which holds by construction. 311e799 says the same in the manuscript in place of "at the false-positive rate just described" (manuscript.qmd:4699-4708 at e515421). The relaxed configuration itself was not measured on the text, the alternative this entry also proposes, so its count of false positives is known only to be at least that floor.

**Failure scenario.** The note (line 55 at 10981d4, line 70 at 7b83945) said that relaxing the gate for both stages, `--ner --case-insensitive`, recovers lower-case names "at the false-positive rate measured above". The arm measured above dropped the gate for the NER stage only: its 18 redactions are the gated dictionary's three plus fifteen lower-case NER proposals. With case_insensitive=True the dictionary alone masks four words of ep05_raw_text.txt, adding the lower-case "grant" in "spending their grant money" as [SURNAME]. The relaxed configuration also masks every word the ungated arm did, so on this text it costs at least one false positive more than the sentence said, and the manuscript repeated the sentence (manuscript.qmd:4472-4473 at 5c903fd).

**Proposed fix.** Say that the relaxed configuration costs at least the ungated arm's false positives, which holds by construction. Alternatively, measure it on the text and give its count.

**Committed results affected.** None move: the wording of the note's sentence and of the manuscript's. The same paragraph of the note, and its table of the three measured configurations, still give the masking benchmark's recalls from before a08265c regenerated it (0.456 and 0.907 overall, where the committed summaries give 0.4737 and 0.9366), which the manuscript does not read.

### NEW-09: An honorific written with a full stop is never masked as [TITLE]

`transcription.py:596` · MINOR · HIGH-RISK · changes numbers · touches end product · verified observed after the audit

**Status.** Resolved. Found on 2026-10-04 in the closing credits of the case study, whose text kept "Dr." before the masked name, and reproduced at fb22ece. f30505a joins a piece of text that ends in an abbreviated title (Mr., Mrs., Ms., Dr. or Prof.) to the next before the masker looks for names, and masks the title as [TITLE] without its full stop; the full words, such as "sir", still end a sentence, and tests/test_masker_abbreviated_titles.py covers "Dr. Pablo Bernabeu" and "Mr. Smith". The masking benchmark's title carrier writes "Dr {name}", so its summaries did not move. On the author's decision of 17 October 2026 the case study was re-run at fc652ab (ARC job 9124852, on an L40S, since the RTX A6000 nodes are reserved). Its committed summary records 4 redactions among 5,382 tokens (0.00074), the fourth being the [TITLE] of the closing credits' "Dr.", and the masking test that compares ep05_raw_text.txt with the summary passes again. output/case_study/README.md describes the run.

**Failure scenario.** create_enhanced_name_masker (line 712 at f2578b8) splits its text into sentences on `(?<=[.!?])\s+` before the title rule looks at the next word of the same sentence. An honorific written with a full stop therefore ends its sentence and never sees the name. "developed by Dr. Pablo Bernabeu" gives "developed by Dr. [NAME] [SURNAME]", whereas "Dr Pablo Bernabeu" gives "[TITLE] [NAME] [SURNAME]", and likewise "Mr. Smith" gives "Mr. [SURNAME]" where "Mr Smith" gives "[TITLE] [SURNAME]". No name leaks this way, but the honorific, which narrows down who is meant, is kept whenever it is written with a full stop, as it is in the case study's transcript.

**Proposed fix.** Keep a title word followed by a full stop in the same sentence as the next word, for example by not splitting after an element of TITLE_WORDS, and add tests for "Dr. Pablo Bernabeu" and "Mr. Smith". The masking benchmark's title carrier writes "Dr {name}", with no full stop, so it would not move.

**Committed results affected.** output/case_study/podcast_eval_summary.json and podcast_eval_report.csv. benchmark_podcast counts [TITLE] among its placeholders (evaluation/benchmark_podcast.py:56 at fb22ece), so the case study's n_redacted would go from 3 to 4 and its redaction rate from 0.00056 to about 0.00074, the case-study README's "three redactions, a rate of 0.056 per cent" would follow, and so would the masking test that compares the text with the summary. The injection benchmark's summaries would not move.

### NEW-10: The NER note's label-phrasing paragraph leaves out that each narrower phrasing proposes "Jordan" and capitalised words that are not people

`output/case_study/ner_false_positive_test.md:36` · MINOR · touches end product · verified observed after the audit

**Status.** Resolved. Found while NEW-07 was checked, by a local run on 2026-10-04 that is not committed. On 17 October 2026 tools/ner_label_phrasings.py repeated the comparison in the environment of the committed NER arms (gliner 0.2.28, transformers 5.13.1, urchade/gliner_small-v2.1 at the pinned revision 4e091416, threshold 0.6), over ep05_raw_text.txt split as the masker now splits it, into 363 sentences since NEW-09, and output/case_study/ner_label_phrasings.json records the result. Each narrower phrasing marks "Jordan", "HPC", "SLURM" and "Whisper" among its capitalised words, and `person name` also "Researchers". The shipped set marks only the author's name, and all four mark speaker one and speaker two. This run does not reproduce the earlier one's "Pinanote". The note's label-phrasing paragraph now gives these words and the file. Its configuration table, which still gave the NER arms' figures from before a08265c, now gives the committed summaries' 0.474 and 0.937 overall.

**Failure scenario.** The paragraph (lines 49-53 at fb22ece) makes three claims: asking only for `person name`, `personal name` or `name of a person` still yields *speaker one* and *speaker two*, all three phrasings find the genuine names equally well, and the confusion is therefore in the task and not in the wording. In the local runs each of the three, asked alone, also proposes "Jordan" and the capitalised words "HPC", "SLURM", "Whisper" and "Pinanote", none of them a person, and `person name` also the sentence-initial "Researchers". The capitalisation gate would let all of these through ("Dr." is proposed too, but the masker never lets the NER stage mask a title word). The shipped label set (person, person name, participant name) proposes none of them, its only capitalised proposal being the author's name, and `personal name` finds *speaker one* but not *speaker two*. All four sets find "Pablo Bernabeu". Now that NEW-07 counts Jordan as a false positive, the paragraph understates what the narrower labels cost under the gate, although its conclusion, that the labels do not fix the confusion, still holds.

**Proposed fix.** Add a dated sentence giving what the narrower phrasings proposed in the later check. Alternatively, re-run the comparison and commit its output beside the note.

**Committed results affected.** None move. The paragraph's wording.

### NEW-12: The review layer cannot flag a passage Whisper writes twice, and in the case study three cues of repeated words carry no flag

`confidence.py:149` · MINOR · changes numbers · touches end product · verified observed after the audit

**Status.** Resolved. On 2026-10-06, confidence.py gained optional checks for zero-duration cues and repeated passages across cue boundaries, with both copies marked and linked by cue indices. The CLI enables them with `--flag-zero-duration --repeated-passage-words 8 --repeated-passage-window 60`; the token threshold and window are explicit settings, and numeric differences are retained. An apostrophe splits a word, so a contraction counts as two tokens, and since the follow-up of 10 October 2026 the CLI refuses a window given without the threshold. The tests cover fragments documented in the case-study README, intervening cues, window boundaries, overlapping matches, ordinary short repetitions, numerical contrasts and unusable timing. Existing behaviour is the default, so the committed review's four high_speech_rate flags and the manifest's digest remain unchanged. Since 17 October 2026 transcription.py runs the two checks through --review-flag-zero-duration, --review-repeated-passage-words and --review-repeated-passage-window and records them in the run manifest as review_settings, and hpc/submit_case_study.sh passes them at 8 words and 60 s. The case study's re-run at fc652ab, ARC job 9124852, flagged 13 of its 403 cues: the four of high speech rate that job 8983112 flagged, and with them both repeated passages. The three zero-length cues at 189.98 s carry zero_duration, and repeated_passage links the copy, cues 50 to 53, to the speech it repeats, cues 46 to 49, and the copy crammed into cue 84 to cues 85 and 86. No other cue of the episode was flagged as a repeated passage. Precision and recall on ordinary long-form speech remain unmeasured, so the checks stay optional and off by default.

**Failure scenario.** The review layer flags a cue whose words repeat those of the cue just before it (`duplicate_of_previous`), a token or a phrase of two to four tokens repeated three times or more within a cue, and a speech rate too high or too low, which it computes only for a positive duration (confidence.py:246-267 at f2578b8). A passage written twice with other text between the copies, or spread over several cues, meets none of these. In the case study, after the fabricated "Thanks for watching!" at 189.98 s, Whisper repeats the 24 words spoken from 179.86 to 189.38 s, timed at 189.98 s with no duration, in three cues of zero length and at the start of the next, and no flag marks them. The 31-word copy crammed into cue 84 at 319.80 to 320.00 s, which repeats the passage spoken in full from 320.04 s, is flagged only because the timeline repair merged three cues into one and so raised that cue's speech rate, and the August run, whose code did not merge them, flagged nothing there. A researcher who reviews the flagged cues therefore meets neither passage as a repetition, although both stay in every text output, since the repair moves times and never adds or drops a word.

**Proposed fix.** Add two checks to confidence.flag_segments: a flag for a cue of zero duration, which the rate flags skip, and a flag for a run of, say, eight or more words that occurs twice within a minute of transcript, across cue boundaries, marking both copies. Choose the run length and the window by what they flag on the case study and on ordinary speech, where a speaker may restate a short clause, and add tests for both. Adopting them changes the committed case-study review, whose SHA-256 the run manifest records, so it would take a re-run of the job.

**Committed results affected.** None unless it is adopted. Then output/case_study/codex_mentis_ep05_review.json gains flags beyond its four, so its flagged count and flag_rate (0.0099) move, and so do the run manifest that records the review's digest, the case-study README's account of the flags and the check of them in tests/test_s1_txt_review.py. The reviews of the example variants would need checking against the new flags too, since tests/test_example_variants.py regenerates them.

## The pass of 20 October 2026 (10)

### CR-02: The honorific rule keeps "Dr." before a possessive name

`transcription.py:838-841` (at bd37445) · MINOR · high-risk · touches end product · verified observed in the correctness review of 20 October 2026

**Status.** Resolved. 808307f strips the possessive clitic in the honorific rule's look-ahead as proposed; tests in tests/test_masker_abbreviated_titles.py ("Dr. Smith's", "Dr Smith's", curly apostrophe) fail without it. d6a5746 regenerates the four masking arms (seed 42; NER arms with gliner 0.2.28 and revision 4e091416): the 66 title-by-possessive rows of each report now read "[TITLE] [NAME]'s" or "[TITLE] [SURNAME]'s", and 136 lower-case title rows of the two case-insensitive arms change through 47540a5, which lets case_insensitive relax the gate on the name after a title. Every summary field outside run_metadata is unchanged, and tools/verify_regeneration.py passes.

**Why deferred.** The fix rewrites the `masked` column of 66 rows in each committed `masking_report*.csv`, which the regeneration gate compares, so it waits for the author's sign-off and a re-run of the masking benchmark.

**Failure scenario.** The name lookup strips a possessive clitic before it checks the dictionary (`stem = re.sub(r"['’]s?(?=\W*$)", "", ...)`), but the honorific rule's look-ahead does not: it turns "Smith's" into `smiths`, which neither dictionary holds, so the title stays while the name after it is masked. "It was Dr. Smith's idea." gives "It was Dr. [SURNAME]'s idea.", and "Dr Smith's" behaves the same. The committed benchmark shows it in every title-by-possessive row ("The referral was signed by Dr [NAME]'s this morning."). The benchmark leaves honorifics out of its precision, so no summary figure ever counted it, but it contradicts the 2.0.0 changelog's account that an abbreviated honorific followed by a name is masked as `[TITLE]`.

**Proposed fix.**
```diff
                 if is_title and word_idx + 1 < len(words):
-                    next_word = re.sub(r'[^\w]', '', words[word_idx + 1].lower())
+                    # The form the name lookup uses, possessive clitic
+                    # removed, so "Dr. Smith's" loses its title as well.
+                    next_word = re.sub(r'[^\w]', '', re.sub(
+                        r"['’]s?(?=\W*$)", "", words[word_idx + 1].lower()))
```
with the test case `("It was Dr. Smith's idea.", "It was [TITLE] [SURNAME]'s idea.")` in tests/test_masker_abbreviated_titles.py. Then re-run `python -m evaluation.benchmark_masking --seed 42` for the four arms (the two NER arms need gliner) and `python tools/verify_regeneration.py`.

**Committed results affected.** The `masked` column of 66 rows each in output/evaluation/masking_report.csv and masking_report_caseinsensitive.csv, and presumably in the two NER reports. A scratch run of the default and case-insensitive arms with the fix left both summaries equal to the committed ones.

### CR-06: The input deposit's README gives the aggregate's rebuild command without its arguments

`tools/build_input_deposit.py:98-100` (at bd37445) · MINOR · touches end product · verified observed in the correctness review of 20 October 2026

**Status.** Resolved in code. 7323b64 makes the README template give `--sweep-dir`, `--out` and `--out-json`, and say that the manifest's `availability` field predates the deposit; the command reproduces the committed sweep_aggregate.csv once line endings are normalised (the csv writer ends rows with CRLF on every platform, and the committed copy is LF), which is byte for byte only on a Windows checkout. Whether the deposited archive is rebuilt with it is recorded under DOCS-14 and in docs/release_readiness.md.

**Why deferred.** Any fix changes the bytes of the deposit archive and so its SHA-256 (`6474ba29…`), which docs/release_readiness.md records. The Zenodo record is still an unpublished draft, so rebuilding and re-uploading it is cheap now, but whether to do so is the author's decision.

**Failure scenario.** The README inside `sweep_inputs_2026-10.zip` says the aggregate's rows are rebuilt by `python -m evaluation.sweep_aggregate`. With its defaults that command scans `output/evaluation`, not the deposit, and would write over the committed `sweep_aggregate.{csv,json}`; its grid check stops it first. A reader following the README therefore cannot rebuild the rows, although the README's other two commands give their inputs and outputs. The archive also ships the committed `sweep_input_manifest.json`, whose `availability` field ("Checksum inventory only … await a versioned public deposit") is stale inside the deposit; editing that field would change the receipt digest that sweep_decode_provenance.json and scorer_sensitivity.json record, so a note in the README is the better fix.

**Proposed fix.**
```diff
 The summaries' digests are those recorded in the repository's
-`output/evaluation/sweep_aggregate.json`, whose rows
-`python -m evaluation.sweep_aggregate` rebuilds from them.
+`output/evaluation/sweep_aggregate.json`, whose rows this rebuilds from
+them:
+
+    python -m evaluation.sweep_aggregate \\
+        --sweep-dir build/recovered_arc_sweep/inputs \\
+        --out my_check/sweep_aggregate.csv \\
+        --out-json my_check/sweep_aggregate.json
+
+The manifest's `availability` field predates this deposit.
```
Then rebuild the archive, replace the file in the Zenodo draft, and update its digest and size in docs/release_readiness.md and DOCS-14.

**Committed results affected.** None of the results. The deposit archive's digest and byte count change.

### SC-17: An exception in the NER stage other than a model failure is swallowed without a count

`transcription.py:764` (at 83553b1) · MAJOR · high-risk · changes numbers · verified observed in the code pass of 20 October 2026

**Status.** Resolved. 73ac761 applies the proposed fix and reports the first such exception on stderr; tests in tests/test_ner_masking.py (a malformed score; a counted failure making _check_ner_ran refuse) fail without it. The NER arms re-run in d6a5746 record 1,940 calls and 0 failures each, with summaries identical outside run_metadata, so no committed NER figure was measured on dictionary-only sentences.

**Why deferred.** If such an exception ever occurred in a committed NER run, benchmark_masking._check_ner_ran would refuse that run once the fix is in, so the fix needs the NER arms re-run.

**Failure scenario.** ner_masking.PersonNameDetector.tokens_in counts an exception the model raises (`n_failures`) and reports the first on stderr. An exception raised after the model call, for example by a malformed entity whose score does not compare with the threshold, or by another detector with a tokens_in method, reaches the masker's `except Exception: ner_tokens = set()` and is swallowed. That sentence is then masked by the dictionary alone, with no count and no message, and a benchmark that checks `n_failures` reports the NER arm as clean.

**Proposed fix.**
```diff
-                except Exception:
+                except Exception as exc:
+                    # Counted with the detector's model failures, so that
+                    # benchmark_masking._check_ner_ran sees it; never fatal.
+                    if hasattr(ner_detector, "n_failures"):
+                        ner_detector.n_failures += 1
+                        if getattr(ner_detector, "first_error", None) is None:
+                            ner_detector.first_error = repr(exc)
                     ner_tokens = set()
```
Then re-run the four NER masking arms on a processor (`python -m evaluation.benchmark_masking --ner`, with and without `--case-insensitive`, gliner 0.2.28 and the pinned model) and compare them with the committed NER summaries.

**Committed results affected.** None, unless the re-run shows that such an exception occurred; then the NER rows of masking_summary_ner.json and masking_summary_caseinsensitive_ner.json were measured with some sentences masked by the dictionary alone.

### SC-18: audio_redaction leaves a name audible when its word has no timestamps, and says nothing

`audio_redaction.py:142` (at 83553b1) · MAJOR · verified observed in the code pass of 20 October 2026

**Status.** Resolved. 5bdf6a9 counts untimed name words in a raw transcript (and names in a segment without words) and, per segment of a redacted one, [NAME] and [SURNAME] placeholders beyond those its timed words carry ([TITLE] excluded). It refuses with exit 3 unless the new --allow-untimed-names is given, and reports the count on stderr either way; tests/test_audio_redaction_untimed.py covers an untimed final name, a redacted transcript with more placeholders than timed words, and the pipeline's redacted honorific (no alarm). 18dc947 makes an unreadable transcript or sibling exit 2.

**Why deferred.** The next step is the author's decision: whether the tool should warn or refuse, and how a `[TITLE]` placeholder counts.

**Failure scenario.** `_timed_words` skips every word without both a start and an end. In a raw transcript, a name word whose timestamp Whisper left as None (in the final chunk, for example) never reaches the masker, so it stays audible while the other names are silenced, and the tool writes its output and exits 0. In a redacted transcript, a placeholder in the segment text that no timed word carries is reported only when no timed word carries one at all. Comparing the two counts would raise false alarms, because the per-word redaction leaves an honorific such as "Dr" that the segment text masks as `[TITLE]`.

**Proposed fix.** Count the name words, or the placeholders other than `[TITLE]`, that no timed word carries, and either report them on stderr or refuse with exit 3, as for an empty result, unless `--allow-empty` is given. Add tests for an untimed final name word in a raw transcript and for a redacted transcript whose text holds more placeholders than its timed words.

**Committed results affected.** None. No committed result uses this tool.

### SC-19: Three source files that committed outputs record by digest carry small defects that cannot be fixed in place

`evaluation/wer.py:396` (at 83553b1) · MINOR · touches end product · verified observed in the code pass of 20 October 2026

**Status.** Resolved. 87d17fb gives evaluation.wer.evaluate_directory an optional `skipped` list, so the command line's summary records `summary.n_skipped_pairs` and a top-level `skipped_pairs` list (hypothesis, reference, error); aggregate() and every other consumer are unchanged. It also adds the missing docstrings, wraps the long lines (abstract syntax trees identical) and removes the unused noqa directives. ae6ff88 regenerates scorer_sensitivity.json and .csv and sweep_decode_provenance.json from the recovered inputs: only the three source digests and the recorded commit changed, the CSV is byte-identical, and no number moved.

**Why deferred.** output/evaluation/scorer_sensitivity.json records the SHA-256 (LF) of evaluation/scorer_sensitivity.py and evaluation/wer.py, and output/evaluation/sweep_decode_provenance.json that of tools/extract_sweep_decode_provenance.py. Any edit, a docstring included, would leave those records describing code that is no longer in the tree.

**Failure scenario.** wer.evaluate_directory drops a pair whose scoring raises, printing one stderr line, and the summary of the evaluation.wer command line records no count of skipped pairs, so a summary over fewer files than were given reads as complete. scorer_sensitivity.main and the two functions of extract_sweep_decode_provenance.py have no docstring, and 33 of the repository's 198 lines over 100 characters are in these files.

**Proposed fix.** At the next deliberate regeneration of scorer_sensitivity.json and sweep_decode_provenance.json (both need the recovered input bundle in build/recovered_arc_sweep/), record `n_skipped_pairs` and the skipped names in the evaluation.wer summary, add the three docstrings and wrap the long lines, then regenerate both outputs so that their digests describe the new files.

**Committed results affected.** The producer and original-scorer digests in scorer_sensitivity.json and `extractor_sha256_lf` in sweep_decode_provenance.json, rewritten by the regeneration. No number changes.

### SC-20: 265 noqa directives name rules the committed ruff configuration does not enable

`ruff.toml:14` · MINOR · verified observed in the code pass of 20 October 2026

**Status.** Resolved. 2ab2757 removed the unused directives outside the masking files (219, keeping 14 reasons as comments), 87d17fb one more, and a8b233c the remaining 53 (PLC0415, BLE001, D401, and E402 in tests/), keeping six more reasons as plain comments. `ruff check --extend-select RUF100 .` reports nothing, every touched file parses to an identical abstract syntax tree, and the three files of SC-19 changed only with the regeneration of their records.

**Why deferred.** The next step is the author's decision.

**Failure scenario.** `ruff check --extend-select RUF100` lists 265 directives that suppress nothing: 127 E402 in tests/, which the per-file ignore already covers, 109 PLC0415, 17 BLE001, 5 I001, 2 D401, 2 N802, and one F401 that is itself unused (evaluation/benchmark_anonymisation.py:75, since SAMPLE_RATE is used). A reader takes them as evidence that those checks run.

**Proposed fix.** Either enable PLC0415 and BLE001 in ruff.toml, so that the directives mean something and new sites must justify themselves, or remove them with `ruff check --extend-select RUF100 --fix`, leaving out the three files of SC-19, in a commit of its own.

**Committed results affected.** None.

### SC-21: Four copies of the chunked SHA-256 helper

`evaluation/fetch_codex_mentis.py:258` · MINOR · verified observed in the code pass of 20 October 2026

**Status.** Resolved. 7cecd95 makes fetch_codex_mentis import provenance.sha256_file. The extractor's and the scorer's copies stay, with the reason recorded in 87d17fb: the extractor runs as a script, and repetition_sensitivity imports scorer_sensitivity._sha256.

**Why deferred.** Two of the copies are in files frozen by committed digests (SC-19), and the gain from the others is small.

**Failure scenario.** fetch_codex_mentis._sha256_file, build_input_deposit._sha256, scorer_sensitivity._sha256 and extract_sweep_decode_provenance._digest each reimplement provenance.sha256_file. They agree today, since the digest does not depend on the chunk size, but a fix to one would not reach the others.

**Proposed fix.** Import provenance.sha256_file in fetch_codex_mentis, which runs with `-m` from the repository root. Leave the tool scripts, which do not put the root on sys.path, and the frozen copies.

**Committed results affected.** None.

### SC-22: requirements-dev.txt lists black and mypy, which nothing configures or runs

`requirements-dev.txt:12` · MINOR · verified observed in the code pass of 20 October 2026

**Status.** Resolved. 9533195 drops black and mypy and keeps ruff==0.15.18, and c312ce1 makes test_deps11 read the tool names from requirements-dev.txt.

**Why deferred.** The next step is the author's decision.

**Failure scenario.** A contributor who installs the development requirements gets two tools the repository has no configuration for. black's defaults would reformat code behind committed results, and mypy's would report thousands of findings, with nothing to say which outcome is wanted.

**Proposed fix.** Drop both, or configure them: black or `ruff format` in a commit of its own, after the regeneration gate, and a mypy configuration scoped to the modules meant to be typed.

**Committed results affected.** None.

### SC-23: LINT-01's count of long lines is out of date

`ISSUES.md` (LINT-01, Status) · MINOR · verified observed in the code pass of 20 October 2026

**Status.** Resolved. 87d17fb, e378f6d and e4cc39e wrapped all 198 long lines, each file's abstract syntax tree checked identical (docstring whitespace aside), and e4cc39e enabled E501 in ruff.toml; LINT-01 records the result. Since ed26529, `shellcheck -x` 0.11.0 reports nothing for the 24 tracked shell scripts (`git ls-files '*.sh'`; the count of 30 first given here was wrong).

**Why deferred.** The audit's Status paragraphs are a record of their date, so the correction is entered here.

**Failure scenario.** LINT-01 records 121 lines over 100 characters at 1f9f22e. `ruff check --select E501` finds 198 at bd37445 and at 83553b1: 57 in evaluation/repetition_sensitivity.py, added after LINT-01 was written, 45 in transcription.py, 26 in evaluation/scorer_sensitivity.py and 19 in tests/test_benchmark_results.py. Its sentence on shellcheck is superseded: since ed26529, `shellcheck -x` 0.11.0 reports nothing for the 30 tracked scripts.

**Proposed fix.** Wrap the long lines outside the files of SC-19 in a style-only commit, and update LINT-01's Status with these counts and with ed26529.

**Committed results affected.** None.

### SC-24: The fine-tuning script does not exit through exit_without_finalising although it streams AMI

`evaluation/finetune_pyannote_segmentation.py:1041` (at 83553b1) · MINOR · verified observed in the code pass of 20 October 2026

**Status.** Resolved. 25cd6ff ends the script as sweep_der does; a runpy test checks that `--help` passes status 0 and a usage error status 2 to exit_without_finalising.

**Why deferred.** The next step is the author's decision. The two processor smoke runs on ARC (8913986, 8918331) exited cleanly, so the abort has not been seen in this script.

**Failure scenario.** benchmark_der and sweep_der end through exit_without_finalising, because the datasets streaming stack leaves a native thread that can abort the interpreter at shutdown with status 134 after every result is written. finetune_pyannote_segmentation streams the AMI train split in its first phase and ends with a plain main(), so a GPU run that hits the abort would be reported as failed after saving its checkpoint.

**Proposed fix.** End the script as sweep_der does: catch SystemExit around main() and call evaluation.benchmark_der.exit_without_finalising with the status. Nothing in the script registers an atexit handler.

**Committed results affected.** None. No GPU fine-tuning result is committed.

## The pre-publication gate of 30 October 2026 (32)

Before the Zenodo records of release 2.1.0 were published, eight read-only
audits checked the tagged tree (ea50965) against its own data: diarisation,
timestamps, the English sweep and its deposit, the multilingual results with
the Spanish control and the hardware comparison, masking with fillers and
anonymisation, the footprint with the three deposit archives, the
manuscript as a whole, and the codebase. Every reported number reproduced,
and every rebuild matched. The findings below are what they found instead,
with PG-01 the reason the records were held and release 2.1.1 cut. The
author decided on 30 October 2026 to deposit the inputs PG-02 names and to
sanitise the identifiers PG-03 names. Line numbers are those of ea50965.

### PG-01: The manuscript explains the gross timestamp end errors as words the model never emitted, which the committed data contradict

`manuscript/manuscript.qmd:4532-4543, 4625-4631, 4648, 6222-6224`, `evaluation/timestamp_metrics.py:147-151`, `confidence.py:472-480` · BLOCKING · touches end product · verified by recomputation

**Status.** Resolved. 8bb2d5b rewrites the section, the table row and the Discussion, computing at render time from the sweep's AMI report that 32 of the 41 clips with an end error over half a second lost no reference word in the same model's decoding (all 18 with a one-word reference among them), and that 85% of ends fall within half a timestamp step of the clip end; the outputs READMEs say the same. a77f755 corrects the docstrings of timestamp_metrics, benchmark_timestamps, confidence.truncation_check and the review writer. No number and no key changed; `truncation_rate` is described as a historical name for ends more than half a second early.

**Failure scenario.** The paper's worst case, "covered 7.6%", is the one-word reference "yeah", transcribed "Yeah." with its last timestamp at 0.22 s of a 2.90 s clip. A reader told that the model stopped transcribing would distrust complete transcripts and misread the review's truncation flag.

**Committed results affected.** None.

### PG-02: The Open Practices statement says the per-utterance reports behind every table are in the repository, but three results rest on inputs held only on ARC

`manuscript/manuscript.qmd:6334-6339, 6362-6365` · MAJOR · touches end product · verified against the tree and ARC

**Status.** Resolved. On the author's decision, 8dd3d1d, d2416a5, 6123b8c, 93fd67b, 2c39081 and 89477e7 add tools/build_arc_inputs_deposit.py, its tests and the receipt output/evaluation/arc_inputs_manifest.json, and multilingual_hardware_inputs_2026-10.zip joins the data record: the 48 per-language summaries of the multilingual arms, the Spanish control's summaries and environment records, the cross-hardware comparison's dumps and reports, and the job logs that name the first three arms' cards, the files with deployment paths sanitised (PG-03) and both digests recorded. All three committed results rebuild from the bundle, apart from the digests of the four records the producers read before sanitisation. e79e30f makes the availability statements describe both archives, and the data record's description does the same.

**Committed results affected.** None.

### PG-03: Deployment identifiers and other projects' job names are in the archived tree, and the privacy records disagree on whether that was decided

`.hpc-plan.yaml`, `hpc/`, `tests/test_footprint_job_scope.py`, provenance fields of ten result files, `decoder_source_6f9bf56.zip` · MAJOR · touches end product · verified by `git grep`

**Status.** Resolved. On 30 October 2026 the author decided to sanitise them. 49cac3f, a8afadf and cdeeefa replace the ARC user name, both project codes and the paths holding them by a documented table, gives other projects' jobs synthetic names, updates the two recorded digests that the change touched (the cross-hardware comparison's record of its runs file and the case-study manifest's own), f64afdb adds tools/build_decoder_source_deposit.py for a sanitised decoder-source archive whose SANITISED.md lists every changed member with its original blob. docs/privacy_review.md records the decision and the table, G6 refers to it, and 5b46974 applies the table to the three files the pass left. The public snapshots of 2.0.0 and 2.1.0 on GitHub and the development history still hold the originals.

**Committed results affected.** Provenance strings only; no number.

### PG-04: The timestamp benchmark scores Whisper's segment timestamps, while the workflow writes word-level ones

`evaluation/benchmark_timestamps.py:296`, `transcription.py:4308`, `manuscript/manuscript.qmd:1829-1833, 3915-3917` · MAJOR · verified in code

**Status.** Resolved. 8bb2d5b says so in the Methods and the section's opening, and a77f755 in benchmark_timestamps' docstring.

**Committed results affected.** None.

### PG-05: A test-suite job is said to have checked "the release tree", which reads as 2.1.0's

`manuscript/manuscript.qmd:5810-5812, ~5619` · MINOR · verified against hpc/README.md

**Status.** Resolved. 8bb2d5b: job 9134598 checked release 2.0.0's tree, c17367b.

### PG-06: The footprint's per-core CPU power had no source, and its share of the total was understated

`evaluation/footprint.py:527-532` · MINOR · verified against the Green Algorithms data

**Status.** Resolved. 78beb7b cites the 12 W "Any" row of Green Algorithms' v2.2 CPU table (Green-Algorithms-data at 0a1d169b) and states the CPU term's share, 14.17 of 96.71 kWh. The footprint artefacts are unchanged.

### PG-07: The data record's reference carries the date of the 2.0.0 build and describes one of its archives

`manuscript/references.bib:31-38`, `manuscript/manuscript.qmd:6300-6303` · MINOR

**Status.** Resolved. e79e30f dates the record as published, gives it the title of its two archives and names them in the availability statements.

### PG-08: Committed files still say the English inputs await a deposit

`output/evaluation/README.md:236-240, 284-285`, `output/evaluation/sweep_input_manifest.json` (`availability`) · MINOR

**Status.** Resolved for the README in 8bb2d5b. The manifest's field is left as CR-06 decided: its digest is recorded by sweep_decode_provenance.json and scorer_sensitivity.json, and the deposit's README says the field predates the deposit.

### PG-09: The manuscript cites development commits that no reader can check out

`manuscript/manuscript.qmd` (provenance paragraph), `output/evaluation/README.md:89-94` · MINOR · verified with `git diff 9cb43e3 v2.1.0`

**Status.** Resolved. 8bb2d5b says the commits are the development repository's, that the data record holds the decoder commit's source, and that the release's diarisation scoring code differs from 9cb43e3 only in comments, documentation and when it reads run metadata.

### PG-10: The oracle speaker-count arm is called an upper bound, but it scores worse than the defaults

`manuscript/manuscript.qmd:3901-3902`, `evaluation/benchmark_der.py:783, 1045` · MINOR · verified (macro DER 25.0% against 16.6%)

**Status.** Resolved in 8bb2d5b and f49edab.

### PG-11: The Methods give the diarisation pipeline two tuning parameters; it has three

`manuscript/manuscript.qmd:~2034` · MINOR

**Status.** Resolved. 8bb2d5b: two of its three were swept, the minimum cluster size held at its default.

### PG-12: Micro DER cannot be recomputed from the committed per-meeting rows

`evaluation/benchmark_der.py:741-746`, `evaluation/sweep_der.py:90-94` · MINOR · verified (macro recomputes exactly)

**Status.** Open. The rows carry rates, not each meeting's scored reference time. Adding that column changes the reports, so it waits for the next diarisation re-run; an estimate from the committed counts agrees with the recorded micro DER to the fourth decimal.

### PG-13: README.md says every Hugging Face model the runs loaded is pinned

`README.md:25` · MINOR

**Status.** Resolved in dc4124a, with DEPS-04's Status.

### PG-14: "Indistinguishable from the defaults and fractionally worse" holds only for macro DER

`manuscript/manuscript.qmd:~6100` · MINOR

**Status.** Resolved in 8bb2d5b.

### PG-15: The timestamp distribution is said to have nothing left of the origin, and the end boundary's edge goes unmentioned

`manuscript/manuscript.qmd:4511-4512, 4561-4562` · MINOR · verified (173 ends at −10 ms; 85% within half a step of the clip end)

**Status.** Resolved in 8bb2d5b.

### PG-16: EWER-10's Status still says the Spanish control awaits approval

`ISSUES.md:708` · MINOR

**Status.** Resolved in dc4124a.

### PG-17: The multilingual summary says raw is stable "to within 0.0003" without "at four decimals"

`output/evaluation/fleurs_multilingual_summary.json:77` (`ratio_definition`) · MINOR · verified (exact spread 0.000308)

**Status.** Open. The field is prose carried in a committed artefact; the manuscript computes 0.0004 from the exact rates. The producer's wording can change at the next assembly.

### PG-18: The outputs README attributes the Spanish drift to the card and drops its node

`output/evaluation/README.md:88` · MINOR

**Status.** Resolved in 8bb2d5b.

### PG-19: The Spanish control compares differing utterances by sentence id, which repeats

`evaluation/fleurs_control.py:322-329` · MINOR · latent

**Status.** Resolved. c0c4467 compares (position, id) pairs; the committed comparison is unchanged, since the control equals the third arm at every position.

### PG-20: CR-06 claims a byte-for-byte rebuild that holds only on Windows

`ISSUES.md` (CR-06) · MINOR · verified (CRLF rows against an LF checkout)

**Status.** Resolved in dc4124a.

### PG-21: G2's Status still reports dirty working trees

`ISSUES.md` (G2) · MINOR

**Status.** Resolved in dc4124a.

### PG-22: Two bullets of the 2.1.0 changelog are loosely worded

`CHANGELOG.md:141-148` · MINOR

**Status.** Resolved in dc4124a ("[TITLE] [SURNAME]'s"; every leak count unchanged).

### PG-23: A name found by NER alone keeps a preceding title

`transcription.py` (`_is_title_token`) · MINOR · verified (40 held-out rows in the NER arm, 92 in the case-insensitive NER arm)

**Status.** Resolved in documentation, d6f415f. The rule is unchanged, so no masking figure moves.

### PG-24: `python -m evaluation.bootstrap_ci --help` raises ValueError

`evaluation/bootstrap_ci.py:381` · MINOR · verified

**Status.** Resolved. 18e3c20 escapes the %, and tests/test_cli_help_strings.py scans every help string.

### PG-25: setup_pyannote.py installs pyannote.audio without the <4 cap and installs speechbrain

`setup/setup_pyannote.py:93-98` · MINOR

**Status.** Resolved in 42fb22b, which installs the specifiers of requirements.txt in one pip call.

### PG-26: The lock's header does not say it is unhardened or which artefacts it does not cover

`requirements-lock.txt:1-33` · MINOR

**Status.** Resolved in 86d005c (comments only; 178 pins, Python 3.12.12 still parsed).

### PG-27: OUTPUTS-12, DEPS-04 and DOCS-15 name a superseded manifest or the wrong repository

`ISSUES.md` · MINOR

**Status.** Resolved in dc4124a.

### PG-28: Exact zeros in the paired-interval tables print as +0.00

`manuscript/manuscript.qmd:626` (`sgn2`) · MINOR

**Status.** Resolved in 8bb2d5b.

### PG-29: The NER false positives are quoted with articles the note does not give, and a code comment cites an old wording of the manuscript

`manuscript/manuscript.qmd:4925-4926`, `transcription.py:1295` · MINOR

**Status.** Resolved in 8bb2d5b and 46357ed.

### PG-30: The full test suite has not run on ARC for this release

`docs/release_readiness.md` · MINOR

**Status.** Open. Submitting the job needs the author's approval; the CPU selection passed on GitHub's runner and locally, and the eleven-artefact gate passed.

### PG-31: The input deposit's README misdescribes the decoder source once it is sanitised, and puts the release's DOI after the decoder commit

`tools/build_input_deposit.py:88-146, 227-229` · MINOR · touches end product (the deposit's README)

**Status.** Resolved. 2ba6fe3 says the decoder source replaces the deployment identifiers as its SANITISED.md lists, that it is licensed as the releases are, and that the DOI given is the release's. `sweep_inputs_2026-10.zip` is rebuilt with it; its 270 inputs are unchanged.

### PG-32: Of two releases with the same date, the version lookup returns the older

`transcription.py:2896-2914` (`_latest_release`) · MINOR · found while stamping release 2.1.1

**Status.** Resolved. The tie went to the later row of versions.csv, which lists the newest release first, so with 2.1.1 and 2.1.0 both dated 2026-10-30 every transcript, manifest and stamp would have named 2.1.0. The tie now goes to the higher version number, and tests/test_s1_txt_version.py checks the newest-first order; tests/test_installed_distribution.py, which had copied the old rule to compute the release it expects, follows the new one.

**Committed results affected.** None; the example variants are restamped with the release.

## Observations from ARC

Read-only checks on the cluster during the audit and its re-run wave turned up three
facts that bear on the committed results. The first two are now settled. The third is
an incident, NEW-INC-01, and its consequences are set out below.

Job 8781724 (`determinism_gpu`, an L40S on htc-g064, completed 2026-09-12) ran with
the default report directory, so on ARC it overwrote the August files under
`output/evaluation/determinism/`, the hypothesis dumps of the August H100 NVL run
(job 8554985) among them. Its own summaries, `gpu.txt` and WER report are now
committed in `output/evaluation/determinism/l40s_8781724/`, beside the August copies,
and `determinism_cross_accelerator.json` compares the two runs with the re-run
sweep's Large v3 AMI decode on a V100 (3efc8c8, 06d5a53). Both determinism runs gave
the same text for all 200 utterances within their card, repeated and across seeds.
The August run enters through the per-utterance error rates its log printed, which
differ from the L40S run's on 1 of 200 utterances (0.333 against 0.111), and the L40S
and V100 decodes differ in text on 2 of 200. Two more runs were submitted on
2026-10-04. The CPU arm, job 8978759, decoded in float32 with 16 threads on an AMD
EPYC 9634 (htc-c074), and its summaries, `cpu.txt` and WER report are committed in
`output/evaluation/determinism/cpu_8978759/` (ddb37e6) and compared with the other
runs (9084c63). Its repeat and second seed matched its first decode on all 200
utterances, and its words match the V100 decode's on all 200 and the L40S run's on
198, differing on the 2 on which the L40S and the V100 differ. The V100 run of the
check itself, job 8978760, completed the same day, from 11:22 to 11:38 on htc-g004,
the node of the sweep's V100 pass (sacct), and wrote into
`repro/v100_arm/determinism/` on ARC. Its summaries, `gpu.txt` and WER report are
committed in `output/evaluation/determinism/v100_8978760/` (203d3ba), and the
comparison holds it as `v100_seed0` (c813fe5). Its repeat and second seed matched its
first decode on all 200 utterances. Its words match the sweep's V100 decode and the CPU
arm's on all 200, with hypothesis files and WER reports byte-identical to the CPU arm's,
and differ from the L40S run's on the same 2. `hpc/runs/determinism_v100.env` (ba982b9)
and `hpc/runs/determinism_cpu.env` (3cae28a) now give the directories the two runs of
2026-10-04 wrote into as their originals and send a reproduction elsewhere (SHELL-08).

`$DATA/speech_transcription_env/output/evaluation/postfix/` holds the 240
`wer_summary*.json` files behind the earlier matrix but no `sweep_aggregate.json`:
that aggregate was assembled locally from a copy (`C:\tmp\pf2`, recorded in its
`source_file` column), which is why it could not be regenerated by the committed
script (EWER-02). This no longer applies. Since 2e36bf9 the committed
`sweep_aggregate.{csv,json}` is the output of `evaluation.sweep_aggregate` itself
over `audit2026/sweep`, the re-run sweep (jobs 8917985 to 8917987 at 6f9bf56), with
255 rows, one pipeline version, source paths relative to the sweep and the SHA-256 of
every input summary. `hpc/aggregate_sweep.sh` defaults to that directory.

NEW-INC-01 is the incident in which the test suite corrupted the shared pyannote
cache. Test-suite jobs 8913985 (commit 76d9489, 2026-09-26 23:52 to 2026-09-27 00:03)
and 8917186 (commit 2e5e852, 2026-09-27 11:53 to 11:59) each wrote a 119-byte stub
without `pipeline.name` over the cached `config.yaml` of
`pyannote/speaker-diarization-3.1` in `~/.cache/torch/pyannote` (blob `5402e3ca`),
through the snapshot's symlink. The pre-cache test in `tests/test_s1_env_setup.py`
was handed the real cache, because an earlier test had imported pyannote.audio. The
blob was restored on 2026-10-04 at 00:03, and `git hash-object` prints its name
again. Four workflow jobs tried to load the pipeline in between, and all four passed
their preflight with `--diarisation-required`. Case-study job 8918023 could not load
it (`Underlying error: 'name'`), transcribed without speaker attribution and failed.
Anonymisation jobs 8913992 (a 12-utterance pre-flight, `preflight_anon`), 8917988 and
8917989 fell back to loading `pyannote/wespeaker-voxceleb-resnet34-LM` directly, and
their summaries say so. Their `embedding_model` lacks the suffix "(via the
diarisation pipeline)" that the August summary carried, and their `revisions` omit
`pyannote/speaker-diarization-3.1`, which a run through the pipeline records. A
diagnostic job after the restore (8976304) found that the pipeline's embedder and the
directly loaded model give identical embeddings on four 3-second random inputs on CPU
(largest absolute difference 0.0), so the two routes load the same model.

The anonymisation runs were not repeated. 8b6144c commits the summaries of 8917989
and 8917988 as they are (`anonymisation_summary.json` and
`anonymisation_single_meeting/`), and `hpc/runs/anonymisation.env` records the
fallback and the 8976304 check; the pre-flight's output is not committed. The case
study was re-run as job 8978758 at f2578b8 on 2026-10-04, after test job 8978757 at
the same commit had passed 2,032 tests with one skip and one expected failure, the
symlink tests of the fix among those that ran. The pipeline loaded and found two
speakers, but the job then failed its structural evaluation (NEW-06), which ca75ced
fixes. Job 8983112 re-ran it the same day from a clone that includes ca75ced, after
test job 8983111 from that clone had passed 2,058 tests with one skip and one
expected failure. It loaded the pipeline, found two speakers and completed, and ac08cdc
commits its summary, report, review and manifest as the case study, in place of the
August run's (job 8441879). The blob still hashed to its name after these four jobs (`git hash-object`
on ARC at 11:51 on 2026-10-04). Four changes guard against a repeat, and a fifth
names the damage when a load still fails on it. The suite redirects every model cache
into a temporary directory for the session, and its stand-in downloader refuses to
write outside its `tmp_path` or through a link (efa2962, d41cd96).
`python -m preflight` reports a damaged cached pipeline config, and fails a job run
with `--diarisation-required` over one (d63aa57, 8a4075c). 463340a extends that check
to every blob of the pipeline whose name is a digest, linked or not, so preflight
also finds a damaged blob whose snapshot link was deleted.
`setup/cache_pyannote_arc.py` exits 3 instead of reporting success over a damaged
config (3334257), and since 463340a over such a blob as well. 1bbae87 has
`transcription.py` name each damaged file when a diarisation load still fails, and
say that neither a token nor a new download repairs it.

## Areas the audit did not cover

The completeness check found these gaps after the main pass. They are recorded
rather than silently dropped.

### G1: manuscript/manuscript.qmd end to end (render), manuscript/apa.csl, manuscript/references.bib, manuscript/protected_terms.json

No auditor rendered the manuscript. MS said explicitly 'no quarto render' and 'apa.csl ... not audited', and replicated inline R expressions in a standalone script instead. Quarto is installed locally (C:\Program Files\Quarto\bin\quarto.exe, verified), so render failures, silent fallbacks to typed literals (MS-10), the undefined 'sweep_dir' guard (MS-17), citeproc or crossref warnings, and CSL-driven reference formatting can all be observed directly. This is the end product that goes to Behavior Research Methods.

**Status.** Partly resolved. At f2578b8 the condition_order check stopped the render, because the committed sweep_aggregate.csv has 17 conditions and the list named 16, and 02079b4 fixed it. Three of the defects this gap names are fixed: 70926fa removed the typed fallbacks (MS-10) and the undefined `sweep_dir` guard (MS-17), and 3c48f8a pruned the bibliography (MS-19). The Stage 4 rewrite (0e90917) and the commits from 33a8e13 to e515421 bring the text to the re-run, leaving two PHASE2 notes, both for the release (manuscript.qmd:1651-1653 and 5983-5985 at e515421), where fd7b0a7 had 37. The 6 October 2026 continuation renders the final HTML and 100-page PDF with all claims checks passed. It checks the twelve tables, six figures, front matter and changed reference formatting; all 34 HTML citations match bibliography entries, with no unresolved cross-reference or broken fragment link. APA display mechanics and the checked Behavior Research Methods format are recorded in manuscript/journal_profile.json and docs/release_readiness.md. The author supplied the correspondence and funding details on 17 October 2026, and release 2.0.0 replaced the two PHASE2 notes with its citation (MS-09). Full authoritative field verification for every reference and the remaining language review remain outstanding. Formatting and a successful render do not settle those facts.

### G2: output/evaluation/masking_report_ner.csv, masking_summary_ner.json, masking_report_caseinsensitive_ner.csv, masking_summary_caseinsensitive_ner.json; evaluation/benchmark_masking.py; ner_masking.py

The NER masking numbers the manuscript reports (for example case-insensitive+NER 0.907) have no known producer. DEPS could not find where they were produced (gliner is absent from the ARC env). REGEN skipped them on the claim that 'gliner [is] not installed', but gliner 0.2.28 IS installed locally (verified with pip show). The files entered the repo only via an auto-sync commit (50314de, 2026-08-10) with no command recorded, and masking_summary_ner.json records no gliner version or model revision. EPRIV-08 (threshold passed positionally into flat_ner) and EPRIV-12 (a NER model that raises silently degrades to dictionary-only) mean these committed numbers may not measure what they claim to measure.

**Status.** Partly resolved. The threshold and silent-degradation defects stay fixed (EPRIV-08, EPRIV-12), and a08265c's local regeneration of all four masking arms at seed 42 moved overall recall from 0.456 to 0.474 with NER and from 0.907 to 0.937 with case folding and NER. Each NER summary now names its producer: run metadata (gliner 0.2.28) and an `ner` block giving the model (urchade/gliner_small-v2.1 at the pinned revision 4e091416), the threshold (0.6), 1,940 calls and no failures. The dirty working trees that three of the a08265c summaries recorded are gone: d6a5746 regenerated all four arms from a clean tree after the honorific fixes of the 2.1.0 pass, and every summary now records `git_dirty: false` (three at 9b43b5a, the case-insensitive NER arm at 1d2f2ac; only lint commits touch the masker since). The pre-publication gate of 30 October 2026 re-ran three arms at ea50965 and matched them apart from run metadata and line endings. tools/verify_regeneration.py still rebuilds only the dictionary arm, so the NER arms stay outside the gate (G5).

### G3: data/curated_names.csv (and its consumers transcription.create_multilingual_curated_names and evaluation/benchmark_masking.py); manuscript.qmd ~488 and the masking section ~2290

Nobody audited the provenance or versioning of the name dictionary behind every masking number. T1, EPRIV and DOCS only counted its rows. The file has a single commit (8d8c58e 'init', 2025-11-05) and no documented source, licence, selection criteria or builder script. docs/audit_phase2.md:95-97 says its entries were 'chosen for recall against the small corpus of recordings that have shipped with the project'. The masking benchmark then scores 'in_db' recall on names drawn from that same CSV, so the in-dictionary recall and the example transcripts may be circular. No committed artefact records a hash of the CSV, so a later edit would silently change masking results.

**Status.** Resolved. Every masking summary now records the SHA-256 of `data/curated_names.csv` (`curated_names_sha256`, written since 04c01b3 and present in all four summaries since a08265c), so an edit to the list would show against the committed results. The list is unchanged since 8d8c58e. docs/dictionary_provenance.md now records its history, 1,793 rows, 1,559 distinct name strings and nine language labels, with their limitations. The author stated on 17 October 2026 that they compiled the list themselves, so it has no external source and is distributed with the software under the MIT licence (XREF-14), as docs/dictionary_provenance.md now records. Its selection procedure is not recorded, and no builder recreates it. The in-dictionary cells still draw their names from the list, so they measure the casing gate, not the list's coverage: the dictionary arm masks all 680 title-cased in-dictionary names and none of the 680 lower-cased ones (recall 0.5 in every language).

### G4: Repo-wide tooling and hygiene configuration: .gitattributes, missing lint/format config (pyproject.toml / ruff / R / shell style), absence of CI, favicon.ico, cross-language style standardisation

No auditor owned the /strong-codebase style and standardisation dimension. Several auditors left lint hits (F401, B033, B905, UP rules) 'to the lint pass', and no lint pass exists. No pyproject.toml, ruff config, editorconfig, pre-commit or .github/workflows is tracked (only an untracked .ruff_cache), so style is unenforced and the test suite has no automated run (TESTS-01). .gitattributes holds only '* text=auto'. On this checkout the working-tree line endings are mixed: hpc/run_tests.sh, hpc/batch_transcription.sh, activate_project_env_arc.sh and setup/setup_environment.sh are CRLF while setup/docker-entrypoint.sh and hpc/submit_anonymisation.sh are LF (verified with git ls-files --eol). A fresh Windows clone with core.autocrlf=true therefore gives CRLF shebang scripts, which break a Docker build from Windows or an scp to ARC. favicon.ico is tracked but referenced nowhere (git grep).

**Status.** Partly resolved. ruff.toml and its fixes are committed (24b2071, 7cbedae, 7924a60, with LINT-01 giving what remains), and shellcheck has been run once over the job scripts (df7e87d). .gitattributes checks out with LF `*.sh` (8952c7c), `example_output/variants/**` (f041d21), the `hpc/runs/*.env` records that bash sources on ARC (4ba44b9) and, since ac08cdc, the case study's JSON files, so that the review still has the digest its manifest records. In a fresh Windows worktree of fb22ece all 24 tracked shell scripts and all 16 records are therefore LF (`git ls-files --eol`, 2026-10-04). A working copy checked out before 4ba44b9 keeps CRLF records until they are deleted and checked out again, as hpc/README.md says (2c1c911). On 6 October 2026, .github/workflows/cpu-verification.yml added a test and regeneration workflow pinned to Ubuntu 24.04 and Python 3.12.12, with read-only permissions, offline model settings and an isolated CPU dependency subset; docs/ci.md gives its scope and local command. As committed it set TMPDIR from the runner context in the job's env, where GitHub does not allow that context, so the file failed validation and no step could run. The follow-up of 10 October 2026 exports TMPDIR from a step instead, and actionlint 1.7.7 now passes the file. The workflow first ran on GitHub on 17 October 2026, after the author approved pushing the review branch: its first two runs found two defects, a run-manifest field that changed the committed example variants (fixed in 05e0530) and an artefact-audit file order that differed between Windows and Linux (fixed in 9e211db), and its third run (39053843039, at 1832fb0) passed all 389 tests of its selection and the full gate on Ubuntu 24.04 with Python 3.12.12. Automated linting, R and Dockerfile linters remain absent, and favicon.ico is still tracked and referenced nowhere.

### G5: Rebuild-and-compare verification gate (no committed script or target); masking run-to-run determinism

/strong-codebase requires a committed rebuild-and-compare gate. REGEN showed that about 12 artefacts regenerate byte-for-byte on CPU, but it did so with an ad hoc scratch script (SCRATCH/regen/compare.py). No Makefile, pipeline script or test re-runs those producers and diffs them against the committed files, so nothing prevents new drift like DEPS-07/REGEN-05 (the hand-edited sweep_aggregate) or REGEN-09 (the schema-stale masking summary). No auditor raised the missing gate as a finding. REGEN also stopped before a second masking run, so run-to-run determinism of masking_report*.csv is unverified.

**Status.** Partly resolved. tools/verify_regeneration.py (fa96d93, with the JSON and path-separator allowances of 9cbd1d9) is the committed gate. The new .github/workflows/cpu-verification.yml runs the focused CPU tests and all eleven gate artefacts on pushes, pull requests and manual requests, and on 17 October 2026 its first passing hosted run (39053843039) matched all eleven on Ubuntu, once the artefact audit stopped depending on the platform's path order (9e211db). It rebuilds eleven artefacts, adding the reader-cluster sensitivity report on 2026-10-06 alongside footprint_report.csv, footprint_summary.json, condition_ci.csv, condition_ci_postfix.csv, normaliser_gain_ami.csv (added to the gate in 81d8054), wer_ci.csv, artefact_audit.{csv,json} and the dictionary arm's masking_report.csv byte for byte, and masking_summary.json apart from generated, generated_at and run_metadata. Run in full on a clean Windows checkout of 913ad58 on 2026-10-04, it passed in 64 s, the footprint pair, which had been the only difference at f2578b8, having been regenerated in e3e436d. At fb22ece the same day it matched all ten again over two runs: in the first, made while the machine was short of memory, the two bootstrap producers exited 1, and a second with --skip-masking matched their tables. The 6 October 2026 portability check adds a narrow dictionary-digest allowance for LF/CRLF checkouts: both digests must identify the current dictionary and all other nonvolatile fields must agree; changed entries still fail. Fifteen adversarial gate tests cover that allowance. The other half of this gap, the masking benchmark's run-to-run determinism, is settled for the dictionary arm the gate runs: its report was byte-identical across at least five commits of the fix pass, and the runs at f2578b8, 3ca26dc, 913ad58 and fb22ece reproduced the report committed in a08265c.

### G6: Git history and committed example artefacts as published privacy surface: example_output/name_masking_logs/*.csv, example_output/transcripts/*.docx, deleted files in history, output/case_study/ep05_raw_text.txt

The repository is public and archived on Zenodo, and the paper's subject is privacy, yet no auditor inspected git history or the committed replacement logs as a privacy surface. OUTPUTS-07 covers .gitignore and CORE-05 covers the manifest, but none of the 16 coverage notes mentions reading example_output/name_masking_logs/*.csv, which commit original names next to full context sentences (verified: 'Pablo' and 'Bernabeu,' with the sentence). History contains three deleted example transcript and replacement-log files (verified with git log --diff-filter=D). A quick grep found no hf_ token in history, but no systematic secret, PII or account-name scan was done, and the .docx example transcripts were never opened (OUTPUTS: only the .txt twins were read).

**Status.** Resolved. The 6 October 2026 review is recorded in docs/privacy_review.md. It inventoried 839 locally reachable commits and 2,021 distinct blobs, checked identifier categories in the text versions, inspected all four current and two historical Word documents, and read deleted example files and name logs. Gitleaks 8.30.1 scanned ordinary and merge diffs; all eight merge-inclusive findings were bibliography keys, with no confirmed credential among the reported matches. The current Word bodies match their text twins after whitespace normalisation; one retains the public author's editor identifier. A deleted older masking log includes an additional first-name token whose identity is unestablished. The unsupported README infographic was moved unchanged to docs/historical/ with a contextual note. Historical logs, transcript originals and Git history remain intact. On 17 October 2026 the author decided not to rewrite the history and to keep the historical Word files' editor metadata, the author's own name. The public repository, github.com/pablobernabeu/secure_local_HPC_speech_transcription, which has held the software since release 1.0.0, receives each release as a single snapshot commit and so carries none of this repository's history, and the recovered inputs go to a separate data deposit, whose bundle a scan found free of deployment paths, account names, email addresses and tokens. The bounded review does not establish that every personal identifier is absent. On 30 October 2026 the author decided to sanitise the deployment identifiers in release 2.1.1 and its deposits, which docs/privacy_review.md records with its substitution table (PG-03); the public snapshots of 2.0.0 and 2.1.0 on GitHub keep the originals.
