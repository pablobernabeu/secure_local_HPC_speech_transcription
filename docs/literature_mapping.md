# Literature mapping for the Background section

This document records how each of the eleven PDFs reviewed for the
Background section of `manuscript/manuscript.qmd` was used. The PDFs
were kept in a local working folder, `docs/temp/`, which is excluded
from the repository; each source is identified here by its DOI instead.
The document dates from the May 2026 revision. Three of the sources it
maps were later removed from `manuscript/references.bib` and are no
longer cited, as noted where they appear (September 2026). For every source we identify the thread
of the literature review it supports, the BibLaTeX key under which it
appears in `manuscript/references.bib`, and the specific claim it
substantiates. The four threads are the distributional view of large
sequence models, the catalogue of automatic speech recognition (ASR)
failure modes, the feasibility of local and edge deployment, and the
necessity of human-in-the-loop review.

Russell, Gessinger, Krason, Vigliocco and Harte (2024), here
`russellWhatAutomaticSpeech2024` (https://doi.org/10.1016/j.rmal.2024.100163), anchors the human-in-the-loop
thread. Their comparison of six commercial and open-source ASR
systems on conversational data concludes that present-day ASR cannot
yet replace the trained transcriber, but that a high-quality
machine-generated draft is a defensible starting point for manual
refinement. We cite this work as the empirical basis for our claim
that an automated transcript must be presented as provisional rather
than authoritative.

Wang, Alhmoud, Alsahly, Alqurishi and Ravanelli (2025), here
`wangCalmWhisperReduceWhisper2025` (https://doi.org/10.21437/Interspeech.2025-201), contributes to the ASR
failure-modes thread. The Calm-Whisper analysis shows that a small
number of decoder attention heads account for the majority of
Whisper's hallucinations on non-speech segments. We use this finding
to justify our defensive layer for silence and non-speech intervals.

Wagner, Thallinger and Zusag (2024), here
`zusagCrisperWhisperAccurateTimestamps2024` (https://doi.org/10.21437/Interspeech.2024-731), also supports the
failure-modes thread. CrisperWhisper documents Whisper's tendency to
suppress disfluencies, filler words and verbatim detail, and shows
that tokeniser adjustments materially improve word-level timestamp
precision. We cite this work to motivate our preservation of
disfluencies and the timestamp accuracy required for downstream
diarisation alignment.

Chung, Hong, Lee and Kim (2026), here
`chungDiagnosisawareMultitaskFinetuning2026` (https://doi.org/10.1016/j.specom.2026.103393), extends the
failure-modes thread to disordered speech. Their disease-specific
fine-tuning of Whisper on Korean dysarthric speech shows that
character error rates drop substantially when the model is adapted to
speaker characteristics absent from its training distribution. We
cite this paper to acknowledge that the failure modes we describe are
not uniformly distributed across speakers and that out-of-distribution
populations are disproportionately affected.

Cao (2025), here `caoPerformanceEvaluationWhisperSeries2025` (https://doi.org/10.1145/3769102.3774244), is the
principal source for the local-and-edge thread. The evaluation of
Whisper variants on four Raspberry Pi platforms establishes that the
`tiny.en` and `base.en` Faster-Whisper models run with acceptable
latency on commodity single-board computers, and that the Raspberry Pi
5 with four gigabytes of memory offers the best
cost-to-performance ratio among the platforms tested. We cite this
work to support our claim that institutional-scale infrastructure is
not strictly required for many transcription workloads.

Prasad, Rao, Geetha and Naidu (2026), here
`prasadASRTransformerBasedModel2026` (https://doi.org/10.37965/jait.2026.0935), also contributes to the
local-and-edge thread by demonstrating that fine-tuned Whisper-small
is viable for real-time, edge-deployable Kannada ASR. We cite this
work as evidence that the deployment envelope for Whisper-class
models extends beyond English and beyond GPU-equipped workstations. This source was dropped from the bibliography (commit 1bc814f, 27 August 2026) and is no longer cited in the manuscript.

Tolle and colleagues (2024), here `tolleVoiceInkVink2024` (https://doi.org/10.1186/s13104-024-06749-0), bridges
the local-and-edge thread and the human-in-the-loop thread. Vink
packages Whisper as a standalone qualitative-research transcription
tool, explicitly motivated by the data-protection concerns that
preclude cloud services in many research settings, and is evaluated
through pilot-tester usability assessment in fourteen languages. We
cite this work as the closest published analogue to our own
architectural choices.

Landesvatter, Behnert and Bauer (2025), here
`landesvatterComparingSpeechtoTextAlgorithms2025` (https://doi.org/10.1093/poq/nfaf056), contributes to the
failure-modes thread by benchmarking Whisper, wav2vec 2.0, NVIDIA
NeMo and Google Cloud Speech-to-Text on open-ended survey audio. The
finding that Google Cloud is outperformed by almost all open-source
alternatives is cited as a counter-argument to the assumption that
cloud services are necessarily more accurate than self-hosted models.

Ma, Zhang, Chen, Jia, Wang and Yan (2026), here
`maDUAPDisentanglementBasedUniversal2026` (https://doi.org/10.1109/TIFS.2026.3671687), sharpens the privacy
motivation that underpins the entire workflow. DUAP demonstrates that
adversarial perturbations can degrade Whisper's multilingual
transcription accuracy by upwards of 85 per cent, illustrating both
the privacy concerns raised by accurate multilingual ASR and the
fragility of cloud-mediated transcription against deliberate
interference. We cite this work as evidence that the surface area of
a cloud-coupled transcription pipeline is larger than the audio
itself. This source was dropped from the bibliography (commit 3b51b91, 27 August 2026) and is no longer cited in the manuscript.

Alumäe (2025), here `alumaeStrivingOpensourceEquitable2025` (https://doi.org/10.1038/d41586-024-04095-6), is the
Nature commentary on Meta's SEAMLESS speech-to-speech translation
system. We cite this piece in the distributional-foundation thread
both for its lucid summary of how foundation models for speech are
trained on weakly supervised internet-mined data and for its
discussion of why the data and code being publicly available matters
more than any particular benchmark number. The commentary is also a
counterpoint to closed cloud services on the equity dimension.

The eleventh PDF, on the Mindshare AI-powered video processing
platform, was reviewed but not cited. The system uploads recorded
video to Amazon S3 for transcription by Whisper and metadata
generation by GPT models, which is precisely the cloud-coupled
architecture our workflow is designed to avoid. Citing it would
require a contrastive comparison whose space we have allocated
instead to the Alumäe commentary on SEAMLESS, which makes the same
point with a less product-specific framing.

The distributional-foundation thread is led by Bernabeu's earlier
theoretical work (`bernabeuLanguageSensorimotorSimulation2022b` (https://doi.org/10.17635/LANCASTER/THESIS/1795)) and
by the original Whisper paper, the latter cited under the alias
`@radford2022whisper` already present in the Introduction. Bernabeu's thesis was dropped from the bibliography (commit 1bc814f, 27 August 2026) and is no longer cited; the Whisper paper still is.
