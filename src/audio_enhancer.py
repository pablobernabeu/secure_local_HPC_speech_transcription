#!/usr/bin/env python3
"""
Audio Enhancement Module for Speech Transcription Pipeline

This module provides audio preprocessing capabilities including:
- Volume normalisation
- Noise reduction  
- High-pass filtering
- Audio quality assessment

British English coding style, following PEP 8.
"""

import numpy as np
import librosa
import scipy.signal
from scipy.io import wavfile
import soundfile as sf
from pathlib import Path
import logging
from typing import Tuple, Optional, Dict, Any
import warnings

# Suppress warnings from audio processing libraries
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger(__name__)


class AudioEnhancer:
    """
    Audio enhancement processor for speech transcription optimisation.
    
    Provides various audio preprocessing techniques to improve transcription
    accuracy whilst maintaining audio quality for speaker diarisation.
    """
    
    def __init__(self, 
                 target_rms: float = 0.1,
                 noise_reduction_strength: float = 0.5,
                 highpass_cutoff: float = 80.0,
                 lowpass_cutoff: Optional[float] = None):
        """
        Initialise audio enhancer with processing parameters.
        
        Args:
            target_rms: Target RMS level for volume normalisation (0.05-0.2)
            noise_reduction_strength: Noise reduction intensity (0.0-1.0)
            highpass_cutoff: High-pass filter cutoff frequency in Hz
            lowpass_cutoff: Low-pass filter cutoff frequency in Hz (optional)
        """
        self.target_rms = target_rms
        self.noise_reduction_strength = noise_reduction_strength
        self.highpass_cutoff = highpass_cutoff
        self.lowpass_cutoff = lowpass_cutoff
        
        logger.info(f"AudioEnhancer initialised with target_rms={target_rms}, "
                   f"noise_reduction={noise_reduction_strength}")
    
    def assess_audio_quality(self, 
                           audio: np.ndarray, 
                           sample_rate: int) -> Dict[str, float]:
        """
        Assess various audio quality metrics.
        
        Args:
            audio: Audio signal as numpy array
            sample_rate: Sample rate in Hz
            
        Returns:
            Dictionary containing quality metrics
        """
        metrics = {}
        
        # RMS level
        metrics['rms_level'] = np.sqrt(np.mean(audio**2))
        
        # Peak level
        metrics['peak_level'] = np.max(np.abs(audio))
        
        # Dynamic range (difference between peak and RMS in dB)
        if metrics['rms_level'] > 0:
            metrics['dynamic_range_db'] = 20 * np.log10(
                metrics['peak_level'] / metrics['rms_level']
            )
        else:
            metrics['dynamic_range_db'] = float('inf')
        
        # Zero crossing rate (indicator of noise/speech content)
        zero_crossings = np.where(np.diff(np.signbit(audio)))[0]
        metrics['zero_crossing_rate'] = len(zero_crossings) / len(audio)
        
        # Spectral centroid (brightness measure)
        stft = librosa.stft(audio)
        spectral_centroids = librosa.feature.spectral_centroid(
            S=np.abs(stft), sr=sample_rate
        )
        metrics['spectral_centroid_hz'] = np.mean(spectral_centroids)
        
        return metrics
    
    def normalise_volume(self, 
                        audio: np.ndarray, 
                        target_rms: Optional[float] = None) -> np.ndarray:
        """
        Normalise audio volume to target RMS level.
        
        Args:
            audio: Input audio signal
            target_rms: Target RMS level (uses instance default if None)
            
        Returns:
            Volume-normalised audio
        """
        if target_rms is None:
            target_rms = self.target_rms
            
        current_rms = np.sqrt(np.mean(audio**2))
        
        if current_rms == 0:
            logger.warning("Audio signal has zero RMS - cannot normalise")
            return audio
            
        gain = target_rms / current_rms
        
        # Prevent clipping
        normalised = audio * gain
        peak = np.max(np.abs(normalised))
        if peak > 0.95:  # Leave some headroom
            gain = gain * (0.95 / peak)
            normalised = audio * gain
            
        logger.debug(f"Volume normalisation: gain={gain:.3f}, "
                    f"RMS {current_rms:.4f} -> {np.sqrt(np.mean(normalised**2)):.4f}")
        
        return normalised
    
    def apply_highpass_filter(self, 
                             audio: np.ndarray, 
                             sample_rate: int,
                             cutoff: Optional[float] = None) -> np.ndarray:
        """
        Apply high-pass filter to remove low-frequency noise.
        
        Args:
            audio: Input audio signal
            sample_rate: Sample rate in Hz
            cutoff: Cutoff frequency in Hz (uses instance default if None)
            
        Returns:
            Filtered audio
        """
        if cutoff is None:
            cutoff = self.highpass_cutoff
            
        # Design Butterworth high-pass filter
        nyquist = sample_rate / 2
        normalised_cutoff = cutoff / nyquist
        
        # Ensure cutoff is valid
        if normalised_cutoff >= 1.0:
            logger.warning(f"High-pass cutoff {cutoff} Hz too high for "
                          f"sample rate {sample_rate} Hz")
            return audio
            
        b, a = scipy.signal.butter(4, normalised_cutoff, btype='high')
        filtered = scipy.signal.filtfilt(b, a, audio)
        
        logger.debug(f"Applied high-pass filter at {cutoff} Hz")
        
        return filtered
    
    def apply_lowpass_filter(self, 
                            audio: np.ndarray, 
                            sample_rate: int,
                            cutoff: float) -> np.ndarray:
        """
        Apply low-pass filter to remove high-frequency noise.
        
        Args:
            audio: Input audio signal
            sample_rate: Sample rate in Hz
            cutoff: Cutoff frequency in Hz
            
        Returns:
            Filtered audio
        """
        # Design Butterworth low-pass filter
        nyquist = sample_rate / 2
        normalised_cutoff = cutoff / nyquist
        
        if normalised_cutoff >= 1.0:
            logger.warning(f"Low-pass cutoff {cutoff} Hz too high for "
                          f"sample rate {sample_rate} Hz")
            return audio
            
        b, a = scipy.signal.butter(4, normalised_cutoff, btype='low')
        filtered = scipy.signal.filtfilt(b, a, audio)
        
        logger.debug(f"Applied low-pass filter at {cutoff} Hz")
        
        return filtered
    
    def reduce_noise_spectral_subtraction(self, 
                                        audio: np.ndarray,
                                        sample_rate: int,
                                        strength: Optional[float] = None) -> np.ndarray:
        """
        Apply spectral subtraction noise reduction.
        
        This method estimates noise from quiet segments and subtracts it
        from the entire signal.
        
        Args:
            audio: Input audio signal
            sample_rate: Sample rate in Hz
            strength: Noise reduction strength (uses instance default if None)
            
        Returns:
            Noise-reduced audio
        """
        if strength is None:
            strength = self.noise_reduction_strength
            
        if strength == 0:
            return audio
            
        # STFT parameters
        n_fft = 2048
        hop_length = 512
        
        # Compute STFT
        stft = librosa.stft(audio, n_fft=n_fft, hop_length=hop_length)
        magnitude = np.abs(stft)
        phase = np.angle(stft)
        
        # Estimate noise from quietest 10% of frames
        frame_energy = np.sum(magnitude**2, axis=0)
        noise_threshold = np.percentile(frame_energy, 10)
        noise_frames = frame_energy < noise_threshold
        
        if np.sum(noise_frames) > 0:
            # Estimate noise spectrum
            noise_spectrum = np.mean(magnitude[:, noise_frames], axis=1, keepdims=True)
            
            # Apply spectral subtraction
            enhanced_magnitude = magnitude - strength * noise_spectrum
            
            # Ensure we don't go below 10% of original magnitude
            enhanced_magnitude = np.maximum(
                enhanced_magnitude, 
                0.1 * magnitude
            )
        else:
            enhanced_magnitude = magnitude
            
        # Reconstruct signal
        enhanced_stft = enhanced_magnitude * np.exp(1j * phase)
        enhanced_audio = librosa.istft(
            enhanced_stft, 
            hop_length=hop_length, 
            length=len(audio)
        )
        
        logger.debug(f"Applied spectral subtraction with strength {strength}")
        
        return enhanced_audio
    
    def enhance_audio(self, 
                     audio: np.ndarray, 
                     sample_rate: int,
                     enable_volume_normalisation: bool = True,
                     enable_noise_reduction: bool = True,
                     enable_filtering: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Apply full audio enhancement pipeline.
        
        Args:
            audio: Input audio signal
            sample_rate: Sample rate in Hz
            enable_volume_normalisation: Whether to normalise volume
            enable_noise_reduction: Whether to apply noise reduction
            enable_filtering: Whether to apply filtering
            
        Returns:
            Tuple of (enhanced_audio, processing_info)
        """
        processing_info = {
            'original_quality': self.assess_audio_quality(audio, sample_rate),
            'steps_applied': []
        }
        
        enhanced = audio.copy()
        
        # Apply high-pass filtering first
        if enable_filtering and self.highpass_cutoff > 0:
            enhanced = self.apply_highpass_filter(enhanced, sample_rate)
            processing_info['steps_applied'].append('highpass_filter')
            
        # Apply low-pass filtering if specified
        if enable_filtering and self.lowpass_cutoff:
            enhanced = self.apply_lowpass_filter(enhanced, sample_rate, 
                                               self.lowpass_cutoff)
            processing_info['steps_applied'].append('lowpass_filter')
            
        # Apply noise reduction
        if enable_noise_reduction and self.noise_reduction_strength > 0:
            enhanced = self.reduce_noise_spectral_subtraction(enhanced, sample_rate)
            processing_info['steps_applied'].append('noise_reduction')
            
        # Apply volume normalisation last
        if enable_volume_normalisation:
            enhanced = self.normalise_volume(enhanced)
            processing_info['steps_applied'].append('volume_normalisation')
            
        # Assess final quality
        processing_info['enhanced_quality'] = self.assess_audio_quality(
            enhanced, sample_rate
        )
        
        logger.info(f"Audio enhancement complete. Applied: "
                   f"{', '.join(processing_info['steps_applied'])}")
        
        return enhanced, processing_info
    
    def process_file(self, 
                    input_path: Path, 
                    output_path: Path,
                    **enhancement_kwargs) -> Dict[str, Any]:
        """
        Process an audio file with enhancement pipeline.
        
        Args:
            input_path: Path to input audio file
            output_path: Path to save enhanced audio
            **enhancement_kwargs: Arguments passed to enhance_audio()
            
        Returns:
            Processing information dictionary
        """
        logger.info(f"Processing audio file: {input_path}")
        
        # Load audio file
        try:
            audio, sample_rate = librosa.load(str(input_path), sr=None, mono=True)
        except Exception as e:
            logger.error(f"Failed to load audio file {input_path}: {e}")
            raise
            
        # Apply enhancement
        enhanced_audio, processing_info = self.enhance_audio(
            audio, sample_rate, **enhancement_kwargs
        )
        
        # Save enhanced audio
        try:
            sf.write(str(output_path), enhanced_audio, sample_rate)
            logger.info(f"Enhanced audio saved to: {output_path}")
        except Exception as e:
            logger.error(f"Failed to save enhanced audio to {output_path}: {e}")
            raise
            
        # Add file information
        processing_info.update({
            'input_file': str(input_path),
            'output_file': str(output_path),
            'sample_rate': sample_rate,
            'duration_seconds': len(audio) / sample_rate
        })
        
        return processing_info


def main():
    """Example usage of AudioEnhancer."""
    
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # Example: enhance an audio file
    enhancer = AudioEnhancer(
        target_rms=0.1,
        noise_reduction_strength=0.3,
        highpass_cutoff=85.0
    )
    
    input_file = Path("audio_input/Interview 1.WAV")
    output_file = Path("enhanced_audio/Interview 1_enhanced.WAV")
    
    if input_file.exists():
        output_file.parent.mkdir(exist_ok=True)
        
        processing_info = enhancer.process_file(input_file, output_file)
        
        print("🎵 Audio Enhancement Complete!")
        print(f"   Input:  {processing_info['input_file']}")
        print(f"   Output: {processing_info['output_file']}")
        print(f"   Steps:  {', '.join(processing_info['steps_applied'])}")
        
        original = processing_info['original_quality']
        enhanced = processing_info['enhanced_quality']
        
        print(f"   Original RMS: {original['rms_level']:.4f}")
        print(f"   Enhanced RMS: {enhanced['rms_level']:.4f}")
    else:
        print(f"❌ Input file not found: {input_file}")


if __name__ == "__main__":
    main()
