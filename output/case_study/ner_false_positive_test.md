# What the NER masking stage costs on real prose

The injection benchmark reports precision 1.000 for every masker
configuration, and that number is an upper bound by construction: its
carrier sentences are built to contain no token that could be mistaken for
a name. It can therefore measure recall honestly and cannot measure
false positives at all.

This is the complementary measurement. Both maskers were run over the
transcript of the August case-study run, ARC job 8441879, which holds
5,384 tokens of natural speech about transcription research (*Codex
Mentis* episode 5, the same recording as the worked example), and the
redactions compared.

## Result

| Configuration | Redactions | Of which genuine names |
|---|---|---|
| Dictionary only | 3 | 2 |
| \+ NER, no capitalisation gate | 18 | 2 |
| \+ NER, capitalisation gate (shipped default) | 3 | 2 |

The counts are of names. Since 17 October 2026 the masker also replaces
the "Dr." before the closing credits' name with `[TITLE]` (audit finding
NEW-09), a fourth placeholder that no configuration's name count includes.

The dictionary's three redactions are all capitalised words in its name
list. Two are genuine names, the first name and surname of the workflow's
author in the closing credits. The third is "Jordan", in a speaker's
example of a false positive: masking "Jordan" when the talk is of the
country, not a person. The dictionary lists Jordan as a first name and
does not read context, so it masks the word there and makes the very
error the speaker describes. The genuine-name column was corrected from 3
to 2 in each row on 2026-10-04, by a hand count that read each redaction
in its context and not by a new measurement, because this note had first
counted Jordan as a personal name.

Both NER configurations keep the dictionary's three redactions, Jordan
among them, since the stage only ever adds to them. Ungated, it added
fifteen and **every one was a false positive**:

    researchers, researcher, we, name, two, speaker, one, user

## Why

A model asked to find people returns person *references*, not personal
*names*. On a recording that discusses speakers, researchers and users,
phrases such as "tagging the transcript with speaker one" are genuine
references to people, and the model is not wrong to mark them; they simply
contain no personal information. The distinction matters here and is
invisible to the injection benchmark.

Label engineering does not fix it. Asked alone, in place of the shipped
label set, each of `person name`, `personal name` and `name of a person`
still marks *speaker one* and *speaker two* over the transcript's 363
sentences, as the shipped set does, and finds the genuine names as well.
Each narrower phrasing also marks capitalised words that are not people
and that the gate would let through: "Jordan", "HPC", "SLURM" and
"Whisper", and `person name` a sentence-initial "Researchers" as well.
The shipped set marks no capitalised word but the author's name. The
confusion is in the task, not in the wording of the prompt, and under the
gate the narrower phrasings cost more than the shipped set, not less.
`ner_label_phrasings.json` records this run of 17 October 2026, made by
`tools/ner_label_phrasings.py` in the environment of the committed NER
arms. An earlier, uncommitted run of 4 October also had each narrower
phrasing mark "Pinanote", which this one does not.

## The gate

Every false positive the NER stage added is lower-case, and every genuine
name is capitalised. The NER stage is therefore held to the same
capitalisation gate the dictionary already applies, and `case_insensitive`
relaxes both together rather than either alone. Under the gate the stage
adds no redaction to this transcript at all, which is what makes it safe
to enable by default for those who install it. The one false redaction
left, Jordan, is the dictionary's own, and no capitalisation gate could
remove it, because the word is capitalised.

The cost is stated rather than hidden: lower-case names stay outside the
stage's reach, exactly as they are outside the dictionary's. Relaxing the
gate for both stages (`--ner --case-insensitive`) recovers them, lifting
overall recall on injected names from 0.474 to 0.937 and lower-case recall
from zero to 0.926, at a cost of at least the ungated arm's false
positives. That arm relaxed the gate for the NER stage alone, and relaxing
the dictionary's gate as well can only add redactions.

## The three measured configurations

| Configuration | Overall recall | Out-of-dictionary | Lower-case | Leakage |
|---|---|---|---|---|
| Dictionary only | 0.351 | 0.000 | 0.000 | 0.649 |
| \+ NER, gated (default) | 0.474 | 0.412 | 0.000 | 0.526 |
| \+ NER, gate relaxed | 0.937 | 0.788 | 0.926 | 0.063 |

Precision is 1.000 in all three, which is precisely the upper bound this
document exists to qualify. The figures are those of the committed
summaries (`output/evaluation/masking_summary*.json`), regenerated at seed
42 in a08265c; the two NER rows gave 0.456 and 0.907 overall before then.

## Reproducing

The NER stage now loads its model from the local cache only, at a pinned
revision, and never downloads it at run time, so the two `--ner` runs
fail until the model has been fetched once with the first command below.

```bash
python -m ner_masking --download                  # once; needs gliner installed
python -m evaluation.benchmark_masking            # dictionary only
python -m evaluation.benchmark_masking --ner      # gated NER arm
python -m evaluation.benchmark_masking --ner --case-insensitive
```

Without `--output-dir DIR`, each benchmark run writes into
`output/evaluation/`, where it replaces the committed masking results.

The transcript text used here is `ep05_raw_text.txt` in this directory,
the text of the August case-study run, ARC job 8441879, extracted from
its timestamped JSON before masking. Job 9124852, the October re-run
whose figures the README in this directory reports, wrote a text of 5,382
whitespace-separated tokens to this one's 5,384. It differs from this
text in nine places: no full stops after "span" and "hours" ("span 60
minutes", "two hours easily"), "you know," added after "factors that",
"you can't see the exact model versions" shortened to "you can model
versions", "explain" for "explained", "Optimize" for "Optimized", the
second "intact" of "intact intact" dropped, and hyphens in
"pre-processing" and "re-engineering",
and the measurement was not repeated on it. Job 8983112, which it
replaced, differed from this text in ten places.
