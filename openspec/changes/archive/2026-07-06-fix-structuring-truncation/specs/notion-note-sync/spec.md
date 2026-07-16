## ADDED Requirements

### Requirement: Truncated Structuring Output Rejection

The system SHALL treat a structuring response whose stop_reason is max_tokens as a structuring failure, raising an error so the recording is marked failed and retried, instead of silently accepting a partially generated note. The structuring call SHALL allocate enough output tokens (at least 8192) that a typical long-recording note does not approach the limit.

#### Scenario: Truncated response triggers failure and retry

- **WHEN** the structuring API response reports stop_reason max_tokens
- **THEN** the structuring step SHALL raise an error, and the pipeline SHALL record the recording as failed with the transcript preserved for retry

#### Scenario: Complete response is parsed normally

- **WHEN** the structuring API response completes without hitting the token limit
- **THEN** the note SHALL be parsed with the existing tolerant parser and written to Notion
