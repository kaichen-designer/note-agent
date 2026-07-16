# local-transcription Specification

## Purpose

TBD - created by archiving change 'recording-to-notion-agent'. Update Purpose after archive.

## Requirements

### Requirement: Local GPU-Accelerated Transcription

The system SHALL transcribe recording files using a locally-run faster-whisper large-v3 model with GPU acceleration, and SHALL NOT upload audio content to any external transcription service.

#### Scenario: Successful transcription produces transcript text

- **WHEN** a stable recording file is submitted for transcription
- **THEN** the system SHALL produce a text transcript of the recording's spoken content without transmitting the audio file to a third-party API

---
### Requirement: Transcription Progress Reporting

The system SHALL report transcription progress to a local progress file while a recording is being transcribed, including the source filename, audio duration, seconds processed so far, and percentage complete, and SHALL provide a user-facing viewer script that displays this progress live regardless of whether the run was triggered by the scheduler or manually.

#### Scenario: Progress is visible during a long transcription

- **WHEN** a recording is being transcribed and the user opens the progress viewer
- **THEN** the viewer SHALL display the file being transcribed and a percentage that advances as transcription proceeds

#### Scenario: Viewer indicates idle state

- **WHEN** no transcription is currently running and the user opens the progress viewer
- **THEN** the viewer SHALL indicate that no transcription is in progress instead of showing stale progress

---
### Requirement: Transcription Failure Handling

The system SHALL mark a file's state as "failed" with a recorded error reason when transcription fails, and SHALL continue processing other pending files without interruption.

#### Scenario: Corrupted audio file does not halt pipeline

- **WHEN** the transcription step raises an error for one recording file (for example, a corrupted or unsupported audio format)
- **THEN** the system SHALL record the failure reason for that file, leave its status as failed, and proceed to process remaining pending files in the same run

---
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
