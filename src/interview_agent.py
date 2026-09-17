"""Structures an interview transcript via Claude into pain points,
highlights, usage habits, and a summary, then writes the result to Notion.

Uses a separate tool schema from notion_agent.py's meeting structuring
(summary/pain_points/highlights/usage_habits instead of key_points/
action_items) because the two recording types answer different questions --
see design.md's "新增 src/interview_agent.py,不擴充 notion_agent.py" decision.
Each finding carries the transcript quote and timestamp that support it, so
the resulting Notion page can show which part of the interview a pain point
or highlight came from.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import anthropic
from notion_client import Client

_log = logging.getLogger("pipeline")

from notion_agent import NotionWriteResult, _chunk_text
from notion_schema import (
    CATEGORY_TAG_PROPERTY,
    DATE_PROPERTY,
    DEFAULT_STATUS,
    INTERVIEW_CATEGORY_TAG,
    SOURCE_FILENAME_PROPERTY,
    STATUS_PROPERTY,
    TITLE_PROPERTY,
)

_FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "insight": {
            "type": "string",
            "description": "The analysis point itself, in the interviewer's own words (not a direct quote).",
        },
        "quote": {
            "type": "string",
            "description": "The transcript excerpt that supports this finding, quoted as close to verbatim as possible.",
        },
        "start_seconds": {
            "type": "number",
            "description": "The start time, in seconds, of the transcript segment the quote is drawn from.",
        },
    },
    "required": ["insight", "quote", "start_seconds"],
}

_STRUCTURE_TOOL = {
    "name": "return_structured_interview",
    "description": "Return the structured interview analysis derived from a timestamped interview transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "A concise summary of the interview"},
            "pain_points": {
                "type": "array",
                "items": _FINDING_SCHEMA,
                "description": "Problems, frustrations, or friction the interviewee described experiencing.",
            },
            "highlights": {
                "type": "array",
                "items": _FINDING_SCHEMA,
                "description": "Things the interviewee liked, praised, or found valuable.",
            },
            "usage_habits": {
                "type": "array",
                "items": _FINDING_SCHEMA,
                "description": "How the interviewee actually uses the product/workflow being discussed -- routines, frequency, context.",
            },
        },
        "required": ["summary", "pain_points", "highlights", "usage_habits"],
    },
}

_STRUCTURE_MODEL = "claude-sonnet-5"

# Matches a JSON object key immediately followed by an array/object open
# bracket (e.g. `"usage_habits":[`), which never occurs in legitimate prose
# but is exactly what a leaked, unparsed field looks like inside a string.
_LEAKED_JSON_PATTERN = re.compile(r'"\w+"\s*:\s*[\[{]')


@dataclass
class InterviewFinding:
    insight: str
    quote: str
    start_seconds: float | None
    speaker: str | None = None


@dataclass
class InterviewNote:
    summary: str
    pain_points: list[InterviewFinding]
    highlights: list[InterviewFinding]
    usage_habits: list[InterviewFinding]


def format_segments_with_timestamps(segments: list[dict]) -> str:
    """Render whisper segments as one line per segment, each prefixed with
    its start time as [MM:SS], so Claude can cite the segment a finding is
    drawn from. When a segment carries a `speaker` label (diarization
    enabled and successful), the label is inserted right after the
    timestamp as `[MM:SS][語者 X]`; segments without one keep the plain
    `[MM:SS]` prefix, identical to before speaker labels existed."""
    lines = []
    for segment in segments:
        minutes, seconds = divmod(int(segment["start"]), 60)
        speaker = segment.get("speaker")
        speaker_prefix = f"[語者 {speaker}]" if speaker else ""
        lines.append(f"[{minutes:02d}:{seconds:02d}]{speaker_prefix} {segment['text'].strip()}")
    return "\n".join(lines)


def structure_interview(
    transcript_with_timestamps: str,
    source_filename: str,
    recording_date: str,
    api_key: str,
    segments: list[dict],
) -> InterviewNote:
    """Ask Claude to derive an interview summary, pain points, highlights,
    and usage habits from a timestamped transcript. Claude decides the
    values; this function only parses the tool-call response into an
    InterviewNote, validating each finding's timestamp against the real
    segments."""
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_STRUCTURE_MODEL,
        max_tokens=8192,
        tools=[_STRUCTURE_TOOL],
        tool_choice={"type": "tool", "name": "return_structured_interview"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"來源檔名:{source_filename}\n訪談日期:{recording_date}\n\n"
                    f"以下是一段使用者訪談的逐字稿,每行前面標有該段話開始的時間戳記 [分:秒]。"
                    f"請幫我分析這份訪談,整理出:\n"
                    f"1. summary:訪談摘要,精簡(200字以內)\n"
                    f"2. pain_points:使用者提到的痛點/困擾\n"
                    f"3. highlights:使用者提到喜歡/覺得好用的地方\n"
                    f"4. usage_habits:使用者實際的使用習慣(多久用一次、在什麼情境下用等)\n\n"
                    f"pain_points/highlights/usage_habits 每一點都必須包含:\n"
                    f"- insight:你的分析文字\n"
                    f"- quote:支持這個分析的逐字稿原句引用\n"
                    f"- start_seconds:引用的那句話開始的時間戳記(取自逐字稿行首的 [分:秒],換算成秒數)\n\n"
                    f"{transcript_with_timestamps}"
                ),
            }
        ],
    )
    if message.stop_reason == "max_tokens":
        raise RuntimeError("interview structuring output truncated (stop_reason=max_tokens)")
    tool_use = next(block for block in message.content if block.type == "tool_use")
    data = tool_use.input
    summary = data.get("summary")
    if isinstance(summary, str) and _LEAKED_JSON_PATTERN.search(summary):
        # A malformed tool call can leave another field's raw JSON (e.g. the
        # usage_habits array) appended to the summary string instead of being
        # parsed into its own field (observed in production: summary ended in
        # literal `","usage_habits":[{...}]`, and usage_habits came back
        # silently empty). Fail loudly so the pipeline marks the file failed
        # and retries -- never write the corrupted text into Notion.
        raise RuntimeError("interview structuring summary contains leaked JSON, likely a malformed tool call")
    return parse_structured_interview(data, segments)


# format_segments_with_timestamps() floors each segment's start to a whole
# second for the [MM:SS] label Claude reads, so echoing that label back as
# seconds can land up to ~1s before the segment's real (fractional) start.
# The tolerance absorbs that self-inflicted rounding gap without being wide
# enough to accept a genuinely wrong timestamp.
_TIMESTAMP_TOLERANCE_SECONDS = 2.0


def _segment_matching_start_seconds(start_seconds: object, segments: list[dict]) -> dict | None:
    """Return the segment whose [start, end] range (with tolerance) contains
    start_seconds, or None. Guards against a hallucinated timestamp that
    does not correspond to anything Claude was actually shown."""
    try:
        value = float(start_seconds)
    except (TypeError, ValueError):
        return None
    for segment in segments:
        if segment["start"] - _TIMESTAMP_TOLERANCE_SECONDS <= value <= segment["end"] + _TIMESTAMP_TOLERANCE_SECONDS:
            return segment
    return None


_MATCH_STRIP_PATTERN = re.compile(r'[\s,。.!?、,!?"\'「」『』]')


def _normalize_for_match(text: str) -> str:
    """Strip whitespace and common punctuation so minor formatting
    differences between Claude's quote and the raw transcript segment text
    (spacing, quote marks, punctuation) don't prevent a textual match."""
    return _MATCH_STRIP_PATTERN.sub("", text)


def _segment_matching_quote(quote: str, segments: list[dict]) -> dict | None:
    """Recover a finding's source segment by locating the one whose text
    contains (or is contained by) the quote, used when Claude's self-reported
    start_seconds does not correspond to any real segment. More reliable than
    trusting a bare number: the quote is expected to be near-verbatim
    transcript text, so a textual match is strong evidence of which segment
    it came from even when the model's own timestamp guess was wrong."""
    normalized_quote = _normalize_for_match(quote)
    if not normalized_quote:
        return None
    for segment in segments:
        normalized_segment_text = _normalize_for_match(str(segment.get("text", "")))
        if not normalized_segment_text:
            continue
        if normalized_quote in normalized_segment_text or normalized_segment_text in normalized_quote:
            return segment
    return None


def _parse_findings(raw: object, segments: list[dict]) -> list[InterviewFinding]:
    if not isinstance(raw, list):
        if raw:
            _log.warning("interview structuring output used a non-list shape for a finding list; treating as empty")
        return []

    findings: list[InterviewFinding] = []
    for item in raw:
        if not isinstance(item, dict):
            _log.warning("interview structuring output contained a non-object finding; dropping it")
            continue
        insight = str(item.get("insight") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if not insight or not quote:
            _log.warning("interview structuring output finding missing insight/quote; dropping it")
            continue
        matched_segment = _segment_matching_start_seconds(item.get("start_seconds"), segments)
        if matched_segment is None:
            matched_segment = _segment_matching_quote(quote, segments)
        start_seconds = float(matched_segment["start"]) if matched_segment is not None else None
        speaker = matched_segment.get("speaker") if matched_segment is not None else None
        findings.append(
            InterviewFinding(insight=insight, quote=quote, start_seconds=start_seconds, speaker=speaker)
        )
    return findings


def parse_structured_interview(data: dict, segments: list[dict]) -> InterviewNote:
    """Convert Claude's tool-call payload into an InterviewNote, tolerating
    missing or malformed fields instead of raising -- a formatting glitch in
    one finding must not fail the whole interview's processing."""
    return InterviewNote(
        summary=str(data.get("summary") or ""),
        pain_points=_parse_findings(data.get("pain_points"), segments),
        highlights=_parse_findings(data.get("highlights"), segments),
        usage_habits=_parse_findings(data.get("usage_habits"), segments),
    )


def _format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def _finding_blocks(findings: list[InterviewFinding]) -> list[dict]:
    """Render each finding as a bulleted insight immediately followed by a
    quote block citing its supporting transcript excerpt, prefixed with a
    [MM:SS] timestamp when the finding has a valid one."""
    blocks: list[dict] = []
    for finding in findings:
        blocks.append(
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": finding.insight}}]},
            }
        )
        if finding.start_seconds is not None:
            speaker_part = f"[語者 {finding.speaker}]" if finding.speaker else ""
            prefix = f"[{_format_timestamp(finding.start_seconds)}]{speaker_part}"
        else:
            prefix = ""
        blocks.append(
            {
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": [{"type": "text", "text": {"content": f"{prefix}「{finding.quote}」"}}]},
            }
        )
    return blocks


def _finding_section(heading: str, findings: list[InterviewFinding]) -> list[dict]:
    if not findings:
        return []
    return [
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": heading}}]},
        },
        *_finding_blocks(findings),
    ]


def build_interview_page_children(note: InterviewNote, transcript: str) -> list[dict]:
    """Build the page body: summary, then a heading + bulleted-insight +
    quoted-evidence section per non-empty finding category, then the full
    transcript inside a collapsed toggle block (matching notion_agent.py's
    Full Transcript Preserved In A Collapsed Section convention)."""
    children: list[dict] = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": note.summary}}]},
        }
    ]

    children.extend(_finding_section("痛點", note.pain_points))
    children.extend(_finding_section("亮點", note.highlights))
    children.extend(_finding_section("使用者使用習慣", note.usage_habits))

    transcript_paragraphs = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        }
        for chunk in _chunk_text(transcript)
    ]
    children.append(
        {
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "text": {"content": "完整逐字稿"}}],
                "children": transcript_paragraphs,
            },
        }
    )
    return children


def build_interview_page_properties(source_filename: str, recording_date: str) -> dict:
    """Build the Notion page properties for an interview page. The title
    falls back to the source filename (no Claude-generated title field
    exists for interviews, unlike the meeting pipeline) and the category tag
    is always INTERVIEW_CATEGORY_TAG -- never Claude-selected."""
    return {
        TITLE_PROPERTY: {"title": [{"text": {"content": source_filename}}]},
        DATE_PROPERTY: {"date": {"start": recording_date}},
        SOURCE_FILENAME_PROPERTY: {"rich_text": [{"text": {"content": source_filename}}]},
        CATEGORY_TAG_PROPERTY: {"multi_select": [{"name": INTERVIEW_CATEGORY_TAG}]},
        STATUS_PROPERTY: {"select": {"name": DEFAULT_STATUS}},
    }


def create_interview_page(
    note: InterviewNote,
    transcript: str,
    source_filename: str,
    recording_date: str,
    database_id: str,
    notion_api_key: str,
) -> NotionWriteResult:
    """Create one Notion page for this interview, in the same database used
    by the meeting pipeline. Never raises: API failures are converted into
    NotionWriteResult(success=False, error=...) so the caller can mark the
    file failed and continue processing other files."""
    client = Client(auth=notion_api_key)
    try:
        page = client.pages.create(
            parent={"database_id": database_id},
            properties=build_interview_page_properties(source_filename, recording_date),
            children=build_interview_page_children(note, transcript),
        )
    except Exception as exc:
        return NotionWriteResult(success=False, error=str(exc))

    return NotionWriteResult(success=True, page_id=page["id"])
