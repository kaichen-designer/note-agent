## ADDED Requirements

### Requirement: Video Container Recording Support

The system SHALL recognize files with the `.mkv` extension found in the watch folder as processable recording files, and SHALL apply the same stability detection, transcription, structuring, Notion-write, failed-file retry, and processed-file archiving rules to them as to the existing supported audio extensions.

#### Scenario: Stable MKV file is included for processing

- **WHEN** a scan finds a file with extension `.mkv` that passes the two-pass stability check
- **THEN** the system SHALL include the file in the set of files to process through the same scan-transcribe-structure-write pipeline used for supported audio files

#### Scenario: Successfully processed MKV file is archived

- **WHEN** a `.mkv` file's Notion page is created successfully
- **THEN** the system SHALL move the file into the 已處理 subfolder using the same archiving rule applied to audio files

#### Scenario: Unsupported video container remains excluded

- **WHEN** a scan finds a stable file whose extension is neither an existing supported audio extension nor `.mkv` (for example `.mov` or `.avi`)
- **THEN** the system SHALL NOT include the file in the set of files to process
