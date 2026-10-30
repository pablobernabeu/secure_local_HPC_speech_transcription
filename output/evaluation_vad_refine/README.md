# Timestamp benchmark with VAD end refinement

The timestamp benchmark run with its benchmark-only `--vad-refine` option,
which moves each segment end to the later of Whisper's own end and the end
of the last stretch of speech Silero VAD finds in the clip. The pipeline
does not ship that option and the manuscript does not report the run. The
reported timestamp results are the plain run in `output/evaluation/`.

ARC job 8917981 (2026-09-27, code 6f9bf56 with a clean tree, an NVIDIA
H100 80GB HBM3 on htc-g059) wrote these files, with Silero VAD loaded from
the tag `snakers4/silero-vad:v6.2.1`. The invocation is
`hpc/runs/timestamps_vad.env`. The summary records the sample, the decode,
the pinned model and dataset revisions, the VAD source and the commit.

It replaces the first committed run, ARC job 7746221 (2026-05-31, code
bb32915, committed in 4bbed5f), which loaded Silero from the untagged
repository and ran on a Tesla P100-PCIE-16GB on htc-g033, as its log and
the node's configuration show. The new run reproduces that one in every
row and in every column it wrote, so pinning the tag changed nothing here.
This file used to give job 7746221 an H100. Job 7746138, an attempt half
an hour earlier, ran on an H100 PCIe on htc-g055, on code from before
bb32915 whose VAD could only pull an end in. Its log gives a mean absolute
end error of about 240 ms, and job 7746221 replaced it and wrote over its
files.

Read against the plain run (`output/evaluation/`, ARC job 8917980, the
same commit, node and card type, the same 500 utterances), the VAD moved
52 of the 499 ends later and none earlier, heard no speech in 162 clips
and left those ends alone, and changed no start and no word: every
hypothesis is identical. Mean absolute end error falls from 127 to 64 ms
and the 90th percentile from 150 to 90 ms, while the median stays at
10 ms. Ends more than half a second early fall from 41 to 21, which the
summary gives as a `truncation_rate` of 4.2 per cent against the plain
run's 8.2; the key's name is historical, and it counts ends more than
half a second early. The VAD changes no word, so the fall is in where
segments end, not in what they hold. Nor were most of the plain run's
early ends missing words: the condition sweep's decoding of the same 41
clips by the same model lost no reference word in 32 of them
(`output/evaluation/sweep_reports_postfix_ami/`, under Whisper's
normaliser). On a clip whose end the VAD extended, the timestamp now
reaches the end of the speech the detector found.

The utterance in `timestamp_skipped.csv` is the plain run's: a 3.17 s
clip whose reference transcript is the single word "yeah", which Whisper
wrote as "ha" 222 times without a closing timestamp.

The files keep a directory of their own because they have the plain
run's file names and the manuscript reads `output/evaluation/`.
`tests/test_benchmark_results.py` pins them in the `TestVadRefine*`
classes.
