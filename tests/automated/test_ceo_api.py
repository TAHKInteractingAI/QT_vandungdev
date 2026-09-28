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
    # Không có header
    res_no_key = client.post("/api/v1/ceo/domains", json=payload)
    assert res_no_key.status_code == 401

    # Key sai
    res_bad_key = client.post("/api/v1/ceo/domains", json=payload, headers={"X-API-Key": "wrong-key"})
    assert res_bad_key.status_code == 401


def test_search_by_domains_success_with_key():
    """Kiểm tra POST /api/v1/ceo/domains thành công khi có API key hợp lệ."""
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

    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_domains", return_value=mock_leads) as mock_func:
        payload = {
            "domains": ["google.com"],
            "save_to_sheet": False,
            "max_workers": 2,
        }
        response = client.post("/api/v1/ceo/domains", json=payload, headers=VALID_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_found"] == 1
        assert len(data["leads"]) == 1
        assert data["leads"][0]["name"] == "Sundar Pichai"
        assert data["leads"][0]["company"] == "Google"
        assert data["sheet_saved"] is False
        mock_func.assert_called_once()


def test_search_by_keyword_requires_api_key():
    """Kiểm tra POST /api/v1/ceo/keyword bắt buộc có X-API-Key."""
    payload = {"keyword": "Fintech Vietnam"}
    res_no_key = client.post("/api/v1/ceo/keyword", json=payload)
    assert res_no_key.status_code == 401


def test_search_by_keyword_success_with_key():
    """Kiểm tra POST /api/v1/ceo/keyword thành công với API key hợp lệ."""
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

    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_keyword", return_value=mock_leads) as mock_func:
        payload = {
            "keyword": "Fintech Vietnam",
            "target_count": 3,
            "save_to_sheet": False,
        }
        response = client.post("/api/v1/ceo/keyword", json=payload, headers=VALID_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_found"] == 1
        assert data["leads"][0]["role"] == "Founder & CEO"
        mock_func.assert_called_once()


def test_quick_search_requires_api_key():
    """Kiểm tra GET /api/v1/ceo/quick-search bắt buộc có API key."""
    res_no_key = client.get("/api/v1/ceo/quick-search?keyword=AI&count=1")
    assert res_no_key.status_code == 401

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

    # Kiểm tra xác thực qua header và qua query parameter key
    with patch("linkedin_ceo_finder.api.routes.find_ceos_by_keyword", return_value=mock_leads):
        res_header = client.get("/api/v1/ceo/quick-search?keyword=AI&count=1", headers=VALID_HEADERS)
        assert res_header.status_code == 200

        res_query = client.get(f"/api/v1/ceo/quick-search?keyword=AI&count=1&key={settings.CRON_API_KEY}")
        assert res_query.status_code == 200
        assert res_query.json()["total_found"] == 1


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
