# Transcripts from release 1.0.0

The four transcripts in this directory, and their masking logs in
`../name_masking_logs/`, were written by release 1.0.0 of the workflow on
10 November 2025, as the `Processed:` and `Transcription system version:`
lines at the top of each file record. They are kept as a record of what
that release produced. They are not a demonstration of what the current
code produces, and three defects found and fixed since are visible in
them (listed below).

For output of the current code, see `../variants/`, which
`tools/generate_example_variants.py` regenerates by running the pipeline
itself (see `tools/README.md`).

## Where they came from

The header of each transcript gives the settings: Whisper Large v3, audio
enhancement, English, repetition repair and name masking with the curated
dictionary, without timestamps or speaker attribution. By title, the four
recordings are episodes one to four of *Codex Mentis*, the author's own
podcast of synthetic two-voice dialogues made with NotebookLM
(`data/codex_mentis/manifest.json`). Episode three was transcribed from a
file named "L3 learning and morphosyntactic transfer".

The WAV files that were transcribed are not in the repository, and
release 1.0.0 wrote no run manifest (the manifest arrived in ddb498f), so
nothing records their digests or how they were converted from the
published `.m4a` episodes. The episodes themselves can be fetched, with
their digests checked, by `python -m evaluation.fetch_codex_mentis`.
Replacing these files means transcribing the four episodes again with the
current code on a GPU, which has not been done. Until it is, the files
stay as they are, unedited, because `output/evaluation/artefact_audit.*`
and the manuscript's masking section describe what the audit found in
them.

## Known defects

Each was found after release and is fixed in the current code.

1. **Correct words rewritten as contractions.** The contraction repair
   had seven ordinary English words among its keys, so it rewrote correct
   text: "were" became "we're", "its" became "it's", and likewise for
   "wont", "cant", "shed", "wed" and "id". Neither "were" nor "its"
   survives anywhere in the four transcripts. Line 14 of three of them
   reads "People we're significantly faster" (`architecture_of_meaning`),
   "There we're several significant drawbacks" (`behind_the_curtains`) and
   "They we're dropping subjects" (`l3_learning`). The defect was found in
   the word error rate sweep, where the stage only ever substituted words
   and never improved a single utterance, and was fixed in af3bee0.

2. **Numbers split by the punctuation spacing.** The stage that puts a
   space after punctuation also did so between digits, so "3,000" became
   "3, 000" and "0.05" became "0. 05". This affects
   `architecture_of_meaning` (for example "over 3, 000 participants") and
   `behind_the_curtains` ("usually 0. 05"). The "10, 11, 12, 13" in
   `modular_mini_grammar` is a genuine list. The codebase audit found it
   (findings T1-04 and T2-01), and 5080964 fixed it.

3. **A possessive surname left unmasked.** In `behind_the_curtains`, the
   surname is masked where it stands alone but survives twice as
   "Bernabeu's thesis", in both `transcript.txt` and `transcript.docx`,
   because the possessive ending defeated the dictionary lookup. The
   artefact audit (`python -m evaluation.audit_artefacts --dir
   example_output`) found it, and `output/evaluation/artefact_audit.csv`
   still reports those two files as masked artefacts that leak a name.
   Stripping the possessive before the lookup, in 7db44bd, closed the gap.
   The surname is the author's own, so no participant's privacy is
   involved.

The masking logs store the original names next to their placeholders.
That is their purpose, and the audit does not count it as a leak.
