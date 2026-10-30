# Release and submission readiness

*Note of 30 October 2026.* This record of the review of 6 to 18 October
2026 is kept as it was written, and its opening sections describe the
state before the release. Release 2.0.0 was tagged at `658009e` on
18 October. The software is archived at
<https://doi.org/10.5281/zenodo.23442766>, and the English sweep's
inputs, with the decoder source, are deposited at
<https://doi.org/10.5281/zenodo.23442874>. The licences were settled on
17 October (see [Rights](#rights-and-retained-personal-information)),
and the manuscript's availability statements cite both records. The
Spanish V100 control, still a proposal below, ran on 19 October
([next_control.md](next_control.md)).
`ISSUES.md` and `CHANGELOG.md` give the current state of each open item.

This record separates the review checkout from a published release. As of
6 October 2026, the code and citation metadata still identify release 1.0.0.
That archive predates the evaluation reported in the manuscript. Version
2.0.0 is the proposed next release because command-line options have been
removed and repaired text-processing stages change the output. Neither a
new release date nor a new DOI has been assigned.

## Verification before freezing the release

The CPU regeneration gate rebuilds eleven committed artefacts. The pinned
Linux workflow and its local equivalent are described in [ci.md](ci.md).
This gate checks statistical derivations and the dictionary benchmark.
Recognition, diarisation and neural name masking require their recorded
models and environment. The installed-distribution tests also verify the
default dictionary masker and release record outside the source checkout.

The full sweep inputs have been recovered from ARC without running new
decoding jobs: 255 summary JSON files and 15 hypothesis CSV files. Every
file matches the remote SHA-256 manifest. Strict aggregation reproduces
the committed 255-row CSV byte for byte and all scientific JSON fields.
Only aggregation time, the input directory and current run metadata differ.
The recovery and verification manifests are currently under
`build/recovered_arc_sweep/`, which is ignored. Local recovery establishes
that the aggregate can be rebuilt, but it does not make those inputs publicly
available.

The derived public checksum receipt,
`output/evaluation/sweep_input_manifest.json`, retains all 270 filenames,
byte counts and exact input digests, along with the source decoder commit,
jobs and corpus notices. It omits private deployment locators and records
the original receipt digests and that derivation. It accompanies the new
exploratory apostrophe-scoring report. The corresponding corpus text inputs
still await a reviewed deposit.

The study archive must therefore include the recovered input bundle or
link to a separate versioned deposit containing it. A separate data record
is preferable: these files contain corpus reference text, transformed
references and generated hypotheses, with different rights and review
needs from the software. The 270 inputs occupy 1,021,407,391 bytes
uncompressed, and the recovered `tar.gz` is 62,595,723 bytes. It must retain the
summary and hypothesis filenames, remote checksums, model and dataset
revisions, aggregation recipe and the recorded decoder commit `6f9bf56`.
Its public README should map the five suite configurations to their source
corpora, explain the 17 conditions and three models, and link to the exact
software version used for regeneration. Review every proposed file and its
metadata before depositing it. The local recovery receipt names a private
ARC account/path. A public inventory can describe that provenance without
repeating the account identifier, while preserving the input hashes and
recording how the public receipt was derived.
The recovered TAR also carries ARC ownership metadata. A separate
metadata-normalised local candidate is prepared under
`build/release_review/data_candidates/`. All 270 input files retain their
exact bytes and digests. It uses neutral ownership, regular-file permissions
and fixed timestamps, with no private gzip filename or PAX metadata.
Its SHA-256 is `e91170f76b82623795333b93612f96b6d197a40d3ed91b44354135fc9f64715a`
and its compressed size is 62,605,837 bytes. The original recovery archive
is preserved. The deposit uses the ZIP described below instead of this
candidate, and the bounded content inventory is recorded in
[privacy_review.md](privacy_review.md).
The decoder commit must also remain recoverable from a persistent source
deposit, for example a labelled source snapshot of `6f9bf56` in the data
record. A commit identifier alone does not put that historical code into
the new release's `git archive`, which contains only its selected tree.
That snapshot predates the test-cache isolation repair recorded under
NEW-INC-01. Label it as the historical decoder source and direct users to
the current isolated verification suite. Its old tests must not be run
against shared model caches. Preserve the source snapshot's original bytes
and place this context in the surrounding archive README.
The checked-in source archive also needs the dictionary, `versions.csv`,
environment locks, normaliser, manuscript source, bibliography, CSL file,
run records and committed statistical inputs. A wheel alone is not the
study archive. The raw scheduler export includes unrelated projects and
must remain outside the public bundle. Its query and digest are already
recorded in the committed ledger provenance.

## Rights and retained personal information

The author settled the licence scope on 17 October 2026. The software,
with the name dictionary it installs, is MIT ([LICENSE](../LICENSE)), and
`manuscript/`, `docs/`, `output/` and `example_output/` are CC BY 4.0
([LICENSE-docs.md](../LICENSE-docs.md), formerly `Licence.md`). Third-party
materials retain their own terms. The author compiled the dictionary, and
its inventory and history are in
[dictionary_provenance.md](dictionary_provenance.md). The Zenodo version
lists both licences, where the 1.0.0 record gave CC BY 4.0 alone;
`CITATION.cff` can name only the software's.

The recovered CSV files contain original and transformed corpus references
as well as generated hypotheses. LibriSpeech,
FLEURS and AMI data are released under CC BY 4.0; VoxPopuli data use CC0.
VoxPopuli's repository code and pretrained models have different terms,
CC BY-NC 4.0. The bundle must identify each corpus and split, cite its
original authors, retain the relevant notices and describe the hypotheses
as generated derivatives. These distinctions were checked against the
[LibriSpeech release](https://www.openslr.org/12),
[FLEURS dataset card](https://huggingface.co/datasets/google/fleurs),
[AMI licence](https://groups.inf.ed.ac.uk/ami/corpus/license.shtml) and
[VoxPopuli licence statement](https://github.com/facebookresearch/voxpopuli#license)
on 6 October 2026. No blanket relicensing of these inputs is implied.
The CC BY material requires retained attribution and disclosure of changes;
its source licence does not establish that the text is free of personal
information. See the [CC BY 4.0 legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en),
sections 2(b) and 3(a). Separate notices are also needed for other bundled
third-party materials: the bundled [APA CSL file](../manuscript/apa.csl)
declares CC BY-SA 3.0, rather than the project's proposed licences.

The repository's retained example names, Word metadata and historical
files are described in [privacy_review.md](privacy_review.md). A source
archive made with `git archive` excludes `.git` and deleted historical
files, but preserves the selected commit's current examples. Any change
to those examples requires a documented disposition and a fresh archive
inventory. The retired infographic under [historical/](historical/README.md)
is a labelled historical artefact; its compliance and performance claims
are not current findings.

An exact inventory of the current example source blobs at `309f1d0` is
held in ignored `build/privacy_audit/current_example_inventory.json`, with
each path, byte count and SHA-256. It contains 46 files and 816,477 bytes:

| Material | Files | Retention condition |
| --- | --- | --- |
| Release 1.0.0 transcript DOCX/TXT pairs | 8 | Keep their historical settings and defect note; author accepts the retained surname and Word editor identifier |
| Original-name example masking logs | 3 | Author accepts disclosure of their 11 rows and context sentences |
| Example README and two `.gitkeep` files | 3 | Retain the provenance and limits of the historical examples |
| Generated example variants | 25 | Keep the four variant manifests and their associated outputs together |
| Public podcast case study | 7 | Keep its README, raw-text/NER note, review, run manifest and evaluation pair together, with their distinct producing runs documented |

The named materials have public podcast or synthetic-example provenance
documented in the repository. The review found no confirmed credential
among the scanner findings, but this is not unrestricted privacy clearance.
The example originals and document metadata require the decisions listed
in G6; public availability alone does not settle their disposition in a new
archive. No raw audio is included in this example inventory. After the
author's decisions and the new documentation are committed, regenerate the
inventory against the frozen release tree. The current count is a review
snapshot, not a claim about an archive that has already been built.
An example-only ZIP was built locally with
`git -c core.autocrlf=false -c core.eol=lf archive` and all 46 ZIP members
matched the inventoried source blobs byte for byte. Both settings matter
on this Windows checkout: ordinary `git archive` converted 14 unprotected
text files to CRLF. The local candidate is
`build/privacy_audit/current_examples_review_exact.zip` (350,485 bytes;
SHA-256 `e100cc9c43b47b403dbc03e9dffc3c0d1669043c17768669293dd40bf6391dd4`).
It has not been uploaded and does not imply publication clearance.

## DOI, metadata and exact archive order

After the content and licence are settled, create an unpublished new
version draft in the existing software record family, whose concept DOI is
recorded as `10.5281/zenodo.17592924`, and reserve its version DOI. Confirm
that family in the owner's deposit account before proceeding. If the
recovered inputs have a separate data record, reserve its DOI as well and
cross-link the two records. Zenodo permits DOI reservation before uploading files, so
the DOI can be included in those files before publication. This order
avoids tagging one tree and then changing its DOI metadata. The procedure
follows Zenodo's [versioning guidance](https://help.zenodo.org/docs/deposit/manage-versions/)
and [DOI reservation guidance](https://help.zenodo.org/docs/deposit/describe-records/reserve-doi/),
checked on 6 October 2026.

Update `versions.csv`, `setup.py`, `CITATION.cff`, the software reference,
README links and changelog together. Replace the manuscript's two PHASE2
notes and its statement that the cited archive predates the evaluation
only when the reserved record will contain the evaluated materials.
Reservation does not make a draft publicly available; the final
availability statement must be checked against the published records.
The historic citation is version DOI `10.5281/zenodo.17624830`; it must
not be relabelled as the new release. If `.zenodo.json` is introduced,
check its complete metadata against `CITATION.cff`, because Zenodo's
GitHub integration gives that JSON priority.

Run the appropriate tests, regeneration gate and both manuscript renders,
then freeze the final source commit and tag that exact tree. Build the
source ZIP from the frozen commit, and prepare the reviewed data bundle
and rendered manuscript as separately inventoried study outputs. Record the commit, tree,
input digests, checks and archive SHA-256 in a detached manifest. Keeping
that manifest outside the hashed ZIP avoids a self-referential digest.
Use `git -c core.autocrlf=false -c core.eol=lf archive` for the source ZIP,
then compare its member paths and bytes with the frozen tree; do not infer
their digests from the working checkout's line endings.
For Zenodo's manual software deposit to be forwarded to Software Heritage,
the record must contain only one compressed source file and use resource
type Software. A second compressed data bundle in that record would fail
that archival route; keep it in the linked data record.
See its [manual software upload guidance](https://help.zenodo.org/docs/github/archive-software/manual-upload/).
After publication, download the deposited archive and verify its digest
against the reviewed local file before declaring the archive complete.

On 17 October 2026 the new version draft was created in that family and
its DOI, `10.5281/zenodo.23442766`, reserved; the inputs' data record has
DOI `10.5281/zenodo.23442874`. The software draft lists MIT and CC BY 4.0
and links the `v2.0.0` tag and the data record, and it takes one file, the
`git archive` ZIP of the tagged tree. The data draft takes two files:
`sweep_inputs_2026-10.zip`, built by `tools/build_input_deposit.py`
(62,808,787 bytes, SHA-256
`6474ba29de744cf989328427313d377b631891892dbafd5a07f472adbe86fa51`), and
`decoder_source_6f9bf56.zip`, the `git archive` of the decoder commit
(8,589,655 bytes, SHA-256
`b66a511905b7e648987ef2f577105cd5b95e7d6556aa4ce398dda605875c5ccb`), which
meets the source-deposit requirement above. The public repository is the
one that has held the software since 1.0.0,
<https://github.com/pablobernabeu/secure_local_HPC_speech_transcription>.
It receives the release as one snapshot commit, without this repository's
history, and the tag `v2.0.0` without a GitHub release, since its Zenodo
webhook would publish a release as a further version. The author
publishes both records.

The release tree was checked on 18 October 2026, after the case study's
re-run (ARC job 9124852) was committed. ARC job 9134598 ran the whole
test suite at `c17367b`, that commit: 2,367 passed, 1 skipped and 1
expected failure. CI run 39168435971 passed the CPU selection and the
eleven-artefact gate at the merge that brought `92e1da2`, and the HTML and
the 102-page PDF rendered from it with 37 references and no unresolved
cross-reference or citation. `92e1da2` changed one line of a note that
no test reads.

## Journal submission facts

The current target is Behavior Research Methods. Its checked requirements
and the limits of the format review are recorded in
[journal_profile.json](../manuscript/journal_profile.json).
The author supplied the funding statement (no specific grant) and the
corresponding postal address on 17 October 2026 and gives no telephone
number. Optional ORCID information can be added when supplied. The
availability statements cite the release the manuscript is rendered from
and the input deposit, whose records are described above and, for 2.1.1,
in the last section.

The remaining empirical issues are recorded individually in `ISSUES.md`.
Scorer sensitivity can be assessed from retained hypotheses without new
recognition. The proposed Spanish V100 decoding control needs a new
full-split ARC job after its small preflight, as specified in
[next_control.md](next_control.md). The P100 nodes were recorded as drained
on 4 October 2026 and remained drained in the read-only check on 6 October.
The V100 nodes were mixed and no matching project jobs were queued. All
178 locked package versions matched the current ARC environment. These
checks establish preparation, not approval to submit the control.
The optional transcript-review flags still need annotated performance
evaluation. None of these checks may silently replace the declared scorer
or the historical artefacts.

## Scope of this review

This is a scoped continuation of `/strong-study`, not a fresh completion
of every stage. The computational work follows the existing
`/strong-codebase` audit, adds empirical source and distribution checks,
and uses `/hpc_advance` for read-only recovery and control preparation.
The submission review applies `/APA7` mechanics and checks the rendered
displays. Literature field verification and new
recognition or neural-masking runs have not been repeated. The study is
ready only after the outstanding author facts, rights decisions and
versioned deposits are completed; the remaining inferential limits must
stay explicit in the submitted text.

Local validation returned 2,231 passed, 38 skipped and one expected
failure for the complete collected suite. The 30 newly added scorer
tests were collected separately; the final focused CPU workflow selection
returned 353 passed. The eleven-artefact gate passed. Final HTML and PDF
renders passed 45 R code chunks, 91 knitting segments and the claims
checks. The 100-page PDF has twelve tables and six figures; all eighteen
display pages, front matter and the changed reference formatting were
visually checked. The HTML has 34 matched references and no unresolved
cross-references or broken fragment links. The abstract has 247 whitespace
words and 250 conservative alphanumeric tokens, within the checked limit.

The frozen scorer was run again from clean source commit
`41fe7125873e3fdab205f4bfa0fcd05f58e565e2`. The resulting CSV is byte-identical,
and every scientific JSON field and type agrees with the first report;
only the producing run metadata and recorded command differ. The committed
JSON now records that clean producer. The comparison is held locally in
`build/clean_scorer_rebuild/comparison.json`. The public input receipt
contains hashes and corpus notices, not a claim that its inputs have
already been deposited.

The language review used two passes over the changed prose and scanned
the source and final PDF. Counts below compare the saved source snapshot
before this submission-formatting stage with its final source. They do
not measure a new whole-manuscript language revision.

| Formula family | Manuscript before | Manuscript after | README before | README after |
| --- | ---: | ---: | ---: | ---: |
| `and not` | 33 | 33 | Unmeasured | Unmeasured |
| Comma followed by `not X` | 25 | 25 | 2 | 2 |
| `instead of` | 23 | 23 | Unmeasured | Unmeasured |
| `rather than` | 8 | 8 | 1 | 1 |
| `in place of` | Unmeasured | Unmeasured | 1 | 1 |
| Total recorded contrastive families | 89 | 89 | 4 | 4 |

Unmeasured cells denote absence from the retained thresholded output,
not an independently retained count for that family. Other below-threshold
families were not measured separately. The manuscript source grew from
57,397 to 59,273 scanner words, including R and LaTeX, so a lower rate
per thousand words would not demonstrate improved prose. The README grew
from 1,368 to 1,895 scanner words. The retained formula counts did not fall.
The new scoring Methods sentence and Results paragraph introduced no
flagged family, but the broader language stage remains partial.

The PDF scan retained thresholded page frequencies, not densities: no
page word denominators or comparable earlier PDF were saved. It reported
`which` clauses on pages 8 (3), 12 (3), 14 (3), 16 (4), 18 (3), 25 (3),
33 (5), 50 (4), 83 (4) and 85 (3), and contrastive frames on pages 61 (3)
and 100 (3). Unflagged pages may contain one or two occurrences. These
twelve flags occur in explanatory prose, including cited findings, and
were inspected; they are not all defects. The source-sentence statistics
also include parsing artefacts and do not establish a general improvement
in sentence length.

This continuation read and applied `/strong-study`, `/strong-codebase`,
`/hpc_advance`, `/APA7` and both passes of `/polish_text` within the scope
stated above. `/project_polish` was unnecessary because the codebase review
already covered the relevant software and documentation. A fresh
`/verify_references` audit remains separate from the completed citation
mechanics. `/dataviz` and the PDF, DOCX and XLSX skills were unavailable;
native figure, PDF and HTML checks provided the recorded substitutes.
No new Word manuscript or spreadsheet was produced. The official APA
site was inaccessible during the review, and the HTML caption script was
checked through its DOM inputs without execution in a browser. These
limitations preclude calling every stage complete.

## Release 2.1.0, 30 October 2026

Release 2.1.0 gathers the two passes after 2.0.0 that `CHANGELOG.md`
describes. Its tree was checked at `3c13116`; the commit that adds this
section changes nothing else.

- The CI selection of 17 test files passed (409 tests) in a virtual
  environment built from `requirements-verification.txt` under Python
  3.13.7, and every test file changed since 2.0.0 passed under the local
  Python 3.13.7 with the CPU build of torch: 1,677 passed, 20 skipped for
  absent optional packages or symlink rights, and 1 expected failure.
  The whole suite was not run on ARC for this release.
- `tools/verify_regeneration.py` regenerated all eleven CPU artefacts
  identically, `ruff check .` (0.15.18, line length included) reported
  nothing, and the HTML and the 97-page PDF rendered with the claims-check
  passing and no warning or unresolved cross-reference.
- The input deposit was rebuilt at this tree with the corrected README of
  CR-06: `sweep_inputs_2026-10.zip`, 62,808,901 bytes, SHA-256
  `fa45a40305655034de8704c33826bd21b6a0b64c3a66d972acf9356edf09524d`.
  Its 273 members equal those of the 2.0.0 build (`6474ba29…`) except
  `README.md`. `decoder_source_6f9bf56.zip` is unchanged (`b66a5119…`).
- The software record takes one ZIP, the `git archive` of the public
  snapshot of this tree, whose digest a detached manifest records, as for
  2.0.0. The reserved DOIs are unchanged: 10.5281/zenodo.23442766 for the
  software and 10.5281/zenodo.23442874 for the inputs.

## Release 2.1.1, 30 October 2026

Release 2.1.1 carries the corrections of the pre-publication gate, which
`ISSUES.md` lists as PG-01 to PG-32 and `CHANGELOG.md` summarises. Release
2.1.0 was tagged on GitHub (7bb5ff8) but never deposited, so 2.1.1 takes
its reserved DOI. Its tree was checked at 4404c12; the commit that adds
this section changes nothing else.

- ARC job 9217052 ran the whole suite on a clean clone of 155d240, whose
  code 4404c12 shares: 2,503 passed, 1 skipped, 1 expected failure and 1
  failure, `tests/test_installed_distribution.py` expecting 2.1.0 by a copy
  of the old same-date rule (PG-32). 4404c12 corrects that test alone, and
  it passes locally. Locally, under Python 3.13.7 with the CPU build of
  torch, the whole suite passed at 5b46974, before the version bump: 2,395
  passed, 43 skipped for absent optional packages or symlink rights, and 1
  expected failure. The CI selection of 20 test files at 155d240 gave 377
  passed, 4 skipped for the absent jiwer, and the same one failure.
- `tools/verify_regeneration.py` regenerated all eleven CPU artefacts
  identically, `ruff check .` reported nothing, and the HTML and the
  98-page PDF rendered at 4404c12 with the claims-check passing and no
  unresolved cross-reference.
- The data record holds three files:
  `sweep_inputs_2026-10.zip` (62,808,954 bytes, SHA-256
  `4fb2071189c9956f22604d47a2b82e0778b69eeeee460bb7da2cba6c31a0e237`),
  whose 273 members equal the 2.1.0 build's except `README.md`;
  `multilingual_hardware_inputs_2026-10.zip` (3,494,333 bytes, SHA-256
  `e5fdecc54ecaa9f85d16c2250afe1f9bf0772b1352466b73162afeb1a7e21db0`),
  built by `tools/build_arc_inputs_deposit.py`; and the sanitised
  `decoder_source_6f9bf56.zip` (8,584,027 bytes, SHA-256
  `c042aa8580cb8afeefbe425fbd177b8c12d328c3db3cad4a42dbb638c63cdd46`),
  built by `tools/build_decoder_source_deposit.py` from the `git archive`
  of 6f9bf56 (`b66a5119…`). The software record takes one ZIP, the `git
  archive` of the public snapshot of this tree, whose digest a detached
  manifest records. The reserved DOIs are unchanged.

