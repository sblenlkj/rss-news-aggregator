"""File-backed RSS 2.0 publisher for the classroom acceptance demo.

The HTTP endpoints (POST /api/v1/test-feed/articles and GET /test-feed/rss.xml)
will be wired to this adapter when the API layer is implemented.
"""

import json
import os
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

from news_aggregator.application.rss.models import TestFeedEntry
from news_aggregator.logger import get_logger

logger = get_logger(__name__)

_CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("content", _CONTENT_NS)


class FileTestFeedPublisher:
    """Persist entries as JSON and render a valid RSS feed on demand.

    Suitable for a single-process local demo; add synchronization or SQL-backed
    storage if concurrent publishers become necessary.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> list[TestFeedEntry]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [
            TestFeedEntry(
                id=UUID(item["id"]),
                title=item["title"],
                summary=item.get("summary", ""),
                content=item.get("content"),
                published_at=datetime.fromisoformat(item["published_at"]),
                tags=tuple(item.get("tags", ())),
            )
            for item in raw
        ]

    def publish(
        self, title: str, summary: str, tags: tuple[str, ...] = (),
        content: str | None = None,
    ) -> TestFeedEntry:
        if not title.strip():
            raise ValueError("Test article title cannot be empty")
        entry = TestFeedEntry(
            id=uuid4(),
            title=title.strip(),
            summary=summary.strip(),
            content=content.strip() if content and content.strip() else None,
            tags=tuple(tag.strip() for tag in tags if tag.strip()),
            published_at=datetime.now(UTC),
        )
        entries = [entry, *self._load()]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            [
                {
                    "id": str(item.id),
                    "title": item.title,
                    "summary": item.summary,
                    "content": item.content,
                    "tags": list(item.tags),
                    "published_at": item.published_at.isoformat(),
                }
                for item in entries
            ],
            ensure_ascii=False,
            indent=2,
        )
        tmp_name = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._path.parent,
                delete=False
            ) as temp:
                tmp_name = temp.name
                temp.write(content)
            os.replace(tmp_name, self._path)
        finally:
            if tmp_name is not None and os.path.exists(tmp_name):
                os.unlink(tmp_name)
        logger.info("Test RSS entry published id=%s total_entries=%d", entry.id, len(entries))
        return entry

    def render_xml(self, base_url: str) -> bytes:
        base = base_url.rstrip("/")
        root = ET.Element("rss", {"version": "2.0"})
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = "News Aggregator Test Feed"
        ET.SubElement(channel, "link").text = base + "/"
        ET.SubElement(channel, "description").text = "Local demonstration RSS feed"
        for entry in self._load():
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = entry.title
            ET.SubElement(item, "link").text = base + "/test-feed/articles/" + str(entry.id)
            guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
            guid.text = str(entry.id)
            if entry.summary:
                ET.SubElement(item, "description").text = entry.summary
            if entry.content:
                ET.SubElement(item, f"{{{_CONTENT_NS}}}encoded").text = entry.content
            ET.SubElement(item, "pubDate").text = format_datetime(
                entry.published_at.astimezone(UTC), usegmt=True
            )
            for tag in entry.tags:
                ET.SubElement(item, "category").text = tag
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
