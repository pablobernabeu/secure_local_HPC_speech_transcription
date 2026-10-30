"""
Setup script for the Speech Transcription System.

The workflow is a set of top-level modules, not a package, so they are
listed in ``py_modules``. With only ``find_packages()`` a non-editable
install carried just ``evaluation`` and ``local_app``, and the declared
``transcribe`` entry point failed with ModuleNotFoundError (audit findings
CORE-17, DEPS-13, XREF-02).
"""

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

# These files are read beside transcription.py. They are outside the two
# Python packages, so package_data alone does not put them in a wheel.
_RUNTIME_DATA = ("data/curated_names.csv", "versions.csv")


class RuntimeDataBuild(build_py):
    """Keep the installed module's dictionary and release record beside it."""

    def run(self):
        """Build the modules, then copy each :data:`_RUNTIME_DATA` file into
        the build tree at its repository-relative path."""
        super().run()
        for relative in _RUNTIME_DATA:
            destination = Path(self.build_lib) / relative
            self.mkpath(str(destination.parent))
            self.copy_file(str(this_directory / relative), str(destination))

    def get_outputs(self, include_bytecode=1):
        """Return the files this command built, the copied runtime data
        included, so that setuptools counts them among its outputs."""
        return [*super().get_outputs(include_bytecode),
                *(str(Path(self.build_lib) / relative) for relative in _RUNTIME_DATA)]


def _read_requirements(name):
    """Return the requirement lines of *name*, without comments or blanks."""
    lines = (this_directory / name).read_text(encoding='utf-8').splitlines()
    return [line.strip() for line in lines
            if line.strip() and not line.strip().startswith('#')]


# Runtime requirements only; development tools live in requirements-dev.txt
# and are offered as the "dev" extra.
requirements = _read_requirements("requirements.txt")

_REPO_URL = "https://github.com/pablobernabeu/secure_local_HPC_speech_transcription"

setup(
    name="speech-transcription-system",
    # Kept by hand in step with CITATION.cff and versions.csv (CORE-17).
    version="2.1.1",
    author="Pablo Bernabeu",
    description="Local speech transcription with audio enhancement and speaker attribution",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url=_REPO_URL,
    license="MIT",
    packages=find_packages(include=["evaluation", "evaluation.*",
                                    "local_app", "local_app.*"]),
    py_modules=[
        "transcription",
        "audio_io",
        "audio_redaction",
        "confidence",
        "ner_masking",
        "preflight",
        "provenance",
        "voice_anonymisation",
    ],
    classifiers=[
        # Beta: the description no longer claims production grade (41fe712),
        # and the evaluation reports defects found after release 1.0.0.
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    # Kept in step with preflight._PYTHON_FLOOR; a test asserts they agree.
    python_requires=">=3.11",
    install_requires=requirements,
    extras_require={"dev": _read_requirements("requirements-dev.txt")},
    entry_points={
        "console_scripts": [
            "transcribe=transcription:main",
        ],
    },
    include_package_data=True,
    cmdclass={"build_py": RuntimeDataBuild},
    package_data={
        "": ["*.md", "*.txt", "*.csv"],
    },
    keywords=("speech recognition, whisper, transcription, audio processing, "
              "speaker diarization, privacy protection"),
    project_urls={
        "Bug Reports": f"{_REPO_URL}/issues",
        "Source": _REPO_URL,
    },
)
