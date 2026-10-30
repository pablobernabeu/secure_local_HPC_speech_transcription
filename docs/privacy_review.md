# Privacy review before release

Reviewed on 6 October 2026 against source HEAD
`309f1d03a0e070ba32ebdf2c0a6559509adbd1db` and all locally reachable Git
references. `git rev-list --count --all` counted 839 commits, including 63
merges. The object inventory contained 2,021 distinct file blobs: 2,012
UTF-8 text blobs, six Word documents and three other binary or non-UTF-8
blobs. Text patterns covered email addresses, Windows user paths, Unix
home/project paths, deployment accounts and the six name tokens in the
current example masking logs. Word XML was inspected separately. The
remaining files were a PNG, an ICO and one legacy shell script, which was
decoded separately and had no email, user/project-path or deployment-account
pattern matches. This is a bounded review of the available checkout and
history, and it does not
establish that every personal identifier is absent. Unreachable objects,
remote-only references, private ARC files and uncommitted ignored files
were outside the history inventory.

Gitleaks 8.30.1 was obtained from the
[official release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1),
with its Windows ZIP checked against the published checksum before use.
Both scans used JSON reports and `--redact`: first with
`--log-opts=--all`, then with `--log-opts='--all --full-history -m'` to
include merge diffs. The second scanner run reported 832 processed commits.
That count is distinct from Git's 839 reachable commits and is not a coverage
identity. The first scan returned four `generic-api-key` findings and the
merge-inclusive scan returned eight. Reading the historical source
classified all eight as bibliography identifiers assigned to
`citation_key` in `evaluation/challenge_suites.py`, with no confirmed
credential among the findings. No allowlist was added and no history was
rewritten.

| Historical commit | Lines | Classification |
| --- | --- | --- |
| `342db0e`, `74a83f6` | 190, 220 | AMI and LibriSpeech bibliography keys, present in the bibliography |
| `f43192c` | 220 | Earlier short LibriSpeech bibliography key |
| `7ba9966` | 154 | Earlier short VoxPopuli bibliography key |
| `0538ee1` | 162, 220 | The same earlier VoxPopuli and LibriSpeech keys |

The following SHA-256 digests identify the scanner and redacted local
reports. Reports and helper inventories remain in ignored
`build/privacy_audit/`, and their presence is not a publication decision.

| Item | SHA-256 |
| --- | --- |
| `gitleaks_8.30.1_windows_x64.zip` | `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e` |
| `gitleaks.exe` | `17157e2ee8b76fc8b1d8bee607a250e34b8a8023c8bc81822d4b5ee4d78fcb7c` |
| `history.json` | `7e49b7c2f452f2d74b43a647d6dc33e0c95576d476faed63335d117b3da59d94` |
| `history_with_merges.json` | `4c5595a89c1a3a339eafa3c4f8397471b217511c023b7953b8c8683a32d337f8` |

The broader text inventory found email-shaped strings in 199 historical
blob versions, Windows user paths in nine, Unix home/project paths in 120
and deployment account names in 110. These categories overlap and count
file versions, not people. Contact addresses occur in the manuscript,
CSL and dependency metadata, and SSH examples also resemble email addresses.
Git author/committer metadata contains three distinct names and three
addresses. Historical bibliography attachments contain local Windows
paths, although the current bibliography has none. Current provenance
files, run configuration and issue descriptions still expose deployment
account/project paths. They help identify the recorded computation but
are not required to interpret its numerical results. Removing them from
a future release copy would not remove earlier public history or archives.

All four current `example_output/transcripts/*/transcript.docx` files were
opened, including `word/document.xml`, both `docProps` XML files and ZIP
relationships. Their transcript bodies exactly match their `.txt` twins
after whitespace normalisation. Headers differ in filenames or processing
timestamps, so the complete files are not text-identical. All four name
`python-docx` as creator, and `behind_the_curtains` additionally has a
`lastModifiedBy` identifier containing the public author's name. No
embedded objects, comments, custom properties, external relationships or
tracked-change tags were found in these four files or the two older Word
blobs. That check does not certify arbitrary Office documents as safe.

The [example README](../example_output/transcripts/README.md) and
[podcast manifest](../data/codex_mentis/manifest.json) identify these as
historical transcripts of the author's public, synthetic *Codex Mentis*
episodes, rather than confidential participant recordings. This is their
documented provenance. The historical input audio digests were not retained
and the original audio bytes could not be independently matched to those
episodes. Their three
current masking logs contain 11 rows with the original tokens and context
sentences, including the author and two researchers cited by the episodes.
The author's possessive surname remains twice in both current
`behind_the_curtains` bodies, as the README already records. Two older Word
versions and their deleted text twins have matching bodies and retain the
surname three times. A four-row older log, deleted in `d44f79b` on
11 November 2025, remains reachable at
`name_masking_logs/name_replacements_Behind the curtains_ Methods used to investigate conceptual processing_enhanced.csv`.
It contains the author's tokens and an additional dictionary-matched
first-name token in a fragmentary sentence. That token's identity has not
been established. The deleted JSON/VTT plain-example outputs in `f041d21`
were also inspected. All originals have been left intact so the historical
masking audit remains reproducible.

*Note of 30 October 2026.* The artefact audit now also scans the review
reports and names the files it could not check (1d2f2ac, 81e57dd). Its
regeneration over `example_output/` (7f867ad) adds the three variants'
`example_review.json` files as masked artefacts and finds them clean. It
still finds the surname in the two `behind_the_curtains` bodies.

The NotebookLM infographic formerly embedded in the root README at
`docs/Beyond the cloud_ Reclaiming data sovereignty in speech transcription.png`
was moved, with its bytes preserved, to
[`docs/historical/Beyond the cloud_ Reclaiming data sovereignty in speech transcription.png`](<historical/Beyond the cloud_ Reclaiming data sovereignty in speech transcription.png>).
The README embed was removed, and the
[historical note](historical/README.md) explains that its claims about
guaranteed GDPR compliance, impossible cloud replication, unlimited scale
and removal of AI-generated errors exceed the evidence. Targeted searches
found no other Markdown, QMD or HTML image references. Its compressed APP1
profile was decoded and inspected: it contains software and image-identifier
tags, with no GPS IFD and no email, local-path, deployment-account or
recognisable secret-token pattern matches. These checks are limited to the
inspected metadata and visible image, and the graphic remains explicitly
historical.

Corpus licences were checked at their primary sources on 6 October 2026.
They govern the source material separately from this project's software.

| Source material | Verified source licence and distinction |
| --- | --- |
| LibriSpeech data | [OpenSLR SLR12](https://www.openslr.org/12): CC BY 4.0 |
| FLEURS data | [Google's dataset card](https://huggingface.co/datasets/google/fleurs): CC BY 4.0 |
| AMI corpus and annotations | [AMI licence](https://groups.inf.ed.ac.uk/ami/corpus/license.shtml): CC BY 4.0 |
| VoxPopuli data | [Authors' licence table](https://github.com/facebookresearch/voxpopuli#license): CC0; the repository's code and pretrained models are separately CC BY-NC 4.0, and raw recordings have a linked European Parliament notice |

Any separately archived hypothesis/reference dumps should identify their
exact corpus, split and producing run, retain supplied attribution and
licence notices, and state that hypotheses are generated transcriptions
which may contain errors. CC BY 4.0 requires attribution and disclosure of
modifications, but it does not grant general privacy or personality rights.
See the [primary legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en),
sections 2(b) and 3(a). The recovered dumps themselves still need a content
inventory before a publication decision. This licence review is not a
review of their individual rows.

The remaining author decisions are to retain or omit the public podcast
original-name logs and document-editor metadata in the next release, and
to review the additional historical log token. Public podcast names can be
retained as explicitly documented historical examples if the author
accepts that disclosure. Publication of any new hypothesis archive also
awaits its content and attribution inventory. These decisions are
unresolved, and the review supports a partly resolved G6, not a claim that
the repository or its history is free of personal data. The decision on
deployment identifiers was taken on 30 October 2026, and
[the last section](#deployment-identifiers-in-release-211) records it.

An incremental Gitleaks scan of `309f1d0..41fe712` on 6 October 2026
returned no findings. It covered the submission and archive follow-up
commit, including the new public hash-only input receipt; the ignored
recovered hypothesis bundle was outside that scan. The redacted result is
held locally in `build/privacy_audit/followup_commits.json`. This update
extends the earlier bounded credential review, without settling the
remaining retention and content decisions.

## Recovered sweep text and archive metadata

The local content inventory traversed all fifteen hypothesis CSVs and
parsed all 255 summary JSON files, rechecking the 270 exact input digests.
The CSVs contain 1,386,066 condition–utterance rows. Within each model,
raw reference and hypothesis strings are unchanged across conditions;
reference strings agree across models on shared utterance IDs. No
condition–utterance key is repeated. The counts below describe the retained
dumps, including the historical reference exclusions in individual cells.

| Suite | Distinct utterance IDs per model | Rows across three models |
| --- | ---: | ---: |
| AMI IHM test | 12,643 | 641,823 |
| FLEURS en_us test | 647 | 32,997 |
| LibriSpeech test-clean | 2,620 | 133,620 |
| LibriSpeech test-other | 2,939 | 149,889 |
| VoxPopuli en_accented test | 8,387 | 427,737 |
| Total | 27,236 per model | 1,386,066 |

Gitleaks scanned all 1,021,407,391 recovered bytes and returned no findings.
Separate patterns checked email-shaped strings, web URLs, Windows user
paths, Unix home/project paths and telephone-shaped numbers in the four
CSV text fields. Only web URLs matched: one distinct raw-hypothesis value
and five transformed values in the VoxPopuli Medium dump. These are field
and file counts, not people or independent recordings. They include
generated text whose accuracy has not been established. No named-entity
recogniser or exhaustive personal-data classification was run. Names and
other identifying or sensitive statements may be present without a match.
The local proof and pattern definitions are in
`build/recovered_arc_sweep/content_inventory.json` and the redacted
credential report is `gitleaks_content.json` beside it.

A further comparison covers all 255 retained CSV cells: row counts agree
with their source summaries, every stored WER is finite and nonnegative,
and each rounded-score mean agrees with the full-precision macro WER
within the six-decimal CSV tolerance. The largest absolute difference is
`2.682190114455807e-08`. This comparison does not re-align words or
characters; the earlier exact alignment reconstruction covers the thirty
raw/normaliser cells. Its local proof is
`build/recovered_arc_sweep/all_csv_cells_verification.json`.

The recovered TAR contains ARC ownership metadata even though its file
contents match the public hash receipt. The original recovery archive
remains unchanged. A separate local candidate removes ownership names,
sets user/group IDs to zero, regular-file mode to `0644` and timestamps
to zero, and uses an empty gzip filename. Independent streaming checks
verify every input byte and all 270 paths, with no extra file, symbolic
link or PAX metadata. The transformation changes the archive hash, not
the source-input hashes. The detached review inventory records both
archives and this derivation. It remains a candidate pending the rights,
attribution and retention decisions above.

## Deployment identifiers in release 2.1.1

On 30 October 2026 the author decided to sanitise deployment identifiers
in release 2.1.1 and its deposits: the Oxford ARC user name, the two ARC
project account codes, the absolute ARC paths that contain them, and the
names of other projects' jobs on the shared account. They point to a
person and to projects, and no result needs them to be read. The names of
the cluster (`htc`), its nodes, its login node, its partitions and its QoS
stay, because they identify the public cluster that the paper names.

Each change is a plain string replacement, made in this order. The
originals are described, not quoted, since quoting them here would undo
the change:

| Original | Replacement |
| --- | --- |
| The user's data directory under either project account, `/data/<account>/<user>` | `$DATA` |
| The user's home directory, `/home/<user>` | `$HOME` |
| The ARC user name anywhere else | `<user>` |
| The first project account, where a record states which account ran a job | `<project-a>` |
| The second project account, likewise | `<project-b>` |
| The account in a usage or reproduction command, `--account=<account>` | `--account='<your-project>'` |
| The name of another study's job | A made-up name of the same shape, such as `other_fit` or `other_render` |

ARC sets `$DATA` to the user's project data directory, which the scripts
already assumed. The command placeholder is quoted because bash reads an
unquoted `<` and `>` as redirections: a command pasted unchanged then
fails at sbatch, which rejects the account, and the tests that run the
records' commands still run them. The lines that said either project
account was valid, and named the one the examples used, now tell the
reader to pass their own. Generic job names of other projects (`render`,
`docchecks`, `cat` and the like) identify no study and stay as they ran,
in the tests and in the comments of `evaluation/footprint.py`.

The release tree changed in these files:

- Scripts and documentation: `.hpc-plan.yaml`, which now describes the
  other projects on the shared account without their job names,
  `docs/next_control.md`, `hpc/README.md`, the seventeen run records in
  `hpc/runs/`, the headers of nine job scripts in `hpc/`,
  `manuscript/README.md` and `output/case_study/README.md`.
- Tests: `tests/test_audit_shell_review_fixes.py`,
  `tests/test_footprint_job_scope.py` and `tests/test_s1_misc_footprint.py`.
  Their sacct rows keep every field the tests read, and the row copied
  from another project's job is now a made-up job, `other_render`.
- Result files, in a provenance-only edit that the author authorised and
  that changes no other byte: `output/evaluation/sweep_aggregate_prefix.json`
  and `.csv`, `determinism/determinism_cross_accelerator.json` and
  `determinism/determinism_cross_accelerator_runs.json`,
  `fleurs_es419_v100_control.json`, `der_sweep_selection.json`,
  `der_sweep2_selection.json`, `reconstruction_audit_test.json` and
  `reconstruction_audit_validation.json` in `output/evaluation/`, and
  `output/case_study/codex_mentis_ep05_manifest.json`. Two recorded
  digests follow the change, so that each record stays true. The LF
  SHA-256 of the runs file that `determinism_cross_accelerator.json`
  gives under `meta_file` is now
  `c39f18cff8a1729fa26667a6996ef005e6ece0c052ac1bc352e639e259e7f34a`, and
  the case-study manifest's own `manifest_sha256` is now
  `a56282e1c81d399f1cbb9015fd61a2e3a85b44895ed24e05fa6dc3f5a91dc598`. No
  other tracked file records the digest of a file changed here. A result
  file rebuilt on ARC from its original inputs would carry the original
  strings again, and differ from the committed copy in those strings only.
- The same table applies to `manuscript/manuscript.qmd`, `CHANGELOG.md`,
  `ISSUES.md`, `requirements-lock.txt` and `tests/test_fleurs_control.py`
  in the same release.

The data record's `decoder_source_6f9bf56.zip` is replaced by a sanitised
copy under the same name, which `tools/build_decoder_source_deposit.py`
writes from the `git archive` of `6f9bf56`. That archive, taken in
memory, matched the deposited original byte for byte (8,589,655 bytes,
SHA-256 `b66a511905b7e648987ef2f577105cd5b95e7d6556aa4ce398dda605875c5ccb`).
The table changed 24 of its 387 files, in 551 replacements, and no binary
member holds an identifier. `SANITISED.md` at the copy's root gives the
table and, for each changed file, its path and the git blob id of its
original content, and the ZIP comment is still the commit identifier. The
copy has 8,584,027 bytes and SHA-256
`c042aa8580cb8afeefbe425fbd177b8c12d328c3db3cad4a42dbb638c63cdd46`, the
same in two builds with Python 3.13.7 and zlib 1.3.1, and a scan of every
member, inside its Word documents too, finds no identifier.

The sanitisation does not reach what was published before it. The
earlier public snapshots on GitHub, release 2.0.0 at `fe579c6` and
release 2.1.0 at `7bb5ff8`, and the development repository's history
still contain the originals.
