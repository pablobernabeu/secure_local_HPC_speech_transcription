"""
Setup script for the Speech Transcription System.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

# Read requirements
requirements = (this_directory / "requirements.txt").read_text().strip().split('\n')

setup(
    name="speech-transcription-system",
    version="1.0.0",
    author="Pablo Bernabeu",
    description="Production-grade speech transcription with audio enhancement, speaker attribution, and privacy protection",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pablobernabeu/speech_transcription",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.11",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "transcribe=transcription:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["*.md", "*.txt", "*.csv"],
    },
    keywords="speech recognition, whisper, transcription, audio processing, speaker diarization, privacy protection",
    project_urls={
        "Bug Reports": "https://github.com/pablobernabeu/speech_transcription/issues",
        "Source": "https://github.com/pablobernabeu/speech_transcription",
    },
)
