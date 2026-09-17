import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class FormatSegmentsWithTimestampsTests(unittest.TestCase):
    def test_segments_rendered_as_mm_ss_prefixed_lines(self):
        from interview_agent import format_segments_with_timestamps

        segments = [
            {"start": 0.0, "end": 3.0, "text": "哈囉大家好"},
            {"start": 75.4, "end": 80.0, "text": "我們開始訪談"},
        ]
        rendered = format_segments_with_timestamps(segments)
        self.assertEqual(rendered, "[00:00] 哈囉大家好\n[01:15] 我們開始訪談")

    def test_segment_with_speaker_label_renders_speaker_prefix(self):
        """Segment Speaker Labels When Diarization Enabled / Speaker-Labeled
        Timestamped Evidence: when a segment carries a speaker letter, the
        rendered line includes it between the timestamp and the text."""
        from interview_agent import format_segments_with_timestamps

        segments = [
            {"start": 0.0, "end": 3.0, "text": "哈囉大家好", "speaker": "A"},
            {"start": 75.4, "end": 80.0, "text": "我們開始訪談", "speaker": "B"},
        ]
        rendered = format_segments_with_timestamps(segments)
        self.assertEqual(
            rendered, "[00:00][語者 A] 哈囉大家好\n[01:15][語者 B] 我們開始訪談"
        )

    def test_mixed_segments_with_and_without_speaker(self):
        from interview_agent import format_segments_with_timestamps

        segments = [
            {"start": 0.0, "end": 3.0, "text": "有語者標籤", "speaker": "A"},
            {"start": 5.0, "end": 8.0, "text": "沒有語者標籤"},
        ]
        rendered = format_segments_with_timestamps(segments)
        self.assertEqual(rendered, "[00:00][語者 A] 有語者標籤\n[00:05] 沒有語者標籤")


def _fake_message(stop_reason: str, tool_input: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.input = tool_input
    message = MagicMock()
    message.stop_reason = stop_reason
    message.content = [block]
    return message


class StructureInterviewToolCallTests(unittest.TestCase):
    """Interview-Specific Structured Analysis: Claude is called with the
    interview-shaped tool schema (summary/pain_points/highlights/
    usage_habits), never the meeting pipeline's key_points/action_items
    schema."""

    def test_calls_claude_with_interview_tool_schema_and_returns_note(self):
        import interview_agent

        payload = {
            "summary": "使用者對匯出流程感到困擾,但很喜歡新的搜尋功能。",
            "pain_points": [
                {"insight": "匯出報表流程太繁瑣", "quote": "我每次要匯出都要點三四層選單", "start_seconds": 192.0}
            ],
            "highlights": [
                {"insight": "搜尋功能很好用", "quote": "新的搜尋超快", "start_seconds": 30.0}
            ],
            "usage_habits": [
                {"insight": "每天早上都會先看儀表板", "quote": "我早上都會先看一下儀表板", "start_seconds": 5.0}
            ],
        }
        fake = _fake_message("tool_use", payload)
        client = MagicMock()
        client.messages.create.return_value = fake

        with patch.object(interview_agent.anthropic, "Anthropic", return_value=client):
            note = interview_agent.structure_interview(
                "[00:05] 我早上都會先看一下儀表板",
                source_filename="interview.mp4",
                recording_date="2026-09-01",
                api_key="key",
                segments=[{"start": 5.0, "end": 8.0, "text": "我早上都會先看一下儀表板"}],
            )

        call_kwargs = client.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["tool_choice"], {"type": "tool", "name": "return_structured_interview"})
        self.assertEqual(call_kwargs["tools"][0]["name"], "return_structured_interview")
        self.assertIn("[00:05]", call_kwargs["messages"][0]["content"])

        self.assertEqual(note.summary, payload["summary"])
        self.assertEqual(len(note.pain_points), 1)
        self.assertEqual(note.pain_points[0].insight, "匯出報表流程太繁瑣")
        self.assertEqual(note.pain_points[0].quote, "我每次要匯出都要點三四層選單")
        self.assertEqual(note.highlights[0].insight, "搜尋功能很好用")
        self.assertEqual(note.usage_habits[0].insight, "每天早上都會先看儀表板")

    def test_max_tokens_stop_reason_raises(self):
        import interview_agent

        fake = _fake_message("max_tokens", {"summary": "S"})
        client = MagicMock()
        client.messages.create.return_value = fake
        with patch.object(interview_agent.anthropic, "Anthropic", return_value=client):
            with self.assertRaises(RuntimeError):
                interview_agent.structure_interview(
                    "轉錄文字", "a.mp4", "2026-09-01", "key", segments=[]
                )

    def test_summary_containing_leaked_json_raises(self):
        """Regression (production 2026-09-17, Nathan interview): a malformed
        tool call left the usage_habits array's raw JSON text appended to the
        summary string instead of being parsed as its own field, so the page
        showed a summary block ending in literal `","usage_habits":[{...}]`
        and a silently-empty 使用者使用習慣 section. Must raise instead of
        writing the corrupted text into Notion."""
        import interview_agent

        payload = {
            "summary": (
                '受訪者對平台高度肯定,期待未來持續優化。","usage_habits":'
                '[{"insight":"日常使用","quote":"我常用","start_seconds":420}]'
            ),
            "pain_points": [],
            "highlights": [],
        }
        fake = _fake_message("tool_use", payload)
        client = MagicMock()
        client.messages.create.return_value = fake
        with patch.object(interview_agent.anthropic, "Anthropic", return_value=client):
            with self.assertRaises(RuntimeError):
                interview_agent.structure_interview(
                    "轉錄文字", "a.mp4", "2026-09-01", "key", segments=[]
                )

    def test_normal_length_summary_parses_normally(self):
        import interview_agent

        payload = {
            "summary": "使用者對匯出流程感到困擾,但很喜歡新的搜尋功能。",
            "pain_points": [],
            "highlights": [],
            "usage_habits": [],
        }
        fake = _fake_message("tool_use", payload)
        client = MagicMock()
        client.messages.create.return_value = fake
        with patch.object(interview_agent.anthropic, "Anthropic", return_value=client):
            note = interview_agent.structure_interview(
                "轉錄文字", "a.mp4", "2026-09-01", "key", segments=[]
            )
        self.assertEqual(note.summary, payload["summary"])


class ParseStructuredInterviewTests(unittest.TestCase):
    """Tolerant parsing of Claude's tool payload: missing/malformed fields
    degrade gracefully instead of raising, matching notion_agent.py's
    tolerant parser philosophy for the meeting pipeline."""

    def test_missing_summary_defaults_to_empty_string(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {"pain_points": [], "highlights": [], "usage_habits": []}, segments=[]
        )
        self.assertEqual(note.summary, "")

    def test_finding_missing_quote_is_dropped(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "沒有引用原文"}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=[],
        )
        self.assertEqual(note.pain_points, [])

    def test_finding_missing_insight_is_dropped(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"quote": "有引用但沒有分析文字", "start_seconds": 1.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=[],
        )
        self.assertEqual(note.pain_points, [])

    def test_non_list_field_becomes_empty_list(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {"summary": "S", "pain_points": "not a list", "highlights": [], "usage_habits": []},
            segments=[],
        )
        self.assertEqual(note.pain_points, [])

    def test_well_formed_findings_are_preserved(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "痛點", "quote": "原話", "start_seconds": 10.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=[{"start": 9.0, "end": 11.0, "text": "原話"}],
        )
        self.assertEqual(len(note.pain_points), 1)
        self.assertEqual(note.pain_points[0].start_seconds, 9.0)


class StartSecondsValidationTests(unittest.TestCase):
    """Timestamped Evidence For Each Finding (second scenario): a
    start_seconds outside every real transcript segment degrades to no
    timestamp, but the quote and insight are still kept -- the finding's
    processing must never fail because of a hallucinated timestamp."""

    def setUp(self):
        self.segments = [
            {"start": 0.0, "end": 5.0, "text": "a"},
            {"start": 5.0, "end": 10.0, "text": "b"},
        ]

    def test_start_seconds_within_a_segment_is_kept(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "x", "quote": "y", "start_seconds": 7.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=self.segments,
        )
        # start_seconds resolves to the matched segment's own (real) start
        # time, not the raw claimed number -- both floor to the same
        # displayed [MM:SS], and the segment is also the source of `speaker`.
        # 7.0 falls in both segments' tolerance-widened ranges; the first
        # (earlier) match wins.
        self.assertEqual(note.pain_points[0].start_seconds, 0.0)

    def test_start_seconds_outside_all_segments_degrades_to_none(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "x", "quote": "y", "start_seconds": 999.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=self.segments,
        )
        self.assertEqual(len(note.pain_points), 1)
        self.assertIsNone(note.pain_points[0].start_seconds)
        self.assertEqual(note.pain_points[0].quote, "y")
        self.assertEqual(note.pain_points[0].insight, "x")

    def test_start_seconds_slightly_before_segment_start_within_tolerance_is_kept(self):
        """Regression: format_segments_with_timestamps floors each segment's
        start to a whole second for the [MM:SS] label shown to Claude (e.g.
        a segment truly starting at 1196.8s is labeled "19:56"). When Claude
        echoes that label back as exactly 1196.0 seconds, the value lands
        just *before* the segment's real start and must not be rejected as
        a near-miss caused by our own floor-rounded display."""
        from interview_agent import parse_structured_interview

        segments = [{"start": 1196.8, "end": 1200.0, "text": "y"}]
        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "x", "quote": "y", "start_seconds": 1196.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=segments,
        )
        # Resolves to the segment's real (fractional) start, not the
        # floor-rounded number Claude echoed back -- both display as the
        # same [MM:SS] ("19:56").
        self.assertEqual(note.pain_points[0].start_seconds, 1196.8)

    def test_quote_text_match_recovers_timestamp_when_start_seconds_is_wrong(self):
        """When Claude's self-reported start_seconds does not correspond to
        any real segment at all (not just a rounding near-miss), but the
        quote text genuinely appears in one of the transcript segments, the
        segment's real start time is recovered by matching the quote text
        instead of trusting the (wrong) number."""
        from interview_agent import parse_structured_interview

        segments = [
            {"start": 0.0, "end": 5.0, "text": "哈囉大家好"},
            {"start": 1500.0, "end": 1510.0, "text": "他最basic的那個contact greater跟mix and match的方面我覺得是好用的"},
        ]
        note = parse_structured_interview(
            {
                "summary": "S",
                "highlights": [
                    {
                        "insight": "喜歡基本功能",
                        "quote": "他最basic的那個contact greater跟mix and match的方面我覺得是好用的",
                        "start_seconds": 99999.0,
                    }
                ],
                "pain_points": [],
                "usage_habits": [],
            },
            segments=segments,
        )
        self.assertEqual(note.highlights[0].start_seconds, 1500.0)

    def test_quote_with_no_textual_match_and_bad_number_degrades_to_none(self):
        from interview_agent import parse_structured_interview

        segments = [{"start": 0.0, "end": 5.0, "text": "完全不相關的內容"}]
        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "x", "quote": "從未出現過的引用句子", "start_seconds": 999.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=segments,
        )
        self.assertIsNone(note.pain_points[0].start_seconds)

    def test_no_segments_available_degrades_every_timestamp_to_none(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "x", "quote": "y", "start_seconds": 1.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=[],
        )
        self.assertIsNone(note.pain_points[0].start_seconds)


class SpeakerLabelPropagationTests(unittest.TestCase):
    """Speaker-Labeled Timestamped Evidence: when the segment a finding's
    timestamp resolves to carries a speaker label, that label is carried
    onto the InterviewFinding; segments without one leave speaker as None."""

    def test_matched_segment_with_speaker_sets_finding_speaker(self):
        from interview_agent import parse_structured_interview

        segments = [{"start": 0.0, "end": 5.0, "text": "y", "speaker": "A"}]
        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "x", "quote": "y", "start_seconds": 2.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=segments,
        )
        self.assertEqual(note.pain_points[0].speaker, "A")

    def test_matched_segment_without_speaker_leaves_none(self):
        from interview_agent import parse_structured_interview

        segments = [{"start": 0.0, "end": 5.0, "text": "y"}]
        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "x", "quote": "y", "start_seconds": 2.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=segments,
        )
        self.assertIsNone(note.pain_points[0].speaker)

    def test_quote_text_fallback_match_also_carries_speaker(self):
        from interview_agent import parse_structured_interview

        segments = [{"start": 100.0, "end": 105.0, "text": "獨特的引用句子", "speaker": "B"}]
        note = parse_structured_interview(
            {
                "summary": "S",
                "highlights": [
                    {"insight": "x", "quote": "獨特的引用句子", "start_seconds": 99999.0}
                ],
                "pain_points": [],
                "usage_habits": [],
            },
            segments=segments,
        )
        self.assertEqual(note.highlights[0].start_seconds, 100.0)
        self.assertEqual(note.highlights[0].speaker, "B")

    def test_no_match_leaves_speaker_none(self):
        from interview_agent import parse_structured_interview

        note = parse_structured_interview(
            {
                "summary": "S",
                "pain_points": [{"insight": "x", "quote": "從未出現過的句子", "start_seconds": 999.0}],
                "highlights": [],
                "usage_habits": [],
            },
            segments=[{"start": 0.0, "end": 5.0, "text": "完全不相關", "speaker": "A"}],
        )
        self.assertIsNone(note.pain_points[0].speaker)


class BuildInterviewPageChildrenTests(unittest.TestCase):
    """Timestamped Evidence For Each Finding: each finding renders as a
    bulleted insight followed immediately by a quote block citing the
    transcript excerpt, prefixed with its timestamp when one is valid."""

    def _note(self, **overrides):
        from interview_agent import InterviewFinding, InterviewNote

        defaults = dict(summary="這是訪談摘要", pain_points=[], highlights=[], usage_habits=[])
        defaults.update(overrides)
        return InterviewNote(**defaults)

    def test_summary_is_first_block(self):
        from interview_agent import build_interview_page_children

        children = build_interview_page_children(self._note(), transcript="逐字稿")
        self.assertEqual(children[0]["type"], "paragraph")
        self.assertEqual(
            children[0]["paragraph"]["rich_text"][0]["text"]["content"], "這是訪談摘要"
        )

    def test_finding_with_valid_timestamp_renders_bullet_then_quote(self):
        from interview_agent import InterviewFinding, build_interview_page_children

        note = self._note(
            pain_points=[
                InterviewFinding(
                    insight="匯出報表流程太繁瑣",
                    quote="我每次要匯出都要點三四層選單才找得到",
                    start_seconds=192.0,
                )
            ]
        )
        children = build_interview_page_children(note, transcript="逐字稿")

        headings = [c for c in children if c["type"] == "heading_3"]
        self.assertEqual(headings[0]["heading_3"]["rich_text"][0]["text"]["content"], "痛點")

        bullet_index = next(
            i for i, c in enumerate(children)
            if c["type"] == "bulleted_list_item"
            and c["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "匯出報表流程太繁瑣"
        )
        quote_block = children[bullet_index + 1]
        self.assertEqual(quote_block["type"], "quote")
        self.assertEqual(
            quote_block["quote"]["rich_text"][0]["text"]["content"],
            "[03:12]「我每次要匯出都要點三四層選單才找得到」",
        )

    def test_finding_with_speaker_renders_speaker_between_timestamp_and_quote(self):
        from interview_agent import InterviewFinding, build_interview_page_children

        note = self._note(
            highlights=[
                InterviewFinding(
                    insight="喜歡基本功能",
                    quote="他最basic的那個功能我覺得是好用的",
                    start_seconds=1500.0,
                    speaker="A",
                )
            ]
        )
        children = build_interview_page_children(note, transcript="逐字稿")
        quote_blocks = [c for c in children if c["type"] == "quote"]
        self.assertEqual(
            quote_blocks[0]["quote"]["rich_text"][0]["text"]["content"],
            "[25:00][語者 A]「他最basic的那個功能我覺得是好用的」",
        )

    def test_finding_with_speaker_but_no_timestamp_omits_speaker_too(self):
        """A finding with no valid timestamp has no segment to attribute a
        speaker to either -- speaker only ever appears alongside a
        timestamp, never on its own."""
        from interview_agent import InterviewFinding, build_interview_page_children

        note = self._note(
            highlights=[
                InterviewFinding(insight="x", quote="超快", start_seconds=None, speaker=None)
            ]
        )
        children = build_interview_page_children(note, transcript="逐字稿")
        quote_blocks = [c for c in children if c["type"] == "quote"]
        self.assertEqual(quote_blocks[0]["quote"]["rich_text"][0]["text"]["content"], "「超快」")

    def test_finding_without_valid_timestamp_omits_prefix(self):
        from interview_agent import InterviewFinding, build_interview_page_children

        note = self._note(
            highlights=[InterviewFinding(insight="搜尋很好用", quote="超快", start_seconds=None)]
        )
        children = build_interview_page_children(note, transcript="逐字稿")
        quote_blocks = [c for c in children if c["type"] == "quote"]
        self.assertEqual(quote_blocks[0]["quote"]["rich_text"][0]["text"]["content"], "「超快」")

    def test_empty_finding_category_emits_no_heading(self):
        from interview_agent import build_interview_page_children

        children = build_interview_page_children(self._note(), transcript="逐字稿")
        headings = [c["heading_3"]["rich_text"][0]["text"]["content"] for c in children if c["type"] == "heading_3"]
        self.assertEqual(headings, [])

    def test_transcript_is_wrapped_in_collapsed_toggle(self):
        from interview_agent import build_interview_page_children

        children = build_interview_page_children(self._note(), transcript="完整訪談逐字稿內容")
        toggles = [c for c in children if c["type"] == "toggle"]
        self.assertEqual(len(toggles), 1)
        self.assertEqual(toggles[0]["toggle"]["rich_text"][0]["text"]["content"], "完整逐字稿")


class BuildInterviewPagePropertiesTests(unittest.TestCase):
    """Interview Notion Page Category Tag: the page is created with the
    dedicated "訪談" category, independent of any network call."""

    def test_properties_include_interview_category_tag(self):
        from interview_agent import build_interview_page_properties
        from notion_schema import INTERVIEW_CATEGORY_TAG

        properties = build_interview_page_properties("interview.mp4", "2026-09-01")
        self.assertEqual(
            properties["分類標籤"]["multi_select"], [{"name": INTERVIEW_CATEGORY_TAG}]
        )
        self.assertEqual(properties["來源檔名"]["rich_text"][0]["text"]["content"], "interview.mp4")
        self.assertEqual(properties["日期"]["date"]["start"], "2026-09-01")


class CreateInterviewPageFailureTests(unittest.TestCase):
    def test_invalid_credentials_return_failure_without_raising(self):
        from interview_agent import InterviewNote, create_interview_page

        note = InterviewNote(summary="摘要", pain_points=[], highlights=[], usage_habits=[])
        result = create_interview_page(
            note,
            transcript="逐字稿",
            source_filename="test.mp4",
            recording_date="2026-09-01",
            database_id="00000000000000000000000000000000",
            notion_api_key="ntn_invalid_token_for_testing",
        )
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        self.assertIsNone(result.page_id)


if __name__ == "__main__":
    unittest.main()
