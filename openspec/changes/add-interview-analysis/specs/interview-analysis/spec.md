## ADDED Requirements

### Requirement: Independently Configured Interview Watch Folder

The system SHALL support an optional interview watch folder path, configured independently from the existing meeting watch folder path, and SHALL only run the interview pipeline when this path is configured. The system SHALL NOT start if the interview watch folder path is configured to be identical to the meeting watch folder path.

#### Scenario: Interview watch folder not configured

- **WHEN** no interview watch folder path is present in configuration
- **THEN** the system SHALL skip the interview pipeline entirely and SHALL log that interview mode is not enabled, without treating this as an error

#### Scenario: Interview watch folder configured

- **WHEN** an interview watch folder path is present in configuration and differs from the meeting watch folder path
- **THEN** the system SHALL scan the interview watch folder for stable files on the same run as the meeting watch folder scan

#### Scenario: Interview and meeting watch folders configured identically

- **WHEN** the interview watch folder path is configured to the same path as the meeting watch folder path
- **THEN** the system SHALL abort the run with a non-zero exit status and SHALL log that the two paths must not be identical

---
### Requirement: Batch Interview Detection Logging

The system SHALL emit a distinct log line naming the number of pending interview files when a scan of the interview watch folder finds two or more files ready for processing, so the operator can tell at a glance that this run will produce more than one interview analysis.

#### Scenario: Single interview file pending

- **WHEN** a scan of the interview watch folder finds exactly one file ready for processing
- **THEN** the system SHALL log the pending file using the same general scan log format used for the meeting pipeline, without a distinct batch-count message

#### Scenario: Multiple interview files pending

- **WHEN** a scan of the interview watch folder finds two or more files ready for processing
- **THEN** the system SHALL log a message stating the count of pending interview files before processing them

##### Example: pending count thresholds

| Pending Files | Log Behavior |
| --- | --- |
| 0 | No interview processing occurs this run |
| 1 | Standard scan log line only |
| 3 | Standard scan log line plus a distinct line stating "3" pending interview files |

---
### Requirement: Interview-Specific Structured Analysis

The system SHALL call the Claude API with an interview transcript to derive an interview summary, pain points, highlights, and user usage habits. The system SHALL NOT reuse the meeting pipeline's key_points/action_items schema for interview recordings.

#### Scenario: Agent produces interview-shaped structured note

- **WHEN** an interview transcript is passed to the interview structuring step along with the source filename and recording date
- **THEN** Claude SHALL generate an interview summary, a list of pain points, a list of highlights, and a list of user usage habits

---
### Requirement: Timestamped Evidence For Each Finding

The system SHALL require each pain point, highlight, and usage habit finding to carry the transcript quote and timestamp that support it, and SHALL render this evidence in the created Notion page directly beneath the corresponding finding.

#### Scenario: Finding rendered with quote and timestamp

- **WHEN** a pain point, highlight, or usage habit finding is written to the Notion page
- **THEN** the page SHALL include a quote block directly beneath that finding's text, containing the cited transcript excerpt prefixed with its timestamp in `[MM:SS]` format

##### Example: rendered finding

- **GIVEN** a pain point finding with insight "匯出報表流程太繁瑣", quote "我每次要匯出都要點三四層選單才找得到", start_seconds 192
- **WHEN** the interview page is built
- **THEN** the page SHALL contain a bulleted item "匯出報表流程太繁瑣" followed by a quote block reading `[03:12]「我每次要匯出都要點三四層選單才找得到」`

#### Scenario: Finding timestamp does not match any real transcript segment

- **WHEN** the timestamp returned for a finding does not fall within any segment of the source transcript
- **THEN** the system SHALL still render the finding's quote text, SHALL omit the timestamp prefix, and SHALL NOT fail the interview's processing because of the mismatch

---
### Requirement: Interview Notion Page Category Tag

The system SHALL create each interview's Notion page in the same database used by the meeting pipeline, with the category tag set to "訪談".

#### Scenario: Interview page created with interview category tag

- **WHEN** an interview recording is successfully structured and written to Notion
- **THEN** the created page's category tag property SHALL include "訪談" and the page SHALL be created in the same configured Notion database as meeting pages

---
### Requirement: Speaker-Labeled Timestamped Evidence

The system SHALL prefix a finding's quote evidence with the speaker label of the transcript segment it was drawn from, when that segment carries a speaker label produced by speaker diarization. When no speaker label is available for the cited segment, or the finding has no valid timestamp at all, the system SHALL render the evidence exactly as it does without diarization (timestamp only, or quote only).

#### Scenario: Cited segment has a speaker label

- **WHEN** a finding's timestamp resolves to a transcript segment that carries a speaker label
- **THEN** the rendered quote block SHALL include the speaker label immediately after the `[MM:SS]` timestamp, before the quoted text

##### Example: rendered finding with speaker label

- **GIVEN** a highlight finding with insight "喜歡基本功能", quote "他最basic的那個contact greater跟mix and match的方面我覺得是好用的", resolved to a segment starting at 1500 seconds labeled speaker "A"
- **WHEN** the interview page is built
- **THEN** the page SHALL contain a quote block reading `[25:00][語者 A]「他最basic的那個contact greater跟mix and match的方面我覺得是好用的」`

#### Scenario: Cited segment has no speaker label

- **WHEN** a finding's timestamp resolves to a transcript segment that carries no speaker label (diarization not enabled, or failed)
- **THEN** the rendered quote block SHALL use the existing `[MM:SS]「quote」` format with no speaker prefix

---
### Requirement: Corrupted Summary Rejection

The system SHALL treat an interview structuring response whose summary field contains embedded JSON key syntax (indicating another field's raw content leaked into the summary string due to a malformed tool call) as a structuring failure, raising an error so the recording is marked failed and retried, instead of writing the corrupted text into the Notion page.

#### Scenario: Summary containing leaked JSON triggers failure and retry

- **WHEN** the structuring API response's summary field contains a pattern matching a JSON object key followed by an array or object (for example `"usage_habits":[`)
- **THEN** the structuring step SHALL raise an error, and the pipeline SHALL record the recording as failed with the transcript preserved for retry

#### Scenario: Normal prose summary is parsed normally

- **WHEN** the structuring API response's summary field contains no embedded JSON syntax
- **THEN** the note SHALL be parsed with the existing tolerant parser and written to Notion

---
### Requirement: Interview Processing State Isolation

The system SHALL track interview file processing state (success/failed/retry count) independently from meeting file processing state, applying the same failed-file retry limit and processed-file archiving rules used by the meeting pipeline without sharing state records between the two folders.

#### Scenario: Interview file failure retried independently of meeting state

- **WHEN** an interview file fails processing and is retried on a subsequent run
- **THEN** its retry count SHALL be tracked in interview-specific state, and SHALL NOT be affected by, or affect, the retry count of any meeting file
