"""Check that the committed example outputs are what the pipeline writes today.

``example_output/variants/`` is what a reader looks at to see what the
workflow produces. ``tools/generate_example_variants.py`` makes it by
running ``transcription.main`` on a synthetic interview, with only the
model calls replaced and the volatile values pinned, so the examples come
from the pipeline's own writers. Nothing imports that generator, so if the
committed files and the pipeline drift apart, because the examples were
hand-edited or a writer changed without the generator being re-run,
nothing would say so. These tests regenerate every variant into a
temporary directory and compare it, file set and contents, with the
committed copy.

They also check what that comparison alone cannot: that the generator
really goes through the pipeline's writers (an earlier version wrote the
files from its own templates, which drifted, audit finding XREF-03), that
the committed manifests verify against the committed files, and that the
example's interview text carries no figures to go stale (CORE-19).

The generator writes only to the destination it is given, so the checks
never touch the repository.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import generate_example_variants as gen

COMMITTED = REPO_ROOT / "example_output" / "variants"


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    """Every variant, regenerated once for the whole module."""
    root = tmp_path_factory.mktemp("variants")
    for variant in gen.VARIANTS:
        gen.generate_variant(variant, root / variant)
    return root


def _files(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir() if p.is_file()}


@pytest.mark.parametrize("variant", sorted(gen.VARIANTS))
def test_committed_variant_has_exactly_the_files_the_pipeline_writes(
        regenerated, variant):
    """A file the pipeline no longer writes, or a new one, fails here."""
    committed = COMMITTED / variant
    if not committed.is_dir():
        pytest.skip(f"{committed.relative_to(REPO_ROOT)} is not committed")
    assert _files(committed) == _files(regenerated / variant)


@pytest.mark.parametrize("variant", sorted(gen.VARIANTS))
def test_committed_example_matches_the_generator(regenerated, variant):
    committed = COMMITTED / variant
    if not committed.is_dir():
        pytest.skip(f"{committed.relative_to(REPO_ROOT)} is not committed")
    for name in sorted(_files(committed) & _files(regenerated / variant)):
        # read_text reads CRLF as LF, so a checkout's line endings do not
        # decide the outcome; the manifest test below checks the bytes.
        assert (regenerated / variant / name).read_text(encoding="utf-8") == \
            (committed / name).read_text(encoding="utf-8"), (
                f"{variant}/{name} differs from what the pipeline writes; "
                "re-run tools/generate_example_variants.py and commit the result")


def test_every_committed_variant_is_covered():
    """A new variant directory must not slip past this file unchecked."""
    if not COMMITTED.exists():
        pytest.skip("example_output/variants is not present")
    on_disk = {d.name for d in COMMITTED.iterdir() if d.is_dir()}
    assert on_disk == set(gen.VARIANTS), (
        f"variants on disk {sorted(on_disk)} do not match those checked "
        f"{sorted(gen.VARIANTS)}")


def test_the_generator_is_deterministic(tmp_path):
    """Two runs must agree byte for byte, or the comparison is meaningless."""
    variant = "04_diarisation_and_timestamps"
    first = gen.generate_variant(variant, tmp_path / "a")
    second = gen.generate_variant(variant, tmp_path / "b")
    assert [p.name for p in first] == [p.name for p in second]
    for a, b in zip(first, second, strict=True):
        assert a.read_bytes() == b.read_bytes(), a.name


def test_the_generator_goes_through_the_pipeline_writers(tmp_path):
    """The examples must come from the real writers, not a copy of them."""
    import provenance

    t = gen.import_pipeline()
    spies = {
        "write_timestamped_outputs": mock.patch.object(
            t, "write_timestamped_outputs", wraps=t.write_timestamped_outputs),
        "write_review_file": mock.patch.object(
            t, "write_review_file", wraps=t.write_review_file),
        "save_transcript_file": mock.patch.object(
            t, "save_transcript_file", wraps=t.save_transcript_file),
        "write_manifest": mock.patch.object(
            provenance, "write_manifest", wraps=provenance.write_manifest),
    }
    started = {name: patcher.start() for name, patcher in spies.items()}
    try:
        gen.generate_variant("04_diarisation_and_timestamps", tmp_path)
    finally:
        for patcher in spies.values():
            patcher.stop()
    for name, spy in started.items():
        assert spy.called, f"{name} was not called"
    assert started["save_transcript_file"].call_count == 2  # plain + speakers


@pytest.mark.parametrize("variant", sorted(gen.VARIANTS))
def test_committed_manifest_verifies(variant):
    """Each committed manifest's digests match the committed files.

    This needs the files checked out with LF line endings, which
    .gitattributes asks for.
    """
    import provenance

    manifest = COMMITTED / variant / "example_manifest.json"
    if not manifest.exists():
        pytest.skip(f"{manifest.relative_to(REPO_ROOT)} is not committed")
    report = provenance.verify_manifest(manifest)
    assert report["ok"], report


def test_the_example_text_states_no_figures():
    """The interview once quoted evaluation results that went stale (CORE-19).

    Figures belong in output/evaluation and the paper, which are regenerated
    with the code; the example text points there instead of repeating them.
    """
    text = " ".join(turn for _, turn in gen.TURNS)
    assert not re.search(r"\d", text)


def test_the_example_shows_masking_at_work(regenerated):
    """The raw captions keep the names; every masked artefact replaces them."""
    variant = regenerated / "04_diarisation_and_timestamps"
    raw = (variant / "example_transcript.vtt").read_text(encoding="utf-8")
    assert "Rossi" in raw and "Elena" in raw
    for name in ("example_transcript.txt", "example_transcript_with_speakers.txt",
                 "example_transcript_redacted.vtt"):
        masked = (variant / name).read_text(encoding="utf-8")
        assert "Rossi" not in masked and "Elena" not in masked, name
        assert "[SURNAME]" in masked and "[NAME]" in masked, name
