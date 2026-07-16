## ADDED Requirements

### Requirement: Silence Skipping Via Voice Activity Detection

The system SHALL apply faster-whisper's built-in Silero voice activity detection (vad_filter) during transcription by default, skipping silent portions of the recording to reduce transcription time and suppress hallucinated text in silence. The system SHALL allow disabling VAD through the VAD_FILTER environment variable, and segment timestamps SHALL remain on the original audio timeline so progress reporting stays valid.

#### Scenario: VAD enabled by default

- **WHEN** a recording is transcribed with no VAD_FILTER setting present in the environment
- **THEN** the transcription worker SHALL run with vad_filter enabled using the library's default VAD parameters

#### Scenario: VAD disabled via environment variable

- **WHEN** VAD_FILTER is set to false in the configuration
- **THEN** the transcription worker SHALL run without VAD filtering, processing the full audio including silence

#### Scenario: Progress reporting remains valid with VAD

- **WHEN** VAD skips silent portions during transcription
- **THEN** reported segment timestamps SHALL remain on the original audio timeline, and the progress percentage SHALL never exceed 100
