#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Speaker Attribution System
Improves speaker-text alignment using raw diarization timing
"""

import re
import json
from typing import List, Dict, Tuple
from pathlib import Path
import numpy as np

class EnhancedSpeakerAttribution:
    """Enhanced speaker attribution that uses raw diarization timing more effectively."""
    
    def __init__(self):
        self.debug = True
    
    def improve_speaker_attribution(self, transcription_file: str, output_file: str = None):
        """
        Improve speaker attribution using raw diarization timing.
        
        Args:
            transcription_file: Path to transcription file with both sections
            output_file: Optional output file path
            
        Returns:
            Improved transcription text
        """
        with open(transcription_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse the existing sections
        speaker_attributed_text, raw_diarization = self._parse_transcription_file(content)
        
        if not raw_diarization:
            print("❌ No raw diarization found")
            return content
        
        # Extract the full transcription text (first part)
        full_text = self._extract_full_transcription(content)
        
        # Create improved speaker attribution
        improved_attribution = self._create_improved_attribution(
            full_text, raw_diarization
        )
        
        # Create improved output
        improved_content = self._format_improved_output(
            full_text, improved_attribution, raw_diarization
        )
        
        # Save if requested
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(improved_content)
            print(f"✅ Improved transcription saved: {output_file}")
        
        return improved_content
    
    def _parse_transcription_file(self, content: str) -> Tuple[List[Dict], List[Dict]]:
        """Parse the transcription file to extract both sections."""
        
        # Find SPEAKER-ATTRIBUTED TRANSCRIPTION section
        speaker_pattern = r'\[(\d+\.\d+)s -> (\d+\.\d+)s\] (SPEAKER_\d+): (.+)'
        speaker_matches = re.findall(speaker_pattern, content)
        
        speaker_attributed = []
        for match in speaker_matches:
            speaker_attributed.append({
                'start': float(match[0]),
                'end': float(match[1]),
                'speaker': match[2],
                'text': match[3].strip()
            })
        
        # Find RAW SPEAKER DIARIZATION section
        raw_pattern = r'\[(\d+\.\d+)s -> (\d+\.\d+)s\] (SPEAKER_\d+)'
        raw_matches = re.findall(raw_pattern, content)
        
        raw_diarization = []
        for match in raw_matches:
            raw_diarization.append({
                'start': float(match[0]),
                'end': float(match[1]),
                'speaker': match[2]
            })
        
        print(f"📊 Parsed: {len(speaker_attributed)} attributed segments, {len(raw_diarization)} raw segments")
        
        return speaker_attributed, raw_diarization
    
    def _extract_full_transcription(self, content: str) -> str:
        """Extract the full transcription text from the beginning of the file."""
        lines = content.split('\n')
        full_text_lines = []
        
        for line in lines:
            if line.strip() == "SPEAKER-ATTRIBUTED TRANSCRIPTION:":
                break
            if line.strip():  # Skip empty lines
                full_text_lines.append(line.strip())
        
        full_text = ' '.join(full_text_lines)
        
        # Clean up common transcription issues
        full_text = self._clean_transcription_text(full_text)
        
        print(f"📝 Extracted full text: {len(full_text)} characters")
        
        return full_text
    
    def _clean_transcription_text(self, text: str) -> str:
        """Clean up common transcription issues."""
        
        # Remove excessive "undefined" words
        text = re.sub(r'\bundefined\b', '', text)
        text = re.sub(r'\bundefin\b', '', text)
        text = re.sub(r'\bundefine\b', '', text)
        
        # Fix spacing issues
        text = re.sub(r'\s+', ' ', text)  # Multiple spaces to single space
        text = text.strip()
        
        # Fix common speech recognition errors
        replacements = {
            ' um ': ' uhm ',
            ' uh ': ' uhm ',
            ' youre ': ' you\'re ',
            ' dont ': ' don\'t ',
            ' cant ': ' can\'t ',
            ' wont ': ' won\'t ',
            ' theyre ': ' they\'re ',
            ' thats ': ' that\'s ',
            ' its ': ' it\'s ',
            ' im ': ' I\'m ',
            ' id ': ' I\'d ',
            ' youve ': ' you\'ve ',
            ' ive ': ' I\'ve ',
            ' isnt ': ' isn\'t ',
            ' wasnt ': ' wasn\'t ',
            ' werent ': ' weren\'t ',
            ' didnt ': ' didn\'t ',
            ' couldnt ': ' couldn\'t ',
            ' wouldnt ': ' wouldn\'t ',
            ' shouldnt ': ' shouldn\'t ',
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        return text
    
    def _create_improved_attribution(self, full_text: str, raw_diarization: List[Dict]) -> List[Dict]:
        """Create improved speaker attribution using raw timing."""
        
        print("🔧 Creating improved speaker attribution...")
        
        # Estimate text timing based on character position and total duration
        if not raw_diarization:
            return []
        
        total_duration = max([seg['end'] for seg in raw_diarization])
        text_length = len(full_text)
        
        # Split text into sentences for better attribution
        sentences = self._split_into_sentences(full_text)
        
        # Calculate timing for each sentence
        sentence_timings = self._estimate_sentence_timings(sentences, total_duration)
        
        # Attribute sentences to speakers based on raw diarization
        attributed_segments = []
        
        for i, (sentence, start_time, end_time) in enumerate(sentence_timings):
            if not sentence.strip():
                continue
            
            # Find the most appropriate speaker for this time segment
            speaker = self._find_speaker_for_time_segment(start_time, end_time, raw_diarization)
            
            attributed_segments.append({
                'start': start_time,
                'end': end_time,
                'speaker': speaker,
                'text': sentence.strip(),
                'sentence_index': i
            })
        
        # Merge consecutive segments from the same speaker
        merged_segments = self._merge_consecutive_same_speaker(attributed_segments)
        
        print(f"✅ Created {len(merged_segments)} improved speaker segments")
        
        # Print speaker distribution
        self._print_speaker_summary(merged_segments)
        
        return merged_segments
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences for better speaker attribution."""
        
        # Simple sentence splitting based on punctuation and pauses
        sentences = []
        
        # Split on sentence endings and common pause indicators
        parts = re.split(r'[.!?]+\s+|uhm\s+|um\s+|\s+and\s+uhm\s+|\s+so\s+|\s+but\s+', text)
        
        for part in parts:
            part = part.strip()
            if len(part) > 10:  # Minimum sentence length
                sentences.append(part)
        
        return sentences
    
    def _estimate_sentence_timings(self, sentences: List[str], total_duration: float) -> List[Tuple[str, float, float]]:
        """Estimate timing for each sentence based on text length."""
        
        total_chars = sum(len(s) for s in sentences)
        if total_chars == 0:
            return []
        
        sentence_timings = []
        current_time = 0.0
        
        for sentence in sentences:
            # Estimate duration based on character count (roughly 15 chars per second for speech)
            estimated_duration = len(sentence) / 15.0
            
            # Scale to fit total duration
            scaled_duration = estimated_duration * (total_duration / (total_chars / 15.0))
            
            end_time = min(current_time + scaled_duration, total_duration)
            
            sentence_timings.append((sentence, current_time, end_time))
            
            current_time = end_time
        
        return sentence_timings
    
    def _find_speaker_for_time_segment(self, start_time: float, end_time: float, raw_diarization: List[Dict]) -> str:
        """Find the most appropriate speaker for a time segment."""
        
        # Find all overlapping diarization segments
        overlapping_segments = []
        
        for seg in raw_diarization:
            # Check for overlap
            overlap_start = max(start_time, seg['start'])
            overlap_end = min(end_time, seg['end'])
            
            if overlap_start < overlap_end:  # There is overlap
                overlap_duration = overlap_end - overlap_start
                overlapping_segments.append({
                    'speaker': seg['speaker'],
                    'overlap_duration': overlap_duration,
                    'start': seg['start'],
                    'end': seg['end']
                })
        
        if not overlapping_segments:
            # No overlap found, find the nearest speaker
            nearest = min(raw_diarization, 
                         key=lambda x: min(abs(x['start'] - start_time), abs(x['end'] - end_time)))
            return nearest['speaker']
        
        # Return speaker with most overlap
        best_speaker = max(overlapping_segments, key=lambda x: x['overlap_duration'])
        return best_speaker['speaker']
    
    def _merge_consecutive_same_speaker(self, segments: List[Dict]) -> List[Dict]:
        """Merge consecutive segments from the same speaker."""
        
        if not segments:
            return []
        
        merged = []
        current_segment = segments[0].copy()
        
        for i in range(1, len(segments)):
            next_segment = segments[i]
            
            # Check if same speaker and close in time (within 2 seconds)
            if (current_segment['speaker'] == next_segment['speaker'] and 
                abs(current_segment['end'] - next_segment['start']) < 2.0):
                
                # Merge segments
                current_segment['end'] = next_segment['end']
                current_segment['text'] += ' ' + next_segment['text']
            else:
                # Different speaker or too far apart
                merged.append(current_segment)
                current_segment = next_segment.copy()
        
        # Add the last segment
        merged.append(current_segment)
        
        return merged
    
    def _print_speaker_summary(self, segments: List[Dict]):
        """Print summary of speaker distribution."""
        
        speaker_stats = {}
        
        for seg in segments:
            speaker = seg['speaker']
            if speaker not in speaker_stats:
                speaker_stats[speaker] = {'count': 0, 'duration': 0.0}
            
            speaker_stats[speaker]['count'] += 1
            speaker_stats[speaker]['duration'] += seg['end'] - seg['start']
        
        print("📋 Improved speaker attribution summary:")
        for speaker, stats in sorted(speaker_stats.items()):
            print(f"   {speaker}: {stats['count']} segments, {stats['duration']:.1f}s total")
