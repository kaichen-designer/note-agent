"""Shared Notion database schema constants.

Used by both the one-time setup script (creates the database with these
property names/options) and the note-writing path (writes pages using the
same names/options), so the two can never drift out of sync.
"""

TITLE_PROPERTY = "標題"
DATE_PROPERTY = "日期"
SOURCE_FILENAME_PROPERTY = "來源檔名"
CATEGORY_TAG_PROPERTY = "分類標籤"
STATUS_PROPERTY = "狀態"

# "其他" must stay the LAST entry: notion_agent.py's tolerant parser falls
# back to CATEGORY_TAG_OPTIONS[-1] for an invalid/missing category, so
# INTERVIEW_CATEGORY_TAG is inserted before it, not appended after.
INTERVIEW_CATEGORY_TAG = "訪談"
CATEGORY_TAG_OPTIONS = ["會議", "靈感", "學習", INTERVIEW_CATEGORY_TAG, "其他"]

# The meeting structuring tool must never offer 訪談 as a selectable
# category for Claude -- interviews are routed through interview_agent.py
# entirely, so a meeting recording being tagged 訪談 would be a mistake, not
# a legitimate choice.
MEETING_CATEGORY_TAG_OPTIONS = [tag for tag in CATEGORY_TAG_OPTIONS if tag != INTERVIEW_CATEGORY_TAG]

STATUS_OPTIONS = ["待處理", "已整理", "已完成"]
DEFAULT_STATUS = "已整理"
