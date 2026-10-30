# Reference and claim review

Reviewed on 6 October 2026 against the 34 entries in
`manuscript/references.bib` and their uses in `manuscript/manuscript.qmd`.
Every work was identified from a primary publication, official legislative
record, software release or evaluation plan. All 27 supplied DOIs resolve to
the cited works: 26 through Crossref and one through DataCite. The seven
entries without a DOI have appropriate primary locators; fuzzy registry
matches were rejected.

The review checked ordered authors, title, publication year, venue,
volume/issue, pages or article number, DOI and software/report version where
those fields apply and the primary record exposes them. A verified identity
does not establish every empirical detail in a paper. The table therefore
records separately the source used to check the manuscript's claim. An
abstract can support the bounded finding it states, without giving access to
all methods or results. This pass did not independently reproduce external
studies or verify the author's ethical-approval declaration.

Three entries were added after this review and are not part of it. The
first, `openaiWhisperLargev3ModelCard2023` (17 October 2026), cites the
model card at the commit the evaluation pinned. The other two are the
release's own records: `bernabeuSecureScalableSpeech2026` cites release
2.0.0 of the software, archived at
<https://doi.org/10.5281/zenodo.23442766>, and
`bernabeuRecoveredInputsEnglish2026` cites the recovered inputs of the
English sweep, deposited at <https://doi.org/10.5281/zenodo.23442874>.

## Evidence for all 34 entries

“Verified” below refers to the fields listed above, subject to the specific
qualification in that row. Publisher-supplied registry records were compared
with publisher pages or the cited primary artifact. Conference dates and
online publication dates were distinguished from the year of the cited
proceedings or journal issue.

| BibTeX key | Primary source | Field status | Claim evidence and scope |
| --- | --- | --- | --- |
| `alumaeStrivingOpensourceEquitable2025` | [Publisher PDF](https://media.nature.com/original/magazine-assets/d41586-024-04095-6/d41586-024-04095-6.pdf), [record](https://doi.org/10.1038/d41586-024-04095-6) | Verified; 2025 print issue, 637(8046), 551–553. | Full commentary discusses unequal language coverage and dialect accuracy. It is a forum contribution, not a new comparative benchmark. The print title is shorter than the digital title retained in the bibliography. |
| `atwanyLostTranscriptionFound2025` | [ACL Anthology](https://aclanthology.org/2025.findings-acl.1190/) | Verified; five ordered authors, 2025, 23181–23203. | Paper supports distribution-shift effects on hallucination and the limits of WER as a measure of fabricated content. |
| `bernabeuSecureScalableSpeech2025` | [Zenodo release](https://zenodo.org/records/17624830) | Verified; Pablo Bernabeu, 16 November 2025, v1.0.0. | Official artifact verifies the historical software release. This DOI does not identify the later evaluation or a newly deposited manuscript/data bundle. |
| `bredinPyannoteAudio2025` | [Release 3.4.0](https://github.com/pyannote/pyannote-audio/releases/tag/3.4.0), [tagged package metadata](https://github.com/pyannote/pyannote-audio/blob/3.4.0/setup.py) | Verified; Hervé Bredin, release published 9 September 2025. URL and version pinned to 3.4.0. | Official software identity/version verified. Algorithmic claims are attributed to Plaquet and Bredin separately. |
| `californiaConsumerPrivacyAct2018` | [CPPA statute PDF](https://www.cppa.ca.gov/regulations/pdf/cppa_act.pdf), [California Attorney General](https://www.oag.ca.gov/privacy/ccpa?version=published) | Verified name, 2018 Act and current section range. Canonical legislative HTML was inaccessible. | Official sources establish coverage of defined businesses; the manuscript no longer implies a general obligation for all research institutions. |
| `caoPerformanceEvaluationWhisperSeries2025` | [Proceedings record](https://doi.org/10.1145/3769102.3774244), [author's conference slides](https://botyue.github.io/docs_25/paper_slides/SEC25_RaspPi_slides.pdf), [official programme](https://acm-ieee-sec.org/2025/program.php) | Verified; Yue Cao, SEC 2025, 1–7. | Author slides show Pi 4 (4 GB) and Pi 5 (4/8/16 GB), latency comparisons and suitability of tiny.en/base.en Faster-Whisper models. Published full text was inaccessible; the claim was checked against the author's presentation. |
| `carlettaAMIMeeting2005` | [Springer chapter](https://link.springer.com/chapter/10.1007/11677482_3) | Verified; 17 ordered authors, editors Renals/Bengio, LNCS 3869, 28–39. The cited edition is 2006. | Corpus description supports multimodal meeting recordings and annotations. It does not establish a blanket consent statement for every downstream use. |
| `chungDiagnosisawareMultitaskFinetuning2026` | [Publisher abstract](https://www.sciencedirect.com/science/article/abs/pii/S0167639326000415) | Verified; four authors, Speech Communication 180, 103393, 2026. | Abstract supports diagnosis-aware fine-tuning of Korean dysarthric speech and an improvement up to 18.34 percentage points in CER. This is task-specific. |
| `conneauFleursFewshotLearning2023` | [Published record](https://doi.org/10.1109/SLT54892.2023.10023141), [author paper](https://arxiv.org/abs/2205.12446), [official dataset](https://huggingface.co/datasets/google/fleurs) | Verified; nine authors, 798–805. Proceedings titled SLT 2022 were published in 2023. | Paper and official dataset support the parallel multilingual read-speech corpus. Dataset availability/licensing does not alone establish participant consent for every use. |
| `dataProtectionAct2018` | [Official current text](https://www.legislation.gov.uk/ukpga/2018/12/2026-02-05/data.html) | Verified; Data Protection Act 2018, c. 12. Canonical contents URL was intermittently inaccessible. | Part 2 supplements the UK GDPR. The manuscript now distinguishes the Act from the retained GDPR regime. |
| `efstathiadisLLMbasedSpeakerDiarization2025` | [Published record](https://doi.org/10.1016/j.specom.2025.103224), [author version v3](https://arxiv.org/html/2406.04927v3) | Verified; three authors, Speech Communication 170, 103224. Published venue takes precedence over the preprint's stale journal header. | Author version Appendix B/Table 6 supports a 6% relative deltaCP reduction and 4% deltaSA reduction on unseen Google ASR, versus larger matched-recogniser improvements. |
| `generalDataProtectionRegulation2016` | [EUR-Lex official text](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng) | Verified; Regulation (EU) 2016/679, OJ L 119, 4 May 2016, 1–88. | Articles 5(2) and 24 place accountability on the controller. Holding a recording alone does not determine that role. |
| `koeneckeCarelessWhisperSpeechtoText2024` | [Published record](https://doi.org/10.1145/3630106.3658996), [author paper](https://arxiv.org/abs/2402.08021) | Verified; five authors, FAccT 2024, 1672–1681. | Full author paper supports roughly 1% hallucinated transcriptions, 38% harmful content among hallucinations, non-vocal-duration association and the reported aphasia-group comparison. Findings concern the tested API/sample. |
| `landesvatterComparingSpeechtoTextAlgorithms2025` | [Publisher abstract](https://academic.oup.com/poq/article-abstract/89/4/1154/8418151) | Verified; three authors, 89(4), 1154–1166. Retain 2025 issue year despite online publication in January 2026. | Abstract supports the comparison of 100 open-ended survey responses and Google's advantage in that study. It does not establish a universal cloud-service ranking. |
| `lannelongueGreenAlgorithmsQuantifying2021` | [Full publisher article](https://advanced.onlinelibrary.wiley.com/doi/10.1002/advs.202100707) | Verified; three authors, Advanced Science 8(12), 2100707, 2021. | Equation 1 supports runtime, power, usage, memory and PUE-based estimation. Defaulting usage to one is documented, but Discussion warns TDP can underestimate consumption; these estimates are not metered upper bounds. |
| `leiGeralProtecaoDados2018` | [Official Brazilian legislation](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm) | Verified; Lei 13.709, 14 August 2018. | Article 4 II(b) exempts exclusively academic processing from the full law while retaining Articles 7 and 11. The manuscript states this narrower scope. |
| `liOurCollectiveVoices2025` | [Published record](https://doi.org/10.1145/3715275.3732179), [later author version](https://www.shaomei.info/pdfs/FAccT25_Our_collective_voices_preprint.pdf), [older author manuscript](https://www.shaomei.info/pdfs/FAccT25_StammerTalk_Dataset_manuscript.pdf) | Verified; five authors, FAccT 2025, 2768–2783. | Both author versions support 72 speakers and increasing deletions with stuttering severity. Exact severe-conversation CER/deletion rates differ between versions; those rates were removed from the manuscript pending a published-version check. |
| `mcgonigleBenchmarkingAutomaticSpeech2024` | [Published record](https://doi.org/10.1109/EMBC53108.2024.10782773), [indexed primary abstract](https://pubmed.ncbi.nlm.nih.gov/40039537/) | Verified; four authors, EMBC 2024, 1–5. | Abstract verifies 34 child samples and 14% versus 50% of words captured. These are recovery proportions, not WER values. |
| `miaoVoicePrivacyChallengeEvaluation2026` | [Official evaluation plan](https://www.voiceprivacychallenge.org/vp2026/docs/VPC_2026_sept01.pdf) | Verified; ten ordered authors, 2026, version 2.0. | Full plan supports evaluation with an attacker adapted to anonymised speech, speaker-verification EER and linguistic/emotional utility. The manuscript's fixed top-1 linkage check is explicitly narrower. |
| `naffahSpokenLanguageAnalysis2025` | [Publisher abstract](https://karger.com/ger/article-abstract/71/5/417/923693/Spoken-Language-Analysis-in-Aging-Research-The), [PubMed record](https://pubmed.ncbi.nlm.nih.gov/40552848/) | Verified except end-page: publisher says 417–423; Crossref/PubMed say 417–424. Current 417–424 retained pending published PDF. | Primary abstract supports 238 older adults, two speech tasks, average LIWC convergence r = .98 and the filler/netspeak exception. Full methods were inaccessible. |
| `panayotovLibrispeechASRCorpus2015` | [Published record](https://doi.org/10.1109/ICASSP.2015.7178964), [official corpus](https://www.openslr.org/12/) | Verified; four authors, ICASSP 2015, 5206–5210. | Original paper/corpus documentation supports public-domain audiobook-derived speech and clean/other partitions. The distributed corpus is separately licensed CC BY 4.0. |
| `patinoSpeakerAnonymisationUsing2021` | [ISCA paper and record](https://www.isca-archive.org/interspeech_2021/patino21_interspeech.html) | Verified; five authors, 2021, 1099–1103. | Full paper supports McAdams-based LPC-pole manipulation and evaluation of privacy/ASR trade-offs. It does not warrant a general guarantee of anonymity. |
| `plaquetPowersetMulticlassCross2023` | [ISCA paper and record](https://www.isca-archive.org/interspeech_2023/plaquet23_interspeech.html) | Verified; Plaquet/Bredin, 2023, 3222–3226. | Full paper supports powerset classes with at most two simultaneous speakers in a local model. Pipeline-specific settings require the actual model/pipeline documentation. |
| `radford2022whisper` | [PMLR record and published PDF](https://proceedings.mlr.press/v202/radford23a.html) | Verified; six authors, published 2023, PMLR 202, 28492–28518. PDF preserves McLeavey spelling. | Published paper supports large-scale weak supervision, conditional encoder–decoder recognition and its normalization/evaluation methods. It is not a theorem that all ASR models must hallucinate. |
| `russellWhatAutomaticSpeech2024` | [Publisher article](https://www.sciencedirect.com/science/article/pii/S2772766124000697) | Verified; five authors, 3(3), 100163, 2024. | Abstract supports the six-system conversational comparison and use as a draft for human correction rather than a replacement for trained transcription. |
| `sloaneCaseStakeholderdrivenAI2026` | [Publisher correspondence](https://www.nature.com/articles/s42256-026-01207-x) | Verified; five authors, 8(4), 493–494, 2026. | Correspondence supports matching the definition of transcription accuracy to stakeholder needs, including disfluencies. It is an argument about auditing, not a new WER experiment. |
| `tolleVoiceInkVink2024` | [Corrected publisher article](https://link.springer.com/article/10.1186/s13104-024-06749-0), [correction notice](https://link.springer.com/article/10.1186/s13104-024-06842-4) | Verified; seven authors, BMC Research Notes 17, article 95, 29 March 2024. Correction reviewed separately. | Corrected article supports Vink's offline workflow and 14-language pilot. The correction removes inadvertently published proof comments; it reports no revised empirical finding used here. |
| `trabelsiNoiseReductionImproving2024` | [SCITEPRESS record/full paper](https://www.scitepress.org/PublishedPapers/2024/124571/) | Verified; four authors, ICAART 2024 volume 3, 1221–1228. | Full paper supports the small/base versus larger-model denoising distinction in its 74-message sample. This does not establish a benefit for every recording or recogniser. |
| `wangCalmWhisperReduceWhisper2025` | [Published ISCA PDF](https://www.isca-archive.org/interspeech_2025/wang25b_interspeech.pdf) | Verified; five authors, 2025, 3414–3418. | Full paper supports three of twenty decoder attention heads, substantial non-speech hallucination reduction and small measured ASR-cost changes in that experiment. |
| `wangVoxpopuliLargescaleMultilingual2021` | [ACL Anthology](https://aclanthology.org/2021.acl-long.80/), [official corpus repository](https://github.com/facebookresearch/voxpopuli) | Verified; nine authors, 2021, 993–1003. | Original paper/repository support parliamentary speech and accented-English configuration. They do not establish blanket consent for all research uses. |
| `zaratianaGLiNERGeneralistModel2024` | [ACL Anthology](https://aclanthology.org/2024.naacl-long.300/) | Verified; four authors, 2024, 5364–5376. | Paper supports compact generalist zero-shot named-entity recognition with bidirectional transformers. Actual CPU behavior remains an implementation/environment property. |
| `zhangEfficientDeploymentLarge2025` | [IEEE published record/abstract](https://ieeexplore.ieee.org/document/11434664/) | Verified; three authors, ASRU 2025, 1–4; IEEE accession in 2026 does not change conference year. | Abstract supports over 50% throughput improvement in the reported optimized deployment. It does not measure this project's energy savings. |
| `zhaoQuantificationAutomaticSpeech2025` | [Publisher record/abstract](https://onlinelibrary.wiley.com/doi/10.1002/lary.31713), [indexed primary record](https://pubmed.ncbi.nlm.nih.gov/39157956/) | Verified; four authors, 135(1), 191–197. Retain January 2025 issue year; first online August 2024. Protect Deaf capitalization. | Abstract supports the 850-sample comparison, 52.6% versus 5.0% mean WER and intelligibility/onset/communication-mode strata. These are the tested groups, not a universal performance floor. |
| `zusagCrisperWhisperAccurateTimestamps2024` | [Published ISCA PDF](https://www.isca-archive.org/interspeech_2024/zusag24_interspeech.pdf), [landing record](https://www.isca-archive.org/interspeech_2024/zusag24_interspeech.html) | Corrected author order to Wagner, Thallinger, Zusag from PDF; 2024, 1265–1269 verified. | Full paper supports tokenizer/timestamp changes and verbatim fine-tuning. General decoder-repetition claims now cite the official Whisper model card instead. |

## Corrections and source disagreements

The CrisperWhisper published PDF lists **Laurin Wagner, Bernhard Thallinger,
Mario Zusag**, whereas the landing page and Crossref put Zusag first and
Crossref misspells Thallinger's given name. The bibliography now follows the
published PDF and retains its citation key. The pyannote software entry now
identifies release **3.4.0**, rather than a changing repository home page.
The Zhao title preserves **d/Deaf** through the curated `Deaf` protect-list
entry, which produces `d/{Deaf}` in BibTeX and survives normalization.

Naffah's end-page is unresolved. The publisher landing page and issue table
of contents give 417–423, while the registered metadata and PubMed record
give 417–424. Access to the published PDF failed. The bibliography retains
417–424; this is a recorded field discrepancy, not a verified correction.

Li's older, 21-page author manuscript reports severe conversational CER
31.27% and deletion 24.23%; the later, 16-page author version reports 34.91%
and 25.76%. Both identify the same DOI and agree on the qualitative
severity/deletion pattern. The former rates were removed from the manuscript
rather than attributed to an inaccessible version of record. The published
PDF was not available in this review.

Several apparent year disagreements reflect publication versions. Carletta
cites a 2006 proceedings edition for a 2005 meeting; Radford cites the 2023
PMLR paper, not the 2022 preprint; FLEURS cites the 2023 proceedings bearing
the SLT 2022 title. Zhao retains its 2025 issue year rather than its 2024
online date. Landesvatter retains its 2025 issue year despite January 2026
online publication. These years were verified and left unchanged.

The Vink correction, published 18 July 2024 as BMC Research Notes 17:198
([DOI 10.1186/s13104-024-06842-4](https://doi.org/10.1186/s13104-024-06842-4)),
removed author proof comments from the introduction and table headers. The
live original article is corrected. No numerical finding cited by this
manuscript was changed in the notice; a separate correction citation is not
needed for the present claims.

The coordinated manuscript pass narrowed the legal accountability claims,
removed an unsupported blanket consent statement, replaced the unsupported
repetition-loop attribution with the
[official Whisper model card](https://huggingface.co/openai/whisper-large-v3#performance-and-limitations),
and removed Li's version-dependent percentages. The footprint wording also
distinguishes full-utilisation assumptions from a metered upper bound.

## Registry audit and its limits

The required citation-shape audit found a bibliography-driven manuscript
with no hand-typed parenthetical citations. The bundled metadata audit
resolved every entry, but its seven first-hit DOI recoveries were unrelated
works and were rejected:

| Entry without DOI | Rejected fuzzy match | Reason |
| --- | --- | --- |
| `bredinPyannoteAudio2025` | `10.21437/Interspeech.2023-205` | Plaquet/Bredin algorithm paper, not this software release. |
| `californiaConsumerPrivacyAct2018` | `10.2139/ssrn.3275571` | Commentary, not the statute. |
| `dataProtectionAct2018` | `10.2139/ssrn.3244203` | Commentary concerning India's legislation, not the UK Act. |
| `generalDataProtectionRegulation2016` | `10.5040/9781509920594.0009` | Book chapter, not the Regulation. |
| `leiGeralProtecaoDados2018` | `10.11606/t.2.2025.tde-03072025-122110` | Thesis, not the Brazilian law. |
| `miaoVoicePrivacyChallengeEvaluation2026` | `10.2139/ssrn.6066413` | Earlier VoicePrivacy challenge paper, not the 2026 plan. |
| `radford2022whisper` | `10.21437/Interspeech.2015-533` | Unrelated 2015 speech paper, not Whisper. |

The bundled parser omits BibLaTeX `date` and `journaltitle` during comparison,
checks surname presence rather than complete author order, and compares only
the first container title. Its Carletta venue flag confused the LNCS series
with the proceedings title. Manual primary-record checks were therefore
necessary; script success alone did not close the audit.

No retraction was flagged in the returned registry records. This is not an
exhaustive claim that every publisher correction or notice has been indexed:
the Vink correction was found on the publisher's site despite no corresponding
`update-to` relation in the returned original record. Publisher records and
the correction notice take precedence over that absence.

Raw API responses, script output and inspected source copies are local review
materials under ignored `build/reference_audit/`, not deposited research data
or additions to the public source archive. The completed primary registry
record file had SHA-256
`4137ca716dfad9403a4caf3718c6e4cfaed48ac4788b77d8bcfa451c91d83c79`.
The primary links above provide the public evidence. Remaining access limits
are the Naffah end-page and the unavailable published full text of Cao and Li;
their cited qualitative findings have independent primary-author support.
