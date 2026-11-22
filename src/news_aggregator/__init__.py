"""RSS News Aggregator."""


def main() -> None:
    """Console entrypoint: uv run news-aggregator."""
    import uvicorn

    uvicorn.run("news_aggregator.main:app", host="127.0.0.1", port=8000)
