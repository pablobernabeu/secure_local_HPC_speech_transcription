#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Audio Processor with Intelligent Volume Normalization
Designed specifically for interview/speech transcription quality improvement
"""

import numpy as np
import librosa
import soundfile as sf
from scipy import signal
from scipy.ndimage import median_filter
import warnings
from pathlib import Path

class EnhancedAudioProcessor:
    """Enhanced audio processor focused on speech clarity without over-processing."""
    
    def __init__(self, target_sr=16000):
        self.target_sr = target_sr
        
    def enhance_for_transcription(self, audio_path, output_path=None, preset="interview_clarity"):
        """
        Enhanced audio processing specifically designed for better transcription quality.
        
        Args:
            audio_path: Path to input audio file
            output_path: Optional path to save enhanced audio
            preset: Enhancement preset ('interview_clarity', 'gentle', 'minimal')
            
        Returns:
            Tuple of (enhanced_audio, sample_rate)
        """
        print(f"🎵 Loading audio: {audio_path}")
        
        # Load audio
        try:
            audio, sr = librosa.load(audio_path, sr=None)
            print(f"📊 Original: {len(audio)} samples, {sr}Hz, {len(audio)/sr:.1f}s")
        except Exception as e:
            raise ValueError(f"Failed to load audio: {e}")
            
        # Apply preset-based enhancement
        if preset == "interview_clarity":
            enhanced_audio = self._interview_clarity_preset(audio, sr)
        elif preset == "gentle":
            enhanced_audio = self._gentle_preset(audio, sr)
        elif preset == "minimal":
            enhanced_audio = self._minimal_preset(audio, sr)
        else:
            raise ValueError(f"Unknown preset: {preset}")
        
        # Resample if needed
        if sr != self.target_sr:
            enhanced_audio = librosa.resample(enhanced_audio, orig_sr=sr, target_sr=self.target_sr)
            sr = self.target_sr
            print(f"🔄 Resampled to {self.target_sr}Hz")
        
        # Save enhanced audio if requested
        if output_path:
            sf.write(output_path, enhanced_audio, sr)
            print(f"💾 Enhanced audio saved: {output_path}")
            
        return enhanced_audio, sr
    
    def _interview_clarity_preset(self, audio, sr):
        """Interview clarity preset with intelligent volume and speech enhancement."""
        print("🎯 Applying interview_clarity preset...")
        
        # Step 1: Intelligent volume normalization
        audio = self.intelligent_normalize(audio)
        
        # Step 2: Gentle high-pass filter to remove low-frequency noise
        audio = self.gentle_highpass_filter(audio, sr, cutoff=80)
        
        # Step 3: Intelligent noise reduction
        audio = self.intelligent_noise_reduction(audio, sr)
        
        # Step 4: Speech frequency boost
        audio = self.speech_frequency_boost(audio, sr)
        
        # Step 5: Gentle compression for consistent levels
        audio = self.gentle_compression(audio)
        
        print("✅ Interview clarity enhancement completed")
        return audio
    
    def _gentle_preset(self, audio, sr):
        """Gentle enhancement preset."""
        print("🎯 Applying gentle preset...")
        
        # Minimal processing
        audio = self.intelligent_normalize(audio, target_rms=0.12)
        audio = self.gentle_highpass_filter(audio, sr, cutoff=60)
        audio = self.gentle_compression(audio, ratio=2.0)
        
        return audio
    
    def _minimal_preset(self, audio, sr):
        """Minimal enhancement preset."""
        print("🎯 Applying minimal preset...")
        
        # Only volume normalization
        audio = self.intelligent_normalize(audio, target_rms=0.15)
        
        return audio
    
    def intelligent_normalize(self, audio, target_rms=0.1):
        """
        Intelligent volume normalization that preserves dynamics.
        
        Args:
            audio: Input audio signal
            target_rms: Target RMS level (0.05-0.2)
            
        Returns:
            Normalized audio
        """
        print(f"🔧 Intelligent volume normalization (target RMS: {target_rms})")
        
        # Calculate current RMS
        current_rms = np.sqrt(np.mean(audio**2))
        
        if current_rms < 1e-6:  # Very quiet audio
            print("⚠️  Very quiet audio detected")
            return audio
            
        # Calculate gain with limiting
        gain = target_rms / current_rms
        gain = min(gain, 10.0)  # Limit maximum gain to prevent over-amplification
        
        # Apply gain
        normalized = audio * gain
        
        # Soft limiting to prevent clipping
        normalized = np.tanh(normalized * 0.95) * 0.95
        
        final_rms = np.sqrt(np.mean(normalized**2))
        print(f"📈 Volume: {current_rms:.4f} → {final_rms:.4f} RMS (gain: {gain:.2f}x)")
        
        return normalized
    
    def gentle_highpass_filter(self, audio, sr, cutoff=80):
        """
        Gentle high-pass filter to remove low-frequency noise.
        
        Args:
            audio: Input audio signal
            sr: Sample rate
            cutoff: Cutoff frequency in Hz
            
        Returns:
            Filtered audio
        """
        print(f"🔧 High-pass filter (cutoff: {cutoff}Hz)")
        
        # Design a gentle Butterworth filter
        nyquist = sr / 2
        normalized_cutoff = cutoff / nyquist
        
        # Use a lower order for gentler filtering
        b, a = signal.butter(2, normalized_cutoff, btype='high')
        
        # Apply filter
        filtered = signal.filtfilt(b, a, audio)
        
        return filtered
    
    def intelligent_noise_reduction(self, audio, sr, strength=0.3):
        """
        Intelligent noise reduction using spectral gating.
        
        Args:
            audio: Input audio signal
            sr: Sample rate
            strength: Noise reduction strength (0.0-1.0)
            
        Returns:
            Noise-reduced audio
        """
        print(f"🔧 Intelligent noise reduction (strength: {strength})")
        
        # Use STFT for frequency domain processing
        stft = librosa.stft(audio, hop_length=512, n_fft=2048)
        magnitude = np.abs(stft)
        phase = np.angle(stft)
        
        # Estimate noise floor from quiet segments
        power = magnitude**2
        noise_floor = np.percentile(power, 10, axis=1, keepdims=True)
        
        # Create spectral gate
        gate = np.minimum(1.0, power / (noise_floor * (1 + strength * 10)))
        gate = gate**0.5  # Square root for gentler reduction
        
        # Apply gate
        magnitude_clean = magnitude * gate
        
        # Reconstruct signal
        stft_clean = magnitude_clean * np.exp(1j * phase)
        audio_clean = librosa.istft(stft_clean, hop_length=512)
        
        return audio_clean
    
    def speech_frequency_boost(self, audio, sr, boost_db=3):
        """
        Boost speech frequencies (300-3400 Hz) for better transcription.
        
        Args:
            audio: Input audio signal
            sr: Sample rate
            boost_db: Boost amount in dB
            
        Returns:
            Frequency-boosted audio
        """
        print(f"🔧 Speech frequency boost ({boost_db}dB, 300-3400Hz)")
        
        # Design bandpass filter for speech frequencies
        nyquist = sr / 2
        low_freq = 300 / nyquist
        high_freq = min(3400 / nyquist, 0.95)  # Avoid Nyquist frequency
        
        # Create boost filter
        b, a = signal.butter(4, [low_freq, high_freq], btype='band')
        
        # Extract speech band
        speech_band = signal.filtfilt(b, a, audio)
        
        # Apply boost
        boost_factor = 10**(boost_db / 20)
        boosted_speech = speech_band * (boost_factor - 1)
        
        # Add boosted speech back to original
        enhanced = audio + boosted_speech
        
        # Prevent clipping
        max_val = np.max(np.abs(enhanced))
        if max_val > 0.95:
            enhanced = enhanced * (0.95 / max_val)
        
        return enhanced
    
    def gentle_compression(self, audio, ratio=3.0, threshold=0.7):
        """
        Gentle dynamic range compression for consistent levels.
        
        Args:
            audio: Input audio signal
            ratio: Compression ratio
            threshold: Compression threshold (0-1)
            
        Returns:
            Compressed audio
        """
        print(f"🔧 Gentle compression (ratio: {ratio}:1, threshold: {threshold})")
        
        # Calculate envelope
        envelope = np.abs(audio)
        
        # Smooth envelope
        envelope_smooth = signal.savgol_filter(envelope, 
                                             window_length=min(1001, len(envelope)//10*2+1), 
                                             polyorder=3)
        
        # Apply compression
        gain = np.ones_like(envelope_smooth)
        over_threshold = envelope_smooth > threshold
        
        if np.any(over_threshold):
            excess = envelope_smooth[over_threshold] - threshold
            compressed_excess = excess / ratio
            gain[over_threshold] = (threshold + compressed_excess) / envelope_smooth[over_threshold]
        
        # Smooth gain changes
        gain_smooth = signal.savgol_filter(gain, 
                                         window_length=min(501, len(gain)//20*2+1), 
                                         polyorder=2)
        
        # Apply gain
        compressed = audio * gain_smooth
        
        return compressed


def main():
    """Test the enhanced audio processor."""
    print("🎵 Enhanced Audio Processor Test")
    print("=" * 32)
    
    # Test with a sample file
    test_file = "audio_input/Interview 1.WAV"
    
    if Path(test_file).exists():
        processor = EnhancedAudioProcessor()
        
        # Test interview clarity preset
        enhanced_audio, sr = processor.enhance_for_transcription(
            test_file, 
            output_path="enhanced_interview_test.wav",
            preset="interview_clarity"
        )
        
        print(f"\n✅ Enhancement completed!")
        print(f"📊 Enhanced audio: {len(enhanced_audio)} samples at {sr}Hz")
        
    else:
        print(f"❌ Test file not found: {test_file}")


if __name__ == "__main__":
    main()
