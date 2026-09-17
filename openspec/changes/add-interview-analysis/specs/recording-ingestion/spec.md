## ADDED Requirements

### Requirement: Independent Watch Folder Support

The system SHALL support scanning a second, independently configured watch folder in the same run as the primary watch folder, applying the same stable-file detection, duplicate-processing prevention, failed-file retry, and processed-file archiving rules to it, while keeping its scan snapshot and processing state records fully separate from the primary watch folder's records.

#### Scenario: Second watch folder scanned independently

- **WHEN** a run scans both the primary watch folder and a second configured watch folder
- **THEN** the system SHALL apply the stable-file detection, duplicate-processing prevention, and failed-file retry rules to each folder using that folder's own scan snapshot and state records

#### Scenario: Processing state does not leak between folders

- **WHEN** a file in the second watch folder shares the same name as a file in the primary watch folder
- **THEN** the two files' processing state (success/failed/retry count) SHALL be tracked independently and SHALL NOT influence each other
