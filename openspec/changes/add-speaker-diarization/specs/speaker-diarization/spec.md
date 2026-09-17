## ADDED Requirements

### Requirement: Local Speaker Diarization

The system SHALL support labeling transcript segments with a speaker identifier using a local, GPU-accelerated speaker diarization pipeline, run entirely on the machine performing transcription. The speaker label text SHALL follow the product's existing Traditional Chinese output convention (e.g. `語者 A`, `語者 B`), consistent with all other user-facing note content the system generates. Only pretrained model weights SHALL be fetched from an external source (Hugging Face) on first use; the recording's audio content SHALL NOT be uploaded to any external service. This capability SHALL be disabled by default and SHALL only activate when explicitly enabled via the `SPEAKER_DIARIZATION_ENABLED` environment variable together with a configured `HUGGINGFACE_TOKEN`.

#### Scenario: Diarization enabled produces speaker-labeled transcript

- **WHEN** a recording is transcribed with `SPEAKER_DIARIZATION_ENABLED=true` and a valid `HUGGINGFACE_TOKEN` configured
- **THEN** the resulting transcript text SHALL contain each spoken segment prefixed with a speaker label in the form `[語者 A]`, with segments separated by newlines, and speaker letters SHALL be assigned in the order each distinct diarization-detected speaker first appears in the recording

##### Example: two-speaker interview

| Segment text | Detected diarization label | Transcript output prefix |
| --- | --- | --- |
| "請問你對這個題目的想法是?" | SPEAKER_00 (first label seen) | `[語者 A]` |
| "我覺得這個方向不錯。" | SPEAKER_01 (second label seen) | `[語者 B]` |

#### Scenario: Diarization disabled preserves existing plain-text transcript

- **WHEN** a recording is transcribed with `SPEAKER_DIARIZATION_ENABLED` unset or set to `false`
- **THEN** the resulting transcript text SHALL be unchanged from the pre-existing format: no speaker labels and no segment-based line breaks introduced by this capability

#### Scenario: Enabling diarization without a Hugging Face token is a configuration error

- **WHEN** `SPEAKER_DIARIZATION_ENABLED=true` and `HUGGINGFACE_TOKEN` is empty or unset at pipeline startup
- **THEN** the system SHALL raise a configuration error and SHALL NOT start processing recordings

---

### Requirement: Meeting Recordings Never Use Diarization

The system SHALL NOT run speaker diarization on recordings from the meeting watch folder (`WATCH_FOLDER_PATH`), regardless of the `SPEAKER_DIARIZATION_ENABLED` value. Diarization SHALL only ever apply to recordings from the interview watch folder (`INTERVIEW_WATCH_FOLDER_PATH`).

#### Scenario: Meeting recording transcribed with diarization enabled globally

- **WHEN** a recording from the meeting watch folder is transcribed while `SPEAKER_DIARIZATION_ENABLED=true`
- **THEN** the resulting transcript text SHALL contain no speaker labels, identical to the diarization-disabled output

---

### Requirement: Diarization Failure Falls Back To Plain Transcript

The system SHALL NOT allow a failure in the speaker diarization step (for example, model download failure, an invalid or expired Hugging Face token, or a runtime error in the diarization pipeline) to cause the overall transcription to fail. On diarization failure, the system SHALL fall back to producing the plain transcript text without speaker labels, and SHALL record a warning describing the failure in the pipeline log.

#### Scenario: Diarization runtime error falls back to plain transcript

- **WHEN** diarization is enabled and the diarization step raises an error while processing a recording whose speech recognition already succeeded
- **THEN** the transcription step SHALL still report success, the returned transcript text SHALL contain no speaker labels, and the pipeline log SHALL contain a warning describing the diarization failure

#### Scenario: Diarization failure does not require re-transcription on retry

- **WHEN** a recording's diarization step fails but its speech recognition succeeded
- **THEN** the pipeline SHALL treat the recording's transcription as successful and SHALL proceed to structuring and Notion write using the plain (non-diarized) transcript, without re-running speech recognition

---

### Requirement: Diarization Progress Reporting

The system SHALL report a distinct progress phase while the diarization step is running, so the progress viewer can display a meaningful status instead of an unrecognized/default state.

#### Scenario: Progress viewer shows diarization phase

- **WHEN** diarization is enabled and the transcription worker is executing the diarization step for a recording
- **THEN** the progress file's `phase` field SHALL be set to `diarizing`, and the progress viewer SHALL render a status message naming the file being processed instead of falling back to an "unknown status" message
