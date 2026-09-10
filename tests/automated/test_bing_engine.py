import pytest
from crawler.config import DEFAULT_PROVIDER
from crawler.discovery import (
    extract_bing_publisher_url,
    fetch_bing_rss,
    fetch_bing_rss_multi,
    discover_articles,
)
from crawler.network import create_session

def test_extract_bing_publisher_url():
    direct = "https://dantri.com.vn/kinh-doanh/bai-viet.htm"
    assert extract_bing_publisher_url(direct) == direct

    bing_click = "http://www.bing.com/news/apiclick.aspx?ref=BDG&aid=&tid=123&url=https%3A%2F%2Fvnexpress.net%2Fkinh-te%2Farticle.html&c=1"
    assert extract_bing_publisher_url(bing_click) == "https://vnexpress.net/kinh-te/article.html"

def test_fetch_bing_rss_live():
    with create_session() as session:
        articles = fetch_bing_rss("AI", max_articles=3, locale="vi", session=session)
        assert len(articles) > 0
        for art in articles:
            assert "title" in art
            assert "google_url" in art
            assert "publisher_url" in art
            assert art["publisher_url"].startswith("http")
            assert "news.google.com" not in art["publisher_url"]

def test_discover_articles_bing():
    with create_session() as session:
        articles = discover_articles("Semiconductor", max_articles=3, locales=[{"lang": "vi"}], provider="bing", session=session)
        assert len(articles) > 0
        for art in articles:
            assert art.get("publisher_url")
            assert "http" in art["publisher_url"]
