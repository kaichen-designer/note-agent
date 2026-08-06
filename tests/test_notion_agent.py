import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from notion_agent import StructuredNote, _chunk_text, build_page_children, create_notion_page


class ChunkTextTests(unittest.TestCase):
    def test_short_text_is_single_chunk(self):
        self.assertEqual(_chunk_text("hello"), ["hello"])

    def test_empty_text_yields_one_empty_chunk(self):
        self.assertEqual(_chunk_text(""), [""])

    def test_long_text_is_split_into_multiple_chunks(self):
        text = "a" * 5000
        chunks = _chunk_text(text, chunk_size=1900)
        self.assertEqual(len(chunks), 3)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 1900 for chunk in chunks))


class BuildPageChildrenTests(unittest.TestCase):
    def test_transcript_is_wrapped_in_collapsed_toggle_block(self):
        note = StructuredNote(
            title="測試標題",
            summary="這是摘要",
            key_points=["重點一", "重點二"],
            action_items=["待辦一"],
            category_tag="會議",
        )
        children = build_page_children(note, "完整逐字稿內容")

        toggle_blocks = [c for c in children if c["type"] == "toggle"]
        self.assertEqual(len(toggle_blocks), 1)
        toggle = toggle_blocks[0]["toggle"]
        self.assertEqual(toggle["rich_text"][0]["text"]["content"], "完整逐字稿")
        transcript_text = "".join(
            block["paragraph"]["rich_text"][0]["text"]["content"] for block in toggle["children"]
        )
        self.assertEqual(transcript_text, "完整逐字稿內容")

        bullet_texts = [
            b["bulleted_list_item"]["rich_text"][0]["text"]["content"]
            for b in children
            if b["type"] == "bulleted_list_item"
        ]
        self.assertEqual(bullet_texts, ["重點一", "重點二", "待辦一"])


class CreateNotionPageFailureTests(unittest.TestCase):
    def test_invalid_credentials_return_failure_without_raising(self):
        note = StructuredNote(
            title="測試",
            summary="摘要",
            key_points=[],
            action_items=[],
            category_tag="其他",
        )
        result = create_notion_page(
            note,
            transcript="逐字稿",
            source_filename="test.m4a",
            recording_date="2026-07-04",
            database_id="00000000000000000000000000000000",
            notion_api_key="ntn_invalid_token_for_testing",
        )
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        self.assertIsNone(result.page_id)


class ParseStructuredNoteTests(unittest.TestCase):
    """Robust parsing of Claude's tool payload: missing fields degrade to
    defaults instead of raising (regression: production KeyError on
    'action_items' burned a retry after a 37-minute transcription)."""

    def test_missing_action_items_defaults_to_empty_list(self):
        from notion_agent import parse_structured_note

        note = parse_structured_note(
            {"title": "T", "summary": "S", "key_points": ["a"], "category_tag": "會議"},
            fallback_title="fallback.m4a",
            transcript="逐字稿",
        )
        self.assertEqual(note.action_items, [])
        self.assertEqual(note.title, "T")

    def test_all_fields_missing_uses_fallbacks(self):
        from notion_agent import parse_structured_note

        note = parse_structured_note({}, fallback_title="rec.m4a", transcript="內容" * 200)
        self.assertEqual(note.title, "rec.m4a")
        self.assertTrue(note.summary)
        self.assertLessEqual(len(note.summary), 200)
        self.assertEqual(note.key_points, [])
        self.assertEqual(note.action_items, [])
        self.assertEqual(note.category_tag, "其他")

    def test_invalid_category_falls_back_to_other(self):
        from notion_agent import parse_structured_note

        note = parse_structured_note(
            {"title": "T", "summary": "S", "key_points": [], "action_items": [], "category_tag": "不存在的標籤"},
            fallback_title="x.m4a",
            transcript="t",
        )
        self.assertEqual(note.category_tag, "其他")


class TruncationRejectionTests(unittest.TestCase):
    """Truncated Structuring Output Rejection: a max_tokens-truncated
    response must raise (marking the file failed for retry), never be
    silently accepted as a partial note."""

    def _fake_message(self, stop_reason, tool_input):
        from unittest.mock import MagicMock

        block = MagicMock()
        block.type = "tool_use"
        block.input = tool_input
        message = MagicMock()
        message.stop_reason = stop_reason
        message.content = [block]
        return message

    def test_max_tokens_stop_reason_raises(self):
        from unittest.mock import MagicMock, patch

        import notion_agent

        fake = self._fake_message("max_tokens", {"title": "T"})
        client = MagicMock()
        client.messages.create.return_value = fake
        with patch.object(notion_agent.anthropic, "Anthropic", return_value=client):
            with self.assertRaises(RuntimeError):
                notion_agent.structure_note("逐字稿", "a.m4a", "2026-07-06", "key")

    def test_complete_response_parses_normally(self):
        from unittest.mock import MagicMock, patch

        import notion_agent

        payload = {
            "title": "T", "summary": "S", "key_points": ["k"],
            "action_items": ["a"], "category_tag": "會議",
        }
        fake = self._fake_message("tool_use", payload)
        client = MagicMock()
        client.messages.create.return_value = fake
        with patch.object(notion_agent.anthropic, "Anthropic", return_value=client):
            note = notion_agent.structure_note("逐字稿", "a.m4a", "2026-07-06", "key")
        self.assertEqual(note.title, "T")
        self.assertEqual(note.action_items, ["a"])


class StringShapedListTests(unittest.TestCase):
    """Regression: the model sometimes returns array fields as one string of
    <item> chunks (observed in production 2026-07-06); the parser must
    recover the items instead of silently dropping them."""

    def test_item_tagged_string_is_recovered(self):
        from notion_agent import parse_structured_note

        note = parse_structured_note(
            {
                "title": "T", "summary": "S",
                "key_points": "\n<item>重點一</item>\n<item>重點二</item>",
                "action_items": "<item>待辦一</item>",
                "category_tag": "會議",
            },
            fallback_title="x.m4a",
            transcript="t",
        )
        self.assertEqual(note.key_points, ["重點一", "重點二"])
        self.assertEqual(note.action_items, ["待辦一"])

    def test_plain_multiline_string_splits_on_lines(self):
        from notion_agent import parse_structured_note

        note = parse_structured_note(
            {"title": "T", "summary": "S", "key_points": "- 重點一\n- 重點二", "action_items": [], "category_tag": "學習"},
            fallback_title="x.m4a",
            transcript="t",
        )
        self.assertEqual(note.key_points, ["重點一", "重點二"])

    def test_parameter_wrapped_json_array_is_recovered(self):
        """Regression: the model sometimes leaks its own tool-call-like
        markup as the field value instead of a real array (observed in
        production 2026-07-16, e.g. `<parameter name="items">["a","b"]`
        with no closing tag). The literal JSON array embedded in the
        string must be recovered rather than treated as one giant line."""
        from notion_agent import parse_structured_note

        note = parse_structured_note(
            {
                "title": "T", "summary": "S",
                "key_points": '<parameter name="items">["重點一","重點二"]',
                "action_items": '<parameter name="items">["待辦一","待辦二"]</parameter>',
                "category_tag": "學習",
            },
            fallback_title="x.m4a",
            transcript="t",
        )
        self.assertEqual(note.key_points, ["重點一", "重點二"])
        self.assertEqual(note.action_items, ["待辦一", "待辦二"])

    def test_list_wrapped_li_tagged_string_is_recovered(self):
        """Regression: the model sometimes wraps <li> items in a <list>
        container instead of <item> tags (observed in production
        2026-08-06); the wrapper tags must not become bogus list items."""
        from notion_agent import parse_structured_note

        note = parse_structured_note(
            {
                "title": "T", "summary": "S",
                "key_points": "<list>\n<li>重點一</li>\n<li>重點二</li>\n</list>",
                "action_items": "<list>\n<li>待辦一</li>\n</list>",
                "category_tag": "會議",
            },
            fallback_title="x.m4a",
            transcript="t",
        )
        self.assertEqual(note.key_points, ["重點一", "重點二"])
        self.assertEqual(note.action_items, ["待辦一"])


if __name__ == "__main__":
    unittest.main()
