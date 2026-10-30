# The Spanish V100 control

This file was the plan for the control that audit finding NEW-05 asked
for, prepared on 6 October 2026. The control ran on 19 October 2026, and
the file now records what ran and what it found. The comparison itself is
`output/evaluation/fleurs_es419_v100_control.json`, written by
`python -m evaluation.fleurs_control`, and the jobs' settings are in
`hpc/runs/fleurs_es419_v100.env`.

## The question

The fourth arm of `output/evaluation/fleurs_multilingual_summary.json`
(ARC job 8917984, code 6f9bf56) decoded every language on L40S, H100 or
A100 cards, none of which the first three arms used, and its raw scores
differ from the third arm's on one to four utterances per language. The
summary puts this down to the card, the only known difference, while
saying that no pair of arms on one model of card isolates it. The control
decodes one split again at the fourth arm's code on the card family the
third arm used for it, keeping the model, dataset, language, seed and
software stack fixed. If the card explains the drift, the control's
per-utterance records match the third arm's exactly. It does not rerun
the six-language experiment or replace its committed results.

## What ran

The jobs ran with these settings:

| Setting | Value |
| --- | --- |
| Source commit | `6f9bf56a0d5839920537f23d73a166dc0f1e478b`, clean tracked tree, clone `~/paper_speech_transcription_ctl_es419` |
| Script | `hpc/submit_benchmark_wer_multilingual.sh`, array index `2` |
| Dataset | `google/fleurs`, revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`, `es_419`, full `test` split |
| Model | `openai/whisper-large-v3`, revision `06f233fe06e710322aca913c1bc4249a0d71fce1`, float16 |
| Decoder and scorer | Language `spanish`, task `transcribe`, native timestamps, seed `42`, condition `raw` |
| Allocation | Cluster `htc`, partition `short`, account `<project-b>`, QoS `standard`, four CPUs, 32 GB, one `gpu:v100` |
| Site modules | `Anaconda3/2025.06-1`, `CUDA/13.0.2`, driver 580.65.06 |
| Run stack | Python 3.12.12, torch 2.5.1+cu121, transformers 4.57.1, datasets 4.8.5, jiwer 4.0.0, cuDNN 9.1 |
| Pre-flight | Job 9124739 (`pf_es419_v100`), five utterances, htc-g003, Tesla V100-PCIE-32GB, 9 min 52 s |
| Full split | Job 9124863 (`ctl_es419_v100`), 908 utterances, htc-g004, Tesla V100-PCIE-32GB, 52 min 26 s |

Both jobs were submitted on 17 October and ran on 19 October 2026. Two
things departed from the commands this file prepared. The full split was
released from its dependency on the pre-flight before the pre-flight ran,
so the two ran side by side, and it was given a two-hour limit instead of
twelve. The pre-flight's five records match the full split's first five.
The board is a V100 PCIe card, where the third
arm's Spanish task ran on a V100 SXM2 module, because `gpu:v100` does not
choose the board.

Both environment records name commit 6f9bf56 with no modified tracked
file and list the same 179 packages, version for version, as the fourth
arm's Spanish task (8917984_2, on an L40S in htc-g081). The summary's
`decode` and `run_metadata` blocks differ from that task's in the card
alone. The outputs are on ARC under
`$DATA/speech_transcription_env/output/evaluation/controls/es_419_v100_6f9bf56`
and `..._preflight`, with the job logs in the clone's `logs/`.

## What it found

The control's records are identical to the third arm's on all 908
utterances, in every field a summary keeps (word, match and character
error rates and the alignment counts), and so is its summary block: raw
macro WER 0.02937565607283082. They are identical to the first arm's as
well, decoded on a V100 SXM2 module at 9ae40a2. Against the fourth arm's
L40S decode, the control differs on four utterances: 1735, 2004, 1966 and
1785, three in word errors and one in character error rate alone. These
are the four on which the third arm differs from the fourth. Against the
second arm's P100 decode it differs on four as well.

Under the rule above, the card accounts for the fourth arm's Spanish
drift. The control shares the fourth arm's code, packages, model and
dataset commits and precision, and differs from it in the card and the
node that holds it. It shares the third arm's card family but not its
code, so the code that separates the third and fourth arms does not move
the raw decode of Spanish. The control cannot tell the card from its node
or the node's host processor, which computes the log-mel features, and it
covers Spanish alone. The summaries keep no transcripts, so the agreement
is of alignment counts and error rates, which the same words would give
but do not prove.

The two original summaries it was compared with were recovered from ARC
and checked against the digests the multilingual summary records:

| Comparison input | SHA-256 recorded in `fleurs_multilingual_summary.json` |
| --- | --- |
| Arm 3 `wer_summary_fleurs_es_419.json` | `7311b602f06666adf2b4ee0a9538f4727700becc601e8773f34541202f5c519b` |
| Arm 4 `wer_summary_fleurs_es_419_whisper-large-v3.json` | `3c21bba3b288e3b97105fefaada3f1c236bac10268f7c62c5b449f4f9bcd765e` |

The comparison record lists every input by file name and digest, the
arms' summaries of Spanish from the first and second arms included. The
canonical multilingual summary is unchanged, and its control paragraph
still describes its four arms alone.
