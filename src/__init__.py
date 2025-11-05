"""
Initialise the src package.
"""

from .transcription_pipeline import ChildrenSpeechTranscriber
from .audio_processor import AudioProcessor
from .utils import (
    format_timestamp,
    validate_audio_file,
    ensure_directory_exists,
    get_audio_files_from_directory,
    save_transcription_results,
    format_transcription_with_timestamps,
    calculate_processing_stats,
    create_project_structure,
    get_system_info
)

__all__ = [
    'ChildrenSpeechTranscriber',
    'AudioProcessor',
    'format_timestamp',
    'validate_audio_file',
    'ensure_directory_exists',
    'get_audio_files_from_directory',
    'save_transcription_results',
    'format_transcription_with_timestamps',
    'calculate_processing_stats',
    'create_project_structure',
    'get_system_info'
]
