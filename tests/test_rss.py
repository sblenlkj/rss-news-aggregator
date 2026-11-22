from datetime import UTC

import pytest

from news_aggregator.adapters.rss import parse_feed


def test_parse_rss_normalizes_title_summary_and_tags():
    xml = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Tech News</title>
      <link>https://example.org</link><description>News feed</description>
      <item><title>New AI model</title>
        <link>https://example.org/1</link><guid isPermaLink="false">story-1</guid>
        <description><![CDATA[<p>Interesting <b>research</b></p>]]></description>
        <category>AI</category><category>Research</category>
        <pubDate>Mon, 16 Nov 2026 08:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    parsed = parse_feed(xml, "https://example.org/rss")
    assert parsed.title == "Tech News"
    assert len(parsed.articles) == 1
    article = parsed.articles[0]
    assert article.external_id == "story-1"
    assert article.title == "New AI model"
    assert article.summary == "Interesting research"
    assert article.tags == ("AI", "Research")
    assert article.published_at.tzinfo == UTC
    assert article.search_text == "New AI model\nInteresting research\nAI Research"
    assert article.content is None


def test_parse_atom_with_missing_optional_fields():
    xml = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom demo</title><id>urn:feed:1</id>
      <entry><id>urn:item:1</id><title>Short update</title>
        <updated>2026-11-16T10:00:00Z</updated></entry>
    </feed>"""
    article = parse_feed(xml, "https://example.org/atom").articles[0]
    assert article.title == "Short update"
    # Optional fields are not required; feedparser may synthesize aliases
    # (for example from Atom id). Verify only the stable contract.
    assert article.external_id == "urn:item:1"
    assert article.published_at is not None


def test_invalid_feed_raises():
    with pytest.raises(ValueError, match="RSS/Atom"):
        parse_feed(b"<html><body>not a feed</body></html>", "https://example.org")


def test_rss_title_only_is_a_valid_article():
    xml = b"""<rss version="2.0"><channel><title>Short</title>
        <description>Short feed</description>
        <item><title>Only a heading</title><guid>42</guid></item>
    </channel></rss>"""
    article = parse_feed(xml, "https://example.org/rss").articles[0]
    assert article.title == "Only a heading"
    assert article.summary is None
    assert article.content is None
    assert article.search_text == "Only a heading"


def test_rss_summary_and_content_are_both_preserved():
    xml = b"""<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
    <channel><title>News</title><description>Feed</description>
      <item>
        <title>LLM</title>
        <description><![CDATA[<p>Short summary</p>]]></description>
        <content:encoded><![CDATA[<div>Full <b>article</b> about retrieval.</div>]]></content:encoded>
      </item>
    </channel></rss>"""
    article = parse_feed(xml, "https://example.org/rss").articles[0]
    assert article.summary == "Short summary"
    assert article.content == "Full article about retrieval."
    assert article.search_text == "LLM\nShort summary\nFull article about retrieval."


def test_rss_content_without_summary():
    xml = b"""<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
    <channel><title>News</title><description>Feed</description><item>
        <title>Update</title><content:encoded>Embedding improvements</content:encoded>
    </item></channel></rss>"""
    article = parse_feed(xml, "https://example.org/rss").articles[0]
    assert article.content == "Embedding improvements"
    # feedparser may expose content:encoded as summary in some feed variants;
    # in either case full text must be retained and searchable.
    assert "Embedding improvements" in article.search_text


def test_rss_duplicate_summary_and_content_kept_intentionally():
    xml = b"""<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
    <channel><title>News</title><description>Feed</description><item>
        <title>Same</title><description>Repeated text</description>
        <content:encoded>Repeated text</content:encoded>
    </item></channel></rss>"""
    article = parse_feed(xml, "https://example.org/rss").articles[0]
    assert article.summary == "Repeated text"
    assert article.content == "Repeated text"
    assert article.search_text.count("Repeated text") == 2


def test_atom_content_is_preserved():
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom</title><id>urn:feed:1</id>
      <entry><id>urn:item:1</id><title>New research</title>
      <summary>Brief</summary><content type="html">&lt;p&gt;Full text&lt;/p&gt;</content>
      </entry>
    </feed>"""
    article = parse_feed(xml, "https://example.org/atom").articles[0]
    assert article.summary == "Brief"
    assert article.content == "Full text"


def test_entry_with_content_but_no_title_gets_fallback_title():
    xml = b"""<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
    <channel><title>News</title><description>Feed</description><item>
      <guid>content-only</guid>
      <content:encoded>New research without item title</content:encoded>
    </item></channel></rss>"""
    article = parse_feed(xml, "https://example.org/rss").articles[0]
    assert article.title == "(без заголовка)"
    assert article.content == "New research without item title"
