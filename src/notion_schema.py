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

CATEGORY_TAG_OPTIONS = ["會議", "靈感", "學習", "其他"]
STATUS_OPTIONS = ["待處理", "已整理", "已完成"]
DEFAULT_STATUS = "已整理"
