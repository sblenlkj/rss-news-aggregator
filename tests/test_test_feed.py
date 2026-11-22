from xml.etree import ElementTree as ET

from news_aggregator.adapters.rss import parse_feed
from news_aggregator.adapters.test_feed import FileTestFeedPublisher


def test_publish_then_render_valid_rss_and_parse(tmp_path):
    publisher = FileTestFeedPublisher(tmp_path / "test-items.json")
    created = publisher.publish(
        title="New NLP approach",
        summary="News about embeddings",
        tags=("NLP", "research"),
    )
    publisher_again = FileTestFeedPublisher(tmp_path / "test-items.json")
    xml = publisher_again.render_xml("http://localhost:8000")
    root = ET.fromstring(xml)
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"

    feed = parse_feed(xml, "http://localhost:8000/test-feed/rss.xml")
    assert feed.articles[0].title == created.title
    assert feed.articles[0].summary == created.summary
    assert feed.articles[0].external_id == str(created.id)
    assert feed.articles[0].tags == ("NLP", "research")
    assert "embeddings" in feed.articles[0].search_text


def test_published_content_survives_json_xml_and_parser(tmp_path):
    path = tmp_path / "test-items.json"
    FileTestFeedPublisher(path).publish(
        title="New model",
        summary="Short introduction",
        content="<p>Full <b>technical</b> description</p>",
    )
    feed = FileTestFeedPublisher(path).render_xml("http://localhost:8000")
    item = parse_feed(feed, "http://localhost:8000/test-feed/rss.xml").articles[0]
    assert item.summary == "Short introduction"
    assert item.content == "Full technical description"
    assert "technical" in item.search_text


def test_publisher_accepts_title_only(tmp_path):
    publisher = FileTestFeedPublisher(tmp_path / "items.json")
    publisher.publish(title="Breaking news", summary="")
    feed = parse_feed(
        publisher.render_xml("http://localhost:8000"),
        "http://localhost:8000/test-feed/rss.xml",
    )
    assert feed.articles[0].title == "Breaking news"
    assert feed.articles[0].content is None
