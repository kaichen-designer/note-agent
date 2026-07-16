## ADDED Requirements

### Requirement: Database Schema Provisioning

The system SHALL provide a one-time setup step, using the `notion-client` library authenticated with a Notion Internal Integration Token, that creates the Notion notes database with the required schema (Date, Source Filename, Category Tag as multi-select with the fixed tag list, and Status as select with options 待處理/已整理/已完成) if the database does not already exist, so the recurring pipeline can rely on the schema being present without checking or creating it on every run.

#### Scenario: Database created on first-time setup

- **WHEN** the user runs the setup step and no notes database exists yet at the configured location
- **THEN** the system SHALL create a Notion database with the Date, Source Filename, Category Tag (multi-select), and Status (select) properties configured with their fixed option lists, and SHALL output the resulting database ID for use in configuration

#### Scenario: Setup step is not re-run automatically by the recurring pipeline

- **WHEN** the scheduled or manual pipeline run executes
- **THEN** the system SHALL NOT attempt to create or modify the database schema as part of that run, and SHALL only write pages into the database ID already configured

### Requirement: Agent-Driven Note Structuring

The system SHALL call the Claude API with the transcript to derive a title, summary, key points, action items, and a category tag. Claude SHALL determine these values itself rather than the system applying a fixed rule-based template; the system SHALL only apply deterministic code to parse Claude's structured response and write it to Notion.

#### Scenario: Agent produces structured note from transcript

- **WHEN** a transcript is passed to the structuring step along with the source filename and recording date
- **THEN** Claude SHALL generate a title, summary, key points, action items, and select one category tag from the configured fixed tag list

### Requirement: Notion Page Creation With Required Properties

The system SHALL use the `notion-client` library, authenticated with a Notion Internal Integration Token, to create one Notion database page per successfully processed recording, setting the Date, Source Filename, Category Tag (multi-select), and Status (select) properties, with Status defaulting to "已整理" (Organized) on successful creation.

#### Scenario: New page created with all properties set

- **WHEN** the Notion agent successfully structures a transcript
- **THEN** the system SHALL create a new page in the configured Notion database with the Date, Source Filename, Category Tag, and Status properties populated, and Status set to "已整理"

##### Example: page properties for a meeting recording

| Property | Value |
| --- | --- |
| Date | 2026-07-04 |
| Source Filename | meeting_0704.m4a |
| Category Tag | 會議 |
| Status | 已整理 |

### Requirement: Full Transcript Preserved In A Collapsed Section

The system SHALL include the complete transcript text in the created page, contained within a toggle (collapsible) block, so the raw transcript remains available without cluttering the default page view.

#### Scenario: Transcript is present but collapsed by default

- **WHEN** a Notion page is created for a processed recording
- **THEN** the page content SHALL include a toggle block containing the full transcript, collapsed by default

### Requirement: Notion Write Failure Handling

The system SHALL mark a recording's state as "failed" when the Notion API call fails to create the page (for example, due to an invalid or revoked Integration Token, or a network error), while preserving the already-generated transcript so a retry does not require re-transcription.

#### Scenario: Notion write failure preserves transcript for retry

- **WHEN** the Notion page creation step fails after transcription has already succeeded
- **THEN** the system SHALL record the failure in state without discarding the transcript, so the next retry attempt reuses the existing transcript instead of re-running transcription
