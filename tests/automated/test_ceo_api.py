"""Tests cho API của LinkedIn CEO Finder tích hợp trong FastAPI app."""

from unittest.mock import patch
from fastapi.testclient import TestClient
from crawler.api.app import app
from crawler.api.config import settings
from linkedin_ceo_finder.models import CEOLead

client = TestClient(app)
VALID_HEADERS = {"X-API-Key": settings.CRON_API_KEY}


def test_ceo_health_endpoint_is_public():
    """Kiểm tra endpoint GET /api/v1/ceo/health hoạt động công khai không cần API key."""
    response = client.get("/api/v1/ceo/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "linkedin-ceo-finder"
    assert "sheet_configured" in data
    assert "service_account_configured" in data


def test_search_by_domains_requires_api_key():
    """Kiểm tra POST /api/v1/ceo/domains bắt buộc có X-API-Key."""
    payload = {"domains": ["google.com"]}
    res_no_key = client.post("/api/v1/ceo/domains", json=payload)
    assert res_no_key.status_code == 401

    res_bad_key = client.post("/api/v1/ceo/domains", json=payload, headers={"X-API-Key": "wrong-key"})
    assert res_bad_key.status_code == 401


def test_search_by_domains_async_running_for_cron():
    """Kiểm tra POST /api/v1/ceo/domains mặc định trả về 'running' cho cron-job."""
    payload = {
        "domains": ["google.com", "nvidia.com"],
        "save_to_sheet": True,
    }
    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_domains") as mock_func:
        response = client.post("/api/v1/ceo/domains", json=payload, headers=VALID_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "job_id" in data
        assert data["mode"] == "domains"
        assert data["save_to_sheet"] is True
        # Background task được trigger sau response trong test client
        mock_func.assert_called_once()


def test_search_by_domains_sync_mode():
    """Kiểm tra POST /api/v1/ceo/domains với sync=True trả về kết quả ngay."""
    mock_leads = [
        CEOLead(
            name="Sundar Pichai",
            role="CEO",
            keyword="Domain: google.com",
            company="Google",
            linkedin_link="https://www.linkedin.com/in/sundarpichai",
            updated_at="2026-09-28 12:00:00",
        )
    ]
    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_domains", return_value=mock_leads):
        payload = {
            "domains": ["google.com"],
            "sync": True,
            "save_to_sheet": False,
        }
        response = client.post("/api/v1/ceo/domains", json=payload, headers=VALID_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_found"] == 1
        assert data["leads"][0]["name"] == "Sundar Pichai"


def test_search_by_keyword_async_running_for_cron():
    """Kiểm tra POST /api/v1/ceo/keyword mặc định trả về 'running' cho cron-job."""
    payload = {
        "keyword": "Fintech Vietnam",
        "target_count": 5,
        "save_to_sheet": True,
    }
    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_keyword") as mock_func:
        response = client.post("/api/v1/ceo/keyword", json=payload, headers=VALID_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "job_id" in data
        assert data["mode"] == "keyword"
        assert data["target"] == "Fintech Vietnam"
        mock_func.assert_called_once()


def test_search_by_keyword_sync_mode():
    """Kiểm tra POST /api/v1/ceo/keyword với sync=True trả về kết quả đầy đủ."""
    mock_leads = [
        CEOLead(
            name="Nguyen Van A",
            role="Founder & CEO",
            keyword="Fintech Vietnam",
            company="FinTech Asia",
            linkedin_link="https://www.linkedin.com/in/nguyenvana",
            updated_at="2026-09-28 12:05:00",
        )
    ]
    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_keyword", return_value=mock_leads):
        payload = {
            "keyword": "Fintech Vietnam",
            "sync": True,
        }
        response = client.post("/api/v1/ceo/keyword", json=payload, headers=VALID_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_found"] == 1
        assert data["leads"][0]["role"] == "Founder & CEO"


def test_quick_search_async_and_sync():
    """Kiểm tra GET /api/v1/ceo/quick-search cả 2 chế độ async và sync."""
    # 1. Mặc định: running
    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_keyword"):
        res = client.get("/api/v1/ceo/quick-search?keyword=AI", headers=VALID_HEADERS)
        assert res.status_code == 200
        assert res.json()["status"] == "running"

    # 2. sync=True: trả về leads
    mock_leads = [
        CEOLead(
            name="Jane Doe",
            role="CEO",
            keyword="AI",
            company="Open Tech",
            linkedin_link="https://www.linkedin.com/in/janedoe",
            updated_at="2026-09-28 12:10:00",
        )
    ]
    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_keyword", return_value=mock_leads):
        res_sync = client.get("/api/v1/ceo/quick-search?keyword=AI&sync=true", headers=VALID_HEADERS)
        assert res_sync.status_code == 200
        assert res_sync.json()["success"] is True
        assert res_sync.json()["total_found"] == 1


def test_search_by_multiple_keywords_and_workers():
    """Kiểm tra POST /api/v1/ceo/keyword hỗ trợ danh sách nhiều keywords và max_workers giống như domain."""
    mock_leads = [
        CEOLead(name="CEO 1", role="CEO", keyword="Fintech", company="A", linkedin_link="https://li/1"),
        CEOLead(name="CEO 2", role="Founder", keyword="AI", company="B", linkedin_link="https://li/2"),
    ]
    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_keyword", return_value=mock_leads) as mock_find:
        payload = {
            "keywords": ["Fintech Vietnam", "AI Vietnam"],
            "target_count": 3,
            "max_workers": 4,
            "save_to_sheet": True,
            "sync": True,
        }
        response = client.post("/api/v1/ceo/keyword", json=payload, headers=VALID_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_found"] == 2
        mock_find.assert_called_once()
        _, kwargs = mock_find.call_args
        assert kwargs["keywords"] == ["Fintech Vietnam", "AI Vietnam"]
        assert kwargs["max_workers"] == 4


def test_openapi_schema_contains_ceo_routes():
    """Đảm bảo OpenAPI documentation chứa các route của LinkedIn CEO Finder."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema["paths"]
    assert "/api/v1/ceo/health" in paths
    assert "/api/v1/ceo/domains" in paths
    assert "/api/v1/ceo/keyword" in paths
    assert "/api/v1/ceo/quick-search" in paths
