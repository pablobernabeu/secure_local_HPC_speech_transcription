# CPU verification

[The GitHub Actions workflow](../.github/workflows/cpu-verification.yml)
checks the committed statistical inputs and the code that produces their
derived results on pushes, pull requests and manual runs. It runs a focused
CPU test suite, then `python tools/verify_regeneration.py --keep`, which
regenerates and compares all eleven CPU artefacts. The tests check bootstrap
sampling, pairing and reader clusters. They also cover job accounting, scoring
and masking, alongside transcript review, provenance and the committed example
variants. Three distribution tests build a wheel and source archive without network access,
rebuild from the archive, and check the installed default dictionary masker
and release record from outside the checkout.

The runner uses Ubuntu 24.04 and Python 3.12.12. The
[verification requirements](../requirements-verification.txt) pin the CPU
packages and their dependencies to the versions recorded in the ARC
[environment lock](../requirements-lock.txt). This subset omits the audio and
machine-learning stack. It tests the derivation of the committed results.
Recognition, diarisation and neural anonymisation remain outside this gate.
Those stages still require the recorded models, evaluation data and ARC environment.

The workflow first ran on GitHub on 17 October 2026, when the author
approved pushing the review branch `study-followup-2026-10-06`. Its third
run (run 39053843039, at 1832fb0) passed all 389 tests of the selection
and matched all eleven gate artefacts on Ubuntu 24.04 with Python 3.12.12.
The two runs before it failed on defects they found: a run-manifest field
that changed the committed example variants, and a file order in the
artefact audit that differed between Windows and Linux. Both are fixed in
the commits those runs tested against (05e0530, 9e211db).

Each run installs binary packages into the runner's fresh Python environment,
checks their dependencies and prints the installed versions. Optional model
loaders are absent, Hugging Face offline mode is enabled, and no credentials
or private files are supplied. The workflow uses a read-only repository token,
does not retain checkout credentials, and pins the two official actions to
full commit SHAs. These choices follow
[GitHub's workflow security guidance](https://docs.github.com/en/actions/reference/security/secure-use).
GitHub manages the runner image and package installer, so these parts of the
execution environment remain outside the project's version pins.

To repeat the checks locally with Python 3.12.12, create a fresh virtual
environment and install the pinned subset:

```sh
python -m venv .venv-verification
. .venv-verification/bin/activate
python -m pip install --only-binary=:all: -r requirements-verification.txt
python -m pip check
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_bootstrap_ci.py tests/test_condition_ci.py \
  tests/test_speaker_cluster_ci.py tests/test_scorer_sensitivity.py \
  tests/test_repetition_sensitivity.py tests/test_footprint.py \
  tests/test_footprint_job_scope.py tests/test_benchmark_masking.py \
  tests/test_wer_normalisation.py tests/test_wer_aggregate.py \
  tests/test_confidence.py tests/test_review_repeated_passages.py \
  tests/test_provenance.py tests/test_example_variants.py \
  tests/test_installed_distribution.py \
  tests/test_verify_regeneration.py tests/test_build_input_deposit.py
python tools/verify_regeneration.py --keep
```

Use the platform's equivalent activation command on Windows. The requirements
also pin pytest's Windows-only `colorama` dependency, which is absent from the
Linux ARC freeze. The regeneration command writes to a temporary
directory and leaves every committed artefact intact. With `--keep`, producer
logs survive a failure. CI prints the last eighty lines of each log when the
gate fails.

The gate first compares bytes, then permits equivalent text line endings,
volatile provenance fields and the historical path separators in `wer_ci.csv`.
One additional allowance applies only to `masking_summary.json`: its
`curated_names_sha256` can identify the current dictionary with LF or CRLF
line endings. Both digests must match those representations of the current
input, and all other nonvolatile fields must agree. A changed dictionary entry,
row order, language label or benchmark measurement still fails. The allowance
is printed explicitly and requires no changes to the archived results.

A passing gate establishes that the current producers reproduce these eleven
artefacts from the committed inputs. It does not establish the
[dictionary's external provenance](dictionary_provenance.md), the validity
of the source recognition results or the portability of GPU inference.

The exploratory [scorer sensitivity](../evaluation/scorer_sensitivity.py)
has its own small tests in CI. Its full regeneration additionally requires
the recovered ARC sweep bundle, containing the hypothesis dumps and source
summaries. The public [checksum receipt](../output/evaluation/sweep_input_manifest.json)
records their exact hashes and byte counts. Once that bundle is available locally,
the separate command is:

```sh
python -m evaluation.scorer_sensitivity \
  --inputs build/recovered_arc_sweep/inputs \
  --input-manifest output/evaluation/sweep_input_manifest.json \
  --aggregate output/evaluation/sweep_aggregate.json \
  --output-csv build/recovered_arc_sweep/scorer_sensitivity.csv \
  --output-json build/recovered_arc_sweep/scorer_sensitivity.json
```

The command verifies the selected input hashes and reconstructs every
original raw and Whisper-normalised per-utterance score and aggregate before
applying the alternative apostrophe rule. It reports gains on shared
utterances under each rule, a fixed sample shared across rules and any new
empty-reference exclusions. The exploratory outputs are separate from the
canonical WER results. Their inputs are deposited in a separate data
record (<https://doi.org/10.5281/zenodo.23442874>), not in this
checkout, so this analysis remains outside the eleven-artefact automatic
regeneration gate.
