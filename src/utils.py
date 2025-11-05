"""
Utility functions for the children's speech transcription pipeline.
"""

import os
import json
from pathlib import Path
from typing import Union, List
import datetime


def format_timestamp(seconds: float) -> str:
    """
    Format seconds into HH:MM:SS.mmm format.
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def validate_audio_file(file_path: Union[str, Path]) -> bool:
    """
    Validate if a file is a supported audio file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if valid audio file, False otherwise
    """
    file_path = Path(file_path)
    
    # Check if file exists
    if not file_path.exists():
        return False
    
    # Check file extension
    supported_extensions = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac', '.wma'}
    if file_path.suffix.lower() not in supported_extensions:
        return False
    
    # Check if file is not empty
    if file_path.stat().st_size == 0:
        return False
    
    return True


def ensure_directory_exists(directory: Union[str, Path]) -> Path:
    """
    Ensure a directory exists, create it if it doesn't.
    
    Args:
        directory: Path to directory
        
    Returns:
        Path object of the directory
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_audio_files_from_directory(directory: Union[str, Path], 
                                 extensions: List[str] = None) -> List[Path]:
    """
    Get all audio files from a directory.
    
    Args:
        directory: Directory to search
        extensions: List of file extensions to include
        
    Returns:
        List of audio file paths
    """
    if extensions is None:
        extensions = ['.wav', '.mp3', '.m4a', '.flac', '.ogg', 'aac']
    
    directory = Path(directory)
    audio_files = []
    
    for ext in extensions:
        # Case-insensitive glob pattern
        pattern = f"*{''.join(f'[{c.lower()}{c.upper()}]' for c in ext)}"
        audio_files.extend(directory.glob(pattern))
    
    # Remove duplicates that might arise from case-sensitive systems
    return sorted(list(set(audio_files)))


def save_transcription_results(results: dict, 
                             output_path: Union[str, Path],
                             format_type: str = "json") -> None:
    """
    Save transcription results to file.
    
    Args:
        results: Transcription results dictionary
        output_path: Output file path
        format_type: Output format ('json', 'txt', 'csv')
    """
    output_path = Path(output_path)
    
    if format_type.lower() == "json":
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    
    elif format_type.lower() == "txt":
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(results.get("text", ""))
    
    elif format_type.lower() == "csv":
        import pandas as pd
        # Convert to DataFrame-friendly format
        data = {
            "file_name": [results.get("file_name", "")],
            "text": [results.get("text", "")],
            "duration": [results.get("duration", 0)],
            "processing_time": [results.get("processing_time", 0)],
            "timestamp": [results.get("timestamp", "")]
        }
        df = pd.DataFrame(data)
        df.to_csv(output_path, index=False, encoding='utf-8')


def format_transcription_with_timestamps(result: dict) -> str:
    """
    Format transcription result with timestamps.
    
    Args:
        result: Transcription result with chunks
        
    Returns:
        Formatted string with timestamps
    """
    if "chunks" not in result or not result["chunks"]:
        return result.get("text", "")
    
    formatted_lines = []
    for chunk in result["chunks"]:
        timestamp = chunk.get("timestamp", [0, 0])
        start_time = format_timestamp(timestamp[0]) if timestamp[0] else "00:00:00.000"
        end_time = format_timestamp(timestamp[1]) if timestamp[1] else "00:00:00.000"
        text = chunk.get("text", "").strip()
        
        if text:
            formatted_lines.append(f"[{start_time} --> {end_time}] {text}")
    
    return "\n".join(formatted_lines)


def calculate_processing_stats(results: List[dict]) -> dict:
    """
    Calculate processing statistics from batch results.
    
    Args:
        results: List of transcription results
        
    Returns:
        Dictionary with processing statistics
    """
    successful_results = [r for r in results if "error" not in r]
    failed_results = [r for r in results if "error" in r]
    
    if not successful_results:
        return {
            "total_files": len(results),
            "successful": 0,
            "failed": len(failed_results),
            "success_rate": 0.0
        }
    
    total_duration = sum(r.get("duration", 0) for r in successful_results)
    total_processing_time = sum(r.get("processing_time", 0) for r in successful_results)
    
    return {
        "total_files": len(results),
        "successful": len(successful_results),
        "failed": len(failed_results),
        "success_rate": len(successful_results) / len(results) * 100,
        "total_audio_duration": total_duration,
        "total_processing_time": total_processing_time,
        "average_processing_time": total_processing_time / len(successful_results),
        "real_time_factor": total_processing_time / total_duration if total_duration > 0 else 0
    }


def create_project_structure(base_dir: Union[str, Path]) -> None:
    """
    Create a standard project structure for transcription projects.
    
    Args:
        base_dir: Base directory for the project
    """
    base_dir = Path(base_dir)
    
    directories = [
        "audio_input",
        "transcriptions",
        "logs",
        "config"
    ]
    
    for directory in directories:
        ensure_directory_exists(base_dir / directory)
    
    print(f"✓ Project structure created in: {base_dir}")


def get_system_info() -> dict:
    """
    Get system information for debugging and logging.
    
    Returns:
        Dictionary with system information
    """
    import platform
    import torch
    
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        "timestamp": datetime.datetime.now().isoformat()
    }
