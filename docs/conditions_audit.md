# Post-processing conditions audit

This document records the gradual, systematic expansion of the
post-processing workflow that feeds the WER benchmark. Each condition
registered in `evaluation/conditions.py` is a single, named text
transformation applied to the ASR hypothesis (and, where the
`apply_to_reference` flag is set, symmetrically to the reference)
before scoring. Conditions are deliberately atomic so that their
individual contribution to the word error rate can be disentangled.

## Acceptance protocol for a new condition

A new condition is accepted into the registry only after passing four
checks. The protocol is the same for every condition, so that the
audit trail remains uniform across the iterative expansion.

The first check is *unit*. The condition must be accompanied by
behavioural tests in `tests/test_conditions.py` that exercise the
identity case, the intended transformation, the idempotency property,
and the boundary conditions that the design notes call out as
deliberately out of scope. The local pytest suite must remain green.

The second check is *registry integration*. The condition must
declare a valid slug, a one-sentence description in British prose, a
pure `str -> str` transform, an `apply_to_reference` flag with
explicit justification in the notes field, and must appear in the
output of `python -m evaluation.benchmark_wer --list-conditions`.

The third check is *pilot benchmark*. The condition must be run
against a small slice of LibriSpeech `test-clean` (200 utterances) and
its effect on WER, MER, WIL and CER must be recorded relative to the
`raw` baseline and to the most-similar existing condition. The pilot
slice deliberately uses the same dataset and split as the canonical
benchmark so that the pilot numbers can be compared like-for-like
once the full ARC sweep completes.

The fourth check is *documentation*. The condition's purpose,
mechanism, expected effect, observed effect on the pilot slice, and
any caveats are recorded in this file under a dated heading. The
entry should be readable independently of the source code by anyone
reviewing the audit trail.

## Conditions registered

### `raw` (baseline)

The identity transformation. Establishes the unmodified baseline
against which all post-processing conditions are compared. No
acceptance protocol applies because this is the canonical reference
point.

### `repetition_fix` (hypothesis-only)

Truncates the pathological n-gram repetition loops that Whisper-family
models occasionally emit on long or degraded audio, delegating to the
existing `transcription.detect_and_fix_repetitions` function used by
the local desktop pipeline. The function is hypothesis-only because
reference transcripts never contain such loops by construction. On
the LibriSpeech `test-clean` benchmark against `whisper-medium`,
the May 2026 run cut insertions from 1,092 to 349 with no spurious
substitutions.

The thresholds, with the default `max_repetitions` of 5: a sentence
repeated more than five times in a row is kept once, followed by a
visible `[...]` when it ran to more than ten copies; a phrase of two to
six words is cut to one copy and `[...]` from its eleventh consecutive
occurrence, counted without regard to case; and a single word repeated
more than five times is kept twice. The phrase count was once computed
wrongly and case-sensitively, so every phrase loop of five copies or
more was cut and a loop whose first copy was capitalised was never cut
at all (audit finding T1-05). The WER matrix committed from the audit's
re-run of the sweep (code 6f9bf56, commit 2e36bf9) includes the repair.
Results from earlier runs, the August 2026 case study among them,
predate it.

### `whisper_norm` (symmetric)

Applies the published Whisper English text normaliser to both the
hypothesis and the reference: it expands contractions, normalises
numerals and currency, removes some hesitations and bracketed text,
collapses punctuation, lowercases, and maps British spellings to
American ones, so that `colour` and `color` score as the same word.
The normaliser is the `EnglishTextNormalizer` in transformers, built
with the spelling map it is meant to load, `normalizers/english.json`
from the `openai-whisper` package (20250625 in the job environment),
whose SHA-256 is pinned in `evaluation/conditions.py`. Without that
package the condition stops with an error.

Until September 2026 the condition built the normaliser with an empty
spelling map, which standardises nothing, under a description that
claimed British and American spellings were treated as equivalent.
Every `whisper_norm` result committed before the audit's re-run of the
sweep was scored that way, and was therefore stricter than the published
normaliser (audit finding EWER-05). The re-run's matrix (2e36bf9) and its
intervals (9cb43e3) use the published map. Against the post-fix matrix
before it, whose raw cells it reproduces, the map lowered the
condition's macro word error rate in all 15 suite-by-model cells, by
0.05 to 0.28 percentage points. The pre-repair matrix and intervals kept
as history do not use it.

The normaliser removes `um`, `uh`, `hmm`, `mm`, `mhm` and `mmm`, so a
reference made only of such a hesitation normalises to nothing, and
that utterance is skipped under this condition only (recorded as
`benchmark.n_skipped_empty_reference`). On AMI this condition therefore
scores fewer utterances than `raw`, and a gain computed from the two
corpus rates mixes its effect with the loss of those utterances;
`python -m evaluation.condition_ci --gains-output` computes the gain on
the utterances both scored (audit finding EWER-09). The condition
reproduces the normalisation used in the original Whisper evaluation
tables and is symmetric by design: applying it only to the hypothesis
would manufacture spurious insertions and substitutions through
asymmetric contraction expansion.

### `filler_strip` (hypothesis-only, added 2026-05)

Removes the unambiguous non-lexical disfluency vocabulary (`um`,
`uh`, `er`, `erm`, `ah`, `mm`, `mhm`, `hmm`, and their length
variants such as `umm`, `errr`, `hmmmm`) from the hypothesis only.
The regex anchors on word boundaries that exclude hyphens, so
compound backchannels such as `uh-huh` and `mm-hmm` are left
untouched. Lexical hedges (`like`, `you know`, `sort of`) are
deliberately outside the scope of this condition because removing
them would change the semantic content of the utterance and would
bias the comparison against models that correctly transcribe them.

The mechanism is purely textual: a single regex substitution followed
by whitespace collapse. The function is idempotent because a second
application has no fillers left to remove and the whitespace collapse
is a no-op on already-clean text. Acceptance check 1 (unit tests)
is satisfied by ten behavioural tests in `tests/test_conditions.py`
covering the identity, removal, length-variant, case-insensitivity,
backchannel-preservation, embedded-substring, lexical-hedge and
idempotency properties. Acceptance check 2 (registry integration)
is satisfied through registration in `evaluation/conditions.py` with
the four standard fields populated and `apply_to_reference=False`
explicitly justified in the notes. Acceptance checks 3 and 4 are now
satisfied by the pilot benchmark of 25 May 2026 (200 utterances,
LibriSpeech test-clean, whisper-large-v3, SLURM job 7721017 on Oxford
ARC htc/short, elapsed 12 min 41 s on an NVIDIA H100 PCIe). The
condition produced WER 0.0308, MER 0.0288, WIL 0.0462 and CER 0.0103
identical across all four metrics to the raw baseline, confirming
the predicted null effect on read-speech corpora where the reference is
prepared text and ASR hypotheses contain few if any filler tokens.
Acceptance check 3 is passed: the pilot WER does not exceed the raw
baseline. The condition is retained so that it can be applied
meaningfully when spontaneous-speech datasets enter the full sweep,
where a material WER reduction is anticipated.

### `dedup_window` (hypothesis-only, added 2026-05)

Collapses immediately-adjacent duplicate tokens in the hypothesis
under case-insensitive, punctuation-insensitive comparison. Targets
the short stutter-like repetitions (`the the cat` becomes `the cat`,
`they they they ran` becomes `they ran`) that survive
`repetition_fix`, which is tuned for longer n-gram repetition loops.

The window is deliberately fixed at one token. Wider windows of two
or three tokens, as originally floated in the revised plan, would
catch additional cases such as `I uh I went` collapsing to `I uh
went`, at the cost of flattening legitimate self-corrections. The
one-token window leaves a self-correction with a filler between the
repeats intact. It does not spare adjacent grammatical doubling:
`I said that that was wrong` becomes `I said that was wrong`, and
`had had enough` becomes `had enough`. An earlier version of this entry
claimed the reverse; the actual behaviour is pinned by
`test_dedup_window_collapses_adjacent_grammatical_reduplication`, and
these deletions are part of the condition's measured cost. A future
wider variant could be registered as a separate condition
(`dedup_window2` or similar) once the empirical evidence justifies
the trade-off.

Acceptance check 1 (unit tests) is satisfied by eleven behavioural
tests in `tests/test_conditions.py` covering the identity case,
simple stutter collapse, case-insensitivity, punctuation-insensitivity,
preservation of non-adjacent repetition, preservation of
self-corrections under the one-token window, collapse of runs of
three or more, robustness against pure-punctuation tokens, and
idempotency. Acceptance check 2 (registry integration) is satisfied
through registration with `apply_to_reference=False` and explicit
justification in the notes field. Acceptance checks 3 and 4 are now satisfied by the pilot benchmark of
25 May 2026 (same corpus and run as above). The condition produced
WER 0.0310, MER 0.0291, WIL 0.0465 and CER 0.0105, against a raw
baseline of WER 0.0308. The difference of +0.0002 WER represents a
marginal regression: inspection of the per-utterance report confirms
that at least one legitimate immediate repetition was collapsed,
producing a deletion error. Acceptance check 3 is therefore narrowly
failed on this read-speech slice. The condition is retained in the
registry because the expected benefit on spontaneous speech with
genuine stutter repetitions outweighs the observed risk on prepared
text; however, it should not be applied by default on corpora where
legitimate immediate repetition is grammatical. A planned follow-up
will evaluate the condition on the spontaneous-speech challenge suite
before it is considered for inclusion in the standard pipeline.

### `punct_strip` (symmetric, added 2026-05)

Removes sentence punctuation symmetrically from the hypothesis and
the reference, replacing each non-word, non-space, non-apostrophe
character with a space and collapsing the resulting whitespace.
Intra-word apostrophes are deliberately preserved so that contractions
such as `don't` and `isn't` survive as single tokens rather than
being split into spurious bigrams. The condition was meant as the
lighter counterpart to `whisper_norm`, isolating the contribution of
punctuation handling. It cannot do that under the scoring normaliser,
which strips the same character class from both sides of every
condition (see "What normalised WER can see" below). Against `raw` it
can differ only because it runs first, on a character that the
normaliser would have rewritten or removed before its own strip. It
turns a curly single quotation mark (U+2018 or U+2019, the second also
the typographic apostrophe) into a space, where the normaliser maps it
to an apostrophe and keeps it, so `don’t` becomes `don t` under it but
`don't` under `raw`. That section lists the other cases. Any difference
from `raw` measures that ordering, not the removal of sentence
punctuation.

The condition is symmetric by design. Reference transcripts vary
considerably in their punctuation conventions: some include
sentence-final periods and others do not, quotation marks are
applied inconsistently, and parenthetical asides may or may not be
typeset with brackets. Applying the strip to the hypothesis only
would therefore manufacture insertions or deletions on every
punctuation token, biasing the comparison without quantifying any
real model behaviour. The function is idempotent because a second
application has no punctuation left to remove and the whitespace
collapse is a no-op on already-clean text.

Acceptance check 1 (unit tests) is satisfied by eight behavioural
tests in `tests/test_conditions.py` covering the empty-string,
identity, removal-of-sentence-punctuation, apostrophe-preservation,
whitespace-collapse, digit-and-underscore-preservation and
idempotency properties, plus the `apply_to_reference=True` assertion.
Acceptance check 2 (registry integration) is satisfied through
registration in `evaluation/conditions.py` with all four standard
fields populated and the symmetry decision explicitly justified in
the notes. Acceptance checks 3 and 4 are now satisfied by the pilot benchmark of
25 May 2026. The condition produced WER 0.0308, MER 0.0288, WIL 0.0462
and CER 0.0103, identical across all four metrics to the raw baseline,
confirming the expected null effect on LibriSpeech test-clean, where
the reference transcripts contain minimal sentence punctuation and the
small amount present is already handled equivalently by the evaluation
pipeline's built-in normalisation before scoring. Acceptance check 3 is
passed. The larger anticipated effect on spontaneous-speech slices,
where reference punctuation conventions vary considerably, remains to be
quantified when those corpora enter the full sweep.

### `case_fold` (symmetric, added 2026-05)

Lowercases both the hypothesis and the reference using Python's
`str.lower`. The condition was meant to isolate the contribution of
case folding from the larger bundle of transformations performed by
`whisper_norm`. The scoring normaliser already lowercases both sides of
every condition, though, so `case_fold` scores exactly as `raw` by
construction and is registered as WER-invisible (see "What normalised
WER can see" below): it cannot isolate any contribution of case folding
to word error rate.

The choice of `str.lower` rather than `str.casefold` is deliberate.
The latter performs additional Unicode mappings such as German
eszett to `ss` and Greek final sigma to medial sigma, which overlap
with the territory of the Whisper canonical normaliser and would
muddy the contrast between this condition and `whisper_norm`. Using
the simpler `str.lower` keeps `case_fold` as a pure case-folding
operation. The function is trivially idempotent because a second
application has no uppercase characters left to fold.

Acceptance check 1 (unit tests) is satisfied by seven behavioural
tests in `tests/test_conditions.py` covering the empty-string,
ASCII-lowercasing, identity-on-lowercase, punctuation-and-digit
preservation, the `str.lower`-versus-`str.casefold` distinction
exercised through the German eszett, and the idempotency property,
plus the `apply_to_reference=True` assertion. Acceptance check 2
(registry integration) is satisfied through registration in
`evaluation/conditions.py` with all four standard fields populated.
Acceptance checks 3 and 4 are now satisfied by the pilot benchmark of
25 May 2026. The condition produced WER 0.0308, MER 0.0288, WIL 0.0462
and CER 0.0103, identical across all four metrics to the raw baseline,
because the evaluation pipeline's built-in normalisation already
performs lowercasing before scoring, leaving no residual
capitalisation-substitution errors for this condition to correct on the
LibriSpeech slice. Acceptance check 3 is passed. On corpora where the
upstream normaliser is bypassed or replaced, a non-negligible WER
reduction remains expected, as capitalisation differences between
hypothesis and reference would then be scored directly as substitution
errors.

## Conditions under consideration

The acceptance protocol has now been applied to all candidates
listed in the revised plan. No further conditions are queued for
registration. Any future addition (for example a `dedup_window2`
two-token window, or a separate `numerals_norm`) will be documented
here as it is proposed.

## 2026-05 expansion: production-pipeline parity

The conditions catalogued above quantify normalisation choices that
the desktop pipeline deliberately does not make, but they leave the
production pipeline itself outside the benchmark. The
`clean_transcription_text` function in `transcription.py`, which the
desktop application chains after the Whisper decoder, was originally
a single monolithic block that applied several substitutions in
sequence. The benchmark could measure the raw model output and the
diagnostic ablations, but it could not measure what an end-user
actually received, and a silent drift between the desktop pipeline
and the benchmark could not be ruled out.

The May 2026 refactor closes that gap. The monolithic block is
decomposed into eight atomic stages exposed at module scope: an
undefined-token tag (`_undefined_tag`), a filler bracketer
(`_filler_bracket`), a contraction repair (`_contraction_fix`), a
common-phrase normaliser (`_common_phrase_fix`), a whitespace
normaliser (`_whitespace_normalise`), a sentence capitaliser
(`_sentence_capitalise`), a pronoun capitaliser (`_pronoun_i_fix`)
and a punctuation-spacing tidier (`_punct_space_fix`). The
pronoun stage was separated from the sentence capitaliser in July
2026 so that it could be gated on language; see the section on the
language gate below. The composite function iterates a tuple
`CLEAN_TEXT_STAGES` that records the stages in production order, so
that the order is explicit, introspectable from outside the module,
and verifiable by test. Each atomic stage is registered as an
individually scorable condition with the same naming convention
(stripping the leading underscore), and the Unicode-and-emoji strip
that precedes them is registered as `unicode_strip`. A composite
`pipeline_full` condition is registered alongside, applying
`unicode_strip`, `repetition_fix` and the eight atomic stages in
production order to a single hypothesis.

The refactor also corrects a latent non-idempotence in the
filler-bracket regex. The original pattern matched any unambiguous
filler token and wrapped it in square brackets, but a second
application would re-match the same tokens inside their brackets and
produce `[[um]]`. The revised regex carries a negative lookbehind
for `[` and a negative lookahead for `]`, so that a second
application leaves already-bracketed fillers untouched. Idempotence
is now a required property of every registered condition, and a
single bulk test (`test_all_conditions_idempotent`) exercises it
across a fixture corpus for all conditions in the registry.

### `unicode_strip` (hypothesis-only, added 2026-05)

Delegates to `transcription.remove_emojis_and_unicode_artifacts`,
which removes emoji and characters in the symbol and control
categories, keeps the letters, combining marks and digits of every
script, punctuation such as `¿`, `«` and `…` and currency signs such as
`£` and `€`, and maps typographic quotation marks to their ASCII forms.
ASCII input comes back with its whitespace collapsed and otherwise
unchanged. Mirrors the first stage of the desktop pipeline.

The stage has been repaired twice. As first registered in May 2026 it
removed every non-ASCII character, deleting diacritics along with the
emoji; that was corrected in July 2026 (commit f6e708e), as described
under the language gate below. The version that followed still deleted
every CJK, kana and Hangul character through an over-wide emoji range,
dropped non-ASCII digits, vulgar fractions, currency signs and
punctuation, and removed typographic apostrophes (audit finding T1-02,
fixed in September 2026 by commit 748ae6b). The WER matrix committed
from the audit's re-run of the sweep and the fourth FLEURS arm, both at
code 6f9bf56, were scored after that second repair. Results from earlier
runs, the first three FLEURS arms among them, were scored before it.

On English read-speech benchmarks the effect is expected to be small
because Whisper-family models rarely emit emoji on clean audio; the
condition is registered for production parity and as insurance
against a model update that begins emitting Unicode artefacts. It is
not WER-invisible: a symbol deleted between two letters joins two
scored tokens, where the scoring normaliser would have put a space.

### `undefined_tag` (hypothesis-only, added 2026-05)

Replaces the whole words `undefined`, `undefine`, `undefin` and
`undefining`, in any case, with the marker `[undefined]`, wherever they
stand. These fragments occasionally surface when audio is cut off
mid-word. The four spellings are listed literally: the pattern
`\bundefin\w*` that the manuscript once gave would also have rewritten
ordinary words such as "undefinable". The earlier implementation
matched the four words only between two runs of whitespace, and so
missed one at the start or end of the text, one before punctuation and
the second of two in a row (audit finding T1-14). A bracketed token is
not matched again, so a second application is a no-op. The condition
is not WER-invisible: the brackets vanish under the scoring normaliser,
but the three variants are rewritten to `undefined`, which changes a
scored token.

### `filler_bracket` (hypothesis-only, added 2026-05)

Wraps unambiguous non-lexical fillers (`um`, `uh`, `er`, `ah`,
`hmm`, `mm`, `mhm`, `uhuh`, `uhhuh`) in square brackets, case
preserved. The hyphenated backchannels `uh-huh`, `mm-hmm`, `uh-uh` and
`mm-mm` are bracketed whole first, so `Mm-hmm` becomes `[Mm-hmm]`
where the stage once gave `[Mm]-[hmm]` (audit finding T1-18). A filler
inside a hyphenated compound such as `uh-oh`, or next to an apostrophe
as in `o'er`, is not a standalone filler and is left alone (EWER-03).
The negative lookbehind and lookahead described above make the
operation idempotent.

The scoring normaliser turns brackets into spaces, so a bracketed
filler scores exactly as the bare one, and the condition scores exactly
as `raw` by construction. It is registered as WER-invisible: its word
error rate cannot show any cost or benefit of the marking. Against a
reference that omits fillers, each filler is one insertion under this
condition and under `raw` alike; `filler_strip`, which deletes them, is
the condition whose difference from `raw` measures that cost. The
post-fix cells (ARC jobs 8688725, 8708134 and 8708135) predated the
apostrophe guard and differed from `raw` in 3 of the 15 suite-by-model
cells, all through words such as `o'er`, which the stage then bracketed
as `o'[er]`, two scored tokens. In the matrix from the audit's re-run of
the sweep (2e36bf9), which has the guard, the condition scores exactly
as `raw` in all 15.
The fillers this stage recognises differ from those of `filler_strip`
and the other inventories; see "Filler inventories" below.

### `contraction_fix` (hypothesis-only, added 2026-05)

Repairs the common contractions that Whisper emits without
apostrophes (`im` to `I'm`, `dont` to `Don't`, and similar) and the
space-split tokeniser artefacts (`isn t` to `isn't`). Each table
entry rewrites an unapostrophised source pattern to its
apostrophised form, which does not match the source pattern on a
second pass.

Amended September 2026. As registered in May, seven of the table's keys
were ordinary English words (`were`, `its`, `wont`, `cant`, `shed`,
`wed` and `id`), so the stage rewrote correct text: "they were happy"
became "they we're happy". On LibriSpeech test-clean it made 228
utterances worse and none better, entirely through 265 added
substitutions. The seven keys were removed in commit af3bee0 (27 August
2026), and `test_contraction_table_holds_no_ordinary_english_word` now
holds the table to the rule that no key may be a word that is already
correct English. The sweep was re-run on the repaired pipeline (see
below), and the stage no longer changes any hypothesis on LibriSpeech
test-clean.

### `common_phrase_fix` (hypothesis-only, added 2026-05)

Normalises capitalisation in a fixed set of lexical hedges (`i mean`
to `I mean` and similar). Most entries map a hedge back to its own
lower-case spelling, and because every row matches case-insensitively
they are not inert: a capitalised `Kind of` in mid-sentence becomes
`kind of` (a sentence start regains its capital at
`sentence_capitalise`). They are kept for production parity, so that
the benchmark sees the same sequence of substitutions as the desktop
pipeline. The stage changes case only, so it scores exactly as `raw` by
construction and is registered as WER-invisible.

### `whitespace_normalise` (hypothesis-only, added 2026-05)

Collapses internal runs of whitespace to single spaces, removes the
space before a comma or full stop, and puts one after a comma or full
stop that is directly followed by a letter. Trailing whitespace is not
stripped at this stage because punctuation tidying is handled by
`punct_space_fix` later in the pipeline. Spacing and punctuation vanish
under the scoring normaliser, so it scores exactly as `raw` by
construction and is registered as WER-invisible.

### `sentence_capitalise` (hypothesis-only, added 2026-05)

Capitalises the first letter of each sentence (the text after `.`, `!`
or `?`), a letter of any script, title-cased. It once matched ASCII
`a` to `z` only, so `élève` and `über` kept their lower case (audit
finding T1-16). A sentence that opens with anything other than a
letter, such as a bracketed filler (`[um] so`), a quotation mark or a
digit, is left as it is. Idempotent because an already-capitalised
sentence is left unchanged. Sentence-initial capitalisation is an
orthographic convention shared across the languages this workflow
handles, so the stage runs whatever the language. It changes case
only, so it is registered as WER-invisible.

### `pronoun_i_fix` (hypothesis-only, added 2026-07)

Capitalises the standalone English first-person pronoun `i`. Split
out of `sentence_capitalise` so that the language gate can skip it:
`i` is an ordinary word elsewhere, notably the Italian masculine
plural article, where `sono qui i libri` would otherwise become
`sono qui I libri`. The split is behaviour-preserving for English,
because a sentence-initial `i` is already upper-cased by the
preceding stage. Idempotent because `I` is already upper case. It
changes case only, so it is registered as WER-invisible.

### `punct_space_fix` (hypothesis-only, added 2026-05)

Normalises spacing around punctuation, quotation marks and
parentheses, removes duplicate punctuation and collapses adjacent
punctuation runs. The final stage of `clean_transcription_text`. It
puts one space after `.`, `,`, `!`, `?`, `;` and `:`, except for a `.`,
`,` or `:` between two digits, so decimals (`3.5`, French `3,5`),
thousands separators (`1,000`) and clock times (`10:30`) stay whole;
they used to be delivered as `3. 5`, `1, 000` and `10: 30` (audit
findings T1-04 and T2-01). An unspaced `...` is kept as an ellipsis. The
space before an opening double quote is kept, where the stage once
glued the quote to the previous word (`he said"Sarah"`), a form in
which the name masker could not see the name (T1-03). The full stops
inside a dotted abbreviation (`i.e.`, `e.g.`, `U.S.`, `p.m.`) and a
lower-case host name ending in a listed domain (`example.com`,
`ox.ac.uk`) are not spaced; the chain used to deliver `i.e. often` as
`I. E. Often` and `example.com` as `example. Com`. `whitespace_normalise`,
`sentence_capitalise` and `pronoun_i_fix` protect the same full stops,
and the final stop of `i.e.` and `e.g.` does not end a sentence (T2-01).
The stage touches only spacing and punctuation other than the apostrophe,
all of which the scoring normaliser removes, so it scores exactly as
`raw` by construction and is registered as WER-invisible.

### `pipeline_full` (hypothesis-only, added 2026-05)

The headline composite. Applies `unicode_strip`, `repetition_fix`,
`undefined_tag`, `filler_bracket`, `contraction_fix`,
`common_phrase_fix`, `whitespace_normalise`, `sentence_capitalise`,
`pronoun_i_fix` and `punct_space_fix` in that order, subject to the
language gate described below, by calling
`transcription.postprocess_transcript_text` with the repetition repair
on. It represents the text `transcription.py` delivers with
`--fix-spurious-repetitions`, before name masking. That flag is off by
default in `transcription.py` and the desktop application, so this is
the opt-in configuration (the one the project's case study used), not
what a default run delivers; a default run omits the repetition repair
(audit finding EWER-04). The decode also differs from a production run:
the benchmark decodes each utterance whole, with the language forced.
Its default GPU precision is the checkpoint's own (float16 for Large v3
and distil-large-v3, float32 for Whisper Medium); on a processor it uses
float32. `transcription.py` requests float16 on a GPU and float32 on a
processor, processes audio in chunks and forces a language only when one
is given. The recorded GPU precision therefore matches that request for
Large v3 and distil-large-v3; Whisper Medium ran in float32. Each benchmark
records its decoding environment. The composition order is fixed by the desktop pipeline and is
verified by `test_pipeline_full_is_ordered_composition`, which applies
the registered atomic conditions in declared order to a fixture corpus
and asserts equality with `pipeline_full`. A second test,
`test_pipeline_full_matches_production`, compares the composite with
`postprocess_transcript_text` run with the repetition repair on and
asserts byte-equality, and
`test_pipeline_full_is_not_the_default_configuration` shows that a
default run differs on a looping hypothesis. Together these tests close
the loop between the desktop pipeline and the benchmark and guarantee
that future edits to either side cannot diverge silently.

Acceptance check 1 (unit tests) for the nine new conditions is
satisfied by per-stage hand-crafted input/output assertions, by the
two composition tests just described, by the bulk
`test_all_conditions_idempotent` and
`test_all_conditions_empty_string_safe` checks that apply to every
condition in the registry, and by a
`test_registry_covers_production_stages` check that fails the suite
if any function in `CLEAN_TEXT_STAGES` is added or removed without a
matching registry update. Acceptance check 2 (registry integration)
is satisfied through registration in `evaluation/conditions.py` with
all four standard fields populated and the production-parity
intent justified in the notes field. Acceptance checks 3 and 4
(pilot benchmark and documentation) are satisfied by the full ARC
sweep submitted as job 7729882 on 26 May 2026, which completed on all
five suites. Its results are committed rather than appended here.
The results for the pipeline before the `contraction_fix` repair are
`output/evaluation/sweep_aggregate_prefix.csv`, the per-utterance
reports in `output/evaluation/sweep_reports/`, and the paired
intervals on LibriSpeech test-clean in
`output/evaluation/condition_ci.csv`. They measured the defect
described above: on LibriSpeech test-clean the stage cost +0.43
percentage points of macro WER, and `pipeline_full` +0.40. After the
repair the sweep was re-run (ARC job 8688725, 30 and 31 August 2026,
committed in 53378ba), and there `contraction_fix` cost +0.00 points and
`pipeline_full` +0.01. The audit's re-run of the sweep (ARC jobs 8917985
to 8917987, code 6f9bf56) has since replaced the post-fix files in
place: the aggregate `output/evaluation/sweep_aggregate.csv`, the
per-utterance Large v3 test-clean reports in
`output/evaluation/sweep_reports_postfix/` and the intervals in
`output/evaluation/condition_ci_postfix.csv`. In the new intervals both
stages differ from `raw` by 0.000 points.

## What normalised WER can see

Every condition is scored after `evaluation.wer.normalise_text`, which
lowercases both sides and replaces every character other than a letter,
digit, underscore, whitespace or apostrophe with a space. A condition
that changes only case, punctuation, spacing or square brackets
therefore scores exactly as `raw`, whatever it does to the transcript.
Seven conditions are of this kind by construction and are registered
with `wer_invisible=True`: `case_fold`, `common_phrase_fix`,
`sentence_capitalise`, `pronoun_i_fix`, `whitespace_normalise`,
`punct_space_fix` and `filler_bracket`. Their word error rate equals
the baseline's on every corpus, so a null difference for one of them is
guaranteed by the method and says nothing about whether the stage helps
or harms a reader. Each benchmark summary records the flag
(`benchmark.wer_invisible`) and the sweep aggregate carries it as a
column, so tables and figures can label these conditions as
unmeasurable under normalised WER (audit finding EWER-03).

Three conditions come close without qualifying. `punct_strip` runs
before the normaliser, so it can score differently from `raw` only on a
character that the normaliser would have rewritten or removed before
its own punctuation strip, because `punct_strip` has already made it a
space. The normaliser maps the curly single quotation marks (U+2018 and
U+2019, the second also the typographic apostrophe) to the apostrophe
it keeps, so `don’t` becomes `don t` under `punct_strip` but `don't`
under `raw`. NFKC folds some characters into ones the normaliser keeps
(`™` into `TM`) and joins a combining accent to its letter, and the
normaliser removes a speaker tag such as `SPEAKER-01` whole, where
`punct_strip` leaves `SPEAKER 01`. In the committed post-fix grid only
the curly marks move a cell: each FLEURS cell scores two errors fewer,
because one reference sentence, read twice, writes `Hira‘”`, which
`raw` scores as `hira'` against the `Hira` that all three models write.
`undefined_tag` rewrites `undefine`, `undefin` and `undefining` to
`undefined`, which changes a scored token. `unicode_strip` deletes a
symbol where the normaliser would put a space, so a symbol between two
letters joins two scored tokens into one. None of them is flagged. The
case conditions
are invisible for every letter whose capital lower-cases back to it,
which is all but a handful (`ß` title-cases to `Ss`); none of those
opens a sentence in the corpora scored.

## Filler inventories

Five lists of non-lexical fillers are in play. They differ, and they
are deliberately not unified: bringing `filler_strip` or the production
list into line with another would move committed word error rates,
which is a decision for the maintainer (audit findings EWER-15 and
XREF-08). All are matched case-insensitively.

| Inventory | Tokens | Used by |
| --- | --- | --- |
| `transcription.FILLER_TOKENS`, with `BACKCHANNEL_TOKENS` | um uh er ah hmm mm mhm uhuh uhhuh; and uh-huh mm-hmm uh-uh mm-mm, bracketed whole | `filler_bracket`, `pipeline_full` |
| `conditions._FILLER_RE` | um uh uhm umm erm er ah mm mhm hmm hm, each also lengthened (ummm, uhhh) | `filler_strip` |
| `disfluency._FILLER_STEM` | the union of the two rows above, with lengthened spellings, hyphenated and unhyphenated backchannels (mm-hmm, mmhmm, uh-huh), and `huh` only as the second element of a compound | filler retention and reference recall (`evaluation.disfluency`) |
| `wer._FILLER_WORDS` | uh um erm ah eh mm hmm | `python -m evaluation.wer --remove-fillers` |
| Whisper `EnglishTextNormalizer` | hmm mm mhm mmm uh um (its `ignore_patterns`) | `whisper_norm`, both sides |

Why each differs:

- The production list is narrow on purpose: every entry is a hesitation
  with no lexical reading in English, so bracketing one can never
  swallow a real word (`oh` and `well` are excluded for that reason). It
  matches exact tokens, so lengthened spellings such as `ummm` are not
  bracketed, and a filler inside a hyphenated compound or next to an
  apostrophe is not a standalone filler.
- `filler_strip` removes the lengthened spellings and `erm`, `uhm` and
  `hm`, which the production list lacks, and leaves `uhuh`, `uhhuh` and
  every hyphenated compound alone. Why its coverage was chosen to differ
  from the production list is not recorded. The consequence is that
  `filler_strip` and `filler_bracket` act on different vocabularies, in
  both directions, so they are not exact counterparts.
- The disfluency detector must see everything either condition might
  remove. A narrower detector would shrink its own denominator, and a
  condition that deleted every `erm` would score as having preserved the
  fillers, so broader is the safe direction.
- `wer._FILLER_WORDS` serves only the `--remove-fillers` flag of the
  standalone scorer, and no committed result uses it.
- The Whisper list is part of the published normaliser and is not ours
  to change. It is why `whisper_norm` empties filler-only references
  (such AMI utterances are then skipped, see
  `benchmark.n_skipped_empty_reference`) while keeping `er`, `ah` and
  `erm`.

## How testing proceeds across the post-processing steps

The test suite that guards the post-processing pipeline operates at
five layers, each addressing a different class of failure.

The first layer is the *per-stage behavioural layer*. For every
registered condition, `tests/test_conditions.py` carries hand-crafted
input/output assertions that exercise the identity case, the
intended transformation, the boundary conditions called out as
deliberately out of scope, and any case-sensitivity or whitespace
edge cases that the design notes flag as decisive. These tests
serve as the executable specification of each stage; a failure here
identifies the stage and the property that has regressed.

The second layer is the *bulk invariants layer*. Two tests apply to
every condition in the registry without exception. The first,
`test_all_conditions_idempotent`, asserts that `f(f(x)) == f(x)`
over a fixture corpus that includes the empty string, simple read
text, text with disfluencies, text with capitalisation artefacts,
text with mid-word breaks, text already in canonical form, and text
with punctuation oddities. The second,
`test_all_conditions_empty_string_safe`, asserts that every
condition returns a string given the empty string as input. These
two tests scale automatically with the registry: a new condition is
covered the moment it is registered, with no test maintenance.

The third layer is the *registry coverage layer*. The
`test_registry_covers_production_stages` test introspects
`transcription.CLEAN_TEXT_STAGES` and asserts that every function in
the tuple has a registered condition with the matching slug, plus
that `unicode_strip`, `repetition_fix` and `pipeline_full` are also
present. Adding a new atomic stage to the desktop pipeline without a
matching registry entry fails this test, which is the principal
mechanism by which the benchmark is kept in sync with the production
pipeline.

The fourth layer is the *composition equality layer*. Two tests
verify that the composite `pipeline_full` behaves as advertised.
`test_pipeline_full_is_ordered_composition` chains the atomic
conditions in the declared production order and asserts byte
equality with `pipeline_full` over the fixture corpus.
`test_pipeline_full_matches_production` calls
`remove_emojis_and_unicode_artifacts`, `detect_and_fix_repetitions`
and `clean_transcription_text` by hand and asserts byte equality
with `pipeline_full` over the same corpus. If the desktop pipeline
changes its stage order, or if a stage's behaviour drifts between
the module and its registered wrapper, both tests fail.

The fifth layer is the *symmetric-application layer*. For each
condition with `apply_to_reference=True` (currently `punct_strip`,
`case_fold` and `whisper_norm`), `tests/test_benchmark_wer_conditions.py`
verifies that the reference path actually invokes the transform when
the condition is selected. The condition's `apply_to_reference` flag
is the single source of truth for that decision, and the test
ensures it is honoured by the WER benchmark driver rather than being
ignored or overridden in some code path.

The local suite is the union of these five layers and is invoked
from the project root with `python -m pytest -q`. Tests are skipped
on machines that lack the optional heavy dependencies (`datasets`,
`transformers`, `torch`), so the number that runs depends on the
machine. Any change to the post-processing pipeline must leave every
previously passing test passing before it can be merged or submitted
to ARC.

## The language gate

The clean-text stages were written for English and, until July 2026,
were applied to every transcript. Measured on the FLEURS test splits
with Whisper Large v3, that inflated the composite's word error rate
on every non-English language tested, by a factor of 1.08 on Dutch
up to 8.10 on Polish, while the raw model output was uniformly
strong. Two independent causes were found and fixed.

The first was the Unicode strip, which removed every non-ASCII
codepoint and so deleted diacritics rather than transliterating
them: `n'était` became `n'tait`, `Gerät` became `Gert`. The damage
tracked the proportion of words carrying a diacritic, which is why
Dutch was almost unaffected and Polish worst hit. The July repair
(f6e708e) kept accented letters, but it still deleted other non-ASCII
characters, the vulgar fractions of one FLEURS sentence (`29¾`) among
them. Since the September repair (748ae6b, audit finding T1-02) the
stage removes only emoji and the Unicode categories that hold symbol and
control artefacts (other and modifier symbols, and control, format,
surrogate, private-use and unassigned codepoints). It keeps the
letters, marks, digits, punctuation, currency signs and mathematical
symbols of every script, and returns ASCII input with its whitespace
collapsed and otherwise unchanged, as described under `unicode_strip`
above.

The second was that the lexical stages assume English vocabulary.
`contraction_fix` rewrites the German preposition `im`, meaning
"in the", to the English contraction `I'm`. `clean_transcription_text`
therefore takes a language, and skips `undefined_tag`,
`filler_bracket`, `contraction_fix`, `common_phrase_fix` and
`pronoun_i_fix` when the transcript is not English. The remaining
stages, which concern whitespace, sentence capitalisation and
punctuation spacing, are orthographically general and always run.
The language defaults to English, so English output is byte-for-byte
what it was and every English benchmark figure stands.

With both fixed, the composite is word-error-neutral (a ratio of
1.00 against raw) on all six languages tested. The comparison is in
`output/evaluation/fleurs_multilingual_summary.json`, over four arms:
before the repairs, after the July Unicode repair, with the language
gate as well, and the re-run at the audited code (6f9bf56, ARC job
8917984). In the fourth the composite scores every utterance of all six
languages exactly as raw, where the third left Spanish at a ratio of
0.9989 because the July strip still deleted the vulgar fractions.

The benchmark passes its `--language` through to any condition whose
`language_aware` flag is set, which at present is `pipeline_full`
alone. In the desktop pipeline the language is whatever `--language`
supplies, falling back to the language Whisper reports having
detected. Detection goes through `WhisperGenerationMixin.detect_language`
rather than the ASR pipeline's `return_language`, because between
transformers 4.48 and 5.6 the generation path strips the language
token before the tokenizer can report it and that field is always
`None`; this is why `requirements.txt` floors transformers at 4.45.
Users are warned in the terminal whenever the language was guessed
rather than stated, and should pass `--language` explicitly: a wrong
guess applies the wrong post-processing rules.
