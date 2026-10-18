# Superseded: clustering threshold 0.60 on the concatenation protocol

History, not a current result. ARC job 7746222 (P100, code bb32915,
committed in 4bbed5f) scored diarisation at a clustering threshold of 0.60
on the old AMI reconstruction, which concatenated 25 single-speaker clips
per meeting and so contained no overlapping speech (973 s of reference in
all). fde27c5 replaced that protocol with a faithful meeting timeline. The
figures here are therefore not comparable with `output/evaluation/der_*`,
and the manuscript does not report them. They stay because
`tests/test_benchmark_results.py` pins them. See
`output/evaluation/README.md` for what is current.

The job ran on 2026-05-31 on a Tesla P100-PCIE-16GB on htc-g034, as its
log and `sacct`'s node list show. This file used to give it an H100. The
default-threshold speaker confusion and missed speech that the tests
compare with this run's are those committed in 815b5a7 on 2026-05-30,
which job 7742188 wrote. Job 7746139 ran the default threshold again on
2026-05-31, on an H100 PCIe on htc-g055, and printed the same per-meeting
figures to the four decimals its log shows, but its summary was never
committed.
