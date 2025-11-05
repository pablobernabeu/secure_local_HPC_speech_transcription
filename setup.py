"""
Setup script for the Children's Speech Transcription Pipeline.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

# Read requirements
requirements = (this_directory / "requirements.txt").read_text().strip().split('\n')

setup(
    name="lift-speech_transcription",
    version="1.0.0",
    author="LiFT Speech Transcription Team",
    description="Children's speech transcription using fine-tuned Whisper model",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/LiFT_speech_transcription",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "lift-transcribe=cli:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["*.md", "*.txt"],
    },
    keywords="speech recognition, children speech, whisper, transcription, audio processing",
    project_urls={
        "Bug Reports": "https://github.com/yourusername/LiFT_speech_transcription/issues",
        "Source": "https://github.com/yourusername/LiFT_speech_transcription",
        "Documentation": "https://github.com/yourusername/LiFT_speech_transcription/wiki",
    },
)
