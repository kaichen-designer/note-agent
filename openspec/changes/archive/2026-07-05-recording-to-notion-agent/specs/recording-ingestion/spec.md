## ADDED Requirements

### Requirement: Stable File Detection

The system SHALL only consider a recording file ready for processing after two consecutive scans report identical file size and modification time, to avoid processing files that are still being synced from cloud storage.

#### Scenario: File still syncing is not processed

- **WHEN** a scan detects a recording file whose size or modification time differs from the previous scan
- **THEN** the system SHALL NOT process the file in this cycle and SHALL re-check it on the next scan

#### Scenario: Stable file is processed

- **WHEN** a scan detects a recording file whose size and modification time are unchanged from the previous scan
- **THEN** the system SHALL mark the file as ready for processing

##### Example: two-pass stability check

| Scan Pass | File Size | Result |
| --- | --- | --- |
| Pass 1 (T=0min) | 12,345,600 bytes | Not yet stable, skip |
| Pass 2 (T=15min) | 18,920,400 bytes | Still changing, skip (still syncing) |
| Pass 3 (T=30min) | 18,920,400 bytes | Unchanged from Pass 2, mark ready |

### Requirement: Duplicate Processing Prevention

The system SHALL track processed files in local state and SHALL NOT reprocess a file whose state record status is "success".

#### Scenario: Already-processed file is skipped

- **WHEN** a scan finds a file whose state record status is "success"
- **THEN** the system SHALL skip the file without re-transcribing it or creating a new Notion page for it

### Requirement: Failed File Retry With Limit

The system SHALL retry files with "failed" status on subsequent runs up to a configured maximum retry count. Once a file's retry count reaches that maximum, the system SHALL mark the file as requiring manual intervention and SHALL NOT attempt automatic reprocessing.

#### Scenario: Failed file retried within limit

- **WHEN** a file's state record status is "failed" and its retry count is below the configured maximum
- **THEN** the system SHALL attempt to process the file again and increment the retry count

#### Scenario: Failed file exceeds retry limit

- **WHEN** a file's retry count reaches the configured maximum
- **THEN** the system SHALL mark the file as requiring manual intervention and SHALL NOT attempt automatic reprocessing

### Requirement: Processed File Archiving

The system SHALL move a recording file into a "已處理" subfolder inside the watch folder after its Notion page has been successfully created, so the watch folder root only contains recordings that still need attention. Files whose processing failed SHALL remain in place for retry. If the move itself fails (for example, the file is locked by the cloud sync client), the system SHALL log a warning and keep the success state — an archiving failure SHALL NOT affect the note or cause reprocessing.

#### Scenario: Successful recording is archived

- **WHEN** a recording's Notion page is created successfully
- **THEN** the system SHALL move the audio file into the 已處理 subfolder of the watch folder, appending a numeric suffix if a file with the same name already exists there

#### Scenario: Failed recording stays in place

- **WHEN** a recording's transcription or Notion write fails
- **THEN** the audio file SHALL remain in the watch folder root so later retries can find it

#### Scenario: Archive subfolder is not scanned

- **WHEN** the watcher scans the watch folder
- **THEN** files inside subfolders (including 已處理) SHALL NOT be picked up for processing

### Requirement: Dual Trigger Entry Points

The system SHALL expose exactly one processing entry point that both the scheduled task and the manual trigger script invoke, so both triggers execute identical scan-transcribe-write-update logic.

#### Scenario: Manual trigger runs full pipeline immediately

- **WHEN** the user runs the manual trigger script
- **THEN** the system SHALL execute the same scan, transcription, structuring, and Notion-write pipeline as the scheduled run, without waiting for the next scheduled interval
