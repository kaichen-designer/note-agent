"""Structures a transcript via Claude and writes it to Notion.

Structuring uses a single Claude API tool-call (not an agentic tool-use
loop) because writing to Notion happens directly through notion-client, not
through MCP tools -- see design.md for why Agent SDK + Notion MCP was
rejected in favor of this simpler, fully headless approach.
"""
from __future__ import annotations

from dataclasses import dataclass

import anthropic
from notion_client import Client

from notion_schema import (
    CATEGORY_TAG_OPTIONS,
    CATEGORY_TAG_PROPERTY,
    DATE_PROPERTY,
    DEFAULT_STATUS,
    SOURCE_FILENAME_PROPERTY,
    STATUS_PROPERTY,
    TITLE_PROPERTY,
)

_STRUCTURE_TOOL = {
    "name": "return_structured_note",
    "description": "Return the structured note derived from a recording transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A short descriptive title for the note"},
            "summary": {"type": "string", "description": "A concise summary of the recording"},
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Discussion points, decisions, and facts covered in the recording. "
                    "Purely informational -- nobody needs to go do something as a direct "
                    "result of the item. Do not include anything that also belongs in "
                    "action_items."
                ),
            },
            "action_items": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Concrete, actionable tasks someone must do after this recording -- "
                    "each one should have an identifiable owner and/or deadline where the "
                    "transcript mentions one (e.g. '[負責人] 於 [期限] 前完成 [任務]'). "
                    "If the transcript names who is responsible or when it's due, include "
                    "that in the item text. Every action item must be moved here, not left "
                    "in key_points, even if it was also discussed as a topic."
                ),
            },
            "category_tag": {"type": "string", "enum": CATEGORY_TAG_OPTIONS},
        },
        "required": ["title", "summary", "key_points", "action_items", "category_tag"],
    },
}

_STRUCTURE_MODEL = "claude-sonnet-5"


@dataclass
class StructuredNote:
    title: str
    summary: str
    key_points: list[str]
    action_items: list[str]
    category_tag: str


def structure_note(
    transcript: str, source_filename: str, recording_date: str, api_key: str
) -> StructuredNote:
    """Ask Claude to derive title/summary/key points/action items/category
    tag from a transcript. Claude decides the values; this function only
    parses the tool-call response into a StructuredNote."""
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_STRUCTURE_MODEL,
        max_tokens=8192,
        tools=[_STRUCTURE_TOOL],
        tool_choice={"type": "tool", "name": "return_structured_note"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"來源檔名:{source_filename}\n錄音日期:{recording_date}\n\n"
                    f"以下是一段錄音的逐字稿,請幫我整理成結構化筆記。"
                    f"摘要請精簡(200字以內);重點(key_points)以簡潔條列,約5~8條,"
                    f"僅記錄討論內容、決策或事實,不含待辦事項;"
                    f"行動項目(action_items)請具體可執行,並盡量包含負責人與期限"
                    f"(逐字稿中有提到的話一定要寫進去,例如「[負責人]於[期限]前完成[任務]」)。"
                    f"兩者互斥:任何屬於待辦性質的項目只能放在 action_items,"
                    f"絕對不要同時出現在 key_points 裡:\n\n{transcript}"
                ),
            }
        ],
    )
    if message.stop_reason == "max_tokens":
        # A truncated tool call silently loses trailing fields (observed in
        # production: pages missing key points / action items). Fail loudly so
        # the pipeline marks the file failed, preserves the transcript, and
        # retries -- never accept a partially generated note.
        raise RuntimeError("structuring output truncated (stop_reason=max_tokens)")
    tool_use = next(block for block in message.content if block.type == "tool_use")
    return parse_structured_note(tool_use.input, source_filename, transcript)


def parse_structured_note(data: dict, fallback_title: str, transcript: str) -> StructuredNote:
    """Convert Claude's tool-call payload into a StructuredNote, tolerating
    missing or malformed fields. Despite the tool schema marking every field
    as required, the model can occasionally omit one (observed in production
    with action_items); a missing optional-ish field must degrade gracefully
    instead of failing the whole recording."""
    category = data.get("category_tag")
    if category not in CATEGORY_TAG_OPTIONS:
        category = CATEGORY_TAG_OPTIONS[-1]  # fallback bucket: 其他

    def _string_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            # The model sometimes serializes array fields as a single string
            # instead of a real array. Malformed shapes observed in
            # production: a string of <item>...</item> or <li>...</li>
            # chunks (optionally wrapped in a <list>...</list> container),
            # and its own tool-call-like markup leaking into the value with
            # a JSON array embedded inside (e.g. `<parameter name="items">
            # ["a","b"]`, sometimes missing the closing tag). Recover
            # whichever shape appears before falling back to line-splitting.
            import json
            import re

            items = re.findall(r"<(?:item|li)>(.*?)</(?:item|li)>", value, re.DOTALL)
            if items:
                return [item.strip() for item in items if item.strip()]
            array_match = re.search(r"\[.*\]", value, re.DOTALL)
            if array_match:
                try:
                    parsed = json.loads(array_match.group(0))
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            lines = [line.strip(" \t-•*") for line in value.splitlines()]
            # Drop stray container tags (e.g. "<list>", "</list>") that
            # line-splitting alone would otherwise turn into bogus items.
            lines = [line for line in lines if not re.fullmatch(r"</?\w+>", line)]
            return [line for line in lines if line]
        return []

    return StructuredNote(
        title=str(data.get("title") or fallback_title),
        summary=str(data.get("summary") or transcript[:200]),
        key_points=_string_list(data.get("key_points")),
        action_items=_string_list(data.get("action_items")),
        category_tag=category,
    )


def _chunk_text(text: str, chunk_size: int = 1900) -> list[str]:
    """Notion rich_text blocks cap out around 2000 characters; split long
    transcripts into multiple paragraph blocks so long recordings don't fail
    to write."""
    if not text:
        return [""]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _bulleted_list(items: list[str]) -> list[dict]:
    return [
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": item}}]},
        }
        for item in items
    ]


def build_page_children(note: StructuredNote, transcript: str) -> list[dict]:
    """Build the page body: summary, key points, action items, then the full
    transcript inside a collapsed toggle block (per Full Transcript Preserved
    In A Collapsed Section)."""
    children: list[dict] = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": note.summary}}]},
        }
    ]

    if note.key_points:
        children.append(
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": "重點"}}]},
            }
        )
        children.extend(_bulleted_list(note.key_points))

    if note.action_items:
        children.append(
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": "行動項目"}}]},
            }
        )
        children.extend(_bulleted_list(note.action_items))

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


@dataclass
class NotionWriteResult:
    success: bool
    page_id: str | None = None
    error: str | None = None


def create_notion_page(
    note: StructuredNote,
    transcript: str,
    source_filename: str,
    recording_date: str,
    database_id: str,
    notion_api_key: str,
) -> NotionWriteResult:
    """Create one Notion page for this recording. Never raises: API failures
    are converted into NotionWriteResult(success=False, error=...) so the
    caller can mark the file failed (preserving the transcript so a retry
    does not require re-transcription) and continue processing other files."""
    client = Client(auth=notion_api_key)
    try:
        page = client.pages.create(
            parent={"database_id": database_id},
            properties={
                TITLE_PROPERTY: {"title": [{"text": {"content": note.title}}]},
                DATE_PROPERTY: {"date": {"start": recording_date}},
                SOURCE_FILENAME_PROPERTY: {"rich_text": [{"text": {"content": source_filename}}]},
                CATEGORY_TAG_PROPERTY: {"multi_select": [{"name": note.category_tag}]},
                STATUS_PROPERTY: {"select": {"name": DEFAULT_STATUS}},
            },
            children=build_page_children(note, transcript),
        )
    except Exception as exc:
        return NotionWriteResult(success=False, error=str(exc))

    return NotionWriteResult(success=True, page_id=page["id"])
