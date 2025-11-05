"""
Audio preprocessing utilities for children's speech transcription.
"""

import numpy as np
import librosa
import soundfile as sf
from pathlib import Path
from typing import Tuple, Optional
import warnings
from scipy import signal
from scipy.ndimage import median_filter


class AudioProcessor:
    """
    Audio preprocessing utilities optimised for children's speech.
    """
    
    def __init__(self, 
                 target_sr: int = 16000,
                 normalise: bool = True,
                 remove_silence: bool = True,
                 noise_reduction: bool = True,
                 enhance_speech: bool = True,
                 volume_balance: bool = True):
        """
        Initialise audio processor.
        
        Args:
            target_sr: Target sample rate for processing
            normalise: Whether to normalise audio amplitude
            remove_silence: Whether to trim silence from beginning/end
            noise_reduction: Whether to apply advanced noise reduction
            enhance_speech: Whether to apply speech-specific enhancements
            volume_balance: Whether to balance volume levels across speakers
        """
        self.target_sr = target_sr
        self.normalise = normalise
        self.remove_silence = remove_silence
        self.noise_reduction = noise_reduction
        self.enhance_speech = enhance_speech
        self.volume_balance = volume_balance
    
    def load_and_preprocess(self, audio_path: Path) -> Tuple[np.ndarray, int]:
        """
        Load and preprocess an audio file with comprehensive enhancements.
        
        Args:
            audio_path: Path to the audio file
            
        Returns:
            Tuple of (audio_data, sample_rate)
        """
        try:
            print(f"🔊 Loading and enhancing audio: {audio_path.name}")
            
            # Load audio file
            audio, original_sr = librosa.load(str(audio_path), sr=self.target_sr)
            print(f"   Original duration: {len(audio)/self.target_sr:.2f}s")
            
            # Apply preprocessing steps in optimal order
            if self.remove_silence:
                audio = self._trim_silence(audio)
                print(f"   After silence removal: {len(audio)/self.target_sr:.2f}s")
            
            if self.noise_reduction:
                audio = self._advanced_noise_reduction(audio)
                print("   ✓ Applied noise reduction")
            
            if self.enhance_speech:
                audio = self._enhance_speech_clarity(audio)
                print("   ✓ Enhanced speech clarity")
            
            if self.volume_balance:
                audio = self._balance_volume_levels(audio)
                print("   ✓ Balanced volume levels")
            
            if self.normalise:
                audio = self._normalise_audio(audio)
                print("   ✓ Normalised audio")
            
            return audio, self.target_sr
            
        except Exception as e:
            raise ValueError(f"Error loading audio file {audio_path}: {str(e)}")
    
    def _trim_silence(self, audio: np.ndarray, top_db: int = 30) -> np.ndarray:
        """
        Remove silence from the beginning and end of audio.
        
        Args:
            audio: Audio signal
            top_db: Threshold for silence detection
            
        Returns:
            Trimmed audio signal
        """
        # Trim silence from beginning and end
        audio_trimmed, _ = librosa.effects.trim(audio, top_db=top_db)
        
        # Ensure we don't return empty audio
        if len(audio_trimmed) == 0:
            return audio
        
        return audio_trimmed
    
    def _normalise_audio(self, audio: np.ndarray) -> np.ndarray:
        """
        Normalise audio amplitude.
        
        Args:
            audio: Audio signal
            
        Returns:
            Normalised audio signal
        """
        # Avoid division by zero
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            return audio / max_val
        return audio
    
    def _reduce_noise(self, audio: np.ndarray) -> np.ndarray:
        """
        Apply basic noise reduction using spectral gating.
        
        Args:
            audio: Audio signal
            
        Returns:
            Noise-reduced audio signal
        """
        # Simple spectral gating approach
        # This is a basic implementation - for advanced noise reduction,
        # consider using specialised libraries like noisereduce
        
        # Compute STFT
        stft = librosa.stft(audio)
        magnitude = np.abs(stft)
        
        # Estimate noise floor (bottom 10% of magnitude values)
        noise_floor = np.percentile(magnitude, 10)
        
        # Create mask: suppress frequencies below noise threshold
        mask = magnitude > (noise_floor * 2)  # 2x noise floor threshold
        
        # Apply mask
        stft_cleaned = stft * mask
        
        # Convert back to time domain
        audio_cleaned = librosa.istft(stft_cleaned)
        
        return audio_cleaned

    def _advanced_noise_reduction(self, audio: np.ndarray) -> np.ndarray:
        """
        Apply advanced noise reduction techniques optimised for speech.
        
        Args:
            audio: Audio signal
            
        Returns:
            Enhanced audio signal
        """
        # 1. Spectral subtraction for noise reduction
        stft = librosa.stft(audio, hop_length=512)
        magnitude, phase = np.abs(stft), np.angle(stft)
        
        # Estimate noise profile from first 0.5 seconds
        noise_frames = int(0.5 * self.target_sr / 512)
        noise_profile = np.mean(magnitude[:, :noise_frames], axis=1, keepdims=True)
        
        # Apply spectral subtraction
        alpha = 2.0  # Over-subtraction factor
        magnitude_enhanced = magnitude - alpha * noise_profile
        
        # Ensure we don't go below 10% of original magnitude
        magnitude_enhanced = np.maximum(magnitude_enhanced, 0.1 * magnitude)
        
        # Reconstruct signal
        stft_enhanced = magnitude_enhanced * np.exp(1j * phase)
        audio_enhanced = librosa.istft(stft_enhanced, hop_length=512)
        
        # 2. Apply median filtering to remove impulse noise
        # Use small kernel to preserve speech transients
        audio_filtered = signal.medfilt(audio_enhanced, kernel_size=3)
        
        return audio_filtered

    def _enhance_speech_clarity(self, audio: np.ndarray) -> np.ndarray:
        """
        Apply speech-specific enhancements to improve clarity.
        
        Args:
            audio: Audio signal
            
        Returns:
            Enhanced audio signal
        """
        # 1. Pre-emphasis filter to boost high frequencies (typical for speech)
        pre_emphasis = 0.97
        audio_preemph = np.append(audio[0], audio[1:] - pre_emphasis * audio[:-1])
        
        # 2. Apply bandpass filter for speech frequencies (80Hz - 8kHz)
        nyquist = self.target_sr / 2
        low_freq = 80 / nyquist
        high_freq = min(8000 / nyquist, 0.95)  # Ensure below Nyquist
        
        if low_freq < high_freq:
            b, a = signal.butter(4, [low_freq, high_freq], btype='band')
            audio_filtered = signal.filtfilt(b, a, audio_preemph)
        else:
            audio_filtered = audio_preemph
        
        # 3. Dynamic range compression to make quiet speech more audible
        audio_compressed = self._apply_compression(audio_filtered)
        
        return audio_compressed

    def _apply_compression(self, audio: np.ndarray, 
                          threshold: float = -20, 
                          ratio: float = 4.0,
                          attack: float = 0.003,
                          release: float = 0.1) -> np.ndarray:
        """
        Apply dynamic range compression to make quiet sounds more audible.
        
        Args:
            audio: Audio signal
            threshold: Compression threshold in dB
            ratio: Compression ratio
            attack: Attack time in seconds
            release: Release time in seconds
            
        Returns:
            Compressed audio signal
        """
        # Convert to dB
        audio_db = 20 * np.log10(np.abs(audio) + 1e-10)
        
        # Simple compression: reduce gain above threshold
        compressed_db = np.where(
            audio_db > threshold,
            threshold + (audio_db - threshold) / ratio,
            audio_db
        )
        
        # Convert back to linear scale
        gain_reduction = np.power(10, (compressed_db - audio_db) / 20)
        
        # Apply smoothing to avoid clicks
        kernel_size = int(attack * self.target_sr)
        if kernel_size > 1:
            gain_reduction = np.convolve(
                gain_reduction, 
                np.ones(kernel_size) / kernel_size, 
                mode='same'
            )
        
        return audio * gain_reduction

    def _balance_volume_levels(self, audio: np.ndarray) -> np.ndarray:
        """
        Balance volume levels across different sections of audio.
        
        Args:
            audio: Audio signal
            
        Returns:
            Volume-balanced audio signal
        """
        # Divide audio into overlapping windows
        window_size = int(2.0 * self.target_sr)  # 2-second windows
        overlap = window_size // 2
        
        if len(audio) < window_size:
            return audio
        
        balanced_audio = audio.copy()
        
        for i in range(0, len(audio) - window_size, overlap):
            window = audio[i:i + window_size]
            
            # Calculate RMS energy
            rms = np.sqrt(np.mean(window ** 2))
            
            if rms > 0:
                # Target RMS level (adjust as needed)
                target_rms = 0.1
                gain = target_rms / rms
                
                # Limit gain to avoid over-amplification
                gain = np.clip(gain, 0.1, 3.0)
                
                # Apply gain with fade in/out to avoid clicks
                fade_samples = overlap // 4
                gain_envelope = np.ones(window_size)
                
                # Fade in
                if i > 0:
                    gain_envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
                
                # Fade out
                if i + window_size < len(audio):
                    gain_envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
                
                balanced_audio[i:i + window_size] *= gain * gain_envelope
        
        return balanced_audio
    
    def convert_to_wav(self, 
                      input_path: Path, 
                      output_path: Optional[Path] = None) -> Path:
        """
        Convert audio file to WAV format.
        
        Args:
            input_path: Path to input audio file
            output_path: Path for output WAV file (optional)
            
        Returns:
            Path to the converted WAV file
        """
        if output_path is None:
            output_path = input_path.with_suffix('.wav')
        
        # Load audio with original sample rate
        audio, sr = librosa.load(str(input_path), sr=None)
        
        # Save as WAV
        sf.write(str(output_path), audio, sr)
        
        return output_path
    
    def get_audio_info(self, audio_path: Path) -> dict:
        """
        Get information about an audio file.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Dictionary with audio information
        """
        try:
            # Get file info without loading the entire file
            info = sf.info(str(audio_path))
            
            return {
                "duration": info.duration,
                "sample_rate": info.samplerate,
                "channels": info.channels,
                "format": info.format,
                "subtype": info.subtype,
                "file_size_mb": audio_path.stat().st_size / (1024 * 1024)
            }
        except Exception as e:
            return {"error": str(e)}
