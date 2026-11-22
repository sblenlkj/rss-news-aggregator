"""Probe public RSS feeds through the application's real HTTP reader.

Usage: uv run python scripts/check_rss.py
No SQLite writes, no users or sources created.
"""

import asyncio
from dataclasses import dataclass

from news_aggregator.adapters.rss import FeedparserReader


@dataclass(frozen=True)
class Candidate:
    name: str
    url: str


CANDIDATES = (
    Candidate("МК — Наука (уже работал)", "https://www.mk.ru/rss/science/index.xml"),
    Candidate("МК — Все новости", "https://www.mk.ru/rss/index.xml"),
    Candidate("Хабр — Все статьи", "https://habr.com/ru/rss/articles/"),
    Candidate("Хабр — IT новости", "https://habr.com/ru/rss/news/"),
    Candidate("Коммерсантъ — основной, canonical", "https://www.kommersant.ru/rss/main.xml"),
    Candidate("Коммерсантъ — Наука, canonical", "https://www.kommersant.ru/rss/science.xml"),
    Candidate("РИА Новости", "https://ria.ru/export/rss2/index.xml"),
)


async def probe(item: Candidate) -> None:
    try:
        parsed = await FeedparserReader().fetch(item.url)
    except Exception as exc:
        print(f"FAIL | {item.name} | {type(exc).__name__}: {str(exc)[:130]}")
    else:
        print(f" OK  | {item.name} | articles={len(parsed.articles)} | {item.url}")


async def main() -> None:
    print("Checking RSS with the same FeedparserReader used by the app. No DB changes.")
    # Probe concurrently so that timeouts do not accumulate sequentially.
    await asyncio.gather(*(probe(item) for item in CANDIDATES))


if __name__ == "__main__":
    asyncio.run(main())
