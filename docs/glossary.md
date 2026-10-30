# Glossary

Several concepts in this project carry more than one name, because the
code, the command line, the manuscript and older documents were written at
different times, and one word has at times named two different things.
This page fixes one name for each concept. New prose should use the name
in the first column; the aliases remain in code and in older text and
mean the same thing, and renaming them in code would break flags and
committed file names.

## Transcription and privacy

| Use | Aliases still found | In the code | Meaning |
| --- | --- | --- | --- |
| speaker attribution | diarisation, diarization | `--speaker-attribution`; `perform_speaker_diarization`; the `--diarization-*` options, each also accepted as `--diarisation-*`; `python -m preflight --diarisation-required` (alias `--diarization-required`) | Labelling who spoke when, and writing those labels into the transcript. "Diarisation" is the technical term for the step and is used for it, for example in "diarisation error rate". Prose uses the British spelling. The American spelling survives in pyannote model names such as `pyannote/speaker-diarization-3.1` and in the JSON keys below. |
| name masking | masking | `--mask-personal-names`; `create_enhanced_name_masker` | Replacing personal names in the text with `[NAME]`, `[SURNAME]` or `[TITLE]`. |
| dictionary stage | curated names, name database | `data/curated_names.csv`; `source` value `dictionary` | The masking rule that masks a capitalised word found in the name dictionary. |
| NER stage | named-entity stage, GLiNER stage | `ner_masking.py`; `source` value `ner` | The optional masking rule that masks a capitalised word a named-entity model reads as a person. Available through the Python API and `evaluation.benchmark_masking --ner`, not through `transcription.py`. |
| title rule | honorific | `TITLE_WORDS`; `source` value `title` | Masking an honorific such as "Dr" or "Professor" when a capitalised dictionary name follows it, possessive or not ("Dr. Smith's" becomes "[TITLE] [SURNAME]'s"). "Miss" counts only with a capital and "Ms" only so spelt, because "miss", "ms" and "MS" are also other words. The masker's `case_insensitive` parameter also drops the capital required of the name that follows, but leaves these two spelling rules in force. |
| masking log | replacement log, name masking log | `--save-name-masking-logs`; `name_masking_logs/name_replacements_<recording>.csv`; `REPLACEMENT_LOG_FIELDS` | One row per masked word. Its `source` column records which of the three rules above masked it. |
| redacted artefact | redacted parallel, redacted set | `_transcript_redacted.json`, `_transcript_redacted.vtt`; `--redacted-timestamps-only` | A timestamped transcript with the same timings as the raw one and the names masked. |
| audio redaction | bleeping | `audio_redaction.py` | Silencing or bleeping the time spans of masked words in the recording itself. |
| voice anonymisation | McAdams transformation, voice disguise | `voice_anonymisation.py`; `submit_anonymisation.sh` | Warping the voice so that it no longer identifies the speaker, while keeping the words intelligible. It changes the sound, not the words, and is separate from masking and redaction. |
| diarisation model source | provenance source | `pipeline.diarization_model_source` in the transcript JSON | Which route loaded the diarisation pipeline: `local_config` (`--diarization-config`), `local_path` (`--diarization-model-path`), `hf_loader` (the HuggingFace loader), `hf_loader_offline` (the same, cache-only because `HF_HUB_OFFLINE` or `TRANSFORMERS_OFFLINE` is set) or `unavailable`. The same block holds `diarization_model_id`, `diarization_model_revision` and `diarization_sub_model_revisions` (the Hub commits of the pipeline and of the segmentation and embedding models it names, read back from the cache, `null` where it cannot say), `diarization_model_path`, `diarization_offline_mode` and, on failure, `diarization_error`. |
| review flags | confidence flags | `confidence.py`; `<name>_review.json` | Heuristic marks on segments whose shape suggests hallucination or a decoding loop. They are not model confidence. |
| manifest | provenance manifest | `provenance.py`; `<name>_manifest.json` | The list of a run's artefacts with their SHA-256 digests and the run settings. |

## Evaluation

| Use | Aliases still found | In the code | Meaning |
| --- | --- | --- | --- |
| condition | post-processing condition | `evaluation/conditions.py` | One named transformation of the text, scored against the reference. |
| symmetric condition | reference-applied | `apply_to_reference=True` | A condition applied to the reference as well as the hypothesis (`punct_strip`, `case_fold`, `whisper_norm`). |
| hypothesis-only condition | | `apply_to_reference=False` | A condition applied to the hypothesis alone, as every other condition is. |
| language-aware condition | | `language_aware=True` | A condition that receives the transcript language and skips its English-only stages on other languages. At present only `pipeline_full` is. |
| composite | full pipeline, production pipeline, desktop pipeline | `pipeline_full` | Every clean-text stage the workflow applies, in the order it applies them, scored as one condition. |
| clean-text stages | atomic stages | `CLEAN_TEXT_STAGES` in `transcription.py` | The eight stages the composite runs after `unicode_strip` and `repetition_fix`. |
| suite | corpus, benchmark | `evaluation/challenge_suites.py`; `evaluation.sweep --suites` | A named dataset, configuration and split scored by the sweep (for example `librispeech_clean`, `ami`). "Corpus" is kept for the underlying dataset. |
| sweep | condition sweep, WER sweep | `evaluation/sweep.py`; `hpc/submit_sweep.sh` | One decode per suite with every condition scored on the same hypotheses. |
| pooled WER | micro WER, micro-averaged WER | `micro_wer` | Total errors divided by total reference words over all utterances. |
| macro WER | mean WER | `macro_wer` | The mean of the per-utterance (or per-file) word error rates. |
| hypothesis dump | verbatim hypotheses | `--dump-hypotheses`; `DUMP_HYPOTHESES=1`; `wer_hypotheses*.csv` | The reference and the raw and transformed hypothesis of every (utterance, condition) pair, so that a condition can be rescored without decoding again. |
| reconstruction mode | mix mode | `--mix-mode`; `MIX_MODE` | How AMI meetings are rebuilt from per-utterance clips for diarisation scoring: `timeline` (each clip at its original offset, overlaps included, which is the default) or `concat` (clips placed end to end). |
| oracle speaker count | oracle | `--oracle-num-speakers`; `ORACLE_NUM_SPEAKERS=1` | Telling the diarisation pipeline the true number of speakers. It is a setting, not a reconstruction mode. |
| development split | dev, validation | `SPLIT=validation` | The AMI split used to choose diarisation settings. Results are reported on the test split. |
| linkage rate | | `linkage_rate` in `evaluation/benchmark_anonymisation.py` | How often an anonymised utterance's nearest original, by speaker embedding and excluding its own recording, belongs to the same speaker. It is read against the chance level reported with it. |
| level ratio | | `level_ratio` | Mean loudness of the anonymised audio relative to the original, checked because quieter audio alone changes the word error rate. |
| guarded baseline | screened baseline | `degenerate_baselines`; `wer_baseline_guarded` (older name `wer_original_guarded`) | The pooled WER after dropping, from both arms, the utterances on which the recogniser looped on the unmodified audio. Only the baseline is screened. |

## Operations

| Use | Aliases still found | In the code | Meaning |
| --- | --- | --- | --- |
| preflight | environment check, doctor | `python -m preflight` | The environment check: Python, torch and CUDA, transformers, audio decoding, pyannote and the HuggingFace token. |
| trial run | pre-flight, pilot | `SWEEP_LIMIT`, `WER_ML_LIMIT`, `LIMIT`; the `preflight` and `preflight_ml` output directories in the script headers | A job run on a few utterances to check it end to end before the full run. Some script headers call this a "pre-flight", which has nothing to do with `python -m preflight`. |
| run record | | `hpc/runs/*.env` | The environment overrides and ARC job ID behind a committed result. |
| environment record | | `arc_record_env` in `hpc/common/arc_common.sh`; `environment/` beside a job's results | What a job ran with: Python stack, modules, GPU and git commit. |
