import pytest
from crawler.config import DEFAULT_PROVIDER
from crawler.discovery import (
    decode_publisher_url,
    discover_articles,
    fetch_rss_multi,
)
from crawler.network import create_session

def test_default_provider():
    assert DEFAULT_PROVIDER == "google"

def test_discover_articles_google():
    with create_session() as session:
        articles = discover_articles(
            "Bán dẫn",
            max_articles=3,
            locales=[{"lang": "vi", "country": "VN", "ceid": "VN:vi"}],
            session=session,
        )
        assert len(articles) > 0
        for art in articles:
            assert "title" in art
            assert "google_url" in art
            assert "news.google.com" in art["google_url"]

def test_decode_publisher_url_direct():
    direct_url = "https://vnexpress.net/kinh-doanh/bai-viet.html"
    url, status = decode_publisher_url(direct_url)
    assert url == direct_url
    assert status == "direct"
