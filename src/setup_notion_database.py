"""One-time setup: provision the Notion notes database schema.

Run this once during initial setup (see design.md Migration Plan). It is a
separate entry point from main.py -- the recurring scheduled/manual pipeline
never calls this, so it never re-checks or re-creates the database schema on
every run (see design.md decision on one-time provisioning).

Handles both first-time layouts:
- The user shared a regular page with the integration -> create a new notes
  database under that page.
- The user shared a database they created themselves -> ensure that database
  has the required schema (rename its title property and add the four
  properties), instead of creating a duplicate database.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from notion_client import Client

from notion_schema import (
    CATEGORY_TAG_OPTIONS,
    CATEGORY_TAG_PROPERTY,
    DATE_PROPERTY,
    SOURCE_FILENAME_PROPERTY,
    STATUS_OPTIONS,
    STATUS_PROPERTY,
    TITLE_PROPERTY,
)

DATABASE_TITLE = "錄音筆記"

_SCHEMA_PROPERTIES = {
    DATE_PROPERTY: {"date": {}},
    SOURCE_FILENAME_PROPERTY: {"rich_text": {}},
    CATEGORY_TAG_PROPERTY: {
        "multi_select": {"options": [{"name": tag} for tag in CATEGORY_TAG_OPTIONS]}
    },
    STATUS_PROPERTY: {"select": {"options": [{"name": status} for status in STATUS_OPTIONS]}},
}


def create_database(client: Client, parent_page_id: str) -> str:
    """Create the notes database under parent_page_id and return its ID."""
    response = client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": DATABASE_TITLE}}],
        properties={TITLE_PROPERTY: {"title": {}}, **_SCHEMA_PROPERTIES},
    )
    return response["id"]


def ensure_schema_on_existing(client: Client, data_source_id: str) -> str:
    """Patch an existing shared database's data source so it has the required
    schema: the title property renamed to the canonical name plus the four
    note properties. Returns the parent database ID used by page creation."""
    data_source = client.request(path=f"data_sources/{data_source_id}", method="GET")

    properties: dict = dict(_SCHEMA_PROPERTIES)
    for name, prop in data_source["properties"].items():
        if prop["type"] == "title" and name != TITLE_PROPERTY:
            properties[name] = {"name": TITLE_PROPERTY}

    client.request(
        path=f"data_sources/{data_source_id}",
        method="PATCH",
        body={"properties": properties},
    )
    return data_source["parent"]["database_id"]


def find_shared_target(client: Client) -> tuple[str, str] | None:
    """Find what the user shared with the integration. Returns
    ("data_source", id) if a database was shared, ("page", id) if a page was
    shared, or None if nothing is shared yet."""
    results = client.search()["results"]
    for item in results:
        if item["object"] == "data_source":
            return ("data_source", item["id"])
    for item in results:
        if item["object"] == "page":
            return ("page", item["id"])
    return None


def main() -> int:
    load_dotenv()
    api_key = os.environ.get("NOTION_API_KEY")
    existing_database_id = os.environ.get("NOTION_DATABASE_ID")

    if not api_key:
        print("錯誤:未設定 NOTION_API_KEY,請先在 .env 中填入 Notion Internal Integration Token")
        return 1

    if existing_database_id:
        print(f"NOTION_DATABASE_ID 已設定為 {existing_database_id},略過建立(如需重建請先清空該設定值)")
        return 0

    client = Client(auth=api_key)

    target = find_shared_target(client)
    if target is None:
        parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID")
        if parent_page_id:
            database_id = create_database(client, parent_page_id)
        else:
            print(
                "錯誤:這個 integration 目前沒有任何已分享的頁面或資料庫。\n"
                "請到 Notion 目標頁面右上角 ... -> 連結,加入這個 integration 後再執行一次。"
            )
            return 1
    elif target[0] == "data_source":
        print("偵測到已分享的現有資料庫,補齊 schema 而不另建新資料庫")
        database_id = ensure_schema_on_existing(client, target[1])
    else:
        print("偵測到已分享的頁面,在其底下建立新資料庫")
        database_id = create_database(client, target[1])

    print(f"Notion 筆記資料庫已就緒,ID: {database_id}")
    print("請將以上 ID 填入 .env 的 NOTION_DATABASE_ID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
