"""One-off utility: convert an existing Notion page's text content from
whatever script whisper happened to decode (Simplified or Traditional
Chinese, unpredictable per recording) to Taiwan-style Traditional Chinese
(OpenCC s2twp), for interview pages created before the interview pipeline's
segment-text conversion bug was fixed (see design.md's "訪談"-related
diarization fixes -- the joined transcript string was normalized, but the
segment list interview mode actually reads from was not).

Walks the page's block tree recursively and updates each rich_text block's
content in place via the Notion API. Never touches page properties (title,
category tag, date, etc.) -- only the body content blocks.

Usage:
    python src/convert_page_to_traditional.py <page_id> [<page_id> ...]
    python src/convert_page_to_traditional.py --dry-run <page_id> [...]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # Force UTF-8 regardless of the invoking console's codepage (e.g. cp950
    # on Traditional Chinese Windows), which can't encode every character
    # OpenCC's output may contain.
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from notion_client import Client
from opencc import OpenCC

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Block types whose text content lives in a `rich_text` array nested under a
# key matching the block's own `type` value.
_RICH_TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "quote",
    "toggle",
    "callout",
}


def _convert_rich_text(rich_text: list[dict], converter: OpenCC) -> list[dict]:
    """Return a new rich_text array with each text run's content converted.
    Non-text rich_text items (mentions, equations) are passed through
    unchanged since they have no plain text content to convert."""
    converted = []
    for item in rich_text:
        item = dict(item)
        if item.get("type") == "text" and "text" in item:
            text_obj = dict(item["text"])
            text_obj["content"] = converter.convert(text_obj["content"])
            item["text"] = text_obj
        converted.append(item)
    return converted


def convert_block_tree(
    client: Client, block_id: str, converter: OpenCC, dry_run: bool = False
) -> int:
    """Recursively convert every rich_text block under block_id (not
    including block_id itself, matching Notion's children-listing API).
    Returns the number of blocks that were changed (or would be changed,
    in dry-run mode)."""
    changed = 0
    cursor: str | None = None
    while True:
        kwargs = {"start_cursor": cursor} if cursor else {}
        response = client.blocks.children.list(block_id, **kwargs)
        for block in response["results"]:
            block_type = block["type"]
            if block_type in _RICH_TEXT_BLOCK_TYPES:
                rich_text = block[block_type].get("rich_text", [])
                if rich_text:
                    new_rich_text = _convert_rich_text(rich_text, converter)
                    if new_rich_text != rich_text:
                        changed += 1
                        old_preview = "".join(
                            t.get("text", {}).get("content", "") for t in rich_text
                        )[:40]
                        new_preview = "".join(
                            t.get("text", {}).get("content", "") for t in new_rich_text
                        )[:40]
                        print(f"  [{'會改' if dry_run else '已改'}] {old_preview!r} -> {new_preview!r}")
                        if not dry_run:
                            client.blocks.update(block["id"], **{block_type: {"rich_text": new_rich_text}})
            if block.get("has_children"):
                changed += convert_block_tree(client, block["id"], converter, dry_run=dry_run)
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return changed


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    page_ids = [a for a in args if a != "--dry-run"]

    if not page_ids:
        print("用法: python src/convert_page_to_traditional.py [--dry-run] <page_id> [<page_id> ...]")
        return 1

    load_dotenv(PROJECT_ROOT / ".env")
    notion_api_key = os.environ.get("NOTION_API_KEY", "").strip()
    if not notion_api_key:
        print("尚未設定 NOTION_API_KEY。")
        return 1

    client = Client(auth=notion_api_key)
    converter = OpenCC("s2twp")

    for page_id in page_ids:
        print(f"處理頁面 {page_id}{'(dry-run)' if dry_run else ''}:")
        changed = convert_block_tree(client, page_id, converter, dry_run=dry_run)
        print(f"  共 {changed} 個區塊{'需要修改' if dry_run else '已更新'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
