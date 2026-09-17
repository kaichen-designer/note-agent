## ADDED Requirements

### Requirement: Segment Timestamp Preservation On Request

The system SHALL support an opt-in mode in which transcription returns the per-segment start and end timestamps produced by the underlying speech recognition model, in addition to the assembled transcript text, when the caller explicitly requests it. When not requested, the system SHALL behave exactly as it does today and SHALL NOT return segment timestamps.

#### Scenario: Segment timestamps requested

- **WHEN** transcription is invoked with segment timestamp preservation enabled
- **THEN** the result SHALL include the assembled transcript text and a list of segments, each carrying its start time, end time, and text, on the original audio timeline

#### Scenario: Segment timestamps not requested

- **WHEN** transcription is invoked without segment timestamp preservation enabled
- **THEN** the result SHALL contain only the assembled transcript text, with no segment list, identical to the existing behavior

#### Scenario: Segment timestamps remain valid alongside VAD

- **WHEN** segment timestamp preservation is enabled and VAD silence skipping is also enabled
- **THEN** each returned segment's start and end times SHALL remain on the original, untrimmed audio timeline

---
### Requirement: Segment Speaker Labels When Diarization Enabled

The system SHALL include a speaker label on each preserved segment when segment timestamp preservation and speaker diarization are both enabled for the same transcription, using the same speaker letter assignment already produced for the plain-text diarized transcript. When diarization is not enabled, or fails and falls back to a plain transcript, preserved segments SHALL NOT carry a speaker label.

#### Scenario: Both segment preservation and diarization enabled

- **WHEN** transcription is invoked with segment timestamp preservation and speaker diarization both enabled, and diarization succeeds
- **THEN** each returned segment SHALL carry a speaker label matching the speaker prefix used for that portion of the plain-text diarized transcript

#### Scenario: Segment preservation enabled without diarization

- **WHEN** transcription is invoked with segment timestamp preservation enabled and speaker diarization not enabled
- **THEN** returned segments SHALL NOT carry a speaker label, identical to the behavior before this requirement existed

#### Scenario: Diarization fails while segment preservation is enabled

- **WHEN** segment timestamp preservation is enabled and diarization is enabled but fails
- **THEN** returned segments SHALL NOT carry a speaker label, and the failure SHALL NOT prevent segments from being returned
